/* FT AI Research panel — evidence-grounded multi-agent report UI.
   Loads independently (never blocks Overview/Charts/Financials). No chatbot:
   a structured research report with progress stages, grounding badges,
   sources and data gaps. Attaches via observers so existing views keep
   working even if this file fails to load. */
(function () {
  "use strict";
  var STAGES = [
    ["prepare", "Preparing market data"],
    ["market", "Market analysis"],
    ["fundamental", "Fundamental analysis"],
    ["news", "News analysis"],
    ["bull", "Bull / Bear research"],
    ["risk", "Risk analysis"],
    ["manager", "Final synthesis"],
  ];
  function $(id) { return document.getElementById(id); }
  function esc(s) {
    var F = window.FT_FMT;
    if (F && F.esc) return F.esc(s === null || s === undefined ? "" : String(s));
    return String(s === null || s === undefined ? "" : s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }
  function gBadge(g) {
    if (g === "grounded") return "<span class='pill pill-live'>GROUNDED</span>";
    if (g === "data_unavailable") return "<span class='pill pill-na'>DATA UNAVAILABLE</span>";
    return "<span class='pill pill-delayed'>UNVERIFIED</span>";
  }
  function stageHtml(state) {
    return "<ol class='ai-stages'>" + STAGES.map(function (s) {
      var st = (state && state[s[0]]) || "pending";
      var mark = st === "done" ? "&#10003;" : (st === "running" ? "&#9679;" : "&#9675;");
      return "<li class='ai-st-" + st + "'><span class='ai-dot'>" + mark + "</span> " + esc(s[1]) + "</li>";
    }).join("") + "</ol>";
  }
  function sectHtml(title, node, open) {
    if (!node) return "";
    var body = "";
    if (node.text) body += "<p class='ai-text'>" + esc(node.text).replace(/\n/g, "<br>") + "</p>";
    if (node.points && node.points.length) {
      body += "<ul class='ai-points'>" + node.points.map(function (p) { return "<li>" + esc(p) + "</li>"; }).join("") + "</ul>";
    }
    if (node.items && node.items.length) {
      body += "<div>" + node.items.map(function (n) {
        var t = n.url ? "<a href='" + esc(n.url) + "' target='_blank' rel='noopener'>" + esc(n.title || n.url) + "</a>" : esc(n.title || "");
        return "<div class='news-item'>" + t + "<div class='meta'>" + esc(n.source || "") + " &middot; " + esc(n.published_at || "") + "</div></div>";
      }).join("") + "</div>";
    }
    var cites = "";
    if (node.citations && node.citations.length) {
      cites = "<div class='src'>Sources: " + node.citations.map(function (c) {
        return esc(c.source || c.domain || "?") + (c.retrieved_at ? " @" + esc(c.retrieved_at) : "") + " [" + esc(c.status || "?") + "]";
      }).join(" &middot; ") + "</div>";
    }
    var g = node.grounding ? " " + gBadge(node.grounding) : "";
    return "<details class='ai-sect'" + (open ? " open" : "") + "><summary><b>" + esc(title) + "</b>" + g + "</summary><div class='ai-sect-body'>" + body + cites + "</div></details>";
  }
  function reportHtml(r) {
    var h = "<div class='ai-meta'>Last run: <b>" + esc(r.generated_at || "?") + "</b> &middot; Model: <b>" +
      esc(r.model || "?") + "</b> &middot; Data: <b>" + esc(String(r.provider_count === undefined ? "?" : r.provider_count)) +
      " providers</b> &middot; Depth: <b>" + esc(r.depth || "?") + "</b>" +
      (r.llm_backed === false ? " &middot; <span class='pill pill-na'>EXTRACTIVE (no LLM)</span>" : "") + "</div>";
    h += sectHtml("Executive Snapshot", r.executive_snapshot, true);
    h += sectHtml("Fundamentals", r.fundamentals, false);
    h += sectHtml("Valuation", r.valuation, false);
    h += sectHtml("Technical Structure", r.technical, false);
    h += sectHtml("News & Sentiment", r.news_sentiment, false);
    h += sectHtml("Bull Case", r.bull_case, false);
    h += sectHtml("Bear Case", r.bear_case, false);
    h += sectHtml("Risk Factors", r.risks, false);
    if (r.catalysts) h += "<details class='ai-sect'><summary><b>Key Catalysts</b></summary><div class='ai-sect-body'><ul class='ai-points'>" + (r.catalysts.points || []).map(function (p) { return "<li>" + esc(p) + "</li>"; }).join("") + "</ul></div></details>";
    if (r.unknowns) h += "<details class='ai-sect'><summary><b>Key Unknowns</b></summary><div class='ai-sect-body'><ul class='ai-points'>" + (r.unknowns.points || []).map(function (p) { return "<li>" + esc(p) + "</li>"; }).join("") + "</ul></div></details>";
    if (r.data_gaps && r.data_gaps.length) {
      h += "<details class='ai-sect'><summary><b>Data Gaps</b></summary><div class='ai-sect-body'><ul class='ai-points'>" +
        r.data_gaps.map(function (g) { return "<li><b>" + esc(g.domain || "?") + ":</b> " + esc(g.reason || "?") + (g.detail ? " — " + esc(g.detail) : "") + "</li>"; }).join("") + "</ul></div></details>";
    }
    h += sectHtml("Research Conclusion", r.conclusion, true);
    if (r.sources && r.sources.length) {
      h += "<details class='ai-sect' open><summary><b>Sources</b></summary><div class='ai-sect-body'><div class='twrap'><table class='t'><thead><tr><th scope='col'>Category</th><th scope='col'>Domain</th><th scope='col'>Provider</th><th scope='col'>As of</th><th scope='col'>Status</th></tr></thead><tbody>" +
        r.sources.map(function (s) {
          return "<tr><td class='txt'>" + esc(s.category || "") + "</td><td class='txt'>" + esc(s.domain || "") + "</td><td class='txt'>" + esc(s.provider || "") + "</td><td class='txt'>" + esc(s.as_of || "—") + "</td><td>" + esc(s.status || "") + "</td></tr>";
        }).join("") + "</tbody></table></div></div></details>";
    }
    return h;
  }
  function panelHtml(sym) {
    return "<div class='card sect ai-panel' id='ai-panel'>" +
      "<h3>AI Research <span class='pill pill-calc'>MULTI-AGENT</span></h3>" +
      "<div class='sub'>Evidence-grounded multi-agent analysis. Research only — never investment advice.</div>" +
      "<div class='row' style='margin:8px 0'><label class='f'>Depth<select id='ai-depth' class='in'><option value='standard'>Standard</option><option value='deep'>Deep</option></select></label>" +
      "<button class='btn primary' id='ai-run'>Run Analysis</button>" +
      "<span class='src' id='ai-status'>Checking LLM status…</span></div>" +
      "<div id='ai-stages'></div><div id='ai-out'></div></div>";
  }
  function setStages(state) {
    var n = $("ai-stages");
    if (n) n.innerHTML = stageHtml(state);
  }
  function runAnalysis(sym, force) {
    var out = $("ai-out"), st = $("ai-status");
    var depth = ($("ai-depth") && $("ai-depth").value) || "standard";
    if (out) out.innerHTML = "<div class='skel'></div><div class='skel'></div>";
    setStages({ prepare: "running" });
    var tick = 0;
    var timer = setInterval(function () {
      tick += 1;
      var s = { prepare: "done" };
      var order = ["market", "fundamental", "news", "bull", "risk", "manager"];
      order.forEach(function (k, i) {
        s[k] = tick > i + 1 ? "done" : (tick === i + 1 ? "running" : "pending");
      });
      setStages(s);
    }, 4000);
    function done() { clearInterval(timer); }
    window.FT_API.post("ai/research", { ticker: sym, depth: depth, force: !!force }).then(function (r) {
      done();
      if (!$("ai-out")) return;
      var b = r.body || {};
      if (!b.ok || !b.report) {
        setStages({});
        $("ai-out").innerHTML = "<div class='empty'><b>AI RESEARCH UNAVAILABLE</b><br>" + esc(b.reason || b.error || ("HTTP " + r.http)) + "<br><span class='src'>The rest of the terminal keeps working. Quotes, charts and financials above are unaffected.</span></div>";
        if (st) st.textContent = "Last run failed.";
        return;
      }
      var rep = b.report;
      var state = {};
      Object.keys(rep.stages || {}).forEach(function (k) { state[k] = rep.stages[k]; });
      state.prepare = "done";
      setStages(state);
      $("ai-out").innerHTML = reportHtml(rep) +
        (b.cache && b.cache.hit ? "<div class='prov'>Served from research cache (" + esc(b.cache.ttl_note || "") + ").</div>" : "");
      if (st) st.textContent = "Last run: " + (rep.generated_at || "?") + " · " + (rep.model || "?") + " · " + (rep.provider_count || 0) + " providers";
    });
  }
  function mountCompanyPanel() {
    try {
      var list = $("r-list");
      if (!list || $("ai-panel")) return;
      var sym = (location.hash.split("/")[2] || "").toUpperCase();
      sym = decodeURIComponent(sym);
      if (!sym) return;
      var wrap = document.createElement("div");
      wrap.innerHTML = panelHtml(sym);
      var body = $("co-body") || list.parentElement;
      (body || list).insertBefore(wrap, (body || list).firstChild);
      window.FT_API.get("ai/status").then(function (r) {
        var b = (r && r.body) || {};
        var st = $("ai-status");
        if (!st) return;
        if (b.available) st.textContent = "LLM ready: " + (b.model || "?") + " (" + (b.provider || "?") + "). Explicit runs only; results cached.";
        else st.textContent = "AI research unavailable — Reason: " + (b.reason || "LLM provider not configured");
      });
      var btn = $("ai-run");
      if (btn) btn.onclick = function () { runAnalysis(sym, true); };
      // Auto-load cached report (no LLM cost) if present.
      window.FT_API.get("ai/research", { ticker: sym, depth: "standard" }).then(function (r) {
        var b = (r && r.body) || {};
        if (b.ok && b.report && $("ai-out")) {
          $("ai-out").innerHTML = reportHtml(b.report);
          var st2 = $("ai-status");
          if (st2) st2.textContent = "Last run: " + (b.report.generated_at || "?") + " · " + (b.report.model || "?");
          var state = {};
          Object.keys(b.report.stages || {}).forEach(function (k) { state[k] = b.report.stages[k]; });
          state.prepare = "done";
          setStages(state);
        }
      });
    } catch (e) { /* never break the company page */ }
  }
  function mountComparePanel() {
    try {
      var out = $("k-out");
      if (!out || $("ai-cmp")) return;
      var box = document.createElement("div");
      box.className = "card sect";
      box.id = "ai-cmp";
      box.innerHTML = "<h3>AI Comparison <span class='pill pill-calc'>EVIDENCE PER COMPANY</span></h3>" +
        "<div class='sub'>Side-by-side research evidence. No winner score.</div>" +
        "<div class='row'><button class='btn primary' id='ai-cmp-run'>Compare with AI</button><span class='src'>Runs explicit cached research per company.</span></div>" +
        "<div id='ai-cmp-out' style='margin-top:8px'></div>";
      out.parentElement.insertBefore(box, out.nextSibling);
      $("ai-cmp-run").onclick = function () {
        var raw = ($("k-s") && $("k-s").value) || "";
        var syms = raw.split(",").map(function (s) { return s.trim().toUpperCase(); }).filter(Boolean).slice(0, 2);
        if (syms.length < 2) { $("ai-cmp-out").innerHTML = "<div class='empty'>Enter at least 2 symbols.</div>"; return; }
        $("ai-cmp-out").innerHTML = "<div class='skel'></div><div class='skel'></div>";
        window.FT_API.post("ai/compare", { left: syms[0], right: syms[1], depth: "standard" }).then(function (r) {
          var b = (r && r.body) || {};
          if (!b.ok) { $("ai-cmp-out").innerHTML = "<div class='empty'><b>AI RESEARCH UNAVAILABLE</b><br>" + esc(b.reason || b.error || "") + "</div>"; return; }
          function col(rep) {
            if (!rep || !rep.report) return "<div class='empty'>Unavailable: " + esc((rep && (rep.reason || rep.error)) || "?") + "</div>";
            var x = rep.report;
            return "<b>" + esc(x.ticker) + "</b> " + gBadge((x.grounding || {}).fundamental || "unverified") +
              "<p class='ai-text'>" + esc(((x.executive_snapshot || {}).text || "").slice(0, 600)) + "</p>" +
              "<div class='src'>Model: " + esc(x.model || "?") + " · " + esc(String(x.provider_count || 0)) + " providers · " + esc(x.generated_at || "") + "</div>";
          }
          $("ai-cmp-out").innerHTML = "<div class='grid g2'><div class='card'>" + col(b.left) + "</div><div class='card'>" + col(b.right) + "</div></div>";
        });
      };
    } catch (e) { /* never break compare */ }
  }
  function mountWatchlistLinks() {
    try {
      var t = $("w-t");
      if (!t || t.getAttribute("data-ai")) return;
      t.setAttribute("data-ai", "1");
      Array.prototype.forEach.call(t.querySelectorAll("tr"), function (tr) {
        var a = tr.querySelector("a[href*='#/company/']");
        if (!a || tr.querySelector(".ai-link")) return;
        var sym = (a.getAttribute("href").split("/company/")[1] || "").toUpperCase();
        var td = document.createElement("td");
        td.className = "num";
        td.innerHTML = "<a class='btn sm ai-link' href='#/company/" + esc(sym) + "/Research'>Analyze</a>";
        tr.appendChild(td);
      });
    } catch (e) { /* never break watchlist */ }
  }
  function scan() {
    var h = location.hash || "";
    if (h.indexOf("#/company/") === 0 && h.split("/").length >= 4 && decodeURIComponent(h.split("/")[3] || "").toLowerCase() === "research") mountCompanyPanel();
    else if (h.indexOf("#/compare") === 0) mountComparePanel();
    else if (h.indexOf("#/watchlist") === 0) mountWatchlistLinks();
  }
  window.FT_AI = { scan: scan, runAnalysis: runAnalysis };
  window.addEventListener("hashchange", function () { setTimeout(scan, 300); });
  document.addEventListener("DOMContentLoaded", function () { setTimeout(scan, 500); });
  setInterval(scan, 1500);
})();
