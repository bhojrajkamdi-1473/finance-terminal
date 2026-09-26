/* FT Terminal views — institutional workstation (light DS v2).
   Data contracts preserved: every number keeps source/period/currency
   attribution; missing data renders explicit unavailable states. */
(function () {
  "use strict";
  var API, F;
  function init() { API = window.FT_API; F = window.FT_FMT; }
  function el(id) { return document.getElementById(id); }
  function view() { return el("view"); }
  var __timers = [];
  function every(ms, fn) {
    fn();
    __timers.push(setInterval(function () {
      if (document.hidden) return;
      fn();
    }, ms));
  }
  function clearTimers() {
    __timers.forEach(clearInterval);
    __timers = [];
  }
  function freshLine(env, refreshLabel) {
    if (!env) return "";
    var t = env.timeliness || env.status || "?";
    return '<div class="src" style="margin-top:6px">Last updated: <b>' +
      F.fmtIST(env.as_of) + "</b> · Source: " + F.esc(F.srcName(env.source)) +
      " · Status: " + F.statusPill(t) +
      (env.stale ? " " + F.statusPill("STALE") : "") +
      (refreshLabel ? " · Refresh: " + refreshLabel : "") +
      (env.served_from === "cache" ? " · served from server cache" : "") + "</div>";
  }
  var INDICES = ["^NSEI", "^NSEBANK", "^BSESN", "^CNXIT", "^CNXAUTO",
    "NIFTY_FIN_SERVICE.NS", "^CNXFMCG", "^CNXPHARMA",
    "^GSPC", "^IXIC", "^RUT", "^FTSE", "^STOXX50E", "^N225", "^HSI"];
  var IDX_LABELS = {"^NSEI": "NIFTY 50", "^NSEBANK": "BANK NIFTY", "^BSESN": "SENSEX",
    "^CNXIT": "NIFTY IT", "^CNXAUTO": "NIFTY AUTO", "NIFTY_FIN_SERVICE.NS": "FIN SERVICE",
    "^CNXFMCG": "FMCG", "^CNXPHARMA": "PHARMA", "^GSPC": "S&P 500", "^IXIC": "NASDAQ",
    "^RUT": "RUSSELL 2000", "^FTSE": "FTSE 100", "^STOXX50E": "EURO STOXX 50",
    "^N225": "NIKKEI 225", "^HSI": "HANG SENG"};
  function isIndex(sym) { return INDICES.indexOf(sym) >= 0; }
  function toast(msg) {
    var r = el("toast-root"), d = document.createElement("div");
    d.className = "toast"; d.textContent = msg; r.appendChild(d);
    setTimeout(function () { d.remove(); }, 4200);
  }
  function skel(n) {
    var h = "";
    for (var i = 0; i < (n || 4); i++) h += '<div class="skel" role="status" aria-label="Loading"></div>';
    return h;
  }
  function unavail(msg, provider, reason) {
    return '<div class="empty"><b>DATA UNAVAILABLE</b><br>' + F.esc(msg || "Provider not configured.") +
      ((provider || reason) ? "<br><span class='src'>Provider: " + F.esc(provider || "?") +
        (reason ? " · Reason: " + F.esc(reason) : "") + "</span>" : "") + "</div>";
  }
  /* Field/request-specific provenance: only providers that actually
     participated (or were checked and skipped) are listed, each with
     its reason. Never presents standby providers as contributors. */
  function provStatus(env) {
    if (!env) return "";
    var list = env.provider_status ||
      ((env.reconciliation && env.reconciliation.skipped) || []).map(function (s) {
        return { provider: s.provider, state: null, reason: s.reason };
      });
    if (!list.length) return "";
    return "<div class='prov'>Providers checked: <b>" + list.map(function (p) {
      var st = p.state ? " · " + F.esc(p.state) : "";
      return F.esc(F.srcName(p.provider) || p.provider || "?") + " — " + F.esc(p.reason || "?") + st;
    }).join(" · ") + "</b></div>";
  }
  /* Compact institutional empty state (not a giant blank box). */
  function emptyState(title, msg, env) {
    return "<div class='empty'><b>" + F.esc(title) + "</b><br>" + F.esc(msg || "No configured provider currently supplies this dataset.") +
      "</div>" + provStatus(env);
  }
  function errBox(msg) {
    return '<div class="err"><b>Unable to retrieve dataset.</b><br>' + F.esc(msg || "") +
      "<br><span class='src'>Other configured sources remain available.</span></div>";
  }
  function srcLine(env) {
    if (!env) return "";
    return F.prov(env.source, env.as_of, env.status);
  }
  function quoteRow(q) {
    if (!q) return '<span class="mut">—</span>';
    var c = F.dirClass(q.change_pct);
    return '<b>' + F.fmtNum(q.price) + '</b> <span class="mut">' + F.esc(q.currency || "") +
      '</span> <span class="' + c + '">' + F.fmtPct(q.change_pct) + "</span>";
  }
  function secCell(symbol, name, meta) { return F.secId(name, symbol, meta); }
  function kpi(label, value, sub, title) {
    return "<div class='kpi'" + (title ? " title='" + F.esc(title) + "'" : "") + "><div class='k-l'>" + F.esc(label) + "</div><div class='k-v'>" +
      value + "</div><div class='k-s'>" + F.esc(sub || "") + "</div></div>";
  }
  function unaCell() { return '<span class="mut">—</span>'; }

  /* ---------- dashboard: financial data visualization workstation ----------
     Hierarchy (visual weight in order): MARKET PULSE > PERFORMANCE >
     SECTOR HEATMAP > GAINERS/LOSERS > VOLUME > NEWS > ANALYTICS.
     Every figure is real backend data; missing metrics are omitted. */
  var SECTOR_IDX = ["^CNXIT", "^CNXAUTO", "^CNXFMCG", "^CNXPHARMA",
    "NIFTY_FIN_SERVICE.NS", "^NSEBANK"];
  var PULSE_IDX = ["^NSEI", "^BSESN", "^NSEBANK"];
  function pDashboard() {
    view().innerHTML = "<h1 class='h-page'>Dashboard</h1>" +
      "<div class='sub'>Market pulse first · auto-refresh 60s · server cache unless refresh is allowed</div>" +
      "<div class='card sect pulse'><h3>Market pulse</h3><div id='d-pulse' class='kpis'>" + skel(4) + "</div><div id='d-pulsemeta'></div></div>" +
      "<div class='card sect'><h3>Market performance</h3><div id='d-idx' class='kpis'>" + skel(4) + "</div><div id='d-src'></div></div>" +
      "<div class='card sect'><h3>Sector heatmap</h3><div id='d-heat'>" + skel(3) + "</div><div class='prov'>Sector moves from real sector-index quotes — never hardcoded.</div></div>" +
      "<div class='lay-8-4'><div>" +
      "<div class='card sect'><h3>Movers — tracked universe</h3><div id='d-mov' class='twrap'>" + skel(5) + "</div><div id='d-breadth'></div></div>" +
      "<div class='card sect'><h3>Watchlist snapshot</h3><div id='d-wl'>" + skel(3) + "</div></div>" +
      "<div class='card sect'><h3>Portfolio snapshot</h3><div id='d-pf'>" + skel(3) + "</div></div>" +
      "</div><div>" +
      "<div class='card sect'><h3>Latest headlines</h3><div id='d-news'>" + skel(5) + "</div></div>" +
      "<div class='card sect'><h3>Research shortcuts</h3><div class='row'>" +
      "<a class='btn sm' href='#/screener'>Screener</a><a class='btn sm' href='#/compare'>Compare</a>" +
      "<a class='btn sm' href='#/earnings'>Earnings calendar</a><a class='btn sm' href='#/macro'>Macro</a>" +
      "<a class='btn sm' href='#/research'>Research notes</a></div></div>" +
      "</div></div>";
    function heatCell(lbl, pct) {
      if (pct === null || pct === undefined || isNaN(Number(pct))) return "";
      var v = Number(pct);
      var mag = Math.min(Math.abs(v) / 2, 1);
      var bg = v >= 0 ? "rgba(24,121,78," + (0.08 + mag * 0.5).toFixed(2) + ")"
        : "rgba(192,53,53," + (0.08 + mag * 0.5).toFixed(2) + ")";
      return "<div class='htile' style='background:" + bg + "' title='" + F.esc(lbl) + ": " + F.fmtPct(v) + "' tabindex='0'>" +
        "<b>" + F.esc(lbl) + "</b><span>" + F.fmtPct(v) + "</span></div>";
    }
    function load() {
      if (!el("d-idx")) return;
      API.get("market-overview").then(function (r) {
        if (!el("d-idx")) return;
        var items = (r.body && r.body.items) || [];
        var bySym = {};
        items.forEach(function (i) { bySym[i.symbol] = i; });
        var idx = items.filter(function (i) { return isIndex(i.symbol); });
        var eq = items.filter(function (i) { return !isIndex(i.symbol); });
        // LEVEL 1 — market pulse: headline indices + breadth summary.
        var tradable = eq.filter(function (i) { return i.quote && i.quote.change_pct !== null && i.quote.change_pct !== undefined; });
        var adv = tradable.filter(function (i) { return i.quote.change_pct > 0; }).length;
        var dec = tradable.filter(function (i) { return i.quote.change_pct < 0; }).length;
        var pulse = PULSE_IDX.map(function (s) { return bySym[s]; }).filter(function (i) { return i && i.quote && i.quote.price !== null && i.quote.price !== undefined; });
        el("d-pulse").innerHTML = (pulse.map(function (i) {
          var q = i.quote || {};
          var lbl = IDX_LABELS[i.symbol] || q.name || i.symbol;
          return kpi(lbl, F.fmtNum(q.price) + " <span class='" + F.dirClass(q.change_pct) + "' style='font-size:11px'>" + F.fmtPct(q.change_pct) + "</span>",
            F.esc(i.symbol));
        }).join("") + (tradable.length ?
          kpi("Advances", String(adv), "tracked") +
          kpi("Declines", String(dec), "tracked") +
          kpi("A/D ratio", dec ? (adv / dec).toFixed(2) + "x" : "—", "adv ÷ dec") : "")) ||
          unavail("Market pulse unavailable.");
        el("d-pulsemeta").innerHTML = '<div class="prov">Source market-overview · exchange snapshot · advances/declines over the tracked universe</div>';
        el("d-idx").innerHTML = idx.map(function (i) {
          var q = i.quote || {};
          if (q.price === undefined || q.price === null) return "";
          var lbl = IDX_LABELS[i.symbol] || q.name || i.symbol;
          return kpi(lbl,
            F.fmtNum(q.price) + " <span class='" + F.dirClass(q.change_pct) + "' style='font-size:11px'>" + F.fmtPct(q.change_pct) + "</span>",
            F.esc(i.symbol));
        }).join("") || unavail("Index quotes unavailable.");
        // LEVEL 3 — sector heatmap from real sector-index quotes.
        var heat = SECTOR_IDX.map(function (s) { return bySym[s]; })
          .filter(function (i) { return i && i.quote && i.quote.change_pct !== null && i.quote.change_pct !== undefined; })
          .map(function (i) { return heatCell(IDX_LABELS[i.symbol] || i.symbol, i.quote.change_pct); })
          .join("");
        el("d-heat").innerHTML = heat ? "<div class='hmap'>" + heat + "</div>"
          : unavail("Sector heatmap needs sector-index quotes.");
        var ranked = tradable.sort(function (a, b) { return Math.abs(b.quote.change_pct) - Math.abs(a.quote.change_pct); }).slice(0, 10);
        el("d-mov").innerHTML = '<table class="t"><thead><tr><th scope="col">Security</th><th scope="col" class="num">Price</th>' +
          '<th scope="col" class="num">Change</th><th scope="col" class="num">Volume</th></tr></thead><tbody>' +
          ranked.map(function (i) {
            var q = i.quote;
            return "<tr><td class='txt'><a href='#/company/" + F.esc(i.symbol) + "'>" +
              secCell(i.symbol, q.name, q.exchange) + "</a></td><td class='num'><b>" + F.fmtNum(q.price) +
              " " + F.esc(q.currency || "") + "</b></td><td class='num " + F.dirClass(q.change_pct) + "'>" + F.fmtPct(q.change_pct) +
              "</td><td class='num'>" + F.fmtInt(q.volume) + "</td></tr>";
          }).join("") + "</tbody></table>";
        el("d-breadth").innerHTML = '<div class="prov">Breadth (tracked, CALCULATED): <b class="up">' + adv +
          " advancing</b> · <b class='dn'>" + dec + " declining</b></div>";
        el("d-src").innerHTML = '<div class="prov">Source market-overview · exchange snapshot · quotes cached 30s server-side</div>';
      });
      // LEVEL 7 — analytics: regime/breadth engine feeds the pulse meta.
      API.get("breadth").then(function (r) {
        if (!el("d-breadth") || !r.body || !r.body.data) return;
        var b = r.body.data;
        el("d-breadth").innerHTML += '<div class="prov">Regime breadth: ' + F.esc(b.advancers || 0) + " up / " +
          F.esc(b.decliners || 0) + " down · coverage " + F.esc(b.coverage_pct || 0) + "% (" + F.esc(b.coverage_note || "") + ")</div>";
      }).catch(function () { /* breadth is additive */ });
    }
    function loadWl() {
      if (!el("d-wl")) return;
      API.get("watchlist").then(function (r) {
        if (!el("d-wl")) return;
        var items = ((r.body && r.body.items) || []).slice(0, 5);
        el("d-wl").innerHTML = items.length ? '<table class="t"><tbody>' + items.map(function (i) {
          var q = i.quote || {};
          return "<tr><td class='txt'><a href='#/company/" + F.esc(i.symbol) + "'>" +
            secCell(i.symbol, i.name || q.name, null) + "</a></td><td class='num'><b>" + F.fmtNum(q.price) +
            "</b></td><td class='num " + F.dirClass(q.change_pct) + "'>" + F.fmtPct(q.change_pct) + "</td></tr>";
        }).join("") + "</tbody></table><div class='prov'><a href='#/watchlist'>Open watchlist →</a></div>"
          : unavail("Watchlist is empty.");
      });
    }
    function loadPf() {
      if (!el("d-pf")) return;
      API.get("portfolio").then(function (r) {
        if (!el("d-pf")) return;
        var b = r.body || {};
        el("d-pf").innerHTML = "<div class='kpis'>" +
          kpi("Total value", b.current_value === null || b.current_value === undefined ? "—" : F.fmtMoney(b.current_value), "delayed quotes") +
          kpi("Total P&L", b.unrealized_pnl === null || b.unrealized_pnl === undefined ? "—" : F.fmtMoney(b.unrealized_pnl), F.fmtPct(b.pnl_pct) + " CALC") +
          kpi("Holdings", String((b.positions || []).length), "manual ledger") + "</div>" +
          "<div class='prov'><a href='#/portfolio'>Open portfolio →</a></div>";
      });
    }
    function loadNews() {
      if (!el("d-news")) return;
      API.get("news", { limit: 8 }).then(function (r) {
        if (!el("d-news")) return;
        var b = r.body;
        if (!b || !b.data || !b.data.items) { el("d-news").innerHTML = unavail((b && b.message) || "News unavailable."); return; }
        el("d-news").innerHTML = b.data.items.slice(0, 8).map(newsItem).join("");
      });
    }
    every(60000, load);
    every(60000, loadNews);
    loadWl(); loadPf();
  }
  function newsItem(n) {
    var sum = n.summary ? F.esc(n.summary.slice(0, 220).replace(/\s+\S*$/, "")) : "";
    return '<article class="news-item"><a href="' + F.esc(n.url) + '" target="_blank" rel="noopener">' +
      F.esc(n.title) + "</a>" +
      (sum ? "<p class='sum'>" + sum + "…</p>" : "") +
      "<div class='meta'>" + F.esc(n.source || "") + " · " + F.esc(n.published_at || "") +
      (n.via ? " · via " + F.esc(n.via) : "") + (n.sentiment ? " · " + F.esc(n.sentiment) : "") + "</div></article>";
  }

  /* ---------- markets ---------- */
  function pMarkets() {
    view().innerHTML = "<h1 class='h-page'>Markets</h1>" +
      "<div class='sub'>NSE/BSE, US and global indices via the free-automatic chain. NSE real-time requires an authorized feed — shown data is delayed.</div>" +
      "<div id='m-sects'>" + skel(8) + "</div>";
    API.get("market-overview").then(function (r) {
      if (!el("m-sects")) return;
      var items = (r.body && r.body.items) || [];
      function isIN(i) {
        return /\.NS$|\.BO$/.test(i.symbol) || /NSE|BSE|CNX|NIFTY|SENSEX/i.test((i.quote && i.quote.name) || "") || isIndex(i.symbol) && /NSEI|NSEBANK|BSESN|CNX|NIFTY/i.test(i.symbol);
      }
      var inIdx = items.filter(function (i) { return isIndex(i.symbol) && isIN(i); });
      var glIdx = items.filter(function (i) { return isIndex(i.symbol) && !isIN(i); });
      var eq = items.filter(function (i) { return !isIndex(i.symbol); });
      function tbl(title, list, showName) {
        if (!list.length) return "";
        return "<div class='card sect'><h3>" + title + "</h3><div class='twrap'><table class='t'><thead><tr>" +
          (showName ? "<th scope='col'>Security</th>" : "<th scope='col'>Index</th>") +
          "<th scope='col' class='num'>Last</th><th scope='col' class='num'>Change</th><th scope='col'>Status</th></tr></thead><tbody>" +
          list.map(function (i) {
            var q = i.quote || {};
            return "<tr><td class='txt'><a href='#/company/" + F.esc(i.symbol) + "'>" +
              (showName ? secCell(i.symbol, q.name, q.exchange) : "<b>" + F.esc(q.name || i.symbol) + "</b> <span class='tk' style='font-family:var(--mono);font-size:10.5px;color:var(--slate)'>" + F.esc(i.symbol) + "</span>") +
              "</a></td><td class='num'><b>" + F.fmtNum(q.price) + " " + F.esc(q.currency || "") + "</b></td>" +
              "<td class='num " + F.dirClass(q.change_pct) + "'>" + F.fmtPct(q.change_pct) + "</td>" +
              "<td>" + F.statusPill(i.status) + "</td></tr>";
          }).join("") + "</tbody></table></div></div>";
      }
      var adv = eq.filter(function (i) { return i.quote && i.quote.change_pct > 0; }).length;
      var dec = eq.filter(function (i) { return i.quote && i.quote.change_pct < 0; }).length;
      el("m-sects").innerHTML = tbl("India — indices", inIdx, false) + tbl("Global — indices", glIdx, false) +
        tbl("Equities — tracked universe", eq, true) +
        "<div class='prov'>Breadth (tracked equities, CALCULATED): <b class='up'>" + adv + " advancing</b> · <b class='dn'>" + dec +
        " declining</b> · fallback chain · delayed</div>";
    });
  }

  /* ---------- screener: screening workstation ---------- */
  var SCR_METRICS = [
    ["price", "Price"], ["change_pct", "Change %"], ["volume", "Volume"],
    ["high_52w", "52W high"], ["low_52w", "52W low"],
    ["rsi14", "RSI 14"], ["sma20", "SMA 20"], ["sma50", "SMA 50"], ["sma200", "SMA 200"],
    ["pe", "P/E"], ["pb", "P/B"], ["roe", "ROE"], ["eps", "EPS"],
    ["div_yield", "Div yield"], ["market_cap", "Market cap"],
  ];
  var SCR_OPS = [["gt", ">"], ["gte", "≥"], ["lt", "<"], ["lte", "≤"], ["eq", "="], ["between", "between"]];
  function pScreener() {
    view().innerHTML = "<h1 class='h-page'>Screener</h1>" +
      "<div class='sub'>Quote fields REPORTED (delayed) · RSI/SMA CALCULATED locally · P/E/ROE REPORTED (Alpha Vantage, quota-noted). Missing values exclude — never invented.</div>" +
      "<div class='card sect'><div class='row'>" +
      "<label class='f'>Universe<select id='s-uni' class='in'><option value='all'>Tracked universe</option>" +
      "<option value='nse'>Tracked NSE</option><option value='us'>Tracked US</option></select></label>" +
      "<span class='src' id='s-cov'></span>" +
      "<span style='flex:1'></span>" +
      "<button class='btn sm' id='s-save'>Save screen</button>" +
      "<button class='btn sm' id='s-load'>Load screen</button>" +
      "<button class='btn sm' id='s-reset'>Reset</button>" +
      "<button class='btn primary' id='s-run'>Apply filters</button></div>" +
      "<div id='s-rows' style='margin-top:8px'></div>" +
      "<div class='row' style='margin-top:8px'><button class='btn sm' id='s-add'>+ Add filter</button>" +
      "<span class='src'>P/E · ROE · P/B · EPS · Div yield · Market cap need ALPHA_VANTAGE_API_KEY (25/day, cached 24h).</span></div>" +
      "<div id='s-chips' class='row' style='margin-top:8px'></div></div>" +
      "<div id='s-out' style='margin-top:12px'></div>";
    var OP_LABEL = {};
    SCR_OPS.forEach(function (o) { OP_LABEL[o[0]] = o[1]; });
    function metOpts(sel) {
      return SCR_METRICS.map(function (m) {
        return "<option value='" + m[0] + "'" + (m[0] === sel ? " selected" : "") + ">" + m[1] + "</option>";
      }).join("");
    }
    function opOpts(sel) {
      return SCR_OPS.map(function (o) {
        return "<option value='" + o[0] + "'" + (o[0] === sel ? " selected" : "") + ">" + o[1] + "</option>";
      }).join("");
    }
    function addRow(m, op, v1, v2) {
      var d = document.createElement("div");
      d.className = "row"; d.style.marginTop = "6px";
      d.innerHTML = "<select class='in s-fm'>" + metOpts(m || "pe") + "</select>" +
        "<select class='in s-fo'>" + opOpts(op || "lt") + "</select>" +
        "<input class='in s-fv1' style='width:110px' placeholder='value' value='" + F.esc(v1 || "") + "'>" +
        "<input class='in s-fv2' style='width:110px" + ((op || "lt") === "between" ? "" : ";display:none") + "' placeholder='and' value='" + F.esc(v2 || "") + "'>" +
        "<button class='btn sm danger s-fx'>×</button>";
      d.querySelector(".s-fo").onchange = function () {
        d.querySelector(".s-fv2").style.display = this.value === "between" ? "" : "none";
      };
      d.querySelector(".s-fx").onclick = function () { d.remove(); run(); };
      ["s-fm", "s-fo", "s-fv1", "s-fv2"].forEach(function (c) {
        d.querySelector("." + c).onchange = function () { /* applied on Apply */ };
      });
      el("s-rows").appendChild(d);
    }
    function readRules() {
      var out = [];
      Array.prototype.forEach.call(document.querySelectorAll("#s-rows > .row"), function (d) {
        var m = d.querySelector(".s-fm").value, op = d.querySelector(".s-fo").value;
        var v1 = d.querySelector(".s-fv1").value.trim(), v2 = d.querySelector(".s-fv2").value.trim();
        if (v1 !== "") out.push({ m: m, op: op, v1: v1, v2: v2 });
      });
      return out;
    }
    function paintChips(rules) {
      el("s-chips").innerHTML = rules.map(function (r, i) {
        return "<span class='chip'>" + F.esc(r.m + " " + (OP_LABEL[r.op] || r.op) + " " + r.v1 + (r.op === "between" ? " … " + r.v2 : "")) +
          " <button data-cx='" + i + "' aria-label='Remove filter'>×</button></span>";
      }).join("");
      Array.prototype.forEach.call(document.querySelectorAll("[data-cx]"), function (b) {
        b.onclick = function () {
          var rows = document.querySelectorAll("#s-rows > .row");
          var ix = Number(b.getAttribute("data-cx"));
          if (rows[ix]) rows[ix].remove();
          run();
        };
      });
    }
    el("s-add").onclick = function () { addRow(); };
    el("s-reset").onclick = function () { el("s-rows").innerHTML = ""; addRow("pe", "lt", "25", ""); run(); };
    el("s-save").onclick = function () {
      try { localStorage.setItem("ft-screen", JSON.stringify(readRules())); toast("Screen saved."); }
      catch (e) { toast("Save failed (private mode?)."); }
    };
    el("s-load").onclick = function () {
      try {
        var rules = JSON.parse(localStorage.getItem("ft-screen") || "[]");
        el("s-rows").innerHTML = "";
        rules.forEach(function (r) { addRow(r.m, r.op, r.v1, r.v2); });
        if (!rules.length) addRow("pe", "lt", "25", "");
        run();
      } catch (e) { toast("No saved screen."); }
    };
    el("s-run").onclick = run;
    el("s-uni").onchange = run;
    addRow("pe", "lt", "25", "");
    var sortBy = null, sortDir = "asc";
    function run() {
      var rules = readRules();
      paintChips(rules);
      el("s-out").innerHTML = "<div class='card'>" + skel(5) + "</div>";
      var params = { universe: el("s-uni").value };
      if (sortBy) { params.sort_by = sortBy; params.sort_dir = sortDir; }
      var qs = Object.keys(params).map(function (k) { return encodeURIComponent(k) + "=" + encodeURIComponent(params[k]); }).join("&") +
        rules.map(function (r) {
          return "&f=" + encodeURIComponent(r.m + ":" + r.op + ":" + r.v1 + (r.op === "between" ? ":" + r.v2 : ""));
        }).join("");
      API.get("screener?" + qs).then(function (r) {
        if (!el("s-out")) return;
        var b = r.body || {};
        if (!b.ok) {
          el("s-out").innerHTML = errBox(b.error || "Screen failed.");
          return;
        }
        var res = b.results || [];
        var skipped = b.skipped || [];
        var excl = skipped.filter(function (x) { return x.excluded_reason; });
        el("s-cov").innerHTML = "Coverage: <b>" + F.esc(b.universe || "") + "</b> · screened " + (b.coverage || 0) + " · matched " + res.length +
          (res.length ? ' · <a id="s-csv" href="/api/screener?' + qs + '&format=csv" download="screen.csv">Export CSV</a>' : "");
        function th(label, metric) {
          var arrow = sortBy === metric ? (sortDir === "asc" ? " ▲" : " ▼") : "";
          return "<th scope='col' class='num'><a href='#' data-sort='" + metric + "' style='color:inherit'>" + label + arrow + "</a></th>";
        }
        el("s-out").innerHTML = "<div class='card flush'><div style='padding:12px 14px 0'><h3>Matches (" + res.length + ") " + F.statusPill("delayed") + "</h3>" +
          "<div class='src'>backed by: " + F.esc((b.backed_by || []).join(", ")) + "</div></div>" +
          (res.length ? '<div class="twrap"><table class="t"><thead><tr><th scope="col">Security</th><th scope="col" class="num">Price</th>' +
            th("Δ%", "change_pct") + th("RSI", "rsi14") + th("P/E", "pe") + th("ROE", "roe") +
            '<th scope="col">Data</th><th scope="col"><span class="hidden">A</span></th></tr></thead><tbody>' +
            res.map(function (x) {
              var t = x.technical || {}, f = x.fundamental || {};
              function fund(k) { return f[k] === undefined || f[k] === null || f[k] === "None" ? "—" : F.esc(String(f[k])); }
              return "<tr data-sym='" + F.esc(x.symbol) + "' style='cursor:pointer'><td class='txt'>" +
                secCell(x.symbol, x.quote && x.quote.name, x.quote && x.quote.exchange) +
                ((x.matched && x.matched.length) ? "<br><span class='src' title='Why this row passed'>" +
                  F.esc(x.matched.map(function (m) {
                    var th = (m.threshold && m.threshold.length !== undefined && typeof m.threshold !== "number")
                      ? m.threshold.join("…") : m.threshold;
                    return m.metric + " " + m.op + " " + th;
                  }).join(" · ")) + "</span>" : "") + "</td><td class='num'><b>" +
                F.fmtNum(x.quote.price) + " " + F.esc(x.quote.currency || "") + "</b></td><td class='num " + F.dirClass(x.quote.change_pct) + "'>" + F.fmtPct(x.quote.change_pct) +
                "</td><td class='num'>" + (t.rsi14 === undefined || t.rsi14 === null ? "—" : F.fmtNum(t.rsi14) + " <span class='pill pill-calc'>CALC</span>") +
                "</td><td class='num'>" + fund("PERatio") + "</td><td class='num'>" + fund("ROE") +
                "</td><td>" + F.statusPill(x.timeliness || x.status) + (x.stale ? " " + F.statusPill("STALE") : "") +
                "<div class='src'>" + F.fmtIST(x.as_of) + "</div></td>" +
                "<td class='num'><button class='btn sm' data-wl='" + F.esc(x.symbol) + "'>+ Watch</button></td></tr>";
            }).join("") + "</tbody></table></div>"
            : unavail("No symbols pass these filters right now.")) +
          (excl.length ? "<div style='padding:0 14px 12px'><h3 style='margin-top:10px'>Excluded from filter (no data — not scored)</h3><ul style='margin:6px 0;padding-left:18px'>" +
            excl.map(function (x) {
              return "<li class='mut'>" + F.esc(x.symbol) + ": " + F.esc(x.excluded_reason) + "</li>";
            }).join("") + "</ul></div>" : "") + "</div>";
        Array.prototype.forEach.call(document.querySelectorAll("[data-wl]"), function (btn) {
          btn.onclick = function (ev) { ev.stopPropagation(); addWatch(btn.getAttribute("data-wl")); };
        });
        Array.prototype.forEach.call(document.querySelectorAll("[data-sort]"), function (a) {
          a.onclick = function (ev) {
            ev.preventDefault();
            var m = a.getAttribute("data-sort");
            if (sortBy === m) sortDir = sortDir === "asc" ? "desc" : "asc";
            else { sortBy = m; sortDir = "asc"; }
            run();
          };
        });
        Array.prototype.forEach.call(document.querySelectorAll("#s-out tr[data-sym]"), function (tr) {
          tr.onclick = function (ev) {
            if (ev.target.tagName === "BUTTON" || ev.target.tagName === "A") return;
            location.hash = "#/company/" + encodeURIComponent(tr.getAttribute("data-sym"));
          };
        });
      });
    }
    run();
  }

  /* ---------- companies ---------- */
  function pCompanies() {
    view().innerHTML = "<h1 class='h-page'>Companies</h1>" +
      "<div class='sub'>Search any listed instrument — name, ticker, sector or index. Quotes: delayed Yahoo.</div>" +
      "<div class='card'><div class='row'><input id='c-q' class='in' aria-label='Company search' style='flex:1;min-width:220px' placeholder='e.g. Reliance, TCS.NS, AAPL, Nifty'>" +
      "<button class='btn primary' id='c-go'>Search</button></div><div id='c-out' style='margin-top:10px'></div></div>";
    function go() {
      var q = el("c-q").value.trim();
      if (!q) return;
      el("c-out").innerHTML = skel(4);
      API.get("search", { q: q }).then(function (r) {
        if (!el("c-out")) return;
        var b = r.body;
        if (!b || !b.data) { el("c-out").innerHTML = unavail((b && b.message) || "No results."); return; }
        el("c-out").innerHTML = '<div class="twrap"><table class="t"><thead><tr><th scope="col">Security</th><th scope="col">Exchange</th><th scope="col">Type</th></tr></thead><tbody>' +
          b.data.results.map(function (x) {
            return "<tr><td class='txt'><a href='#/company/" + F.esc(x.symbol) + "'>" +
              secCell(x.symbol, x.name, null) + "</a></td><td class='txt'>" + F.esc(x.exchange || "—") +
              "</td><td>" + F.typeBadge(x.type) + "</td></tr>";
          }).join("") + "</tbody></table></div>" + srcLine(b);
      });
    }
    el("c-go").onclick = go;
    el("c-q").onkeydown = function (e) { if (e.key === "Enter") go(); };
  }

  /* ---------- company detail ---------- */
  /* v4: 5 tabs (company.js override is canonical). Kept in sync. */
  var CTABS = ["Overview", "Financials", "Valuation", "Technicals", "Research"];
  function pCompany(sym, tab) {
    sym = (sym || "").toUpperCase();
    tab = tab || "Overview";
    view().innerHTML = "<div id='co-head' class='card'>" + skel(3) + "</div>" +
      "<div class='tabs sticky' role='tablist' id='co-tabs'>" + CTABS.map(function (t) {
        return "<button role='tab' aria-selected='" + (t === tab ? "true" : "false") + "' data-t='" + t + "' class='" + (t === tab ? "on" : "") + "'>" + t + "</button>";
      }).join("") + "</div><div class='lay-8-4'><div id='co-body'></div>" +
      "<aside><div id='co-quality'></div></aside></div><div id='co-hub'></div>";
    Array.prototype.forEach.call(document.querySelectorAll("#co-tabs button"), function (b) {
      b.onclick = function () { location.hash = "#/company/" + encodeURIComponent(sym) + "/" + b.getAttribute("data-t"); };
    });
    API.get("company", { symbol: sym }).then(function (rc) {
      API.get("quote", { symbol: sym }).then(function (rq) {
        if (!el("co-head")) return;
        renderHead(sym, rc.body, rq.body);
        renderTab(sym, tab);
        loadQuality(sym, rc.body, rq.body);
        loadHub(sym);
        loadKpis(sym, (rq.body && rq.body.data) || {}, rq.body);
        every(10000, function () {
          if (!el("co-price")) return;
          API.get("quote", { symbol: sym }).then(function (r) {
            if (el("co-price")) patchHead(r.body);
          });
        });
      });
    });
    function loadKpis(sym, q, qenv) {
      var q_src = (qenv && qenv.source) || q.source || "?";
      API.get("ratios", { symbol: sym }).then(function (r) {
        if (!el("co-kpis")) return;
        var d = (r.body && r.body.data) || null, ccy = q.currency || "";
        var rsrc = F.srcName(r.body && r.body.source);
        function val(x, fmt) {
          if (x === undefined || x === null || x === "None" || x === "-") return null;
          if (fmt === "x") { var n = Number(x); return isNaN(n) ? null : n.toFixed(1) + "x"; }
          if (fmt === "pct") return String(x) + "%";
          if (fmt === "in") { var m = Number(x); return isNaN(m) ? null : F.fmtIN(m, ccy); }
          return String(x);
        }
        function cell(l, v, s, t) {
          return kpi(l, v === null ? unaCell() : F.esc(v), s || "", t || ("Source: " + rsrc));
        }
        el("co-kpis").innerHTML =
          (d ? cell("Market cap", val(d.MarketCapitalization, "in"), ((d.MarketCapKind === "CALCULATED" ? "calculated" : "reported") + " · " + rsrc)) +
          cell("P/E", val(d.PERatio, "x"), "TTM · reported") +
          cell("EPS", val(d.EPS, "num") && F.fmtNum(Number(d.EPS)), "TTM · reported") +
          cell("ROE", val(d.ROE, "pct"), "reported") +
          cell("Book value", (d.BookValue && d.BookValue !== "None") ? F.fmtNum(Number(d.BookValue)) : null, "reported") +
          cell("52W high", F.fmtNum(q.fifty_two_week_high) === "—" ? null : F.fmtNum(q.fifty_two_week_high), "quote", "Source: " + F.srcName(q_src)) +
          cell("52W low", F.fmtNum(q.fifty_two_week_low) === "—" ? null : F.fmtNum(q.fifty_two_week_low), "quote", "Source: " + F.srcName(q_src)) +
          cell("Div yield", val(d.DividendYield, "pct"), "reported")
          : cell("Market cap", null, "Not available from configured sources") + cell("P/E", null, "Not available from configured sources") +
            cell("EPS", null, "Not available from configured sources") + cell("ROE", null, "Not available from configured sources") +
            cell("Book value", null, "Not available from configured sources") +
            cell("52W high", F.fmtNum(q.fifty_two_week_high) === "—" ? null : F.fmtNum(q.fifty_two_week_high), "quote", "Source: " + F.srcName(q_src)) +
            cell("52W low", F.fmtNum(q.fifty_two_week_low) === "—" ? null : F.fmtNum(q.fifty_two_week_low), "quote", "Source: " + F.srcName(q_src)) +
            cell("Div yield", null, "Not available from configured sources"));
      });
    }
    function loadQuality(sym, profEnv, quoteEnv) {
      API.get("quality", { symbol: sym }).then(function (r) {
        if (!el("co-quality")) return;
        var b = r.body || {}, rows = b.providers || [], q = b.quote || {};
        var sum = (q.reconciliation || {});
        function dot(st) {
          return st === "connected" ? "● " : (st === "cooling" ? "◐ " : "○ ");
        }
        function qline() {
          return "<b>" + F.esc(F.srcName(q.quote_source) || q.quote_source || "?") + "</b> · " +
            F.esc(q.quote_status || "?") + "/" + F.esc(q.quote_timeliness || "?");
        }
        function prow(label, env) {
          if (!env) return "<div class='dr'><div class='dl'>" + label + "</div><div class='dv'>loading…</div></div>";
          var d = env.data;
          if (d) return "<div class='dr'><div class='dl'>" + label + "</div><div class='dv'><b>" +
            F.esc(F.srcName(env.source)) + "</b> · " + F.esc(env.timeliness || env.status || "?") + "</div></div>";
          return "<div class='dr'><div class='dl'>" + label + "</div><div class='dv'>" +
            F.esc((env.message || "Not available").split(".")[0]) + "</div></div>";
        }
        function paint(fundEnv) {
          if (!el("co-quality")) return;
          el("co-quality").innerHTML = "<div class='card sect'><h3>Data sources</h3>" +
            "<div class='dsrc'>" +
            "<div class='dr'><div class='dl'>Price</div><div class='dv'>" + qline() + "</div></div>" +
            prow("Company profile", profEnv) +
            prow("Fundamentals", fundEnv) +
            "<div class='dr'><div class='dl'>Technical</div><div class='dv'>Calculated from historical data</div></div>" +
            "</div>" +
            "<div class='prov'>Cross-check: " +
            (sum.fields_compared === undefined ? "—" : sum.fields_compared) + " fields checked · " +
            (sum.discrepancies === undefined ? "—" : sum.discrepancies) + " discrepancies</div>" +
            "<details><summary class='src'>Other available providers</summary><div style='margin-top:6px'>" +
            rows.map(function (p) {
              var last = p.last_ok ? new Date(p.last_ok * 1000).toISOString().slice(11, 19) + "Z" :
                (p.last_error ? "err: " + F.esc(String(p.last_error).slice(0, 60)) : "—");
              return "<div style='padding:3px 0'><b>" + dot(p.state) + F.esc(p.label) + "</b><div class='src'>" + F.esc(p.detail || "") +
                "<br>Last response: " + last +
                (p.last_latency_ms !== null && p.last_latency_ms !== undefined ? " · " + p.last_latency_ms + " ms" : "") + "</div></div>";
            }).join("") + "</div></details></div>";
        }
        paint(null);
        API.get("ratios", { symbol: sym }).then(function (rr) {
          paint(rr.body);
        });
      });
    }
    function loadHub(sym) {
      API.get("research-links", { symbol: sym }).then(function (r) {
        if (!el("co-hub")) return;
        var b = r.body || {};
        if (!b.ok) { el("co-hub").innerHTML = ""; return; }
        function rows(list) {
          return list.map(function (d) {
            var badge = d.badge === "OFFICIAL"
              ? "<span class='pill pill-live'>OFFICIAL</span>"
              : "<span class='pill pill-calc'>EXTERNAL</span>";
            var action = d.url
              ? "<a class='btn sm' href='" + F.esc(d.url) + "' target='_blank' rel='noopener noreferrer' " +
                "aria-label='Open " + F.esc(d.name) + " in a new tab'>Open ↗</a>"
              : "<span class='src'>" + F.esc(d.reason || "No verified URL available") + "</span>";
            return "<tr><td class='txt'><b>" + F.esc(d.name) + "</b> " + badge +
              "<br><span class='src'>" + F.esc(d.description || "") + "</span></td>" +
              "<td class='num'>" + action + "</td></tr>";
          }).join("");
        }
        el("co-hub").innerHTML = "<div class='card sect'><h3>Research Hub</h3>" +
          "<div class='grid g2'>" +
          "<div><div class='lbl' style='margin-bottom:4px'>Official &amp; market data</div>" +
          '<div class="twrap hub"><table class="t"><tbody>' + rows(b.official || []) + "</tbody></table></div></div>" +
          "<div><div class='lbl' style='margin-bottom:4px'>External research</div>" +
          '<div class="twrap hub"><table class="t"><tbody>' + rows(b.research || []) + "</tbody></table></div></div>" +
          "</div><div class='prov' style='margin-top:6px'>" + F.esc(b.notice || "") + "</div></div>";
      });
    }
    function patchHead(qenv) {
      var q = (qenv && qenv.data) || {};
      if (!q.price && q.price !== 0) return;
      var c = F.dirClass(q.change_pct);
      el("co-price").innerHTML = F.fmtNum(q.price) +
        " <small>" + F.esc(q.currency || "") + "</small>";
      var ch = el("co-chg");
      ch.className = "c " + c;
      ch.textContent = F.fmtPct(q.change_pct) + " (" + F.fmtNum(q.change) + ")";
      var pills = el("co-pills");
      if (pills) pills.innerHTML = F.statusPill(qenv.timeliness || qenv.status) +
        (qenv.stale ? " " + F.statusPill("STALE") : "");
      var fl = el("co-fresh");
      if (fl) fl.innerHTML = freshInner(qenv, "10s");
    }
    function freshInner(qenv, refreshLabel) {
      return "Last updated: <b>" + F.fmtIST(qenv.as_of) + "</b> · Source: " +
        F.esc(F.srcName(qenv.source)) + " · Status: " +
        F.statusPill(qenv.timeliness || qenv.status) +
        (qenv.stale ? " " + F.statusPill("STALE") : "") +
        (refreshLabel ? " · Refresh: " + refreshLabel : "") +
        (qenv.served_from === "cache" ? " · served from server cache" : "");
    }
    function renderHead(sym, prof, qenv) {
      var q = (qenv && qenv.data) || {}, p = (prof && prof.data) || {};
      var nm = q.name || p.name || sym;
      var c = F.dirClass(q.change_pct);
      var isIdx = sym.charAt(0) === "^";
      var ticker = sym.replace(/\.(NS|BO)$/, "");
      var exch = q.exchange || p.exchange || (isIdx ? "Index" : "—");
      var country = /\.NS$|\.BO$/.test(sym) ? "India" : (isIdx ? "" : (/NASDAQ|NYSE|NMS/i.test(exch) ? "USA" : ""));
      var venue = [exch, q.instrument_type || p.instrument_type].filter(Boolean).join(" · ");
      var sectorLine = [p.sector || q.sector, p.industry || q.industry].filter(Boolean).join(" · ");
      el("co-head").innerHTML = "<div class='co-head'><div class='co-id'><div class='sec-row'>" +
        F.logo(sym, nm, 42) +
        "<div><div class='co-eyebrow'>Equity · " + F.esc(country || exch) + "</div>" +
        "<h1>" + F.esc(nm) + "</h1>" +
        "<div class='tk'>" + F.esc(ticker) + " · " + F.esc(exch) +
        (country ? " · " + F.esc(country) : "") + (isIdx ? " · Index" : "") + "</div>" +
        "<div class='mt'>" + F.esc(venue + (q.currency || p.currency ? " · " + (q.currency || p.currency) : "")) + "</div>" +
        (sectorLine ? "<div class='mt'>" + F.esc(sectorLine) + "</div>" : "") +
        "</div></div>" +
        "<div class='src' id='co-pills'>" +
        (qenv ? F.statusPill(qenv.timeliness || qenv.status) : "") +
        (qenv && qenv.stale ? " " + F.statusPill("STALE") : "") + "</div>" +
        "<div class='src' id='co-fresh' title='Provenance: " + F.esc(F.srcName(qenv && qenv.source)) + "'>" + freshInner(qenv, "10s") + "</div>" +
        (isIdx ? "<div class='src'>Index security — company tabs (financials, holdings) do not apply; market data below.</div>" : "") + "</div>" +
        "<div class='co-px'><div class='p' id='co-price' title='Source: " + F.esc(F.srcName(qenv && qenv.source)) + "'>" + F.fmtNum(q.price) +
        " <small>" + F.esc(q.currency || "") + "</small></div>" +
        "<div class='c " + c + "' id='co-chg' title='Source: " + F.esc(F.srcName(qenv && qenv.source)) + "'>" + F.fmtPct(q.change_pct) + " (" + F.fmtNum(q.change) + ")</div>" +
        "<div class='row' style='justify-content:flex-end;margin-top:6px'><button class='btn sm' id='co-wl'>+ Watchlist</button>" +
        "<button class='btn sm' id='co-pf'>+ Portfolio</button><button class='btn sm' id='co-cmp'>⇄ Compare</button></div></div></div>" +
        "<div class='kpis' id='co-kpis' style='margin-top:10px'>" + skel(6) + "</div>";
      el("co-wl").onclick = function () { addWatch(sym, q.name); };
      el("co-cmp").onclick = function () { location.hash = "#/compare"; sessionStorage.setItem("ft-cmp", sym); };
      el("co-pf").onclick = function () {
        if (window.FT_CX && window.FT_CX.addHolding) { window.FT_CX.addHolding(sym, q || {}); return; }
        toast("Portfolio entry is available on the new company page.");
      };
    }
  }
  function renderTab(sym, tab) {
    var b = el("co-body");
    if (tab === "Overview") return tOverview(sym, b);
    if (tab === "Financials") return tFinancials(sym, b);
    if (tab === "Valuation") return tValuation(sym, b);
    if (tab === "Estimates") return tEstimates(sym, b);
    if (tab === "Earnings") return tEarnings(sym, b);
    if (tab === "News") return tNews(sym, b);
    if (tab === "Actions") return tActions(sym, b);
    if (tab === "Ownership" || tab === "Holdings") return tHoldings(sym, b);
    if (tab === "Charts") return tCharts(sym, b, "1Y", "1d");
    if (tab === "Technicals") return tTechnicals(sym, b);
    if (tab === "Research") return tResearch(sym, b);
  }
  function tOverview(sym, b) {
    b.innerHTML = "<div class='card sect' id='ov-about'>" + skel(3) + "</div>" +
      "<div class='card sect' id='ov-chart'>" + skel(3) + "</div>" +
      "<div class='grid g2'><div class='card' id='ov-q'>" + skel(6) + "</div>" +
      "<div class='card' id='ov-r'>" + skel(6) + "</div></div>" +
      "<div class='card sect' id='ov-fsnap'>" + skel(4) + "</div>" +
      "<div class='grid g2'><div class='card' id='ov-own'>" + skel(3) + "</div>" +
      "<div class='card' id='ov-news'>" + skel(4) + "</div></div>" +
      "<div id='ov-brief'></div>";
    var quote = null, history = null, ratios = null, recon = null, settled = 0;
    API.get("company", { symbol: sym }).then(function (r) {
      var p = r.body && r.body.data;
      if (!el("ov-about") || !p) { if (el("ov-about")) el("ov-about").outerHTML = ""; return; }
      el("ov-about").innerHTML = "<h3>Business</h3>" +
        (p.description ? "<p style='margin:0 0 6px;font-size:12.5px;line-height:1.55'>" + F.esc(p.description.slice(0, 900)) + "</p>" : "") +
        ((p.sector || p.industry) ?
          "<div class='prov'>Sector: <b>" + F.esc(p.sector || "—") + "</b> · Industry: <b>" + F.esc(p.industry || "—") + "</b> · " +
          F.esc(F.srcName((r.body || {}).source)) + "</div>" :
          "<div class='prov'>Sector / industry unavailable — no fundamentals feed configured.</div>");
    });
    API.get("quote", { symbol: sym }).then(function (r) {
      var q = r.body && r.body.data;
      quote = q;
      if (!el("ov-q")) return;
      el("ov-q").innerHTML = "<h3>Key quote " + F.statusPill(r.body.status) + "</h3>" + (q ?
        "<dl class='kv'><dt>Price</dt><dd>" + F.fmtNum(q.price) + " " + F.esc(q.currency || "") + "</dd>" +
        "<dt>Δ vs prev close</dt><dd class='" + F.dirClass(q.change_pct) + "'>" + F.fmtPct(q.change_pct) + "</dd>" +
        "<dt>Prev close</dt><dd>" + F.fmtNum(q.previous_close) + "</dd>" +
        "<dt>Volume</dt><dd>" + F.fmtInt(q.volume) + "</dd>" +
        "<dt>Market time</dt><dd>" + F.fmtDateTime(q.market_time) + "</dd></dl>" :
        unavail((r.body && r.body.message) || "Quote unavailable.")) + srcLine(r.body);
      maybeBrief();
    });
    API.get("ratios", { symbol: sym }).then(function (r) {
      ratios = (r.body && r.body.data) || null;
      recon = (r.body && r.body.reconciliation) || null;
      if (!el("ov-r")) return;
      el("ov-r").innerHTML = "<h3>Key metrics " + F.statusPill(r.body.status) + "</h3>" + (ratios ?
        "<dl class='kv'>" + [["Market cap", "MarketCapitalization"], ["P/E", "PERatio"], ["P/B", "PriceToBookRatio"],
          ["EV/EBITDA", "EVToEBITDA"], ["Div yield", "DividendYield"], ["EPS", "EPS"],
          ["ROE", "ROE"], ["Beta", "Beta"]].map(function (pair) {
            var v = ratios[pair[1]];
            return "<dt>" + pair[0] + "</dt><dd>" + (v === undefined || v === null || v === "None" || v === "-" ? "—" : F.esc(String(v))) + "</dd>";
          }).join("") + "</dl>" :
        emptyState("Fundamentals unavailable", (r.body && r.body.message) || "No configured provider currently supplies valuation.", r.body)) + srcLine(r.body) + provStatus(r.body);
      maybeBrief();
    });
    API.get("history", { symbol: sym, range: "3M", interval: "1d" }).then(function (r) {
      history = (r.body && r.body.data) || null;
      maybeBrief();
    });
    API.get("history", { symbol: sym, range: "6M", interval: "1d" }).then(function (r) {
      if (!el("ov-chart")) return;
      var d = r.body && r.body.data;
      if (!d || !d.bars || !d.bars.length) {
        el("ov-chart").innerHTML = "<h3>Price — 6M " + F.statusPill("CALCULATED") + "</h3>" +
          unavail((r.body && r.body.message) || "No chart data.") + srcLine(r.body);
        return;
      }
      el("ov-chart").innerHTML = "<h3>Price — 6M</h3><div class='chart-box'>" +
        "<canvas class='chart' id='ov-c' style='height:180px' role='img' aria-label='Six month price history'></canvas>" +
        "<div class='chart-tip'></div></div>" + srcLine(r.body);
      window.FT_CHART.drawPriceChart(el("ov-c"), d.bars, { sma: [20, 50] });
    });
    API.get("fundamentals", { symbol: sym, statement: "income", period: "annual" }).then(function (r) {
      if (!el("ov-fsnap")) return;
      var d = r.body && r.body.data, reps = (d && d.reports) || [];
      if (reps.length < 1) {
        el("ov-fsnap").innerHTML = "<h3>Fundamental snapshot</h3>" +
          emptyState("Fundamental snapshot unavailable", (r.body && r.body.message) || "No configured provider currently supplies this financial statement.", r.body) + srcLine(r.body);
        return;
      }
      function num(rep, keys) {
        for (var i = 0; i < keys.length; i++) {
          var v = rep[keys[i]];
          if (v !== undefined && v !== null && v !== "None" && v !== "-") { var n = Number(v); if (!isNaN(n)) return n; }
        }
        return null;
      }
      function row(l, vals, isPct, src) {
        var cur = vals[0], prev = vals[1];
        var yoy = (cur !== null && prev !== null && prev !== 0) ? (cur - prev) / Math.abs(prev) * 100 : null;
        var tr = yoy === null ? "—" : "<span class='" + F.dirClass(yoy) + "'>" + (yoy >= 0 ? "▲" : "▼") + " " + F.fmtPct(yoy) + "</span>";
        function cell(v) { return v === null ? "—" : (isPct ? v.toFixed(1) + "%" : F.fmtMoney(v)); }
        return "<tr><td class='txt'>" + l + "</td><td class='num'><b>" + cell(cur) + "</b></td><td class='num'>" + cell(prev) +
          "</td><td class='num " + F.dirClass(yoy) + "'>" + F.fmtPct(yoy) + "</td><td class='num'>" + tr +
          "</td><td><span class='sect-tag'>" + src + "</span></td></tr>";
      }
      var r0 = reps[0], r1 = reps[1] || {};
      var rev0 = num(r0, ["totalRevenue", "revenue", "revenues", "sales"]), rev1 = num(r1, ["totalRevenue", "revenue", "revenues", "sales"]);
      var ni0 = num(r0, ["netIncome", "net_income", "netEarnings"]), ni1 = num(r1, ["netIncome", "net_income", "netEarnings"]);
      var eps0 = num(r0, ["eps", "EPS", "dilutedEPS"]), eps1 = num(r1, ["eps", "EPS", "dilutedEPS"]);
      var gm = (rev0 && num(r0, ["grossProfit", "gross_profit"])) ? num(r0, ["grossProfit", "gross_profit"]) / rev0 * 100 : null;
      var nm = (rev0 && ni0) ? ni0 / rev0 * 100 : null;
      el("ov-fsnap").innerHTML = "<h3>Fundamental snapshot — annual " + F.statusPill("live") + "</h3>" +
        '<div class="twrap"><table class="t"><thead><tr><th scope="col">Metric</th><th scope="col" class="num">Current</th>' +
        '<th scope="col" class="num">Previous</th><th scope="col" class="num">YoY</th><th scope="col">Trend</th><th scope="col">Source</th></tr></thead><tbody>' +
        row("Revenue", [rev0, rev1], false, "REPORTED") +
        row("Net profit", [ni0, ni1], false, "REPORTED") +
        row("EPS", [eps0, eps1], false, "REPORTED") +
        row("Gross margin", [gm, null], true, "CALCULATED") +
        row("Net margin", [nm, null], true, "CALCULATED") +
        "</tbody></table></div>" +
        "<div class='prov'>Periods: <b>" + F.esc(r0.fiscalDateEnding || r0.date || "?") + "</b> vs <b>" +
        F.esc(r1.fiscalDateEnding || r1.date || "?") + "</b> · currency: <b>" + F.esc(d.currency || "?") +
        "</b> · src: <b>" + F.esc(r.body.source || "?") + "</b></div>";
    });
    API.get("holdings", { symbol: sym }).then(function (r) {
      if (!el("ov-own")) return;
      var hd = (r.body && r.body.data) || null, owns = (hd && hd.ownership) || [];
      el("ov-own").innerHTML = "<h3>Ownership " + F.statusPill(r.body.status) + "</h3>" +
        (owns.length ? owns.slice(0, 4).map(function (o) {
          return "<div class='kv' style='margin-bottom:2px'><dt>" + F.esc(o.category || "?") + "</dt><dd>" +
            (o.percentage !== null && o.percentage !== undefined ? Number(o.percentage).toFixed(1) + "%" : "—") + "</dd></div>";
        }).join("") + "<div class='prov'>as of <b>" + F.esc(owns[0].holding_date || "?") + "</b></div>"
        : unavail((r.body && r.body.message) || "Ownership unavailable for this security.")) + srcLine(r.body);
    });
    API.get("news", { symbol: sym, limit: 5 }).then(function (r) {
      if (!el("ov-news")) return;
      var d = r.body && r.body.data;
      el("ov-news").innerHTML = "<h3>Latest news</h3>" +
        (d && d.items && d.items.length ? d.items.slice(0, 5).map(newsItem).join("") : unavail((r.body && r.body.message) || "No news.")) +
        srcLine(r.body);
    });
    function maybeBrief() {
      if (++settled < 3) return;
      if (!el("ov-brief") || el("ov-brief").getAttribute("data-done")) return;
      el("ov-brief").setAttribute("data-done", "1");
      var brief = window.FT_ANALYSIS.brief(sym, quote, history, ratios, recon);
      window.FT_ANALYSIS.renderBrief(el("ov-brief"), brief);
    }
  }
  function stmtTable(title, env) {
    if (!env || !env.data) return "<h2 class='h-sec'>" + title + "</h2>" +
      emptyState("Financial statements unavailable", (env && env.message) || "No configured provider currently supplies this financial statement.", env);
    var d = env.data, reps = d.reports || [];
    if (!reps.length) return "<h2 class='h-sec'>" + title + "</h2>" + emptyState("Financial statements unavailable", "No reports returned.", env);
    var keys = Object.keys(reps[0]).filter(function (k) { return k !== "fiscalDateEnding" && k !== "reportedCurrency"; }).slice(0, 14);
    var h = "<h2 class='h-sec'>" + title + " " + F.statusPill(env.status) + "</h2>" +
      '<div class="prov">currency: <b>' + F.esc(d.currency || "?") + "</b> · period: <b>" + F.esc(d.period || "") + "</b> · src: <b>" + F.esc(env.source || "") + "</b></div>" +
      '<div class="card flush twrap"><table class="t"><thead><tr><th scope="col" class="freeze">Line item</th>';
    reps.slice(0, 6).forEach(function (r) { h += "<th scope='col' class='num'>" + F.esc(r.fiscalDateEnding || "") + "</th>"; });
    h += "<th scope='col' class='num'>YoY</th></tr></thead><tbody>";
    keys.forEach(function (k, ix) {
      var important = /revenue|netincome|grossprofit|ebitda|operatingincome|eps/i.test(k.replace(/\s/g, ""));
      h += "<tr" + (ix % 2 ? " class='zeb'" : "") + "><td class='txt freeze'" + (important ? " style='font-weight:650'" : "") + ">" + F.esc(k) + "</td>";
      var vals = reps.slice(0, 6).map(function (r) { return r[k] === "None" ? null : Number(r[k]); });
      vals.forEach(function (v) { h += "<td class='num'>" + (v === null || isNaN(v) ? "—" : F.fmtMoney(v)) + "</td>"; });
      var yoy = (vals[0] !== null && vals[1] !== null && vals[1] !== 0 && !isNaN(vals[0]) && !isNaN(vals[1]))
        ? (vals[0] - vals[1]) / Math.abs(vals[1]) * 100 : null;
      h += "<td class='num " + F.dirClass(yoy) + "'>" + F.fmtPct(yoy) + " <span class='pill pill-calc'>CALC</span></td></tr>";
    });
    return h + "</tbody></table></div>";
  }
  function tFinancials(sym, b) {
    b.innerHTML = "<div class='card sect'><h3>Financial statements</h3>" +
      "<div class='row'><label class='f'>Statement<select id='f-s' class='in'><option value='income'>Income</option><option value='balance'>Balance sheet</option><option value='cashflow'>Cash flow</option></select></label>" +
      "<label class='f'>Period<select id='f-p' class='in'><option value='annual'>Annual</option><option value='quarterly'>Quarterly</option></select></label>" +
      "<button class='btn primary' id='f-go'>Load</button></div>" +
      "<div class='prov'>Reported statements only — Alpha Vantage / Twelve Data / Indian Stock Market API where configured. Never synthesised.</div></div><div id='f-out' style='margin-top:10px'></div>";
    function go() {
      el("f-out").innerHTML = "<div class='card'>" + skel(6) + "</div>";
      API.get("fundamentals", { symbol: sym, statement: el("f-s").value, period: el("f-p").value }).then(function (r) {
        if (!el("f-out")) return;
        el("f-out").innerHTML = stmtTable("Financial statements", r.body) + srcLine(r.body);
      });
    }
    el("f-go").onclick = go; go();
  }
  function tValuation(sym, b) {
    b.innerHTML = "<div id='v-out'>" + skel(6) + "</div>";
    API.get("ratios", { symbol: sym }).then(function (rr) {
      API.get("quote", { symbol: sym }).then(function (rq) {
        if (!el("v-out")) return;
        var r = (rr.body && rr.body.data) || null, q = (rq.body && rq.body.data) || null;
        var vm = (rr.body && rr.body.valuation) || {};
        function mkind(name, fallback) {
          return ((vm[name] || {}).kind) || fallback;
        }
        if (!r) {
          el("v-out").innerHTML = "<div class='card'><h3>Valuation " + F.statusPill(rr.body.status) + "</h3>" +
            emptyState("Valuation unavailable", (rr.body && rr.body.message) || "No configured provider currently supplies valuation.", rr.body) + srcLine(rr.body) + "</div>";
          return;
        }
        function mx(label, v, sub) {
          return kpi(label, v === undefined || v === null || v === "None" || v === "-" ? unaCell() : F.esc(String(v)), sub || "reported");
        }
        var calcPe = (function () {
          var eps = (r.EPS && r.EPS !== "None" && r.EPS !== "-") ? Number(r.EPS) : null;
          var px = q && q.price !== undefined ? Number(q.price) : null;
          if (eps === null || isNaN(eps) || eps <= 0 || px === null || isNaN(px)) return null;
          return (px / eps).toFixed(2);
        })();
        el("v-out").innerHTML = "<div class='kpis sect'>" +
          mx("P/E", r.PERatio && r.PERatio !== "None" ? Number(r.PERatio).toFixed(1) + "x" : null, "TTM · reported") +
          mx("P/B", r.PriceToBookRatio && r.PriceToBookRatio !== "None" ? Number(r.PriceToBookRatio).toFixed(1) + "x" : null, "reported") +
          mx("EV/EBITDA", r.EVToEBITDA && r.EVToEBITDA !== "None" ? Number(r.EVToEBITDA).toFixed(1) + "x" : null, "reported") +
          mx("P/S", r.PriceToSalesRatioTTM && r.PriceToSalesRatioTTM !== "None" ? Number(r.PriceToSalesRatioTTM).toFixed(1) + "x" : null, "reported") +
          mx("Div yield", r.DividendYield && r.DividendYield !== "None" ? r.DividendYield + "%" : null, "reported") +
          mx("EPS", r.EPS && r.EPS !== "None" ? F.fmtNum(Number(r.EPS)) : null, "TTM · reported") + "</div>" +
          "<div class='card'><h3>Valuation detail — provider vs calculated " + F.statusPill(rr.body.status) + "</h3>" +
          '<div class="twrap"><table class="t"><thead><tr><th scope="col">Metric</th><th scope="col" class="num">Value</th><th scope="col">Kind</th></tr></thead><tbody>' +
          "<tr><td class='txt'>Price</td><td class='num'>" + (q && q.price !== undefined ? F.fmtNum(q.price) + " " + F.esc(q.currency || "") : "—") + "</td><td>" + F.statusPill("delayed") + "</td></tr>" +
          "<tr><td class='txt'>Market cap</td><td class='num'>" + (r.MarketCapitalization ? F.fmtIN(Number(r.MarketCapitalization), q && q.currency) : "—") + "</td><td>" + mkind("market_cap", "REPORTED") + "</td></tr>" +
          "<tr><td class='txt'>Forward P/E</td><td class='num'>" + (r.ForwardPE && r.ForwardPE !== "None" ? F.esc(String(r.ForwardPE)) : "—") + "</td><td>REPORTED</td></tr>" +
          "<tr><td class='txt'>PEG</td><td class='num'>" + (r.PEGRatio && r.PEGRatio !== "None" ? F.esc(String(r.PEGRatio)) : "—") + "</td><td>REPORTED</td></tr>" +
          (calcPe !== null ? "<tr><td class='txt'>P/E (price ÷ reported EPS " + F.esc(String(r.EPS)) + ")</td><td class='num'>" + calcPe + "</td><td>CALCULATED</td></tr>" : "") +
          "</tbody></table></div>" + srcLine(rr.body) +
          "<div class='prov'>Forward P/E shown only when the feed returns it — never estimated in-terminal.</div></div>" +
          reconHtml(rr.body);
        function reconHtml(env) {
          var rec = env.reconciliation;
          if (!rec || !rec.comparisons || !rec.comparisons.length) return "";
          function pill(st) {
            return F.statusPill(st === "CROSS_CHECK_OK" ? "CALCULATED" :
              (st === "PROVIDER_DISCREPANCY" ? "UNAVAILABLE" : "STALE"));
          }
          return "<div class='card' style='margin-top:10px'><h3>Cross-check (primary × other source)</h3>" +
            '<div class="twrap"><table class="t"><thead><tr><th scope="col">Field</th><th scope="col">Primary</th><th scope="col">Other source</th><th scope="col">Status</th></tr></thead><tbody>' +
            rec.comparisons.map(function (c) {
              var other = (c.cross_check || []).map(function (o) {
                return F.esc(o.source) + ": " + F.esc(o.value === null || o.value === undefined ? "—" : o.value) +
                  (o.difference_pct !== null && o.difference_pct !== undefined ? " (" + o.difference_pct.toFixed(2) + "%)" : "") +
                  (o.reason ? " [" + F.esc(o.reason) + "]" : "");
              }).join("<br>") || "—";
              return "<tr><td class='txt'>" + F.esc(c.field) + "</td><td class='num'>" +
                F.esc(c.primary.value === null || c.primary.value === undefined ? "—" : c.primary.value) +
                " <span class='sect-tag'>" + F.esc(c.primary.source) + "</span></td><td class='txt'>" + other +
                "</td><td>" + pill(c.status) + "<div class='src'>" + F.esc(c.status) + "</div></td></tr>";
            }).join("") + "</tbody></table></div>" +
            "<div class='prov'>" + F.esc(rec.summary ? (rec.summary.cross_check_ok + " agree · " + rec.summary.discrepancies + " disagree · " + rec.summary.single_source + " single-source") : "") + "</div></div>";
        }
      });
    });
  }
  function tEstimates(sym, b) {
    b.innerHTML = "<div id='e-out'>" + skel(3) + "</div>";
    API.get("estimates", { symbol: sym }).then(function (r) {
      if (!el("e-out")) return;
      var d = r.body && r.body.data;
      if (!d) {
        el("e-out").innerHTML = "<div class='card'><h3>Analyst estimates " + F.statusPill(r.body.status) + "</h3>" +
          emptyState("Estimates unavailable", (r.body && r.body.message) || "No configured provider currently supplies analyst estimates.", r.body) + srcLine(r.body) + "</div>";
        return;
      }
      function estRows(list) {
        return (list || []).map(function (x) {
          return "<tr><td class='txt'>" + F.esc(x.fiscalDateEnding || x.horizon || "—") + "</td>" +
            "<td class='num'>" + F.esc(x.epsAvgEstimate !== undefined ? x.epsAvgEstimate : (x.eps !== undefined ? x.eps : "—")) + "</td>" +
            "<td class='num'>" + F.esc(x.revenueAvgEstimate !== undefined ? x.revenueAvgEstimate : (x.revenue !== undefined ? x.revenue : "—")) + "</td>" +
            "<td class='num'>" + F.esc(x.numAnalysts !== undefined ? x.numAnalysts : "—") + "</td></tr>";
        }).join("");
      }
      function estTable(list) {
        return '<div class="twrap"><table class="t"><thead><tr><th scope="col">Period</th><th scope="col" class="num">EPS est</th><th scope="col" class="num">Revenue est</th><th scope="col" class="num"># analysts</th></tr></thead><tbody>' + estRows(list) + "</tbody></table></div>";
      }
      var ar = d.analyst_ratings, ratingsHtml = "";
      if (ar && (ar.distribution || ar.bands || ar.no_of_recommendations)) {
        var head = "";
        if (ar.no_of_recommendations !== undefined && ar.no_of_recommendations !== null) {
          head = "<div class='kpis sect'>" +
            kpi("Recommendations", F.esc(String(ar.no_of_recommendations)), "reported") +
            kpi("Buy call", ar.buy_percentage !== undefined && ar.buy_percentage !== null ? Number(ar.buy_percentage).toFixed(1) + "%" : "—", "reported") +
            kpi("Mean rating", ar.mean_rating !== undefined && ar.mean_rating !== null ? Number(ar.mean_rating).toFixed(2) : "—", "reported") + "</div>";
        }
        var tables = "";
        if (ar.distribution && ar.distribution.length) {
          tables = '<div class="twrap"><table class="t"><thead><tr><th scope="col">Rating</th><th scope="col" class="num">Analysts (latest)</th></tr></thead><tbody>' +
            ar.distribution.map(function (bucket) {
              return "<tr><td class='txt'>" + F.esc(bucket.rating || "—") + "</td>" +
                "<td class='num'>" + (bucket.analysts !== undefined && bucket.analysts !== null ? F.esc(String(bucket.analysts)) : "—") + "</td></tr>";
            }).join("") + "</tbody></table></div>";
        }
        if (ar.bands && ar.bands.length) {
          tables += '<div class="twrap" style="margin-top:10px"><table class="t"><thead><tr><th scope="col">Rating band</th><th scope="col" class="num">Analysts</th></tr></thead><tbody>' +
            ar.bands.map(function (x) {
              return "<tr><td class='txt'>" + F.esc(x.rating || "—") + (x.band && x.band.length ? " <span class='src'>(" + F.esc(String(x.band[0])) + "–" + F.esc(String(x.band[1])) + ")</span>" : "") + "</td>" +
                "<td class='num'>" + (x.analysts !== undefined && x.analysts !== null ? F.esc(String(x.analysts)) : "—") + "</td></tr>";
            }).join("") + "</tbody></table></div>";
        }
        ratingsHtml = "<div class='card sect'><h3>Analyst ratings (reported)</h3>" + head + tables + "</div>";
      }
      var hasRatings = ar && (ar.distribution || ar.bands || ar.no_of_recommendations);
      el("e-out").innerHTML = "<h2 class='h-sec'>Analyst estimates · " + F.esc(sym) + " " + F.statusPill(r.body.status) + "</h2>" +
        "<div class='prov'>REPORTED forecasts only — never synthesised in-terminal.</div>" + ratingsHtml +
        "<div class='card sect'><h3>EPS forecasts — annual</h3>" +
        ((d.annual && d.annual.length) ? estTable(d.annual)
          : unavail(hasRatings ? "Annual EPS forecasts not provided by this feed." : "No annual estimate rows reported.")) + "</div>" +
        "<div class='card sect'><h3>EPS forecasts — quarterly</h3>" +
        ((d.quarterly && d.quarterly.length) ? estTable(d.quarterly)
          : unavail(hasRatings ? "Quarterly EPS forecasts not provided by this feed." : "No quarterly estimate rows reported.")) +
        ((d.note) ? "<div class='prov'>" + F.esc(d.note) + "</div>" : "") + "</div>" + srcLine(r.body);
    });
  }
  function tEarnings(sym, b) {
    b.innerHTML = "<div id='e2-out'>" + skel(5) + "</div>";
    API.get("earnings", { symbol: sym }).then(function (r) {
      if (!el("e2-out")) return;
      var d = r.body && r.body.data;
      if (!d) {
        el("e2-out").innerHTML = "<div class='card'><h3>Earnings " + F.statusPill(r.body.status) + "</h3>" +
          emptyState("Earnings unavailable", (r.body && r.body.message) || "No configured provider currently supplies earnings.", r.body) + srcLine(r.body) + "</div>";
        return;
      }
      function repRow(x) {
        var sv = x.surprise !== undefined ? x.surprise : (x.surprisePercentage !== undefined ? x.surprisePercentage + "%" : null);
        var cls = (typeof sv === "number") ? F.dirClass(sv) : (typeof x.surprisePercentage === "number" ? F.dirClass(x.surprisePercentage) : "");
        return "<tr><td class='txt'>" + F.esc(x.fiscalDateEnding || x.reportedDate || "—") + "</td>" +
          "<td class='num'>" + F.esc(x.reportedEPS !== undefined ? x.reportedEPS : "—") + "</td>" +
          "<td class='num'>" + F.esc(x.estimatedEPS !== undefined ? x.estimatedEPS : "—") + "</td>" +
          "<td class='num " + cls + "'>" + F.esc(sv === null ? "—" : sv) + "</td></tr>";
      }
      function earnTable(list) {
        return '<div class="twrap"><table class="t"><thead><tr><th scope="col">Fiscal end</th><th scope="col" class="num">Reported EPS</th><th scope="col" class="num">Est. EPS</th><th scope="col" class="num">Surprise</th></tr></thead><tbody>' + list.map(repRow).join("") + "</tbody></table></div>";
      }
      el("e2-out").innerHTML = "<h2 class='h-sec'>Earnings · " + F.esc(sym) + " " + F.statusPill(r.body.status) + "</h2>" +
        "<div class='prov'>Periods never mixed · reported vs estimated labeled per cell · never synthesised</div>" +
        "<div class='card sect'><h3>Annual</h3>" +
        ((d.annual && d.annual.length) ? earnTable(d.annual) : unavail("No annual earnings rows.")) + "</div>" +
        "<div class='card sect'><h3>Quarterly</h3>" +
        ((d.quarterly && d.quarterly.length) ? earnTable(d.quarterly) : unavail("No quarterly earnings rows.")) + "</div>" +
        srcLine(r.body);
    });
  }
  function tNews(sym, b) {
    b.innerHTML = "<div class='card' id='n-out'>" + skel(5) + "</div>";
    API.get("news", { symbol: sym, limit: 20 }).then(function (r) {
      if (!el("n-out")) return;
      var d = r.body && r.body.data;
      var items = (d && d.items) || [];
      var cats = ["All", "Company", "Markets", "Results", "Corporate", "Regulatory"];
      function catOf(it) {
        var t = ((it.title || "") + " " + (it.summary || "")).toLowerCase();
        if (/result|earning|profit|revenue|quarter|guidance/.test(t)) return "Results";
        if (/dividend|split|bonus|right|merger|acquis|buyback|agm|board meet/.test(t)) return "Corporate";
        if (/sebi|regulat|approv|filing|compliance|order|penalty/.test(t)) return "Regulatory";
        if (/market|sensex|nifty|index|sector|economy|rate|inflation/.test(t)) return "Markets";
        return "Company";
      }
      function paint(sel) {
        if (!el("n-out")) return;
        var list = sel === "All" ? items : items.filter(function (it) { return catOf(it) === sel; });
        el("n-out").innerHTML = "<h3>News · " + F.esc(sym) + " " + F.statusPill(r.body.status) + "</h3>" +
          "<div class='fchips' role='group' aria-label='News filter'>" + cats.map(function (c) {
            return "<button data-c='" + c + "'" + (c === sel ? " class='on'" : "") + ">" + c + "</button>";
          }).join("") + "</div>" +
          (list.length ? list.map(newsItem).join("") : "<div class='src'>No " + F.esc(sel) + " items in this batch.</div>") +
          srcLine(r.body);
        Array.prototype.forEach.call(document.querySelectorAll("#n-out .fchips button"), function (btn) {
          btn.onclick = function () { paint(btn.getAttribute("data-c")); };
        });
      }
      if (!items.length) {
        el("n-out").innerHTML = "<h3>News · " + F.esc(sym) + " " + F.statusPill(r.body.status) + "</h3>" +
          unavail((r.body && r.body.message) || "News unavailable.") + srcLine(r.body);
        return;
      }
      paint("All");
    });
  }
  function tActions(sym, b) {
    b.innerHTML = "<div class='card' id='a-out'>" + skel(4) + "</div>";
    API.get("actions", { symbol: sym }).then(function (r) {
      if (!el("a-out")) return;
      var d = r.body && r.body.data;
      if (!d) { el("a-out").innerHTML = "<div class='card'><h3>Corporate actions</h3>" + unavail((r.body && r.body.message) || "Unavailable.") + srcLine(r.body) + "</div>"; return; }
      function shownDate(x) {
        if (typeof x === "number") return F.fmtDate(x);
        return F.esc(x || "—");
      }
      function divRows(list) {
        return list.slice(0, 20).map(function (x) {
          return "<tr><td class='txt'><b>" + shownDate(x.date) + "</b></td><td class='num'>" + F.fmtNum(x.amount, 4) + " " + F.esc(x.currency || "") +
            "</td><td><span class='sect-tag'>" + F.esc(x.source || "?") + "</span></td></tr>";
        }).join("");
      }
      function splitRows(list) {
        return list.map(function (x) {
          return "<tr><td class='txt'><b>" + shownDate(x.date) + "</b></td><td class='num'>" + F.esc(x.numerator + ":" + x.denominator) +
            "</td><td><span class='sect-tag'>" + F.esc(x.source || "?") + "</span></td></tr>";
        }).join("");
      }
      el("a-out").innerHTML = "<div class='card sect'><h3>Dividends (" + d.dividends.length + ") " + F.statusPill(r.body.status) + "</h3>" +
        (d.dividends.length ? '<div class="twrap"><table class="t"><thead><tr><th scope="col">Date</th><th scope="col" class="num">Amount</th><th scope="col">Source</th></tr></thead><tbody>' +
          divRows(d.dividends) + "</tbody></table></div>" : unavail("No dividends reported by configured sources.")) + "</div>" +
        "<div class='card sect'><h3>Splits (" + d.splits.length + ")</h3>" +
        (d.splits.length ? '<div class="twrap"><table class="t"><thead><tr><th scope="col">Date</th><th scope="col" class="num">Ratio</th><th scope="col">Source</th></tr></thead><tbody>' +
          splitRows(d.splits) + "</tbody></table></div>" : unavail("No splits reported by configured sources.")) + "</div>" +
        "<div class='prov'>" + F.esc(d.note || "") + "</div>" + srcLine(r.body);
    });
  }
  function tHoldings(sym, b) {
    b.innerHTML = "<div id='h-out'>" + skel(3) + "</div>";
    Promise.all([
      API.get("quote", { symbol: sym }),
      API.get("ratios", { symbol: sym }),
      API.get("holdings", { symbol: sym })
    ]).then(function (rs) {
      if (!el("h-out")) return;
      var rq = rs[0], rr = rs[1], rh = rs[2];
      var q = (rq.body && rq.body.data) || {}, r = (rr.body && rr.body.data) || null;
      function row(l, v, src) {
        return "<tr><td class='txt'>" + l + "</td><td class='num'>" + (v === undefined || v === null || v === "None" || v === "-" ? "—" : F.esc(String(v))) +
          "</td><td><span class='sect-tag'>" + src + "</span></td></tr>";
      }
      var primLab = (r && /^indian-api/.test(r._metric_source || "")) ? "Indian Stock Market API" : "Alpha Vantage";
      var h = "<div class='card sect'><h3>Capital structure</h3>";
      if (r) {
        h += '<div class="twrap"><table class="t"><thead><tr><th scope="col">Metric</th><th scope="col" class="num">Value</th><th scope="col">Kind</th></tr></thead><tbody>' +
          row("Shares outstanding", r.SharesOutstanding, "REPORTED · " + primLab) +
          row("Market cap", r.MarketCapitalization ? F.fmtIN(Number(r.MarketCapitalization), q.currency) : null, "REPORTED · " + primLab) +
          row("Book value / share", r.BookValue, "REPORTED · " + primLab);
        var price = q.price, mcap = r ? FLT(r.MarketCapitalization) : null;
        var implShares = (price && mcap) ? mcap / price : null;
        if (implShares) h += row("Implied shares (mktcap ÷ price)", Math.round(implShares).toLocaleString("en-US"), "CALCULATED · quote × overview");
        h += "</tbody></table></div>";
      } else {
        h += emptyState("Capital metrics unavailable", (rr.body && rr.body.message) || "No configured provider currently supplies valuation.", rr.body);
      }
      h += "</div>";
      var hd = (rh.body && rh.body.data) || null;
      var owns = hd && hd.ownership ? hd.ownership : [];
      var total = owns.reduce(function (s, o) { return s + (Number(o.percentage) || 0); }, 0);
      h += "<div class='card sect'><h3>Ownership split " + F.statusPill(rh.body.status) + "</h3>";
      if (owns.length) {
        var palette = ["#1a56c4", "#18794e", "#9a6b12", "#6d4fc2", "#687182", "#c03535"];
        h += '<div class="twrap"><table class="t"><thead><tr><th scope="col">Category</th><th scope="col" class="num">% holding</th><th scope="col">As of</th><th scope="col">Source</th></tr></thead><tbody>' +
          owns.map(function (o) {
            return "<tr><td class='txt'>" + F.esc(o.category || "—") + "</td>" +
              "<td class='num'>" + (o.percentage !== null && o.percentage !== undefined ? Number(o.percentage).toFixed(2) + "%" : "—") + "</td>" +
              "<td class='txt'>" + F.esc(o.holding_date || "—") + "</td>" +
              "<td><span class='sect-tag'>" + F.esc(o.source || "indian-api") + "</span></td></tr>";
          }).join("") + "</tbody></table></div>";
        h += "<div class='alloc' role='img' aria-label='Ownership allocation'>" + owns.map(function (o, ix) {
          var w = total > 0 ? (Number(o.percentage) || 0) / total * 100 : 0;
          return "<span style='width:" + w.toFixed(1) + "%;background:" + palette[ix % palette.length] + "'></span>";
        }).join("") + "</div><div class='alloc-legend'>" + owns.map(function (o, ix) {
          return "<span><i style='background:" + palette[ix % palette.length] + "'></i>" + F.esc(o.category || "?") + " " + F.esc(o.percentage) + "%</span>";
        }).join("") + "</div>";
      } else {
        h += emptyState("Ownership unavailable", (rh.body && rh.body.message) || "No ownership split available. Splits are never guessed.", rh.body);
      }
      h += (hd && hd.note ? "<div class='prov'>" + F.esc(hd.note) + "</div>" : "") + "</div>";
      el("h-out").innerHTML = "<h2 class='h-sec'>Ownership</h2>" + h + srcLine(rh.body);
      function FLT(v) { var n = Number(v); return isNaN(n) ? null : n; }
    });
  }
  var TV_MAP = {
    "^NSEI": "NSE:NIFTY", "^NSEBANK": "NSE:BANKNIFTY", "^BSESN": "BSE:SENSEX",
    "^GSPC": "SP:SPX", "^IXIC": "NASDAQ:NDX", "^FTSE": "TVC:UKX",
  };
  function tvSymbol(sym) {
    if (TV_MAP[sym]) return TV_MAP[sym];
    if (/\.NS$/.test(sym)) return "NSE:" + sym.slice(0, -3);
    if (/\.BO$/.test(sym)) return "BSE:" + sym.slice(0, -3);
    return sym;
  }
  function tCharts(sym, b, range, interval) {
    var smas = [20, 50];
    b.innerHTML = "<div class='row'><div class='row' role='group' aria-label='Chart source'>" +
      "<button class='btn sm primary' id='ch-t1'>Terminal chart</button>" +
      "<button class='btn sm' id='ch-t2'>TradingView chart</button></div>" +
      "<span id='ch-ranges' class='row' role='group' aria-label='Timeframe'>" +
      ["1D", "5D", "1M", "3M", "6M", "1Y", "5Y", "MAX"].map(function (x) {
        return "<button class='btn sm" + (x === range ? " primary" : "") + "' data-r='" + x + "'>" + x + "</button>";
      }).join("") + "</span>" +
      "<span class='ch-legend' id='ch-smas'>" +
      [[20, true], [50, true], [200, false]].map(function (p) {
        return "<label><input type='checkbox' data-sma='" + p[0] + "'" + (p[1] ? " checked" : "") + "> SMA" + p[0] + "</label>";
      }).join("") + "</span></div>" +
      "<div class='card sect' id='ch-tvnote' style='display:none'>" +
      "<h3>TRADINGVIEW CHART " + F.statusPill("delayed") + "</h3>" +
      "<div class='src'>Official TradingView embed. Its data is TradingView's own feed — not ours, not scraped, not re-labeled. " +
      "Free widget data is delayed; NSE real-time requires an authorized feed.</div>" +
      "<div id='ch-tvw' style='height:420px;margin-top:8px'></div></div>" +
      "<div class='card sect' id='ch-own'><h3>Chart — delayed backend data</h3><div class='chart-box'><canvas class='chart' id='ch-c' role='img' aria-label='Price history chart'></canvas><div class='chart-tip'></div></div>" +
      "<div class='ch-legend'><span><i style='color:#18794e'>—</i> price</span><span><i style='color:#1a56c4'>—</i> SMA</span>" +
      "<span id='ch-meta'></span></div></div>" +
      "<div class='prov'>NSE real-time not available without an authorized feed — never claimed. " +
      "Terminal charts use delayed backend history with volume where returned.</div>" +
      "<div class='card sect' id='ch-tech'>" + skel(3) + "</div>";
    function curSmas() {
      var out = [];
      Array.prototype.forEach.call(document.querySelectorAll("#ch-smas input"), function (c) {
        if (c.checked) out.push(Number(c.getAttribute("data-sma")));
      });
      return out.length ? out : [20];
    }
    function draw() {
      var indianPeriod = { "1M": "1m", "3M": "6m", "6M": "6m", "1Y": "1yr", "3Y": "3yr", "5Y": "5yr", "MAX": "max" }[range];
      var tryIndian = indianPeriod && /\.NS$|\.BO$/.test(sym) && interval === "1d";
      function renderHistory(r) {
        if (!el("ch-c")) return;
        var d = r.body && r.body.data;
        if (!d || !d.bars || !d.bars.length) {
          el("ch-c").outerHTML = unavail((r.body && r.body.message) || "No chart data.");
          return;
        }
        smas = curSmas();
        window.FT_CHART.drawPriceChart(el("ch-c"), d.bars, { sma: smas });
        el("ch-meta").textContent = "n=" + d.bars.length + " · " + (d.interval || "1d") + " · " +
          (r.body.timeliness || r.body.status) + " · " + F.srcName(r.body.source) + " · " + d.currency +
          " · as of " + F.fmtIST(r.body.as_of);
      }
      if (tryIndian) {
        API.get("indian-history", { symbol: sym, period: indianPeriod, filter: "price" }).then(function (r) {
          if ((r.body && r.body.data && r.body.data.bars && r.body.data.bars.length)) renderHistory(r);
          else API.get("history", { symbol: sym, range: range, interval: interval }).then(renderHistory);
        });
      } else {
        API.get("history", { symbol: sym, range: range, interval: interval }).then(renderHistory);
      }
    }
    draw();
    Array.prototype.forEach.call(document.querySelectorAll("#ch-smas input"), function (c) {
      c.onchange = draw;
    });
    API.get("technical", { symbol: sym }).then(function (r) {
      if (!el("ch-tech")) return;
      var d = r.body && r.body.data;
      if (!d) {
        el("ch-tech").innerHTML = "<h3>Technicals " + F.statusPill("CALCULATED") + "</h3>" +
          unavail((r.body && r.body.message) || "Needs verified history.") + srcLine(r.body);
        return;
      }
      el("ch-tech").innerHTML = "<h3>Technicals " + F.statusPill("CALCULATED") + "</h3>" +
        "<div class='prov'>CALCULATED FROM: <b>" + F.esc(d.calculated_from || "?") + "</b> · PERIODS: <b>" + d.periods +
        "</b> daily bars · CALCULATED AT: <b>" + F.esc(d.calculated_at || "?") + "</b> · not provider-reported</div>" +
        "<div class='kpis' style='margin-top:8px'>" +
        kpi("RSI 14", d.rsi14 === null || d.rsi14 === undefined ? "—" : F.fmtNum(d.rsi14), "calculated") +
        kpi("MACD", d.macd === null || d.macd === undefined ? "—" : F.fmtNum(d.macd), "calculated") +
        kpi("Signal", d.macd_signal === null || d.macd_signal === undefined ? "—" : F.fmtNum(d.macd_signal), "calculated") +
        kpi("ATR 14", d.atr14 === null || d.atr14 === undefined ? "—" : F.fmtNum(d.atr14), "calculated") +
        kpi("Vol 20d ann.", d.volatility_20d_ann_pct === null || d.volatility_20d_ann_pct === undefined ? "—" : F.fmtNum(d.volatility_20d_ann_pct) + "%", "calculated") +
        kpi("Max drawdown", d.max_drawdown_pct === null || d.max_drawdown_pct === undefined ? "—" : F.fmtNum(d.max_drawdown_pct) + "%", "calculated") +
        "</div>";
    });
    el("ch-t2").onclick = function () {
      el("ch-own").style.display = "none";
      el("ch-tvnote").style.display = "";
      el("ch-t1").classList.remove("primary");
      el("ch-t2").classList.add("primary");
      loadTvWidget(sym);
    };
    el("ch-t1").onclick = function () { tCharts(sym, b, range, interval); };
    Array.prototype.forEach.call(document.querySelectorAll("#ch-ranges button"), function (btn) {
      btn.onclick = function () { tCharts(sym, b, btn.getAttribute("data-r"), range === "1D" ? "5m" : "1d"); };
    });
  }
  function tTechnicals(sym, b) {
    b.innerHTML = "<div class='card' id='tq-out'>" + skel(6) + "</div>";
    API.get("analytics", { symbol: sym }).then(function (r) {
      if (!el("tq-out")) return;
      var d = r.body && r.body.data;
      if (!d) {
        el("tq-out").innerHTML = "<h3>Technical analytics " + F.statusPill("CALCULATED") + "</h3>" +
          unavail((r.body && r.body.message) || "Needs verified history.") + srcLine(r.body);
        return;
      }
      function kv(label, v, suffix) {
        return "<div class='metric'><div class='l'>" + label + "</div><div class='v' style='font-size:13px'>" +
          (v === null || v === undefined ? "—" : F.fmtNum(v) + (suffix || "")) + "</div></div>";
      }
      function condTable(conds) {
        var keys = Object.keys(conds || {});
        if (!keys.length) return unavail("Trend checklist unavailable (insufficient history).");
        return '<div class="twrap"><table class="t"><thead><tr><th scope="col">Condition</th><th scope="col">Result</th></tr></thead><tbody>' +
          keys.map(function (k) {
            var v = conds[k];
            var pill = v === "pass" ? "<span class='pill pill-live'>PASS</span>" :
              (v === "fail" ? "<span class='pill pill-na'>FAIL</span>" : "<span class='pill pill-delayed'>UNKNOWN</span>");
            return "<tr><td class='txt'>" + F.esc(k.replace(/_/g, " ")) + "</td><td>" + pill + "</td></tr>";
          }).join("") + "</tbody></table></div>";
      }
      var ph = d.phase || {}, rs = d.relative_strength || {}, vcp = d.vcp || {},
        bo = d.breakout || {}, tt = d.trend_template || {}, rr = d.risk_reward || {},
        sc = d.score || {}, rg = d.regime || {};
      var comps = (sc.components || {});
      var h = "<h3>Technical regime " + F.statusPill("CALCULATED") + "</h3>" +
        "<div class='kpis'>" +
        kpi("Phase", ph.phase || "—", "descriptive, not a forecast") +
        kpi("Regime", rg.status || "—", "benchmark gauge") +
        kpi("RS vs " + F.esc(d.benchmark || "—"), rs.rs_pp === null || rs.rs_pp === undefined ? "—" : F.fmtPct(rs.rs_pp), "pp over lookback") +
        kpi("VCP", vcp.detected === null || vcp.detected === undefined ? "—" : (vcp.detected ? "Detected" : "Not detected"), vcp.quality || "") +
        kpi("Breakout", bo.status || "—", bo.distance_pct === null || bo.distance_pct === undefined ? "" : F.fmtPct(bo.distance_pct) + " vs level") +
        kpi("Setup score", sc.overall || "—", "components below") + "</div>" +
        "<h3 style='margin-top:12px'>Trend template (" + (tt.passed === undefined ? "—" : tt.passed + "/" + tt.total) + ")</h3>" +
        condTable(tt.conditions) +
        (tt.measurements && tt.measurements.relative_strength && tt.measurements.relative_strength.status === "OK" ? "" :
          "<div class='prov'>Relative-strength benchmark: <b>" + F.esc(d.benchmark || "none") + "</b></div>") +
        "<h3 style='margin-top:12px'>Risk / reward (technical reference)</h3>" +
        (rr.status === "OK"
          ? "<div class='grid g4'>" + kv("Entry ref", rr.reference_entry) + kv("Stop ref", rr.technical_stop) +
            kv("Risk", rr.risk_pct, "%") + kv("Target ref", rr.reference_target) +
            kv("Reward", rr.reward_pct, "%") + kv("R/R", rr.risk_reward_ratio) + "</div>" +
            "<div class='prov'>TECHNICAL REFERENCE — not investment advice. No target invented: requires a real level.</div>"
          : unavail("Risk/reward needs price, ATR and a real resistance level.")) +
        "<h3 style='margin-top:12px'>Score components</h3>" +
        '<div class="twrap"><table class="t"><thead><tr><th scope="col">Component</th><th scope="col" class="num">Value</th><th scope="col" class="num">Max</th><th scope="col">State</th></tr></thead><tbody>' +
        Object.keys(comps).map(function (k) {
          var c = comps[k];
          return "<tr><td class='txt'>" + F.esc(c.label || k) + "</td><td class='num'>" +
            (c.value === null || c.value === undefined ? "—" : c.value) + "</td><td class='num'>" + c.max +
            "</td><td>" + F.esc(c.state) + (c.note ? " <span class='src'>" + F.esc(c.note) + "</span>" : "") + "</td></tr>";
        }).join("") + "</tbody></table></div>" +
        "<div class='prov'>Overall: <b>" + F.esc(sc.overall || "?") + "</b> (" + F.esc(sc.total) + "/" + F.esc(sc.maximum) + ")" +
        " · score methodology: equal-weighted transparent components, descriptive labels only.</div>" +
        "<h3 style='margin-top:12px'>Methodology</h3><div class='src'>" +
        "Phase: " + F.esc(ph.method || "Weinstein stage rules") + "<br>" +
        "VCP: " + F.esc(vcp.method || "Minervini-style contraction screen") + "<br>" +
        "Source: calculated locally from verified backend history (" + F.esc(d.history_source || "?") +
        ") · " + F.esc(d.history_range || "") + " · not provider-reported.</div>" +
        "<h3 style='margin-top:12px'>Market breadth (tracked universe)</h3>" +
        "<div id='tq-breadth'><button class='btn sm' id='tq-bload'>Compute breadth</button> " +
        "<span class='src'>30 histories max · cached 4h server-side · explicit universe only</span></div>" +
        srcLine(r.body);
      el("tq-out").innerHTML = h;
      el("tq-bload").onclick = function () {
        if (!el("tq-breadth")) return;
        el("tq-breadth").innerHTML = skel(3);
        API.get("breadth").then(function (br) {
          if (!el("tq-breadth")) return;
          var bd = br.body && br.body.data;
          if (!bd) {
            el("tq-breadth").innerHTML = unavail((br.body && br.body.message) || "Breadth unavailable.") + srcLine(br.body);
            return;
          }
          el("tq-breadth").innerHTML = "<div class='kpis'>" +
            kpi("Phase 2", bd.phase2_pct + "%", "of scored") +
            kpi("Phase 4", bd.phase4_pct + "%", "of scored") +
            kpi("Advancers", bd.advancers, "last bar") +
            kpi("Decliners", bd.decliners, "last bar") +
            kpi("Coverage", bd.coverage_pct + "%", bd.coverage_note) +
            kpi("Scored", bd.scored + "/" + bd.universe_size, "universe: tracked-symbols") + "</div>" +
            ((bd.missing_symbols || []).length ? "<div class='prov'>Missing: <b>" + F.esc(bd.missing_symbols.join(", ")) + "</b></div>" : "") +
            srcLine(br.body);
        });
      };
    });
  }
  function loadTvWidget(sym) {
    var host = el("ch-tvw");
    if (!host) return;
    host.innerHTML = "<div class='skel'></div>";
    function render() {
      if (!el("ch-tvw")) return;
      try {
        new window.TradingView.widget({
          container_id: "ch-tvw",
          symbol: tvSymbol(sym),
          interval: "D",
          theme: (document.body && document.body.dataset.theme === "light") ? "light" : "dark",
          style: "1",
          locale: "en",
          hide_side_toolbar: false,
          allow_symbol_change: true,
          autosize: true,
        });
      } catch (e) {
        host.innerHTML = unavail("TradingView widget failed to load (" + e.message + "). Terminal chart above remains available.");
      }
    }
    if (window.TradingView && window.TradingView.widget) { render(); return; }
    var s = document.createElement("script");
    s.src = "https://s3.tradingview.com/tv.js";
    s.onload = render;
    s.onerror = function () {
      if (el("ch-tvw")) host.innerHTML = unavail("TradingView script unreachable (offline?). Terminal chart above remains available.");
    };
    document.head.appendChild(s);
  }
  var RSECTS = ["thesis", "business", "industry", "financials", "growth", "margins", "capital", "management", "governance", "valuation", "catalysts", "risks", "technical", "observations", "assumptions"];
  function tResearch(sym, b) {
    b.innerHTML = "<div class='grid g2'><div class='card'><h3>New note · " + F.esc(sym) + "</h3>" +
      "<div class='row'><label class='f'>Section<select id='r-s' class='in'>" + RSECTS.map(function (s) { return "<option>" + s + "</option>"; }).join("") +
      "</select></label><input id='r-t' class='in' aria-label='Note title' placeholder='Title' style='flex:1'></div>" +
      "<div style='margin-top:8px'><textarea id='r-b' class='in' aria-label='Note body' placeholder='Observation / thesis / catalyst / risk… (your own words — stored locally)'></textarea></div>" +
      "<div style='margin-top:8px'><button class='btn primary' id='r-save'>Save note</button></div></div>" +
      "<div class='card'><h3>Saved notes</h3><div id='r-list'>" + skel(3) + "</div></div></div>";
    function load() {
      API.get("research", { symbol: sym }).then(function (r) {
        if (!el("r-list")) return;
        var notes = (r.body && r.body.notes) || [];
        el("r-list").innerHTML = notes.length ? notes.map(function (n) {
          return "<div class='news-item'><b>" + F.esc(n.title || "(untitled)") + "</b> <span class='sect-tag'>" + F.esc(n.section) + "</span>" +
            "<div style='white-space:pre-wrap;margin:4px 0'>" + F.esc(n.body) + "</div>" +
            "<div class='meta'>#" + n.id + " · updated " + new Date(n.updated_at * 1000).toISOString().slice(0, 16) +
            " <button class='btn sm danger' data-del='" + n.id + "'>delete</button></div></div>";
        }).join("") : unavail("No notes for " + sym + " yet.");
        Array.prototype.forEach.call(document.querySelectorAll("[data-del]"), function (x) {
          x.onclick = function () { API.del("research", { id: x.getAttribute("data-del") }).then(load); };
        });
      });
    }
    el("r-save").onclick = function () {
      API.post("research", { symbol: sym, section: el("r-s").value, title: el("r-t").value, body: el("r-b").value }).then(function (r) {
        if (!r.body.ok) { toast("Save failed: " + (r.body.error || r.http)); return; }
        el("r-t").value = ""; el("r-b").value = ""; toast("Note saved."); load();
      });
    };
    load();
  }

  /* ---------- watchlist ---------- */
  function addWatch(symbol, name) {
    API.post("watchlist", { symbol: symbol, name: name || "" }).then(function (r) {
      toast(r.body.ok ? symbol + " added to watchlist." : ("Failed: " + (r.body.error || r.http)));
      if ((location.hash || "").indexOf("watchlist") >= 0) pWatchlist();
    });
  }
  var WL_SORT = "name";
  function pWatchlist() {
    view().innerHTML = "<h1 class='h-page'>Watchlist</h1>" +
      "<div class='sub'>Persisted server-side (SQLite) · quotes via fallback chain · auto-refresh 30s.</div>" +
      "<div class='card sect'><div class='row'><input id='w-s' class='in' aria-label='Add symbol' placeholder='Add symbol e.g. TCS.NS' style='flex:1;min-width:200px'>" +
      "<button class='btn primary' id='w-add'>Add</button>" +
      "<input id='w-f' class='in' aria-label='Filter watchlist' placeholder='Filter…' style='width:130px'>" +
      "<label class='f'>Sort<select id='w-sort' class='in'><option value='name'>Name</option><option value='chg'>Change %</option><option value='price'>Price</option></select></label>" +
      "<button class='btn sm' id='w-fund' title='Fetch P/E + market cap per row (Alpha Vantage quota)'>Load P/E · MCap</button>" +
      "</div><div id='w-t' style='margin-top:10px'>" + skel(5) + "</div></div>";
    el("w-add").onclick = function () { var s = el("w-s").value.trim(); if (s) addWatch(s.toUpperCase()); };
    el("w-f").oninput = load;
    el("w-sort").onchange = function () { WL_SORT = el("w-sort").value; load(); };
    el("w-fund").onclick = function () {
      API.get("watchlist").then(function (r) {
        var items = (r.body && r.body.items) || [];
        var done = 0;
        items.forEach(function (i) {
          API.get("ratios", { symbol: i.symbol }).then(function (rr) {
            var d = (rr.body && rr.body.data) || {};
            var cell = el("w-fund-" + i.symbol.replace(/[^A-Z0-9]/g, ""));
            if (cell) cell.innerHTML = F.esc(d.PERatio && d.PERatio !== "None" ? "P/E " + d.PERatio : "—") +
              "<br><span class='src'>" + F.esc(d.MarketCapitalization ? F.fmtIN(Number(d.MarketCapitalization), (i.quote && i.quote.currency) || "") : "") + "</span>";
            if (++done === items.length) toast("Fundamentals loaded where available.");
          });
        });
      });
    };
    function load() {
      if (!el("w-t")) return;
      API.get("watchlist").then(function (r) {
        if (!el("w-t")) return;
        var items = (r.body && r.body.items) || [];
        var f = (el("w-f") && el("w-f").value || "").toUpperCase();
        if (f) items = items.filter(function (i) { return (i.symbol + " " + (i.name || "")).toUpperCase().indexOf(f) >= 0; });
        items.sort(function (a, b) {
          if (WL_SORT === "chg") return ((b.quote && b.quote.change_pct) || -1e18) - ((a.quote && a.quote.change_pct) || -1e18);
          if (WL_SORT === "price") return ((b.quote && b.quote.price) || 0) - ((a.quote && a.quote.price) || 0);
          return String(a.name || a.symbol).localeCompare(String(b.name || b.symbol));
        });
        el("w-t").innerHTML = items.length ? '<div class="twrap"><table class="t"><thead><tr><th scope="col">Security</th><th scope="col" class="num">Price</th><th scope="col" class="num">Change</th><th scope="col" class="num">Volume</th><th scope="col">Fund.</th><th scope="col"><span class="hidden">A</span></th></tr></thead><tbody>' +
          items.map(function (i) {
            var q = i.quote || {};
            return "<tr><td class='txt'><a href='#/company/" + F.esc(i.symbol) + "'>" +
              secCell(i.symbol, i.name || q.name, q.exchange) + "</a></td><td class='num'><b>" + F.fmtNum(q.price) + " " + F.esc(q.currency || "") +
              "</b></td><td class='num " + F.dirClass(q.change_pct) + "'>" + F.fmtPct(q.change_pct) +
              "</td><td class='num'>" + F.fmtInt(q.volume) + "</td><td class='txt' id='w-fund-" + F.esc(i.symbol.replace(/[^A-Z0-9]/g, "")) + "'><span class='src'>—</span></td>" +
              "<td class='num'><button class='btn sm danger' data-rm='" + F.esc(i.symbol) + "'>remove</button></td></tr>";
          }).join("") + "</tbody></table></div>" : unavail("Watchlist is empty. Add symbols to track them.");
        Array.prototype.forEach.call(document.querySelectorAll("[data-rm]"), function (x) {
          x.onclick = function () { API.del("watchlist", { symbol: x.getAttribute("data-rm") }).then(load); };
        });
      });
    }
    every(30000, load);
  }

  /* ---------- portfolio ---------- */
  function pPortfolio() {
    view().innerHTML = "<h1 class='h-page'>Portfolio</h1>" +
      "<div class='sub'>Manual holdings ledger (no brokerage integration claimed). Prices are MARKET DATA (delayed); totals and P&L are CALCULATED.</div>" +
      "<div class='card sect'><h3>Add / update holding</h3><div class='row'>" +
      "<label class='f'>Symbol<input id='p-s' class='in' style='width:130px'></label>" +
      "<label class='f'>Qty<input id='p-q' class='in' style='width:90px'></label>" +
      "<label class='f'>Avg price<input id='p-p' class='in' style='width:110px'></label>" +
      "<button class='btn primary' id='p-add'>Save</button></div></div>" +
      "<div id='p-out' style='margin-top:12px'><div class='card'>" + skel(5) + "</div></div>";
    el("p-add").onclick = function () {
      API.post("portfolio", { symbol: el("p-s").value, quantity: Number(el("p-q").value), avg_price: Number(el("p-p").value) }).then(function (r) {
        toast(r.body.ok ? "Holding saved." : ("Failed: " + (r.body.error || r.http))); load();
      });
    };
    function load() {
      if (!el("p-out")) return;
      API.get("portfolio").then(function (r) {
        if (!el("p-out")) return;
        var b = r.body || {}, pos = b.positions || [];
        var h = "<div class='kpis sect'>" +
          kpi("Invested", F.fmtMoney(b.invested_value), "your input") +
          kpi("Current value", (b.current_value === null || b.current_value === undefined) ? "—" : F.fmtMoney(b.current_value), "market data · delayed") +
          kpi("Unrealised P&L", (b.unrealized_pnl === null || b.unrealized_pnl === undefined) ? "—" : F.fmtMoney(b.unrealized_pnl), "calculated") +
          kpi("P&L %", F.fmtPct(b.pnl_pct), "calculated") + "</div>";
        if (pos.length) {
          var palette = ["#1a56c4", "#18794e", "#9a6b12", "#6d4fc2", "#687182", "#c03535", "#0e7490", "#b45309"];
          h += "<div class='card sect'><h3>Allocation (current value)</h3><div class='alloc' role='img' aria-label='Portfolio allocation'>" +
            pos.map(function (p, ix) {
              return "<span style='width:" + (p.allocation_pct || 0).toFixed(1) + "%;background:" + palette[ix % palette.length] + "'></span>";
            }).join("") + "</div><div class='alloc-legend'>" + pos.map(function (p, ix) {
              return "<span><i style='background:" + palette[ix % palette.length] + "'></i>" + F.esc(p.symbol) + " " + F.fmtPct(p.allocation_pct) + "</span>";
            }).join("") + "</div></div>";
          h += "<div class='card sect'><h3>Holdings (" + pos.length + ")</h3>" +
            '<div class="twrap"><table class="t"><thead><tr><th scope="col">Security</th><th scope="col" class="num">Qty</th><th scope="col" class="num">Avg</th><th scope="col" class="num">LTP</th><th scope="col" class="num">Invested</th><th scope="col" class="num">Current</th><th scope="col" class="num">P&amp;L</th><th scope="col" class="num">Alloc</th><th scope="col"><span class="hidden">A</span></th></tr></thead><tbody>' +
            pos.map(function (p) {
              return "<tr><td class='txt'><a href='#/company/" + F.esc(p.symbol) + "'>" + secCell(p.symbol, p.name, null) + "</a></td><td class='num'>" + F.fmtNum(p.quantity, 0) +
                "</td><td class='num'>" + F.fmtNum(p.avg_price) + "</td><td class='num'>" + F.fmtNum(p.current_price) +
                "</td><td class='num'>" + F.fmtMoney(p.invested_value) + "</td><td class='num'>" + (p.current_value === null ? "—" : F.fmtMoney(p.current_value)) +
                "</td><td class='num " + F.dirClass(p.unrealized_pnl) + "'>" + (p.unrealized_pnl === null ? "—" : F.fmtMoney(p.unrealized_pnl) + " (" + F.fmtPct(p.pnl_pct) + ")") +
                "</td><td class='num'>" + F.fmtPct(p.allocation_pct) + "</td>" +
                "<td class='num'><button class='btn sm danger' data-prm='" + F.esc(p.symbol) + "'>x</button></td></tr>";
            }).join("") + "</tbody></table></div></div>";
        } else {
          h += "<div class='card'>" + unavail("No holdings yet.") + "</div>";
        }
        el("p-out").innerHTML = h;
        Array.prototype.forEach.call(document.querySelectorAll("[data-prm]"), function (x) {
          x.onclick = function () { API.del("portfolio", { symbol: x.getAttribute("data-prm") }).then(load); };
        });
      });
    }
    load();
  }

  /* ---------- news: dense terminal table ---------- */
  function pNews() {
    view().innerHTML = "<h1 class='h-page'>News</h1>" +
      "<div class='sub'>Research feed — headlines via Yahoo Finance RSS (no key). Never synthesised; explicit state on failure. Auto-refresh 60s.</div>" +
      "<div class='card sect'><div class='row'><input id='n-s' class='in' aria-label='Symbol filter' placeholder='Company e.g. AAPL (blank = market)'>" +
      "<input id='n-t' class='in' aria-label='Topic filter' placeholder='Topic keyword (optional)'>" +
      "<input id='n-d' class='in' aria-label='Date filter YYYY-MM-DD' placeholder='Date YYYY-MM-DD' style='width:140px'>" +
      "<button class='btn primary' id='n-go'>Load</button></div>" +
      "<div id='n-out' style='margin-top:10px'>" + skel(5) + "</div></div>";
    function go() {
      if (!el("n-out")) return;
      el("n-out").innerHTML = skel(5);
      API.get("news", { symbol: el("n-s").value.trim(), topic: el("n-t").value.trim(), limit: 25 }).then(function (r) {
        if (!el("n-out")) return;
        var d = r.body && r.body.data;
        var items = (d && d.items) || [];
        var df = el("n-d").value.trim();
        if (df) items = items.filter(function (n) { return String(n.published_at || "").indexOf(df) === 0 || String(n.published_at || "").indexOf(df) >= 0; });
        el("n-out").innerHTML = (items.length ? '<div class="twrap"><table class="t"><thead><tr><th scope="col">Time</th>' +
          "<th scope='col'>Company</th><th scope='col'>Headline</th><th scope='col'>Source</th></tr></thead><tbody>" +
          items.map(function (n) {
            return "<tr><td class='txt' style='white-space:nowrap'>" + F.esc(n.published_at || "—") + "</td>" +
              "<td class='txt'>" + F.esc(n.symbol || el("n-s").value.trim().toUpperCase() || "—") + "</td>" +
              "<td class='txt' style='white-space:normal;min-width:280px'><a href='" + F.esc(n.url) + "' target='_blank' rel='noopener'>" +
              F.esc(n.title) + "</a>" + (n.sentiment ? " <span class='sect-tag'>" + F.esc(n.sentiment) + "</span>" : "") + "</td>" +
              "<td class='txt'>" + F.esc(n.source || "") + "</td></tr>";
          }).join("") + "</tbody></table></div>"
          : unavail((r.body && r.body.message) || "News unavailable.")) + srcLine(r.body);
      });
    }
    el("n-go").onclick = go;
    every(60000, go);
  }

  /* ---------- research home ---------- */
  function pResearch() {
    view().innerHTML = "<h1 class='h-page'>Research</h1>" +
      "<div class='sub'>Saved thesis notes, observations, catalysts and risks. Open a company → Research tab to add.</div>" +
      "<div class='card' id='r-all'>" + skel(5) + "</div>";
    API.get("research", {}).then(function (r) {
      if (!el("r-all")) return;
      var notes = (r.body && r.body.notes) || [];
      el("r-all").innerHTML = notes.length ? notes.map(function (n) {
        return "<div class='news-item'><a href='#/company/" + F.esc(n.symbol) + "/Research'>" + F.esc(n.symbol) + "</a> " +
          "<span class='sect-tag'>" + F.esc(n.section) + "</span> <b>" + F.esc(n.title || "(untitled)") + "</b>" +
          "<div style='white-space:pre-wrap;margin:4px 0'>" + F.esc((n.body || "").slice(0, 300)) + "</div></div>";
      }).join("") : unavail("No research notes yet.");
    });
  }

  /* ---------- compare ---------- */
  function pCompare() {
    view().innerHTML = "<h1 class='h-page'>Compare</h1><div class='sub'>Factual side-by-side. No automatic ranking — you judge.</div>" +
      "<div class='card sect'><div class='row'><input id='k-s' class='in' aria-label='Symbols to compare' style='flex:1' value='RELIANCE.NS,TCS.NS,INFY.NS' placeholder='Comma-separated symbols, max 5'>" +
      "<button class='btn primary' id='k-go'>Compare</button></div></div><div id='k-out' style='margin-top:12px'></div>";
    function go() {
      var syms = el("k-s").value.split(",").map(function (s) { return s.trim().toUpperCase(); }).filter(Boolean).slice(0, 5);
      if (syms.length < 2) { toast("Enter at least 2 symbols."); return; }
      if (!syms.length) return;
      el("k-out").innerHTML = "<div class='card'>" + skel(6) + "</div>";
      Promise.all(syms.map(function (s) {
        return Promise.all([
          API.get("company", { symbol: s }), API.get("quote", { symbol: s }),
          API.get("ratios", { symbol: s }),
          API.get("fundamentals", { symbol: s, statement: "income", period: "annual" }),
        ]).then(function (x) {
          return { symbol: s, prof: x[0].body && x[0].body.data, quote: x[1].body && x[1].body.data,
            ratios: x[2].body && x[2].body.data, fin: x[3].body && x[3].body.data };
        });
      })).then(function (cols) {
        if (!el("k-out")) return;
        function num(rep, keys) {
          if (!rep) return null;
          for (var i = 0; i < keys.length; i++) {
            var v = rep[keys[i]];
            if (v !== undefined && v !== null && v !== "None" && v !== "-") { var n = Number(v); if (!isNaN(n)) return n; }
          }
          return null;
        }
        function finRows(c) {
          var reps = (c.fin && c.fin.reports) || [];
          var r0 = reps[0] || null, r1 = reps[1] || null;
          var rev0 = num(r0, ["totalRevenue", "revenue", "revenues", "sales"]);
          var rev1 = num(r1, ["totalRevenue", "revenue", "revenues", "sales"]);
          var ni0 = num(r0, ["netIncome", "net_income", "netEarnings"]);
          var per = r0 ? (r0.fiscalDateEnding || r0.date || "?") : null;
          return { rev0: rev0, rev1: rev1, ni0: ni0, per: per,
            growth: (rev0 !== null && rev1) ? (rev0 - rev1) / Math.abs(rev1) * 100 : null,
            margin: (rev0 && ni0) ? ni0 / rev0 * 100 : null };
        }
        cols.forEach(function (c) { c.fx = finRows(c); });
        function qrow(label, fn) {
          return "<tr><td class='txt freeze'>" + label + "</td>" + cols.map(function (c) { return "<td class='num'>" + fn(c) + "</td>"; }).join("") + "</tr>";
        }
        function rrow(label, key) {
          return "<tr><td class='txt freeze'>" + label + "</td>" + cols.map(function (c) {
            var v = c.ratios && c.ratios[key];
            return "<td class='num'>" + (v === undefined || v === null || v === "None" ? "—" : F.esc(String(v))) + "</td>";
          }).join("") + "</tr>";
        }
        var h = "<div class='card flush'><div class='twrap'><table class='t'><thead><tr><th scope='col' class='cmp-head freeze'>Metric</th>" +
          cols.map(function (c) {
            return "<th scope='col' class='num'><a href='#/company/" + F.esc(c.symbol) + "'>" +
              F.logo(c.symbol, (c.prof && c.prof.name) || (c.quote && c.quote.name), 26) + "<br>" +
              secCell(c.symbol, (c.prof && c.prof.name) || (c.quote && c.quote.name), null) + "</a></th>";
          }).join("") + "</tr></thead><tbody>";
        h += qrow("Price", function (c) { return c.quote ? "<b>" + F.fmtNum(c.quote.price) + "</b> " + F.esc(c.quote.currency || "") : "—"; });
        h += qrow("Δ% vs prev close", function (c) { return c.quote ? "<span class='" + F.dirClass(c.quote.change_pct) + "'>" + F.fmtPct(c.quote.change_pct) + "</span>" : "—"; });
        h += qrow("Revenue (" + F.esc((cols[0].fx && cols[0].fx.per) || "?") + ")", function (c) { return c.fx.rev0 === null ? "—" : F.fmtMoney(c.fx.rev0); });
        h += qrow("Revenue growth YoY", function (c) { return c.fx.growth === null ? "—" : "<span class='" + F.dirClass(c.fx.growth) + "'>" + F.fmtPct(c.fx.growth) + "</span>"; });
        h += qrow("Net profit", function (c) { return c.fx.ni0 === null ? "—" : F.fmtMoney(c.fx.ni0); });
        h += qrow("Net margin", function (c) { return c.fx.margin === null ? "—" : F.fmtPct(c.fx.margin); });
        h += rrow("Market cap", "MarketCapitalization") + rrow("P/E", "PERatio") + rrow("P/B", "PriceToBookRatio") +
          rrow("EPS", "EPS") + rrow("ROE", "ROE") + rrow("Dividend yield", "DividendYield");
        h += qrow("Debt/Equity", function () { return "—"; });
        el("k-out").innerHTML = h + "</tbody></table></div><div class='prov' style='padding:0 14px 12px'>Quotes: delayed chain · " +
          "financials: reported statements where configured · ratios: " +
          (cols[0].ratios ? "reported provider data" : "unavailable — no configured provider supplies ratios for this symbol") +
          " · Debt/Equity: unavailable — no leverage feed configured</div></div>";
      });
    }
    el("k-go").onclick = go; go();
  }

  /* ---------- ipos / earnings / macro / settings ---------- */
  function pIPOs() {
    view().innerHTML = "<h1 class='h-page'>IPOs</h1><div class='sub'>Free IPO calendar feed (Alpha Vantage) where entitled. Never synthesised.</div>" +
      "<div class='card' id='ipo-out'>" + skel(5) + "</div>";
    API.get("ipo").then(function (r) {
      if (!el("ipo-out")) return;
      var d = r.body && r.body.data;
      if (!d || !d.rows || !d.rows.length) {
        el("ipo-out").innerHTML = "<h3>IPO calendar " + F.statusPill(r.body.status) + "</h3>" +
          unavail((r.body && r.body.message) || "No IPO feed configured.", "Alpha Vantage", "Free IPO_CALENDAR feed returned no rows") + srcLine(r.body);
        return;
      }
      var cols = d.columns || Object.keys(d.rows[0]);
      el("ipo-out").innerHTML = "<h3>IPO calendar (" + d.rows.length + ") " + F.statusPill(r.body.status) + "</h3>" +
        '<div class="twrap"><table class="t"><thead><tr>' + cols.map(function (c) { return "<th scope='col'>" + F.esc(c) + "</th>"; }).join("") + "</tr></thead><tbody>" +
        d.rows.map(function (row) {
          var sym = row.symbol || row.ticker || "";
          var nm = row.name || row.company || sym;
          return "<tr>" + cols.map(function (c, ix) {
            var v = row[c] || "—";
            if (ix === 0 && sym) return "<td class='txt'><b>" + F.esc(nm) + "</b><br><span class='src'>" + F.esc(sym) + "</span></td>";
            return "<td class='txt'>" + F.esc(v) + "</td>";
          }).join("") + "</tr>";
        }).join("") + "</tbody></table></div>" + srcLine(r.body);
    });
  }
  function pEarnings() {
    view().innerHTML = "<h1 class='h-page'>Earnings</h1>" +
      "<div class='sub'>Reported earnings where a key is configured. Estimates appear only when the feed reports them.</div>" +
      "<div class='card sect'><h3>Earnings calendar</h3><div id='e-cal'>" + skel(4) + "</div></div>" +
      "<div class='card sect'><h3>Company earnings</h3><div class='row'><input id='e-s' class='in' aria-label='Symbol' placeholder='Symbol e.g. RELIANCE.NS'>" +
      "<button class='btn primary' id='e-go'>Open company earnings</button>" +
      "<button class='btn' id='e-d'>Dividends &amp; splits</button></div>" +
      "<div class='prov' style='margin-top:6px'>For dividends/splits use Corporate Actions (exchange-reported events).</div></div>";
    API.get("earnings-calendar").then(function (r) {
      if (!el("e-cal")) return;
      var rows = r.body && r.body.data && r.body.data.rows;
      if (!rows || !rows.length) {
        el("e-cal").innerHTML = unavail((r.body && r.body.message) || "Earnings calendar unavailable.", "Alpha Vantage", "EARNINGS_CALENDAR returned no rows") + srcLine(r.body);
        return;
      }
      var cols = ["symbol", "name", "reportDate", "fiscalDateEnding", "estimate", "currency"];
      el("e-cal").innerHTML = '<div class="twrap"><table class="t"><thead><tr><th scope="col">Company</th><th scope="col">Report date</th><th scope="col">Fiscal end</th><th scope="col" class="num">EPS est</th><th scope="col">Status</th></tr></thead><tbody>' +
        rows.slice(0, 30).map(function (x) {
          return "<tr><td class='txt'><b>" + F.esc(x.name || x.symbol || "—") + "</b><br><span class='src'>" + F.esc(x.symbol || "") + "</span></td>" +
            "<td class='txt'>" + F.esc(x.reportDate || "—") + "</td><td class='txt'>" + F.esc(x.fiscalDateEnding || "—") + "</td>" +
            "<td class='num'>" + F.esc(x.estimate !== undefined ? x.estimate : "—") + "</td>" +
            "<td>" + F.statusPill("END-OF-DAY") + "</td></tr>";
        }).join("") + "</tbody></table></div>" + srcLine(r.body);
    });
    el("e-go").onclick = function () {
      var s = el("e-s").value.trim().toUpperCase();
      if (s) location.hash = "#/company/" + encodeURIComponent(s) + "/Earnings";
    };
    el("e-d").onclick = function () {
      var s = el("e-s").value.trim().toUpperCase() || "RELIANCE.NS";
      location.hash = "#/company/" + encodeURIComponent(s) + "/Actions";
    };
  }
  function pMacro() {
    view().innerHTML = "<h1 class='h-page'>Macro</h1>" +
      "<div class='sub'>Index snapshot from the fallback chain (delayed) + economic indicators via Alpha Vantage (free) where a key is configured. Nothing fabricated.</div>" +
      "<div id='mc-out' class='card'>" + skel(5) + "</div>" +
      "<div class='card sect' id='mc-econ' style='margin-top:12px'>" + skel(4) + "</div>";
    API.get("market-overview").then(function (r) {
      if (!el("mc-out")) return;
      var items = ((r.body && r.body.items) || []).filter(function (i) { return isIndex(i.symbol); });
      el("mc-out").innerHTML = items.length ? "<h3>Indices</h3>" + '<div class="twrap"><table class="t"><thead><tr><th scope="col">Index</th><th scope="col">Name</th><th scope="col" class="num">Level</th><th scope="col" class="num">Δ%</th></tr></thead><tbody>' +
        items.map(function (i) {
          var q = i.quote || {};
          return "<tr><td class='txt'><b>" + F.esc(q.name || i.symbol) + "</b><br><span class='src'>" + F.esc(i.symbol) + "</span></td>" +
            "<td class='txt'>" + F.esc(q.name || "—") + "</td><td class='num'><b>" + F.fmtNum(q.price) +
            "</b></td><td class='num " + F.dirClass(q.change_pct) + "'>" + F.fmtPct(q.change_pct) + "</td></tr>";
        }).join("") + "</tbody></table></div><div class='prov'>fallback chain · delayed</div>" : unavail("Index data unavailable.");
    });
    var INDS = [["GDP", "Output"], ["INFLATION", "Prices"], ["UNEMPLOYMENT", "Labor"], ["FEDERAL_FUNDS_RATE", "Rates"]];
    Promise.all(INDS.map(function (p) { return API.get("macro", { indicator: p[0] }); })).then(function (rs) {
      if (!el("mc-econ")) return;
      el("mc-econ").innerHTML = "<h3>Economic indicators</h3><div class='kpis'>" + rs.map(function (r, ix) {
        var d = r.body && r.body.data;
        var pts = (d && d.points) || [];
        var last = pts[0] || {};
        return kpi(INDS[ix][0].replace(/_/g, " "), pts.length ? F.esc(last.value || "—") : "—",
          pts.length ? (last.date || "") + " · " + ((d && d.unit) || "") + " · Alpha Vantage" : ((r.body && r.body.message) || "Unavailable"));
      }).join("") + "</div>";
    });
  }
  function pSettings() {
    view().innerHTML = "<h1 class='h-page'>Settings</h1>" +
      "<div class='sub'>Provider wiring &amp; data transparency — free-automatic mode, no paid subscription required</div>" +
      "<div class='card sect'><h3>Data providers</h3><div id='s-prov'>" + skel(5) + "</div></div>" +
      "<div class='card sect'><h3>Data sources — internal vs external</h3>" +
      "<div class='grid g2'><div><div class='lbl' style='margin-bottom:4px'>Internal data</div>" +
      "<div class='src'>Yahoo Finance · Alpha Vantage · Twelve Data · Indian Stock Market API · Stooq (history). " +
      "Fetched server-side, cached, reconciled, attributed per field.</div></div>" +
      "<div><div class='lbl' style='margin-bottom:4px'>External research</div>" +
      "<div class='src'>Screener · Trendlyne · Tickertape · NSE · BSE · Company IR. " +
      "Links open the original source. The terminal does not scrape or mirror proprietary research databases.</div></div>" +
      "</div></div>" +
      "<div class='grid g2' style='margin-top:12px'><div class='card'><h3>Refresh policy</h3><div class='src'>" +
      "Browser polls quotes every 10s (company) / 30s (watchlist) / 60s (dashboard, news). " +
      "The backend serves cache unless an upstream refresh is allowed: quotes 30s, intraday history 15m, daily history 4h, " +
      "news 10m, fundamentals 24h, Alpha Vantage quotes 6h (25 req/day free tier). " +
      "Twelve Data free budget: 8 credits/min, 800/day. Free APIs are never hammered.</div></div>" +
      "<div class='card'><h3>Environment</h3><div class='src'>ALPHA_VANTAGE_API_KEY / FUNDAMENTALS_API_KEY — optional, server-side only, enables statements + ratios + last-resort quotes.<br><br>" +
      "TWELVE_DATA_API_KEY — optional, server-side only, enables the middle fallback leg.<br><br>" +
      "INDIAN_STOCK_MARKET_API_KEY — optional, server-side only. With a key: full NSE/BSE coverage (statements, ownership, forecasts, news, actions, history). Without: free quote + market fundamentals.<br><br>" +
      "TERMINAL_DB — sqlite path (default ./terminal-data/terminal.db).<br><br>No key is ever shipped to the browser. Validate input; external content is escaped before render.</div>" +
      "<h3 style='margin-top:12px'>Legend</h3><div class='row'>" + F.statusPill("REAL-TIME") + F.statusPill("CALCULATED") + F.statusPill("UNAVAILABLE") + F.statusPill("STALE") + "<a class='src' href='#/status'>Feed timeliness lives on the Data status page →</a></div></div></div>";
    API.get("providers").then(function (r) {
      if (!el("s-prov")) return;
      var b = r.body || {}, list = b.providers || [];
      var badge = {
        connected: ["pill-live", "✓ Connected"],
        key_missing: ["pill-na", "○ API KEY NOT CONFIGURED"],
        feed_missing: ["pill-na", "○ AUTHORIZED REAL-TIME FEED NOT CONFIGURED"],
        widget_available: ["pill-live", "✓ CHART WIDGET AVAILABLE"],
        cooling: ["pill-delayed", "○ COOLING (upstream errors)"],
        unreachable: ["pill-na", "○ UNREACHABLE"],
      };
      el("s-prov").innerHTML = '<div class="twrap"><table class="t"><thead><tr><th scope="col">Provider</th><th scope="col">Status</th><th scope="col">Capabilities</th><th scope="col">Detail</th></tr></thead><tbody>' +
        list.map(function (p) {
          var m = badge[p.state] || ["pill-na", F.esc(p.state)];
          var caps = p.capabilities ? Object.keys(p.capabilities).filter(function (k) { return p.capabilities[k]; }).join(", ") : "—";
          var extra = "";
          if (p.id === "twelvedata" && p.budget) {
            extra = "<div class='src'>budget: " + p.budget.per_minute_used + "/" +
              p.budget.per_minute_limit + " per min · " + p.budget.daily_used + "/" +
              p.budget.daily_limit + " today</div>";
          }
          if (p.id === "yahoo" && p.health && p.health.last_latency_ms !== null && p.health.last_latency_ms !== undefined) {
            extra = "<div class='src'>last upstream latency: " + p.health.last_latency_ms + " ms</div>";
          }
          return "<tr><td class='txt'><b>" + F.esc(p.label) + "</b></td><td><span class='pill " + m[0] + "'>" + m[1] + "</span></td>" +
            "<td class='txt' style='white-space:normal;max-width:220px'>" + F.esc(caps) + "</td>" +
            "<td class='txt' style='white-space:normal'>" + F.esc(p.detail || "") + extra + "</td></tr>";
        }).join("") + "</tbody></table></div>" +
        "<div class='prov' style='margin-top:8px'>fallback chains — quote: " + F.esc(((b.chain || {}).quote || []).join(" → ")) +
        " · history: " + F.esc(((b.chain || {}).history || []).join(" → ")) +
        " → DATA UNAVAILABLE. Never hide why data is unavailable.</div>";
    });
  }

  /* ---------- FINSIGHT landing: brand + live market strip, zero invented numbers.
     First visit only (app.js routes #/welcome when no fi-seen flag). */
  function pWelcome() {
    var F = window.FT_FMT;
    function esc2(s) { return F.esc(s === null || s === undefined ? "" : String(s)); }
    document.getElementById("view").innerHTML =
      "<div class='fi-landing'><section class='fi-hero' aria-labelledby='fi-h1'>" +
      "<svg class='fi-mark' width='44' height='44' viewBox='0 0 64 64' aria-hidden='true'>" +
      "<rect width='64' height='64' rx='12' fill='#0B1120'/>" +
      "<path d='M20 14h26v7H29v8h15v7H29v14h-9V14z' fill='#10B981'/>" +
      "<rect x='20' y='50' width='26' height='3' fill='#10B981' opacity='0.4'/></svg>" +
      "<h1 id='fi-h1'>FINSIGHT</h1>" +
      "<p class='tag'>Financial intelligence, reconciled</p>" +
      "<p class='lede'>Verified market data, financial analytics and research in one professional " +
      "workspace. Every number traceable to its source; conflicting providers shown side by side, never averaged.</p>" +
      "<div class='fi-cta'><a class='btn primary' href='#/dashboard' id='fi-enter'>Enter Finsight</a>" +
      "<a class='btn' href='#/markets'>Explore terminal</a></div>" +
      "<div class='fi-strip'><div class='lbl' style='margin-bottom:6px'>Live market snapshot</div>" +
      "<div class='pulse' id='fi-pulse'></div></div>" +
      "<div class='fi-foot' id='fi-src'>Loading market snapshot…</div>" +
      "</section></div>";
    try { localStorage.setItem("fi-seen", "1"); } catch (e) { /* ignore */ }
    document.getElementById("fi-enter").focus({ preventScroll: true });
    window.FT_API.get("market-overview").then(function (r) {
      var host = document.getElementById("fi-pulse");
      if (!host) return;
      var items = (((r.body || {}).items) || []).filter(function (i) {
        return i.quote && i.quote.price !== null && i.quote.price !== undefined;
      }).slice(0, 6);
      host.innerHTML = items.map(function (i) {
        var qq = i.quote;
        return "<div class='pcell'><div class='pnm'>" + esc2(qq.name || i.symbol) + "</div>" +
          "<div class='pvl'>" + F.fmtNum(qq.price) + "</div>" +
          "<div class='" + F.dirClass(qq.change_pct) + "' style='font-weight:650'>" + F.fmtPct(qq.change_pct) + "</div></div>";
      }).join("") || "<div class='empty'><b>Snapshot unavailable</b><p>Market feed unreachable.</p></div>";
      var src = document.getElementById("fi-src");
      if (src) src.textContent = "Delayed market snapshot · " + items.length + " instruments · source: exchange-delayed feed";
    }).catch(function () {
      var host = document.getElementById("fi-pulse");
      if (host) host.innerHTML = "";
    });
  }

  /* ---------- Data status: the one place feed freshness is disclosed.
     Every provider row states whether its data is delayed or live, with
     last-ok timestamps and latency. Numbers elsewhere stay clean. */
  function pStatus() {
    var F = window.FT_FMT;
    function esc2(s) { return F.esc(s === null || s === undefined ? "" : String(s)); }
    document.getElementById("view").innerHTML =
      "<h1 class='h-page'>Data status</h1>" +
      "<div class='sub'>Is it delayed or not — answered here, per provider. Retail market feeds " +
      "(Yahoo, Upstox analytics, Twelve Data free tier) are exchange-delayed by construction; " +
      "only an authorized real-time feed would change that, and none is configured.</div>" +
      "<div class='card flush sect'><div class='twrap'><table class='t' id='st-t'>" +
      "<thead><tr><th scope='col'>Provider</th><th scope='col'>State</th>" +
      "<th scope='col'>Freshness</th><th scope='col' class='num'>Latency</th>" +
      "<th scope='col' class='txt'>Detail</th></tr></thead>" +
      "<tbody><tr><td colspan='5'>Loading provider health…</div></td></tr></tbody></table></div></div>" +
      "<div class='prov'>Source: live /api/providers health · timestamps are server time</div>";
    window.FT_API.get("providers").then(function (r) {
      var host = document.querySelector("#st-t tbody");
      if (!host) return;
      var list = ((r.body || {}).providers) || [];
      host.innerHTML = list.map(function (p) {
        var h = p.health || {};
        var caps = p.capabilities || {};
        var movesData = caps.quote || caps.history;
        var fresh = (p.key_required && !p.key_configured) ? "NOT CONFIGURED"
          : !movesData ? "—"
          : "DELAYED"; // no authorized real-time feed is configured anywhere
        var pill = fresh === "DELAYED" ? "<span class='pill pill-na'>DELAYED</span>"
          : "<span class='pill pill-na'>" + esc2(fresh) + "</span>";
        var lat = (h.last_latency_ms === null || h.last_latency_ms === undefined)
          ? "—" : Math.round(h.last_latency_ms) + " ms";
        var state = esc2(p.state || "?");
        return "<tr><td class='txt'><b>" + esc2(p.label || p.id) + "</b></td>" +
          "<td class='txt'>" + state + "</td><td>" + pill + "</td>" +
          "<td class='num'>" + lat + "</td>" +
          "<td class='txt' style='white-space:normal;max-width:340px'>" + esc2(p.detail || "") + "</td></tr>";
      }).join("");
    }).catch(function () {
      var host = document.querySelector("#st-t tbody");
      if (host) host.innerHTML = "<tr><td colspan='5'>Provider health unreachable.</td></tr>";
    });
  }

  window.FT_PAGES = {
    init, clearTimers, pDashboard, pMarkets, pScreener, pCompanies, pCompany, pWatchlist,
    pPortfolio, pNews, pResearch, pCompare, pIPOs, pEarnings, pMacro, pSettings, pWelcome, pStatus, toast,
  };
})();
