/* Canvas charts: price + volume + SMA overlays, crosshair tooltip. No deps.
   Light institutional theme. drawPriceChart(canvas, bars, opts) keeps its
   signature: opts.sma = array of windows (default [20,50]). */
(function () {
  "use strict";
  var C = {
    grid: "#e7ebf0", ink: "#687182", up: "#18794e", dn: "#c03535",
    upFill: "rgba(24,121,78,.14)", dnFill: "rgba(192,53,53,.14)",
    volUp: "rgba(24,121,78,.30)", volDn: "rgba(192,53,53,.30)",
    cross: "#9aa3af", smas: ["#1a56c4", "#9a6b12", "#6d4fc2"],
  };
  var C_DARK = {
    grid: "#1E2A45", ink: "#8A9BC0", up: "#00D68F", dn: "#FF4D6A",
    upFill: "rgba(0,214,143,.14)", dnFill: "rgba(255,77,106,.14)",
    volUp: "rgba(0,214,143,.30)", volDn: "rgba(255,77,106,.30)",
    cross: "#4A5A7A", smas: ["#3B7BF6", "#F5A623", "#7B5CF6"],
  };
  function palette() {
    try {
      if (document.body && document.body.dataset.theme === "dark") return C_DARK;
    } catch (e) { /* default light */ }
    return C;
  }
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
  function fmtN(v) {
    if (v === null || v === undefined || isNaN(v)) return "—";
    return Number(v).toLocaleString("en-US", { maximumFractionDigits: 2 });
  }
  function fmtD(t) {
    if (!t) return "";
    var d = new Date(t * 1000);
    return isNaN(d) ? "" : d.toISOString().slice(0, 10);
  }
  function drawPriceChart(canvas, bars, opts) {
    opts = opts || {};
    C = palette();
    var smas = opts.sma || [20, 50];
    var dpr = window.devicePixelRatio || 1;
    var W = canvas.clientWidth || 800, H = canvas.clientHeight || 300;
    canvas.width = W * dpr; canvas.height = H * dpr;
    var ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);
    var closes = bars.map(function (b) { return b.c; }).filter(function (v) { return v !== null && v !== undefined; });
    if (!closes.length) {
      ctx.fillStyle = C.ink; ctx.font = "12px sans-serif";
      ctx.fillText("Insufficient data", 16, 30);
      return;
    }
    var padL = 6, padR = 66, padT = 10, padB = 30, volH = 46;
    var lo = Math.min.apply(null, closes), hi = Math.max.apply(null, closes);
    var span = hi - lo || 1; lo -= span * 0.07; hi += span * 0.07;
    var vols = bars.map(function (b) { return b.v || 0; });
    var vmax = Math.max.apply(null, vols.concat([1]));
    function x(i) { return padL + (i / Math.max(bars.length - 1, 1)) * (W - padL - padR); }
    function y(v) { return padT + (1 - (v - lo) / (hi - lo)) * (H - padT - padB - volH); }
    // grid + y labels
    ctx.strokeStyle = C.grid; ctx.fillStyle = C.ink;
    ctx.font = "10px 'IBM Plex Mono',Consolas,monospace"; ctx.lineWidth = 1;
    for (var g = 0; g <= 4; g++) {
      var gv = lo + ((hi - lo) * g) / 4, gy = Math.round(y(gv)) + 0.5;
      ctx.beginPath(); ctx.moveTo(padL, gy); ctx.lineTo(W - padR, gy); ctx.stroke();
      ctx.fillText(fmtN(gv), W - padR + 6, gy + 3);
    }
    // volume
    var vy0 = H - padB - volH, bw = Math.max(1, (W - padL - padR) / bars.length - 1);
    bars.forEach(function (b, i) {
      var h = (b.v || 0) / vmax * (volH - 4);
      var up = b.c !== null && b.o !== null && b.c >= b.o;
      ctx.fillStyle = up ? C.volUp : C.volDn;
      ctx.fillRect(x(i) - bw / 2, vy0 + (volH - 4 - h), bw, h);
    });
    // area + price line
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
    var upTrend = last >= first;
    var grad = ctx.createLinearGradient(0, padT, 0, H - padB - volH);
    grad.addColorStop(0, upTrend ? C.upFill : C.dnFill);
    grad.addColorStop(1, "rgba(255,255,255,0)");
    var cl = bars.map(function (b) { return b.c; });
    pathOf(cl);
    ctx.save();
    ctx.lineTo(x(bars.length - 1), H - padB - volH);
    ctx.lineTo(x(0), H - padB - volH); ctx.closePath();
    ctx.fillStyle = grad; ctx.fill(); ctx.restore();
    pathOf(cl);
    ctx.strokeStyle = upTrend ? C.up : C.dn; ctx.lineWidth = 1.6; ctx.stroke();
    // SMA overlays
    var smaSeries = smas.map(function (w) { return sma(cl, w); });
    smaSeries.forEach(function (s, k) {
      if (s.every(function (v) { return v === null; })) return;
      pathOf(s); ctx.strokeStyle = C.smas[k % C.smas.length]; ctx.lineWidth = 1; ctx.stroke();
    });
    // x labels
    ctx.fillStyle = C.ink;
    if (bars.length) {
      ctx.fillText(fmtD(bars[0].t), padL, H - 8);
      ctx.fillText(fmtD(bars[Math.floor(bars.length / 2)].t), W / 2 - 30, H - 8);
      var end = fmtD(bars[bars.length - 1].t);
      ctx.fillText(end, W - padR - end.length * 6 - 4, H - 8);
    }
    // crosshair + tooltip
    var tip = canvas.parentNode ? canvas.parentNode.querySelector(".chart-tip") : null;
    function nearest(ev) {
      var r = canvas.getBoundingClientRect();
      var mx = ev.clientX - r.left;
      var i = Math.round((mx - padL) / Math.max(1, (W - padL - padR)) * (bars.length - 1));
      return Math.max(0, Math.min(bars.length - 1, i));
    }
    function hide() {
      if (tip) tip.style.display = "none";
      drawStatic();
    }
    function drawStatic() {
      // redraw without crosshair (cheap: full redraw)
      drawPriceChart(canvas, bars, { sma: smas, _noBind: true });
    }
    if (tip && !opts._noBind) {
      canvas.onmousemove = function (ev) {
        var i = nearest(ev), b = bars[i];
        if (!b) return;
        drawStatic();
        var c2 = canvas.getContext("2d");
        c2.setTransform(dpr, 0, 0, dpr, 0, 0);
        c2.strokeStyle = C.cross; c2.setLineDash([3, 3]); c2.lineWidth = 1;
        c2.beginPath(); c2.moveTo(x(i), padT); c2.lineTo(x(i), H - padB); c2.stroke();
        c2.setLineDash([]);
        c2.fillStyle = "#fff"; c2.strokeStyle = upTrend ? C.up : C.dn; c2.lineWidth = 1.5;
        c2.beginPath(); c2.arc(x(i), y(b.c), 3, 0, 7); c2.fill(); c2.stroke();
        tip.innerHTML = "<b>" + fmtD(b.t) + "</b><br>O " + fmtN(b.o) + " · H " + fmtN(b.h) +
          "<br>L " + fmtN(b.l) + " · C <b>" + fmtN(b.c) + "</b><br>Vol " + fmtN(b.v);
        tip.style.display = "block";
        var r = canvas.getBoundingClientRect(), pr = canvas.parentNode.getBoundingClientRect();
        var lx = r.left - pr.left + x(i) + 12, ly = r.top - pr.top + y(b.c) - 10;
        if (lx + 150 > pr.width) lx -= 165;
        tip.style.left = lx + "px"; tip.style.top = Math.max(0, ly) + "px";
      };
      canvas.onmouseleave = hide;
    }
  }
  /* Sparkline: compact trend line for index cards. No axes, no tooltip. */
  function drawSpark(canvas, closes, up) {
    var P = palette();
    var dpr = window.devicePixelRatio || 1;
    var W = canvas.clientWidth || 180, H = canvas.clientHeight || 38;
    canvas.width = W * dpr; canvas.height = H * dpr;
    var ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);
    var vals = (closes || []).filter(function (v) { return v !== null && v !== undefined && !isNaN(v); });
    if (vals.length < 2) return;
    var lo = Math.min.apply(null, vals), hi = Math.max.apply(null, vals), span = hi - lo || 1;
    function x(i) { return 2 + (i / (vals.length - 1)) * (W - 4); }
    function y(v) { return 3 + (1 - (v - lo) / span) * (H - 6); }
    var col = up === false ? P.dn : P.up;
    ctx.strokeStyle = col; ctx.lineWidth = 1.5; ctx.lineJoin = "round";
    ctx.beginPath();
    vals.forEach(function (v, i) { if (i) ctx.lineTo(x(i), y(v)); else ctx.moveTo(x(i), y(v)); });
    ctx.stroke();
    ctx.lineTo(x(vals.length - 1), H); ctx.lineTo(x(0), H); ctx.closePath();
    ctx.globalAlpha = 0.12; ctx.fillStyle = col; ctx.fill(); ctx.globalAlpha = 1;
  }
  /* Grouped bars: financial statement charts (revenue/EBITDA/PAT...). */
  function drawBars(canvas, groups, opts) {
    var P = palette();
    opts = opts || {};
    var dpr = window.devicePixelRatio || 1;
    var W = canvas.clientWidth || 600, H = canvas.clientHeight || 220;
    canvas.width = W * dpr; canvas.height = H * dpr;
    var ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);
    var series = groups.series || [], labels = groups.labels || [];
    if (!series.length || !labels.length) {
      ctx.fillStyle = P.ink; ctx.font = "12px sans-serif";
      ctx.fillText("Insufficient data", 16, 30);
      return;
    }
    var cols = opts.colors || [P.smas[0], P.smas[1], P.smas[2], "#7B5CF6"];
    var all = [];
    series.forEach(function (s) { (s.values || []).forEach(function (v) { if (v !== null && v !== undefined) all.push(v); }); });
    if (!all.length) {
      ctx.fillStyle = P.ink; ctx.font = "12px sans-serif";
      ctx.fillText("Insufficient data", 16, 30);
      return;
    }
    var mx = Math.max.apply(null, all.concat([0])), mn = Math.min.apply(null, all.concat([0]));
    var span = mx - mn || 1;
    var padL = 56, padB = 26, padT = 8;
    var zeroY = padT + (1 - (0 - mn) / span) * (H - padT - padB);
    function y(v) { return padT + (1 - (v - mn) / span) * (H - padT - padB); }
    ctx.strokeStyle = P.grid; ctx.fillStyle = P.ink;
    ctx.font = "10px 'JetBrains Mono','IBM Plex Mono',Consolas,monospace"; ctx.lineWidth = 1;
    for (var g = 0; g <= 3; g++) {
      var gv = mn + (span * g) / 3, gy = Math.round(y(gv)) + 0.5;
      ctx.beginPath(); ctx.moveTo(padL, gy); ctx.lineTo(W - 6, gy); ctx.stroke();
    }
    ctx.beginPath(); ctx.moveTo(padL, zeroY); ctx.lineTo(W - 6, zeroY);
    ctx.strokeStyle = P.ink; ctx.stroke();
    var slot = (W - padL - 10) / labels.length, bw = Math.min(26, (slot - 10) / series.length);
    labels.forEach(function (lab, i) {
      var cx = padL + slot * i + slot / 2;
      series.forEach(function (s, j) {
        var v = (s.values || [])[i];
        if (v === null || v === undefined) return;
        var h = Math.abs(y(v) - zeroY);
        ctx.fillStyle = cols[j % cols.length];
        ctx.fillRect(cx - (series.length * bw) / 2 + j * bw, Math.min(y(v), zeroY), bw - 1, Math.max(1, h));
      });
      ctx.fillStyle = P.ink;
      ctx.fillText(String(lab).slice(0, 10), cx - 20, H - 8);
    });
    /* legend */
    var lx = padL;
    ctx.font = "10px sans-serif";
    series.forEach(function (s, j) {
      ctx.fillStyle = cols[j % cols.length];
      ctx.fillRect(lx, 2, 8, 8);
      ctx.fillStyle = P.ink;
      ctx.fillText(s.name || "", lx + 11, 9);
      lx += ctx.measureText(s.name || "").width + 26;
    });
  }
  /* Multi-series lines (compare performance, GMP trend). Shared axis. */
  function drawLines(canvas, groups, opts) {
    var P = palette();
    opts = opts || {};
    var dpr = window.devicePixelRatio || 1;
    var W = canvas.clientWidth || 600, H = canvas.clientHeight || 220;
    canvas.width = W * dpr; canvas.height = H * dpr;
    var ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);
    var series = (groups.series || []).filter(function (s) {
      return s.values && s.values.some(function (v) { return v !== null && v !== undefined && !isNaN(v); });
    });
    var labels = groups.labels || [];
    if (!series.length) {
      ctx.fillStyle = P.ink; ctx.font = "12px sans-serif";
      ctx.fillText("Insufficient data", 16, 30);
      return;
    }
    var cols = opts.colors || [P.smas[0], P.smas[1], P.smas[2], "#7B5CF6", "#00D68F", "#F5A623"];
    var all = [];
    series.forEach(function (s) { s.values.forEach(function (v) { if (v !== null && v !== undefined && !isNaN(v)) all.push(v); }); });
    var mx = Math.max.apply(null, all), mn = Math.min.apply(null, all), span = mx - mn || 1;
    var padL = 52, padB = 22, padT = 8;
    function x(i, n) { return padL + (i / Math.max(n - 1, 1)) * (W - padL - 8); }
    function y(v) { return padT + (1 - (v - mn) / span) * (H - padT - padB); }
    ctx.strokeStyle = P.grid; ctx.fillStyle = P.ink;
    ctx.font = "10px 'JetBrains Mono','IBM Plex Mono',Consolas,monospace"; ctx.lineWidth = 1;
    for (var g = 0; g <= 3; g++) {
      var gv = mn + (span * g) / 3, gy = Math.round(y(gv)) + 0.5;
      ctx.beginPath(); ctx.moveTo(padL, gy); ctx.lineTo(W - 8, gy); ctx.stroke();
      var lab = gv >= 1000 ? (gv / 1000).toFixed(1) + "k" : gv >= 100 ? gv.toFixed(0) : gv.toFixed(1);
      ctx.fillText(lab, 4, gy + 3);
    }
    series.forEach(function (s, j) {
      var n = s.values.length;
      ctx.strokeStyle = cols[j % cols.length]; ctx.lineWidth = 2; ctx.lineJoin = "round";
      ctx.beginPath();
      var started = false;
      s.values.forEach(function (v, i) {
        if (v === null || v === undefined || isNaN(v)) { started = false; return; }
        if (!started) { ctx.moveTo(x(i, n), y(v)); started = true; }
        else ctx.lineTo(x(i, n), y(v));
      });
      ctx.stroke();
    });
    var lx = padL;
    ctx.font = "11px sans-serif";
    series.forEach(function (s, j) {
      ctx.fillStyle = cols[j % cols.length];
      ctx.fillRect(lx, 2, 8, 8);
      ctx.fillStyle = P.ink;
      ctx.fillText(s.name || "", lx + 11, 9);
      try { lx += ctx.measureText(s.name || "").width + 26; } catch (e) { lx += 90; }
    });
    if (labels.length) {
      ctx.fillStyle = P.ink;
      ctx.fillText(String(labels[0]).slice(0, 10), padL, H - 6);
      ctx.fillText(String(labels[labels.length - 1]).slice(0, 10), W - 60, H - 6);
    }
  }
  window.FT_CHART = { drawPriceChart: drawPriceChart, drawSpark: drawSpark, drawBars: drawBars, drawLines: drawLines, sma: sma };
})();
