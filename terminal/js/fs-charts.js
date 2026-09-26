/* FINSIGHT chart + visual primitives (spec section 9).
   Canvas hand-rolled, no library. Gaps break lines (never interpolate).
   <2 points -> return false so callers render Empty/Unavailable instead.
   HTML helpers (bars/heatmap/kpiStrip) return strings; all text escaped. */
(function () {
  "use strict";
  function esc(s) {
    return String(s === null || s === undefined ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }
  function hasV(v) { return v !== null && v !== undefined && !isNaN(Number(v)); }
  function css(v, d) {
    if (typeof getComputedStyle === "undefined") return d;
    try { var x = getComputedStyle(document.body).getPropertyValue(v); return (x || "").trim() || d; }
    catch (e) { return d; }
  }
  function setup(cv, h) {
    var dpr = window.devicePixelRatio || 1;
    var w = cv.clientWidth || cv.parentNode.clientWidth || 300;
    cv.width = w * dpr; cv.height = h * dpr;
    cv.style.height = h + "px";
    var ctx = cv.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    return { ctx: ctx, w: w, h: h };
  }
  function strokeSeries(ctx, pts, color, width, dash) {
    ctx.strokeStyle = color; ctx.lineWidth = width || 1.5;
    ctx.setLineDash(dash || []);
    ctx.beginPath();
    var pen = false;
    pts.forEach(function (p) {
      if (p === null) { pen = false; return; }
      if (!pen) { ctx.moveTo(p[0], p[1]); pen = true; }
      else ctx.lineTo(p[0], p[1]);
    });
    ctx.stroke(); ctx.setLineDash([]);
  }
  /* Sparkline: no axes. Returns false if <2 valid points. */
  function sparkline(cv, series, up) {
    var vals = (series || []).filter(hasV).map(Number);
    if (vals.length < 2) return false;
    var H = 34, s = setup(cv, H), pad = 2;
    var mn = Math.min.apply(null, vals), mx = Math.max.apply(null, vals);
    if (mx === mn) { mx += 1; mn -= 1; }
    var pts = vals.map(function (v, i) {
      return [pad + i / (vals.length - 1) * (s.w - pad * 2),
              pad + (1 - (v - mn) / (mx - mn)) * (H - pad * 2)];
    });
    var good = (up === undefined) ? vals[vals.length - 1] >= vals[0] : !!up;
    strokeSeries(s.ctx, pts, good ? css("--up", "#3A9E6E") : css("--dn", "#C25A4A"), 1.5);
    /* area fill */
    try {
      s.ctx.lineTo(pts[pts.length - 1][0], H); s.ctx.lineTo(pts[0][0], H); s.ctx.closePath();
      s.ctx.fillStyle = good ? "rgba(58,158,110,.12)" : "rgba(194,90,74,.12)";
      s.ctx.fill();
    } catch (e) {}
    return true;
  }
  /* Multi-line chart with optional SMA overlay series. Nulls break lines. */
  function lines(cv, series, opts) {
    opts = opts || {};
    var valid = (series || []).filter(function (s) {
      return s && (s.values || []).filter(hasV).length >= 2;
    });
    if (!valid.length) return false;
    var H = opts.height || 220, s = setup(cv, H), padL = 8, padB = 18, padT = 8;
    var all = [];
    valid.forEach(function (x) { x.values.forEach(function (v) { if (hasV(v)) all.push(Number(v)); }); });
    var mn = Math.min.apply(null, all), mx = Math.max.apply(null, all);
    if (mx === mn) { mx += 1; mn -= 1; }
    var n = Math.max.apply(null, valid.map(function (x) { return x.values.length; }));
    function xy(i, v) {
      return [padL + i / Math.max(n - 1, 1) * (s.w - padL - 8),
              padT + (1 - (Number(v) - mn) / (mx - mn)) * (H - padT - padB)];
    }
    var palette = [css("--acc", "#C49A3C"), css("--info-ink", "#8AC3E0"), css("--up", "#3A9E6E"), "#C9A0DC"];
    /* gridlines */
    s.ctx.strokeStyle = css("--line", "#141E30"); s.ctx.lineWidth = 1;
    [0, 0.5, 1].forEach(function (f) {
      var y = padT + f * (H - padT - padB);
      s.ctx.beginPath(); s.ctx.moveTo(padL, y); s.ctx.lineTo(s.w - 8, y); s.ctx.stroke();
    });
    valid.forEach(function (x, ix) {
      var pts = x.values.map(function (v, i) { return hasV(v) ? xy(i, v) : null; });
      strokeSeries(s.ctx, pts, x.color || palette[ix % palette.length], x.dash ? 1.2 : 1.6, x.dash || []);
    });
    return true;
  }
  /* Horizontal performance bars. Rows with null value render Unavailable. */
  function bars(rows) {
    rows = (rows || []).filter(function (r) { return r; });
    if (!rows.length) return "";
    var mx = 1;
    rows.forEach(function (r) { if (hasV(r.value) && Math.abs(r.value) > mx) mx = Math.abs(r.value); });
    return rows.map(function (r) {
      var right = hasV(r.value)
        ? "<span class='tr'><span class='fl' style='display:block;width:" + Math.max(2, Math.round(Math.abs(r.value) / mx * 100)) +
          "%;background:" + (r.value >= 0 ? "var(--up)" : "var(--dn)") + "'></span></span><b>" + esc(r.display) + "</b>"
        : "<span class='tr'></span><b class='mut'>Unavailable</b>";
      return "<div class='bar-row'><span>" + esc(r.label) + "</span>" + right + "</div>";
    }).join("");
  }
  /* Sector heatmap: intensity = magnitude. Cells without values use "—". */
  function heatmap(tiles, fmt) {
    tiles = tiles || [];
    if (!tiles.length) return "";
    return "<div class='hmap'>" + tiles.map(function (t) {
      if (!hasV(t.value)) {
        return "<div class='htile'><b>" + esc(t.label) + "</b><span class='mut'>—</span></div>";
      }
      var mag = Math.min(Math.abs(t.value) / 2, 1);
      var bg = t.value >= 0
        ? "rgba(58,158,110," + (0.08 + mag * 0.45).toFixed(2) + ")"
        : "rgba(194,90,74," + (0.08 + mag * 0.45).toFixed(2) + ")";
      return "<div class='htile' style='background:" + bg + "'><b>" + esc(t.label) + "</b><span>" +
        esc(fmt ? fmt(t.value) : String(t.value)) + "</span></div>";
    }).join("") + "</div>";
  }
  function kpiStrip(cells) {
    return "<div class='kstrip'>" + (cells || []).map(function (c) {
      return "<div class='kpi'><div class='k-l'>" + esc(c.label) + "</div>" +
        "<div class='k-v'>" + (c.value === null || c.value === undefined ? "—" : esc(String(c.value))) + "</div>" +
        (c.sub ? "<div class='k-s'>" + esc(c.sub) + "</div>" : "") + "</div>";
    }).join("") + "</div>";
  }
  window.FS_CHART = {
    hasV: hasV, esc: esc, sparkline: sparkline, lines: lines,
    bars: bars, heatmap: heatmap, kpiStrip: kpiStrip
  };
})();
