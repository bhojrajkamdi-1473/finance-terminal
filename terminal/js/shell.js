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
            return "<tr><td>" + esc(g.company || "—") + "<br><span class='cx-note'>IPO Guru · unofficial chatter, not a price promise</span></td>" +
              "<td class='num'>₹" + esc(String(g.value)) + "</td><td class='num'>" + esc(String(g.percent === null || g.percent === undefined ? "—" : g.percent + "%")) +
              "</td><td>" + esc(g.updated_at || "—") + "</td></tr>";
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
            function x(v) { return v === null || v === undefined ? "—" : esc(String(v)) + "x"; }
            return "<tr><td>" + esc(s.company || "—") + "</td><td class='num'>" + x(s.qib) + "</td><td class='num'>" + x(s.nii) +
              "</td><td class='num'>" + x(s.retail) + "</td><td class='num'><b>" + x(s.total) + "</b></td><td>" + esc(s.updated_at || "—") + "</td></tr>";
          }).join("") + "</tbody></table></div>";
        return;
      }
      var rows = tab === "Calendar"
        ? Object.keys(buckets).reduce(function (a, k) { return a.concat(buckets[k]); }, [])
        : (buckets[tab.toLowerCase()] || []);
      if (!rows.length) {
        host.innerHTML = "<div class='cx-empty'><b>" + esc(tab) + "</b><p>No verified data available.</p></div>";
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
      return "—";
    }
    function band(w) {
      var lo = pick(w, ["pricerangelow", "pricelow", "lowerband", "floorprice"]);
      var hi = pick(w, ["pricerangehigh", "pricehigh", "upperband", "capprice", "offerprice"]);
      if (lo === "—" && hi === "—") return "—";
      return lo === "—" ? hi : hi === "—" ? lo : lo + " – " + hi;
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
        var gmpHtml = (grow && grow.gmp_value !== null && grow.gmp_value !== undefined)
          ? "<dl class='cx-facts'><div><dt>GMP (unofficial)</dt><dd>₹" + esc(String(grow.gmp_value)) + "</dd></div>" +
            "<div><dt>GMP %</dt><dd>" + esc(String(grow.gmp_percent === null || grow.gmp_percent === undefined ? "—" : grow.gmp_percent + "%")) + "</dd></div>" +
            "<div><dt>Updated</dt><dd>" + esc(grow.gmp_updated_at || "—") + "</dd></div>" +
            (grow.estimated_listing_price !== null && grow.estimated_listing_price !== undefined ?
              "<div><dt>Indicative listing</dt><dd>₹" + esc(String(grow.estimated_listing_price)) + " (indicative GMP-derived estimate)</dd></div>" : "") + "</dl>"
          : "<div class='cx-empty'><b>Grey market premium</b>" +
            "<p><span class='cx-q cx-q-warn'>UNOFFICIAL GREY MARKET PREMIUM</span></p>" +
            "<p>" + esc(gm.message || "No verified GMP source.") + "</p></div>";
        host.innerHTML = "<section class='cx-sec'><h2>" + esc(prof.name || sym) + " — issue file</h2>" +
          "<p class='cx-note'>" + esc((prof.description || "").slice(0, 400)) + "</p>" +
          "<dl class='cx-facts'><div><dt>Sector</dt><dd>" + esc(prof.sector || "—") + "</dd></div>" +
          "<div><dt>P/E</dt><dd>" + esc((val.metrics && val.metrics.pe && val.metrics.pe.value) || "—") + "</dd></div>" +
          "<div><dt>Market cap</dt><dd>" + esc((val.metrics && val.metrics.market_cap && val.metrics.market_cap.value) || "—") + "</dd></div></dl>" +
          gmpHtml +
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
  if (window.FT_PAGES) window.FT_PAGES.pActions = pActions;
  /* ---------- dashboard: market intelligence (overrides pDashboard) ---------- */
  var SPARK_IDX = [["^NSEI", "Nifty 50"], ["^BSESN", "Sensex"], ["^NSEBANK", "Bank Nifty"],
    ["^CNXIT", "Nifty IT"], ["^GSPC", "S&P 500"], ["^IXIC", "Nasdaq"]];
  var SECTORS = [["^CNXIT", "IT"], ["^CNXAUTO", "Auto"], ["^CNXFMCG", "FMCG"],
    ["^CNXPHARMA", "Pharma"], ["^NSEBANK", "Bank"]];
  function pDashboard() {
    var API = window.FT_API, F = window.FT_FMT;
    function esc2(s) { return F.esc(s === null || s === undefined ? "" : String(s)); }
    $("view").innerHTML = "<h1 class='h-page'>Market dashboard</h1>" +
      "<div class='sub'>Delayed market data · sparklines from verified history · auto-refresh 60s</div>" +
      "<section aria-label='Market snapshot'><h2>Market snapshot</h2><div class='idx-grid' id='d-idx'>" +
      SPARK_IDX.map(function () { return "<div class='idx-card'><div class='cx-skel'></div></div>"; }).join("") +
      "</div><div id='d-interp' style='margin-top:8px'></div></section>" +
      "<div class='dash-grid' style='margin-top:12px'><div>" +
      "<section aria-label='Market movers'><h2>Market movers</h2>" +
      "<div class='seg' role='group' aria-label='Movers filter' id='d-seg'>" +
      "<button data-m='gain' class='on'>Gainers</button><button data-m='lose'>Losers</button>" +
      "<button data-m='vol'>Volume</button></div>" +
      "<div class='card' style='margin-top:8px'><div id='d-mov'></div></div>" +
      "<div id='d-breadth' style='margin-top:8px'></div></div>" +
      "<section aria-label='Sector performance' style='margin-top:12px'><h2>Sector performance</h2>" +
      "<div class='card'><div id='d-sect'></div></div></section>" +
      "</div><div>" +
      "<section aria-label='Latest news'><h2>Latest market news</h2><div class='card'><div id='d-news'></div></div></section>" +
      "<section aria-label='IPO pulse' style='margin-top:12px'><h2>IPO pulse</h2><div class='card'><div id='d-ipo'></div></div></section>" +
      "</div></div>";
    var quotes = {};
    API.get("market-overview").then(function (r) {
      var items = ((r.body || {}).items) || [];
      items.forEach(function (i) { quotes[i.symbol] = i; });
      paintCards();
      paintMovers("gain");
      paintSectors();
      SPARK_IDX.forEach(function (p, ix) { spark(p[0], ix); });
    });
    function q(sym) { return (quotes[sym] || {}).quote || {}; }
    function paintCards() {
      var host = $("d-idx");
      if (!host) return;
      host.innerHTML = SPARK_IDX.map(function (p, ix) {
        var v = q(p[0]);
        if (v.price === null || v.price === undefined) {
          return "<div class='idx-card'><div class='nm'>" + p[1] + "</div><div class='vl'>—</div>" +
            "<div class='ft'>No verified quote.</div></div>";
        }
        var cls = F.dirClass(v.change_pct);
        return "<div class='idx-card'><div class='nm'>" + p[1] + "</div>" +
          "<div class='vl'>" + F.fmtNum(v.price) + "</div>" +
          "<div class='" + cls + "' style='font-size:13px;font-weight:650'>" + F.fmtPct(v.change_pct) + "</div>" +
          "<canvas class='spark' id='sp-" + ix + "' aria-hidden='true'></canvas>" +
          "<div class='ft'>" + esc2(F.srcName((quotes[p[0]] || {}).source || v.source)) + " · delayed</div></div>";
      }).join("");
    }
    function spark(sym, ix) {
      API.get("history", { symbol: sym, range: "3M", interval: "1d" }).then(function (r) {
        var cv = $("sp-" + ix);
        if (!cv) return;
        var bars = (((r.body || {}).data) || {}).bars || [];
        var closes = bars.map(function (b) { return b.c; });
        if (closes.length < 5) return;
        var up = closes[closes.length - 1] >= closes[0];
        window.FT_CHART.drawSpark(cv, closes, up);
        if (ix === 0) {
          var m = (closes[closes.length - 1] - closes[0]) / closes[0] * 100;
          var el = $("d-interp");
          if (el) el.innerHTML = "<p class='interp'>Nifty 50 " +
            (m >= 0 ? "gained " + F.fmtPct(m) : "lost " + F.fmtPct(m)) +
            " over the last 3 months of verified closes (" + bars.length + " sessions).</p>";
        }
      }).catch(function () { /* card keeps quote; spark optional */ });
    }
    function paintMovers(mode) {
      var host = $("d-mov");
      if (!host) return;
      var eq = Object.keys(quotes).map(function (s) { return quotes[s]; })
        .filter(function (i) { return i.quote && i.symbol.charAt(0) !== "^" && !/NIFTY_FIN/.test(i.symbol); });
      eq.sort(function (a, b) {
        if (mode === "lose") return (a.quote.change_pct || 0) - (b.quote.change_pct || 0);
        if (mode === "vol") return (b.quote.volume || 0) - (a.quote.volume || 0);
        return (b.quote.change_pct || 0) - (a.quote.change_pct || 0);
      });
      host.innerHTML = '<table class="t"><thead><tr><th scope="col">Company</th><th scope="col" class="num">Price</th>' +
        '<th scope="col" class="num">Change %</th><th scope="col" class="num">Volume</th></tr></thead><tbody>' +
        eq.slice(0, 8).map(function (i) {
          var c = i.quote;
          return "<tr data-sym='" + esc2(i.symbol) + "' style='cursor:pointer'><td class='txt'><a href='#/company/" +
            esc2(i.symbol) + "'>" + esc2(c.name || i.symbol) + "</a><br><span class='tk'>" + esc2(i.symbol) + "</span></td>" +
            "<td class='num'><b>" + F.fmtNum(c.price) + "</b></td>" +
            "<td class='num " + F.dirClass(c.change_pct) + "'>" + F.fmtPct(c.change_pct) + "</td>" +
            "<td class='num'>" + F.fmtInt(c.volume) + "</td></tr>";
        }).join("") + "</tbody></table>";
      var adv = eq.filter(function (i) { return (i.quote.change_pct || 0) > 0; }).length;
      var dec = eq.filter(function (i) { return (i.quote.change_pct || 0) < 0; }).length;
      var bh = $("d-breadth");
      if (bh) bh.innerHTML = "<div class='card'><h3>Market breadth</h3><div class='bar-row'><span>Advances</span>" +
        "<span class='tr'><span class='fl' style='display:block;width:" + pct(adv, adv + dec) + "%;background:var(--up)'></span></span><b>" + adv + "</b></div>" +
        "<div class='bar-row'><span>Declines</span>" +
        "<span class='tr'><span class='fl' style='display:block;width:" + pct(dec, adv + dec) + "%;background:var(--dn)'></span></span><b>" + dec + "</b></div>" +
        "<p class='interp'>" + (adv > dec ? "Breadth is positive: more tracked stocks advanced than declined."
          : adv < dec ? "Breadth is negative: decliners outnumber advancers in the tracked universe."
          : "Breadth is even across the tracked universe.") + " Tracked universe only — not the whole market.</p></div>";
      Array.prototype.forEach.call(document.querySelectorAll("#d-seg button"), function (b) {
        b.classList.toggle("on", b.getAttribute("data-m") === mode);
        b.onclick = function () { paintMovers(b.getAttribute("data-m")); };
      });
      Array.prototype.forEach.call(host.querySelectorAll("tr[data-sym]"), function (tr) {
        tr.onclick = function () { location.hash = "#/company/" + encodeURIComponent(tr.getAttribute("data-sym")); };
      });
    }
    function pct(a, b) { return b ? Math.round(a / b * 100) : 0; }
    function paintSectors() {
      var host = $("d-sect");
      if (!host) return;
      var rows = SECTORS.map(function (p) {
        var v = q(p[0]);
        return { name: p[1], chg: (v.change_pct === null || v.change_pct === undefined) ? null : v.change_pct };
      }).filter(function (r) { return r.chg !== null; });
      if (!rows.length) { host.innerHTML = "<div class='cx-note'>Sector indices unavailable.</div>"; return; }
      var mx = Math.max.apply(null, rows.map(function (r) { return Math.abs(r.chg); }).concat([1]));
      host.innerHTML = rows.map(function (r) {
        var w = Math.round(Math.abs(r.chg) / mx * 100);
        var col = r.chg >= 0 ? "var(--up)" : "var(--dn)";
        return "<div class='bar-row'><span>" + esc2(r.name) + "</span>" +
          "<span class='tr'><span class='fl' style='display:block;width:" + w + "%;background:" + col + "'></span></span>" +
          "<b class='" + F.dirClass(r.chg) + "'>" + F.fmtPct(r.chg) + "</b></div>";
      }).join("") + "<div class='cx-note'>NSE sector indices as sector proxies · delayed.</div>";
    }
    API.get("news", { limit: 6 }).then(function (r) {
      var host = $("d-news");
      if (!host) return;
      var items = (((r.body || {}).data) || {}).items || [];
      host.innerHTML = items.length ? items.slice(0, 6).map(function (n) {
        var t = n.url ? "<a href='" + esc2(n.url) + "' target='_blank' rel='noopener'>" + esc2(n.title || "") + "</a>" : esc2(n.title || "");
        var sum = n.summary ? esc2(String(n.summary).slice(0, 140)) : "";
        return "<article class='news-item'>" + t + (sum ? "<p class='sum'>" + sum + "</p>" : "") +
          "<div class='meta'>" + esc2(n.source || "") + " · " + esc2(F.fmtTimeHM(n.published_at)) +
          " · <a href='#/news'>Read article →</a></div></article>";
      }).join("") : "<div class='cx-note'>No headlines right now.</div>";
    });
    API.get("ipo").then(function (r) {
      var host = $("d-ipo");
      if (!host) return;
      var b = (r.body || {}).buckets || null;
      if (!b) { host.innerHTML = "<div class='cx-note'>IPO feed unavailable — open the IPO page for status.</div>"; return; }
      function n(k) { return (b[k] || []).length; }
      host.innerHTML = "<div class='bar-row'><span>Open</span><b>" + n("open") + "</b></div>" +
        "<div class='bar-row'><span>Upcoming</span><b>" + n("upcoming") + "</b></div>" +
        "<div class='bar-row'><span>Listed</span><b>" + n("listed") + "</b></div>" +
        "<p class='interp'><a href='#/ipos'>Open IPO dashboard →</a></p>";
    });
  }
  if (window.FT_PAGES) window.FT_PAGES.pDashboard = pDashboard;
  function theme() {
    try {
      var q = (location.search || "").match(/theme=(light|dark)/);
      var t = q ? q[1] : (localStorage.getItem("ft-theme") || "light");
      document.body.dataset.theme = (t === "dark") ? "dark" : "light";
    } catch (e) { document.body.dataset.theme = "light"; }
  }
  function boot() { theme(); sectionize(); strip(); }
  document.addEventListener("DOMContentLoaded", function () { setTimeout(boot, 400); });
  setInterval(boot, 2500);
  window.FT_SHELL = { boot: boot };
})();
