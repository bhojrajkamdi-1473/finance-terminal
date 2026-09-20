/* Structured research engine: OBSERVE -> QUESTION -> HYPOTHESISE ->
   CONNECT -> VERIFY -> JUDGE. Builds a strictly-labelled brief from
   REAL quote/history/statement data. Interpretation is always fenced
   off from facts; gaps are listed as uncertainty. No LLM, no invented
   numbers — the "AI" pill means "machine-structured analysis". */
(function () {
  "use strict";
  var F = null;
  function fmt() { return (F = F || window.FT_FMT); }

  function pct(a, b) {
    if (a === null || a === undefined || b === null || b === undefined) return null;
    if (Number(b) === 0) return null;
    return (Number(a) - Number(b)) / Math.abs(Number(b)) * 100;
  }

  function brief(symbol, quote, history, ratios, recon) {
    var f = fmt(), facts = [], changed = [], calcs = [], interp = [], questions = [], risks = [];
    var src = [];
    if (quote) {
      src.push("quote:yahoo");
      facts.push("Last price " + f.fmtNum(quote.price) + " " + (quote.currency || "") +
        " on " + (quote.exchange || "unknown venue") +
        " (change " + f.fmtPct(quote.change_pct) + " vs prior close " + f.fmtNum(quote.previous_close) + ").");
      if (quote.market_time) facts.push("Quote timestamp " + f.fmtDateTime(quote.market_time) + " (delayed feed).");
    } else {
      risks.push("No live quote available — price-based checks are impossible right now.");
    }
    var bars = (history && history.bars) || [];
    if (bars.length >= 2) {
      src.push("history:yahoo:" + bars.length + "-bars");
      var first = bars[0].c, last = bars[bars.length - 1].c;
      var chg = pct(last, first);
      changed.push("Close moved " + f.fmtNum(first) + " → " + f.fmtNum(last) +
        " (" + f.fmtPct(chg) + ") over " + f.fmtDate(bars[0].t) + " → " +
        f.fmtDate(bars[bars.length - 1].t) + " (n=" + bars.length + ").");
      var hi = -Infinity, lo = Infinity, vsum = 0, vn = 0;
      bars.forEach(function (b) {
        if (b.c !== null) { hi = Math.max(hi, b.c); lo = Math.min(lo, b.c); }
        if (b.v) { vsum += b.v; vn++; }
      });
      calcs.push("Window range " + f.fmtNum(lo) + " – " + f.fmtNum(hi) +
        (vn ? "; avg daily volume " + f.fmtInt(vsum / vn) + "." : "."));
      var s20 = window.FT_CHART.sma(bars.map(function (b) { return b.c; }), 20);
      var s50 = window.FT_CHART.sma(bars.map(function (b) { return b.c; }), 50);
      var l20 = s20[s20.length - 1], l50 = s50[s50.length - 1];
      if (l20 !== null && l50 !== null && last !== null) {
        calcs.push("Trend (calculated): price " + f.fmtNum(last) + " vs SMA20 " +
          f.fmtNum(l20) + " vs SMA50 " + f.fmtNum(l50) + ".");
        interp.push(last > l20 && l20 > l50
          ? "Price holds above both moving averages — momentum is constructive, not a buy signal."
          : last < l20 && l20 < l50
            ? "Price sits below both moving averages — trend is weak; mean-reversion vs continuation is the open question."
            : "Price is mixed against its moving averages — trend is indecisive on this window.");
      } else {
        risks.push("Not enough history for SMA20/50 trend read.");
      }
    } else {
      risks.push("Insufficient price history for window statistics.");
      questions.push("Load a longer range (1Y/5Y) and re-run this brief.");
    }
    if (ratios && Object.keys(ratios).length) {
      var rsrc = ratios._metric_source || "Alpha Vantage overview";
      src.push("ratios:" + rsrc);
      ["PERatio", "PriceToBookRatio", "EVToEBITDA", "DividendYield", "ProfitMargin"].forEach(function (k) {
        if (ratios[k] !== undefined && ratios[k] !== null && ratios[k] !== "None" && ratios[k] !== "-")
          facts.push(k + " = " + ratios[k] + " (source: " + rsrc + ").");
      });
    } else {
      risks.push("No fundamentals feed — P/E, margins, ROE/ROCE, debt and cash cannot be verified in-terminal.");
      questions.push("Configure ALPHA_VANTAGE_API_KEY (or upload filings) to verify earnings quality and leverage.");
    }
    questions.push("What drove the largest single-day move in the window — results, guidance, or flows?");
    questions.push("Is volume confirming the price move, or diverging?");
    interp.push("Quality of the move is unverified without statements: price action alone cannot confirm earnings support.");
    var sum = recon && recon.summary;
    if (sum && sum.discrepancies > 0) {
      risks.push("PROVIDER DISCREPANCY on " + (sum.discrepancy_fields || []).join(", ") +
        " — providers disagree; treat any conclusion on these fields as INSUFFICIENT EVIDENCE until resolved.");
      questions.push("Which provider's " + (sum.discrepancy_fields || [])[0] + " figure matches the company's own filings?");
    }
    if (sum && sum.fields_compared > 0 && sum.discrepancies === 0) {
      facts.push("Cross-checked " + sum.fields_compared + " field(s) across providers with no material disagreement.");
    }
    return {
      symbol: symbol, sources: src,
      facts: facts, facts2: changed, calculations: calcs,
      interpretation: interp, questions: questions, uncertainty: risks,
      evidence: src.slice(),
    };
  }

  function renderBrief(el, b) {
    var f = fmt();
    function sec(title, pill, items, cls) {
      if (!items.length) return "";
      return '<div class="card" style="margin-top:10px"><h3>' + title + " " + pill + "</h3><ul style='margin:6px 0;padding-left:18px'>" +
        items.map(function (t) { return '<li class="' + (cls || "") + '" style="margin:4px 0">' + f.esc(t) + "</li>"; }).join("") +
        "</ul></div>";
    }
    var ev = (b.evidence && b.evidence.length ? b.evidence : b.sources) || [];
    el.innerHTML =
      '<div class="card"><h3>Research brief · ' + f.esc(b.symbol) + ' ' + f.statusPill("ai") + "</h3>" +
      '<div class="src">OBSERVE → QUESTION → HYPOTHESISE → CONNECT → VERIFY → JUDGE · sources: ' +
      f.esc((b.sources || []).join(", ") || "none") + "</div></div>" +
      sec("Key facts (source data)", f.statusPill("live"), b.facts) +
      sec("What changed", f.statusPill("live"), b.facts2 || []) +
      sec("Calculations", f.statusPill("calculated"), b.calculations) +
      sec("Why it matters (interpretation — not fact)", f.statusPill("ai"), b.interpretation) +
      sec("What to investigate", f.statusPill("ai"), b.questions) +
      sec("Risks / uncertainty", f.statusPill("unavailable"), b.uncertainty, "warn") +
      '<div class="card" style="margin-top:10px"><h3>Source evidence</h3><div class="src">' +
      (ev.length ? f.esc(ev.join(" · ")) : "INSUFFICIENT EVIDENCE — no verified inputs for this section.") + "</div></div>";
  }
  window.FT_ANALYSIS = { brief, renderBrief };
})();
