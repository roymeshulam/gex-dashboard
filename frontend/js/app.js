/* App controller: hash router, data loading, status row, per-view rendering. */
(function () {
  "use strict";

  const VIEWS = ["heatmap", "strikemap", "zerodte", "flow", "greeks", "sentiment", "volatility"];

  const state = {
    view: "heatmap",
    loading: false, abort: null, data: null,
    strikemapExpiry: null, flowExpiry: null, flowMode: "vol",
    greeksExpiry: null, greeksStrike: null, greeksCp: "C", greeksPosition: "long",
    greeksRequest: 0,
    greeksAbort: null,
  };

  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s).replace(/[&<>"]/g,
    (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[ch]));

  /* ------------------------------ routing ------------------------------ */

  function parseHash() {
    const h = (location.hash || "").replace(/^#\/?/, "").toLowerCase();
    const parts = h.split("/");
    const view = parts[0] === "spx" ? parts[1] : parts[0];
    return VIEWS.includes(view) ? view : "heatmap";
  }

  function navigate(view) {
    location.hash = "#/" + view;
  }

  function applyRoute() {
    const view = parseHash();
    const changed = view !== state.view;
    if (changed && view !== "greeks" && state.greeksAbort) state.greeksAbort.abort();
    if (changed && view !== "greeks") state.greeksRequest++;
    state.view = view;
    try { localStorage.setItem("gexdash.route", location.hash); } catch (e) {}

    document.querySelectorAll("#viewTabs button").forEach((b) =>
      b.classList.toggle("active", b.dataset.view === state.view));

    VIEWS.forEach((v) =>
      $("panel-" + v).classList.toggle("hidden", v !== state.view));

    // Guard double-refresh at startup: restoring the saved route sets
    // location.hash, which re-fires applyRoute while the first fetch runs.
    if (changed || (!state.data && !state.loading)) refresh();
    else renderAll();
  }

  /* ---------------------------- data loading ---------------------------- */

  function banner(msg, cls) {
    const el = $("banner");
    if (!msg) { el.classList.add("hidden"); return; }
    el.textContent = msg;
    el.className = "banner " + (cls || "");
  }

  async function refresh() {
    if (state.abort) state.abort.abort();
    const ctrl = new AbortController();
    state.abort = ctrl;
    state.loading = true;

    const isFirst = !state.data;
    if (isFirst) {
      document.body.classList.add("first-load");
    }

    try {
      const previousTimestamp = state.data && state.data.meta.data_timestamp;
      const data = await Api.fetchSnapshot(
        state.view === "heatmap" ? "heatmap" : state.view,
        { signal: ctrl.signal, timeout: isFirst ? 90000 : 30000 });
      const hasNewData = isFirst || data.meta.data_timestamp !== previousTimestamp;
      state.data = data;
      banner(null);
      if (hasNewData) renderAll();
    } catch (e) {
      if (ctrl.signal.aborted) return;
      console.error("Dashboard refresh failed", e);
      const message = window.echarts
        ? "Data fetch failed — reload the page to try again"
        : "Chart library failed to load — reload the page to try again";
      banner(message, "error");
    } finally {
      document.body.classList.remove("first-load");
      if (state.abort === ctrl) state.abort = null;
      state.loading = false;
    }
  }

  /* ----------------------------- rendering ----------------------------- */

  function chipHtml(label, value, extraCls, valueCls) {
    return '<div class="schip ' + (extraCls || "") + '"><span class="k">' + label +
      '</span><span class="v ' + (valueCls || "") + '">' + value + "</span></div>";
  }

  function renderStatus() {
    const d = state.data;
    if (!d) return;
    const s = d.status, m = d.meta;
    const chgCls = s.change_pct === null ? "" : s.change_pct >= 0 ? "pos" : "neg";
    const gexCls = s.total_gex_bn >= 0 ? "pos" : "neg";
    const directionCls = s.direction_score === null ? ""
      : s.direction_score >= 15 ? "pos" : s.direction_score <= -15 ? "neg" : "";
    const volatilityCls = s.volatility_score === null ? "warn"
      : s.volatility_score >= 15 ? "neg" : s.volatility_score <= -15 ? "pos" : "";
    let html = "";
    html += chipHtml(d.symbol, Fmt.fmtStrike(s.spot) +
      ' <small class="' + chgCls + '">' + Fmt.fmtPct(s.change_pct) + "</small>");
    html += chipHtml("Net GEX", Fmt.fmtBn(s.total_gex_bn), "", gexCls);
    html += chipHtml("Regime", s.regime === "positive" ? "POSITIVE γ" : "NEGATIVE γ",
      "", s.regime === "positive" ? "pos" : "neg");
    html += chipHtml("Gamma Flip", Fmt.fmtStrike(s.flip));
    html += chipHtml("Call Wall", Fmt.fmtStrike(s.call_wall), "", "pos");
    html += chipHtml("Put Wall", Fmt.fmtStrike(s.put_wall), "", "neg");
    html += chipHtml("Call Δ", Fmt.fmtBn(s.call_dex_bn));
    html += chipHtml("Put Δ", Fmt.fmtBn(s.put_dex_bn));
    html += chipHtml("P/C Vol", s.pcr_vol === null ? "—" : s.pcr_vol.toFixed(2));
    html += chipHtml("IV30", s.iv30 === null ? "—" : s.iv30.toFixed(1));
    html += chipHtml("Direction", s.direction_score === null ? "—" :
      s.direction_score.toFixed(0) + " · " + esc(s.direction_label), "", directionCls);
    html += chipHtml("Volatility", s.volatility_score === null ? "—" :
      s.volatility_score.toFixed(0) + " · " + esc(s.volatility_label), "", volatilityCls);
    html += chipHtml("Confidence", esc(s.confidence || "—"),
      s.confidence === "Medium" ? "" : "warn",
      s.confidence === "Medium" ? "" : "warn");
    const mkt = m.market || {};
    html += chipHtml("Market", esc((mkt.session || "?").toUpperCase()) +
      " · " + esc(mkt.ny_time || "") + " ET");
    let fresh = m.freshness || "";
    if (m.stale) fresh += " · stale " + Math.round(m.cache_age_sec) + "s";
    html += chipHtml("Data", esc(fresh),
      m.stale ? "warn" : "", m.stale ? "warn" : "");
    $("statusRow").innerHTML = html;
  }

  function levelsFromStatus(over) {
    const s = state.data.status;
    over = over || {};
    return {
      spot: s.spot,
      flip: over.flip !== undefined ? over.flip : s.flip,
      call_wall: over.call_wall !== undefined ? over.call_wall : s.call_wall,
      put_wall: over.put_wall !== undefined ? over.put_wall : s.put_wall,
    };
  }

  function levelChips(el, lv) {
    el.innerHTML =
      chipHtml("Spot", Fmt.fmtStrike(lv.spot)) +
      chipHtml("Flip", Fmt.fmtStrike(lv.flip), "", "warn") +
      chipHtml("Call Wall", Fmt.fmtStrike(lv.call_wall), "", "pos") +
      chipHtml("Put Wall", Fmt.fmtStrike(lv.put_wall), "", "neg");
  }

  function fillExpirySelect(sel, keys, current) {
    sel.innerHTML = keys.map((k) =>
      '<option value="' + k + '"' + (k === current ? " selected" : "") + ">" +
      Fmt.fmtExpiryDte(k) + "</option>").join("");
  }

  function renderHeatmapView() {
    const hm = state.data.views.heatmap;
    if (hm) Charts.renderHeatmap($("chart-heatmap"), hm, state.data.status);
  }

  function renderStrikemapView() {
    const sm = state.data.views.strikemap;
    if (!sm) return;
    if (!sm.expiries.includes(state.strikemapExpiry)) state.strikemapExpiry = sm.expiries[0];
    if (!state.strikemapExpiry) return;
    fillExpirySelect($("expirySelect"), sm.expiries, state.strikemapExpiry);
    const cur = sm.by_expiry[state.strikemapExpiry];
    const lv = levelsFromStatus(cur);
    levelChips($("strikemapLevels"), lv);
    Charts.renderTornado($("chart-strikemap"), cur.rows, lv,
      { fmt: "money", showNet: true });

    const mkRows = (arr, cls) => arr.map((r) =>
      "<tr><td>" + Fmt.fmtStrike(r[0]) + '</td><td class="' + cls + '">' +
      Fmt.fmtM(r[1]) + "</td></tr>").join("");
    $("topPos").innerHTML = "<tr><th>Strike</th><th>Net GEX</th></tr>" +
      (mkRows(sm.top_pos, "pos") || '<tr><td colspan="2">—</td></tr>');
    $("topNeg").innerHTML = "<tr><th>Strike</th><th>Net GEX</th></tr>" +
      (mkRows(sm.top_neg, "neg") || '<tr><td colspan="2">—</td></tr>');
    Charts.renderMiniBar($("chart-gexbyexp"), sm.gex_by_expiry);
  }

  function renderZeroDteView() {
    const z = state.data.views.zerodte;
    if (!z) return;
    const empty = $("zerodteEmpty"), full = $("zerodteContent");
    if (!z.available) {
      empty.textContent = "No 0DTE expiration trading today." +
        (z.next_expiry ? " Next expiration: " + Fmt.fmtExpiry(z.next_expiry) : "");
      empty.classList.remove("hidden");
      full.classList.add("hidden");
      return;
    }
    empty.classList.add("hidden");
    full.classList.remove("hidden");
    const lv = levelsFromStatus(z);
    levelChips($("zerodteLevels"), lv);
    $("zerodteStats").innerHTML =
      chipHtml("0DTE Volume", Fmt.fmtCount(z.stats.dte_volume)) +
      chipHtml("Share of chain", z.stats.dte_share_pct + "%") +
      chipHtml("0DTE Net GEX", Fmt.fmtM(z.stats.dte_net_gex_m), "",
        z.stats.dte_net_gex_m >= 0 ? "pos" : "neg") +
      chipHtml("Expiry", Fmt.fmtExpiry(z.expiry));
    Charts.renderTornado($("chart-zerodte"), z.rows, lv,
      { fmt: "money", showNet: true });
  }

  function renderFlowView() {
    const f = state.data.views.flow;
    if (!f) return;
    if (!f.expiries.includes(state.flowExpiry)) state.flowExpiry = f.expiries[0];
    if (!state.flowExpiry) return;
    fillExpirySelect($("flowExpirySelect"), f.expiries, state.flowExpiry);
    document.querySelectorAll("#flowModeBtns button").forEach((b) =>
      b.classList.toggle("active", b.dataset.mode === state.flowMode));

    const cur = f.by_expiry[state.flowExpiry];
    const rowIndexes = {
      vol: [1, 2], prem: [3, 4], oi: [5, 6], spread: [7, 8],
    };
    const indexes = rowIndexes[state.flowMode] || rowIndexes.vol;
    const rows = cur.rows.map((r) => [r[0], r[indexes[0]], r[indexes[1]]]);
    const fmt = state.flowMode === "spread" ? "price"
      : state.flowMode === "prem" ? "money"
        : "count";
    Charts.renderTornado($("chart-flow"), rows,
      {
        spot: state.data.status.spot,
        expected_move_lower: cur.expected_move ? cur.expected_move.lower : null,
        expected_move_upper: cur.expected_move ? cur.expected_move.upper : null,
        sd_lower: cur.expected_move ? cur.expected_move.sd_lower : null,
        sd_upper: cur.expected_move ? cur.expected_move.sd_upper : null,
      },
      { fmt, showNet: false });

    const t = f.totals;
    $("flowTotals").innerHTML =
      chipHtml("STRADDLE", Fmt.fmtPrice(
        cur.expected_move ? cur.expected_move.straddle : null)) +
      chipHtml("ATM IV", cur.expected_move && cur.expected_move.atm_iv_pct !== null
        ? cur.expected_move.atm_iv_pct.toFixed(2) + "%" : "—") +
      chipHtml("1 SD MOVE", Fmt.fmtPrice(
        cur.expected_move ? cur.expected_move.standard_deviation : null)) +
      chipHtml("Call Vol", Fmt.fmtCount(cur.call_vol)) +
      chipHtml("Put Vol", Fmt.fmtCount(cur.put_vol)) +
      chipHtml("Call Prem", Fmt.fmtM(cur.call_prem_m)) +
      chipHtml("Put Prem", Fmt.fmtM(cur.put_prem_m)) +
      chipHtml("Buy-side Prem", Fmt.fmtM(t.prem_buy_m)) +
      chipHtml("Sell-side Prem", Fmt.fmtM(t.prem_sell_m));

    $("topTrades").innerHTML =
      "<tr><th>Contract</th><th>Vol</th><th>Last</th><th>Premium</th><th>Side</th></tr>" +
      f.top_trades.map((tr) => {
        const sideCls = tr.side === "buy" ? "pos" : tr.side === "sell" ? "neg" : "";
        return "<tr><td>" + Fmt.fmtStrike(tr.strike) + tr.cp + " " +
          Fmt.fmtExpiry(tr.expiry) + "</td><td>" + Fmt.fmtCount(tr.volume) +
          "</td><td>" + tr.last.toFixed(2) + "</td><td>" + Fmt.fmtM(tr.premium_m) +
          '</td><td class="' + sideCls + '">' + tr.side + "</td></tr>";
      }).join("");
  }

  function renderSentimentView() {
    const sn = state.data.views.sentiment;
    if (!sn) return;
    const direction = sn.direction || { score: sn.score, label: sn.label, components: [] };
    const volatility = sn.volatility || { score: null, label: "Insufficient data", components: [] };
    Charts.renderGauge($("chart-direction"), direction.score, direction.label);
    Charts.renderGauge($("chart-volatility"), volatility.score, volatility.label,
      { positiveIsRisk: true });

    $("sentiComponents").innerHTML =
      "<tr><th>Type</th><th>Component</th><th>Raw</th><th>Score</th><th>Effective weight</th><th>Contrib</th></tr>" +
      sn.components.map((c) => {
        const riskScore = c.group === "volatility";
        const cls = c.score > 0 ? (riskScore ? "neg" : "pos")
          : c.score < 0 ? (riskScore ? "pos" : "neg") : "";
        return "<tr><td>" + esc(c.group === "volatility" ? "Volatility" : "Direction") +
          "</td><td><span class=\"component-help\" tabindex=\"0\" title=\"" +
          esc(c.description || "No explanation available.") + "\" aria-label=\"" +
          esc(c.label + ". " + (c.description || "No explanation available.")) +
          "\">" + esc(c.label) + " <span class=\"help-icon\" aria-hidden=\"true\">ⓘ</span></span></td><td>" + c.raw +
          '</td><td class="' + cls + '">' + c.score.toFixed(0) +
          "</td><td>" + ((c.effective_weight || 0) * 100).toFixed(0) + "%</td><td>" +
          c.contribution.toFixed(1) + "</td></tr>";
      }).join("");

    const confidence = sn.confidence || { level: "—", disclosures: [] };
    $("sentiConfidence").innerHTML =
      '<div class="confidence-summary">Data confidence: <b class="' +
      (confidence.level === "Medium" ? "" : "warn") + '">' +
      esc(confidence.level) + "</b> · Direction coverage " +
      (direction.coverage_pct === undefined ? "—" : direction.coverage_pct + "%") +
      " · Volatility coverage " +
      (volatility.coverage_pct === undefined ? "—" : volatility.coverage_pct + "%") +
      "%</div><ul>" + (confidence.disclosures || []).map((item) =>
        "<li>" + esc(item) + "</li>").join("") + "</ul>";

    const mm = sn.metrics;
    const card = (k, v, cls) =>
      '<div class="card metric"><div class="k">' + k +
      '</div><div class="v ' + (cls || "") + '">' + v + "</div></div>";
    $("sentiMetrics").innerHTML =
      card("VIX", (mm.vix === null ? "—" : mm.vix) +
        ' <small class="' + (mm.vix_change_pct > 0 ? "neg" : "pos") + '">' +
        Fmt.fmtPct(mm.vix_change_pct) + "</small>") +
      card("IV30", (mm.iv30 === null ? "—" : mm.iv30) + ' <small class="' +
        (mm.iv30_change_pct > 0 ? "neg" : "pos") + '">' +
        Fmt.fmtPct(mm.iv30_change_pct) + "</small>") +
      card("Max Pain (" + Fmt.fmtExpiry(mm.max_pain_expiry) + ")",
        Fmt.fmtStrike(mm.max_pain)) +
      card("0DTE Volume Share", mm.zero_dte_share_pct + "%") +
      card("Net GEX", Fmt.fmtBn(mm.net_gex_bn),
        mm.net_gex_bn >= 0 ? "pos" : "neg") +
      card("Gamma Regime", mm.regime.toUpperCase(),
        mm.regime === "positive" ? "pos" : "neg") +
      card("Dist. to Flip", Fmt.fmtPct(mm.flip_dist_pct)) +
      card("P/C OI", mm.pcr_oi === null ? "—" : mm.pcr_oi);
  }

  function renderVolatilityView() {
    const vol = state.data.views.volatility;
    if (!vol) return;
    Charts.renderIvTermStructure($("chart-iv-term"), vol.term_structure || []);
    Charts.renderExpectedMoveTermStructure(
      $("chart-expected-move-term"), vol.expected_move_term_structure || []);
  }

  function greeksRows() {
    const surface = state.data.views.greeks;
    return surface && state.greeksExpiry
      ? surface.by_expiry[state.greeksExpiry].rows : [];
  }

  function setGreeksStrikeOptions() {
    const select = $("greeksStrikeSelect");
    const ivIndex = state.greeksCp === "C" ? 1 : 2;
    const strikes = greeksRows().filter((row) => row[ivIndex] !== null).map((row) => row[0]);
    if (!strikes.length) { select.innerHTML = ""; return false; }
    if (!strikes.includes(Number(state.greeksStrike))) {
      const spot = state.data.status.spot;
      state.greeksStrike = strikes.reduce((best, value) =>
        Math.abs(value - spot) < Math.abs(best - spot) ? value : best, strikes[0]);
    }
    select.innerHTML = strikes.map((strike) =>
      '<option value="' + strike + '"' + (strike === Number(state.greeksStrike) ? " selected" : "") +
      ">" + Fmt.fmtStrike(strike) + "</option>").join("");
    return true;
  }

  function syncGreeksTypeToggle() {
    const toggle = $("greeksTypeToggle");
    const isCall = state.greeksCp === "C";
    toggle.textContent = isCall ? "Call" : "Put";
    toggle.setAttribute("aria-label", "Option type: " + (isCall ? "Call" : "Put") +
      ". Click to show " + (isCall ? "puts" : "calls"));
  }

  function syncGreeksPositionToggle() {
    const toggle = $("greeksPositionToggle");
    const isLong = state.greeksPosition === "long";
    toggle.textContent = isLong ? "Long" : "Short";
    toggle.setAttribute("aria-label", "Position: " + (isLong ? "Long" : "Short") +
      ". Click to show " + (isLong ? "short" : "long") + " exposure");
  }

  function nextAnimationFrame() {
    return new Promise((resolve) => requestAnimationFrame(resolve));
  }

  async function renderGreeksCharts(data, axes, metricOptions, request) {
    const jobs = [];
    Object.keys(metricOptions).forEach((metric) => {
      const metricConfig = metricOptions[metric];
      Object.keys(axes).forEach((axis) => {
        const axisConfig = axes[axis];
        const id = metric === "price" ? "chart-greeks-" + axisConfig.suffix
          : "chart-" + metric + "-" + axisConfig.suffix;
        jobs.push(() => Charts.renderPriceCurve($(id), data.curves[metric][axis], {
          xLabel: axisConfig.label, actualX: axisConfig.actual,
          xFormatter: axisConfig.formatter, yLabel: metricConfig.label,
          yFormatter: metricConfig.formatter, nonnegative: metricConfig.nonnegative,
          inverse: axisConfig.inverse, xMin: axisConfig.min, xMax: axisConfig.max,
          showCurrent: axisConfig.showCurrent,
        }));
      });
    });

    const chartsPerFrame = 3;
    for (let index = 0; index < jobs.length; index += chartsPerFrame) {
      if (request !== state.greeksRequest || state.view !== "greeks") return;
      jobs.slice(index, index + chartsPerFrame).forEach((job) => job());
      if (index + chartsPerFrame < jobs.length) await nextAnimationFrame();
    }
  }

  async function renderGreeksView() {
    const surface = state.data.views.greeks;
    if (!surface || !surface.expiries.length) return;
    if (!surface.expiries.includes(state.greeksExpiry)) state.greeksExpiry = surface.expiries[0];
    fillExpirySelect($("greeksExpirySelect"), surface.expiries, state.greeksExpiry);
    syncGreeksTypeToggle();
    syncGreeksPositionToggle();
    if (!setGreeksStrikeOptions()) return;

    const request = ++state.greeksRequest;
    if (state.greeksAbort) state.greeksAbort.abort();
    const ctrl = new AbortController();
    state.greeksAbort = ctrl;
    const selectedExpiry = state.greeksExpiry;
    const selectedDte = surface.by_expiry[selectedExpiry].dte;
    try {
      const data = await Api.fetchGreeks(
        selectedExpiry, state.greeksStrike, state.greeksCp, state.greeksPosition,
        { signal: ctrl.signal, timeout: 30000 });
      if (request !== state.greeksRequest || state.view !== "greeks" ||
          data.expiry !== selectedExpiry) return;
      state.greeksStrike = data.strike;
      $("greeksBasis").innerHTML =
        chipHtml("SPOT", Fmt.fmtStrike(data.spot)) +
        chipHtml("DTE", data.dte) +
        chipHtml("IMPLIED VOL", data.iv_pct.toFixed(2) + "%") +
        chipHtml("RATE", data.rate_pct.toFixed(2) + "%");
      const isLong = data.position === "long";
      const metricOptions = {
        price: { label: "Position value", formatter: Fmt.fmtPrice, nonnegative: isLong },
        delta: { label: "Delta", formatter: (value) => Number(value).toFixed(3) },
        gamma: { label: "Gamma", formatter: (value) => Number(value).toFixed(5), nonnegative: isLong },
        theta: { label: "Theta / day", formatter: (value) => Number(value).toFixed(2) },
        vega: { label: "Vega / 1% IV", formatter: (value) => Number(value).toFixed(2), nonnegative: isLong },
      };
      const axes = {
        spot: { suffix: "spot", label: "Spot", actual: data.spot, formatter: Fmt.fmtStrike,
          min: data.spot_lower, max: data.spot_upper },
        volatility: { suffix: "vol", label: "Implied volatility", actual: data.iv_pct,
          formatter: (value) => Number(value).toFixed(1) + "%" },
        time: { suffix: "time", label: "Days to expiry", actual: null,
          formatter: (value) => value + "d", min: 0, max: selectedDte,
          showCurrent: false },
      };
      await renderGreeksCharts(data, axes, metricOptions, request);
    } catch (error) {
      if (error.name !== "AbortError" && request === state.greeksRequest) {
        banner("Unable to calculate option curves: " + error.message, "error");
      }
    } finally {
      if (state.greeksAbort === ctrl) state.greeksAbort = null;
    }
  }

  function renderAll() {
    if (!state.data) return;
    renderStatus();
    if (state.view === "heatmap") renderHeatmapView();
    else if (state.view === "strikemap") renderStrikemapView();
    else if (state.view === "zerodte") renderZeroDteView();
    else if (state.view === "flow") renderFlowView();
    else if (state.view === "sentiment") renderSentimentView();
    else if (state.view === "volatility") renderVolatilityView();
    else if (state.view === "greeks") renderGreeksView();
  }

  /* ------------------------------ wiring ------------------------------ */

  document.querySelectorAll("#viewTabs button").forEach((b) =>
    b.addEventListener("click", () => {
      const needsFetch = !state.data ||
        !state.data.views[b.dataset.view === "heatmap" ? "heatmap" : b.dataset.view];
      if (needsFetch) state.data = null;
      navigate(b.dataset.view);
    }));
  $("expirySelect").addEventListener("change", (e) => {
    state.strikemapExpiry = e.target.value; renderStrikemapView();
  });
  $("flowExpirySelect").addEventListener("change", (e) => {
    state.flowExpiry = e.target.value; renderFlowView();
  });
  $("greeksExpirySelect").addEventListener("change", (e) => {
    state.greeksExpiry = e.target.value; state.greeksStrike = null; renderGreeksView();
  });
  $("greeksStrikeSelect").addEventListener("change", (e) => {
    state.greeksStrike = Number(e.target.value); renderGreeksView();
  });
  $("greeksTypeToggle").addEventListener("click", () => {
    state.greeksCp = state.greeksCp === "C" ? "P" : "C";
    state.greeksStrike = null;
    renderGreeksView();
  });
  $("greeksPositionToggle").addEventListener("click", () => {
    state.greeksPosition = state.greeksPosition === "long" ? "short" : "long";
    renderGreeksView();
  });
  document.querySelectorAll("#flowModeBtns button").forEach((b) =>
    b.addEventListener("click", () => {
      state.flowMode = b.dataset.mode; renderFlowView();
    }));
  window.addEventListener("hashchange", applyRoute);
  // Re-render when crossing the mobile/desktop breakpoint (phone rotation,
  // resized panes) so width-dependent chart options like cell labels update.
  let lastNarrow = window.innerWidth <= 768;
  function breakpointCheck() {
    const narrow = window.innerWidth <= 768;
    if (narrow !== lastNarrow) { lastNarrow = narrow; renderAll(); }
  }
  window.addEventListener("resize", breakpointCheck);
  try {
    window.matchMedia("(max-width: 768px)")
      .addEventListener("change", breakpointCheck);
  } catch (e) {}

  if (!location.hash) {
    let saved = null;
    try { saved = localStorage.getItem("gexdash.route"); } catch (e) {}
    if (saved) location.hash = saved;
  }
  applyRoute();
})();
