/* Terminal views. Every number carries source/period/currency attribution;
   missing data renders explicit unavailable states — never invented. */
(function () {
  "use strict";
  var API, F;
  function init() { API = window.FT_API; F = window.FT_FMT; }
  function el(id) { return document.getElementById(id); }
  function view() { return el("view"); }
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
    view().innerHTML = "<h1>Dashboard</h1><div class='sub'>Delayed market snapshot · source: Yahoo · quotes refresh ~60s server-side</div>" +
      "<div id='d-idx' class='grid g4'>" + skel(4) + "</div>" +
      "<div class='grid g2'><div><h2>Movers (tracked universe)</h2><div id='d-mov' class='card'>" + skel(5) + "</div></div>" +
      "<div><h2>Latest headlines</h2><div id='d-news' class='card'>" + skel(5) + "</div></div></div>" +
      "<div id='d-src'></div>";
    API.get("market-overview").then(function (r) {
      var items = (r.body && r.body.items) || [];
      var idx = items.filter(function (i) { return i.symbol.charAt(0) === "^"; });
      var eq = items.filter(function (i) { return i.symbol.charAt(0) !== "^"; });
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
      el("d-src").innerHTML = '<div class="src">market-overview · delayed · yahoo</div>';
    });
    API.get("news", { limit: 8 }).then(function (r) {
      var b = r.body;
      if (!b || !b.data || !b.data.items) { el("d-news").innerHTML = unavail((b && b.message) || "News unavailable."); return; }
      el("d-news").innerHTML = b.data.items.slice(0, 8).map(newsItem).join("");
    });
  }
  function newsItem(n) {
    return '<div class="news-item"><a href="' + F.esc(n.url) + '" target="_blank" rel="noopener">' +
      F.esc(n.title) + "</a><div class='meta'>" + F.esc(n.source || "") + " · " + F.esc(n.published_at || "") + "</div></div>";
  }

  /* ---------- markets ---------- */
  function pMarkets() {
    view().innerHTML = "<h1>Markets</h1><div class='sub'>Live-delayed quotes across the default universe (NSE, BSE, US, global indices)</div>" +
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
    view().innerHTML = "<h1>Screener</h1><div class='sub'>Only filters backed by live quote data are enabled. Fundamental filters need a fundamentals provider.</div>" +
      "<div class='card'><div class='row'>" +
      "<label>Min Δ% <input id='s-min' class='in' style='width:90px' placeholder='e.g. 1'></label>" +
      "<label>Max Δ% <input id='s-max' class='in' style='width:90px' placeholder='e.g. 5'></label>" +
      "<label>Min price <input id='s-minp' class='in' style='width:100px'></label>" +
      "<label>Max price <input id='s-maxp' class='in' style='width:100px'></label>" +
      "<button class='btn primary' id='s-run'>Run screen</button></div>" +
      "<div class='src' style='margin-top:8px'>backed by: price, change_pct · unsupported: P/E, P/B, ROE, ROCE, debt/equity, margins, growth, dividend yield, EV/EBITDA (need ALPHA_VANTAGE_API_KEY)</div></div>" +
      "<div id='s-out' style='margin-top:12px'></div>";
    el("s-run").onclick = run;
    run();
    function run() {
      el("s-out").innerHTML = "<div class='card'>" + skel(5) + "</div>";
      API.get("screener", {
        min_change_pct: el("s-min").value, max_change_pct: el("s-max").value,
        min_price: el("s-minp").value, max_price: el("s-maxp").value,
      }).then(function (r) {
        var b = r.body || {}, res = b.results || [];
        el("s-out").innerHTML = "<div class='card'><h3>Matches (" + res.length + ") " + F.statusPill("delayed") + "</h3>" +
          (res.length ? '<table class="t"><tr><th>Symbol</th><th class="num">Price</th><th class="num">Δ%</th><th></th></tr>' +
            res.map(function (x) {
              return "<tr><td><a href='#/company/" + F.esc(x.symbol) + "'>" + F.esc(x.symbol) + "</a></td><td class='num'>" +
                quoteRow(x.quote) + "</td><td class='num " + F.dirClass(x.quote.change_pct) + "'>" + F.fmtPct(x.quote.change_pct) +
                "</td><td class='num'><button class='btn sm' data-wl='" + F.esc(x.symbol) + "'>+ Watch</button></td></tr>";
            }).join("") + "</table>"
            : unavail("No symbols pass these filters right now.")) + "</div>";
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
  var CTABS = ["Overview", "Financials", "Valuation", "Estimates", "News", "Actions", "Holdings", "Charts", "Research"];
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
        renderHead(sym, rc.body, rq.body);
        renderTab(sym, tab);
      });
    });
    function renderHead(sym, prof, qenv) {
      var q = (qenv && qenv.data) || {}, p = (prof && prof.data) || {};
      var c = F.dirClass(q.change_pct);
      el("co-head").innerHTML = "<div class='row spread'><div><h1 style='margin:0'>" + F.esc(q.name || p.name || sym) +
        " <span class='mut' style='font-size:12px'>" + F.esc(sym) + "</span></h1>" +
        "<div class='sub' style='margin:4px 0 0'>" + F.esc(q.exchange || p.exchange || "—") + " · " +
        F.esc(q.instrument_type || p.instrument_type || "") + " · " + F.esc(q.currency || p.currency || "") + " · " +
        (qenv ? F.statusPill(qenv.status) : "") + " <span class='src'>src: yahoo</span></div></div>" +
        "<div style='text-align:right'><div style='font-family:var(--mono);font-size:22px;font-weight:700'>" + F.fmtNum(q.price) +
        " <span style='font-size:12px' class='mut'>" + F.esc(q.currency || "") + "</span></div>" +
        "<div class='" + c + "' style='font-family:var(--mono)'>" + F.fmtPct(q.change_pct) + " (" + F.fmtNum(q.change) + ")</div>" +
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
          '<table class="t"><tr><th>Metric</th><th class="num">Value</th><th>Kind</th></tr>' +
          row("Price", q && q.price !== undefined ? F.fmtNum(q.price) + " " + (q.currency || "") : "—", F.statusPill("delayed")) +
          row("Market cap", r.MarketCapitalization, F.statusPill("live")) +
          row("P/E (TTM)", r.PERatio, F.statusPill("live")) +
          row("Forward P/E", r.ForwardPE, F.statusPill("live")) +
          row("P/B", r.PriceToBookRatio, F.statusPill("live")) +
          row("EV/Revenue", r.EVToRevenue, F.statusPill("live")) +
          row("EV/EBITDA", r.EVToEBITDA, F.statusPill("live")) +
          row("PEG", r.PEGRatio, F.statusPill("live")) +
          row("Dividend yield", r.DividendYield, F.statusPill("live")) +
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
  function tCharts(sym, b, range, interval) {
    b.innerHTML = "<div class='row' id='ch-ranges'>" +
      ["1D", "5D", "1M", "3M", "6M", "1Y", "5Y", "MAX"].map(function (x) {
        return "<button class='btn sm" + (x === range ? " primary" : "") + "' data-r='" + x + "'>" + x + "</button>";
      }).join("") + "</div><div class='card' style='margin-top:10px'><canvas class='chart' id='ch-c'></canvas>" +
      "<div class='ch-legend'><span><i style='color:#2fbf71'>—</i> price</span><span><i style='color:#4da3ff'>—</i> SMA20</span>" +
      "<span><i style='color:#e0a63c'>—</i> SMA50</span><span id='ch-meta'></span></div></div>";
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
      el("ch-meta").textContent = "n=" + d.bars.length + " · " + d.interval + " · delayed · yahoo · " + d.currency;
    });
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
    view().innerHTML = "<h1>Watchlist</h1><div class='sub'>Persisted server-side (SQLite). Prices: delayed Yahoo.</div>" +
      "<div class='card'><div class='row'><input id='w-s' class='in' placeholder='Add symbol e.g. TCS.NS' style='flex:1;min-width:200px'>" +
      "<button class='btn primary' id='w-add'>Add</button></div><div id='w-t' style='margin-top:10px'>" + skel(5) + "</div></div>";
    el("w-add").onclick = function () { var s = el("w-s").value.trim(); if (s) addWatch(s.toUpperCase()); };
    function load() {
      API.get("watchlist").then(function (r) {
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
    load();
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
      el("n-out").innerHTML = skel(5);
      API.get("news", { symbol: el("n-s").value.trim(), topic: el("n-t").value.trim(), limit: 25 }).then(function (r) {
        var d = r.body && r.body.data;
        el("n-out").innerHTML = (d ? d.items.map(newsItem).join("") : unavail((r.body && r.body.message) || "News unavailable.")) + srcLine(r.body);
      });
    }
    el("n-go").onclick = go; go();
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
  function needProviderPage(title, what, how) {
    view().innerHTML = "<h1>" + title + "</h1><div class='card'><h3>" + F.statusPill("unavailable") + " Provider not configured</h3>" +
      "<p class='mut'>" + what + "</p><p class='mut'>" + how + "</p>" +
      "<p class='mut'>Track these manually in the meantime: open a company → Research tab → add a note under <span class='sect-tag'>catalysts</span>.</p></div>";
  }
  function pIPOs() {
    needProviderPage("IPOs",
      "A live IPO calendar (issue size, price band, fresh issue vs OFS, dates, prospectus extraction) needs an IPO feed or uploaded DRHP/RHP documents.",
      "No IPO data is synthesised. Document ingestion (parse → chunk → cite) lands with the RAG pipeline; until then this section stays explicit.");
  }
  function pEarnings() {
    view().innerHTML = "<h1>Earnings</h1><div class='sub'>Exchange-reported dividends &amp; splits for a symbol (yahoo events). Earnings dates need an estimates feed.</div>" +
      "<div class='card'><div class='row'><input id='e-s' class='in' placeholder='Symbol e.g. RELIANCE.NS'><button class='btn primary' id='e-go'>Load</button></div>" +
      "<div id='e-out' style='margin-top:10px'></div></div>";
    el("e-go").onclick = function () {
      var s = el("e-s").value.trim().toUpperCase();
      if (!s) return;
      location.hash = "#/company/" + encodeURIComponent(s) + "/Actions";
    };
  }
  function pMacro() {
    view().innerHTML = "<h1>Macro</h1><div class='sub'>Index-level snapshot from delayed quotes. Economic indicators need a macro feed.</div><div id='mc-out' class='card'>" + skel(5) + "</div>";
    API.get("market-overview").then(function (r) {
      var items = ((r.body && r.body.items) || []).filter(function (i) { return i.symbol.charAt(0) === "^"; });
      el("mc-out").innerHTML = items.length ? '<table class="t"><tr><th>Index</th><th>Name</th><th class="num">Level</th><th class="num">Δ%</th></tr>' +
        items.map(function (i) {
          var q = i.quote || {};
          return "<tr><td>" + F.esc(i.symbol) + "</td><td>" + F.esc(q.name || "—") + "</td><td class='num'>" + F.fmtNum(q.price) +
            "</td><td class='num " + F.dirClass(q.change_pct) + "'>" + F.fmtPct(q.change_pct) + "</td></tr>";
        }).join("") + "</table><div class='src'>source: yahoo · delayed</div>" : unavail("Index data unavailable.");
    });
  }
  function pSettings() {
    view().innerHTML = "<h1>Settings</h1><div class='sub'>Provider wiring &amp; data transparency</div>" +
      "<div class='grid g2'><div class='card'><h3>Providers</h3><table class='t' id='s-prov'></table></div>" +
      "<div class='card'><h3>Environment</h3><div class='src'>ALPHA_VANTAGE_API_KEY / FUNDAMENTALS_API_KEY — optional, server-side only, enables statements + ratios.<br><br>" +
      "TERMINAL_DB — sqlite path (default ./terminal-data/terminal.db).<br><br>No key is ever shipped to the browser. Validate input; external content is escaped before render.</div>" +
      "<h3 style='margin-top:12px'>Legend</h3><div class='row'>" + F.statusPill("live") + F.statusPill("delayed") + F.statusPill("calculated") + F.statusPill("ai") + F.statusPill("unavailable") + "</div></div></div>";
    Promise.all([API.get("quote", { symbol: "AAPL" }), API.get("ratios", { symbol: "AAPL" }), API.get("news", { limit: 1 })]).then(function (x) {
      el("s-prov").innerHTML = "<tr><th>Provider</th><th>Status</th></tr>" +
        "<tr><td>market-data (yahoo)</td><td>" + F.statusPill(x[0].body.status) + "</td></tr>" +
        "<tr><td>fundamentals (alphavantage)</td><td>" + F.statusPill(x[1].body.status) + "</td></tr>" +
        "<tr><td>news (yahoo-rss)</td><td>" + F.statusPill(x[2].body.status) + "</td></tr>" +
        "<tr><td>estimates</td><td>" + F.statusPill("unavailable") + "</td></tr>";
    });
  }

  window.FT_PAGES = {
    init, pDashboard, pMarkets, pScreener, pCompanies, pCompany, pWatchlist,
    pPortfolio, pNews, pResearch, pCompare, pIPOs, pEarnings, pMacro, pSettings, toast,
  };
})();
