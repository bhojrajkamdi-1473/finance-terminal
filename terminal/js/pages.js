/* Terminal views. Every number carries source/period/currency attribution;
   missing data renders explicit unavailable states — never invented. */
(function () {
  "use strict";
  var API, F;
  function init() { API = window.FT_API; F = window.FT_FMT; }
  function el(id) { return document.getElementById(id); }
  function view() { return el("view"); }
  /* Route-scoped timers: cleared on every navigation (see clearTimers). */
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
  /* Freshness line: last-updated IST clock + source + data status. */
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
    "NIFTY_FIN_SERVICE.NS", "^GSPC", "^IXIC", "^RUT", "^FTSE",
    "^STOXX50E", "^N225", "^HSI"];
  function isIndex(sym) { return INDICES.indexOf(sym) >= 0; }
  function toast(msg) {
    var r = el("toast-root"), d = document.createElement("div");
    d.className = "toast"; d.textContent = msg; r.appendChild(d);
    setTimeout(function () { d.remove(); }, 4200);
  }
  function skel(n) {
    var h = "";
    for (var i = 0; i < (n || 4); i++) h += '<div class="skel"></div>';
    return h;
  }
  function unavail(msg) {
    return '<div class="empty"><b>Data unavailable.</b><br>' + F.esc(msg || "Provider not configured.") + "</div>";
  }
  function errBox(msg) {
    return '<div class="err"><b>Request failed.</b><br>' + F.esc(msg || "") + "</div>";
  }
  function srcLine(env) {
    if (!env) return "";
    return '<div class="src">source: ' + F.esc(env.source || "?") +
      " · status: " + F.esc(env.status || "?") +
      (env.as_of ? " · as of " + F.esc(env.as_of) : " · last updated: unavailable") + "</div>";
  }
  function quoteRow(q, symFallback) {
    if (!q) return '<span class="mut">—</span>';
    var c = F.dirClass(q.change_pct);
    return '<b>' + F.fmtNum(q.price) + '</b> <span class="mut">' + F.esc(q.currency || "") +
      '</span> <span class="' + c + '">' + F.fmtPct(q.change_pct) + "</span>";
  }

  /* ---------- dashboard ---------- */
  function pDashboard() {
    view().innerHTML = "<h1>Dashboard</h1><div class='sub'>Free-automatic mode: Yahoo → Twelve Data → Alpha Vantage → unavailable. Browser refreshes every 60s; the backend serves cache unless a refresh is allowed.</div>" +
      "<div id='d-idx' class='grid g4'>" + skel(4) + "</div>" +
      "<div class='grid g2'><div><h2>Movers (tracked universe)</h2><div id='d-mov' class='card'>" + skel(5) + "</div></div>" +
      "<div><h2>Latest headlines <span class='src'>(auto-refresh 60s)</span></h2><div id='d-news' class='card'>" + skel(5) + "</div></div></div>" +
      "<div id='d-src'></div>";
    function load() {
      if (!el("d-idx")) return;
      API.get("market-overview").then(function (r) {
        if (!el("d-idx")) return;
        var items = (r.body && r.body.items) || [];
        var idx = items.filter(function (i) { return isIndex(i.symbol); });
        var eq = items.filter(function (i) { return !isIndex(i.symbol); });
      el("d-idx").innerHTML = idx.map(function (i) {
        return '<div class="card metric"><h3>' + F.esc(i.symbol) + "</h3><div class='v'>" +
          (i.quote ? F.fmtNum(i.quote.price) + ' <span class="' + F.dirClass(i.quote.change_pct) + '">' + F.fmtPct(i.quote.change_pct) + "</span>" : "—") +
          "</div><div class='l'>" + F.esc((i.quote && i.quote.name) || i.status) + "</div></div>";
      }).join("") || unavail("Index quotes unavailable.");
      var ranked = eq.filter(function (i) { return i.quote && i.quote.change_pct !== null; })
        .sort(function (a, b) { return b.quote.change_pct - a.quote.change_pct; });
      var rows = ranked.map(function (i) {
        return "<tr><td><a href='#/company/" + F.esc(i.symbol) + "'>" + F.esc(i.symbol) + "</a></td><td class='num'>" +
          quoteRow(i.quote) + "</td></tr>";
      }).join("");
      el("d-mov").innerHTML = '<table class="t"><tr><th>Symbol</th><th class="num">Price · Δ%</th></tr>' + rows + "</table>";
      el("d-src").innerHTML = '<div class="src">market-overview · fallback chain (Yahoo → Twelve Data → Alpha Vantage) · quotes cached 30s server-side</div>';
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
  }
  function newsItem(n) {
    return '<div class="news-item"><a href="' + F.esc(n.url) + '" target="_blank" rel="noopener">' +
      F.esc(n.title) + "</a><div class='meta'>" + F.esc(n.source || "") + " · " + F.esc(n.published_at || "") + "</div></div>";
  }

  /* ---------- markets ---------- */
  function pMarkets() {
    view().innerHTML = "<h1>Markets</h1><div class='sub'>Quotes across NSE, BSE, US and global indices via the free-automatic chain (Yahoo → Twelve Data → Alpha Vantage). NSE real-time requires an authorized feed — shown data is delayed.</div>" +
      "<div id='m-t' class='card'>" + skel(8) + "</div>";
    API.get("market-overview").then(function (r) {
      var items = (r.body && r.body.items) || [];
      el("m-t").innerHTML = '<table class="t"><tr><th>Symbol</th><th>Name</th><th class="num">Price</th>' +
        '<th class="num">Δ%</th><th>CCY</th><th>Status</th></tr>' +
        items.map(function (i) {
          var q = i.quote || {};
          return "<tr><td><a href='#/company/" + F.esc(i.symbol) + "'>" + F.esc(i.symbol) + "</a></td><td>" +
            F.esc(q.name || "—") + "</td><td class='num'>" + F.fmtNum(q.price) + "</td><td class='num " +
            F.dirClass(q.change_pct) + "'>" + F.fmtPct(q.change_pct) + "</td><td>" + F.esc(q.currency || "—") +
            "</td><td>" + F.statusPill(i.status) + "</td></tr>";
        }).join("") + "</table><div class='src' style='margin-top:8px'>source: yahoo · delayed · last updated on fetch</div>";
    });
  }

  /* ---------- screener ---------- */
  function pScreener() {
    view().innerHTML = "<h1>Screener</h1><div class='sub'>Real screens over verified data. Quote fields are REPORTED (delayed); RSI/SMA are CALCULATED locally; P/E/ROE are REPORTED (Alpha Vantage, quota-noted). Missing values exclude — never invented.</div>" +
      "<div class='card'><div class='row'>" +
      "<label>Min Δ% <input id='s-min' class='in' style='width:80px' placeholder='e.g. 1'></label>" +
      "<label>Max Δ% <input id='s-max' class='in' style='width:80px' placeholder='e.g. 5'></label>" +
      "<label>Min price <input id='s-minp' class='in' style='width:90px'></label>" +
      "<label>Max price <input id='s-maxp' class='in' style='width:90px'></label>" +
      "<label>Min volume <input id='s-minv' class='in' style='width:110px' placeholder='shares'></label></div><div class='row' style='margin-top:8px'>" +
      "<label>RSI min <input id='s-rsi0' class='in' style='width:70px'></label>" +
      "<label>RSI max <input id='s-rsi1' class='in' style='width:70px'></label>" +
      "<label>Above SMA <select id='s-sma' class='in'><option value=''>—</option><option value='20'>20</option><option value='50'>50</option><option value='200'>200</option></select></label>" +
      "<label>Max P/E <input id='s-pe' class='in' style='width:70px'></label>" +
      "<label>Min ROE <input id='s-roe' class='in' style='width:70px'></label>" +
      "<button class='btn primary' id='s-run'>Run screen</button></div>" +
      "<div class='src' style='margin-top:8px'>P/E + ROE need ALPHA_VANTAGE_API_KEY and consume its 25/day free quota (cached 24h). Technicals compute from cached history.</div></div>" +
      "<div id='s-out' style='margin-top:12px'></div>";
    el("s-run").onclick = run;
    run();
    function run() {
      el("s-out").innerHTML = "<div class='card'>" + skel(5) + "</div>";
      API.get("screener", {
        min_change_pct: el("s-min").value, max_change_pct: el("s-max").value,
        min_price: el("s-minp").value, max_price: el("s-maxp").value,
        min_volume: el("s-minv").value, rsi_min: el("s-rsi0").value,
        rsi_max: el("s-rsi1").value, above_sma: el("s-sma").value,
        max_pe: el("s-pe").value, min_roe: el("s-roe").value,
      }).then(function (r) {
        if (!el("s-out")) return;
        var b = r.body || {}, res = b.results || [];
        var skipped = b.skipped || [];
        var excl = skipped.filter(function (x) { return x.excluded_reason; });
        el("s-out").innerHTML = "<div class='card'><h3>Matches (" + res.length + ") — latest cached quotes " + F.statusPill("delayed") + "</h3>" +
          "<div class='src'>backed by: " + F.esc((b.backed_by || []).join(", ")) + "</div>" +
          (res.length ? '<table class="t"><tr><th>Symbol</th><th class="num">Price</th><th class="num">Δ%</th><th class="num">RSI</th><th class="num">P/E</th><th>Data</th><th></th></tr>' +
            res.map(function (x) {
              var t = x.technical || {}, f = x.fundamental || {};
              return "<tr><td><a href='#/company/" + F.esc(x.symbol) + "'>" + F.esc(x.symbol) + "</a></td><td class='num'>" +
                quoteRow(x.quote) + "</td><td class='num " + F.dirClass(x.quote.change_pct) + "'>" + F.fmtPct(x.quote.change_pct) +
                "</td><td class='num'>" + (t.rsi14 === undefined || t.rsi14 === null ? "—" : F.fmtNum(t.rsi14) + " <span class='pill pill-calc'>CALC</span>") +
                "</td><td class='num'>" + (f.PERatio === undefined || f.PERatio === null ? "—" : F.esc(String(f.PERatio))) +
                "</td><td>" + F.statusPill(x.timeliness || x.status) + (x.stale ? " " + F.statusPill("STALE") : "") +
                "<div class='src'>" + F.fmtIST(x.as_of) + "</div></td>" +
                "<td class='num'><button class='btn sm' data-wl='" + F.esc(x.symbol) + "'>+ Watch</button></td></tr>";
            }).join("") + "</table>"
            : unavail("No symbols pass these filters right now.")) +
          (excl.length ? "<h3 style='margin-top:10px'>Excluded from filter (no data — not scored)</h3><ul style='margin:6px 0;padding-left:18px'>" +
            excl.map(function (x) {
              return "<li class='mut'>" + F.esc(x.symbol) + ": " + F.esc(x.excluded_reason) + "</li>";
            }).join("") + "</ul>" : "") + "</div>";
        Array.prototype.forEach.call(document.querySelectorAll("[data-wl]"), function (btn) {
          btn.onclick = function () { addWatch(btn.getAttribute("data-wl")); };
        });
      });
    }
  }

  /* ---------- companies (search directory) ---------- */
  function pCompanies() {
    view().innerHTML = "<h1>Companies</h1><div class='sub'>Search any listed instrument — name, ticker, sector or index. Quotes: delayed Yahoo.</div>" +
      "<div class='card'><div class='row'><input id='c-q' class='in' style='flex:1;min-width:220px' placeholder='e.g. Reliance, TCS.NS, AAPL, Nifty'>" +
      "<button class='btn primary' id='c-go'>Search</button></div><div id='c-out' style='margin-top:10px'></div></div>";
    function go() {
      var q = el("c-q").value.trim();
      if (!q) return;
      el("c-out").innerHTML = skel(4);
      API.get("search", { q: q }).then(function (r) {
        var b = r.body;
        if (!b || !b.data) { el("c-out").innerHTML = unavail((b && b.message) || "No results."); return; }
        el("c-out").innerHTML = '<table class="t"><tr><th>Symbol</th><th>Name</th><th>Exchange</th><th>Type</th></tr>' +
          b.data.results.map(function (x) {
            return "<tr><td><a href='#/company/" + F.esc(x.symbol) + "'>" + F.esc(x.symbol) + "</a></td><td>" +
              F.esc(x.name || "—") + "</td><td>" + F.esc(x.exchange || "—") + "</td><td>" + F.esc(x.type || "—") + "</td></tr>";
          }).join("") + "</table>" + srcLine(b);
      });
    }
    el("c-go").onclick = go;
    el("c-q").onkeydown = function (e) { if (e.key === "Enter") go(); };
  }

  /* ---------- company detail ---------- */
  var CTABS = ["Overview", "Financials", "Valuation", "Estimates", "Earnings", "News", "Actions", "Holdings", "Charts", "Research"];
  function pCompany(sym, tab) {
    sym = (sym || "").toUpperCase();
    tab = tab || "Overview";
    view().innerHTML = "<div id='co-head' class='card'>" + skel(3) + "</div>" +
      "<div class='tabs' id='co-tabs'>" + CTABS.map(function (t) {
        return "<button data-t='" + t + "' class='" + (t === tab ? "on" : "") + "'>" + t + "</button>";
      }).join("") + "</div><div id='co-body'></div>";
    Array.prototype.forEach.call(document.querySelectorAll("#co-tabs button"), function (b) {
      b.onclick = function () { location.hash = "#/company/" + encodeURIComponent(sym) + "/" + b.getAttribute("data-t"); };
    });
    API.get("company", { symbol: sym }).then(function (rc) {
      API.get("quote", { symbol: sym }).then(function (rq) {
        if (!el("co-head")) return;
        renderHead(sym, rc.body, rq.body);
        renderTab(sym, tab);
        // Free-automatic mode: browser polls every 10s; the backend
        // serves cache unless an upstream refresh is allowed.
        every(10000, function () {
          if (!el("co-price")) return;
          API.get("quote", { symbol: sym }).then(function (r) {
            if (el("co-price")) patchHead(r.body);
          });
        });
      });
    });
    function patchHead(qenv) {
      var q = (qenv && qenv.data) || {};
      if (!q.price && q.price !== 0) return;
      var c = F.dirClass(q.change_pct);
      el("co-price").innerHTML = F.fmtNum(q.price) +
        " <span style='font-size:12px' class='mut'>" + F.esc(q.currency || "") + "</span>";
      var ch = el("co-chg");
      ch.className = c;
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
      var c = F.dirClass(q.change_pct);
      el("co-head").innerHTML = "<div class='row spread'><div><h1 style='margin:0'>" + F.esc(q.name || p.name || sym) +
        " <span class='mut' style='font-size:12px'>" + F.esc(sym) + "</span></h1>" +
        "<div class='sub' style='margin:4px 0 0'>" + F.esc(q.exchange || p.exchange || "—") + " · " +
        F.esc(q.instrument_type || p.instrument_type || "") + " · " + F.esc(q.currency || p.currency || "") +
        "</div><div class='src' id='co-pills'>" +
        (qenv ? F.statusPill(qenv.timeliness || qenv.status) : "") +
        (qenv && qenv.stale ? " " + F.statusPill("STALE") : "") + "</div>" +
        "<div class='src' id='co-fresh'>" + freshInner(qenv, "10s") + "</div></div>" +
        "<div style='text-align:right'><div id='co-price' style='font-family:var(--mono);font-size:22px;font-weight:700'>" + F.fmtNum(q.price) +
        " <span style='font-size:12px' class='mut'>" + F.esc(q.currency || "") + "</span></div>" +
        "<div id='co-chg' class='" + c + "' style='font-family:var(--mono)'>" + F.fmtPct(q.change_pct) + " (" + F.fmtNum(q.change) + ")</div>" +
        "<div class='grid g4' style='margin-top:8px;min-width:280px'>" +
        "<div class='metric'><div class='l'>Volume</div><div class='v' style='font-size:13px'>" + F.fmtInt(q.volume) + "</div></div>" +
        "<div class='metric'><div class='l'>Prev close</div><div class='v' style='font-size:13px'>" + F.fmtNum(q.previous_close) + "</div></div>" +
        "<div class='metric'><div class='l'>Day high</div><div class='v up' style='font-size:13px'>" + F.fmtNum(q.day_high) + "</div></div>" +
        "<div class='metric'><div class='l'>Day low</div><div class='v dn' style='font-size:13px'>" + F.fmtNum(q.day_low) + "</div></div>" +
        "<div class='metric'><div class='l'>52W high</div><div class='v' style='font-size:13px'>" + F.fmtNum(q.fifty_two_week_high) + "</div></div>" +
        "<div class='metric'><div class='l'>52W low</div><div class='v' style='font-size:13px'>" + F.fmtNum(q.fifty_two_week_low) + "</div></div>" +
        "</div>" +
        "<div class='row' style='justify-content:flex-end;margin-top:6px'><button class='btn sm' id='co-wl'>+ Watchlist</button>" +
        "<button class='btn sm' id='co-pf'>+ Portfolio</button></div></div></div>";
      el("co-wl").onclick = function () { addWatch(sym, q.name); };
      el("co-pf").onclick = function () {
        var qty = prompt("Quantity held for " + sym + "?", "10");
        if (qty === null) return;
        var px = prompt("Average buy price (" + (q.currency || "") + ")?", String(q.price || ""));
        if (px === null) return;
        API.post("portfolio", { symbol: sym, name: q.name || "", quantity: Number(qty), avg_price: Number(px) }).then(function (r) {
          toast(r.body.ok ? sym + " added to portfolio." : ("Failed: " + (r.body.error || r.http)));
        });
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
    if (tab === "Holdings") return tHoldings(sym, b);
    if (tab === "Charts") return tCharts(sym, b, "1Y", "1d");
    if (tab === "Research") return tResearch(sym, b);
  }
  function tOverview(sym, b) {
    b.innerHTML = "<div class='grid g2'><div class='card' id='ov-q'>" + skel(6) + "</div>" +
      "<div class='card' id='ov-r'>" + skel(6) + "</div></div><div id='ov-brief'></div>";
    var quote = null, history = null, ratios = null, settled = 0;
    API.get("quote", { symbol: sym }).then(function (r) {
      var q = r.body && r.body.data;
      quote = q;
      el("ov-q").innerHTML = "<h3>Key quote " + F.statusPill(r.body.status) + "</h3>" + (q ?
        "<dl class='kv'><dt>Price</dt><dd>" + F.fmtNum(q.price) + " " + F.esc(q.currency || "") + "</dd>" +
        "<dt>Δ vs prev close</dt><dd class='" + F.dirClass(q.change_pct) + "'>" + F.fmtPct(q.change_pct) + "</dd>" +
        "<dt>Prev close</dt><dd>" + F.fmtNum(q.previous_close) + "</dd>" +
        "<dt>Market time</dt><dd>" + F.fmtDateTime(q.market_time) + "</dd>" +
        "<dt>Feed</dt><dd>delayed · yahoo</dd></dl>" :
        unavail((r.body && r.body.message) || "Quote unavailable.")) + srcLine(r.body);
      maybeBrief();
    });
    API.get("ratios", { symbol: sym }).then(function (r) {
      ratios = (r.body && r.body.data) || null;
      el("ov-r").innerHTML = "<h3>Key metrics " + F.statusPill(r.body.status) + "</h3>" + (ratios ?
        "<dl class='kv'>" + ["MarketCapitalization", "PERatio", "PriceToBookRatio", "EVToEBITDA",
          "DividendYield", "EPS", "ProfitMargin", "ROE", "Beta"].map(function (k) {
            return "<dt>" + k + "</dt><dd>" + F.esc(ratios[k] === undefined ? "—" : ratios[k]) + "</dd>";
          }).join("") + "</dl>" :
        unavail((r.body && r.body.message) || "Fundamentals unavailable.")) + srcLine(r.body);
      maybeBrief();
    });
    API.get("history", { symbol: sym, range: "3M", interval: "1d" }).then(function (r) {
      history = (r.body && r.body.data) || null;
      maybeBrief();
    });
    function maybeBrief() {
      if (++settled < 3) return;
      if (el("ov-brief").getAttribute("data-done")) return;
      el("ov-brief").setAttribute("data-done", "1");
      var brief = window.FT_ANALYSIS.brief(sym, quote, history, ratios);
      window.FT_ANALYSIS.renderBrief(el("ov-brief"), brief);
    }
  }
  function stmtTable(title, env, periodKey) {
    if (!env || !env.data) return "<h2>" + title + "</h2>" + unavail((env && env.message) || "Provider not configured.");
    var d = env.data, reps = d.reports || [];
    if (!reps.length) return "<h2>" + title + "</h2>" + unavail("No reports returned.");
    var keys = Object.keys(reps[0]).filter(function (k) { return k !== "fiscalDateEnding" && k !== "reportedCurrency"; }).slice(0, 14);
    var h = "<h2>" + title + " " + F.statusPill(env.status) + "</h2>" +
      '<div class="src">currency: ' + F.esc(d.currency || "?") + " · period: " + F.esc(d.period || "") + " · src: " + F.esc(env.source || "") + "</div>" +
      '<div class="card" style="overflow:auto"><table class="t"><tr><th>Line item</th>';
    reps.slice(0, 6).forEach(function (r) { h += "<th class='num'>" + F.esc(r.fiscalDateEnding || "") + "</th>"; });
    h += "<th class='num'>YoY</th></tr>";
    keys.forEach(function (k) {
      h += "<tr><td>" + F.esc(k) + "</td>";
      var vals = reps.slice(0, 6).map(function (r) { return r[k] === "None" ? null : Number(r[k]); });
      vals.forEach(function (v) { h += "<td class='num'>" + (v === null || isNaN(v) ? "—" : F.fmtMoney(v)) + "</td>"; });
      var yoy = (vals[0] !== null && vals[1] !== null && vals[1] !== 0 && !isNaN(vals[0]) && !isNaN(vals[1]))
        ? (vals[0] - vals[1]) / Math.abs(vals[1]) * 100 : null;
      h += "<td class='num " + F.dirClass(yoy) + "'>" + F.fmtPct(yoy) + " <span class='pill pill-calc'>CALC</span></td></tr>";
    });
    return h + "</table></div>";
  }
  function tFinancials(sym, b) {
    b.innerHTML = "<div class='row'><select id='f-s' class='in'><option value='income'>Income</option><option value='balance'>Balance sheet</option><option value='cashflow'>Cash flow</option></select>" +
      "<select id='f-p' class='in'><option value='annual'>Annual</option><option value='quarterly'>Quarterly</option></select>" +
      "<button class='btn primary' id='f-go'>Load</button></div><div id='f-out' style='margin-top:10px'></div>";
    function go() {
      el("f-out").innerHTML = "<div class='card'>" + skel(6) + "</div>";
      API.get("fundamentals", { symbol: sym, statement: el("f-s").value, period: el("f-p").value }).then(function (r) {
        el("f-out").innerHTML = stmtTable("Financial statements", r.body) + srcLine(r.body);
      });
    }
    el("f-go").onclick = go; go();
  }
  function tValuation(sym, b) {
    b.innerHTML = "<div id='v-out' class='card'>" + skel(6) + "</div>";
    API.get("ratios", { symbol: sym }).then(function (rr) {
      API.get("quote", { symbol: sym }).then(function (rq) {
        var r = (rr.body && rr.body.data) || null, q = (rq.body && rq.body.data) || null;
        if (!r) {
          el("v-out").innerHTML = "<h3>Valuation " + F.statusPill(rr.body.status) + "</h3>" +
            unavail((rr.body && rr.body.message) || "Ratios unavailable.") + srcLine(rr.body);
          return;
        }
        function row(l, v, tag) {
          return "<tr><td>" + l + "</td><td class='num'>" + (v === undefined || v === null || v === "None" || v === "-" ? "—" : F.esc(v)) +
            "</td><td>" + tag + "</td></tr>";
        }
        el("v-out").innerHTML = "<h3>Valuation " + F.statusPill(rr.body.status) + "</h3>" +
          "<div class='src'>provider values: REPORTED · nothing calculated here · period: TTM unless labeled</div>" +
          '<table class="t"><tr><th>Metric</th><th class="num">Value</th><th>Kind</th></tr>' +
          row("Price", q && q.price !== undefined ? F.fmtNum(q.price) + " " + (q.currency || "") : "—", F.statusPill("delayed")) +
          row("Market cap", r.MarketCapitalization, "REPORTED") +
          row("P/E (TTM)", r.PERatio, "REPORTED") +
          row("Forward P/E", r.ForwardPE, "REPORTED") +
          row("P/B", r.PriceToBookRatio, "REPORTED") +
          row("EV/Revenue", r.EVToRevenue, "REPORTED") +
          row("EV/EBITDA", r.EVToEBITDA, "REPORTED") +
          row("PEG", r.PEGRatio, "REPORTED") +
          row("Dividend yield", r.DividendYield, "REPORTED") +
          "</table>" + srcLine(rr.body) +
          "<div class='src'>forward P/E shown only when the feed returns it — never estimated in-terminal.</div>";
      });
    });
  }
  function tEstimates(sym, b) {
    b.innerHTML = "<div class='card' id='e-out'>" + skel(3) + "</div>";
    API.get("estimates", { symbol: sym }).then(function (r) {
      el("e-out").innerHTML = "<h3>Analyst estimates " + F.statusPill(r.body.status) + "</h3>" +
        unavail((r.body && r.body.message) || "Estimates unavailable.") + srcLine(r.body);
    });
  }
  function tEarnings(sym, b) {
    b.innerHTML = "<div class='card' id='e2-out'>" + skel(5) + "</div>";
    API.get("earnings", { symbol: sym }).then(function (r) {
      if (!el("e2-out")) return;
      var d = r.body && r.body.data;
      if (!d) {
        el("e2-out").innerHTML = "<h3>Earnings " + F.statusPill(r.body.status) + "</h3>" +
          unavail((r.body && r.body.message) || "Earnings unavailable.") + srcLine(r.body);
        return;
      }
      function repRow(x) {
        return "<tr><td>" + F.esc(x.fiscalDateEnding || x.reportedDate || "—") + "</td>" +
          "<td class='num'>" + F.esc(x.reportedEPS !== undefined ? x.reportedEPS : "—") + "</td>" +
          "<td class='num'>" + F.esc(x.estimatedEPS !== undefined ? x.estimatedEPS : "—") + "</td>" +
          "<td class='num'>" + F.esc(x.surprise !== undefined ? x.surprise : (x.surprisePercentage !== undefined ? x.surprisePercentage + "%" : "—")) + "</td></tr>";
      }
      el("e2-out").innerHTML = "<h3>Earnings · " + F.esc(sym) + " " + F.statusPill(r.body.status) + "</h3>" +
        "<div class='src'>periods never mixed · source: Alpha Vantage EARNINGS · estimated EPS only where the feed reports it — never synthesised</div>" +
        "<h2>Annual (reported EPS)</h2>" +
        ((d.annual && d.annual.length) ? '<table class="t"><tr><th>Fiscal end</th><th class="num">Reported EPS</th><th class="num">Est. EPS</th><th class="num">Surprise</th></tr>' +
          d.annual.map(repRow).join("") + "</table>" : unavail("No annual earnings rows.")) +
        "<h2>Quarterly</h2>" +
        ((d.quarterly && d.quarterly.length) ? '<table class="t"><tr><th>Fiscal end</th><th class="num">Reported EPS</th><th class="num">Est. EPS</th><th class="num">Surprise</th></tr>' +
          d.quarterly.map(repRow).join("") + "</table>" : unavail("No quarterly earnings rows.")) +
        srcLine(r.body);
    });
  }
  function tNews(sym, b) {
    b.innerHTML = "<div class='card' id='n-out'>" + skel(5) + "</div>";
    API.get("news", { symbol: sym, limit: 20 }).then(function (r) {
      var d = r.body && r.body.data;
      el("n-out").innerHTML = "<h3>News · " + F.esc(sym) + " " + F.statusPill(r.body.status) + "</h3>" +
        (d ? d.items.map(newsItem).join("") : unavail((r.body && r.body.message) || "News unavailable.")) + srcLine(r.body);
    });
  }
  function tActions(sym, b) {
    b.innerHTML = "<div class='card' id='a-out'>" + skel(4) + "</div>";
    API.get("actions", { symbol: sym }).then(function (r) {
      var d = r.body && r.body.data;
      if (!d) { el("a-out").innerHTML = "<h3>Corporate actions</h3>" + unavail((r.body && r.body.message) || "Unavailable.") + srcLine(r.body); return; }
      el("a-out").innerHTML = "<h3>Corporate actions " + F.statusPill(r.body.status) + "</h3>" +
        "<h2>Dividends (" + d.dividends.length + ")</h2>" +
        (d.dividends.length ? '<table class="t"><tr><th>Date</th><th class="num">Amount</th></tr>' +
          d.dividends.slice(0, 20).map(function (x) {
            return "<tr><td>" + F.fmtDate(x.date) + "</td><td class='num'>" + F.fmtNum(x.amount, 4) + " " + F.esc(x.currency || "") + "</td></tr>";
          }).join("") + "</table>" : unavail("No dividends in the last 2 years.")) +
        "<h2>Splits (" + d.splits.length + ")</h2>" +
        (d.splits.length ? '<table class="t"><tr><th>Date</th><th class="num">Ratio</th></tr>' +
          d.splits.map(function (x) {
            return "<tr><td>" + F.fmtDate(x.date) + "</td><td class='num'>" + F.esc(x.numerator + ":" + x.denominator) + "</td></tr>";
          }).join("") + "</table>" : unavail("No splits in the last 2 years.")) +
        "<div class='src'>" + F.esc(d.note || "") + "</div>" + srcLine(r.body);
    });
  }
  function tHoldings(sym, b) {
    b.innerHTML = "<div class='card'>" + skel(3) + "</div>";
    API.get("ratios", { symbol: sym }).then(function (r) {
      b.innerHTML = "<h2>Shareholding</h2><div class='card'><h3>Ownership " + F.statusPill("unavailable") + "</h3>" +
        unavail("Shareholding requires a fundamentals/ownership feed. Provider not configured — promoter/FII/DII splits are never guessed.") +
        srcLine(r.body) + "</div>";
    });
  }
  /* Yahoo symbol -> TradingView symbol for the official widget embed.
     Only well-known mappings; otherwise the raw symbol is passed and the
     widget itself reports unknown symbols. Widget data is TradingView's,
     never presented as our backend feed. */
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
    b.innerHTML = "<div class='row'><button class='btn sm primary' id='ch-t1'>Terminal chart</button>" +
      "<button class='btn sm' id='ch-t2'>TradingView widget</button>" +
      "<span id='ch-ranges' class='row'>" +
      ["1D", "5D", "1M", "3M", "6M", "1Y", "5Y", "MAX"].map(function (x) {
        return "<button class='btn sm" + (x === range ? " primary" : "") + "' data-r='" + x + "'>" + x + "</button>";
      }).join("") + "</span></div>" +
      "<div class='card' id='ch-tvnote' style='margin-top:10px;display:none'>" +
      "<h3>External chart — TradingView widget " + F.statusPill("delayed") + "</h3>" +
      "<div class='src'>Official TradingView embed. Its data is TradingView's own feed — not ours, not scraped, not re-labeled. " +
      "Free widget data is delayed; NSE real-time requires an authorized feed.</div>" +
      "<div id='ch-tvw' style='height:420px;margin-top:8px'></div></div>" +
      "<div class='card' id='ch-own' style='margin-top:10px'><canvas class='chart' id='ch-c'></canvas>" +
      "<div class='ch-legend'><span><i style='color:#2fbf71'>—</i> price</span><span><i style='color:#4da3ff'>—</i> SMA20</span>" +
      "<span><i style='color:#e0a63c'>—</i> SMA50</span><span id='ch-meta'></span></div></div>" +
      "<div class='src' style='margin-top:6px'>NSE REAL-TIME NOT AVAILABLE WITHOUT AUTHORIZED FEED. " +
      "All terminal charts use delayed backend data (Yahoo → Twelve Data → Alpha Vantage).</div>" +
      "<div class='card' id='ch-tech' style='margin-top:10px'>" + skel(3) + "</div>";
    API.get("technical", { symbol: sym }).then(function (r) {
      if (!el("ch-tech")) return;
      var d = r.body && r.body.data;
      if (!d) {
        el("ch-tech").innerHTML = "<h3>Technicals " + F.statusPill("CALCULATED") + "</h3>" +
          unavail((r.body && r.body.message) || "Needs verified history.") + srcLine(r.body);
        return;
      }
      function m(label, v, suffix) {
        return "<div class='metric'><div class='l'>" + label + "</div><div class='v' style='font-size:13px'>" +
          (v === null || v === undefined ? "—" : F.fmtNum(v) + (suffix || "")) + "</div></div>";
      }
      el("ch-tech").innerHTML = "<h3>Technicals " + F.statusPill("CALCULATED") + "</h3>" +
        "<div class='src'>CALCULATED FROM: " + F.esc(d.calculated_from || "?") + " · PERIODS: " + d.periods +
        " daily bars · CALCULATED AT: " + F.esc(d.calculated_at || "?") + " · not provider-reported</div>" +
        "<div class='grid g4' style='margin-top:8px'>" +
        m("RSI 14", d.rsi14) + m("MACD", d.macd) + m("Signal", d.macd_signal) + m("Histogram", d.macd_histogram) +
        m("ATR 14", d.atr14) + m("Vol 20d ann.", d.volatility_20d_ann_pct, "%") +
        m("1M return", d.return_1m_pct, "%") + m("Max drawdown", d.max_drawdown_pct, "%") +
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
    var iv = range === "1D" ? "5m" : (range === "5D" ? "15m" : "1d");
    API.get("history", { symbol: sym, range: range, interval: iv }).then(function (r) {
      var d = r.body && r.body.data;
      if (!d || !d.bars || !d.bars.length) {
        el("ch-c").outerHTML = unavail((r.body && r.body.message) || "No chart data.");
        return;
      }
      window.FT_CHART.drawPriceChart(el("ch-c"), d.bars, { sma: [20, 50] });
      el("ch-meta").textContent = "n=" + d.bars.length + " · " + d.interval + " · " +
        (r.body.timeliness || r.body.status) + " · " + F.srcName(r.body.source) + " · " + d.currency +
        " · as of " + F.fmtIST(r.body.as_of);
    });
  }
  function loadTvWidget(sym) {
    var host = el("ch-tvw");
    if (!host) return;
    host.innerHTML = "<div class='skel'></div>";
    function render() {
      if (!el("ch-tvw")) return;
      /* global TradingView */
      try {
        new window.TradingView.widget({
          container_id: "ch-tvw",
          symbol: tvSymbol(sym),
          interval: "D",
          theme: "dark",
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
      "<div class='row'><select id='r-s' class='in'>" + RSECTS.map(function (s) { return "<option>" + s + "</option>"; }).join("") +
      "</select><input id='r-t' class='in' placeholder='Title' style='flex:1'></div>" +
      "<div style='margin-top:8px'><textarea id='r-b' class='in' placeholder='Observation / thesis / catalyst / risk… (your own words — stored locally)'></textarea></div>" +
      "<div style='margin-top:8px'><button class='btn primary' id='r-save'>Save note</button></div></div>" +
      "<div class='card'><h3>Saved notes</h3><div id='r-list'>" + skel(3) + "</div></div></div>";
    function load() {
      API.get("research", { symbol: sym }).then(function (r) {
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
  function pWatchlist() {
    view().innerHTML = "<h1>Watchlist</h1><div class='sub'>Persisted server-side (SQLite). Free-automatic quotes via fallback chain · auto-refresh 30s.</div>" +
      "<div class='card'><div class='row'><input id='w-s' class='in' placeholder='Add symbol e.g. TCS.NS' style='flex:1;min-width:200px'>" +
      "<button class='btn primary' id='w-add'>Add</button></div><div id='w-t' style='margin-top:10px'>" + skel(5) + "</div></div>";
    el("w-add").onclick = function () { var s = el("w-s").value.trim(); if (s) addWatch(s.toUpperCase()); };
    function load() {
      if (!el("w-t")) return;
      API.get("watchlist").then(function (r) {
        if (!el("w-t")) return;
        var items = (r.body && r.body.items) || [];
        el("w-t").innerHTML = items.length ? '<table class="t"><tr><th>Symbol</th><th>Name</th><th class="num">Price</th><th class="num">Δ%</th><th></th></tr>' +
          items.map(function (i) {
            return "<tr><td><a href='#/company/" + F.esc(i.symbol) + "'>" + F.esc(i.symbol) + "</a></td><td>" +
              F.esc(i.name || (i.quote && i.quote.name) || "—") + "</td><td class='num'>" + F.fmtNum(i.quote && i.quote.price) +
              "</td><td class='num " + F.dirClass(i.quote && i.quote.change_pct) + "'>" + F.fmtPct(i.quote && i.quote.change_pct) +
              "</td><td class='num'><button class='btn sm danger' data-rm='" + F.esc(i.symbol) + "'>remove</button></td></tr>";
          }).join("") + "</table>" : unavail("Watchlist is empty. Add symbols to track them.");
        Array.prototype.forEach.call(document.querySelectorAll("[data-rm]"), function (x) {
          x.onclick = function () { API.del("watchlist", { symbol: x.getAttribute("data-rm") }).then(load); };
        });
      });
    }
    every(30000, load);
  }

  /* ---------- portfolio ---------- */
  function pPortfolio() {
    view().innerHTML = "<h1>Portfolio</h1><div class='sub'>Manual holdings ledger (no brokerage integration claimed). P&amp;L uses delayed quotes.</div>" +
      "<div class='card'><h3>Add / update holding</h3><div class='row'>" +
      "<input id='p-s' class='in' placeholder='Symbol' style='width:130px'><input id='p-q' class='in' placeholder='Qty' style='width:90px'>" +
      "<input id='p-p' class='in' placeholder='Avg price' style='width:110px'><button class='btn primary' id='p-add'>Save</button></div></div>" +
      "<div id='p-out' style='margin-top:12px'><div class='card'>" + skel(5) + "</div></div>";
    el("p-add").onclick = function () {
      API.post("portfolio", { symbol: el("p-s").value, quantity: Number(el("p-q").value), avg_price: Number(el("p-p").value) }).then(function (r) {
        toast(r.body.ok ? "Holding saved." : ("Failed: " + (r.body.error || r.http))); load();
      });
    };
    function load() {
      API.get("portfolio").then(function (r) {
        var b = r.body || {}, pos = b.positions || [];
        var h = "<div class='grid g4'>" +
          "<div class='card metric'><h3>Invested</h3><div class='v'>" + F.fmtMoney(b.invested_value) + "</div></div>" +
          "<div class='card metric'><h3>Current " + F.statusPill("delayed") + "</h3><div class='v'>" + (b.current_value === null || b.current_value === undefined ? "—" : F.fmtMoney(b.current_value)) + "</div></div>" +
          "<div class='card metric'><h3>Unrealised P&amp;L</h3><div class='v " + F.dirClass(b.unrealized_pnl) + "'>" + (b.unrealized_pnl === null || b.unrealized_pnl === undefined ? "—" : F.fmtMoney(b.unrealized_pnl)) + "</div></div>" +
          "<div class='card metric'><h3>P&amp;L % <span class='pill pill-calc'>CALC</span></h3><div class='v " + F.dirClass(b.pnl_pct) + "'>" + F.fmtPct(b.pnl_pct) + "</div></div></div>";
        h += "<div class='card' style='margin-top:12px'><h3>Holdings (" + pos.length + ")</h3>" + (pos.length ?
          '<table class="t"><tr><th>Symbol</th><th class="num">Qty</th><th class="num">Avg</th><th class="num">LTP</th><th class="num">Invested</th><th class="num">Current</th><th class="num">P&amp;L</th><th class="num">Alloc</th><th></th></tr>' +
          pos.map(function (p) {
            return "<tr><td><a href='#/company/" + F.esc(p.symbol) + "'>" + F.esc(p.symbol) + "</a></td><td class='num'>" + F.fmtNum(p.quantity, 0) +
              "</td><td class='num'>" + F.fmtNum(p.avg_price) + "</td><td class='num'>" + F.fmtNum(p.current_price) +
              "</td><td class='num'>" + F.fmtMoney(p.invested_value) + "</td><td class='num'>" + (p.current_value === null ? "—" : F.fmtMoney(p.current_value)) +
              "</td><td class='num " + F.dirClass(p.unrealized_pnl) + "'>" + (p.unrealized_pnl === null ? "—" : F.fmtMoney(p.unrealized_pnl) + " (" + F.fmtPct(p.pnl_pct) + ")") +
              "</td><td class='num'>" + F.fmtPct(p.allocation_pct) + "</td>" +
              "<td class='num'><button class='btn sm danger' data-prm='" + F.esc(p.symbol) + "'>x</button></td></tr>";
          }).join("") + "</table>" : unavail("No holdings yet.")) + "</div>";
        el("p-out").innerHTML = h;
        Array.prototype.forEach.call(document.querySelectorAll("[data-prm]"), function (x) {
          x.onclick = function () { API.del("portfolio", { symbol: x.getAttribute("data-prm") }).then(load); };
        });
      });
    }
    load();
  }

  /* ---------- news ---------- */
  function pNews() {
    view().innerHTML = "<h1>News</h1><div class='sub'>Headlines via Yahoo Finance RSS (no key). Never synthesised — if the feed fails you see an explicit state.</div>" +
      "<div class='card'><div class='row'><input id='n-s' class='in' placeholder='Filter by symbol e.g. AAPL (blank = market)'>" +
      "<input id='n-t' class='in' placeholder='Topic keyword (optional)'><button class='btn primary' id='n-go'>Load</button></div>" +
      "<div id='n-out' style='margin-top:10px'>" + skel(5) + "</div></div>";
    function go() {
      if (!el("n-out")) return;
      el("n-out").innerHTML = skel(5);
      API.get("news", { symbol: el("n-s").value.trim(), topic: el("n-t").value.trim(), limit: 25 }).then(function (r) {
        if (!el("n-out")) return;
        var d = r.body && r.body.data;
        el("n-out").innerHTML = (d ? d.items.map(newsItem).join("") : unavail((r.body && r.body.message) || "News unavailable.")) + srcLine(r.body);
      });
    }
    el("n-go").onclick = go;
    every(60000, go);
  }

  /* ---------- research home ---------- */
  function pResearch() {
    view().innerHTML = "<h1>Research</h1><div class='sub'>All saved thesis notes, observations, catalysts and risks across symbols. Open a company → Research tab to add.</div>" +
      "<div class='card' id='r-all'>" + skel(5) + "</div>";
    API.get("research", {}).then(function (r) {
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
    view().innerHTML = "<h1>Compare</h1><div class='sub'>Factual side-by-side. No automatic ranking — you judge.</div>" +
      "<div class='card'><div class='row'><input id='k-s' class='in' style='flex:1' value='RELIANCE.NS,TCS.NS,INFY.NS' placeholder='Comma-separated symbols, max 4'>" +
      "<button class='btn primary' id='k-go'>Compare</button></div></div><div id='k-out' style='margin-top:12px'></div>";
    function go() {
      var syms = el("k-s").value.split(",").map(function (s) { return s.trim().toUpperCase(); }).filter(Boolean).slice(0, 4);
      if (!syms.length) return;
      el("k-out").innerHTML = "<div class='card'>" + skel(6) + "</div>";
      Promise.all(syms.map(function (s) {
        return Promise.all([API.get("quote", { symbol: s }), API.get("ratios", { symbol: s })]).then(function (x) {
          return { symbol: s, quote: x[0].body && x[0].body.data, qstat: x[0].body && x[0].body.status, ratios: x[1].body && x[1].body.data };
        });
      })).then(function (cols) {
        var qrows = [["Price (delayed)", function (c) { return c.quote ? F.fmtNum(c.quote.price) + " " + (c.quote.currency || "") : "—"; }],
          ["Δ% vs prev close (calc)", function (c) { return c.quote ? F.fmtPct(c.quote.change_pct) : "—"; }],
          ["Exchange", function (c) { return c.quote ? F.esc(c.quote.exchange || "—") : "—"; }]];
        var rkeys = ["MarketCapitalization", "PERatio", "PriceToBookRatio", "EVToEBITDA", "DividendYield", "EPS", "ProfitMargin", "ROE", "Beta"];
        var h = "<div class='card' style='overflow:auto'><table class='t'><tr><th class='cmp-head'>Metric</th>" +
          cols.map(function (c) { return "<th class='num'><a href='#/company/" + F.esc(c.symbol) + "'>" + F.esc(c.symbol) + "</a></th>"; }).join("") + "</tr>";
        qrows.forEach(function (qr) {
          h += "<tr><td>" + qr[0] + "</td>" + cols.map(function (c) { return "<td class='num'>" + qr[1](c) + "</td>"; }).join("") + "</tr>";
        });
        rkeys.forEach(function (k) {
          h += "<tr><td>" + k + "</td>" + cols.map(function (c) {
            var v = c.ratios && c.ratios[k];
            return "<td class='num'>" + (v === undefined || v === null ? "—" : F.esc(String(v))) + "</td>";
          }).join("") + "</tr>";
        });
        el("k-out").innerHTML = h + "</table><div class='src'>quotes: delayed yahoo · ratios: " +
          (cols[0].ratios ? "alphavantage" : "unavailable — set ALPHA_VANTAGE_API_KEY") + "</div></div>";
      });
    }
    el("k-go").onclick = go; go();
  }

  /* ---------- ipos / earnings / macro / settings ---------- */
  function pIPOs() {
    view().innerHTML = "<h1>IPOs</h1><div class='sub'>Free IPO calendar feed (Alpha Vantage) where entitled. Never synthesised.</div>" +
      "<div class='card' id='ipo-out'>" + skel(5) + "</div>";
    API.get("ipo").then(function (r) {
      if (!el("ipo-out")) return;
      var d = r.body && r.body.data;
      if (!d || !d.rows || !d.rows.length) {
        el("ipo-out").innerHTML = "<h3>IPO calendar " + F.statusPill(r.body.status) + "</h3>" +
          "<div class='empty'><b>IPO DATA UNAVAILABLE.</b><br>" + F.esc((r.body && r.body.message) || "No IPO feed configured.") +
          "<br><span class='src'>No IPO records are synthesised.</span></div>" + srcLine(r.body);
        return;
      }
      var cols = d.columns || Object.keys(d.rows[0]);
      el("ipo-out").innerHTML = "<h3>IPO calendar (" + d.rows.length + ") " + F.statusPill(r.body.status) + "</h3>" +
        '<div style="overflow:auto"><table class="t"><tr>' + cols.map(function (c) { return "<th>" + F.esc(c) + "</th>"; }).join("") + "</tr>" +
        d.rows.map(function (row) {
          return "<tr>" + cols.map(function (c) { return "<td>" + F.esc(row[c] || "—") + "</td>"; }).join("") + "</tr>";
        }).join("") + "</table></div>" + srcLine(r.body);
    });
  }
  function pEarnings() {
    view().innerHTML = "<h1>Earnings</h1><div class='sub'>Reported earnings via Alpha Vantage (free tier) where a key is configured. Estimates appear only when the feed reports them.</div>" +
      "<div class='card'><div class='row'><input id='e-s' class='in' placeholder='Symbol e.g. RELIANCE.NS'>" +
      "<button class='btn primary' id='e-go'>Open company earnings</button>" +
      "<button class='btn' id='e-d'>Dividends &amp; splits</button></div>" +
      "<div class='src' style='margin-top:6px'>For dividends/splits use Corporate Actions (exchange-reported Yahoo events).</div></div>";
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
    view().innerHTML = "<h1>Macro</h1><div class='sub'>Index snapshot from the fallback chain (delayed) + official-style economic indicators via Alpha Vantage (free) where a key is configured. Nothing fabricated.</div>" +
      "<div id='mc-out' class='card'>" + skel(5) + "</div>" +
      "<div class='card' id='mc-econ' style='margin-top:12px'>" + skel(4) + "</div>";
    API.get("market-overview").then(function (r) {
      if (!el("mc-out")) return;
      var items = ((r.body && r.body.items) || []).filter(function (i) { return isIndex(i.symbol); });
      el("mc-out").innerHTML = items.length ? '<table class="t"><tr><th>Index</th><th>Name</th><th class="num">Level</th><th class="num">Δ%</th></tr>' +
        items.map(function (i) {
          var q = i.quote || {};
          return "<tr><td>" + F.esc(i.symbol) + "</td><td>" + F.esc(q.name || "—") + "</td><td class='num'>" + F.fmtNum(q.price) +
            "</td><td class='num " + F.dirClass(q.change_pct) + "'>" + F.fmtPct(q.change_pct) + "</td></tr>";
        }).join("") + "</table><div class='src'>fallback chain · delayed</div>" : unavail("Index data unavailable.");
    });
    var INDS = ["GDP", "INFLATION", "UNEMPLOYMENT", "FEDERAL_FUNDS_RATE"];
    Promise.all(INDS.map(function (k) { return API.get("macro", { indicator: k }); })).then(function (rs) {
      if (!el("mc-econ")) return;
      var cards = rs.map(function (r, ix) {
        var d = r.body && r.body.data;
        var pts = (d && d.points) || [];
        var last = pts[0] || {};
        return "<div class='card metric'><h3>" + INDS[ix] + " " + F.statusPill(r.body.status) + "</h3>" +
          (pts.length ? "<div class='v'>" + F.esc(last.value || "—") + "</div><div class='l'>" +
            F.esc(last.date || "") + " · " + F.esc((d && d.unit) || "") + " · Alpha Vantage</div>"
            : "<div class='l'>" + F.esc((r.body && r.body.message) || "Unavailable") + "</div>") + "</div>";
      }).join("");
      el("mc-econ").innerHTML = "<h3>Economic indicators</h3><div class='grid g4'>" + cards + "</div>";
    });
  }
  function pSettings() {
    view().innerHTML = "<h1>Settings</h1><div class='sub'>Provider wiring &amp; data transparency — free-automatic mode, no paid subscription required</div>" +
      "<div class='card'><h3>Data Providers</h3><div id='s-prov'>" + skel(5) + "</div></div>" +
      "<div class='grid g2' style='margin-top:12px'><div class='card'><h3>Refresh policy</h3><div class='src'>" +
      "Browser polls quotes every 10s (company) / 30s (watchlist) / 60s (dashboard, news). " +
      "The backend serves cache unless an upstream refresh is allowed: quotes 30s, intraday history 15m, daily history 4h, " +
      "news 10m, fundamentals 24h, Alpha Vantage quotes 6h (25 req/day free tier). " +
      "Twelve Data free budget: 8 credits/min, 800/day. Free APIs are never hammered.</div></div>" +
      "<div class='card'><h3>Environment</h3><div class='src'>ALPHA_VANTAGE_API_KEY / FUNDAMENTALS_API_KEY — optional, server-side only, enables statements + ratios + last-resort quotes.<br><br>" +
      "TWELVE_DATA_API_KEY — optional, server-side only, enables the middle fallback leg.<br><br>" +
      "TERMINAL_DB — sqlite path (default ./terminal-data/terminal.db).<br><br>No key is ever shipped to the browser. Validate input; external content is escaped before render.</div>" +
      "<h3 style='margin-top:12px'>Legend</h3><div class='row'>" + F.statusPill("REAL-TIME") + F.statusPill("DELAYED") + F.statusPill("END-OF-DAY") + F.statusPill("CALCULATED") + F.statusPill("UNAVAILABLE") + F.statusPill("STALE") + "</div></div></div>";
    API.get("providers").then(function (r) {
      if (!el("s-prov")) return;
      var b = r.body || {}, list = b.providers || [];
      var badge = {
        connected: ["pill-live", "✓ Connected"],
        key_missing: ["pill-na", "○ API KEY NOT CONFIGURED"],
        feed_missing: ["pill-na", "○ AUTHORIZED REAL-TIME FEED NOT CONFIGURED"],
        widget_available: ["pill-live", "✓ CHART WIDGET AVAILABLE"],
        cooling: ["pill-delayed", "○ COOLING (upstream errors)"],
      };
      el("s-prov").innerHTML = '<table class="t"><tr><th>Provider</th><th>Status</th><th>Detail</th></tr>' +
        list.map(function (p) {
          var m = badge[p.state] || ["pill-na", F.esc(p.state)];
          var extra = "";
          if (p.id === "twelvedata" && p.budget) {
            extra = "<div class='src'>budget: " + p.budget.per_minute_used + "/" +
              p.budget.per_minute_limit + " per min · " + p.budget.daily_used + "/" +
              p.budget.daily_limit + " today</div>";
          }
          if (p.id === "yahoo" && p.health && p.health.last_latency_ms !== null && p.health.last_latency_ms !== undefined) {
            extra = "<div class='src'>last upstream latency: " + p.health.last_latency_ms + " ms</div>";
          }
          return "<tr><td><b>" + F.esc(p.label) + "</b></td><td><span class='pill " + m[0] + "'>" + m[1] + "</span></td>" +
            "<td style='white-space:normal'>" + F.esc(p.detail || "") + extra + "</td></tr>";
        }).join("") + "</table>" +
        "<div class='src' style='margin-top:8px'>fallback chains — quote: " + F.esc(((b.chain || {}).quote || []).join(" → ")) +
        " · history: " + F.esc(((b.chain || {}).history || []).join(" → ")) +
        " → DATA UNAVAILABLE. Never hide why data is unavailable.</div>";
    });
  }

  window.FT_PAGES = {
    init, clearTimers, pDashboard, pMarkets, pScreener, pCompanies, pCompany, pWatchlist,
    pPortfolio, pNews, pResearch, pCompare, pIPOs, pEarnings, pMacro, pSettings, toast,
  };
})();
