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
    else if (parts[0] === "actions") P.pCompanies();
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
    var t = null, items = [], active = -1;
    function hide() { box.classList.add("hidden"); box.innerHTML = ""; active = -1; items = []; }
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
          items = b.data.results || [];
          box.innerHTML = items.map(function (x, i) {
            return '<div class="sr" data-i="' + i + '"><span><b>' + F.esc(x.symbol) + "</b> · " + F.esc(x.name || "") +
              "</span><small>" + F.esc(x.exchange || "") + "</small></div>";
          }).join("");
          box.classList.remove("hidden");
          box.querySelectorAll(".sr").forEach(function (d) {
            d.onclick = function () {
              var it = items[Number(d.getAttribute("data-i"))];
              hide(); inp.value = "";
              location.hash = "#/company/" + encodeURIComponent(it.symbol);
            };
          });
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
        hide(); var it = items[active]; inp.value = "";
        location.hash = "#/company/" + encodeURIComponent(it.symbol);
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
  window.addEventListener("hashchange", route);
  document.addEventListener("DOMContentLoaded", function () {
    window.FT_PAGES.init();
    buildNav(); bindSearch(); clock();
    // Corp-actions nav prompts for a symbol
    document.querySelector('[data-r="actions"]').addEventListener("click", function (e) {
      e.preventDefault();
      var s = prompt("Symbol for corporate actions (e.g. RELIANCE.NS)?", "RELIANCE.NS");
      if (s) location.hash = "#/company/" + encodeURIComponent(s.trim().toUpperCase()) + "/Actions";
    });
    if (!location.hash) location.hash = "#/dashboard";
    route();
  });
})();
