/* Canvas charts: line/area price chart with volume + SMA overlays. No deps. */
(function () {
  "use strict";
  function sma(values, w) {
    var out = [];
    for (var i = 0; i < values.length; i++) {
      if (i + 1 < w) { out.push(null); continue; }
      var s = 0, ok = true;
      for (var j = i + 1 - w; j <= i; j++) {
        if (values[j] === null || values[j] === undefined) { ok = false; break; }
        s += values[j];
      }
      out.push(ok ? s / w : null);
    }
    return out;
  }
  function drawPriceChart(canvas, bars, opts) {
    opts = opts || {};
    var dpr = window.devicePixelRatio || 1;
    var W = canvas.clientWidth || 800, H = canvas.clientHeight || 280;
    canvas.width = W * dpr; canvas.height = H * dpr;
    var ctx = canvas.getContext("2d");
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, W, H);
    var closes = bars.map(function (b) { return b.c; }).filter(function (v) { return v !== null; });
    if (!closes.length) {
      ctx.fillStyle = "#8b96ab"; ctx.font = "12px sans-serif";
      ctx.fillText("Insufficient data", 16, 30);
      return;
    }
    var padL = 8, padR = 64, padT = 12, padB = 34;
    var volH = 44;
    var lo = Math.min.apply(null, closes), hi = Math.max.apply(null, closes);
    var span = hi - lo || 1; lo -= span * 0.06; hi += span * 0.06;
    var vols = bars.map(function (b) { return b.v || 0; });
    var vmax = Math.max.apply(null, vols.concat([1]));
    function x(i) { return padL + (i / Math.max(bars.length - 1, 1)) * (W - padL - padR); }
    function y(v) { return padT + (1 - (v - lo) / (hi - lo)) * (H - padT - padB - volH); }
    // gridlines
    ctx.strokeStyle = "#1c2434"; ctx.fillStyle = "#5b6579"; ctx.font = "10px monospace"; ctx.lineWidth = 1;
    for (var g = 0; g <= 4; g++) {
      var gv = lo + (span * 1.12 * g) / 4, gy = y(gv);
      ctx.beginPath(); ctx.moveTo(padL, gy); ctx.lineTo(W - padR, gy); ctx.stroke();
      ctx.fillText(Number(gv).toLocaleString("en-US", { maximumFractionDigits: 2 }), W - padR + 6, gy + 3);
    }
    // volume
    var vy0 = H - padB - volH;
    bars.forEach(function (b, i) {
      var h = (b.v || 0) / vmax * (volH - 4);
      var up = (b.c !== null && b.o !== null && b.c >= b.o);
      ctx.fillStyle = up ? "rgba(47,191,113,.35)" : "rgba(240,85,85,.35)";
      ctx.fillRect(x(i) - 1, vy0 + (volH - 4 - h), 2, h);
    });
    // area + line
    function pathOf(vals) {
      ctx.beginPath();
      var started = false;
      bars.forEach(function (b, i) {
        var v = vals[i];
        if (v === null || v === undefined) { started = false; return; }
        if (!started) { ctx.moveTo(x(i), y(v)); started = true; }
        else ctx.lineTo(x(i), y(v));
      });
    }
    var first = closes[0], last = closes[closes.length - 1];
    var col = last >= first ? "#2fbf71" : "#f05555";
    var grad = ctx.createLinearGradient(0, padT, 0, H - padB - volH);
    grad.addColorStop(0, last >= first ? "rgba(47,191,113,.25)" : "rgba(240,85,85,.25)");
    grad.addColorStop(1, "rgba(0,0,0,0)");
    pathOf(bars.map(function (b) { return b.c; }));
    ctx.save();
    ctx.lineTo(x(bars.length - 1), H - padB - volH); ctx.lineTo(x(0), H - padB - volH); ctx.closePath();
    ctx.fillStyle = grad; ctx.fill(); ctx.restore();
    pathOf(bars.map(function (b) { return b.c; }));
    ctx.strokeStyle = col; ctx.lineWidth = 1.6; ctx.stroke();
    // SMA overlays
    var smas = opts.sma || [20, 50];
    var scols = ["#4da3ff", "#e0a63c", "#c79bff"];
    smas.forEach(function (w, k) {
      var s = sma(bars.map(function (b) { return b.c; }), w);
      if (s.every(function (v) { return v === null; })) return;
      pathOf(s); ctx.strokeStyle = scols[k % scols.length]; ctx.lineWidth = 1; ctx.stroke();
    });
    // x labels (first/mid/last dates)
    ctx.fillStyle = "#5b6579";
    function dt(i) {
      var t = bars[i] && bars[i].t;
      return t ? new Date(t * 1000).toISOString().slice(0, 10) : "";
    }
    if (bars.length) {
      ctx.fillText(dt(0), padL, H - 8);
      var mid = dt(Math.floor(bars.length / 2));
      ctx.fillText(mid, W / 2 - 30, H - 8);
      var end = dt(bars.length - 1);
      ctx.fillText(end, W - padR - 60, H - 8);
    }
  }
  window.FT_CHART = { drawPriceChart, sma };
})();
