/* ECharts builders: GEX heatmap, strike tornado, sentiment gauge, mini bars.
   One chart instance per container element, resized on window resize. */
(function () {
  "use strict";

  const GREEN = "#089981";
  const RED = "#f23645";
  const AMBER = "#f5a623";
  const TEXT = "#d7dde8";
  const MUTED = "#7a849a";
  const BG_CELL = "#141927";

  const instances = {};

  function chart(el, heightPx) {
    if (heightPx) el.style.height = heightPx + "px";
    let inst = instances[el.id];
    if (!inst) {
      inst = echarts.init(el, null, { renderer: "canvas" });
      instances[el.id] = inst;
    }
    return inst;
  }

  window.addEventListener("resize", () => {
    Object.values(instances).forEach((c) => c.resize());
  });

  function baseText() {
    return { color: TEXT, fontSize: 11 };
  }

  function nearestLabel(strikes, level) {
    if (level === null || level === undefined || !strikes.length) return null;
    let best = strikes[0];
    for (const s of strikes) if (Math.abs(s - level) < Math.abs(best - level)) best = s;
    return Fmt.fmtStrike(best);
  }

  /* ---------------- GEX heatmap (strikes x expirations) ---------------- */

  function renderHeatmap(el, hm, status, attempt) {
    // The container can be 0-wide before first layout (hidden panel, preview
    // panes). Width drives label format, so wait for a real measurement.
    const w = el.clientWidth || document.body.clientWidth;
    if (!w && (attempt || 0) < 10) {
      setTimeout(() => renderHeatmap(el, hm, status, (attempt || 0) + 1), 120);
      return;
    }
    const rows = hm.strikes.length;
    const mobile = (w || window.innerWidth) <= 768;
    // Taller rows when labels are printed in the cells.
    const inst = chart(el, Math.max(420, rows * (mobile ? 16 : 19) + 130));
    const yLabels = hm.strikes.map(Fmt.fmtStrike);
    const xLabels = hm.expiries.map(Fmt.fmtExpiry);
    const spotLabel = hm.spot_row !== null ? yLabels[hm.spot_row] : null;

    // Clip the color scale at the ~88th percentile of |GEX| so a single
    // monster wall cell doesn't wash out the rest of the map.
    const absVals = hm.cells.map((c) => Math.abs(c[2])).sort((a, b) => a - b);
    const p88 = absVals.length
      ? absVals[Math.min(absVals.length - 1, Math.floor(absVals.length * 0.88))]
      : 1;
    const vmax = Math.max(p88, 1);
    // dims: [x, y, clamped (drives color), raw (shown in tooltip/label)]
    const cells = hm.cells.map((c) =>
      [c[0], c[1], Math.max(-vmax, Math.min(vmax, c[2])), c[2]]);

    inst.setOption({
      animation: false,
      grid: { left: 64, right: 14, top: 14, bottom: 78 },
      tooltip: {
        backgroundColor: "#11151f", borderColor: "#1d2433",
        textStyle: baseText(),
        formatter: (p) =>
          "<b>" + yLabels[p.value[1]] + "</b> × " + xLabels[p.value[0]] +
          "<br>GEX: <b>" + Fmt.fmtM(p.value[3]) + "</b>",
      },
      xAxis: {
        type: "category", data: xLabels,
        axisLabel: { color: MUTED, rotate: 45, fontSize: 10 },
        axisLine: { lineStyle: { color: "#1d2433" } },
        splitArea: { show: false },
      },
      yAxis: {
        type: "category", data: yLabels, inverse: true,
        axisLabel: {
          color: (v) => (v === spotLabel ? "#ffffff" : MUTED),
          fontSize: 10,
        },
        axisLine: { lineStyle: { color: "#1d2433" } },
      },
      visualMap: {
        type: "continuous", min: -vmax, max: vmax, dimension: 2,
        orient: "horizontal", left: "center", bottom: 2, itemHeight: 110,
        text: ["+GEX", "−GEX"], textStyle: { color: MUTED, fontSize: 10 },
        inRange: { color: [RED, BG_CELL, GREEN] },
      },
      series: [{
        type: "heatmap",
        data: cells,
        label: {
          // Print the GEX value in every meaningful cell, reference-site
          // style. Desktop: "-76.9M" / "+1.2B". Narrow screens: bare $M
          // integers ("-77") so they fit ~26px cells. Cells under a few % of
          // the color scale stay blank to keep far-OTM noise clean.
          show: true,
          fontSize: mobile ? 7.5 : 9, fontWeight: 600, color: "#f2f5fa",
          textBorderColor: "rgba(0,0,0,0.65)", textBorderWidth: 2,
          formatter: (p) => {
            const v = p.value[3];
            const a = Math.abs(v);
            if (mobile) {
              if (a < Math.max(1, vmax * 0.15)) return "";
              return String(Math.round(v));
            }
            if (a < Math.max(1, vmax * 0.04)) return "";
            let s;
            if (a >= 1000) s = (a / 1000).toFixed(1) + "B";
            else if (a >= 100) s = Math.round(a) + "M";
            else s = a.toFixed(1) + "M";
            return (v < 0 ? "-" : "+") + s;
          },
        },
        itemStyle: { borderColor: "#0b0e14", borderWidth: 1 },
        emphasis: { itemStyle: { borderColor: "#ffffff", borderWidth: 1 } },
        markLine: spotLabel === null ? undefined : {
          symbol: "none", silent: true,
          lineStyle: { color: "#ffffff", type: "dashed", width: 1 },
          label: {
            formatter: "SPOT " + Fmt.fmtStrike(status.spot),
            color: "#ffffff", fontSize: 10, position: "insideEndTop",
          },
          data: [{ yAxis: spotLabel }],
        },
      }],
    }, { notMerge: true });
    inst.resize();
  }

  /* -------- Horizontal tornado: GEX by strike or flow by strike -------- */
  // rows: [[strike, callVal, putVal, (netVal)] ...] strikes DESC.
  // levels: {spot, flip, call_wall, put_wall} (nulls ok)
  // opts: {fmt: 'money'|'count'|'price', showNet: bool, title}

  function renderTornado(el, rows, levels, opts) {
    opts = opts || {};
    const fmt = opts.fmt === "count" ? Fmt.fmtCount
      : opts.fmt === "price" ? Fmt.fmtPrice : Fmt.fmtM;
    const strikes = rows.map((r) => r[0]);
    const cats = strikes.map(Fmt.fmtStrike);
    const calls = rows.map((r) => r[1]);
    const puts = rows.map((r) => (r[2] <= 0 ? r[2] : -r[2]));  // force left side
    const nets = opts.showNet ? rows.map((r) => r[3]) : null;
    const inst = chart(el, Math.max(380, rows.length * 18 + 110));

    const markData = [];
    function level(name, value, color, type, position) {
      const lab = nearestLabel(strikes, value);
      if (lab === null) return;
      markData.push({
        yAxis: lab,
        lineStyle: { color, type: type || "dashed", width: 1.2 },
        label: {
          formatter: name + " " + Fmt.fmtStrike(value),
          color, fontSize: 10, position: position || "insideEndTop",
        },
      });
    }
    if (levels) {
      // Left/right label split so coinciding levels (e.g. spot on the put
      // wall) don't overlap.
      level("SPOT", levels.spot, "#ffffff", "solid", "insideStartTop");
      level("FLIP", levels.flip, AMBER, "dashed", "insideStartBottom");
      level("CALL WALL", levels.call_wall, GREEN, "dashed", "insideStartTop");
      level("PUT WALL", levels.put_wall, RED, "dashed", "insideStartBottom");
    }

    const series = [
      {
        name: "Calls", type: "bar", stack: "g", data: calls,
        itemStyle: { color: GREEN }, barCategoryGap: "25%", barMaxWidth: 22,
        markLine: markData.length ? { symbol: "none", silent: true, data: markData } : undefined,
      },
      {
        name: "Puts", type: "bar", stack: "g", data: puts,
        itemStyle: { color: RED }, barMaxWidth: 22,
      },
    ];
    if (nets) {
      series.push({
        name: "Net", type: "line", data: nets, showSymbol: false,
        lineStyle: { color: "#e3e8f2", width: 1.5 }, z: 5,
      });
    }

    inst.setOption({
      animation: false,
      grid: { left: 64, right: 18, top: 26, bottom: 30 },
      legend: {
        top: 0, textStyle: { color: MUTED, fontSize: 10 },
        itemWidth: 12, itemHeight: 8,
        data: nets ? ["Calls", "Puts", "Net"] : ["Calls", "Puts"],
      },
      tooltip: {
        trigger: "axis", axisPointer: { type: "shadow" },
        backgroundColor: "#11151f", borderColor: "#1d2433", textStyle: baseText(),
        formatter: (ps) => {
          const i = ps[0].dataIndex;
          let html = "<b>" + cats[i] + "</b>";
          ps.forEach((p) => {
            html += "<br>" + p.seriesName + ": " + fmt(Math.abs(p.value) * (p.seriesName === "Puts" ? -1 : 1));
          });
          return html;
        },
      },
      xAxis: {
        type: "value",
        axisLabel: { color: MUTED, fontSize: 10, formatter: (v) => fmt(v) },
        splitLine: { lineStyle: { color: "#161b29" } },
      },
      yAxis: {
        type: "category", data: cats, inverse: true,
        axisLabel: { color: MUTED, fontSize: 10 },
        axisLine: { lineStyle: { color: "#1d2433" } },
      },
      series,
    }, { notMerge: true });
    inst.resize();
  }

  /* ---------------------- Sentiment gauge ---------------------- */

  function renderGauge(el, score, label, opts) {
    opts = opts || {};
    const colors = opts.positiveIsRisk
      ? [[0.425, GREEN], [0.575, "#3a4254"], [1, RED]]
      : [[0.425, RED], [0.575, "#3a4254"], [1, GREEN]];
    const inst = chart(el, 260);
    inst.setOption({
      animation: true,
      series: [{
        type: "gauge", min: -100, max: 100, startAngle: 200, endAngle: -20,
        axisLine: {
          lineStyle: {
            width: 16,
            color: colors,
          },
        },
        pointer: { itemStyle: { color: "#e3e8f2" }, length: "60%", width: 4 },
        axisTick: { show: false }, splitLine: { show: false },
        axisLabel: { color: MUTED, fontSize: 9, distance: -38 },
        anchor: { show: true, size: 8, itemStyle: { color: "#e3e8f2" } },
        title: { show: false },
        detail: {
          valueAnimation: true, offsetCenter: [0, "62%"],
          formatter: (v) => "{s|" + v.toFixed(0) + "}\n{l|" + label + "}",
          rich: {
            s: { color: TEXT, fontSize: 26, fontWeight: 700 },
            l: { color: MUTED, fontSize: 12, padding: [4, 0, 0, 0] },
          },
        },
        data: [{ value: score === null || score === undefined ? 0 : score }],
      }],
    }, { notMerge: true });
    inst.resize();
  }

  /* -------------- Vertical mini bars (GEX by expiration) -------------- */

  function renderMiniBar(el, pairs, opts) {
    opts = opts || {};
    const inst = chart(el, opts.height || 220);
    inst.setOption({
      animation: false,
      grid: { left: 56, right: 10, top: 12, bottom: 44 },
      tooltip: {
        backgroundColor: "#11151f", borderColor: "#1d2433", textStyle: baseText(),
        formatter: (p) => p.name + "<br>Net GEX: <b>" + Fmt.fmtM(p.value) + "</b>",
      },
      xAxis: {
        type: "category", data: pairs.map((p) => Fmt.fmtExpiry(p[0])),
        axisLabel: { color: MUTED, rotate: 45, fontSize: 9 },
        axisLine: { lineStyle: { color: "#1d2433" } },
      },
      yAxis: {
        type: "value",
        axisLabel: { color: MUTED, fontSize: 9, formatter: (v) => Fmt.fmtM(v) },
        splitLine: { lineStyle: { color: "#161b29" } },
      },
      series: [{
        type: "bar", data: pairs.map((p) => ({
          value: p[1], itemStyle: { color: p[1] >= 0 ? GREEN : RED },
        })),
      }],
    }, { notMerge: true });
    inst.resize();
  }

  window.Charts = { renderHeatmap, renderTornado, renderGauge, renderMiniBar };
})();
