/* Canvas charts: price + volume + SMA overlays, crosshair tooltip. No deps.
   Light institutional theme. drawPriceChart(canvas, bars, opts) keeps its
   signature: opts.sma = array of windows (default [20,50]). */
(function () {
  "use strict";
  var C = {
    grid: "#e7ebf0", ink: "#5b6068", up: "#1a7f37", dn: "#c62828",
    upFill: "rgba(26,127,55,.22)", dnFill: "rgba(198,40,40,.22)",
    volUp: "rgba(26,127,55,.30)", volDn: "rgba(198,40,40,.30)",
    cross: "#8a8f96", smas: ["#2563eb", "#9a6b12", "#0e7490"],
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
  /* Axis titles: drawn only when supplied (they should always be supplied
     for analytical charts). Small muted caps, never competing with data. */
  function axisTitles(ctx, W, H, padL, padB, xTitle, yTitle, P) {
    ctx.save();
    ctx.fillStyle = P.ink;
    ctx.font = "9px Inter,system-ui,sans-serif";
    if (yTitle) {
      ctx.save();
      ctx.translate(8, H / 2);
      ctx.rotate(-Math.PI / 2);
      ctx.textAlign = "center";
      ctx.fillText(String(yTitle).slice(0, 28), 0, 0);
      ctx.restore();
    }
    if (xTitle) {
      ctx.textAlign = "center";
      ctx.fillText(String(xTitle).slice(0, 40), padL + (W - padL) / 2, H - 2);
    }
    ctx.restore();
  }
  /* RSI-14 series from closes (Wilder). Terminal-calculated, marked ‡. */
  function rsiSeries(closes, period) {
    period = period || 14;
    var out = [], gains = 0, losses = 0;
    for (var i = 1; i < closes.length; i++) {
      var c = closes[i], p = closes[i - 1];
      if (c === null || c === undefined || p === null || p === undefined) { out.push(null); continue; }
      var ch = c - p;
      if (i <= period) {
        gains += Math.max(ch, 0); losses += Math.max(-ch, 0);
        out.push(i < period ? null : 100 - 100 / (1 + (losses ? gains / losses : 100)));
      } else {
        gains = (gains * (period - 1) + Math.max(ch, 0)) / period;
        losses = (losses * (period - 1) + Math.max(-ch, 0)) / period;
        out.push(losses === 0 ? 100 : 100 - 100 / (1 + gains / losses));
      }
    }
    out.unshift(null);
    return out;
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
    ctx.font = "10px Inter,system-ui,sans-serif"; ctx.lineWidth = 1;
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
    // analytical markers — levels ({value}) and events ({t} timestamp).
    // Only supplied, in-range, real markers render. Never invented.
    (opts.markers || []).forEach(function (m) {
      if (m.t !== undefined && m.t !== null) {
        var bi = 0, bd = Infinity;
        bars.forEach(function (b, i) {
          if (b.t === null || b.t === undefined) return;
          var dd = Math.abs(b.t - m.t);
          if (dd < bd) { bd = dd; bi = i; }
        });
        if (!isFinite(bd)) return;
        var mx = Math.round(x(bi)) + 0.5;
        ctx.save();
        ctx.strokeStyle = m.color || C.cross; ctx.setLineDash([2, 3]); ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(mx, padT); ctx.lineTo(mx, H - padB - volH); ctx.stroke();
        ctx.setLineDash([]);
        ctx.fillStyle = m.color || C.ink;
        ctx.fillText(String(m.label || "").slice(0, 12), Math.min(mx + 3, W - padR - 70), padT + 9);
        ctx.restore();
        return;
      }
      if (m.value === null || m.value === undefined || isNaN(m.value)) return;
      if (m.value < lo || m.value > hi) return;
      var my = Math.round(y(m.value)) + 0.5;
      ctx.save();
      ctx.strokeStyle = m.color || C.cross; ctx.setLineDash([5, 4]); ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(padL, my); ctx.lineTo(W - padR, my); ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = m.color || C.ink;
      ctx.fillText(String(m.label || "").slice(0, 18), padL + 4, my - 4);
      ctx.restore();
    });
    // latest-value end label (direct series labeling, not legend-hunting)
    (function () {
      var li = bars.length - 1;
      while (li >= 0 && (bars[li].c === null || bars[li].c === undefined)) li--;
      if (li < 0) return;
      ctx.save();
      ctx.fillStyle = upTrend ? C.up : C.dn;
      ctx.font = "700 11px Inter,system-ui,sans-serif";
      ctx.fillText(fmtN(bars[li].c), W - padR + 6, Math.max(padT + 8, Math.min(H - padB - volH, y(bars[li].c) + 3)));
      ctx.restore();
    })();
    axisTitles(ctx, W, H, padL, padB, opts.xTitle || "", opts.yTitle || "Price", P);
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
      drawPriceChart(canvas, bars, { sma: smas, markers: opts.markers, xTitle: opts.xTitle, yTitle: opts.yTitle, src: opts.src, _noBind: true });
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
          "<br>L " + fmtN(b.l) + " · C <b>" + fmtN(b.c) + "</b><br>Vol " + fmtN(b.v) +
          (opts.src ? "<br><span>" + opts.src + "</span>" : "");
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
    ctx.globalAlpha = 0.22; ctx.fillStyle = col; ctx.fill(); ctx.globalAlpha = 1;
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
    ctx.font = "10px Inter,system-ui,sans-serif"; ctx.lineWidth = 1;
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
    axisTitles(ctx, W, H, padL, padB, opts.xTitle || "", opts.yTitle || "", P);
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
    ctx.font = "10px Inter,system-ui,sans-serif"; ctx.lineWidth = 1;
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
    axisTitles(ctx, W, H, padL, padB, opts.xTitle || "", opts.yTitle || "", P);
  }
  /* Donut: composition only where categories are additive (holdings,
     allocation). Center total, per-slice legend with values. */
  function drawDonut(canvas, slices, opts) {
    opts = opts || {};
    var P = palette();
    var dpr = window.devicePixelRatio || 1;
    var W = canvas.clientWidth || 300, H = canvas.clientHeight || 200;
    canvas.width = W * dpr; canvas.height = H * dpr;
    var ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);
    var live = (slices || []).filter(function (s) { return s.value !== null && s.value !== undefined && !isNaN(s.value) && s.value > 0; });
    var total = live.reduce(function (a, s) { return a + s.value; }, 0);
    if (!live.length || !total) {
      ctx.fillStyle = P.ink; ctx.font = "12px Inter,sans-serif";
      ctx.fillText("Insufficient data", 16, 30);
      return;
    }
    var cols = opts.colors || ["#2563eb", "#0e7490", "#9a6b12", "#6d4fc2", "#5b6068", "#1a7f37", "#c62828"];
    var cx = 70, cy = H / 2, R = Math.min(58, H / 2 - 8), r0 = R * 0.62, a = -Math.PI / 2;
    live.forEach(function (s, i) {
      var a2 = a + (s.value / total) * Math.PI * 2;
      ctx.beginPath();
      ctx.arc(cx, cy, R, a, a2);
      ctx.arc(cx, cy, r0, a2, a, true);
      ctx.closePath();
      ctx.fillStyle = cols[i % cols.length];
      ctx.fill();
      a = a2;
    });
    ctx.fillStyle = P.ink;
    ctx.font = "700 15px Inter,sans-serif"; ctx.textAlign = "center";
    ctx.fillText(opts.center || "", cx, cy + 5);
    ctx.textAlign = "left"; ctx.font = "11px Inter,sans-serif";
    live.forEach(function (s, i) {
      var y = 22 + i * 20;
      if (y > H - 4) return;
      ctx.fillStyle = cols[i % cols.length];
      ctx.fillRect(140, y - 8, 8, 8);
      ctx.fillStyle = P.ink;
      ctx.fillText(String(s.label).slice(0, 22) + "  " + s.display, 152, y);
    });
  }
  /* Scatter: relationships (P/E vs growth). Points carry labels. */
  function drawScatter(canvas, points, opts) {
    opts = opts || {};
    var P = palette();
    var dpr = window.devicePixelRatio || 1;
    var W = canvas.clientWidth || 600, H = canvas.clientHeight || 260;
    canvas.width = W * dpr; canvas.height = H * dpr;
    var ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);
    var live = (points || []).filter(function (p) {
      return p.x !== null && p.x !== undefined && !isNaN(p.x) && p.y !== null && p.y !== undefined && !isNaN(p.y);
    });
    if (live.length < 2) {
      ctx.fillStyle = P.ink; ctx.font = "12px Inter,sans-serif";
      ctx.fillText("Not enough points for a scatter — need 2+ companies with both metrics.", 16, 30);
      return;
    }
    var xs = live.map(function (p) { return p.x; }), ys = live.map(function (p) { return p.y; });
    var x0 = Math.min.apply(null, xs), x1 = Math.max.apply(null, xs);
    var y0 = Math.min.apply(null, ys), y1 = Math.max.apply(null, ys);
    if (x1 === x0) x1 = x0 + 1;
    if (y1 === y0) y1 = y0 + 1;
    var padL = 52, padR = 12, padT = 10, padB = 34;
    function X(v) { return padL + ((v - x0) / (x1 - x0)) * (W - padL - padR); }
    function Y(v) { return padT + (1 - (v - y0) / (y1 - y0)) * (H - padT - padB); }
    ctx.strokeStyle = P.grid; ctx.fillStyle = P.ink;
    ctx.font = "10px Inter,system-ui,sans-serif"; ctx.lineWidth = 1;
    for (var g = 0; g <= 3; g++) {
      var gv = y0 + ((y1 - y0) * g) / 3, gy = Math.round(Y(gv)) + 0.5;
      ctx.beginPath(); ctx.moveTo(padL, gy); ctx.lineTo(W - padR, gy); ctx.stroke();
      ctx.fillText(fmtN(gv), 4, gy + 3);
    }
    live.forEach(function (p, i) {
      ctx.fillStyle = ["#2563eb", "#0e7490", "#9a6b12", "#6d4fc2", "#1a7f37"][i % 5];
      ctx.beginPath(); ctx.arc(X(p.x), Y(p.y), 4.5, 0, 7); ctx.fill();
      ctx.fillStyle = P.ink;
      ctx.fillText(String(p.label || "").slice(0, 14), X(p.x) + 7, Y(p.y) + 3);
    });
    axisTitles(ctx, W, H, padL, padB, opts.xTitle || "X", opts.yTitle || "Y", P);
    canvas.onmousemove = function (ev) {
      var tip = canvas.parentNode ? canvas.parentNode.querySelector(".chart-tip") : null;
      if (!tip) return;
      var r = canvas.getBoundingClientRect();
      var mx = ev.clientX - r.left, my = ev.clientY - r.top;
      var best = null, bd = 18;
      live.forEach(function (p) {
        var dx = X(p.x) - mx, dy = Y(p.y) - my, dd = Math.sqrt(dx * dx + dy * dy);
        if (dd < bd) { bd = dd; best = p; }
      });
      if (!best) { tip.style.display = "none"; return; }
      tip.innerHTML = "<b>" + best.label + "</b><br>" + (opts.xTitle || "X") + ": <b>" + fmtN(best.x) + "</b><br>" +
        (opts.yTitle || "Y") + ": <b>" + fmtN(best.y) + "</b>" + (opts.src ? "<br><span>" + opts.src + "</span>" : "");
      tip.style.display = "block";
      var pr = canvas.parentNode.getBoundingClientRect();
      tip.style.left = Math.min(pr.width - 170, mx + 12) + "px";
      tip.style.top = Math.max(0, my - 10) + "px";
    };
    canvas.onmouseleave = function () {
      var tip = canvas.parentNode ? canvas.parentNode.querySelector(".chart-tip") : null;
      if (tip) tip.style.display = "none";
    };
  }
  /* Histogram: distributions (P/E, ROE, mcap buckets). */
  function drawHist(canvas, values, opts) {
    opts = opts || {};
    var P = palette();
    var dpr = window.devicePixelRatio || 1;
    var W = canvas.clientWidth || 600, H = canvas.clientHeight || 200;
    canvas.width = W * dpr; canvas.height = H * dpr;
    var ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);
    var vals = (values || []).filter(function (v) { return v !== null && v !== undefined && !isNaN(v); });
    if (vals.length < 3) {
      ctx.fillStyle = P.ink; ctx.font = "12px Inter,sans-serif";
      ctx.fillText("Too few values for a distribution.", 16, 30);
      return;
    }
    var nb = Math.max(3, Math.min(10, Math.round(Math.sqrt(vals.length))));
    var lo = Math.min.apply(null, vals), hi = Math.max.apply(null, vals);
    if (hi === lo) hi = lo + 1;
    var bins = [], w = (hi - lo) / nb, i;
    for (i = 0; i < nb; i++) bins.push(0);
    vals.forEach(function (v) { bins[Math.min(nb - 1, Math.floor((v - lo) / w))]++; });
    var mx = Math.max.apply(null, bins);
    var padL = 34, padB = 30, padT = 8;
    var bw = (W - padL - 8) / nb;
    ctx.fillStyle = opts.color || "#2563eb";
    bins.forEach(function (c, k) {
      var h = (c / mx) * (H - padT - padB);
      ctx.fillRect(padL + k * bw + 1, H - padB - h, bw - 2, Math.max(1, h));
      if (c > 0) {
        ctx.fillStyle = P.ink;
        ctx.font = "10px Inter,sans-serif";
        ctx.fillText(String(c), padL + k * bw + 3, H - padB - h - 3);
        ctx.fillStyle = opts.color || "#2563eb";
      }
    });
    ctx.fillStyle = P.ink; ctx.font = "10px Inter,sans-serif";
    ctx.fillText(fmtN(lo), padL, H - padB + 14);
    var hiLab = fmtN(hi);
    ctx.fillText(hiLab, W - 8 - hiLab.length * 6, H - padB + 14);
    axisTitles(ctx, W, H, padL, padB, opts.xTitle || "Value", opts.yTitle || "Count", P);
  }
  /* RSI-14 panel with 70/30 reference bands. */
  function drawRSI(canvas, closes, opts) {
    opts = opts || {};
    var P = palette();
    var vals = rsiSeries(closes, 14);
    var dpr = window.devicePixelRatio || 1;
    var W = canvas.clientWidth || 600, H = canvas.clientHeight || 120;
    canvas.width = W * dpr; canvas.height = H * dpr;
    var ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);
    var live = vals.filter(function (v) { return v !== null; });
    if (live.length < 5) {
      ctx.fillStyle = P.ink; ctx.font = "12px Inter,sans-serif";
      ctx.fillText("Not enough history for RSI-14.", 16, 30);
      return;
    }
    var padL = 34, padB = 20, padT = 6;
    function Y(v) { return padT + (1 - v / 100) * (H - padT - padB); }
    function X(i) { return padL + (i / (vals.length - 1)) * (W - padL - 8); }
    ctx.strokeStyle = P.grid; ctx.lineWidth = 1;
    [70, 50, 30].forEach(function (b) {
      var gy = Math.round(Y(b)) + 0.5;
      ctx.setLineDash(b === 50 ? [] : [4, 4]);
      ctx.beginPath(); ctx.moveTo(padL, gy); ctx.lineTo(W - 8, gy); ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = P.ink; ctx.font = "10px Inter,sans-serif";
      ctx.fillText(String(b), 4, gy + 3);
    });
    ctx.strokeStyle = "#0e7490"; ctx.lineWidth = 1.5; ctx.lineJoin = "round";
    ctx.beginPath();
    var started = false;
    vals.forEach(function (v, i) {
      if (v === null) { started = false; return; }
      if (!started) { ctx.moveTo(X(i), Y(v)); started = true; }
      else ctx.lineTo(X(i), Y(v));
    });
    ctx.stroke();
    var last = live[live.length - 1];
    ctx.fillStyle = last > 70 ? C.dn : last < 30 ? C.up : P.ink;
    ctx.font = "700 12px Inter,sans-serif";
    ctx.fillText("RSI " + last.toFixed(1), W - 64, Y(last) - 6);
    axisTitles(ctx, W, H, padL, padB, opts.xTitle || "Date", opts.yTitle || "RSI (14)", P);
  }
  window.FT_CHART = { drawPriceChart: drawPriceChart, drawSpark: drawSpark, drawBars: drawBars, drawLines: drawLines, drawDonut: drawDonut, drawScatter: drawScatter, drawHist: drawHist, drawRSI: drawRSI, sma: sma, rsiSeries: rsiSeries };
})();
