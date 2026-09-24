/* Router, nav, global search, clock. Hash routes: #/route + #/company/SYM/Tab */
(function () {
  "use strict";
  var NAV = [
    ["dashboard", "Dashboard", "▦"], ["markets", "Markets", "◈"],
    ["screener", "Screener", "▼"], ["companies", "Companies", "◎"],
    ["compare", "Compare", "⇄"], ["watchlist", "Watchlist", "★"],
    ["portfolio", "Portfolio", "⬣"], ["news", "News", "📰"],
    ["research", "Research", "✎"], ["ipos", "IPOs", "◉"],
    ["earnings", "Earnings", "◐"], ["actions", "Corp Actions", "⬔"],
    ["macro", "Macro", "🌐"], ["settings", "Settings", "⚙"],
  ];
  function route() {
    var h = (location.hash || "#/dashboard").replace(/^#\/?/, "");
    var parts = h.split("/").map(decodeURIComponent);
    var P = window.FT_PAGES;
    if (P.clearTimers) P.clearTimers(); // stop previous view's polling
    document.querySelectorAll("#sidenav a").forEach(function (a) {
      a.classList.toggle("on", a.getAttribute("data-r") === parts[0]);
    });
    window.scrollTo(0, 0);
    document.getElementById("view").scrollTop = 0;
    if (parts[0] === "company" && parts[1]) P.pCompany(parts[1], parts[2] || "Overview");
    else if (parts[0] === "markets") P.pMarkets();
    else if (parts[0] === "screener") P.pScreener();
    else if (parts[0] === "companies") P.pCompanies();
    else if (parts[0] === "compare") P.pCompare();
    else if (parts[0] === "watchlist") P.pWatchlist();
    else if (parts[0] === "portfolio") P.pPortfolio();
    else if (parts[0] === "news") P.pNews();
    else if (parts[0] === "research") P.pResearch();
    else if (parts[0] === "ipos") P.pIPOs();
    else if (parts[0] === "earnings") P.pEarnings();
    else if (parts[0] === "actions") P.pActions();
    else if (parts[0] === "macro") P.pMacro();
    else if (parts[0] === "settings") P.pSettings();
    else P.pDashboard();
  }
  function buildNav() {
    var n = document.getElementById("sidenav");
    n.innerHTML = NAV.map(function (x) {
      return '<a data-r="' + x[0] + '" href="#/' + x[0] + '"><span class="nav-ic">' + x[2] + '</span><span class="lbl">' + x[1] + "</span></a>";
    }).join("");
  }
  function bindSearch() {
    var inp = document.getElementById("global-search"), box = document.getElementById("search-results");
    var t = null, items = [], active = -1, wlCache = null, wlAt = 0;
    function hide() { box.classList.add("hidden"); box.innerHTML = ""; active = -1; items = []; }
    function recents() {
      try { return JSON.parse(localStorage.getItem("ft-recent") || "[]"); }
      catch (e) { return []; }
    }
    function remember(sym, name) {
      try {
        var r = recents().filter(function (x) { return x.s !== sym; });
        r.unshift({ s: sym, n: name || "" });
        localStorage.setItem("ft-recent", JSON.stringify(r.slice(0, 6)));
      } catch (e) { /* private mode: ignore */ }
    }
    function go(sym, name) {
      hide(); inp.value = ""; remember(sym, name);
      location.hash = "#/company/" + encodeURIComponent(sym);
    }
    function row(x, i) {
      var F = window.FT_FMT;
      return '<div class="sr" role="option" data-i="' + i + '"><span style="display:flex;gap:10px;align-items:center">' +
        F.logo(x.symbol, x.name, 30) + '<span><span class="nm">' + F.esc(x.name || x.symbol) + "</span> " +
        "<span class='tk'>" + F.esc(x.symbol) + "</span> " + F.typeBadge(x.type) +
        "<br><span class='tk'>" + F.esc([x.exchange, x.sector || x.type].filter(Boolean).join(" · ") || "—") +
        "</span></span></span><span class='px' data-qpx='" + F.esc(x.symbol) + "'>…</span></div>";
    }
    inp.addEventListener("focus", function () {
      if (inp.value.trim() || box.children.length) return;
      var r = recents();
      if (!r.length) return;
      var F = window.FT_FMT;
      items = r.map(function (x) { return { symbol: x.s, name: x.n }; });
      box.innerHTML = "<div class='src' style='padding:6px 12px'>RECENT</div>" + items.map(row).join("");
      box.classList.remove("hidden");
      bindRows();
    });
    function bindRows() {
      box.querySelectorAll(".sr").forEach(function (d) {
        d.onclick = function () {
          var it = items[Number(d.getAttribute("data-i"))];
          go(it.symbol, it.name);
        };
      });
    }
    inp.addEventListener("input", function () {
      clearTimeout(t);
      var q = inp.value.trim();
      if (q.length < 2) { hide(); return; }
      t = setTimeout(function () {
        window.FT_API.get("search", { q: q }).then(function (r) {
          var F = window.FT_FMT, b = r.body;
          if (!b || !b.data) {
            box.innerHTML = '<div class="sr"><span>No matches — ' + F.esc((b && b.message) || "") + "</span></div>";
            box.classList.remove("hidden"); items = []; return;
          }
          var ql = q.toUpperCase();
          var res = (b.data.results || []).slice(0, 10);
          // exact ticker matches first, then name prefix, then rest
          res.sort(function (a, c) {
            function score(x) {
              var s = String(x.symbol || "").toUpperCase(), n = String(x.name || "").toUpperCase();
              if (s === ql) return 0;
              if (s === ql + ".NS" || s === ql + ".BO") return 1;
              if (n.indexOf(ql) === 0) return 2;
              if (s.indexOf(ql) === 0) return 3;
              return 4;
            }
            return score(a) - score(c);
          });
          items = res.slice(0, 8);
          var wlMatches = [];
          var FX = [["Screener", "#/screener"], ["Compare", "#/compare"], ["Watchlist", "#/watchlist"],
            ["Portfolio", "#/portfolio"], ["Market news", "#/news"], ["IPO dashboard", "#/ipos"],
            ["Earnings calendar", "#/earnings"], ["Corporate actions", "#/actions"], ["Macro", "#/macro"],
            ["Markets", "#/markets"], ["Research notes", "#/research"], ["Settings", "#/settings"]];
          var fxMatches = FX.filter(function (f) { return f[0].toUpperCase().indexOf(ql) >= 0; }).slice(0, 2);
          var ipoMatches = [], ipoAt = 0, ipoCache = null;
          try { ipoCache = JSON.parse(sessionStorage.getItem("ft-ipo") || "null"); } catch (e) { ipoCache = null; }
          function fxRow(f, i) {
            return '<div class="sr" role="option" data-i="f' + i + '"><span><span class="nm">' + F.esc(f[0]) + "</span> " +
              "<span class='tk'>feature</span></span><span class='px'>→</span></div>";
          }
          function ipoRow(x, i) {
            return '<div class="sr" role="option" data-i="p' + i + '"><span><span class="nm">' + F.esc(x.company_name || x.name || "?") + "</span> " +
              "<span class='tk'>IPO · " + F.esc(x._bucket || x.status || "") + "</span></span><span class='px'>→</span></div>";
          }
          function render() {
            var html = "";
            if (fxMatches.length) {
              html += "<div class='src' style='padding:6px 12px'>FEATURES</div>" +
                fxMatches.map(function (x, i) { return fxRow(x, i); }).join("");
            }
            if (ipoMatches.length) {
              html += "<div class='src' style='padding:6px 12px'>IPOS</div>" +
                ipoMatches.map(function (x, i) { return ipoRow(x, i); }).join("");
            }
            if (wlMatches.length) {
              html += "<div class='src' style='padding:6px 12px'>IN WATCHLIST</div>" +
                wlMatches.map(function (x, i) { return row(x, "w" + i); }).join("");
            }
            html += items.map(function (x, i) { return row(x, i); }).join("");
            box.innerHTML = html || '<div class="sr"><span>No matches</span></div>';
            box.classList.remove("hidden");
            // merge watchlist rows into clickable items
            var all = fxMatches.concat(ipoMatches, wlMatches, items);
            box.querySelectorAll(".sr").forEach(function (d) {
              d.onclick = function () {
                var k = String(d.getAttribute("data-i"));
                if (k.charAt(0) === "f") {
                  var f = fxMatches[Number(k.slice(1))];
                  hide(); inp.value = ""; location.hash = f[1]; return;
                }
                if (k.charAt(0) === "p") { hide(); inp.value = ""; location.hash = "#/ipos"; return; }
                var it;
                if (k.charAt(0) === "w") it = all[fxMatches.length + ipoMatches.length + Number(k.slice(1))];
                else it = all[fxMatches.length + ipoMatches.length + wlMatches.length + Number(k)];
                go(it.symbol, it.name);
              };
            });
            var allItems = wlMatches.concat(items);
            allItems.forEach(function (x) {
              window.FT_API.get("quote", { symbol: x.symbol }).then(function (r) {
                var qq = r.body && r.body.data, cell = box.querySelector("[data-qpx='" + x.symbol.replace(/'/g, "") + "']");
                if (!qq || !cell) return;
                var c = F.dirClass(qq.change_pct);
                cell.innerHTML = F.fmtNum(qq.price) + " <span class='" + c + "'>" + F.fmtPct(qq.change_pct) + "</span>";
              });
            });
            items = allItems;
          }
          if (Date.now() - wlAt > 60000 || !wlCache) {
            window.FT_API.get("watchlist").then(function (wr) {
              wlCache = (wr.body && wr.body.items) || []; wlAt = Date.now();
              wlMatches = wlCache.filter(function (w) {
                return (w.symbol + " " + (w.name || "")).toUpperCase().indexOf(ql) >= 0;
              }).slice(0, 3);
              render();
            });
          } else {
            wlMatches = (wlCache || []).filter(function (w) {
              return (w.symbol + " " + (w.name || "")).toUpperCase().indexOf(ql) >= 0;
            }).slice(0, 3);
            render();
          }
          /* IPO name matches (cached hourly in session). */
          function ipoFilter(rows) {
            ipoMatches = (rows || []).filter(function (w) {
              return ((w.company_name || w.name || "") + " " + (w.symbol || "")).toUpperCase().indexOf(ql) >= 0;
            }).slice(0, 3);
            if (ipoMatches.length && !box.classList.contains("hidden")) render();
          }
          if (ipoCache && Date.now() - (ipoCache.at || 0) < 3600000) {
            ipoFilter(ipoCache.rows);
          } else {
            window.FT_API.get("ipo").then(function (ir) {
              var rows = (((ir.body || {}).data || {}).rows) || [];
              try { sessionStorage.setItem("ft-ipo", JSON.stringify({ at: Date.now(), rows: rows.slice(0, 200) })); } catch (e) { /* ignore */ }
              ipoFilter(rows);
            }).catch(function () { /* search works without IPO leg */ });
          }
        });
      }, 220);
    });
    inp.addEventListener("keydown", function (e) {
      var rows = box.querySelectorAll(".sr");
      if (e.key === "Escape") { hide(); inp.blur(); }
      if (!rows.length) return;
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        active = e.key === "ArrowDown" ? Math.min(active + 1, rows.length - 1) : Math.max(active - 1, 0);
        rows.forEach(function (r, i) { r.classList.toggle("active", i === active); });
      }
      if (e.key === "Enter" && active >= 0 && items[active]) {
        var it = items[active];
        go(it.symbol, it.name);
      }
    });
    document.addEventListener("click", function (e) {
      if (!document.querySelector(".search-wrap").contains(e.target)) hide();
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "/" && document.activeElement !== inp && !/INPUT|TEXTAREA/.test(document.activeElement.tagName)) {
        e.preventDefault(); inp.focus();
      }
    });
  }
  function clock() {
    var c = document.getElementById("clock");
    function tick() {
      c.textContent = new Date().toISOString().replace("T", " ").slice(0, 19) + "Z";
    }
    tick(); setInterval(tick, 1000);
  }
  function providerPill() {
    var pill = document.getElementById("data-status");
    window.FT_API.get("providers").then(function (r) {
      var list = ((r.body || {}).providers) || [];
      var yahoo = list.filter(function (p) { return p.id === "yahoo"; })[0] || {};
      var td = list.filter(function (p) { return p.id === "twelvedata"; })[0] || {};
      var av = list.filter(function (p) { return p.id === "alphavantage"; })[0] || {};
      var ia = list.filter(function (p) { return p.id === "indian-api"; })[0] || {};
      var legs = "YAHOO" + (td.key_configured ? "+TD" : "") + (av.key_configured ? "+AV" : "") + (ia.key_configured ? "+IA" : "");
      if (yahoo.state === "cooling") {
        pill.className = "pill pill-delayed";
        pill.textContent = "AUTO · YAHOO COOLING · " + legs;
      } else {
        pill.className = "pill pill-live";
        pill.textContent = "AUTO · " + legs;
      }
      pill.title = "Free-automatic chain: Yahoo → Twelve Data → Alpha Vantage → unavailable";
    });
  }
  window.addEventListener("hashchange", route);
  document.addEventListener("DOMContentLoaded", function () {
    window.FT_PAGES.init();
    buildNav(); bindSearch(); clock(); providerPill();
    document.getElementById("top-refresh").onclick = function () { route(); };
    if (!location.hash) location.hash = "#/dashboard";
    route();
  });
})();
