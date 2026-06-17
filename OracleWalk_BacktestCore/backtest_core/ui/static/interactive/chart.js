const DEFAULT_PRICE_FORMAT = {
  type: "price",
  precision: 5,
  minMove: 0.00001,
};

const DEFAULT_INDICATORS_META = {
  overlays: ["sma60"],
  panes: [
    { key: "rsi", range: [0, 100], oversold: 27, overbought: 72 },
    { key: "stoch_k", range: [0, 100], oversold: 20, overbought: 80 },
    { key: "uo", range: [0, 100], oversold: 30, overbought: 70 },
  ],
};

const INDICATOR_COLORS = {
  sma60: "#ffb547",
  rsi: "#5b9dff",
  stoch_k: "#c084fc",
  uo: "#4ad6e6",
};

export function normalizeTime(value) {
  if (typeof value === "number" && Number.isFinite(value)) {
    return Math.floor(value > 10_000_000_000 ? value / 1000 : value);
  }
  if (typeof value === "string") {
    const numeric = Number(value);
    if (Number.isFinite(numeric)) return normalizeTime(numeric);
    const parsed = Date.parse(value);
    if (Number.isFinite(parsed)) return Math.floor(parsed / 1000);
  }
  return Math.floor(Date.now() / 1000);
}

export function normalizeBar(bar) {
  const rawVolume = Number(bar.volume ?? 0);
  const tickVolume = Number(bar.tick_volume ?? bar.tickVolume ?? 0);
  const realVolume = Number(bar.real_volume ?? bar.realVolume ?? 0);
  return {
    time: normalizeTime(bar.time),
    open: Number(bar.open),
    high: Number(bar.high),
    low: Number(bar.low),
    close: Number(bar.close),
    volume: rawVolume > 0 ? rawVolume : (tickVolume > 0 ? tickVolume : Math.max(0, realVolume || 0)),
  };
}

export function formatPrice(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "--";
  return n.toFixed(Math.abs(n) >= 10 ? 2 : 5);
}

export class InteractiveChart {
  constructor(container) {
    this.container = container;
    this.chart = null;
    this.candleSeries = null;
    this.volumeSeries = null;
    this.chartType = "candles";
    this.priceScaleMode = "linear";
    this.overlaySeries = new Map();
    this.indicatorSeries = new Map();
    this.indicatorPriceLines = new Map();
    // Stored line points per indicator key, so the rolling window can trim them in
    // lock-step with the candles (lightweight-charts only lets us append via update).
    this.overlayData = new Map();
    this.indicatorData = new Map();
    // Rolling-window cap: keep at most `maxBars` candles in the chart so fluidity
    // doesn't degrade after tens of thousands of replayed bars. `baseIndexOffset`
    // tracks how many bars were dropped off the front, so absolute engine bar
    // indices (e.g. a zone's created_at_bar) still map to the right time.
    this.maxBars = 10000;
    this.windowSlack = 1000;
    this.baseIndexOffset = 0;
    this.indicatorsMeta = DEFAULT_INDICATORS_META;
    this.markersApi = null;
    this.sourceBars = [];
    this.bars = [];
    this.baseTimeframe = "H1";
    this.displayTimeframe = "H1";
    this.markerMap = new Map();
    this.tradeLineMap = new Map();
    this.viewportCallbacks = new Set();
    this.hoverCallback = null;
    this.resizeObserver = null;
    this.resizeFrame = 0;
  }

  init() {
    const lc = window.LightweightCharts;
    if (!lc?.createChart) {
      throw new Error("lightweight-charts nao foi carregado");
    }

    this.chart = lc.createChart(this.container, {
      autoSize: true,
      layout: {
        background: { color: "#05070a" },
        textColor: "#9aa4b2",
        fontFamily: "Inter, system-ui, sans-serif",
      },
      grid: {
        vertLines: { color: "#111923" },
        horzLines: { color: "#111923" },
      },
      rightPriceScale: {
        borderColor: "#1d2633",
        scaleMargins: { top: 0.08, bottom: 0.2 },
      },
      timeScale: {
        borderColor: "#1d2633",
        timeVisible: true,
        secondsVisible: false,
        rightOffset: 18,
        barSpacing: 9,
        fixLeftEdge: false,
        fixRightEdge: false,
      },
      crosshair: {
        mode: lc.CrosshairMode?.Normal ?? 0,
        vertLine: { color: "rgba(180, 191, 204, 0.42)", width: 1, style: 2, labelBackgroundColor: "#243041" },
        horzLine: { color: "rgba(180, 191, 204, 0.42)", width: 1, style: 2, labelBackgroundColor: "#243041" },
      },
      handleScale: {
        axisPressedMouseMove: true,
        mouseWheel: true,
        pinch: true,
      },
      handleScroll: {
        mouseWheel: true,
        pressedMouseMove: true,
        horzTouchDrag: true,
        vertTouchDrag: false,
      },
    });

    this.candleSeries = this.createPriceSeries(this.chartType);

    this.volumeSeries = this.addSeries("HistogramSeries", {
      priceFormat: { type: "volume" },
      priceScaleId: "",
      lastValueVisible: false,
      priceLineVisible: false,
    }, "addHistogramSeries");
    this.volumeSeries.priceScale().applyOptions({
      scaleMargins: { top: 0.78, bottom: 0 },
    });

    this.chart.timeScale().subscribeVisibleLogicalRangeChange(() => {
      this.emitViewportChange();
    });

    this.chart.subscribeCrosshairMove((param) => {
      if (this.moveCallback) {
        const x = param?.point?.x;
        this.moveCallback({ x: Number.isFinite(x) ? x : null });
      }
      if (!this.hoverCallback) return;
      const data = param?.seriesData?.get?.(this.candleSeries);
      if (data && data.open != null) {
        this.hoverCallback(normalizeBar(data));
        return;
      }
      if (param?.time) {
        const time = normalizeTime(param.time);
        const found = this.bars.find((bar) => normalizeTime(bar.time) === time);
        if (found) this.hoverCallback(found);
      }
    });

    // Click anywhere on the chart -> reposition the replay there (TradingView style).
    this.chart.subscribeClick((param) => {
      if (!this.clickCallback) return;
      this.clickCallback({
        x: Number.isFinite(param?.point?.x) ? param.point.x : null,
        time: param?.time != null ? normalizeTime(param.time) : null,
        logical: Number.isFinite(param?.logical) ? param.logical : null,
      });
    });

    this.resizeObserver = new ResizeObserver(() => this.scheduleResize());
    this.resizeObserver.observe(this.container);
    this.scheduleResize();
  }

  addSeries(seriesName, options, legacyMethod, paneIndex = undefined) {
    const lc = window.LightweightCharts;
    if (lc?.[seriesName] && typeof this.chart.addSeries === "function") {
      return paneIndex == null
        ? this.chart.addSeries(lc[seriesName], options)
        : this.chart.addSeries(lc[seriesName], options, paneIndex);
    }
    if (typeof this.chart[legacyMethod] === "function") {
      return this.chart[legacyMethod](options);
    }
    throw new Error(`Serie ${seriesName} indisponivel no lightweight-charts`);
  }

  createPriceSeries(type) {
    const normalized = normalizeChartType(type);
    const priceFormat = priceFormatForBars(this.bars);
    if (normalized === "bars") {
      return this.addSeries("BarSeries", {
        upColor: "#2bd47f",
        downColor: "#ff5867",
        thinBars: false,
        priceFormat,
      }, "addBarSeries");
    }
    if (normalized === "line") {
      return this.addSeries("LineSeries", {
        color: "#4ad6e6",
        lineWidth: 2,
        crosshairMarkerVisible: true,
        priceFormat,
      }, "addLineSeries");
    }
    if (normalized === "area") {
      return this.addSeries("AreaSeries", {
        lineColor: "#4ad6e6",
        topColor: "rgba(74, 214, 230, 0.32)",
        bottomColor: "rgba(74, 214, 230, 0.03)",
        lineWidth: 2,
        priceFormat,
      }, "addAreaSeries");
    }
    return this.addSeries("CandlestickSeries", {
      upColor: "#2bd47f",
      downColor: "#ff5867",
      borderUpColor: "#2bd47f",
      borderDownColor: "#ff5867",
      wickUpColor: "#2bd47f",
      wickDownColor: "#ff5867",
      priceFormat,
    }, "addCandlestickSeries");
  }

  setChartType(type) {
    const next = normalizeChartType(type);
    if (next === this.chartType && this.candleSeries) return;
    const openTrades = [...this.tradeLineMap.values()].map((item) => item.source).filter(Boolean);
    this.clearTradeLines();
    if (this.candleSeries && typeof this.chart.removeSeries === "function") {
      this.chart.removeSeries(this.candleSeries);
    }
    this.chartType = next;
    this.candleSeries = this.createPriceSeries(next);
    this.setPriceScaleMode(this.priceScaleMode);
    this.setPriceData();
    this.applyMarkers();
    this.syncOpenTradeLevels(openTrades);
    this.emitViewportChange();
  }

  setPriceScaleMode(mode) {
    this.priceScaleMode = mode === "log" ? "log" : "linear";
    const scaleMode = window.LightweightCharts?.PriceScaleMode;
    const value = this.priceScaleMode === "log"
      ? (scaleMode?.Logarithmic ?? 1)
      : (scaleMode?.Normal ?? 0);
    this.chart.priceScale("right").applyOptions({ mode: value });
    this.emitViewportChange();
  }

  setHoverCallback(callback) {
    this.hoverCallback = callback;
  }

  setClickCallback(callback) {
    this.clickCallback = callback;
  }

  setMoveCallback(callback) {
    this.moveCallback = callback;
  }

  setCrosshairCursor(enabled) {
    if (this.container) this.container.style.cursor = enabled ? "crosshair" : "";
  }

  onViewportChange(callback) {
    this.viewportCallbacks.add(callback);
    return () => this.viewportCallbacks.delete(callback);
  }

  emitViewportChange() {
    for (const callback of this.viewportCallbacks) callback();
  }

  scheduleResize() {
    cancelAnimationFrame(this.resizeFrame);
    this.resizeFrame = requestAnimationFrame(() => {
      const width = Math.max(1, this.container.clientWidth);
      const height = Math.max(1, this.container.clientHeight);
      if (typeof this.chart?.resize === "function") this.chart.resize(width, height);
      this.resizeIndicatorPanes();
      this.emitViewportChange();
    });
  }

  setBaseTimeframe(timeframe) {
    this.baseTimeframe = timeframe || this.baseTimeframe || "H1";
    if (!this.displayTimeframe) this.displayTimeframe = this.baseTimeframe;
  }

  setDisplayTimeframe(timeframe) {
    this.displayTimeframe = timeframe || this.baseTimeframe || "H1";
    this.refreshDisplayData({ fit: true });
  }

  setHistory(history, { baseTimeframe, displayTimeframe } = {}) {
    this.baseTimeframe = baseTimeframe || this.baseTimeframe || "H1";
    this.displayTimeframe = displayTimeframe || this.displayTimeframe || this.baseTimeframe;
    const all = (history || []).map(normalizeBar);
    // Window the initial history too — a long seek can hand us >10k bars.
    const over = Math.max(0, all.length - this.maxBars);
    this.baseIndexOffset = over;
    this.sourceBars = over > 0 ? all.slice(over) : all;
    this.refreshDisplayData({ fit: true });
    this.markerMap.clear();
    this.clearTradeLines();
    this.clearIndicatorData();
    this.applyMarkers();
    this.emitViewportChange();
  }

  refreshDisplayData({ fit = false } = {}) {
    this.bars = aggregateBars(this.sourceBars, this.displayTimeframe, this.baseTimeframe);
    this.candleSeries.applyOptions({
      priceFormat: priceFormatForBars(this.bars),
    });
    this.setPriceData();
    this.volumeSeries.setData(volumeDataForBars(this.bars));
    if (fit && this.bars.length) {
      this.chart.timeScale().fitContent();
    }
    this.emitViewportChange();
  }

  appendBars(bars) {
    const normalized = (bars || []).map(normalizeBar);
    this.sourceBars.push(...normalized);
    if (this.displayTimeframe !== this.baseTimeframe) {
      this.enforceWindow();
      this.refreshDisplayData();
      if (normalized.length) this.chart.timeScale().scrollToRealTime();
      return;
    }
    for (const rawBar of bars || []) {
      const bar = normalizeBar(rawBar);
      this.bars.push(bar);
      this.candleSeries.update(priceSeriesPoint(bar, this.chartType));
      this.volumeSeries.update(volumeDataForBar(bar));
    }
    if (bars?.length) {
      this.enforceWindow();
      this.chart.timeScale().scrollToRealTime();
      this.emitViewportChange();
    }
  }

  // Drop the oldest candles/indicator points once the buffer grows past the cap,
  // in batches (slack) so we only pay a setData() once per `windowSlack` bars.
  enforceWindow() {
    const over = this.sourceBars.length - this.maxBars;
    if (over < this.windowSlack) return;
    this.sourceBars.splice(0, over);
    this.baseIndexOffset += over;
    const minTime = this.sourceBars.length ? normalizeTime(this.sourceBars[0].time) : 0;
    // Rebuild the candle/volume series from the windowed source.
    this.bars = aggregateBars(this.sourceBars, this.displayTimeframe, this.baseTimeframe);
    this.setPriceData();
    this.volumeSeries.setData(volumeDataForBars(this.bars));
    // Trim the stored indicator points to the same window and re-push them.
    for (const [key, series] of this.overlaySeries.entries()) {
      this.trimIndicatorStore(this.overlayData, key, series, minTime);
    }
    for (const [key, series] of this.indicatorSeries.entries()) {
      this.trimIndicatorStore(this.indicatorData, key, series, minTime);
    }
  }

  trimIndicatorStore(store, key, series, minTime) {
    const points = store.get(key);
    if (!points || !points.length) return;
    const trimmed = points.filter((point) => point.time >= minTime);
    store.set(key, trimmed);
    series.setData(trimmed);
  }

  lastBar() {
    return this.bars[this.bars.length - 1] || null;
  }

  visibleBars() {
    if (!this.bars.length) return [];
    const range = this.chart?.timeScale?.().getVisibleLogicalRange?.();
    if (!range || !Number.isFinite(range.from) || !Number.isFinite(range.to)) {
      return [...this.bars];
    }
    const from = Math.max(0, Math.floor(range.from));
    const to = Math.min(this.bars.length - 1, Math.ceil(range.to));
    if (to < from) return [];
    return this.bars.slice(from, to + 1);
  }

  setPriceData() {
    if (!this.candleSeries) return;
    this.candleSeries.setData(this.bars.map((bar) => priceSeriesPoint(bar, this.chartType)));
  }

  getBarTimeByIndex(index) {
    // `index` is an absolute engine bar index; map it into the current window.
    const local = Number(index) - this.baseIndexOffset;
    const bar = this.sourceBars[local] || (local < 0 ? this.sourceBars[0] : null);
    if (!bar) return this.lastBar()?.time ?? null;
    return bucketTime(normalizeTime(bar.time), this.displayTimeframe, this.baseTimeframe);
  }

  priceToY(price) {
    const y = this.candleSeries.priceToCoordinate(Number(price));
    return Number.isFinite(y) ? y : null;
  }

  yToPrice(y) {
    const price = this.candleSeries.coordinateToPrice(Number(y));
    return Number.isFinite(price) ? price : null;
  }

  timeToX(time) {
    if (time == null) return null;
    const x = this.chart.timeScale().timeToCoordinate(normalizeTime(time));
    return Number.isFinite(x) ? x : null;
  }

  xToCursor(x) {
    const time = this.chart.timeScale().coordinateToTime(Number(x));
    if (time == null || !this.sourceBars.length) return null;
    const target = normalizeTime(time);
    const index = nearestBarIndexByTime(this.sourceBars, target);
    return Number.isFinite(index) ? index + this.baseIndexOffset : null;
  }

  xToTime(x) {
    const time = this.chart.timeScale().coordinateToTime(Number(x));
    return time == null ? null : normalizeTime(time);
  }

  upsertTradeMarkers(openTrades = [], closedNow = []) {
    for (const trade of openTrades) {
      this.addEntryMarker(trade);
    }
    for (const trade of closedNow) {
      this.addEntryMarker(trade);
      this.addExitMarker(trade);
    }
    this.applyMarkers();
  }

  configureIndicators(meta = {}) {
    const normalized = normalizeIndicatorsMeta(meta);
    this.indicatorsMeta = normalized;
    this.syncOverlaySeries(normalized.overlays);
    this.syncPaneSeries(normalized.panes);
  }

  syncOverlaySeries(overlays = []) {
    const next = new Set(overlays);
    for (const key of [...this.overlaySeries.keys()]) {
      if (!next.has(key)) this.removeSeriesFromMap(this.overlaySeries, key);
    }
    for (const key of overlays) {
      if (this.overlaySeries.has(key)) continue;
      const series = this.addSeries("LineSeries", {
        color: INDICATOR_COLORS[key] || "#ffb547",
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: true,
        title: key.toUpperCase(),
        priceFormat: DEFAULT_PRICE_FORMAT,
      }, "addLineSeries", 0);
      this.overlaySeries.set(key, series);
    }
  }

  syncPaneSeries(panes = []) {
    const next = new Set(panes.map((pane) => pane.key));
    for (const key of [...this.indicatorSeries.keys()]) {
      if (!next.has(key)) {
        this.clearIndicatorPriceLines(key);
        this.removeSeriesFromMap(this.indicatorSeries, key);
      }
    }
    panes.forEach((pane, index) => {
      if (!this.indicatorSeries.has(pane.key)) {
        const series = this.addSeries("LineSeries", {
          color: INDICATOR_COLORS[pane.key] || "#5b9dff",
          lineWidth: 2,
          priceLineVisible: false,
          lastValueVisible: false,
          title: "",
          priceFormat: { type: "price", precision: 2, minMove: 0.01 },
        }, "addLineSeries", index + 1);
        if (typeof series.priceScale === "function") {
          series.priceScale().applyOptions({
            scaleMargins: { top: 0.16, bottom: 0.14 },
          });
        }
        this.indicatorSeries.set(pane.key, series);
      }
      this.syncIndicatorPriceLines(pane);
    });
    this.resizeIndicatorPanes();
  }

  removeSeriesFromMap(map, key) {
    const series = map.get(key);
    if (series && typeof this.chart.removeSeries === "function") {
      this.chart.removeSeries(series);
    }
    map.delete(key);
  }

  syncIndicatorPriceLines(pane) {
    this.clearIndicatorPriceLines(pane.key);
    const series = this.indicatorSeries.get(pane.key);
    if (!series || typeof series.createPriceLine !== "function") return;
    const lines = [];
    const limits = [
      ["OS", pane.oversold, "#2bd47f"],
      ["OB", pane.overbought, "#ff5867"],
    ];
    for (const [label, value, color] of limits) {
      const price = Number(value);
      if (!Number.isFinite(price)) continue;
      lines.push(series.createPriceLine({
        price,
        color: colorWithAlpha(color, 0.72),
        lineWidth: 1,
        lineStyle: this.lineStyle("dashed"),
        axisLabelVisible: false,
        title: "",
      }));
    }
    this.indicatorPriceLines.set(pane.key, lines);
  }

  resizeIndicatorPanes() {
    if (typeof this.chart?.panes !== "function") return;
    const panes = this.chart.panes();
    if (!Array.isArray(panes) || panes.length < 2) return;
    panes.slice(1).forEach((pane) => {
      if (typeof pane.setHeight === "function") pane.setHeight(86);
    });
  }

  clearIndicatorPriceLines(key) {
    const lines = this.indicatorPriceLines.get(key) || [];
    const series = this.indicatorSeries.get(key);
    if (series && typeof series.removePriceLine === "function") {
      for (const line of lines) series.removePriceLine(line);
    }
    this.indicatorPriceLines.delete(key);
  }

  setIndicatorSeries(seriesData = {}) {
    for (const [key, series] of this.overlaySeries.entries()) {
      const data = lineDataFromSeries(seriesData, key);
      this.overlayData.set(key, data);
      series.setData(data);
    }
    for (const [key, series] of this.indicatorSeries.entries()) {
      const data = lineDataFromSeries(seriesData, key);
      this.indicatorData.set(key, data);
      series.setData(data);
    }
  }

  appendIndicatorPoint(time, indicators = {}) {
    if (time == null) return;
    for (const [key, series] of this.overlaySeries.entries()) {
      const point = linePoint(time, indicators[key]);
      if (point) { this.storeIndicatorPoint(this.overlayData, key, point); series.update(point); }
    }
    for (const [key, series] of this.indicatorSeries.entries()) {
      const point = linePoint(time, indicators[key]);
      if (point) { this.storeIndicatorPoint(this.indicatorData, key, point); series.update(point); }
    }
  }

  storeIndicatorPoint(store, key, point) {
    const points = store.get(key);
    if (!points) { store.set(key, [point]); return; }
    const last = points[points.length - 1];
    // update() can replace the last point (same time) or append a new one.
    if (last && last.time === point.time) points[points.length - 1] = point;
    else points.push(point);
  }

  clearIndicatorData() {
    for (const series of this.overlaySeries.values()) series.setData([]);
    for (const series of this.indicatorSeries.values()) series.setData([]);
    this.overlayData.clear();
    this.indicatorData.clear();
  }

  syncOpenTradeLevels(openTrades = []) {
    const nextKeys = new Set();
    for (const trade of openTrades || []) {
      const id = String(trade.id);
      this.upsertTradeLine(`${id}:entry`, trade.entry_price, {
        color: "#4ad6e6",
        title: `#${id} ENTRY`,
        style: "solid",
        width: 2,
        source: trade,
      });
      nextKeys.add(`${id}:entry`);

      if (Number.isFinite(Number(trade.stop_price))) {
        this.upsertTradeLine(`${id}:sl`, trade.stop_price, {
        color: "#ff5867",
        title: `#${id} SL`,
        style: "dashed",
        width: 2,
        source: trade,
      });
        nextKeys.add(`${id}:sl`);
      }

      if (Number.isFinite(Number(trade.take_price))) {
        this.upsertTradeLine(`${id}:tp`, trade.take_price, {
        color: "#2bd47f",
        title: `#${id} TP`,
        style: "dashed",
        width: 2,
        source: trade,
      });
        nextKeys.add(`${id}:tp`);
      }
    }

    for (const key of [...this.tradeLineMap.keys()]) {
      if (!nextKeys.has(key)) this.removeTradeLine(key);
    }
  }

  upsertTradeLine(key, price, options) {
    const value = Number(price);
    if (!Number.isFinite(value)) {
      this.removeTradeLine(key);
      return;
    }
    const existing = this.tradeLineMap.get(key);
    if (existing && existing.price === value && existing.title === options.title) return;
    this.removeTradeLine(key);
    if (typeof this.candleSeries.createPriceLine !== "function") return;
    const lineStyle = this.lineStyle(options.style);
    const line = this.candleSeries.createPriceLine({
      price: value,
      color: options.color,
      lineWidth: options.width || 1,
      lineStyle,
      axisLabelVisible: true,
      title: options.title,
    });
    this.tradeLineMap.set(key, { line, price: value, title: options.title, source: options.source });
  }

  removeTradeLine(key) {
    const existing = this.tradeLineMap.get(key);
    if (!existing) return;
    if (typeof this.candleSeries.removePriceLine === "function") {
      this.candleSeries.removePriceLine(existing.line);
    }
    this.tradeLineMap.delete(key);
  }

  clearTradeLines() {
    for (const key of [...this.tradeLineMap.keys()]) {
      this.removeTradeLine(key);
    }
  }

  lineStyle(name) {
    const style = window.LightweightCharts?.LineStyle;
    if (name === "dashed") return style?.Dashed ?? 2;
    if (name === "dotted") return style?.Dotted ?? 1;
    return style?.Solid ?? 0;
  }

  addEntryMarker(trade) {
    if (!trade?.entry_time) return;
    const id = `entry:${trade.id}`;
    if (this.markerMap.has(id)) return;
    const isLong = trade.direction !== "short";
    this.markerMap.set(id, {
      time: normalizeTime(trade.entry_time),
      position: isLong ? "belowBar" : "aboveBar",
      color: isLong ? "#2bd47f" : "#ff5867",
      shape: isLong ? "arrowUp" : "arrowDown",
      text: `${isLong ? "L" : "S"} #${trade.id}`,
    });
  }

  addExitMarker(trade) {
    if (!trade?.exit_time) return;
    const id = `exit:${trade.id}`;
    const pnl = Number(trade.pnl ?? 0);
    this.markerMap.set(id, {
      time: normalizeTime(trade.exit_time),
      position: pnl >= 0 ? "aboveBar" : "belowBar",
      color: pnl >= 0 ? "#ffb547" : "#ff5867",
      shape: "circle",
      text: `X #${trade.id}`,
    });
  }

  applyMarkers() {
    const markers = [...this.markerMap.values()].sort((a, b) => a.time - b.time);
    const lc = window.LightweightCharts;
    if (typeof this.candleSeries.setMarkers === "function") {
      this.candleSeries.setMarkers(markers);
      return;
    }
    if (!this.markersApi && typeof lc?.createSeriesMarkers === "function") {
      this.markersApi = lc.createSeriesMarkers(this.candleSeries, markers);
      return;
    }
    if (typeof this.markersApi?.setMarkers === "function") {
      this.markersApi.setMarkers(markers);
    }
  }
}

function normalizeIndicatorsMeta(meta = {}) {
  const overlays = Array.isArray(meta.overlays) && meta.overlays.length
    ? meta.overlays
    : DEFAULT_INDICATORS_META.overlays;
  const panes = Array.isArray(meta.panes) && meta.panes.length
    ? meta.panes
    : DEFAULT_INDICATORS_META.panes;
  return {
    overlays: overlays.map((key) => String(key)).filter(Boolean),
    panes: panes
      .map((pane) => ({
        key: String(pane?.key || "").trim(),
        range: Array.isArray(pane?.range) ? pane.range : [0, 100],
        oversold: pane?.oversold,
        overbought: pane?.overbought,
      }))
      .filter((pane) => pane.key),
  };
}

function lineDataFromSeries(seriesData = {}, key) {
  const times = Array.isArray(seriesData.time) ? seriesData.time : [];
  const values = Array.isArray(seriesData[key]) ? seriesData[key] : [];
  const out = [];
  for (let i = 0; i < times.length && i < values.length; i += 1) {
    const point = linePoint(times[i], values[i]);
    if (point) out.push(point);
  }
  return out;
}

function linePoint(time, value) {
  if (value == null || value === "") return null;
  const n = Number(value);
  if (!Number.isFinite(n)) return null;
  return { time: normalizeTime(time), value: n };
}

function colorWithAlpha(hex, alpha) {
  const value = String(hex || "").trim();
  const match = value.match(/^#([0-9a-f]{6})$/i);
  if (!match) return value;
  const n = Number.parseInt(match[1], 16);
  const r = (n >> 16) & 255;
  const g = (n >> 8) & 255;
  const b = n & 255;
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function nearestBarIndexByTime(bars, targetTime) {
  let lo = 0;
  let hi = bars.length - 1;
  while (lo <= hi) {
    const mid = Math.floor((lo + hi) / 2);
    const time = normalizeTime(bars[mid].time);
    if (time === targetTime) return mid;
    if (time < targetTime) lo = mid + 1;
    else hi = mid - 1;
  }
  const before = Math.max(0, hi);
  const after = Math.min(bars.length - 1, lo);
  const beforeDelta = Math.abs(normalizeTime(bars[before].time) - targetTime);
  const afterDelta = Math.abs(normalizeTime(bars[after].time) - targetTime);
  return afterDelta < beforeDelta ? after : before;
}

function priceFormatForBars(bars) {
  const sample = bars.find((bar) => Number.isFinite(bar?.close));
  if (sample && Math.abs(sample.close) >= 10) {
    return { type: "price", precision: 2, minMove: 0.01 };
  }
  return DEFAULT_PRICE_FORMAT;
}

function volumeDataForBars(bars) {
  return bars.map(volumeDataForBar);
}

function volumeDataForBar(bar) {
  const up = Number(bar.close) >= Number(bar.open);
  return {
    time: normalizeTime(bar.time),
    value: Number(bar.volume || 0),
    color: up ? "rgba(43, 212, 127, 0.28)" : "rgba(255, 88, 103, 0.28)",
  };
}

function normalizeChartType(type) {
  const value = String(type || "").toLowerCase();
  if (value === "bars" || value === "bar") return "bars";
  if (value === "line") return "line";
  if (value === "area") return "area";
  return "candles";
}

function priceSeriesPoint(bar, type) {
  const normalized = normalizeChartType(type);
  const time = normalizeTime(bar.time);
  if (normalized === "line" || normalized === "area") {
    return { time, value: Number(bar.close) };
  }
  return {
    time,
    open: Number(bar.open),
    high: Number(bar.high),
    low: Number(bar.low),
    close: Number(bar.close),
  };
}

function aggregateBars(bars, displayTimeframe, baseTimeframe) {
  const displayMinutes = timeframeMinutes(displayTimeframe);
  const baseMinutes = timeframeMinutes(baseTimeframe);
  if (!displayMinutes || !baseMinutes || displayMinutes <= baseMinutes) return [...bars];
  const buckets = new Map();
  for (const bar of bars) {
    const key = bucketTime(bar.time, displayTimeframe, baseTimeframe);
    const existing = buckets.get(key);
    if (!existing) {
      buckets.set(key, { ...bar, time: key });
      continue;
    }
    existing.high = Math.max(existing.high, bar.high);
    existing.low = Math.min(existing.low, bar.low);
    existing.close = bar.close;
    existing.volume += Number(bar.volume || 0);
  }
  return [...buckets.values()].sort((a, b) => a.time - b.time);
}

function bucketTime(time, displayTimeframe, baseTimeframe) {
  const displayMinutes = timeframeMinutes(displayTimeframe);
  const baseMinutes = timeframeMinutes(baseTimeframe);
  if (!displayMinutes || !baseMinutes || displayMinutes <= baseMinutes) return normalizeTime(time);
  const bucketSeconds = displayMinutes * 60;
  return Math.floor(normalizeTime(time) / bucketSeconds) * bucketSeconds;
}

function timeframeMinutes(value) {
  const match = String(value || "").match(/^([A-Z]+)(\d+)$/i);
  if (!match) return 0;
  const n = Number(match[2]);
  const unit = match[1].toUpperCase();
  if (unit === "M") return n;
  if (unit === "H") return n * 60;
  if (unit === "D") return n * 1440;
  if (unit === "W") return n * 10080;
  return 0;
}
