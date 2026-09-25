/* FT shell enhancements: sidebar sections, topbar market strip, IPO dashboard.
   Non-invasive: enhances DOM built by app.js/pages.js, never replaces routes.
   window.FT_PAGES.pIPOs is overridden with a tabbed dashboard (same route). */
(function () {
  "use strict";
  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return (window.FT_FMT ? window.FT_FMT.esc(String(s === null || s === undefined ? "" : s)) : String(s));
  }
  /* ---------- sidebar sections ---------- */
  var SECTIONS = [
    ["MARKETS", ["dashboard", "markets", "companies", "compare"]],
    ["RESEARCH", ["screener", "watchlist", "portfolio", "news", "research", "earnings", "actions", "macro"]],
    ["IPO", ["ipos"]],
    ["SYSTEM", ["settings"]],
  ];
  function sectionize() {
    try {
      var nav = $("sidenav");
      if (!nav || nav.getAttribute("data-sec")) return;
      var links = {};
      Array.prototype.forEach.call(nav.querySelectorAll("a[data-r]"), function (a) {
        links[a.getAttribute("data-r")] = a;
      });
      if (!links.dashboard) return;
      nav.setAttribute("data-sec", "1");
      var frag = document.createDocumentFragment();
      SECTIONS.forEach(function (sec) {
        var has = sec[1].some(function (r) { return links[r]; });
        if (!has) return;
        var lab = document.createElement("div");
        lab.className = "nav-sec";
        lab.textContent = sec[0];
        frag.appendChild(lab);
        sec[1].forEach(function (r) { if (links[r]) frag.appendChild(links[r]); });
      });
      /* any route not mapped (future pages) keeps working at the end */
      Object.keys(links).forEach(function (r) {
        var mapped = SECTIONS.some(function (s) { return s[1].indexOf(r) >= 0; });
        if (!mapped) frag.appendChild(links[r]);
      });
      nav.innerHTML = "";
      nav.appendChild(frag);
    } catch (e) { /* shell must never break nav */ }
  }
  /* ---------- topbar market strip ---------- */
  var STRIP = [["^NSEI", "NIFTY"], ["^BSESN", "SENSEX"], ["^GSPC", "S&P 500"]];
  function strip() {
    try {
      if ($("mstrip")) return;
      var bar = document.querySelector("#topbar .topbar-right");
      if (!bar || !window.FT_API) return;
      var el = document.createElement("span");
      el.id = "mstrip";
      el.className = "mstrip";
      el.setAttribute("aria-label", "Market status");
      bar.insertBefore(el, bar.firstChild);
      function load() {
        var host = $("mstrip");
        if (!host) return;
        window.FT_API.get("market-overview").then(function (r) {
          var items = ((r.body || {}).items) || [];
          var by = {};
          items.forEach(function (i) { by[i.symbol] = i; });
          host.innerHTML = STRIP.map(function (p) {
            var it = by[p[0]], q = (it && it.quote) || {};
            if (q.price === null || q.price === undefined) return "";
            var cls = (window.FT_FMT ? window.FT_FMT.dirClass(q.change_pct) : "");
            var pct = (window.FT_FMT ? window.FT_FMT.fmtPct(q.change_pct) : "");
            return '<span class="ms"><b>' + p[1] + "</b> " + esc(String(q.price)) +
              ' <span class="' + cls + '">' + pct + "</span></span>";
          }).join("");
        }).catch(function () { /* strip stays empty; never blocks */ });
      }
      load();
      setInterval(load, 60000);
    } catch (e) { /* ignore */ }
  }
  /* ---------- IPO dashboard (overrides pIPOs, same route) ---------- */
  var TABS = ["Upcoming", "Open", "Closed", "Listed", "GMP", "Subscription", "Calendar"];
  function pIPOs() {
    var API = window.FT_API, F = window.FT_FMT;
    var view = $("view");
    view.innerHTML = "<h1 class='h-page'>IPO Dashboard</h1>" +
      "<div class='sub'>Calendar feed where entitled. GMP is unofficial chatter — labelled, never advice.</div>" +
      "<div class='cx-tabs' role='tablist' aria-label='IPO views' id='ipo-tabs'>" +
      TABS.map(function (t, i) {
        return "<button role='tab' data-ip='" + t + "'" + (i === 0 ? " class='on'" : "") + ">" + t + "</button>";
      }).join("") + "</div><div id='ipo-out' style='margin-top:12px'></div>";
    var buckets = null, gmp = null, sub = null, calStatus = null, calMsg = null;
    API.get("ipo").then(function (r) {
      var b = r.body || {};
      buckets = b.buckets || null; gmp = b.gmp || null; sub = b.subscription || null;
      calStatus = b.status; calMsg = b.message;
      paint("Upcoming");
    });
    function paint(tab) {
      var host = $("ipo-out");
      if (!host) return;
      Array.prototype.forEach.call(document.querySelectorAll("#ipo-tabs button"), function (x) {
        x.classList.toggle("on", x.getAttribute("data-ip") === tab);
        x.onclick = function () { paint(x.getAttribute("data-ip")); };
      });
      if (!buckets) {
        host.innerHTML = "<div class='cx-empty'><b>IPO calendar</b><p>No verified data available.</p>" +
          "<p class='why'>" + esc(calMsg || "No IPO feed configured.") + "</p></div>";
        return;
      }
      if (tab === "GMP") {
        var gl = (gmp && gmp.data) || [];
        if (!gl.length) {
          host.innerHTML = "<div class='cx-empty'><b>Grey market premium</b>" +
            "<p><span class='cx-q cx-q-warn'>UNOFFICIAL GREY MARKET PREMIUM</span></p>" +
            "<p>" + esc((gmp && gmp.message) || "No verified GMP source configured.") + "</p>" +
            "<p class='why'>Rules: source + timestamp required · estimated listing = upper band + GMP (" +
            "INDICATIVE ONLY) · disagreeing sources shown separately (GMP DISCREPANCY), never averaged.</p></div>";
          return;
        }
        host.innerHTML = "<div class='cx-scroll'><table class='cx-t'><thead><tr><th scope='col'>Company</th>" +
          "<th scope='col' class='num'>GMP (UNOFFICIAL)</th><th scope='col' class='num'>GMP %</th>" +
          "<th scope='col'>Updated</th></tr></thead><tbody>" +
          gl.map(function (g) {
            if (g.value === null || g.value === undefined) return "";
            return "<tr><td>" + esc(g.company || "") + "<br><span class='cx-note'>IPO Guru · unofficial chatter, not a price promise</span></td>" +
              "<td class='num'>₹" + esc(String(g.value)) + "</td><td class='num'>" + esc(String(g.percent === null || g.percent === undefined ? "" : g.percent + "%")) +
              "</td><td>" + esc(g.updated_at || "") + "</td></tr>";
          }).join("") + "</tbody></table></div>" +
          ((gmp && gmp.discrepancy_note) ? "<div class='cx-note'>Status: GMP DISCREPANCY — values shown per source, never averaged.</div>" : "");
        return;
      }
      if (tab === "Subscription") {
        var sd = (sub && sub.data) || [];
        if (!sd.length) {
          host.innerHTML = "<div class='cx-empty'><b>Subscription</b><p>" +
            esc((sub && sub.message) || "No subscription feed configured.") +
            "</p><p class='why'>QIB / NII / Retail splits appear only from exchange-published figures.</p></div>";
          return;
        }
        host.innerHTML = "<div class='cx-scroll'><table class='cx-t'><thead><tr><th scope='col'>Company</th>" +
          "<th scope='col' class='num'>QIB</th><th scope='col' class='num'>NII</th>" +
          "<th scope='col' class='num'>Retail</th><th scope='col' class='num'>Total</th><th scope='col'>Updated</th></tr></thead><tbody>" +
          sd.map(function (s) {
            function x(v) { return v === null || v === undefined ? "" : esc(String(v)) + "x"; }
            return "<tr><td>" + esc(s.company || "") + "</td><td class='num'>" + x(s.qib) + "</td><td class='num'>" + x(s.nii) +
              "</td><td class='num'>" + x(s.retail) + "</td><td class='num'><b>" + x(s.total) + "</b></td><td>" + esc(s.updated_at || "") + "</td></tr>";
          }).join("") + "</tbody></table></div>";
        var bars = sd.filter(function (s) { return s.total !== null && s.total !== undefined && !isNaN(Number(s.total)); })
          .map(function (s) { return { label: String(s.company || "?").slice(0, 22), value: Number(s.total), display: Number(s.total).toFixed(2) + "x" }; });
        if (bars.length && window.FT_VIZ) {
          host.innerHTML = "<div style='margin-bottom:8px'>" + window.FT_VIZ.bars(bars) + "</div>" + host.innerHTML;
        }
        return;
      }
      var rows = tab === "Calendar"
        ? Object.keys(buckets).reduce(function (a, k) { return a.concat(buckets[k]); }, [])
        : (buckets[tab.toLowerCase()] || []);
      rows = rows.filter(function (w) { return (w.name || w.company || w.symbol || w.ticker); });
      if (!rows.length) {
        host.innerHTML = "<div class='cx-note'>No " + esc(tab.toLowerCase()) + " IPOs right now.</div>";
        return;
      }
      host.innerHTML = '<div class="cx-scroll"><table class="cx-t"><thead><tr><th scope="col">Company</th>' +
        "<th scope='col'>Open</th><th scope='col'>Close</th><th scope='col'>Price band</th>" +
        "<th scope='col'>List date</th><th scope='col'>Detail</th></tr></thead><tbody>" +
        rows.map(function (w, ix) {
          var nm = w.name || w.company || w.symbol || w.ticker || "—";
          return "<tr><td><b>" + esc(nm) + "</b><br><span class='cx-note'>" + esc(w.symbol || w.ticker || "") + "</span></td>" +
            "<td>" + esc(pick(w, ["offerdate", "offer_date", "opendate", "open"])) + "</td>" +
            "<td>" + esc(pick(w, ["closedate", "close_date", "closedate"])) .replace(/^\s*$/, "—") + "</td>" +
            "<td class='num'>" + esc(band(w)) + "</td>" +
            "<td>" + esc(pick(w, ["listingdate", "listing_date", "listdate"])) + "</td>" +
            "<td><button class='cx-btn2' data-ipo='" + ix + "'>Analyse</button></td></tr>";
        }).join("") + "</tbody></table></div><div id='ipo-det'></div>";
      Array.prototype.forEach.call(host.querySelectorAll("[data-ipo]"), function (b) {
        b.onclick = function () { detail(rows[Number(b.getAttribute("data-ipo"))]); };
      });
    }
      function pick(w, keys) {
      for (var i = 0; i < keys.length; i++) {
        for (var k in w) {
          if (String(k).toLowerCase().replace(/[^a-z]/g, "") === keys[i].replace(/[^a-z]/g, "") && w[k]) return String(w[k]).slice(0, 10);
        }
      }
      return "";
    }
    function band(w) {
      var lo = pick(w, ["pricerangelow", "pricelow", "lowerband", "floorprice"]);
      var hi = pick(w, ["pricerangehigh", "pricehigh", "upperband", "capprice", "offerprice"]);
      if (!lo && !hi) return "";
      return !lo ? hi : !hi ? lo : lo + " – " + hi;
    }
    function detail(w) {
      var host = $("ipo-det");
      if (!host) return;
      var sym = w.symbol || w.ticker || "";
      host.innerHTML = "<div class='cx-skel'></div>";
      if (!sym) { host.innerHTML = "<div class='cx-note'>No listed symbol for this issue yet.</div>"; return; }
      API.get("ipo/detail", { symbol: sym }).then(function (r) {
        var b = (r.body || {});
        if (!b.ok) { host.innerHTML = "<div class='cx-note'>Detail unavailable.</div>"; return; }
        var prof = ((b.profile || {}).data) || {}, val = ((b.valuation || {}).data) || {};
        var gm = b.gmp || {}, sb = b.subscription || {};
        var grow = (gm.data && gm.data[0]) || null;
        var facts = [];
        if (grow && grow.gmp_value !== null && grow.gmp_value !== undefined)
          facts.push("<div><dt>GMP (unofficial)</dt><dd>₹" + esc(String(grow.gmp_value)) + "</dd></div>");
        if (grow && grow.gmp_percent !== null && grow.gmp_percent !== undefined)
          facts.push("<div><dt>GMP %</dt><dd>" + esc(String(grow.gmp_percent)) + "%</dd></div>");
        if (grow && grow.gmp_updated_at)
          facts.push("<div><dt>Updated</dt><dd>" + esc(grow.gmp_updated_at) + "</dd></div>");
        if (grow && grow.estimated_listing_price !== null && grow.estimated_listing_price !== undefined)
          facts.push("<div><dt>Indicative listing</dt><dd>₹" + esc(String(grow.estimated_listing_price)) + " (indicative GMP-derived estimate)</dd></div>");
        var gmpHtml = facts.length ? "<dl class='cx-facts'>" + facts.join("") + "</dl>"
          : "<div class='cx-empty'><b>Grey market premium</b>" +
            "<p><span class='cx-q cx-q-warn'>UNOFFICIAL GREY MARKET PREMIUM</span></p>" +
            "<p>" + esc(gm.message || "No verified GMP source.") + "</p></div>";
        host.innerHTML = "<section class='cx-sec'><h2>" + esc(prof.name || sym) + " — issue file</h2>" +
          "<p class='cx-note'>" + esc((prof.description || "").slice(0, 400)) + "</p>" +
          "<dl class='cx-facts'>" +
          (prof.sector ? "<div><dt>Sector</dt><dd>" + esc(prof.sector) + "</dd></div>" : "") +
          ((val.metrics && val.metrics.pe && val.metrics.pe.value !== null && val.metrics.pe.value !== undefined)
            ? "<div><dt>P/E</dt><dd>" + esc(String(val.metrics.pe.value)) + "</dd></div>" : "") +
          ((val.metrics && val.metrics.market_cap && val.metrics.market_cap.value !== null && val.metrics.market_cap.value !== undefined)
            ? "<div><dt>Market cap</dt><dd>" + esc(String(val.metrics.market_cap.value)) + "</dd></div>" : "") +
          "</dl>" + gmpHtml +
          "<div class='cx-note' style='margin-top:6px'>Structured analysis inputs only — never apply/avoid advice. " +
          "Subscription: " + esc((sb.data && sb.data.length) ? "live figures in Subscription tab" : (sb.message || "unavailable")) + "</div></section>";
        host.scrollIntoView();
      });
    }
  }
  if (window.FT_PAGES) window.FT_PAGES.pIPOs = pIPOs;
  /* ---------- corporate actions page (no browser dialogs, ever) ---------- */
  function pActions() {
    var API = window.FT_API, F = window.FT_FMT;
    function esc2(s) { return F.esc(s === null || s === undefined ? "" : String(s)); }
    $("view").innerHTML = "<h1 class='h-page'>Corporate actions</h1>" +
      "<div class='sub'>Exchange-reported dividends, splits and distributions. Never inferred from price moves.</div>" +
      "<div class='card sect'><div class='row'><input id='ca-s' class='in' aria-label='Symbol' " +
      "placeholder='Symbol e.g. RELIANCE.NS' style='flex:1;min-width:200px'>" +
      "<button class='btn primary' id='ca-go'>Load actions</button></div>" +
      "<div id='ca-out' style='margin-top:10px'></div></div>";
    function go() {
      var sym = ($("ca-s").value || "").trim().toUpperCase();
      if (!sym) { $("ca-out").innerHTML = ""; return; }
      $("ca-out").innerHTML = "<div class='cx-skel'></div><div class='cx-skel'></div>";
      API.get("actions", { symbol: sym }).then(function (r) {
        if (!$("ca-out")) return;
        var b = r.body || {}, d = b.data || {};
        if (!d || (!((d.dividends || []).length) && !((d.splits || []).length))) {
          $("ca-out").innerHTML = "<div class='cx-empty'><b>Corporate actions</b><p>No verified data available.</p>" +
            "<p class='why'>" + esc2(b.message || "No corporate actions reported by configured sources.") + "</p></div>";
          return;
        }
        function rows(list, kind) {
          return list.slice(0, 40).map(function (x, ix) {
            var det = kind === "div"
              ? "Amount " + F.fmtNum(x.amount, 4) + " " + (x.currency || "")
              : "Ratio " + x.numerator + ":" + x.denominator;
            return "<details class='ca-row'><summary><span class='dt'>" + esc2(String(x.date).slice(0, 10)) +
              "</span><span class='tp'>" + (kind === "div" ? "Dividend" : "Split") + "</span>" +
              "<span>" + esc2(det) + "</span></summary>" +
              "<div class='cx-note'>Type: " + (kind === "div" ? "Cash dividend" : "Stock split") +
              " · Detail: " + esc2(det) + " · Source: " + esc2(F.srcName(x.source)) + "</div></details>";
          }).join("");
        }
        $("ca-out").innerHTML = "<h3>Dividends (" + (d.dividends || []).length + ")</h3>" +
          ((d.dividends || []).length ? rows(d.dividends, "div") : "<div class='cx-note'>None reported.</div>") +
          "<h3 style='margin-top:10px'>Splits (" + (d.splits || []).length + ")</h3>" +
          ((d.splits || []).length ? rows(d.splits, "split") : "<div class='cx-note'>None reported.</div>") +
          "<div class='cx-note'>" + esc2(d.note || "") + "</div>";
      });
    }
    $("ca-go").onclick = go;
    $("ca-s").onkeydown = function (e) { if (e.key === "Enter") go(); };
  }
  /* ---------- dashboard: market intelligence (overrides pDashboard) ---------- */
  var SPARK_IDX = [["^NSEI", "Nifty 50"], ["^BSESN", "Sensex"], ["^NSEBANK", "Bank Nifty"],
    ["^CNXIT", "Nifty IT"], ["^GSPC", "S&P 500"], ["^IXIC", "Nasdaq"]];
  var SECTORS = [["^CNXIT", "IT"], ["^CNXAUTO", "Auto"], ["^CNXFMCG", "FMCG"],
    ["^CNXPHARMA", "Pharma"], ["^NSEBANK", "Bank"]];
  /* ---------- dashboard: analytical workspace (overrides pDashboard) ----------
     Flow: pulse -> performance -> heatmap -> breadth/movers -> regime/news. */
  var SPARK_IDX = [["^NSEI", "Nifty 50"], ["^BSESN", "Sensex"], ["^NSEBANK", "Bank Nifty"],
    ["^CNXIT", "Nifty IT"], ["^GSPC", "S&P 500"], ["^IXIC", "Nasdaq"]];
  var SECTORS = [["^CNXIT", "IT"], ["^CNXAUTO", "Auto"], ["^CNXFMCG", "FMCG"],
    ["^CNXPHARMA", "Pharma"], ["^NSEBANK", "Banking"]];
  function pDashboard() {
    var API = window.FT_API, F = window.FT_FMT, V = window.FT_VIZ, I = window.FT_INTERP;
    function esc2(s) { return F.esc(s === null || s === undefined ? "" : String(s)); }
    $("view").innerHTML = "<h1 class='h-page'>Market dashboard</h1>" +
      "<div class='sub'>Delayed market data · every visual answers what changed and by how much</div>" +
      "<section aria-label='Market pulse'><h2>Market pulse</h2><div class='pulse' id='d-pulse'>" +
      SPARK_IDX.map(function () { return "<div class='pcell'><div class='cx-skel'></div></div>"; }).join("") +
      "</div><div id='d-pulsesrc'></div></section>" +
      "<section aria-label='Market indicators' style='margin-top:12px'><h2>Market indicators</h2>" +
      "<div class='pulse' id='d-ind'>" +
      ["Gold", "Silver", "Crude", "USD/INR", "Volatility", "Crypto"].map(function () {
        return "<div class='pcell'><div class='cx-skel'></div></div>";
      }).join("") + "</div><div id='d-indsrc'></div></section>" +
      "<div class='an-grid' style='margin-top:12px'>" +
      "<div class='an-8'><section aria-label='Market performance'><h2>Market performance</h2>" +
      "<div class='card'><div id='d-perf'></div><div id='d-perfnote'></div></div></section></div>" +
      "<div class='an-4'><section aria-label='Market regime'><h2>Market regime</h2>" +
      "<div class='card'><div id='d-regime'></div></div></section></div>" +
      "<div class='an-4'><section aria-label='Sector heatmap'><h2>Sector heatmap</h2>" +
      "<div class='card'><div id='d-heat'></div><div id='d-heatnote'></div></div></section></div>" +
      "<div class='an-8'><section aria-label='Market breadth'><h2>Market breadth</h2>" +
      "<div class='card'><div id='d-breadth'></div></div></section></div>" +
      "<div class='an-4'><section aria-label='Top gainers'><h2>Top gainers</h2>" +
      "<div class='card'><div id='d-gain'></div></div></section></div>" +
      "<div class='an-4'><section aria-label='Top losers'><h2>Top losers</h2>" +
      "<div class='card'><div id='d-lose'></div></div></section></div>" +
      "<div class='an-4'><section aria-label='Most active'><h2>Most active</h2>" +
      "<div class='card'><div id='d-vol'></div></div></section></div>" +
      "<div class='an-8'><section aria-label='Index structure'><h2>Nifty 50 structure</h2>" +
      "<div class='card'><div id='d-struct'></div></div></section></div>" +
      "<div class='an-8'><section aria-label='Latest news'><h2>Latest market news</h2>" +
      "<div class='card'><div id='d-news'></div></div></section></div>" +
      "<div class='an-4'><section aria-label='IPO pulse'><h2>IPO pulse</h2>" +
      "<div class='card'><div id='d-ipo'></div></div></section></div>" +
      "</div>";
    var quotes = {}, hists = {};
    function q(sym) { return (quotes[sym] || {}).quote || {}; }
    function ret(closes, back) {
      if (!closes || closes.length < back + 1) return null;
      var now = closes[closes.length - 1], old = closes[closes.length - 1 - back];
      if (now === null || old === null || !old) return null;
      return (now - old) / Math.abs(old) * 100;
    }
    API.get("market-overview").then(function (r) {
      var items = ((r.body || {}).items) || [];
      items.forEach(function (i) { quotes[i.symbol] = i; });
            paintPulse();
      paintMovers();
      paintIndicators();      var needed = SPARK_IDX.map(function (p) { return p[0]; });
      var done = 0;
      needed.forEach(function (s) {
        API.get("history", { symbol: s, range: "1Y", interval: "1d" }).then(function (h) {
          var bars = (((h.body || {}).data) || {}).bars || [];
          hists[s] = bars.map(function (b) { return b.c; });
          if (++done === needed.length) paintHist();
          else paintPulseSparks();
        }).catch(function () { if (++done === needed.length) paintHist(); });
      });
    });
    /* Heavy indicators: gold, silver, crude, FX, VIX, crypto, rates.
       One backend call; each tile omitted if its quote is missing. */
    function paintIndicators() {
      var host = $("d-ind");
      if (!host) return;
      API.get("indicators").then(function (r) {
        if (!$("d-ind")) return;
        var items = ((r.body || {}).items) || [];
        var cells = [];
        items.forEach(function (it) {
          if (!V.hasV(it.price)) return;
          cells.push("<div class='pcell'><div class='pnm'>" + esc2(it.label) + "</div>" +
            "<div class='pvl'>" + F.fmtNum(it.price) + " <small>" + esc2(it.currency || "") + "</small></div>" +
            "<div class='" + F.dirClass(it.change_pct) + "' style='font-weight:650'>" + F.fmtPct(it.change_pct) + "</div></div>");
        });
        host.innerHTML = cells.join("");
        var src = items.filter(function (it) { return V.hasV(it.price); })[0] || {};
        $("d-indsrc").innerHTML = V.srcLine({ label: "Market data", source: "yahoo", timeliness: "delayed", asOf: src.as_of });
      }).catch(function () { if ($("d-ind")) $("d-ind").innerHTML = ""; });
    }
    function paintPulse() {
      var host = $("d-pulse");
      if (!host) return;
      var cells = [];
      SPARK_IDX.forEach(function (p, ix) {
        var v = q(p[0]);
        if (!V.hasV(v.price)) return;
        cells.push("<div class='pcell'><div class='pnm'>" + p[1] + "</div>" +
          "<div class='pvl'>" + F.fmtNum(v.price) + "</div>" +
          "<div class='" + F.dirClass(v.change_pct) + "' style='font-weight:650'>" + F.fmtPct(v.change_pct) + "</div>" +
          "<canvas class='spark' id='sp-" + ix + "' aria-hidden='true'></canvas></div>");
      });
      host.innerHTML = cells.join("");
      var first = q("^NSEI");
      $("d-pulsesrc").innerHTML = V.srcLine({ label: "Market data", source: "yahoo", timeliness: "delayed", asOf: first.as_of });
      paintPulseSparks();
    }
    function paintPulseSparks() {
      SPARK_IDX.forEach(function (p, ix) {
        var cv = $("sp-" + ix), cl = hists[p[0]];
        if (!cv || !cl || cl.length < 5) return;
        window.FT_CHART.drawSpark(cv, cl, cl[cl.length - 1] >= cl[0]);
      });
    }
    function paintHist() {
      paintPulseSparks();
      var host = $("d-perf");
      if (host) {
        var rows = [];
        SPARK_IDX.forEach(function (p) {
          var cl = hists[p[0]] || [];
          var m = ret(cl, 21);
          if (m !== null) rows.push({ label: p[1], value: m, display: F.fmtPct(m) });
        });
        host.innerHTML = V.bars(rows) ||
          V.emptyFeature("Market performance", "Not enough verified history to compute returns.");
        var note = I.trend("Nifty 50", hists["^NSEI"] || [], "the last month of verified closes");
        $("d-perfnote").innerHTML = note ? "<p class='interp'>" + esc2(note) + "</p>" : "";
      }
      var heat = $("d-heat");
      if (heat) {
        var tiles = SECTORS.map(function (p) {
          var v = q(p[0]);
          return { label: p[1], value: v.change_pct, sub: "NSE sector index" };
        });
        heat.innerHTML = V.heatmap(tiles, { fmt: function (v) { return F.fmtPct(v); } }) ||
          V.emptyFeature("Sector heatmap", "Sector index quotes are unavailable.");
        var hh = $("d-heatnote");
        if (hh && tiles.some(function (t) { return V.hasV(t.value); })) {
          var worst = tiles.slice().sort(function (a, b) { return a.value - b.value; })[0];
          var best = tiles.slice().sort(function (a, b) { return b.value - a.value; })[0];
          hh.innerHTML = "<p class='interp'>" + esc2(best.label + " leads at " + F.fmtPct(best.value) +
            " while " + worst.label + " trails at " + F.fmtPct(worst.value) + ". Equal-size tiles: performance only, no weight data.") + "</p>";
        }
      }
      var rg = $("d-regime");
      if (rg) {
        var cl = hists["^NSEI"] || [];
        var m1m = ret(cl, 21), m3m = ret(cl, 63);
        var sma200 = cl.length > 200 ? cl.slice(-200).reduce(function (a, b) { return a + b; }, 0) / 200 : null;
        var last = cl.length ? cl[cl.length - 1] : null;
        var trendState = (m3m === null) ? null : (m3m >= 5 ? "Bullish" : m3m <= -5 ? "Bearish" : "Neutral");
        var dist = (last !== null && sma200) ? (last - sma200) / sma200 * 100 : null;
        var cells = [
          { label: "Trend", value: trendState, sub: "3M Nifty move" },
          { label: "Momentum", value: m1m === null ? null : F.fmtPct(m1m), sub: "1M Nifty" },
          { label: "Distance from 200D", value: dist === null ? null : F.fmtPct(dist), sub: "SMA" },
        ];
        var rtext = I.regime({ trend: trendState ? trendState.toLowerCase() : null,
          momentum: m1m === null ? null : (m1m >= 0 ? "positive" : "negative") });
        rg.innerHTML = V.kpiStrip(cells) + (rtext ? "<p class='interp'>" + esc2(rtext) + "</p>" : "");
      }
      var st = $("d-struct");
      if (st) {
        var nq = q("^NSEI");
        var hi = nq.fifty_two_week_high, lo = nq.fifty_two_week_low, px = nq.price;
        var pos = (hi && lo && px && hi !== lo) ? Math.round((px - lo) / (hi - lo) * 100) : null;
        st.innerHTML = V.kpiStrip([
          { label: "52-week high", value: V.hasV(hi) ? F.fmtNum(hi) : null },
          { label: "52-week low", value: V.hasV(lo) ? F.fmtNum(lo) : null },
          { label: "Position in range", value: pos === null ? null : pos + "%" },
        ]) + (pos !== null ? "<p class='interp'>Nifty 50 sits " + pos + "% up its 52-week range.</p>" : "");
      }
    }
    function moverRows(list) {
      return list.map(function (i) {
        var c = i.quote;
        return "<li><span class='rk'>·</span><span><a href='#/company/" + esc2(i.symbol) + "'>" +
          esc2(c.name || i.symbol) + "</a> <span class='tk'>" + esc2(i.symbol) + "</span></span>" +
          "<b>" + F.fmtNum(c.price) + "</b><b class='" + F.dirClass(c.change_pct) + "'>" + F.fmtPct(c.change_pct) + "</b></li>";
      }).join("");
    }
    function paintMovers() {
      var eq = Object.keys(quotes).map(function (s) { return quotes[s]; })
        .filter(function (i) { return i.quote && V.hasV(i.quote.price) && i.symbol.charAt(0) !== "^" && !/NIFTY_FIN/.test(i.symbol); });
      function put(id, list, note) {
        var host = $(id);
        if (!host) return;
        host.innerHTML = list.length ? "<ul class='ranklist'>" + moverRows(list.slice(0, 6)) + "</ul>" + (note || "") : "";
      }
      var gains = eq.slice().sort(function (a, b) { return (b.quote.change_pct || -1e9) - (a.quote.change_pct || -1e9); });
      var losers = eq.slice().sort(function (a, b) { return (a.quote.change_pct || 1e9) - (b.quote.change_pct || 1e9); });
      var vols = eq.slice().sort(function (a, b) { return (b.quote.volume || 0) - (a.quote.volume || 0); });
      put("d-gain", gains.filter(function (i) { return (i.quote.change_pct || 0) > 0; }));
      put("d-lose", losers.filter(function (i) { return (i.quote.change_pct || 0) < 0; }));
      put("d-vol", vols, "<div class='cx-note'>By reported volume.</div>");
      var adv = eq.filter(function (i) { return (i.quote.change_pct || 0) > 0; }).length;
      var dec = eq.filter(function (i) { return (i.quote.change_pct || 0) < 0; }).length;
      var unch = eq.length - adv - dec;
      var bh = $("d-breadth");
      if (bh) {
        var total = adv + dec + unch;
        var I2 = window.FT_INTERP;
        function bar(l, v, col) {
          var w = total ? Math.round(v / total * 100) : 0;
          return "<div class='bar-row'><span>" + l + "</span>" +
            "<span class='tr'><span class='fl' style='display:block;width:" + w + "%;background:" + col + "'></span></span><b>" + v + "</b></div>";
        }
        bh.innerHTML = bar("Advancing", adv, "var(--up)") + bar("Declining", dec, "var(--dn)") + bar("Unchanged", unch, "var(--faint)") +
          "<p class='interp'>" + esc2(I2.breadth(adv, dec, unch, "the tracked universe") +
            " Tracked universe — a participation proxy, not full market breadth.") + "</p>";
      }
    }
    API.get("news", { limit: 6 }).then(function (r) {
      var host = $("d-news");
      if (!host) return;
      var items = (((r.body || {}).data) || {}).items || [];
      host.innerHTML = items.length ? items.slice(0, 6).map(function (n) {
        var t = n.url ? "<a href='" + esc2(n.url) + "' target='_blank' rel='noopener'>" + esc2(n.title || "") + "</a>" : esc2(n.title || "");
        var sum = n.summary ? esc2(String(n.summary).slice(0, 130)) : "";
        return "<article class='news-item'>" + t + (sum ? "<p class='sum'>" + sum + "</p>" : "") +
          "<div class='meta'>" + esc2(n.source || "") + " · " + esc2(F.fmtTimeHM(n.published_at)) + "</div></article>";
      }).join("") : "";
    });
    API.get("ipo").then(function (r) {
      var host = $("d-ipo");
      if (!host) return;
      var b = (r.body || {}).buckets || null;
      if (!b) { host.innerHTML = ""; return; }
      function n(k) { return (b[k] || []).length; }
      var cells = [];
      if (n("open")) cells.push({ label: "Open", value: n("open") });
      if (n("upcoming")) cells.push({ label: "Upcoming", value: n("upcoming") });
      if (n("listed")) cells.push({ label: "Listed", value: n("listed") });
      host.innerHTML = V.kpiStrip(cells) + "<p class='interp'><a href='#/ipos'>Open IPO dashboard →</a></p>";
    });
  }
  if (window.FT_PAGES) window.FT_PAGES.pDashboard = pDashboard;

  if (window.FT_PAGES) window.FT_PAGES.pActions = pActions;
  /* ---------- compare: analytical rebuild (overrides pCompare) ----------
     Visual bars first, performance chart, trends, dynamic table last.
     A row renders only when >=1 company has the metric. Calculated
     values come from the canonical ratio sheet — never recomputed. */
  function pCompare() {
    var API = window.FT_API, F = window.FT_FMT, V = window.FT_VIZ, I = window.FT_INTERP;
    function esc2(s) { return F.esc(s === null || s === undefined ? "" : String(s)); }
    var preset = "";
    try { preset = sessionStorage.getItem("ft-cmp") || ""; sessionStorage.removeItem("ft-cmp"); } catch (e) { /* ignore */ }
    $("view").innerHTML = "<h1 class='h-page'>Compare</h1>" +
      "<div class='sub'>Evidence side-by-side. No winner scores, no rankings.</div>" +
      "<div class='card'><div class='row'><input id='k-s' class='in' aria-label='Symbols' style='flex:1;min-width:220px' " +
      "placeholder='Comma-separated, e.g. RELIANCE.NS, TCS.NS, INFY.NS' value='" + esc2(preset || "RELIANCE.NS,TCS.NS,INFY.NS") + "'>" +
      "<button class='btn primary' id='k-go'>Compare</button></div><div id='k-out' style='margin-top:10px'></div></div>";
    function numOf(v) {
      if (v === null || v === undefined) return null;
      if (typeof v === "string" && /^(none|null|undefined|nan|-|n\/a)$/i.test(v.trim())) return null;
      var n = Number(v);
      return isNaN(n) ? null : n;
    }
    function go() {
      var syms = $("k-s").value.split(",").map(function (s) { return s.trim().toUpperCase(); }).filter(Boolean).slice(0, 4);
      if (syms.length < 2) { $("k-out").innerHTML = "<div class='cx-note'>Enter at least 2 symbols.</div>"; return; }
      $("k-out").innerHTML = "<div class='cx-skel'></div><div class='cx-skel'></div><div class='cx-skel'></div>";
      Promise.all(syms.map(function (s) {
        return Promise.all([
          API.get("quote", { symbol: s }),
          API.get("ratios", { symbol: s }),
          API.get("ratiosheet", { symbol: s }).catch(function () { return { body: null }; }),
          API.get("fundamentals", { symbol: s, statement: "income", period: "annual" }).catch(function () { return { body: null }; }),
          API.get("history", { symbol: s, range: "1Y", interval: "1d" }).catch(function () { return { body: null }; }),
        ]).then(function (x) {
          return { symbol: s, quote: ((x[0].body || {}).data) || null,
            rep: ((x[1].body || {}).data) || {},
            sheet: ((((x[2] || {}).body) || {}).data) || null,
            fin: ((((x[3] || {}).body) || {}).data) || null,
            hist: ((((x[4] || {}).body) || {}).data) || null };
        });
      })).then(function (cols) {
        if (!$("k-out")) return;
        paint(cols);
      }).catch(function () {
        if ($("k-out")) $("k-out").innerHTML = "<div class='cx-empty'><b>Compare</b><p>One or more legs failed. Other pages remain available.</p></div>";
      });
    }
    function repVal(c, key) { return numOf(c.rep[key]); }
    function calcVal(c, key) {
      var d = (c.sheet && c.sheet.display) || {};
      var n = d[key];
      return (n && n.value !== null && n.value !== undefined) ? Number(n.value) : null;
    }
    function metricVal(c, repKey, calcKey) {
      var r = repVal(c, repKey);
      return r !== null ? { v: r, kind: "REPORTED" } : (calcVal(c, calcKey) !== null ? { v: calcVal(c, calcKey), kind: "CALCULATED" } : null);
    }
    function growth(c, item) {
      var reps = ((c.fin || {}).reports) || [];
      var keys = item === "rev" ? ["totalRevenue", "revenue", "revenues", "sales"] : ["netIncome", "net_income", "netEarnings"];
      function val(r) {
        for (var i = 0; i < keys.length; i++) {
          var n = numOf(r[keys[i]]);
          if (n !== null) return n;
        }
        return null;
      }
      if (reps.length < 2) return null;
      var a = val(reps[0]), b = val(reps[1]);
      if (a === null || b === null || !b) return null;
      return (a - b) / Math.abs(b) * 100;
    }
    function barSection(title, defs, cols, fmt) {
      var rows = defs.map(function (d) {
        var vals = cols.map(function (c) { return metricVal(c, d.rep, d.calc); });
        if (vals.every(function (x) { return !x; })) return null; // omit empty rows
        return { label: d.label, vals: vals };
      }).filter(Boolean);
      if (!rows.length) return "";
      var mx = 0;
      rows.forEach(function (r) { r.vals.forEach(function (x) { if (x && Math.abs(x.v) > mx) mx = Math.abs(x.v); }); });
      mx = mx || 1;
      var h = "<section aria-label='" + esc2(title) + "'><h2>" + esc2(title) + "</h2><div class='card'>";
      rows.forEach(function (r) {
        h += "<div style='margin:8px 0'><div class='lbl'>" + esc2(r.label) + "</div>";
        r.vals.forEach(function (x, ix) {
          if (!x) return;
          var w = Math.max(2, Math.round(Math.abs(x.v) / mx * 100));
          h += "<div class='cmpbar'><span title='" + esc2(cols[ix].symbol) + "'>" + esc2(cols[ix].symbol.replace(/\.(NS|BO)$/, "")) +
            (x.kind === "CALCULATED" ? " <span class='cx-q cx-q-calc'>CALC</span>" : "") + "</span>" +
            "<span class='tr'><span class='fl' style='left:0;width:" + w + "%;background:" +
            (x.v >= 0 ? "var(--acc)" : "var(--dn)") + "'></span></span>" +
            "<b>" + fmt(x.v) + "</b></div>";
        });
        h += "</div>";
      });
      return h + "</div></section>";
    }
    function paint(cols) {
      var host = $("k-out");
      var h = "<div class='seg' style='margin-bottom:8px'>" + cols.map(function (c) {
        var nm = ((c.quote || {}).name) || c.symbol;
        return "<a class='btn sm' href='#/company/" + esc2(c.symbol) + "'>" + esc2(nm) + "</a>";
      }).join("") + "</div>";
      function f1(v) { return v === null ? "" : v.toFixed(1) + "x"; }
      function f2(v) { return v === null ? "" : v.toFixed(1) + "%"; }
      function fM(v, ccy) { return v === null ? "" : F.fmtMoney(v); }
      h += barSection("Valuation", [
        { label: "P/E", rep: "PERatio", calc: "pe_calc" },
        { label: "P/B", rep: "PriceToBookRatio", calc: "pb_calc" },
        { label: "Dividend yield", rep: "DividendYield", calc: "div_yield_calc" },
      ], cols, function (v) { return v.toFixed(2); });
      h += barSection("Profitability", [
        { label: "ROE", rep: "ROE", calc: "roe" },
        { label: "ROCE", rep: null, calc: "roce" },
        { label: "Net margin", rep: "ProfitMargin", calc: "net_margin" },
      ], cols, function (v) { return v.toFixed(1) + "%"; });
      /* growth bars from reported statements */
      var grows = [["Revenue growth", "rev"], ["PAT growth", "ni"]].map(function (g) {
        var vals = cols.map(function (c) {
          var v = growth(c, g[1]);
          return v === null ? null : { v: v, kind: "REPORTED" };
        });
        return vals.every(function (x) { return !x; }) ? null : { label: g[0], vals: vals };
      }).filter(Boolean);
      if (grows.length) {
        h += "<section aria-label='Growth'><h2>Growth</h2><div class='card'>";
        grows.forEach(function (r) {
          var mx = Math.max.apply(null, r.vals.map(function (x) { return x ? Math.abs(x.v) : 0; }).concat([1]));
          h += "<div style='margin:8px 0'><div class='lbl'>" + r.label + " (YoY)</div>";
          r.vals.forEach(function (x, ix) {
            if (!x) return;
            var w = Math.max(2, Math.round(Math.abs(x.v) / mx * 100));
            h += "<div class='cmpbar'><span>" + esc2(cols[ix].symbol.replace(/\.(NS|BO)$/, "")) + "</span>" +
              "<span class='tr'><span class='fl' style='left:0;width:" + w + "%;background:" +
              (x.v >= 0 ? "var(--up)" : "var(--dn)") + "'></span></span><b>" + F.fmtPct(x.v) + "</b></div>";
          });
          h += "</div>";
        });
        h += "</div></section>";
      }
      h += barSection("Balance sheet", [
        { label: "Debt / Equity", rep: null, calc: "debt_equity" },
        { label: "Current ratio", rep: null, calc: "current_ratio" },
      ], cols, function (v) { return v.toFixed(2) + "x"; });
      /* performance lines (normalized to 100) */
      var perf = cols.map(function (c) {
        var bars = ((c.hist || {}).bars) || [];
        var cl = bars.map(function (b) { return b.c; }).filter(function (v) { return v !== null && v !== undefined; });
        if (cl.length < 20) return null;
        var base = cl[0];
        return { name: c.symbol.replace(/\.(NS|BO)$/, ""), values: cl.map(function (v) { return v / base * 100; }) };
      }).filter(Boolean);
      if (perf.length >= 2) {
        var cid = "cmp-perf";
        h += "<section aria-label='Price performance'><h2>Price performance (rebased = 100)</h2>" +
          "<div class='card'><canvas class='chart' id='" + cid + "' style='height:220px' role='img' aria-label='Rebased price comparison'></canvas>" +
          V.srcLine({ label: "Market data", source: "yahoo", timeliness: "delayed" }) + "</div></section>";
      }
      /* detailed table, last and dynamic */
      var detDefs = [
        ["Price", function (c) { return (c.quote || {}).price !== null && (c.quote || {}).price !== undefined ? F.fmtNum(c.quote.price) : null; }],
        ["Market cap", function (c) { var v = repVal(c, "MarketCapitalization"); return v === null ? null : F.fmtIN(v, (c.quote || {}).currency); }],
        ["P/E", function (c) { var m = metricVal(c, "PERatio", "pe_calc"); return m ? m.v.toFixed(1) + "x" : null; }],
        ["EPS", function (c) { var v = repVal(c, "EPS"); return v === null ? null : F.fmtNum(v); }],
        ["ROE", function (c) { var m = metricVal(c, "ROE", "roe"); return m ? m.v.toFixed(1) + "%" : null; }],
        ["Book value", function (c) { var v = repVal(c, "BookValue"); return v === null ? null : F.fmtNum(v); }],
        ["Dividend yield", function (c) { var v = repVal(c, "DividendYield"); return v === null ? null : Number(v).toFixed(2) + "%"; }],
      ];
      var detRows = detDefs.map(function (d) {
        var vals = cols.map(d[1]);
        return vals.every(function (x) { return x === null; }) ? null : { label: d[0], vals: vals };
      }).filter(Boolean);
      if (detRows.length) {
        h += "<section aria-label='Detailed table'><h2>Detailed table</h2><div class='cx-scroll'><table class='cx-t'><thead><tr><th scope='col'>Metric</th>" +
          cols.map(function (c) { return "<th scope='col' class='num'>" + esc2(c.symbol) + "</th>"; }).join("") +
          "</tr></thead><tbody>" + detRows.map(function (r) {
            return "<tr><td>" + esc2(r.label) + "</td>" + r.vals.map(function (v) {
              return "<td class='num'>" + (v === null ? "" : esc2(v)) + "</td>";
            }).join("") + "</tr>";
          }).join("") + "</tbody></table></div></section>";
      }
      host.innerHTML = h || V.emptyFeature("Compare", "None of the selected companies returned comparable data.");
      if (perf.length >= 2 && $("cmp-perf")) {
        window.FT_CHART.drawLines($("cmp-perf"), { labels: [], series: perf });
      }
    }
    $("k-go").onclick = go;
    $("k-s").onkeydown = function (e) { if (e.key === "Enter") go(); };
    go();
  }
  if (window.FT_PAGES) window.FT_PAGES.pCompare = pCompare;
  /* ---------- mutual fund page (AMFI NAV via mfapi.in, free) ---------- */
  function pMF(code) {
    var API = window.FT_API, F = window.FT_FMT;
    code = String(code || "").replace(/^MF:/i, "");
    $("view").innerHTML = "<h1 class='h-page'>Mutual fund</h1>" +
      "<div class='sub'>AMFI-published NAV history · not a live tradable price</div>" +
      "<div class='card' id='mf-out'><div class='cx-skel'></div><div class='cx-skel'></div></div>";
    API.get("mf/scheme", { code: code, points: 365 }).then(function (r) {
      if (!$("mf-out")) return;
      var b = r.body || {}, d = b.data || {};
      if (!d.bars || !d.bars.length) {
        $("mf-out").innerHTML = "<div class='cx-empty'><b>Mutual fund</b><p>No verified data available.</p>" +
          "<p class='why'>" + F.esc(b.message || "Scheme not found.") + "</p></div>";
        return;
      }
      var bars = d.bars.map(function (p, i) {
        return { t: i, c: p.nav, o: p.nav, h: p.nav, l: p.nav, v: null };
      });
      var first = d.bars[0].nav, last = d.bars[d.bars.length - 1].nav;
      var chg = first ? (last - first) / first * 100 : null;
      $("mf-out").innerHTML = "<h3>" + F.esc(d.scheme_name || ("Scheme " + code)) + "</h3>" +
        "<div class='kstrip big'><div class='kpi'><div class='k-l'>Latest NAV</div>" +
        "<div class='k-v'>" + F.fmtNum(d.latest_nav) + "</div>" +
        "<div class='k-s'>" + F.esc(d.latest_date || "") + "</div></div>" +
        (chg !== null ? "<div class='kpi'><div class='k-l'>Change (" + d.bars.length + " sessions)</div>" +
          "<div class='k-v " + F.dirClass(chg) + "'>" + F.fmtPct(chg) + "</div></div>" : "") +
        "</div><div class='cx-note'>" + F.esc(d.fund_house || "") +
        (d.scheme_category ? " · " + F.esc(d.scheme_category) : "") + "</div>" +
        "<div class='chart-box' style='margin-top:10px'><canvas class='chart' id='mf-c' style='height:230px' role='img' aria-label='NAV history'></canvas><div class='chart-tip'></div></div>" +
        "<div class='cx-prov'>Data · mfapi.in (AMFI) · end-of-day</div>";
      if ($("mf-c")) window.FT_CHART.drawPriceChart($("mf-c"), bars, { sma: [] });
    });
  }
  if (window.FT_PAGES) window.FT_PAGES.pMF = pMF;
  /* ---------- markets: indicators strip injected above sections ---------- */
  function marketsStrip() {
    try {
      var host = document.getElementById("m-sects");
      if (!host || document.getElementById("ind-strip")) return;
      var box = document.createElement("div");
      box.className = "card";
      box.id = "ind-strip";
      box.innerHTML = "<h3>Market indicators</h3><div class='pulse' id='ind-cells'></div>";
      host.parentNode.insertBefore(box, host);
      window.FT_API.get("indicators").then(function (r) {
        var el = document.getElementById("ind-cells");
        if (!el) return;
        var items = ((r.body || {}).items) || [];
        var groups = { metal: [], energy: [], fx: [], volatility: [], crypto: [], rates: [] };
        items.forEach(function (it) {
          if (it.price === null || it.price === undefined) return;
          (groups[it.kind] || (groups[it.kind] = [])).push(it);
        });
        var F = window.FT_FMT;
        function cell(it) {
          return "<div class='pcell'><div class='pnm'>" + F.esc(it.label) + "</div>" +
            "<div class='pvl'>" + F.fmtNum(it.price) + " <small>" + F.esc(it.currency || "") + "</small></div>" +
            "<div class='" + F.dirClass(it.change_pct) + "' style='font-weight:650'>" + F.fmtPct(it.change_pct) + "</div></div>";
        }
        var order = [["metal", "Metals"], ["energy", "Energy"], ["fx", "Currency"], ["volatility", "Volatility"], ["crypto", "Crypto"], ["rates", "Rates"]];
        el.innerHTML = order.map(function (g) {
          if (!(groups[g[0]] || []).length) return "";
          return "<div style='min-width:100%'><div class='lbl' style='margin:6px 0 4px'>" + g[1] + " — " +
            (g[0] === "metal" || g[0] === "energy" ? "India" : "Global") + "</div><div class='pulse'>" +
            groups[g[0]].map(cell).join("") + "</div></div>";
        }).join("") + "<div class='cx-prov'>Data · Yahoo Finance · delayed · India and Global shown in separate groups</div>";
      }).catch(function () { /* strip stays empty */ });
    } catch (e) { /* never break markets */ }
  }
  function theme() {
    try {
      var q = (location.search || "").match(/theme=(light|dark)/);
      var t = q ? q[1] : (localStorage.getItem("ft-theme") || "light");
      document.body.dataset.theme = (t === "dark") ? "dark" : "light";
    } catch (e) { document.body.dataset.theme = "light"; }
  }
  function boot() { theme(); sectionize(); strip(); marketsStrip(); }
  document.addEventListener("DOMContentLoaded", function () { setTimeout(boot, 400); });
  setInterval(boot, 2500);
  window.FT_SHELL = { boot: boot };
})();
