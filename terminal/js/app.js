/* Router, nav, global search, clock. Hash routes: #/route + #/company/SYM/Tab */
(function () {
  "use strict";
  var NAV = [
    ["dashboard", "Dashboard", "⬡"], ["markets", "Markets", "◈"],
    ["companies", "Companies", "◎"], ["screener", "Screener", "⊟"],
    ["compare", "Compare", "⇄"], ["watchlist", "Watchlist", "★"],
    ["portfolio", "Portfolio", "◳"], ["research", "Research", "✦"],
    ["earnings", "Earnings", "◐"], ["actions", "Actions", "⬔"],
    ["ipos", "IPOs", "⬑"], ["news", "News", "▤"],
    ["macro", "Macro", "⊕"], ["status", "Data Status", "◔"],
    ["settings", "Settings", "⚙"],
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
    else if (parts[0] === "welcome") P.pWelcome();
    else if (parts[0] === "mf" && parts[1] && P.pMF) P.pMF(parts[1]);
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
    else if (parts[0] === "status" && P.pStatus) P.pStatus();
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
        "<span class='tk'>" + F.esc(x.symbol) + "</span> " + F.typeBadge(x.type) + " " + mktTag(x.symbol, x.exchange) +
        "<br><span class='tk'>" + F.esc([x.exchange, x.sector || x.type].filter(Boolean).join(" · ") || "—") +
        "</span></span></span><span class='px' data-qpx='" + F.esc(x.symbol) + "'>…</span></div>";
    }
    /* India vs US vs Global bucket, mirrored from the server classifier:
       separate categories, never mixed in one bucket. */
    function mktTag(symbol, exchange) {
      var s = String(symbol || "").toUpperCase(), e = String(exchange || "").toUpperCase();
      var id = "Global", label = "Global";
      if (s.indexOf("=") >= 0 || /-USD$/.test(s)) { id = "Global"; label = "Global"; }
      else if (/\.NS$|\.BO$/.test(s) || /NSE|BSE/.test(e) || s === "^NSEI" || s === "^NSEBANK" || s === "^BSESN" || s.indexOf("^CNX") === 0) { id = "IN"; label = "India"; }
      else if (/NASDAQ|NYSE|AMEX|ARCA|BATS/.test(e)) { id = "US"; label = "US"; }
      var cls = id === "IN" ? "cx-q-rep" : (id === "US" ? "cx-q-calc" : "cx-q-na");
      return "<span class='cx-q " + cls + "'>" + label + "</span>";
    }
    function mfRow(x, i) {
      var F = window.FT_FMT;
      return '<div class="sr" role="option" data-i="m' + i + '"><span><span class="nm">' + F.esc(x.name || x.symbol) + "</span> " +
        "<span class='tk'>MF · " + F.esc(String(x.code || "")) + "</span> <span class='cx-q cx-q-rep'>India</span></span><span class='px'>→</span></div>";
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
          var mfMatches = [];
          var mfCache = null;
          try {
            ipoCache = JSON.parse(sessionStorage.getItem("ft-ipo") || "null");
            mfCache = JSON.parse(sessionStorage.getItem("ft-mf") || "null");
          } catch (e) { ipoCache = null; mfCache = null; }
          function fxRow(f, i) {
            return '<div class="sr" role="option" data-i="f' + i + '"><span><span class="nm">' + F.esc(f[0]) + "</span> " +
              "<span class='tk'>feature</span></span><span class='px'>→</span></div>";
          }
          function ipoRow(x, i) {
            return '<div class="sr" role="option" data-i="p' + i + '"><span><span class="nm">' + F.esc(x.company_name || x.name || x.symbol || "IPO") + "</span> " +
              "<span class='tk'>IPO · " + F.esc(x._bucket || x.status || "") + "</span></span><span class='px'>→</span></div>";
          }
          function render() {
            var html = "";
            if (fxMatches.length) {
              html += "<div class='src' style='padding:6px 12px'>Features</div>" +
                fxMatches.map(function (x, i) { return fxRow(x, i); }).join("");
            }
            if (ipoMatches.length) {
              html += "<div class='src' style='padding:6px 12px'>IPOS</div>" +
                ipoMatches.map(function (x, i) { return ipoRow(x, i); }).join("");
            }
            if (mfMatches.length) {
              html += "<div class='src' style='padding:6px 12px'>Mutual funds</div>" +
                mfMatches.map(function (x, i) { return mfRow(x, i); }).join("");
            }
            if (wlMatches.length) {
              html += "<div class='src' style='padding:6px 12px'>In watchlist</div>" +
                wlMatches.map(function (x, i) { return row(x, "w" + i); }).join("");
            }
            html += items.map(function (x, i) { return row(x, i); }).join("");
            box.innerHTML = html || '<div class="sr"><span>No matches</span></div>';
            box.classList.remove("hidden");
            // unified keyboard + click model across every section
            var keyNav = [];
            fxMatches.forEach(function (f) {
              keyNav.push({ el: null, run: function () { hide(); inp.value = ""; location.hash = f[1]; } });
            });
            ipoMatches.forEach(function () {
              keyNav.push({ el: null, run: function () { hide(); inp.value = ""; location.hash = "#/ipos"; } });
            });
            mfMatches.forEach(function (m) {
              keyNav.push({ el: null, run: function () { hide(); inp.value = ""; location.hash = "#/mf/" + encodeURIComponent(m.code); } });
            });
            var all = fxMatches.concat(ipoMatches, mfMatches, wlMatches, items);
            box.querySelectorAll(".sr").forEach(function (d, di) {
              if (keyNav[di]) keyNav[di].el = d;
              d.onclick = function () {
                var k = String(d.getAttribute("data-i"));
                if (k.charAt(0) === "f") {
                  var f = fxMatches[Number(k.slice(1))];
                  hide(); inp.value = ""; location.hash = f[1]; return;
                }
                if (k.charAt(0) === "p") { hide(); inp.value = ""; location.hash = "#/ipos"; return; }
                if (k.charAt(0) === "m") {
                  var m = mfMatches[Number(k.slice(1))];
                  hide(); inp.value = ""; location.hash = "#/mf/" + encodeURIComponent(m.code); return;
                }
                var it;
                if (k.charAt(0) === "w") it = all[fxMatches.length + ipoMatches.length + mfMatches.length + Number(k.slice(1))];
                else it = all[fxMatches.length + ipoMatches.length + mfMatches.length + wlMatches.length + Number(k)];
                go(it.symbol, it.name);
              };
            });
            keyNav = keyNav.concat(wlMatches.concat(items).map(function (it) {
              return { el: null, run: function () { go(it.symbol, it.name); } };
            }));
            box.querySelectorAll(".sr").forEach(function (d, di) {
              if (keyNav[di]) keyNav[di].el = d;
            });
            active = -1;
            box._keyNav = keyNav;
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
          /* Mutual fund matches (session-cached 10 min, free mfapi.in). */
          function mfFilter(rows) {
            mfMatches = (rows || []).slice(0, 3);
            if (mfMatches.length && !box.classList.contains("hidden")) render();
          }
          if (mfCache && Date.now() - (mfCache.at || 0) < 600000 && mfCache.q === ql) {
            mfFilter(mfCache.rows);
          } else {
            window.FT_API.get("mf/search", { q: q }).then(function (mr) {
              var rows = (((mr.body || {}).data || {}).results) || [];
              try { sessionStorage.setItem("ft-mf", JSON.stringify({ at: Date.now(), q: ql, rows: rows.slice(0, 10) })); } catch (e) { /* ignore */ }
              mfFilter(rows);
            }).catch(function () { /* search works without MF leg */ });
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
      if (e.key === "Enter" && active >= 0) {
        var nav = box._keyNav || [];
        if (nav[active]) { nav[active].run(); return; }
        if (items[active]) {
          var it = items[active];
          go(it.symbol, it.name);
        }
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
    /* Neutral entry point to the Data status page (#/status), where feed
       freshness (delayed vs live) is disclosed per provider. The pill
       itself carries no timeliness claim. */
    var pill = document.getElementById("data-status");
    function paint(alert) {
      pill.className = "pill" + (alert ? " pill-bad" : "");
      pill.innerHTML = "";
      var a = document.createElement("a");
      a.href = "#/status";
      a.textContent = alert ? "DATA · CHECK" : "DATA STATUS";
      a.style.cssText = "color:inherit;text-decoration:none";
      a.setAttribute("aria-label", "Open Data status page");
      pill.appendChild(a);
      pill.title = "Feed freshness per provider — see Data status";
    }
    window.FT_API.get("providers").then(function (r) {
      var list = ((r.body || {}).providers) || [];
      var alert = list.some(function (p) {
        return p.health && (p.health.state === "cooling" ||
          (p.health.consecutive_errors || 0) > 0);
      });
      paint(alert);
    }).catch(function () { paint(false); });
  }
  function profileChip() {
    /* Local workspace label only (this device). No account, no auth. */
    function paint() {
      var nm = "";
      try { nm = localStorage.getItem("fi-profile") || ""; } catch (e) { /* ignore */ }
      document.getElementById("profile-name").textContent = nm || "Profile";
      document.getElementById("profile-initial").textContent = (nm || "–").charAt(0).toUpperCase();
    }
    paint();
    document.getElementById("top-profile").onclick = function () { location.hash = "#/settings"; };
    window.FT_PROFILE = { paint: paint };
  }
  function themeToggle() {
    var b = document.getElementById("top-theme");
    if (!b) return;
    function label() {
      var dark = document.body.dataset.theme !== "light";
      b.textContent = dark ? "Light" : "Dark";
    }
    label();
    b.onclick = function () {
      var next = document.body.dataset.theme === "light" ? "dark" : "light";
      document.body.dataset.theme = next;
      try { localStorage.setItem("ft-theme", next); } catch (e) { /* ignore */ }
      label();
    };
    /* keep label in sync if theme changes elsewhere */
    new MutationObserver(label).observe(document.body, { attributes: true, attributeFilter: ["data-theme"] });
  }
  window.addEventListener("hashchange", route);
  document.addEventListener("DOMContentLoaded", function () {
    window.FT_PAGES.init();
    buildNav(); bindSearch(); clock(); providerPill(); profileChip(); themeToggle();
    document.getElementById("top-refresh").onclick = function () { route(); };
    if (!location.hash) {
      var seen = null;
      try { seen = localStorage.getItem("fi-seen"); } catch (e) { /* ignore */ }
      location.hash = seen ? "#/dashboard" : "#/welcome";
    }
    route();
  });
})();
