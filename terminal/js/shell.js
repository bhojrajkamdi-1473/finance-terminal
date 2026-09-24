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
        host.innerHTML = "<div class='cx-empty'><b>Grey market premium</b>" +
          "<p><span class='cx-q cx-q-warn'>UNOFFICIAL GREY MARKET PREMIUM</span></p>" +
          "<p>" + esc((gmp && gmp.message) || "No verified GMP source configured.") + "</p>" +
          "<p class='why'>Rules: source + timestamp required · estimated listing = upper band + GMP (" +
          "INDICATIVE ONLY) · disagreeing sources shown separately (GMP DISCREPANCY), never averaged.</p></div>";
        return;
      }
      if (tab === "Subscription") {
        host.innerHTML = "<div class='cx-empty'><b>Subscription</b><p>" +
          esc((sub && sub.message) || "No subscription feed configured.") +
          "</p><p class='why'>QIB / NII / Retail / Employee splits appear only from exchange-published figures.</p></div>";
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
        host.innerHTML = "<section class='cx-sec'><h2>" + esc(prof.name || sym) + " — issue file</h2>" +
          "<p class='cx-note'>" + esc((prof.description || "").slice(0, 400)) + "</p>" +
          "<dl class='cx-facts'><div><dt>Sector</dt><dd>" + esc(prof.sector || "—") + "</dd></div>" +
          "<div><dt>P/E</dt><dd>" + esc((val.metrics && val.metrics.pe && val.metrics.pe.value) || "—") + "</dd></div>" +
          "<div><dt>Market cap</dt><dd>" + esc((val.metrics && val.metrics.market_cap && val.metrics.market_cap.value) || "—") + "</dd></div></dl>" +
          "<div class='cx-empty' style='margin-top:8px'><b>Grey market premium</b>" +
          "<p><span class='cx-q cx-q-warn'>UNOFFICIAL GREY MARKET PREMIUM</span></p>" +
          "<p>" + esc(((b.gmp || {}).message) || "No verified GMP source.") + "</p></div>" +
          "<div class='cx-note' style='margin-top:6px'>Structured analysis inputs only — never apply/avoid advice. " +
          "Subscription: " + esc(((b.subscription || {}).message) || "unavailable") + "</div></section>";
        host.scrollIntoView();
      });
    }
  }
  if (window.FT_PAGES) window.FT_PAGES.pIPOs = pIPOs;
  function theme() {
    try {
      var q = (location.search || "").match(/theme=(light|dark)/);
      var t = q ? q[1] : (localStorage.getItem("ft-theme") || "dark");
      document.body.dataset.theme = (t === "light") ? "light" : "dark";
    } catch (e) { document.body.dataset.theme = "dark"; }
  }
  function boot() { theme(); sectionize(); strip(); }
  document.addEventListener("DOMContentLoaded", function () { setTimeout(boot, 400); });
  setInterval(boot, 2500);
  window.FT_SHELL = { boot: boot };
})();
