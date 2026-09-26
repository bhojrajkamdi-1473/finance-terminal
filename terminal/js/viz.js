/* FT viz library: KPI strips, heatmaps, bars, rankings, provenance.
   HARD RULE: missing values are omitted, never rendered as placeholders.
   hasV() is the single gate every component uses. */
(function () {
  "use strict";
  function esc(s) {
    return (window.FT_FMT ? window.FT_FMT.esc(String(s === null || s === undefined ? "" : s)) : String(s));
  }
  function hasV(v) {
    if (v === null || v === undefined) return false;
    if (typeof v === "number") return !isNaN(v);
    var s = String(v).trim();
    return s !== "" && !/^(none|null|undefined|nan|-|n\/a|—)$/i.test(s);
  }
  function dir(v) { return window.FT_FMT.dirClass(v); }
  /* KPI strip: cells {label, value, sub, tip, mark("stale"|"calc"), info}.
     Null values are dropped; the strip reflows. Returns "" when empty. */
  function kpiStrip(cells, opts) {
    opts = opts || {};
    var F = window.FT_FMT;
    var live = (cells || []).filter(function (c) { return c && hasV(c.value); });
    if (!live.length) return "";
    return '<div class="kstrip' + (opts.big ? " big" : "") + '">' + live.map(function (c) {
      var mk = c.mark === "stale" ? F.mark("stale", c.info)
        : c.mark === "calc" ? F.mark("calc", c.info) : "";
      return '<div class="kpi"' + (c.tip ? " title='" + esc(c.tip) + "'" : "") + ">" +
        '<div class="k-l">' + esc(c.label || "") + "</div>" +
        '<div class="k-v">' + c.value + mk + "</div>" +
        (hasV(c.sub) ? '<div class="k-s">' + c.sub + "</div>" : "") + "</div>";
    }).join("") + "</div>";
  }
  /* MetricTile (master spec §3): white card, label → value + inline
     †/‡ mark → colored delta → full-width gradient sparkline.
     t = {label, value(html), delta(html, may be ""), spark:[closes]|null,
       up(bool), mark("stale"|"calc"|""), info{source,status,asOf},
       tip(triplet string), compact(bool)}. Spark omitted entirely when
     no history exists. */
  var tileN = 0;
  function metricTile(t) {
    t = t || {};
    if (!hasV(t.value) && !hasV(t.label)) return "";
    var F = window.FT_FMT;
    var mk = "";
    if (t.mark === "stale") mk = F.mark("stale", t.info);
    else if (t.mark === "calc") mk = F.mark("calc", t.info);
    var spark = "";
    if (t.spark && t.spark.length >= 2) {
      var up = t.up !== false;
      var col = up ? "var(--up)" : "var(--dn)";
      spark = '<svg class="tile-spark" viewBox="0 0 100 28" preserveAspectRatio="none" aria-hidden="true">' +
        '<defs><linearGradient id="tg' + (tileN++) + '" x1="0" y1="0" x2="0" y2="1">' +
        '<stop offset="0" stop-color="' + (up ? "#1a7f37" : "#c62828") + '" stop-opacity="0.25"/>' +
        '<stop offset="1" stop-color="' + (up ? "#1a7f37" : "#c62828") + '" stop-opacity="0"/></linearGradient></defs>' +
        '<path d="' + sparkPath(t.spark) + '" fill="none" stroke="' + col + '" stroke-width="1.6"/>' +
        '<path d="' + sparkPath(t.spark) + ' L 100 28 L 0 28 Z" fill="url(#tg' + (tileN - 1) + ')" stroke="none"/></svg>';
    }
    return '<div class="mtile' + (t.compact ? " compact" : "") + '"' +
      (t.tip ? ' title="' + esc(t.tip) + '"' : "") + ">" +
      '<div class="mt-l">' + esc(t.label || "") + "</div>" +
      '<div class="mt-v">' + t.value + mk + "</div>" +
      (hasV(t.delta) ? '<div class="mt-d">' + t.delta + "</div>" : "") + spark + "</div>";
  }
  function sparkPath(vals) {
    var lo = Math.min.apply(null, vals), hi = Math.max.apply(null, vals), sp = hi - lo || 1;
    return vals.map(function (v, i) {
      var x = (i / (vals.length - 1)) * 100, y = 26 - ((v - lo) / sp) * 24;
      return (i ? "L" : "M") + x.toFixed(1) + " " + y.toFixed(1);
    }).join(" ");
  }
  /* Heatmap: equal tiles (no fabricated weights), color intensity from
     value through a neutral midpoint. Tooltip carries detail. */
  function heatmap(items, opts) {
    opts = opts || {};
    var live = (items || []).filter(function (i) { return i && hasV(i.value) && !isNaN(Number(i.value)); });
    if (!live.length) return "";
    var mx = Math.max.apply(null, live.map(function (i) { return Math.abs(Number(i.value)); }).concat([0.5]));
    return '<div class="hmap">' + live.map(function (i) {
      var v = Number(i.value), t = Math.min(1, Math.abs(v) / mx);
      var bg = v >= 0
        ? "rgba(0,150,100," + (0.08 + 0.5 * t).toFixed(2) + ")"
        : "rgba(200,50,70," + (0.08 + 0.5 * t).toFixed(2) + ")";
      var tip = i.label + ": " + (opts.fmt ? opts.fmt(v) : v) +
        (hasV(i.sub) ? " · " + i.sub : "");
      return '<div class="htile" style="background:' + bg + '" title="' + esc(tip) + '" tabindex="0">' +
        '<b>' + esc(i.label) + "</b><span>" + (opts.fmt ? opts.fmt(v) : esc(String(v))) + "</span></div>";
    }).join("") + "</div>";
  }
  /* Horizontal bars: rows {label, value, max?, display?}. */
  function bars(rows, opts) {
    opts = opts || {};
    var live = (rows || []).filter(function (r) { return r && hasV(r.value) && !isNaN(Number(r.value)); });
    if (!live.length) return "";
    var mx = opts.max || Math.max.apply(null, live.map(function (r) { return Math.abs(Number(r.value)); }).concat([1]));
    return live.map(function (r) {
      var v = Number(r.value), w = Math.round(Math.abs(v) / mx * 100);
      var col = opts.color || (v >= 0 ? "var(--up)" : "var(--dn)");
      return '<div class="bar-row"><span>' + esc(r.label) + "</span>" +
        '<span class="tr"><span class="fl" style="display:block;width:' + w + "%;background:" + col + '"></span></span>' +
        "<b class='" + dir(v) + "'>" + (r.display || esc(String(v))) + "</b></div>";
    }).join("");
  }
  /* Single provenance line per section. Unknown parts are dropped;
     returns "" when nothing is known. */
  function srcLine(o) {
    o = o || {};
    var F = window.FT_FMT, parts = [];
    if (hasV(o.label)) parts.push(esc(o.label));
    else if (o.calculated) parts.push("Calculated");
    else parts.push("Data");
    if (hasV(o.source)) parts.push(esc(F.srcName(o.source)));
    if (hasV(o.period)) parts.push(esc(o.period));
    if (hasV(o.asOf)) {
      var d = String(o.asOf).slice(0, 10);
      if (/^\d{4}-\d{2}-\d{2}/.test(d)) parts.push(esc(d));
    }
    if (parts.length <= 1 && !hasV(o.source)) return "";
    var tip = [o.provider, o.asOf, o.status].filter(hasV).join(" · ");
    return '<div class="cx-prov"' + (tip ? " title='" + esc(tip) + "'" : "") + ">" + parts.join(" · ") + "</div>";
  }
  /* Feature-level empty state ONLY (entire feature down). Never per-metric. */
  function emptyFeature(title, why) {
    return "<div class='cx-empty'><b>" + esc(title) + "</b><p>" + esc(why || "This feature has no verified data source right now.") + "</p></div>";
  }
  /* Score gauge row (master spec §4): semi-circle red→yellow→green arc,
     centered score, colored pill tag below. g = {label, score(0-100),
     tag, note}. Omitted when score is absent — never a fabricated dial. */
  function gauge(g) {
    g = g || {};
    var s = Number(g.score);
    if (isNaN(s)) return "";
    s = Math.max(0, Math.min(100, Math.round(s)));
    var col = s >= 60 ? "var(--up)" : s >= 40 ? "var(--warn)" : "var(--dn)";
    var arc = Math.PI * (s / 100);
    var x2 = 50 + 40 * Math.cos(Math.PI - arc), y2 = 48 - 40 * Math.sin(Math.PI - arc);
    var large = s > 50 ? 1 : 0;
    return '<div class="gauge" title="' + esc(g.note || "") + '">' +
      '<svg viewBox="0 0 100 52" aria-hidden="true">' +
      '<path d="M 10 48 A 40 40 0 0 1 90 48" fill="none" stroke="var(--line-2)" stroke-width="9"/>' +
      '<path d="M 10 48 A 40 40 0 0 1 ' + x2.toFixed(1) + " " + y2.toFixed(1) +
      '" fill="none" stroke="' + col + '" stroke-width="9" stroke-linecap="round"/>' +
      '<text x="50" y="42" text-anchor="middle" font-size="17" font-weight="700" fill="var(--ink)">' + s + "</text></svg>" +
      '<div class="g-l">' + esc(g.label || "") + "</div>" +
      (g.tag ? '<div class="g-tag" style="color:' + col + '">' + esc(g.tag) + "</div>" : "") + "</div>";
  }
  /* Pros & cons (master spec §4): plain two-column bullets, green/red
     headings. items = [{t:"pro"|"con", text, cite}]. Every bullet cites
     its metric — no uncited claims. */
  function prosCons(items) {
    var pros = (items || []).filter(function (i) { return i && i.t === "pro" && hasV(i.text); });
    var cons = (items || []).filter(function (i) { return i && i.t === "con" && hasV(i.text); });
    if (!pros.length && !cons.length) return "";
    function li(i) {
      return "<li>" + esc(i.text) +
        (hasV(i.cite) ? ' <span class="pc-cite">(' + esc(i.cite) + ")</span>" : "") + "</li>";
    }
    return '<div class="proscons"><div><h4 class="pro-h">Strengths</h4><ul>' +
      pros.map(li).join("") + "</ul></div>" +
      '<div><h4 class="con-h">Concerns</h4><ul>' + cons.map(li).join("") + "</ul></div></div>";
  }
  window.FT_VIZ = {
    hasV: hasV, kpiStrip: kpiStrip, metricTile: metricTile, gauge: gauge,
    prosCons: prosCons, heatmap: heatmap, bars: bars,
    srcLine: srcLine, emptyFeature: emptyFeature, esc: esc, dir: dir,
  };
})();
