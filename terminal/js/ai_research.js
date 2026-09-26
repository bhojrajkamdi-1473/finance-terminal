/* FT AI Research — structured report renderer.
   Reads ONLY the cleaned report contract (summary/observations/metrics).
   Never renders raw orchestration text. Exposes FT_AI.mountPanel(host, sym).
   Loads independently; failures never break the company page. */
(function () {
  "use strict";
  var TID = null;
  function esc(s) {
    return (window.FT_FMT ? window.FT_FMT.esc(String(s === null || s === undefined ? "" : s)) : String(s));
  }
  function clean(s) {
    if (s === null || s === undefined) return "";
    var t = String(s);
    if (/^(none|null|undefined|nan|-|n\/a)$/i.test(t.trim())) return "";
    return t.replace(/\b(None|null|undefined|NaN)\b/g, "").replace(/[ \t]{2,}/g, " ").trim();
  }
  function dayTime(iso) {
    try {
      var d = new Date(iso);
      if (isNaN(d)) return "—";
      var day = d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "Asia/Kolkata" });
      var tm = d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Asia/Kolkata" });
      return day + " · " + tm + " IST";
    } catch (e) { return "—"; }
  }
  function obsList(list) {
    var live = (list || []).filter(function (o) { return o && clean(o.statement); });
    if (!live.length) return "";
    return '<ul class="cx-obs">' + live.map(function (o) {
      var meta = [o.source, o.period].filter(function (x) { return x && !/^(none|null)$/i.test(String(x)); }).join(" · ");
      return "<li>" + esc(clean(o.statement)) + (meta ? '<span class="om">' + esc(meta) + "</span>" : "") + "</li>";
    }).join("") + "</ul>";
  }
  function metricGrid(metrics) {
    var live = (metrics || []).filter(function (m) { return m && m.display; });
    if (!live.length) return "";
    return '<dl class="cx-facts">' + live.map(function (m) {
      return "<div><dt>" + esc(m.label || "") + "</dt><dd>" + esc(m.display) + "</dd></div>";
    }).join("") + "</dl>";
  }
  function rsec(title, node, open) {
    if (!node) return "";
    var inner = "";
    if (node.text && clean(node.text)) inner += '<p class="cx-exec" style="border:none;padding-left:0">' + esc(clean(node.text)) + "</p>";
    if (node.summary && clean(node.summary)) inner += '<p class="cx-exec">' + esc(clean(node.summary)) + "</p>";
    inner += metricGrid(node.metrics) + obsList(node.observations);
    if ((!node.observations || !node.observations.length) && node.points && node.points.length && !node.text && !node.summary) {
      var pts = node.points.filter(clean).slice(0, 5);
      if (pts.length) inner += '<ul class="cx-obs">' + pts.map(function (p) { return "<li>" + esc(clean(p)) + "</li>"; }).join("") + "</ul>";
    }
    if (!inner) return ""; // omit empty sections entirely
    return '<details class="cx-sec" style="padding:12px 14px"' + (open ? " open" : "") + '><summary style="cursor:pointer;font-size:12px;text-transform:uppercase;letter-spacing:.07em;color:var(--cx-sub);font-weight:750">' +
      esc(title) + "</summary><div style='margin-top:8px'>" + inner + "</div></details>";
  }
  function newsSec(ns) {
    ns = ns || {};
    if ((!ns.observations || !ns.observations.length) && (!ns.items || !ns.items.length)) return "";
    var h = '<section class="cx-sec"><h2>News &amp; sentiment</h2>' + obsList(ns.observations);
    if (ns.items && ns.items.length) {
      h += '<div style="margin-top:6px">' + ns.items.slice(0, 6).map(function (n) {
        var t = n.url ? '<a href="' + esc(n.url) + '" target="_blank" rel="noopener">' + esc(clean(n.title) || "Untitled") + "</a>" : esc(clean(n.title) || "Untitled");
        return '<div class="cx-newsrow"><span class="tm">' + esc(String(n.published_at || "").slice(0, 10)) + "</span><span class='hl'>" + t +
          "</span><span class='src'>" + esc(n.source || "") + "</span></div>";
      }).join("") + "</div>";
    }
    return h + "</section>";
  }
  function reportHtml(r) {
    var h = "";
    if (!r.llm_backed) {
      h += "<div class='cx-note' style='margin-bottom:8px'>Deterministic research mode — every section below is built from verified data.</div>";
    }
    var snap = (r.executive_snapshot || {}).text || (r.executive_snapshot || {}).summary || "";
    if (clean(snap)) h += '<section class="cx-sec"><h2>Research snapshot</h2><p class="cx-exec">' + esc(clean(snap)) + "</p></section>";
    /* Two-column snapshot: fundamentals left, market context right. */
    h += "<div class='an-grid'><div class='an-6'>" +
      rsec("Fundamentals", r.fundamentals, false) +
      rsec("Valuation", r.valuation, false) + "</div><div class='an-6'>" +
      rsec("Technical structure", r.technical, false) +
      newsSec(r.news_sentiment) + "</div></div>";
    h += '<section class="cx-sec"><h2>Bull case / Bear case</h2><div class="cx-cols"><div class="cx-col bull"><h4>Bull case</h4>' +
      obsList((r.bull_case || {}).observations) + '</div><div class="cx-col bear"><h4>Bear case</h4>' +
      obsList((r.bear_case || {}).observations) + "</div></div></section>";
    var risks = (r.risks || {}).observations || [];
    if (risks.length) {
      h += '<section class="cx-sec"><h2>Risk factors</h2>' +
        '<div class="cx-scroll"><table class="cx-t"><thead><tr><th scope="col">Risk</th><th scope="col">Evidence</th></tr></thead><tbody>' +
        risks.filter(function (o) { return clean(o.statement); }).map(function (o) {
          return "<tr><td>" + esc(clean(o.statement)) + "</td><td>" + esc([o.source, o.period].filter(Boolean).join(" · ")) + "</td></tr>";
        }).join("") + "</tbody></table></div></section>";
    }
    if (r.data_gaps && r.data_gaps.length) {
      var labels = { estimates: "No verified analyst estimates available.", ownership: "Ownership breakdown unavailable.",
        earnings: "Earnings history unavailable.", news: "Recent news unavailable.", income_annual: "Statements unavailable from configured providers.",
        valuation: "Valuation multiples unavailable.", technicals: "Technical analytics unavailable.", quote: "Quote unavailable." };
      h += '<section class="cx-sec"><h2>Data gaps</h2><ul class="cx-obs">' +
        r.data_gaps.map(function (g) { return "<li>" + esc(labels[g.domain] || ("Unavailable: " + g.domain)) + "</li>"; }).join("") + "</ul></section>";
    }
    var concl = (r.conclusion || {}).text || (r.conclusion || {}).summary || "";
    if (clean(concl)) h += '<section class="cx-sec"><h2>Research conclusion</h2><p class="cx-exec">' + esc(clean(concl)) + "</p></section>";
    if (r.sources && r.sources.length) {
      var seen = {}, rows = [];
      r.sources.forEach(function (s) {
        if (s.category === "AI" || seen[s.provider]) return;
        seen[s.provider] = 1;
        rows.push("<tr><td>" + esc(s.provider) + "</td><td>" + esc(s.status || "") + "</td><td>" + esc(s.as_of ? dayTime(s.as_of) : "") + "</td></tr>");
      });
      h += '<section class="cx-sec"><h2>Sources</h2><details><summary class="cx-note">Show contributing sources (' + rows.length + ")</summary>" +
        '<div class="cx-scroll" style="margin-top:8px"><table class="cx-t"><thead><tr><th scope="col">Source</th><th scope="col">Status</th><th scope="col">As of</th></tr></thead><tbody>' +
        rows.join("") + "</tbody></table></div></details></section>";
    }
    return h;
  }
  function mountPanel(host, sym) {
    var depth = "standard";
    host.innerHTML =
      '<section class="cx-sec"><div class="cx-aihead"><h2>AI Research</h2>' +
      '<div class="cx-depth" role="group" aria-label="Depth">' +
      [["quick", "Quick"], ["standard", "Standard"], ["deep", "Deep"]].map(function (d) {
        return '<button data-d="' + d[0] + '"' + (d[0] === depth ? ' class="on"' : "") + ">" + d[1] + "</button>";
      }).join("") + "</div>" +
      '<button class="cx-btn" id="cxai-run">Run analysis</button></div>' +
      '<div class="cx-note">Evidence-grounded multi-agent research. Research only — never investment advice.</div>' +
      '<div class="cx-note" id="cxai-meta">Checking availability…</div>' +
      '<div id="cxai-out" style="margin-top:8px"></div>' +
      '<details style="margin-top:8px"><summary class="cx-note">Recent runs (audit trail)</summary>' +
      '<div id="cxai-runs" class="cx-note">Loading…</div></details></section>';
    Array.prototype.forEach.call(host.querySelectorAll("[data-d]"), function (b) {
      b.onclick = function () {
        Array.prototype.forEach.call(host.querySelectorAll("[data-d]"), function (x) { x.classList.remove("on"); });
        b.classList.add("on"); depth = b.getAttribute("data-d");
      };
    });
    function meta(r) {
      var m = host.querySelector("#cxai-meta");
      if (!m) return;
      var bits = ["Last updated: " + dayTime(r.generated_at)];
      if (r.provider_count !== undefined && r.provider_count !== null) bits.push("Sources: " + r.provider_count);
      bits.push(r.llm_backed ? "AI synthesis · " + r.model : "Verified-data analysis");
      m.textContent = bits.join("  ·  ");
    }
    function fail(reason) {
      var r = String(reason || "The research service did not respond.");
      var hint = /not configured|no llm|missing key/i.test(r)
        ? "<p class='why'>Setup: set AI_PROVIDER + AI_API_KEY (+ optional AI_MODEL) in the server environment / Render dashboard, then redeploy. Evidence tabs above are unaffected.</p>"
        : "";
      host.querySelector("#cxai-out").innerHTML =
        '<div class="cx-empty"><b>AI research unavailable</b><p>' + esc(r) +
        "</p><p class='why'>Verified market data in the tabs above remains available.</p>" + hint + "</div>";
    }
    host.querySelector("#cxai-run").onclick = function () {
      var btn = host.querySelector("#cxai-run");
      btn.disabled = true;
      host.querySelector("#cxai-out").innerHTML = '<div class="cx-skel"></div><div class="cx-skel"></div><div class="cx-skel"></div>';
      window.FT_API.post("ai/research", { ticker: sym, depth: depth, force: true }).then(function (x) {
        btn.disabled = false;
        var b = (x && x.body) || {};
        if (!b.ok || !b.report) { fail(b.reason || b.error); return; }
        host.querySelector("#cxai-out").innerHTML = reportHtml(b.report);
        meta(b.report);
        window.FT_API.get("ai/runs", { ticker: sym, limit: 5 }).then(function (rx) {
          var el = host.querySelector("#cxai-runs");
          if (!el) return;
          var runs = (((rx || {}).body) || {}).runs || [];
          if (runs.length) el.innerHTML = runs.map(function (r) {
            return "<div>" + esc(r.ticker) + " · " + esc(r.depth) + " · " + esc(r.model || "evidence") + "</div>";
          }).join("");
        }).catch(function () { /* optional */ });
      }).catch(function () { btn.disabled = false; fail("Network error while running analysis."); });
    };
    window.FT_API.get("ai/research", { ticker: sym, depth: "standard" }).then(function (x) {
      var b = (x && x.body) || {};
      if (b.ok && b.report) { host.querySelector("#cxai-out").innerHTML = reportHtml(b.report); meta(b.report); }
      else {
        var m = host.querySelector("#cxai-meta");
        if (m) m.textContent = "No cached analysis yet — press Run analysis.";
      }
    }).catch(function () { /* stay quiet; user can run */ });
    window.FT_API.get("ai/runs", { ticker: sym, limit: 5 }).then(function (x) {
      var el = host.querySelector("#cxai-runs");
      if (!el) return;
      var b = (x && x.body) || {}, runs = b.runs || [];
      el.innerHTML = runs.length ? runs.map(function (r) {
        return "<div>" + esc(r.ticker) + " · " + esc(r.depth) + " · " + esc(r.model || "evidence") +
          " · " + esc(dayTime(new Date((r.created_at || 0) * 1000).toISOString())) + "</div>";
      }).join("") : "No recorded runs for this ticker yet.";
    }).catch(function () { /* audit list is optional */ });
  }
  /* legacy compare/watchlist hooks (non-breaking) */
  function scan() {
    try {
      var h = location.hash || "";
      if (h.indexOf("#/compare") === 0) mountCompare();
      else if (h.indexOf("#/watchlist") === 0) mountWatch();
    } catch (e) { /* never break pages */ }
  }
  function mountCompare() {
    var out = document.getElementById("k-out");
    if (!out || document.getElementById("ai-cmp")) return;
    var box = document.createElement("div");
    box.className = "card sect"; box.id = "ai-cmp";
    box.innerHTML = "<h3>AI Comparison</h3><div class='sub'>Side-by-side evidence. No winner score.</div>" +
      "<div class='row'><button class='btn primary' id='ai-cmp-run'>Compare with AI</button></div><div id='ai-cmp-out' style='margin-top:8px'></div>";
    out.parentElement.insertBefore(box, out.nextSibling);
    document.getElementById("ai-cmp-run").onclick = function () {
      var raw = (document.getElementById("k-s") || {}).value || "";
      var syms = raw.split(",").map(function (s) { return s.trim().toUpperCase(); }).filter(Boolean).slice(0, 2);
      if (syms.length < 2) { document.getElementById("ai-cmp-out").innerHTML = "<div class='empty'>Enter at least 2 symbols.</div>"; return; }
      document.getElementById("ai-cmp-out").innerHTML = "<div class='skel'></div>";
      window.FT_API.post("ai/compare", { left: syms[0], right: syms[1], depth: "standard" }).then(function (x) {
        var b = (x && x.body) || {};
        if (!b.ok) { document.getElementById("ai-cmp-out").innerHTML = "<div class='empty'><b>AI research unavailable.</b></div>"; return; }
        function col(rep) {
          if (!rep || !rep.report) return "<div class='empty'>Unavailable.</div>";
          var r = rep.report, s = (r.executive_snapshot || {}).summary || (r.executive_snapshot || {}).text || "";
          return "<b>" + esc(r.ticker) + "</b><p class='ai-text'>" + esc(clean(s).slice(0, 500)) + "</p>" +
            "<div class='src'>" + esc(r.model || "") + " · " + esc(String(r.provider_count || 0)) + " sources</div>";
        }
        document.getElementById("ai-cmp-out").innerHTML = "<div class='grid g2'><div class='card'>" + col(b.left) + "</div><div class='card'>" + col(b.right) + "</div></div>";
      });
    };
  }
  function mountWatch() {
    var t = document.getElementById("w-t");
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
  }
  window.FT_AI = { mountPanel: mountPanel, scan: scan };
  window.addEventListener("hashchange", function () { setTimeout(scan, 300); });
  document.addEventListener("DOMContentLoaded", function () { setTimeout(scan, 500); });
  if (TID) clearInterval(TID);
  TID = setInterval(scan, 2000);
})();
