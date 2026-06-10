/* App controller: hash router, 30s poll with countdown + visibility pause,
   status row, per-view rendering. */
(function () {
  "use strict";

  const REFRESH_SEC = 30;
  const SYMBOLS = ["SPX", "SPY", "QQQ"];
  const VIEWS = ["heatmap", "strikemap", "zerodte", "flow", "sentiment"];

  const state = {
    symbol: "SPX", view: "heatmap",
    countdown: REFRESH_SEC, loading: false, abort: null,
    retries: 0, lastFetch: 0, data: null, trinity: null,
    strikemapExpiry: "ALL", flowExpiry: "ALL", flowMode: "vol",
    wakeTimer: null,
  };

  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s).replace(/[&<>"]/g,
    (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[ch]));

  /* ------------------------------ routing ------------------------------ */

  function parseHash() {
    const h = (location.hash || "").replace(/^#\/?/, "").toLowerCase();
    if (h.startsWith("trinity")) return { symbol: "TRINITY", view: null };
    const parts = h.split("/");
    const sym = (parts[0] || "spx").toUpperCase();
    const view = parts[1] || "heatmap";
    return {
      symbol: SYMBOLS.includes(sym) ? sym : "SPX",
      view: VIEWS.includes(view) ? view : "heatmap",
    };
  }

  function navigate(symbol, view) {
    location.hash = symbol === "TRINITY" ? "#/trinity"
      : "#/" + symbol.toLowerCase() + "/" + view;
  }

  function applyRoute() {
    const r = parseHash();
    const changed = r.symbol !== state.symbol || r.view !== state.view;
    state.symbol = r.symbol;
    if (r.view) state.view = r.view;
    try { localStorage.setItem("gexdash.route", location.hash); } catch (e) {}

    document.querySelectorAll("#symbolNav button").forEach((b) =>
      b.classList.toggle("active", b.dataset.symbol === state.symbol));
    document.querySelectorAll("#viewTabs button").forEach((b) =>
      b.classList.toggle("active", b.dataset.view === state.view));

    const trinity = state.symbol === "TRINITY";
    $("viewTabs").classList.toggle("hidden", trinity);
    $("statusRow").classList.toggle("hidden", trinity);
    VIEWS.forEach((v) =>
      $("panel-" + v).classList.toggle("hidden", trinity || v !== state.view));
    $("panel-trinity").classList.toggle("hidden", !trinity);

    // Guard double-refresh at startup: restoring the saved route sets
    // location.hash, which re-fires applyRoute while the first fetch runs.
    if (changed || (!state.data && !state.loading)) refresh();
    else renderAll();
  }

  /* ------------------------------ polling ------------------------------ */

  function setChip(text, cls) {
    const chip = $("refreshChip");
    chip.textContent = text;
    chip.className = "chip " + (cls || "");
  }

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
    setChip("updating…", "busy");

    const isFirst = !state.data && !state.trinity;
    if (isFirst) {
      if (state.wakeTimer) clearTimeout(state.wakeTimer);  // no orphan timers
      state.wakeTimer = setTimeout(() =>
        banner("Waking the free server — first load can take up to a minute…", "info"), 3000);
      document.body.classList.add("first-load");
    }

    try {
      if (state.symbol === "TRINITY") {
        state.trinity = await Api.fetchTrinity(
          { signal: ctrl.signal, timeout: isFirst ? 90000 : 30000 });
      } else {
        state.data = await Api.fetchSnapshot(
          state.symbol, state.view === "heatmap" ? "heatmap" : state.view,
          { signal: ctrl.signal, timeout: isFirst ? 90000 : 30000 });
      }
      state.retries = 0;
      state.countdown = REFRESH_SEC;
      banner(null);
      renderAll();
    } catch (e) {
      if (ctrl.signal.aborted) return;
      state.retries += 1;
      const wait = Math.min(5 * Math.pow(2, state.retries - 1), 20);
      state.countdown = wait;
      banner("Data fetch failed — retrying in " + wait + "s", "error");
      setChip("retry " + wait + "s", "error");
    } finally {
      if (state.wakeTimer) { clearTimeout(state.wakeTimer); state.wakeTimer = null; }
      document.body.classList.remove("first-load");
      if (state.abort === ctrl) state.abort = null;
      state.loading = false;
      state.lastFetch = Date.now();
    }
  }

  setInterval(() => {
    if (document.hidden || state.loading) return;
    state.countdown -= 1;
    if (state.countdown <= 0) { refresh(); return; }
    if (state.retries === 0) setChip("↻ " + state.countdown + "s");
  }, 1000);

  document.addEventListener("visibilitychange", () => {
    if (!document.hidden &&
        Date.now() - state.lastFetch > REFRESH_SEC * 1000) refresh();
  });

  /* ----------------------------- rendering ----------------------------- */

  function chipHtml(label, value, extraCls, valueCls) {
    return '<div class="schip ' + (extraCls || "") + '"><span class="k">' + label +
      '</span><span class="v ' + (valueCls || "") + '">' + value + "</span></div>";
  }

  function renderStatus() {
    const d = state.data;
    if (!d) return;
    const s = d.status, m = d.meta;
    const chgCls = s.change_pct >= 0 ? "pos" : "neg";
    const gexCls = s.total_gex_bn >= 0 ? "pos" : "neg";
    const sentiCls = s.sentiment_score >= 15 ? "pos"
      : s.sentiment_score <= -15 ? "neg" : "";
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
    html += chipHtml("Sentiment", s.sentiment_score.toFixed(0) +
      " · " + esc(s.sentiment_label), "", sentiCls);
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
      (k === "ALL" ? "All expirations" : Fmt.fmtExpiry(k)) + "</option>").join("");
  }

  function renderHeatmapView() {
    const hm = state.data.views.heatmap;
    if (hm) Charts.renderHeatmap($("chart-heatmap"), hm, state.data.status);
  }

  function renderStrikemapView() {
    const sm = state.data.views.strikemap;
    if (!sm) return;
    if (!sm.by_expiry[state.strikemapExpiry]) state.strikemapExpiry = "ALL";
    fillExpirySelect($("expirySelect"), sm.expiries, state.strikemapExpiry);
    const cur = sm.by_expiry[state.strikemapExpiry];
    const lv = levelsFromStatus(state.strikemapExpiry === "ALL" ? {} : cur);
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
    if (!f.by_expiry[state.flowExpiry]) state.flowExpiry = "ALL";
    fillExpirySelect($("flowExpirySelect"), f.expiries, state.flowExpiry);
    document.querySelectorAll("#flowModeBtns button").forEach((b) =>
      b.classList.toggle("active", b.dataset.mode === state.flowMode));

    const cur = f.by_expiry[state.flowExpiry];
    const rows = state.flowMode === "vol"
      ? cur.rows.map((r) => [r[0], r[1], -r[2]])
      : cur.rows.map((r) => [r[0], r[3], -r[4]]);
    Charts.renderTornado($("chart-flow"), rows,
      { spot: state.data.status.spot },
      { fmt: state.flowMode === "vol" ? "count" : "money", showNet: false });

    const t = f.totals;
    $("flowTotals").innerHTML =
      chipHtml("Call Vol", Fmt.fmtCount(cur.call_vol), "", "pos") +
      chipHtml("Put Vol", Fmt.fmtCount(cur.put_vol), "", "neg") +
      chipHtml("Call Prem", Fmt.fmtM(cur.call_prem_m), "", "pos") +
      chipHtml("Put Prem", Fmt.fmtM(cur.put_prem_m), "", "neg") +
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
    Charts.renderGauge($("chart-gauge"), sn.score, sn.label);

    $("sentiComponents").innerHTML =
      "<tr><th>Component</th><th>Raw</th><th>Score</th><th>Weight</th><th>Contrib</th></tr>" +
      sn.components.map((c) => {
        const cls = c.score > 0 ? "pos" : c.score < 0 ? "neg" : "";
        return "<tr><td>" + esc(c.label) + "</td><td>" + c.raw +
          '</td><td class="' + cls + '">' + c.score.toFixed(0) +
          "</td><td>" + (c.weight * 100).toFixed(0) + "%</td><td>" +
          c.contribution.toFixed(1) + "</td></tr>";
      }).join("");

    const mm = sn.metrics;
    const card = (k, v, cls) =>
      '<div class="card metric"><div class="k">' + k +
      '</div><div class="v ' + (cls || "") + '">' + v + "</div></div>";
    $("sentiMetrics").innerHTML =
      card("VIX", (mm.vix === null ? "—" : mm.vix) +
        ' <small class="' + (mm.vix_change_pct > 0 ? "neg" : "pos") + '">' +
        Fmt.fmtPct(mm.vix_change_pct) + "</small>") +
      card("IV30", mm.iv30 + ' <small class="' +
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

  function renderTrinity() {
    const t = state.trinity;
    if (!t) return;
    const ag = $("trinityAgreement");
    ag.textContent = t.agreement.label;
    ag.className = "banner " + (t.agreement.aligned ? "ok" : "warn-banner");

    const grid = $("trinityGrid");
    const cols = Object.keys(t.symbols);
    grid.innerHTML = cols.map((sym) => {
      const s = t.symbols[sym];
      const chg = s.change_pct >= 0 ? "pos" : "neg";
      const reg = s.regime === "positive" ? "pos" : "neg";
      return '<div class="card tcol">' +
        '<div class="thead"><b>' + sym + "</b> <span>" + Fmt.fmtStrike(s.spot) +
        '</span> <small class="' + chg + '">' + Fmt.fmtPct(s.change_pct) + "</small></div>" +
        '<div class="tmeta">' +
        '<div>Regime <b class="' + reg + '">' + s.regime + "</b></div>" +
        "<div>Net GEX <b>" + Fmt.fmtBn(s.net_gex_bn) + "</b></div>" +
        "<div>Flip <b>" + Fmt.fmtStrike(s.flip) + "</b> <small>(" +
          Fmt.fmtPct(s.flip_pct) + ")</small></div>" +
        '<div>Call Wall <b class="pos">' + Fmt.fmtStrike(s.call_wall) +
          "</b> <small>(" + Fmt.fmtPct(s.call_wall_pct) + ")</small></div>" +
        '<div>Put Wall <b class="neg">' + Fmt.fmtStrike(s.put_wall) +
          "</b> <small>(" + Fmt.fmtPct(s.put_wall_pct) + ")</small></div>" +
        "<div>Sentiment <b>" + s.sentiment_score.toFixed(0) + " · " +
          esc(s.sentiment_label) + "</b></div>" +
        "</div>" +
        '<div class="chart-box" id="chart-trinity-' + sym + '"></div>' +
        "</div>";
    }).join("");
    cols.forEach((sym) =>
      Charts.renderTrinityMini($("chart-trinity-" + sym),
        t.symbols[sym].mini_rows));
  }

  function renderAll() {
    if (state.symbol === "TRINITY") { renderTrinity(); return; }
    if (!state.data) return;
    renderStatus();
    if (state.view === "heatmap") renderHeatmapView();
    else if (state.view === "strikemap") renderStrikemapView();
    else if (state.view === "zerodte") renderZeroDteView();
    else if (state.view === "flow") renderFlowView();
    else if (state.view === "sentiment") renderSentimentView();
  }

  /* ------------------------------ wiring ------------------------------ */

  document.querySelectorAll("#symbolNav button").forEach((b) =>
    b.addEventListener("click", () => {
      state.data = null;  // force refetch for the new symbol
      navigate(b.dataset.symbol, state.view || "heatmap");
    }));
  document.querySelectorAll("#viewTabs button").forEach((b) =>
    b.addEventListener("click", () => {
      const needsFetch = !state.data ||
        !state.data.views[b.dataset.view === "heatmap" ? "heatmap" : b.dataset.view];
      if (needsFetch) state.data = null;
      navigate(state.symbol, b.dataset.view);
    }));
  $("expirySelect").addEventListener("change", (e) => {
    state.strikemapExpiry = e.target.value; renderStrikemapView();
  });
  $("flowExpirySelect").addEventListener("change", (e) => {
    state.flowExpiry = e.target.value; renderFlowView();
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
