import { InteractiveChart, formatPrice, normalizeBar, normalizeTime } from "./chart.js";
import { ZoneLayer } from "./zones.js";
import { DrawingLayer } from "./drawings.js";
import { VolumeProfile } from "./volume_profile.js";

const state = {
  api: null,
  chart: null,
  zones: null,
  catalog: null,
  session: null,
  cursor: 0,
  totalBars: 0,
  balance: 1000,
  equity: 1000,
  indicators: {},
  tfIndicators: {},
  indicatorThresholds: {},
  indicatorsMeta: {},
  activeIndicatorTimeframe: "",
  zoneTimeframes: ["H1"],
  chartTimeframes: ["H1"],
  chartTimeframe: "H1",
  chartType: "candles",
  scaleMode: "linear",
  drawings: null,
  volumeProfile: null,
  volumeProfileEnabled: true,
  volumeProfilePicker: false,
  volumeProfilePendingStart: null,
  volumeProfileDomClickAt: 0,
  openTrades: [],
  closedEvents: [],
  playing: false,
  stepping: false,
  seeking: false,
  done: false,
  timer: null,
  mode: "real",
  speed: 25,
  warmupCursor: 0,
  seekPickerActive: false,
  seekPreviewCursor: null,
  lastSessionRequest: null,
  seriesRequestToken: 0,
  lastReport: null,
};

const els = {};

const DEFAULT_INDICATOR_THRESHOLDS = {
  rsi: { oversold: 27, overbought: 72 },
  stoch_k: { oversold: 20, overbought: 80 },
  uo: { oversold: 30, overbought: 70 },
};

const INDICATOR_ALIASES = {
  rsi: "rsi",
  stoch: "stoch_k",
  stoch_k: "stoch_k",
  stochastic: "stoch_k",
  stochastic_k: "stoch_k",
  uo: "uo",
  ultosc: "uo",
  ultimate: "uo",
  ultimate_oscillator: "uo",
};

const DEFAULT_INDICATOR_ORDER = ["rsi", "stoch_k", "uo", "sma60"];
const LAYOUT_STORAGE_KEY = "oraclewalk.interactive.layout.v1";

async function bootstrap() {
  cacheElements();
  state.chart = new InteractiveChart(els.chart);
  state.chart.init();
  restoreLayout();
  state.chart.setChartType(state.chartType);
  state.chart.setPriceScaleMode(state.scaleMode);
  state.chart.setHoverCallback((bar) => renderOhlc(bar));
  state.chart.setClickCallback((point) => handleChartReplayClick(point));
  state.chart.setMoveCallback((point) => renderRepositionLine(point));
  state.chart.onViewportChange(() => {
    state.zones?.render();
    state.volumeProfile?.render();
  });

  state.api = new ApiFacade({
    onModeChange: (mode, reason) => {
      state.mode = mode;
      renderConnection(mode, reason);
    },
  });

  state.zones = new ZoneLayer({
    overlay: els.zoneOverlay,
    chart: state.chart,
    api: {
      createZone: (payload) => state.api.createZone(payload),
      updateZone: (id, payload) => state.api.updateZone(id, payload),
      deleteZone: (id) => state.api.deleteZone(id),
    },
    getCursor: () => state.cursor,
    onSelect: (zone) => renderSelectedZone(zone),
    onStatus: setStatus,
  });
  state.zones.init();

  state.drawings = new DrawingLayer({
    overlay: els.drawingOverlay,
    chart: state.chart,
    onStatus: setStatus,
  });
  state.drawings.init();

  state.volumeProfile = new VolumeProfile({
    overlay: els.volumeProfileOverlay,
    chart: state.chart,
    onStatus: setStatus,
  });
  state.volumeProfile.init();
  state.volumeProfile.setEnabled(state.volumeProfileEnabled);

  wireControls();
  await loadCatalog();
  // No auto-start: open the setup window first (classic-backtester style) so the
  // user picks strategy/asset/params before any backtest runs.
  openSetup({ first: true });
}

function cacheElements() {
  for (const id of [
    "symbolTitle", "connectionPill", "connectionLabel", "symbolSelect", "timeframeSelect",
    "strategySelect", "modeSelect", "newSessionBtn", "finishBtn",
    "instrumentLabel", "timeframeLabel", "barTime", "ohlcOpen", "ohlcHigh", "ohlcLow", "ohlcClose",
    "cursorLabel", "progressFill", "chartShell", "chart", "volumeProfileOverlay", "drawingOverlay", "zoneOverlay", "repositionLine",
    "chartTimeframeSelect", "chartTypeSelect", "scaleModeSelect", "volumeProfileBtn", "volumeProfileRangeBtn",
    "seekStartBtn", "stepBackBtn", "resetBtn", "timelineDate", "timelineCursor", "cursorInput",
    "cursorScrubber", "seekEndBtn",
    "playBtn", "playIcon", "playLabel", "stepBtn",
    "speedPresets", "drawZoneBtn", "supportBtn", "resistanceBtn", "zoneTimeframeSelect",
    "deleteZoneBtn", "drawingToolbar", "clearDrawingsBtn", "statusLine",
    "doneBadge", "balanceValue", "equityValue", "zonesValue", "openTradesValue", "selectedZoneState",
    "selectedZonePanel", "indicatorCount", "indicatorsList", "openTradesList", "openTradeCount",
    "eventsList", "closedCount", "reportState", "reportPanel",
    "setupModal", "setupStrategy", "setupMode", "setupModeField", "setupSymbol", "setupTimeframe",
    "setupCapital", "setupLeverage", "setupRisk", "setupCommission", "setupStartBtn", "setupCancelBtn",
    "setupCommissionPerc", "setupUseSpread", "setupFixedSpread", "setupSlippage", "setupSwapLong",
    "setupSwapShort", "setupTripleSwap", "setupPoint", "setupContractSize",
    "reportDashboard", "reportDashMeta", "reportDashMetrics", "reportDashCharts",
    "reportExportBtn", "reportCloseBtn",
  ]) {
    els[id] = document.getElementById(id);
  }
}

function wireControls() {
  els.newSessionBtn.addEventListener("click", () => openSetup());
  els.symbolSelect.addEventListener("change", () => populateTimeframes(els.symbolSelect.value));
  els.strategySelect.addEventListener("change", updateModeAvailability);

  // Setup window (pre-backtest config).
  els.setupSymbol?.addEventListener("change", () => {
    populateSetupTimeframes(els.setupSymbol.value);
    applyBrokerDefaults(els.setupSymbol.value);
  });
  els.setupStrategy?.addEventListener("change", updateSetupModeAvailability);
  els.setupStartBtn?.addEventListener("click", () => startFromSetup());
  els.setupCancelBtn?.addEventListener("click", () => closeSetup());

  // Inline report dashboard.
  els.reportExportBtn?.addEventListener("click", () => exportReportPdf());
  els.reportCloseBtn?.addEventListener("click", () => closeReportDashboard());
  els.chartTimeframeSelect.addEventListener("change", async () => {
    state.chartTimeframe = els.chartTimeframeSelect.value;
    if (state.tfIndicators?.[state.chartTimeframe]) {
      state.activeIndicatorTimeframe = state.chartTimeframe;
    }
    state.chart.setDisplayTimeframe(state.chartTimeframe);
    await refreshChartSeries();
    renderSessionHeader(state.session || {});
    renderIndicators();
    renderOhlc(state.chart.lastBar());
    state.zones.render();
    state.volumeProfile?.render(true);
    setStatus(`Grafico em ${state.chartTimeframe}`);
  });
  els.chartTypeSelect?.addEventListener("change", () => {
    state.chartType = els.chartTypeSelect.value;
    state.chart.setChartType(state.chartType);
    state.chart.syncOpenTradeLevels(state.openTrades);
    state.zones.render();
    state.drawings.render();
    state.volumeProfile?.render(true);
    saveLayout();
    setStatus(`Tipo de grafico: ${labelChartType(state.chartType)}`);
  });
  els.scaleModeSelect?.addEventListener("change", () => {
    state.scaleMode = els.scaleModeSelect.value === "log" ? "log" : "linear";
    state.chart.setPriceScaleMode(state.scaleMode);
    state.zones.render();
    state.drawings.render();
    state.volumeProfile?.render(true);
    saveLayout();
    setStatus(`Escala ${state.scaleMode === "log" ? "log" : "linear"}`);
  });
  els.volumeProfileBtn?.addEventListener("click", () => {
    state.volumeProfileEnabled = !state.volumeProfileEnabled;
    state.volumeProfilePicker = false;
    state.volumeProfilePendingStart = null;
    els.volumeProfileBtn.setAttribute("aria-pressed", String(state.volumeProfileEnabled));
    els.volumeProfileBtn.classList.toggle("active", state.volumeProfileEnabled);
    els.volumeProfileRangeBtn?.setAttribute("aria-pressed", "false");
    els.volumeProfileRangeBtn?.classList.remove("active");
    if (state.volumeProfileEnabled) state.volumeProfile?.setVisibleRangeMode();
    state.volumeProfile?.setEnabled(state.volumeProfileEnabled);
    saveLayout();
  });
  els.volumeProfileRangeBtn?.addEventListener("click", () => {
    state.volumeProfileEnabled = true;
    state.volumeProfilePicker = true;
    state.volumeProfilePendingStart = null;
    state.volumeProfile?.setEnabled(true);
    els.volumeProfileBtn?.setAttribute("aria-pressed", "true");
    els.volumeProfileBtn?.classList.add("active");
    els.volumeProfileRangeBtn.setAttribute("aria-pressed", "true");
    els.volumeProfileRangeBtn.classList.add("active");
    state.chart.setCrosshairCursor(true);
    setDrawingTool("cursor");
    setSeekPicker(false);
    setStatus("VP Range: clique no inicio do periodo");
    saveLayout();
  });
  els.chartShell?.addEventListener("click", (event) => {
    if (!state.volumeProfilePicker) return;
    event.preventDefault();
    event.stopPropagation();
    const rect = els.chartShell.getBoundingClientRect();
    const x = event.clientX - rect.left;
    state.volumeProfileDomClickAt = performance.now();
    handleVolumeProfileRangeClick({ x });
  }, true);
  els.playBtn.addEventListener("click", () => togglePlay());
  els.stepBtn.addEventListener("click", () => step(1));
  els.stepBackBtn?.addEventListener("click", () => seekToCursor(state.cursor - 1));
  els.resetBtn?.addEventListener("click", () => resetReplay());
  els.seekStartBtn?.addEventListener("click", () => toggleSeekPicker());
  els.seekEndBtn?.addEventListener("click", () => seekToCursor(state.totalBars - 1));
  els.cursorScrubber?.addEventListener("input", () => {
    state.seekPreviewCursor = clampCursor(els.cursorScrubber.value);
    renderTimeline();
  });
  els.cursorScrubber?.addEventListener("change", () => seekToCursor(els.cursorScrubber.value));
  els.cursorInput?.addEventListener("change", () => seekToCursor(els.cursorInput.value));
  els.cursorInput?.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      els.cursorInput.blur();
      seekToCursor(els.cursorInput.value);
    }
  });
  els.speedPresets.querySelectorAll("button").forEach((button) => {
    button.addEventListener("click", () => {
      state.speed = Math.max(1, Number(button.dataset.speed || 25));
      els.speedPresets.querySelectorAll("button").forEach((item) => {
        item.classList.toggle("active", item === button);
      });
      // Apply the new speed immediately if a replay is already running.
      if (state.playing) startPlayTimer();
    });
  });
  els.finishBtn.addEventListener("click", () => finish());
  els.drawZoneBtn.addEventListener("click", () => {
    const enabled = els.drawZoneBtn.getAttribute("aria-pressed") !== "true";
    els.drawZoneBtn.setAttribute("aria-pressed", String(enabled));
    state.zones.setDrawing(enabled);
    if (enabled) setDrawingTool("cursor");
  });
  els.supportBtn.addEventListener("click", () => setZoneSide("support"));
  els.resistanceBtn.addEventListener("click", () => setZoneSide("resistance"));
  els.zoneTimeframeSelect.addEventListener("change", () => {
    state.zones.select(null);
    state.zones.setTimeframe(els.zoneTimeframeSelect.value);
  });
  els.deleteZoneBtn.addEventListener("click", () => state.zones.deleteSelected());
  els.drawingToolbar?.querySelectorAll("[data-tool]").forEach((button) => {
    button.addEventListener("click", () => setDrawingTool(button.dataset.tool || "cursor"));
  });
  els.clearDrawingsBtn?.addEventListener("click", () => state.drawings.clear());

  window.addEventListener("keydown", (event) => {
    const tag = document.activeElement?.tagName?.toLowerCase();
    if (tag === "input" || tag === "textarea" || tag === "select") return;
    if (event.key === " ") {
      event.preventDefault();
      state.playing ? pause() : play();
    } else if (event.key === "ArrowRight") {
      event.preventDefault();
      step(1);
    } else if (event.key === "ArrowLeft") {
      event.preventDefault();
      seekToCursor(state.cursor - 1);
    } else if (event.key === "Escape" && state.seekPickerActive) {
      event.preventDefault();
      setSeekPicker(false);
    } else if (event.key === "Escape" && state.volumeProfilePicker) {
      event.preventDefault();
      cancelVolumeProfilePicker();
    } else if (event.key === "v" || event.key === "V") {
      setDrawingTool("cursor");
    }
  });

  if (els.chartTypeSelect) els.chartTypeSelect.value = state.chartType;
  if (els.scaleModeSelect) els.scaleModeSelect.value = state.scaleMode;
  if (els.volumeProfileBtn) {
    els.volumeProfileBtn.setAttribute("aria-pressed", String(state.volumeProfileEnabled));
    els.volumeProfileBtn.classList.toggle("active", state.volumeProfileEnabled);
  }
}

async function loadCatalog() {
  setStatus("Carregando catalogo");
  state.catalog = await state.api.catalog();
  populateCatalogControls(state.catalog);
}

function populateCatalogControls(catalog) {
  const datasets = Array.isArray(catalog?.datasets) ? catalog.datasets : [];
  const symbols = unique(datasets.map((item) => item.symbol).filter(Boolean));
  fillSelect(els.symbolSelect, symbols.length ? symbols : ["EURUSD"]);
  populateTimeframes(els.symbolSelect.value);

  const strategies = Array.isArray(catalog?.strategies) && catalog.strategies.length
    ? catalog.strategies
    : ["sr_quant", "stub"];
  fillSelect(els.strategySelect, strategies, strategies.includes("sr_quant") ? "sr_quant" : strategies[0]);

  const modes = Array.isArray(catalog?.modes) && catalog.modes.length
    ? catalog.modes
    : ["SEM", "COM", "AMBOS"];
  fillSelect(els.modeSelect, modes, modes.includes("SEM") ? "SEM" : modes[0]);
  updateModeAvailability();

  // Mirror the same options into the setup window.
  fillSelect(els.setupSymbol, symbols.length ? symbols : ["EURUSD"]);
  populateSetupTimeframes(els.setupSymbol.value);
  fillSelect(els.setupStrategy, strategies, strategies.includes("sr_quant") ? "sr_quant" : strategies[0]);
  fillSelect(els.setupMode, modes, modes.includes("SEM") ? "SEM" : modes[0]);
  applyBrokerDefaults(els.setupSymbol.value);
  updateSetupModeAvailability();
}

function populateSetupTimeframes(symbol) {
  const datasets = Array.isArray(state.catalog?.datasets) ? state.catalog.datasets : [];
  const timeframes = unique(datasets
    .filter((item) => item.symbol === symbol)
    .map((item) => item.timeframe)
    .filter(Boolean));
  fillSelect(els.setupTimeframe, timeframes.length ? timeframes : ["H1"]);
}

function updateSetupModeAvailability() {
  const usesMode = els.setupStrategy.value === "sr_quant";
  els.setupMode.disabled = !usesMode;
  els.setupModeField?.classList.toggle("disabled", !usesMode);
}

function openSetup({ first = false } = {}) {
  pause();
  // Mirror the live selectors into the modal so it reflects the current session.
  if (!first) {
    if (els.symbolSelect.value) { els.setupSymbol.value = els.symbolSelect.value; populateSetupTimeframes(els.setupSymbol.value); }
    if (els.timeframeSelect.value) els.setupTimeframe.value = els.timeframeSelect.value;
    if (els.strategySelect.value) els.setupStrategy.value = els.strategySelect.value;
    if (els.modeSelect.value) els.setupMode.value = els.modeSelect.value;
  }
  updateSetupModeAvailability();
  // Can't cancel the very first setup (there's no session to fall back to).
  if (els.setupCancelBtn) els.setupCancelBtn.hidden = Boolean(first) && !state.session;
  els.setupModal.hidden = false;
}

function closeSetup() {
  if (!state.session) return; // keep the modal up until a session exists
  els.setupModal.hidden = true;
}

async function startFromSetup() {
  // Push the modal choices into the live selectors, then run the standard flow.
  els.setupSymbol.value && (els.symbolSelect.value = els.setupSymbol.value);
  populateTimeframes(els.symbolSelect.value);
  if (els.setupTimeframe.value && [...els.timeframeSelect.options].some((o) => o.value === els.setupTimeframe.value)) {
    els.timeframeSelect.value = els.setupTimeframe.value;
  }
  els.setupStrategy.value && (els.strategySelect.value = els.setupStrategy.value);
  els.setupMode.value && (els.modeSelect.value = els.setupMode.value);
  updateModeAvailability();
  els.setupModal.hidden = true;
  await startNewSession();
}

function readSetupEngine() {
  const num = (el) => {
    const v = Number(el?.value);
    return el && el.value !== "" && Number.isFinite(v) ? v : undefined;
  };
  const bool = (el) => (el ? Boolean(el.checked) : undefined);
  const engine = {
    initial_capital: num(els.setupCapital),
    leverage: num(els.setupLeverage),
    risk_per_trade_pct: num(els.setupRisk),
    commission_per_lot: num(els.setupCommission),
    commission_perc: num(els.setupCommissionPerc),
    use_spread: bool(els.setupUseSpread),
    fixed_spread_points: num(els.setupFixedSpread),
    slippage: num(els.setupSlippage),
    swap_long_per_lot: num(els.setupSwapLong),
    swap_short_per_lot: num(els.setupSwapShort),
    triple_swap_weekday: num(els.setupTripleSwap),
    point: num(els.setupPoint),
    contract_size: num(els.setupContractSize),
  };
  // Drop undefined keys so the backend keeps its defaults for blank fields.
  return Object.fromEntries(Object.entries(engine).filter(([, v]) => v !== undefined));
}

function applyBrokerDefaults(symbol) {
  const presets = {
    EURUSD: {
      point: 0.00001,
      contract_size: 100000,
      commission_per_lot: 3.5,
      leverage: 30,
      swap_long_per_lot: -7.5,
      swap_short_per_lot: 2.5,
    },
    XAUUSD: {
      point: 0.01,
      contract_size: 100,
      commission_per_lot: 0,
      leverage: 100,
      swap_long_per_lot: 0,
      swap_short_per_lot: 0,
    },
  };
  const preset = presets[String(symbol || "").toUpperCase()];
  if (!preset) return;
  setDefaultNumber(els.setupPoint, preset.point);
  setDefaultNumber(els.setupContractSize, preset.contract_size);
  setDefaultNumber(els.setupCommission, preset.commission_per_lot);
  setDefaultNumber(els.setupLeverage, preset.leverage);
  setDefaultNumber(els.setupSwapLong, preset.swap_long_per_lot);
  setDefaultNumber(els.setupSwapShort, preset.swap_short_per_lot);
}

function setDefaultNumber(el, value) {
  if (!el || el.dataset.touched === "true") return;
  el.value = String(value);
  el.addEventListener("input", () => { el.dataset.touched = "true"; }, { once: true });
}

function populateTimeframes(symbol) {
  const datasets = Array.isArray(state.catalog?.datasets) ? state.catalog.datasets : [];
  const timeframes = unique(datasets
    .filter((item) => item.symbol === symbol)
    .map((item) => item.timeframe)
    .filter(Boolean));
  fillSelect(els.timeframeSelect, timeframes.length ? timeframes : ["H1"]);
}

function updateModeAvailability() {
  const usesMode = els.strategySelect.value === "sr_quant";
  els.modeSelect.disabled = !usesMode;
  els.modeSelect.closest("label")?.classList.toggle("disabled", !usesMode);
}

function fillSelect(select, values, preferred) {
  const previous = select.value;
  select.replaceChildren(...values.map((value) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    return option;
  }));
  if (preferred && values.includes(preferred)) {
    select.value = preferred;
  } else if (previous && values.includes(previous)) {
    select.value = previous;
  }
}

function unique(values) {
  return [...new Set(values)];
}

function setDrawingTool(tool) {
  const normalized = tool || "cursor";
  state.drawings?.setTool(normalized);
  els.drawingToolbar?.querySelectorAll("[data-tool]").forEach((button) => {
    button.classList.toggle("active", button.dataset.tool === normalized);
  });
  if (normalized !== "cursor") {
    els.drawZoneBtn?.setAttribute("aria-pressed", "false");
    state.zones?.setDrawing(false);
    setSeekPicker(false);
  }
}

function cancelVolumeProfilePicker() {
  state.volumeProfilePicker = false;
  state.volumeProfilePendingStart = null;
  state.chart.setCrosshairCursor(false);
  els.volumeProfileRangeBtn?.setAttribute("aria-pressed", "false");
  els.volumeProfileRangeBtn?.classList.remove("active");
  setStatus("VP Range cancelado");
}

function restoreLayout() {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(LAYOUT_STORAGE_KEY) || "{}");
    state.chartType = ["candles", "bars", "line", "area"].includes(parsed.chartType) ? parsed.chartType : state.chartType;
    state.scaleMode = parsed.scaleMode === "log" ? "log" : "linear";
    state.volumeProfileEnabled = parsed.volumeProfileEnabled !== false;
  } catch {
    state.chartType = "candles";
    state.scaleMode = "linear";
    state.volumeProfileEnabled = true;
  }
}

function saveLayout() {
  try {
    window.localStorage.setItem(LAYOUT_STORAGE_KEY, JSON.stringify({
      chartType: state.chartType,
      scaleMode: state.scaleMode,
      volumeProfileEnabled: state.volumeProfileEnabled,
    }));
  } catch {
    // localStorage can be disabled; layout still works during the current session.
  }
}

function labelChartType(type) {
  return {
    candles: "candles",
    bars: "barras",
    line: "linha",
    area: "area",
  }[type] || "candles";
}

function setZoneSide(side) {
  state.zones.setSide(side);
  state.zones.setSelectedSide(side);
  els.supportBtn.classList.toggle("active", side === "support");
  els.resistanceBtn.classList.toggle("active", side === "resistance");
}

async function startNewSession() {
  pause();
  setBusy(true);
  setStatus("Criando sessao");
  state.done = false;
  state.closedEvents = [];
  renderReport(null);
  closeReportDashboard();

  try {
    const request = selectedSessionRequest();
    state.lastSessionRequest = request;
    const session = await state.api.newSession(request);
    applySession(session);
    await refreshChartSeries();
    setStatus(state.mode === "mock" ? "Mock local ativo" : "Sessao pronta");
  } catch (error) {
    renderConnection("error", error.message || error);
    setStatus(`Erro: ${error.message || error}`);
  } finally {
    setBusy(false);
  }
}

function applySession(session) {
  state.session = session;
  state.cursor = Number(session.cursor ?? 0);
  state.warmupCursor = Number(session.warmup_bars ?? state.cursor);
  state.totalBars = Number(session.total_bars ?? session.history?.length ?? 0);
  state.balance = Number(session.balance ?? 1000);
  state.equity = Number(session.equity ?? state.balance);
  state.indicators = session.indicators || {};
  state.tfIndicators = session.tf_indicators || {};
  state.indicatorThresholds = session.indicator_thresholds || {};
  state.indicatorsMeta = indicatorsMetaFromSession(session);
  state.activeIndicatorTimeframe = "";
  state.zoneTimeframes = normalizeZoneTimeframes(session);
  state.chartTimeframes = normalizeChartTimeframes(session, state.zoneTimeframes);
  // Default the chart view to the TF the user picked (display_timeframe), even though
  // the replay base is the finest TF — so "select H4" shows H4 while H1 zones exist.
  const wantDisplay = String(session.display_timeframe || "").toUpperCase();
  state.chartTimeframe = (state.chartTimeframes.includes(wantDisplay) ? wantDisplay : null)
    || state.chartTimeframes[0] || session.base_timeframe || session.timeframe || "H1";
  state.seekPreviewCursor = null;
  setSeekPicker(false);
  populateChartTimeframeSelect(state.chartTimeframes, state.chartTimeframe);
  populateZoneTimeframeSelect(state.zoneTimeframes, session.base_timeframe || session.timeframe);
  state.openTrades = session.open_trades || [];
  state.done = Boolean(session.done);

  state.chart.setHistory(session.history || [], {
    baseTimeframe: session.base_timeframe || session.timeframe || state.chartTimeframe,
    displayTimeframe: state.chartTimeframe,
  });
  state.chart.configureIndicators(state.indicatorsMeta);
  state.zones.sync(session.zones || []);
  state.volumeProfile?.render(true);
  renderSessionHeader(session);
  renderSnapshot({
    cursor: state.cursor,
    total_bars: state.totalBars,
    done: state.done,
    indicators: state.indicators,
    tf_indicators: state.tfIndicators,
    indicator_thresholds: state.indicatorThresholds,
    indicators_meta: state.indicatorsMeta,
    balance: state.balance,
    equity: state.equity,
    open_trades: state.openTrades,
    closed_now: [],
    zones: session.zones || [],
  });
  renderOhlc(state.chart.lastBar());
}

function normalizeZoneTimeframes(session) {
  const values = Array.isArray(session?.zone_timeframes) && session.zone_timeframes.length
    ? session.zone_timeframes
    : [session?.base_timeframe || session?.timeframe || els.timeframeSelect.value || "H1"];
  return unique(values.filter(Boolean));
}

function normalizeChartTimeframes(session, zoneTimeframes) {
  const base = session?.base_timeframe || session?.timeframe || els.timeframeSelect.value || "H1";
  const baseMinutes = timeframeMinutes(base);
  const values = unique([base, ...(zoneTimeframes || [])])
    .filter((tf) => timeframeMinutes(tf) >= baseMinutes)
    .sort(sortTimeframe);
  return values.length ? values : [base];
}

function indicatorsMetaFromSession(session) {
  if (session?.indicators_meta) return session.indicators_meta;
  const thresholds = session?.indicator_thresholds || {};
  const paneKeys = Object.keys(thresholds).filter((key) => key !== "sma60");
  return {
    overlays: ["sma60"],
    panes: paneKeys.map((key) => ({
      key,
      range: [0, 100],
      oversold: thresholds[key]?.oversold,
      overbought: thresholds[key]?.overbought,
    })),
  };
}

async function refreshChartSeries() {
  if (!state.session) return;
  const token = ++state.seriesRequestToken;
  state.chart.configureIndicators(state.indicatorsMeta);
  const series = await state.api.series({ tf: state.chartTimeframe }).catch(() => null);
  if (token !== state.seriesRequestToken) return;
  if (series) {
    state.chart.setIndicatorSeries(series);
    return;
  }
  state.chart.clearIndicatorData();
  state.chart.appendIndicatorPoint(state.chart.lastBar()?.time, currentChartIndicators());
}

function currentChartIndicators() {
  return state.tfIndicators?.[state.chartTimeframe] || state.indicators || {};
}

function populateChartTimeframeSelect(timeframes, preferred) {
  const values = timeframes.length ? timeframes : ["H1"];
  fillSelect(els.chartTimeframeSelect, values, values.includes(preferred) ? preferred : values[0]);
  state.chartTimeframe = els.chartTimeframeSelect.value;
}

function populateZoneTimeframeSelect(timeframes, preferred) {
  const values = timeframes.length ? timeframes : ["H1"];
  fillSelect(els.zoneTimeframeSelect, values, values.includes(preferred) ? preferred : values[0]);
  state.zones.setTimeframe(els.zoneTimeframeSelect.value);
}

function selectedSessionRequest() {
  const request = {
    symbol: els.symbolSelect.value || undefined,
    timeframe: els.timeframeSelect.value || undefined,
    strategy: els.strategySelect.value || "sr_quant",
  };
  if (request.strategy === "sr_quant") {
    request.mode = els.modeSelect.value || "SEM";
  }
  const engine = readSetupEngine();
  if (Object.keys(engine).length) request.engine = engine;
  return request;
}

function play() {
  if (state.playing || state.done || !state.session) return;
  // Clear a possibly-stuck guard from a prior failed step, which would otherwise
  // make every tick return early (replay "running" but frozen).
  state.stepping = false;
  state.playing = true;
  setPlayButton();
  startPlayTimer();
  setStatus("Replay rodando");
}

function startPlayTimer() {
  if (state.timer) {
    clearInterval(state.timer);
    state.timer = null;
  }
  // `speed` is candles/second. Advance ONE candle per tick at an interval matching
  // the speed (so it animates smoothly instead of blasting to the end). Only batch
  // candles per tick for very high speeds. The async `step` self-throttles via the
  // `stepping` guard if the network is slower than the interval.
  const cps = Math.max(1, Number(state.speed) || 1);
  const intervalMs = Math.max(16, Math.round(1000 / cps));
  const perStep = cps > 60 ? Math.max(1, Math.round(cps / 60)) : 1;
  state.timer = window.setInterval(() => step(perStep), intervalMs);
}

function pause() {
  state.playing = false;
  if (state.timer) {
    clearInterval(state.timer);
    state.timer = null;
  }
  setPlayButton();
  renderTimeline(); // re-enable controls that were disabled mid-step
  setStatus(state.done ? "Replay finalizado" : "Replay pausado");
}

function togglePlay() {
  state.playing ? pause() : play();
}

function setPlayButton() {
  els.playBtn.classList.toggle("playing", state.playing);
  els.playLabel.textContent = state.playing ? "Pause" : "Play";
  els.playIcon.innerHTML = state.playing
    ? '<rect x="4" y="3" width="3" height="10"></rect><rect x="9" y="3" width="3" height="10"></rect>'
    : '<path d="M4 3 L13 8 L4 13 Z"></path>';
}

async function step(n) {
  if (state.stepping || state.seeking || state.done) return;
  state.stepping = true;
  try {
    await applyStep(n);
  } catch (error) {
    pause();
    setStatus(`Erro no step: ${error.message || error}`);
  } finally {
    state.stepping = false;
  }
}

async function applyStep(n) {
  const snapshot = await state.api.step({ n });
  state.chart.appendBars(snapshot.bars || []);
  state.volumeProfile?.render();
  state.chart.upsertTradeMarkers(snapshot.open_trades || [], snapshot.closed_now || []);
  renderSnapshot(snapshot);
  renderOhlc(state.chart.lastBar());
  if (snapshot.done) pause();
  return snapshot;
}

async function seekToCursor(rawTarget) {
  const target = clampCursor(rawTarget);
  state.seekPreviewCursor = null;
  renderTimeline();
  if (!state.session || state.seeking || state.stepping || target === state.cursor) return;
  pause();
  state.seeking = true;
  setBusy(true);
  try {
    setStatus(`Indo para candle ${target}`);
    state.closedEvents = [];
    renderEvents();
    const snapshot = await state.api.seek({ bar: target });
    await syncChartHistoryAfterSeek(snapshot);
    state.chart.upsertTradeMarkers(snapshot.open_trades || [], snapshot.closed_now || []);
    renderSnapshot(snapshot);
    renderOhlc(state.chart.lastBar());
    await refreshChartSeries();
    state.volumeProfile?.render(true);
    setStatus(`Replay no candle ${state.cursor}`);
  } catch (error) {
    setStatus(`Erro ao navegar no tempo: ${error.message || error}`);
  } finally {
    state.seeking = false;
    setBusy(false);
    renderTimeline();
  }
}

async function resetReplay() {
  if (!state.session || state.seeking || state.stepping) return;
  pause();
  state.seeking = true;
  setBusy(true);
  try {
    setStatus("Resetando replay");
    state.closedEvents = [];
    renderEvents();
    const snapshot = await state.api.reset();
    if (snapshot?.history) {
      applySession(snapshot);
    } else {
      await syncChartHistoryAfterSeek(snapshot);
      renderSnapshot(snapshot);
      renderOhlc(state.chart.lastBar());
      await refreshChartSeries();
    }
    state.volumeProfile?.render(true);
    setStatus("Replay voltou ao inicio");
  } catch (error) {
    setStatus(`Erro ao resetar: ${error.message || error}`);
  } finally {
    state.seeking = false;
    setBusy(false);
    renderTimeline();
  }
}

async function syncChartHistoryAfterSeek(snapshot) {
  const series = await state.api.series({ tf: state.session?.base_timeframe || state.session?.timeframe || state.chartTimeframe })
    .catch(() => null);
  const history = barsFromSeries(series);
  if (history.length) {
    state.chart.setHistory(history, {
      baseTimeframe: state.session?.base_timeframe || state.session?.timeframe || state.chartTimeframe,
      displayTimeframe: state.chartTimeframe,
    });
    return;
  }
  if (Array.isArray(snapshot.bars) && snapshot.bars.length) {
    state.chart.appendBars(snapshot.bars);
  }
}

function barsFromSeries(series) {
  const times = Array.isArray(series?.time) ? series.time : [];
  return times.map((time, index) => ({
    time,
    open: series.open?.[index],
    high: series.high?.[index],
    low: series.low?.[index],
    close: series.close?.[index],
    volume: series.volume?.[index] ?? 0,
  })).filter((bar) => Number.isFinite(Number(bar.open))
    && Number.isFinite(Number(bar.high))
    && Number.isFinite(Number(bar.low))
    && Number.isFinite(Number(bar.close)));
}

async function finish() {
  pause();
  setBusy(true);
  setStatus("Finalizando");
  try {
    const result = await state.api.finish();
    state.done = true;
    state.lastReport = result;
    renderReport(result);
    renderSnapshot({ ...snapshotFromState(), done: true });
    // Show the report INLINE below the candle chart (charts + metrics), like the
    // classic graphic backtester. PDF export is on-demand via the Exportar button.
    renderReportDashboard(result);
    openReportDashboard();
    setStatus("Relatorio gerado");
  } catch (error) {
    setStatus(`Erro ao finalizar: ${error.message || error}`);
  } finally {
    setBusy(false);
  }
}

function renderSnapshot(snapshot) {
  state.cursor = Number(snapshot.cursor ?? state.cursor);
  state.totalBars = Number(snapshot.total_bars ?? state.totalBars);
  state.balance = Number(snapshot.balance ?? state.balance);
  state.equity = Number(snapshot.equity ?? state.equity);
  state.indicators = snapshot.indicators || {};
  state.tfIndicators = snapshot.tf_indicators || state.tfIndicators || {};
  state.indicatorThresholds = snapshot.indicator_thresholds || state.indicatorThresholds || {};
  state.indicatorsMeta = snapshot.indicators_meta || state.indicatorsMeta || {};
  if (state.activeIndicatorTimeframe && !state.tfIndicators?.[state.activeIndicatorTimeframe]) {
    state.activeIndicatorTimeframe = "";
  }
  state.openTrades = snapshot.open_trades || [];
  state.done = Boolean(snapshot.done);

  if (Array.isArray(snapshot.closed_now) && snapshot.closed_now.length) {
    state.closedEvents = [...snapshot.closed_now, ...state.closedEvents].slice(0, 8);
  }
  if (Array.isArray(snapshot.zones)) state.zones.sync(snapshot.zones);
  state.chart.syncOpenTradeLevels(state.openTrades);
  state.chart.appendIndicatorPoint(state.chart.lastBar()?.time, currentChartIndicators());
  state.volumeProfile?.render();

  renderProgress();
  renderMetrics();
  renderIndicators();
  renderOpenTrades();
  renderEvents();
}

function snapshotFromState() {
  return {
    cursor: state.cursor,
    total_bars: state.totalBars,
    balance: state.balance,
    equity: state.equity,
    indicators: state.indicators,
    tf_indicators: state.tfIndicators,
    indicator_thresholds: state.indicatorThresholds,
    indicators_meta: state.indicatorsMeta,
    open_trades: state.openTrades,
    closed_now: [],
    zones: [...state.zones.zones.values()],
  };
}

function renderSessionHeader(session) {
  const symbol = session.symbol || "UNKNOWN";
  const baseTimeframe = session.base_timeframe || session.timeframe || "TF";
  const displayTimeframe = state.chartTimeframe || baseTimeframe;
  els.symbolTitle.textContent = `${symbol} ${displayTimeframe}`;
  els.instrumentLabel.textContent = symbol;
  els.timeframeLabel.textContent = displayTimeframe === baseTimeframe ? displayTimeframe : `${displayTimeframe} / base ${baseTimeframe}`;
}

function renderConnection(mode, reason) {
  els.connectionPill.classList.remove("connected", "mock", "error");
  if (mode === "mock") {
    els.connectionPill.classList.add("mock");
    els.connectionLabel.textContent = "Mock";
    if (reason) setStatus(`Mock local: ${reason}`);
  } else if (mode === "error") {
    els.connectionPill.classList.add("error");
    els.connectionLabel.textContent = "Erro";
  } else {
    els.connectionPill.classList.add("connected");
    els.connectionLabel.textContent = "API real";
  }
}

function renderProgress() {
  const total = Math.max(1, state.totalBars);
  const pct = Math.max(0, Math.min(100, (state.cursor / total) * 100));
  els.cursorLabel.textContent = `${state.cursor} / ${state.totalBars}`;
  els.progressFill.style.width = `${pct}%`;
  els.doneBadge.textContent = state.done ? "Fim" : "Ativo";
  renderTimeline();
}

function renderTimeline() {
  const maxCursor = Math.max(state.warmupCursor, state.totalBars - 1, 0);
  const current = clampCursor(state.cursor);
  const preview = state.seekPreviewCursor ?? current;
  if (els.cursorInput) {
    els.cursorInput.min = String(state.warmupCursor || 0);
    els.cursorInput.max = String(maxCursor);
    els.cursorInput.value = String(preview);
  }
  if (els.cursorScrubber) {
    els.cursorScrubber.min = String(state.warmupCursor || 0);
    els.cursorScrubber.max = String(maxCursor);
    els.cursorScrubber.value = String(preview);
    els.cursorScrubber.disabled = state.seeking || !state.session;
  }
  if (els.timelineCursor) els.timelineCursor.textContent = `${preview} / ${state.totalBars || 0}`;
  if (els.timelineDate) els.timelineDate.textContent = labelForCursor(preview);
  if (els.stepBackBtn) els.stepBackBtn.disabled = state.seeking || current <= state.warmupCursor;
  if (els.seekStartBtn) {
    // Always clickable — it's a mode toggle (and entering it pauses the replay).
    els.seekStartBtn.disabled = false;
    els.seekStartBtn.classList.toggle("active", state.seekPickerActive);
  }
  if (els.seekEndBtn) els.seekEndBtn.disabled = state.seeking || current >= maxCursor;
  if (els.resetBtn) els.resetBtn.disabled = state.seeking || current <= state.warmupCursor;
}

function toggleSeekPicker() {
  setSeekPicker(!state.seekPickerActive);
}

// Reposition mode: a single toggle (scissors). While active, clicking anywhere on
// the chart jumps the replay to that candle — no gray strip needed.
function setSeekPicker(enabled) {
  state.seekPickerActive = Boolean(enabled);
  state.seekPreviewCursor = null;
  state.chart?.setCrosshairCursor?.(state.seekPickerActive);
  if (els.seekStartBtn) els.seekStartBtn.classList.toggle("active", state.seekPickerActive);
  if (state.seekPickerActive) {
    pause();
    els.drawZoneBtn?.setAttribute("aria-pressed", "false");
    state.zones?.setDrawing(false);
    state.drawings?.setTool("cursor");
    els.drawingToolbar?.querySelectorAll("[data-tool]").forEach((button) => {
      button.classList.toggle("active", button.dataset.tool === "cursor");
    });
    setStatus("Clique no gráfico para posicionar o replay (Esc cancela)");
  } else {
    hideRepositionLine();
    setStatus(state.done ? "Replay finalizado" : "Replay pausado");
  }
  renderTimeline();
}

// Click on the chart while in reposition mode -> seek the replay there.
// `logical` is the candle index in the series (== engine bar index on the base TF).
function handleChartReplayClick(point) {
  if (state.volumeProfilePicker) {
    return;
  }
  if (!state.seekPickerActive || !state.session) return;
  const fromX = point?.x != null ? state.chart.xToCursor(point.x) : null;
  const logical = point?.logical;
  if (!Number.isFinite(fromX) && (logical == null || !Number.isFinite(logical))) return;
  const target = clampCursor(Number.isFinite(fromX) ? fromX : Math.round(logical));
  setSeekPicker(false);
  seekToCursor(target);
}

function handleVolumeProfileRangeClick(point) {
  const cursor = point?.x != null ? state.chart.xToCursor?.(point.x) : null;
  const time = Number.isFinite(cursor)
    ? state.chart.getBarTimeByIndex?.(cursor)
    : point?.time;
  if (time == null) return;
  if (state.volumeProfilePendingStart == null) {
    state.volumeProfilePendingStart = time;
    state.volumeProfile?.setFixedRange(time, null);
    setStatus("VP Range: clique no fim do periodo");
    return;
  }
  state.volumeProfile?.completeFixedRange(time);
  state.volumeProfilePicker = false;
  state.volumeProfilePendingStart = null;
  state.chart.setCrosshairCursor(false);
  els.volumeProfileRangeBtn?.setAttribute("aria-pressed", "false");
  els.volumeProfileRangeBtn?.classList.remove("active");
  setStatus("Volume Profile fixo aplicado");
}

function renderSeekLine() { /* gray seek strip removed — reposition is via chart click */ }

// Blue vertical line that tracks the cursor while reposition mode is active.
function renderRepositionLine(point) {
  const line = els.repositionLine;
  if (!line) return;
  const x = point?.x;
  if (!state.seekPickerActive || x == null || !Number.isFinite(x)) {
    line.hidden = true;
    return;
  }
  line.hidden = false;
  line.style.left = `${Math.round(x)}px`;
}

function hideRepositionLine() {
  if (els.repositionLine) els.repositionLine.hidden = true;
}

function clampCursor(value) {
  const n = Math.round(Number(value));
  const min = Math.max(0, Number(state.warmupCursor || 0));
  const max = Math.max(min, Number(state.totalBars || 0) - 1);
  if (!Number.isFinite(n)) return state.cursor || min;
  return Math.max(min, Math.min(max, n));
}

function labelForCursor(cursor) {
  if (cursor > state.cursor) return `candle ${cursor}`;
  const time = state.chart?.getBarTimeByIndex?.(cursor);
  return time ? formatDateTime(time) : "--";
}

function renderMetrics() {
  els.balanceValue.textContent = formatMoney(state.balance);
  els.equityValue.textContent = formatMoney(state.equity);
  els.zonesValue.textContent = String(state.zones.countActive());
  els.openTradesValue.textContent = String(state.openTrades.length);
  els.openTradeCount.textContent = String(state.openTrades.length);
}

function renderIndicators() {
  const tfKeys = unique([
    ...(state.zoneTimeframes || []),
    ...Object.keys(state.tfIndicators || {}),
  ]).filter(Boolean).sort(sortTimeframe);
  const tfEntries = tfKeys.map((tf) => [tf, state.tfIndicators?.[tf] || {}]);
  if (tfEntries.length) {
    const indicatorKeys = orderedIndicatorKeys(tfEntries);
    const totalIndicators = tfEntries.length * indicatorKeys.length;
    els.indicatorCount.textContent = String(totalIndicators);

    els.indicatorsList.replaceChildren(...tfEntries.map(([timeframe, values]) => {
      const available = indicatorKeys.filter((key) => hasIndicatorValue(values, key)).length;
      const card = document.createElement("div");
      card.className = "tf-indicator-card";

      const head = document.createElement("div");
      head.className = "tf-indicator-head";
      head.append(strong(timeframe), textSpan(indicatorStatusLabel(available, indicatorKeys.length)));

      const body = document.createElement("div");
      body.className = "tf-indicator-grid";
      if (!indicatorKeys.length) {
        body.append(emptyNode("Warmup"));
      } else {
        body.append(...indicatorKeys.map((key) => indicatorRow(key, values?.[key], {
          missing: !hasIndicatorValue(values, key),
        })));
      }

      card.append(head, body);
      return card;
    }));
    return;
  }

  const entries = Object.entries(state.indicators || {});
  els.indicatorCount.textContent = String(entries.length);
  if (!entries.length) {
    els.indicatorsList.replaceChildren(emptyNode("Sem dados"));
    return;
  }
  els.indicatorsList.replaceChildren(...entries.map(([key, value]) => indicatorRow(key, value)));
}

function orderedIndicatorKeys(tfEntries) {
  const keys = new Map(DEFAULT_INDICATOR_ORDER.map((key) => [key, key]));
  for (const [, values] of tfEntries) {
    for (const rawKey of Object.keys(values || {})) {
      const key = normalizeIndicatorKey(rawKey);
      if (!keys.has(key)) keys.set(key, rawKey);
    }
  }
  return [...keys.values()];
}

function hasIndicatorValue(values, key) {
  if (values?.[key] == null || values?.[key] === "") return false;
  return Number.isFinite(Number(values?.[key]));
}

function indicatorStatusLabel(available, total) {
  if (!total || !available) return "warmup";
  if (available >= total) return "ativo";
  return `${available}/${total}`;
}

function indicatorRow(key, value, { missing = false } = {}) {
  const row = document.createElement("div");
  const signal = indicatorSignal(key, value);
  row.className = `kv-row${signal ? ` indicator-${signal}` : ""}${missing ? " indicator-missing" : ""}`;
  row.append(textSpan(key), strong(formatNumber(value)));
  return row;
}

function indicatorSignal(key, value) {
  const normalizedKey = normalizeIndicatorKey(key);
  const limits = state.indicatorThresholds?.[normalizedKey] || DEFAULT_INDICATOR_THRESHOLDS[normalizedKey];
  if (value == null || value === "") return "";
  const n = Number(value);
  if (!limits || !Number.isFinite(n)) return "";
  const oversold = Number(limits.oversold);
  const overbought = Number(limits.overbought);
  if (Number.isFinite(oversold) && n < oversold) return "oversold";
  if (Number.isFinite(overbought) && n > overbought) return "overbought";
  return "";
}

function normalizeIndicatorKey(key) {
  const normalized = String(key || "")
    .trim()
    .toLowerCase()
    .replace(/[%\s-]+/g, "_");
  return INDICATOR_ALIASES[normalized] || normalized;
}

function sortTimeframe(a, b) {
  return timeframeMinutes(a) - timeframeMinutes(b);
}

function timeframeMinutes(value) {
  const match = String(value).match(/^([A-Z]+)(\d+)$/i);
  if (!match) return Number.MAX_SAFE_INTEGER;
  const n = Number(match[2]);
  const unit = match[1].toUpperCase();
  if (unit === "M") return n;
  if (unit === "H") return n * 60;
  if (unit === "D") return n * 1440;
  return Number.MAX_SAFE_INTEGER;
}

function aggregateMockBars(bars, displayTimeframe, baseTimeframe) {
  const displayMinutes = timeframeMinutes(displayTimeframe);
  const baseMinutes = timeframeMinutes(baseTimeframe);
  if (!Number.isFinite(displayMinutes) || !Number.isFinite(baseMinutes) || displayMinutes <= baseMinutes) {
    return [...bars];
  }
  const bucketSeconds = displayMinutes * 60;
  const buckets = new Map();
  for (const bar of bars) {
    const time = Math.floor(normalizeTime(bar.time) / bucketSeconds) * bucketSeconds;
    const existing = buckets.get(time);
    if (!existing) {
      buckets.set(time, { ...bar, time });
      continue;
    }
    existing.high = Math.max(existing.high, bar.high);
    existing.low = Math.min(existing.low, bar.low);
    existing.close = bar.close;
    existing.volume += Number(bar.volume || 0);
  }
  return [...buckets.values()].sort((a, b) => a.time - b.time);
}

function renderOpenTrades() {
  if (!state.openTrades.length) {
    els.openTradesList.replaceChildren(emptyNode("Nenhum trade aberto"));
    return;
  }
  els.openTradesList.replaceChildren(...state.openTrades.map((trade) => {
    const item = document.createElement("div");
    const direction = trade.direction === "short" ? "short" : "long";
    item.className = `trade-item ${direction}`;
    const pnl = Number(trade.unrealized_pnl ?? 0);
    item.append(
      titleRow(`#${trade.id}`, direction.toUpperCase(), direction),
      metaLine(`Entry ${formatPrice(trade.entry_price)} | SL ${formatPrice(trade.stop_price)} | TP ${formatPrice(trade.take_price)}`),
      metaLine(`Size ${formatNumber(trade.size)} | PnL ${formatSignedMoney(pnl)}`),
    );
    return item;
  }));
}

function renderEvents() {
  els.closedCount.textContent = String(state.closedEvents.length);
  if (!state.closedEvents.length) {
    els.eventsList.replaceChildren(emptyNode("Nenhum fechamento"));
    return;
  }
  els.eventsList.replaceChildren(...state.closedEvents.map((event) => {
    const item = document.createElement("div");
    item.className = "event-item";
    const pnl = Number(event.pnl ?? 0);
    item.append(
      titleRow(`#${event.id}`, formatSignedMoney(pnl), pnl >= 0 ? "win" : "loss"),
      metaLine(`${event.exit_reason || "exit"} | ${formatPrice(event.entry_price)} -> ${formatPrice(event.exit_price)}`),
    );
    return item;
  }));
}

function renderSelectedZone(zone) {
  els.deleteZoneBtn.disabled = !zone;
  els.selectedZoneState.textContent = zone?.state || "--";
  if (!zone) {
    els.selectedZonePanel.className = "empty-panel";
    els.selectedZonePanel.textContent = "--";
    return;
  }
  els.supportBtn.classList.toggle("active", zone.side === "support");
  els.resistanceBtn.classList.toggle("active", zone.side === "resistance");
  if (zone.timeframe && [...els.zoneTimeframeSelect.options].some((option) => option.value === zone.timeframe)) {
    els.zoneTimeframeSelect.value = zone.timeframe;
    state.zones.setTimeframe(zone.timeframe);
  }
  els.selectedZonePanel.className = "kv-list";
  const rows = [
    ["ID", zone.id],
    ["TF", zone.timeframe || "--"],
    ["Lado", zone.side],
    ["Low", formatPrice(zone.price_low)],
    ["High", formatPrice(zone.price_high)],
    ["Criada", zone.created_at_bar],
  ].map(([key, value]) => {
    const row = document.createElement("div");
    row.className = "kv-row";
    row.append(textSpan(key), strong(String(value)));
    return row;
  });
  els.selectedZonePanel.replaceChildren(...rows);
}

function renderOhlc(bar) {
  if (!bar) return;
  const normalized = normalizeBar(bar);
  els.barTime.textContent = formatDateTime(normalized.time);
  els.ohlcOpen.textContent = formatPrice(normalized.open);
  els.ohlcHigh.textContent = formatPrice(normalized.high);
  els.ohlcLow.textContent = formatPrice(normalized.low);
  els.ohlcClose.textContent = formatPrice(normalized.close);
}

function renderReport(result) {
  if (!result) {
    els.reportState.textContent = "--";
    els.reportPanel.textContent = "--";
    return;
  }
  els.reportState.textContent = "Pronto";
  const panel = document.createElement("div");
  if (result.report_html) {
    const link = document.createElement("a");
    link.href = result.report_html;
    link.target = "_blank";
    link.rel = "noopener";
    link.textContent = result.report_html;
    panel.append(link);
  }
  const metrics = result.metrics || {};
  const metricText = [
    `Net ${formatSignedMoney(metrics.net_profit ?? 0)}`,
    `PF ${formatNumber(metrics.profit_factor)}`,
    `DD ${formatSignedMoney(metrics.max_drawdown ?? 0)}`,
    `Trades ${metrics.trades ?? 0}`,
  ].join(" | ");
  panel.append(document.createElement("br"), document.createTextNode(metricText));
  els.reportPanel.replaceChildren(panel);
}

// ----- Inline report dashboard (charts + metrics below the candle chart) -----

const REPORT_METRIC_CARDS = [
  ["Lucro liquido", (m) => formatSignedMoney(m.net_profit ?? 0)],
  ["Retorno %", (m) => formatPctValue(m.net_return_pct)],
  ["Saldo final", (m) => formatMoney(m.final_balance)],
  ["Trades", (m) => String(m.total_trades ?? m.trades ?? 0)],
  ["Win rate", (m) => (m.win_rate != null ? `${Number(m.win_rate).toFixed(1)}%` : "--")],
  ["Profit factor", (m) => formatRatioValue(m.profit_factor)],
  ["Max drawdown", (m) => formatPctValue(m.max_drawdown_pct)],
  ["Expectancy", (m) => formatSignedMoney(m.expectancy ?? 0)],
  ["Payoff", (m) => formatRatioValue(m.payoff_ratio)],
  ["Sharpe/trade", (m) => formatRatioValue(m.sharpe_per_trade)],
];

function renderReportDashboard(result) {
  const metrics = result?.metrics_full || result?.metrics || {};
  const images = Array.isArray(result?.images) ? result.images : [];

  const symbol = state.session?.symbol || els.symbolSelect.value || "--";
  const tf = state.chartTimeframe || state.session?.base_timeframe || "--";
  const strat = els.strategySelect.value || "--";
  const mode = els.strategySelect.value === "sr_quant" ? ` · ${els.modeSelect.value}` : "";
  els.reportDashMeta.textContent = `${symbol} ${tf} · ${strat}${mode}`;

  els.reportDashMetrics.replaceChildren(...REPORT_METRIC_CARDS.map(([label, fn]) => {
    const card = document.createElement("div");
    card.className = "metric";
    let value = "--";
    try { value = fn(metrics); } catch { value = "--"; }
    card.append(textSpan(label), strong(value));
    return card;
  }));

  if (!images.length) {
    const note = emptyNode(result?.report_html === "#mock-report"
      ? "Graficos do relatorio disponiveis apenas com o backend real."
      : "Sem trades fechados — nenhum grafico gerado.");
    els.reportDashCharts.replaceChildren(note);
  } else {
    els.reportDashCharts.replaceChildren(...images.map((image) => {
      const card = document.createElement("div");
      card.className = "report-chart-card";
      const title = document.createElement("h3");
      title.textContent = image.title || image.name;
      const img = document.createElement("img");
      img.loading = "lazy";
      img.alt = image.title || image.name;
      img.src = image.url;
      card.append(title, img);
      return card;
    }));
  }

  const exportable = Boolean(result?.report_html) && result.report_html !== "#mock-report";
  if (els.reportExportBtn) {
    els.reportExportBtn.disabled = !exportable;
    els.reportExportBtn.title = exportable ? "Abrir relatorio para imprimir / salvar como PDF" : "Indisponivel (sem backend real ou sem trades)";
  }
}

function openReportDashboard() {
  if (!els.reportDashboard) return;
  els.reportDashboard.hidden = false;
  document.body.classList.add("report-open");
  els.reportState.textContent = "Inline";
  requestAnimationFrame(() => els.reportDashboard.scrollIntoView({ behavior: "smooth", block: "start" }));
}

function closeReportDashboard() {
  if (!els.reportDashboard) return;
  els.reportDashboard.hidden = true;
  document.body.classList.remove("report-open");
  state.chart?.scheduleResize?.();
}

function exportReportPdf() {
  const url = state.lastReport?.report_html;
  if (!url || url === "#mock-report") {
    setStatus("Exportacao indisponivel (sem relatorio real)");
    return;
  }
  // Open the full HTML report and trigger the browser print dialog → Save as PDF.
  const win = window.open(url, "_blank");
  if (win) {
    win.addEventListener("load", () => {
      try { win.focus(); win.print(); } catch { /* user can print manually */ }
    });
  }
  setStatus("Relatorio aberto em nova aba — use Imprimir → Salvar como PDF");
}

function formatPctValue(value) {
  const n = Number(value);
  if (value == null || !Number.isFinite(n)) return "--";
  return `${n >= 0 ? "+" : ""}${n.toFixed(2)}%`;
}

function formatRatioValue(value) {
  const n = Number(value);
  if (value == null || !Number.isFinite(n)) return "--";
  return n.toFixed(2);
}

function setBusy(isBusy) {
  for (const el of [
    els.newSessionBtn,
    els.finishBtn,
    els.stepBtn,
    els.stepBackBtn,
    els.resetBtn,
    els.seekStartBtn,
    els.seekEndBtn,
    els.cursorInput,
    els.cursorScrubber,
  ]) {
    if (el) el.disabled = Boolean(isBusy);
  }
  if (!isBusy) renderTimeline();
}

function setStatus(message) {
  els.statusLine.textContent = message || "";
}

function emptyNode(text) {
  const node = document.createElement("div");
  node.className = "empty-panel";
  node.textContent = text;
  return node;
}

function textSpan(text) {
  const span = document.createElement("span");
  span.textContent = text;
  return span;
}

function strong(text) {
  const node = document.createElement("strong");
  node.textContent = text;
  return node;
}

function titleRow(left, right, tone) {
  const row = document.createElement("div");
  row.className = "trade-title";
  const a = document.createElement("span");
  a.textContent = left;
  const b = document.createElement("span");
  b.className = tone;
  b.textContent = right;
  row.append(a, b);
  return row;
}

function metaLine(text) {
  const line = document.createElement("div");
  line.className = "trade-meta";
  line.textContent = text;
  return line;
}

function formatMoney(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "--";
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2 }).format(n);
}

function formatSignedMoney(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "--";
  const cls = n >= 0 ? "value-positive" : "value-negative";
  return `${n >= 0 ? "+" : ""}${formatMoney(n)}`.replace("$-", "-$");
}

function formatNumber(value) {
  if (value == null || value === "") return "--";
  const n = Number(value);
  if (!Number.isFinite(n)) return "--";
  return Math.abs(n) >= 100 ? n.toFixed(0) : n.toFixed(2);
}

function formatDateTime(seconds) {
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "UTC",
  }).format(new Date(normalizeTime(seconds) * 1000));
}

class ApiFacade {
  constructor({ onModeChange }) {
    this.real = new RealApi();
    this.mock = new MockApi();
    this.mode = this.shouldUseMockFirst() ? "mock" : "real";
    this.onModeChange = onModeChange;
    if (this.mode === "mock") {
      queueMicrotask(() => this.onModeChange("mock", "modo estatico"));
    }
  }

  async call(method, ...args) {
    if (this.mode === "mock") return this.mock[method](...args);
    try {
      const result = await this.real[method](...args);
      this.onModeChange("real");
      return result;
    } catch (error) {
      this.mode = "mock";
      this.onModeChange("mock", error.message || error);
      return this.mock[method](...args);
    }
  }

  catalog() { return this.call("catalog"); }
  newSession(config) { return this.call("newSession", config); }
  step(payload) { return this.call("step", payload); }
  reset() { return this.call("reset"); }
  seek(payload) { return this.call("seek", payload); }
  async series(payload) {
    if (this.mode === "mock") return this.mock.series(payload);
    return this.real.series(payload).catch(() => null);
  }
  finish() { return this.call("finish"); }
  createZone(payload) { return this.call("createZone", payload); }
  updateZone(id, payload) { return this.call("updateZone", id, payload); }
  deleteZone(id) { return this.call("deleteZone", id); }

  shouldUseMockFirst() {
    const { protocol, search } = window.location;
    return protocol === "file:" || new URLSearchParams(search).has("mock");
  }
}

class RealApi {
  catalog() {
    return this.request("/interactive/catalog");
  }

  newSession(payload) {
    return this.request("/interactive/session/new", { method: "POST", body: payload });
  }

  step(payload) {
    return this.request("/interactive/step", { method: "POST", body: payload });
  }

  reset() {
    return this.request("/interactive/reset", { method: "POST", body: {} });
  }

  seek(payload) {
    return this.request("/interactive/seek", { method: "POST", body: payload || {} });
  }

  series(payload) {
    return this.request("/interactive/series", { method: "POST", body: payload || {} });
  }

  finish() {
    return this.request("/interactive/finish", { method: "POST", body: {} });
  }

  createZone(payload) {
    return this.request("/interactive/zone", { method: "POST", body: payload });
  }

  updateZone(id, payload) {
    return this.request(`/interactive/zone/${encodeURIComponent(id)}`, { method: "PUT", body: payload });
  }

  deleteZone(id) {
    return this.request(`/interactive/zone/${encodeURIComponent(id)}`, { method: "DELETE" });
  }

  async request(path, { method = "GET", body } = {}) {
    const response = await fetch(path, {
      method,
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
    if (!response.ok) {
      const text = await response.text().catch(() => "");
      throw new Error(`HTTP ${response.status} ${path}${text ? `: ${text.slice(0, 90)}` : ""}`);
    }
    return response.json();
  }
}

class MockApi {
  constructor() {
    this.seed = 7;
    this.bars = [];
    this.cursor = 0;
    this.balance = 1000;
    this.openTrades = [];
    this.closedTrades = [];
    this.zones = new Map();
    this.zoneSeq = 1;
    this.tradeSeq = 1;
    this.baseTimeframe = "H1";
    this.lastConfig = {};
  }

  async catalog() {
    return {
      datasets: [
        { symbol: "EURUSD", timeframe: "H1", path: "mock/EURUSD_H1.csv" },
        { symbol: "EURUSD", timeframe: "H4", path: "mock/EURUSD_H4.csv" },
        { symbol: "XAUUSD", timeframe: "H1", path: "mock/XAUUSD_H1.csv" },
        { symbol: "XAUUSD", timeframe: "H4", path: "mock/XAUUSD_H4.csv" },
      ],
      strategies: ["sr_quant", "stub"],
      modes: ["SEM", "COM", "AMBOS"],
    };
  }

  async newSession(config) {
    this.lastConfig = { ...(config || {}) };
    this.seed = 7;
    const symbol = config?.symbol || "EURUSD";
    const timeframe = config?.timeframe || "H1";
    this.baseTimeframe = timeframe;
    this.bars = this.generateBars(720, symbol, timeframe);
    this.cursor = 150;
    this.balance = 1000;
    this.openTrades = [];
    this.closedTrades = [];
    this.zones = new Map();
    this.zoneSeq = 1;
    this.tradeSeq = 1;
    return {
      session_id: "mock-s1",
      symbol,
      timeframe,
      base_timeframe: timeframe,
      zone_timeframes: timeframe === "H1" ? ["H1", "H4"] : [timeframe],
      config,
      strategy: config?.strategy || "sr_quant",
      mode: config?.mode || "SEM",
      total_bars: this.bars.length,
      warmup_bars: 150,
      cursor: this.cursor,
      history: this.bars.slice(0, this.cursor + 1),
      balance: this.balance,
      equity: this.balance,
      indicators: this.indicators(),
      indicator_thresholds: this.indicatorThresholds(),
      indicators_meta: this.indicatorsMeta(),
      tf_indicators: this.tfIndicators(timeframe),
      zones: [],
    };
  }

  async step({ n = 1 } = {}) {
    const appended = [];
    const closedNow = [];
    for (let i = 0; i < n && this.cursor < this.bars.length - 1; i += 1) {
      this.cursor += 1;
      const bar = this.bars[this.cursor];
      appended.push(bar);
      this.maybeOpenTrade(bar);
      closedNow.push(...this.closeExpiredTrades(bar));
      this.updateZoneStates(bar);
    }
    const openTrades = this.openTrades.map((trade) => this.withUnrealized(trade));
    const equity = this.balance + openTrades.reduce((sum, trade) => sum + Number(trade.unrealized_pnl || 0), 0);
    return {
      cursor: this.cursor,
      total_bars: this.bars.length,
      done: this.cursor >= this.bars.length - 1,
      bars: appended,
      indicators: this.indicators(),
      indicator_thresholds: this.indicatorThresholds(),
      indicators_meta: this.indicatorsMeta(),
      tf_indicators: this.tfIndicators(this.baseTimeframe),
      equity,
      balance: this.balance,
      open_trades: openTrades,
      closed_now: closedNow,
      zones: [...this.zones.values()],
    };
  }

  async series({ tf } = {}) {
    const requested = tf || this.baseTimeframe;
    const bars = requested === this.baseTimeframe
      ? this.bars.slice(0, this.cursor + 1)
      : aggregateMockBars(this.bars.slice(0, this.cursor + 1), requested, this.baseTimeframe);
    const out = {
      time: [],
      open: [],
      high: [],
      low: [],
      close: [],
      volume: [],
      rsi: [],
      stoch_k: [],
      uo: [],
      sma60: [],
    };
    bars.forEach((bar, index) => {
      const values = this.indicatorsAt(index, bars);
      out.time.push(bar.time);
      out.open.push(bar.open);
      out.high.push(bar.high);
      out.low.push(bar.low);
      out.close.push(bar.close);
      out.volume.push(bar.volume);
      out.rsi.push(values.rsi);
      out.stoch_k.push(values.stoch_k);
      out.uo.push(values.uo);
      out.sma60.push(values.sma60);
    });
    return out;
  }

  async reset() {
    const config = this.lastConfig || {};
    const zones = new Map(this.zones);
    const zoneSeq = this.zoneSeq;
    const session = await this.newSession(config);
    this.zones = zones;
    this.zoneSeq = zoneSeq;
    return {
      ...session,
      reset: true,
      zones: [...this.zones.values()].filter((zone) => Number(zone.created_at_bar || 0) <= this.cursor),
    };
  }

  async seek({ bar = 0 } = {}) {
    this.cursor = Math.max(0, Math.min(Math.round(Number(bar) || 0), this.bars.length - 1));
    this.openTrades = [];
    return this.snapshot();
  }

  snapshot() {
    const openTrades = this.openTrades.map((trade) => this.withUnrealized(trade));
    const equity = this.balance + openTrades.reduce((sum, trade) => sum + Number(trade.unrealized_pnl || 0), 0);
    return {
      cursor: this.cursor,
      total_bars: this.bars.length,
      done: this.cursor >= this.bars.length - 1,
      bars: [],
      indicators: this.indicators(),
      indicator_thresholds: this.indicatorThresholds(),
      indicators_meta: this.indicatorsMeta(),
      tf_indicators: this.tfIndicators(this.baseTimeframe),
      equity,
      balance: this.balance,
      open_trades: openTrades,
      closed_now: [],
      zones: [...this.zones.values()].filter((zone) => Number(zone.created_at_bar || 0) <= this.cursor),
    };
  }

  async finish() {
    const bar = this.bars[this.cursor];
    for (const trade of [...this.openTrades]) {
      const closed = this.closeTrade(trade, bar, "finish");
      this.closedTrades.push(closed);
    }
    this.openTrades = [];
    const net = this.balance - 1000;
    return {
      report_dir: "reports/mock_interactive_run",
      report_html: "#mock-report",
      metrics: {
        net_profit: net,
        profit_factor: net >= 0 ? 1.42 : 0.82,
        max_drawdown: -42.5,
        trades: this.closedTrades.length,
      },
    };
  }

  async createZone(payload) {
    const low = Math.min(Number(payload.price_low), Number(payload.price_high));
    const high = Math.max(Number(payload.price_low), Number(payload.price_high));
    const zone = {
      id: `z${this.zoneSeq++}`,
      price_low: low,
      price_high: high,
      side: payload.side === "resistance" ? "resistance" : "support",
      timeframe: payload.timeframe || "H1",
      created_at_bar: this.cursor,
      state: "active",
    };
    this.zones.set(zone.id, zone);
    return zone;
  }

  async updateZone(id, payload) {
    const existing = this.zones.get(id);
    if (!existing) throw new Error(`Zona ${id} nao encontrada`);
    const low = Math.min(Number(payload.price_low), Number(payload.price_high));
    const high = Math.max(Number(payload.price_low), Number(payload.price_high));
    const zone = {
      ...existing,
      price_low: low,
      price_high: high,
      side: payload.side === "resistance" ? "resistance" : "support",
      timeframe: payload.timeframe || existing.timeframe || "H1",
    };
    this.zones.set(id, zone);
    return zone;
  }

  async deleteZone(id) {
    this.zones.delete(id);
    return { id, state: "deleted" };
  }

  generateBars(count, symbol = "EURUSD", timeframe = "H1") {
    const bars = [];
    const isMetal = symbol === "XAUUSD";
    const stepSeconds = timeframe === "H4" ? 14400 : 3600;
    let lastClose = isMetal ? 2340 : 1.084;
    const start = Date.UTC(2024, 0, 2, 0, 0, 0) / 1000;
    for (let i = 0; i < count; i += 1) {
      const scale = isMetal ? 1.8 : 0.00042;
      const wave = Math.sin(i / 18) * scale + Math.sin(i / 7) * scale * 0.42;
      const noise = (this.random() - 0.5) * scale;
      const open = lastClose;
      const close = open + wave * 0.22 + noise;
      const wick = scale * (0.42 + this.random() * 0.9);
      const high = Math.max(open, close) + wick;
      const low = Math.min(open, close) - wick * (0.7 + this.random() * 0.6);
      const volume = Math.floor(740 + this.random() * 980);
      bars.push({ time: start + i * stepSeconds, open, high, low, close, volume });
      lastClose = close;
    }
    return bars;
  }

  random() {
    this.seed = (this.seed * 1664525 + 1013904223) >>> 0;
    return this.seed / 4294967296;
  }

  indicators() {
    return this.indicatorsAt(this.cursor, this.bars);
  }

  indicatorsAt(i, bars = this.bars) {
    return {
      rsi: 50 + Math.sin(i / 9) * 22,
      stoch_k: 50 + Math.sin(i / 6) * 38,
      uo: 48 + Math.cos(i / 11) * 26,
      sma60: bars.slice(Math.max(0, i - 59), i + 1)
        .reduce((sum, bar) => sum + bar.close, 0) / Math.min(60, i + 1),
    };
  }

  indicatorThresholds() {
    return {
      rsi: { oversold: 27, overbought: 72 },
      stoch_k: { oversold: 20, overbought: 80 },
      uo: { oversold: 30, overbought: 70 },
    };
  }

  indicatorsMeta() {
    return {
      overlays: ["sma60"],
      panes: [
        { key: "rsi", range: [0, 100], oversold: 27, overbought: 72 },
        { key: "stoch_k", range: [0, 100], oversold: 20, overbought: 80 },
        { key: "uo", range: [0, 100], oversold: 30, overbought: 70 },
      ],
    };
  }

  tfIndicators(baseTimeframe = "H1") {
    const base = this.indicators();
    const h4Ready = this.cursor >= 80;
    const h4 = h4Ready
      ? {
          rsi: 50 + Math.sin(this.cursor / 18) * 18,
          stoch_k: 50 + Math.sin(this.cursor / 12) * 32,
          uo: 48 + Math.cos(this.cursor / 22) * 20,
          sma60: base.sma60,
        }
      : {};
    if (baseTimeframe === "H4") return { H4: h4Ready ? h4 : base };
    return { H1: base, H4: h4 };
  }

  maybeOpenTrade(bar) {
    if (this.openTrades.length >= 2) return;
    if (this.cursor % 47 !== 0 && this.cursor % 71 !== 0) return;
    const direction = this.cursor % 2 === 0 ? "long" : "short";
    const spread = 0.0018;
    const trade = {
      id: this.tradeSeq++,
      direction,
      entry_time: bar.time,
      entry_price: bar.close,
      stop_price: direction === "long" ? bar.close - spread : bar.close + spread,
      take_price: direction === "long" ? bar.close + spread * 1.6 : bar.close - spread * 1.6,
      size: 0.1,
      entry_cursor: this.cursor,
      unrealized_pnl: 0,
    };
    this.openTrades.push(trade);
  }

  closeExpiredTrades(bar) {
    const closed = [];
    const stillOpen = [];
    for (const trade of this.openTrades) {
      const age = this.cursor - trade.entry_cursor;
      const hitLong = trade.direction === "long" && (bar.low <= trade.stop_price || bar.high >= trade.take_price);
      const hitShort = trade.direction === "short" && (bar.high >= trade.stop_price || bar.low <= trade.take_price);
      if (age >= 14 || hitLong || hitShort) {
        const reason = age >= 14 ? "time" : this.exitReason(trade, bar);
        const closedTrade = this.closeTrade(trade, bar, reason);
        closed.push(closedTrade);
        this.closedTrades.push(closedTrade);
      } else {
        stillOpen.push(trade);
      }
    }
    this.openTrades = stillOpen;
    return closed;
  }

  closeTrade(trade, bar, reason) {
    const exitPrice = reason === "tp"
      ? trade.take_price
      : reason === "sl"
        ? trade.stop_price
        : bar.close;
    const pnl = this.pnlFor(trade, exitPrice);
    this.balance += pnl;
    return {
      id: trade.id,
      direction: trade.direction,
      entry_price: trade.entry_price,
      exit_price: exitPrice,
      exit_reason: reason,
      pnl,
      entry_time: trade.entry_time,
      exit_time: bar.time,
    };
  }

  exitReason(trade, bar) {
    if (trade.direction === "long") {
      if (bar.low <= trade.stop_price) return "sl";
      if (bar.high >= trade.take_price) return "tp";
    } else {
      if (bar.high >= trade.stop_price) return "sl";
      if (bar.low <= trade.take_price) return "tp";
    }
    return "exit";
  }

  withUnrealized(trade) {
    const bar = this.bars[this.cursor];
    return { ...trade, unrealized_pnl: this.pnlFor(trade, bar.close) };
  }

  pnlFor(trade, price) {
    const direction = trade.direction === "long" ? 1 : -1;
    return (Number(price) - Number(trade.entry_price)) * direction * 100000 * Number(trade.size || 0.1);
  }

  updateZoneStates(bar) {
    for (const zone of this.zones.values()) {
      if (zone.state !== "active") continue;
      if (zone.side === "support" && bar.close < zone.price_low) zone.state = "broken";
      if (zone.side === "resistance" && bar.close > zone.price_high) zone.state = "broken";
    }
  }
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", bootstrap);
} else {
  bootstrap();
}
