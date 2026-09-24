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
  /* KPI strip: cells {label, value, sub, tip}. Null values are dropped;
     the strip reflows. Returns "" when nothing is showable. */
  function kpiStrip(cells, opts) {
    opts = opts || {};
    var live = (cells || []).filter(function (c) { return c && hasV(c.value); });
    if (!live.length) return "";
    return '<div class="kstrip' + (opts.big ? " big" : "") + '">' + live.map(function (c) {
      return '<div class="kpi"' + (c.tip ? " title='" + esc(c.tip) + "'" : "") + ">" +
        '<div class="k-l">' + esc(c.label || "") + "</div>" +
        '<div class="k-v">' + c.value + "</div>" +
        (hasV(c.sub) ? '<div class="k-s">' + c.sub + "</div>" : "") + "</div>";
    }).join("") + "</div>";
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
  window.FT_VIZ = {
    hasV: hasV, kpiStrip: kpiStrip, heatmap: heatmap, bars: bars,
    srcLine: srcLine, emptyFeature: emptyFeature, esc: esc, dir: dir,
  };
})();
