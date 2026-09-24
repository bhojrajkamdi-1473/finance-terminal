/* FT interpretation engine: deterministic DATA -> sentence templates.
   Every function returns "" when its inputs are insufficient — callers
   omit the interpretation instead of showing hedged filler. No LLM
   needed; no advice, no forecasts, only what the numbers support. */
(function () {
  "use strict";
  function num(v, dp) {
    if (v === null || v === undefined || isNaN(Number(v))) return null;
    return Number(v).toFixed(dp === undefined ? 1 : dp);
  }
  function pct(v) {
    var n = num(v, 2);
    return n === null ? null : (Number(v) > 0 ? "+" : "") + n + "%";
  }
  /* Index/stock trend over a close series. */
  function trend(name, closes, spanLabel) {
    var vals = (closes || []).filter(function (v) { return v !== null && v !== undefined && !isNaN(v); });
    if (vals.length < 2) return "";
    var m = (vals[vals.length - 1] - vals[0]) / Math.abs(vals[0]) * 100;
    var p = pct(m);
    if (p === null) return "";
    return name + " is " + (m >= 0 ? "up " + p : "down " + p) +
      (spanLabel ? " over " + spanLabel : "") + ".";
  }
  /* Advance/decline breadth. */
  function breadth(adv, dec, unch, universeLabel) {
    if (adv === null || adv === undefined || dec === null || dec === undefined) return "";
    var total = adv + dec + (unch || 0);
    if (!total) return "";
    var lead = adv === dec ? "Even breadth"
      : adv > dec ? "Breadth favors advancers" : "Breadth favors decliners";
    return lead + " (" + adv + " up, " + dec + " down" +
      (unch ? ", " + unch + " unchanged" : "") + ")" +
      (universeLabel ? " in " + universeLabel + "." : ".");
  }
  /* Sector/index move of the day. */
  function move(name, chg) {
    var p = pct(chg);
    if (p === null) return "";
    return name + " " + (Number(chg) >= 0 ? "gained " + p : "lost " + p) + " today.";
  }
  /* Financial growth: CAGR preferred, YoY fallback. */
  function growth(label, cagr, yoy, spanLabel, latestPeriod) {
    var c = num(cagr, 1), y = num(yoy, 1);
    if (c !== null && spanLabel) {
      return label + " grew at " + c + "% CAGR over " + spanLabel + ".";
    }
    if (y !== null) {
      return label + " " + (Number(yoy) >= 0 ? "grew " + y + "%" : "declined " + y + "%") +
        " year on year" + (latestPeriod ? " in " + latestPeriod : "") + ".";
    }
    return "";
  }
  /* Valuation level, descriptive only. */
  function multiple(label, value, period) {
    var n = num(value, 1);
    if (n === null) return "";
    return label + " stands at " + n + "x" + (period ? " (" + period + ")" : "") + ".";
  }
  /* RSI zone reading. */
  function rsi(v) {
    var n = num(v, 0);
    if (n === null) return "";
    return "RSI " + n + (Number(v) > 70 ? " — overheated zone."
      : Number(v) < 30 ? " — oversold zone." : " — neutral zone.");
  }
  /* Price vs moving averages. */
  function vsAverages(last, sma50, sma200) {
    var L = Number(last), A = Number(sma50), B = Number(sma200);
    if ([L, A, B].some(isNaN)) return "";
    if (L > A && L > B) return "Price is above both the 50-day and 200-day averages.";
    if (L < A && L < B) return "Price is below both the 50-day and 200-day averages.";
    return "Price sits between the 50-day and 200-day averages.";
  }
  /* Market regime from computed parts. */
  function regime(o) {
    o = o || {};
    var bits = [];
    if (o.trend) bits.push("Trend reads " + o.trend);
    if (o.breadthNote) bits.push("breadth " + o.breadthNote);
    if (o.momentum) bits.push("momentum " + o.momentum);
    if (o.volatility) bits.push("volatility at " + o.volatility);
    if (!bits.length) return "";
    return "Market regime: " + bits.join(", ") + ".";
  }
  /* Relative performance vs benchmark. */
  function relative(name, pp, bench) {
    var n = num(pp, 1);
    if (n === null) return "";
    return name + " is " + (Number(pp) >= 0 ? "+" : "") + n +
      " pp vs " + (bench || "benchmark") + " over the lookback.";
  }
  window.FT_INTERP = {
    trend: trend, breadth: breadth, move: move, growth: growth,
    multiple: multiple, rsi: rsi, vsAverages: vsAverages,
    regime: regime, relative: relative,
  };
})();
