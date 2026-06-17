// ============================================================
// OracleWalk BacktestCore — Replay Cockpit
// Interactive client
// ============================================================

// Live device-pixel-ratio: refreshed on every resize and whenever the window
// moves to a monitor with a different density (external ultrawide, macOS scaled
// modes). A stale value is the #1 cause of a blurry canvas on a second monitor.
let DPR = Math.max(1, window.devicePixelRatio || 1);

const DEFAULT_OVERLAYS = {
  ema9: true,
  ema20: true,
  ema50: true,
  ema200: true,
  sma60: true,
  ml_st_line: true,
  fvg_boxes: true,
};

const state = {
  session: null,
  index: 0,
  playing: false,
  speed: 25,
  windowBars: 360,
  zoom: 1.0,            // multiplier of windowBars (1 = current windowBars)
  panOffset: 0,         // candles offset from "current centered" view
  hover: null,          // { x, y, idx, paneId }
  overlays: { ...DEFAULT_OVERLAYS },
  logFilter: "all",
  tradeFilter: "all",
  symbolFilter: "all",
  reportScope: "account",
  reportSessionOverride: null,
  selectedTradeId: null,
  timer: null,
  progressRatio: 0,
  chartModal: { open: false, chartId: null, reportScope: "account", view: "angle", equity3d: null },
  // pre-computed lookup tables
  eventByIndex: null,
  openTradesByIndex: null,
  activeTradeAtIndex: null,
  replayFrameToCandle: null,
  replayCandleToFrame: null,
};

const els = {};

const COLORS = {
  bgGrid: "#1b2330",
  bgGridStrong: "#222c3a",
  axisText: "#6e7d8f",
  axisStrong: "#b5c0cf",
  candleUp: "#2bd47f",
  candleDown: "#ff5867",
  candleUpFill: "rgba(43, 212, 127, 0.92)",
  candleDownFill: "rgba(255, 88, 103, 0.92)",
  crosshair: "rgba(232, 237, 240, 0.55)",
  crosshairFill: "rgba(74, 214, 230, 0.85)",
  cursorLine: "rgba(74, 214, 230, 0.75)",
  ema9: "#4ad6e6",
  ema20: "#ffb547",
  ema50: "#b78aff",
  ema200: "#8a969d",
  sma60: "#ff79c6",
  mlSt: "#f5f7fb",
  buy: "#2bd47f",
  sell: "#ff5867",
  win: "#ffb547",
  loss: "#ff5867",
  equity: "#4ad6e6",
  balance: "#ffb547",
  drawdown: "rgba(255, 88, 103, 0.18)",
  drawdownLine: "rgba(255, 88, 103, 0.6)",
  volume: "#2a3445",
  volumeUp: "rgba(43, 212, 127, 0.35)",
  volumeDown: "rgba(255, 88, 103, 0.35)",
  initialLine: "rgba(110, 125, 143, 0.55)",
  openTradeLine: "rgba(74, 214, 230, 0.6)",
};

// ============================================================
// Bootstrap
// ============================================================

document.addEventListener("DOMContentLoaded", () => {
  cacheElements();
  wireControls();
  wireKeyboard();
  wireSetupModal();
  wireReports();
  wireChartModal();
  loadSession().then(() => {
    renderInteractiveReports();
    refreshCatalog();
  }).catch((error) => {
    console.error("Falha ao carregar sessão:", error);
    setLoadingText(`Erro ao carregar: ${error.message || error}`);
  });
});

function cacheElements() {
  const ids = [
    "loadingOverlay", "loadingText",
    "loadingTitle", "loadingStageText", "loadingProgress", "loadingProgressFill",
    "loadingPhase", "loadingPct",
    "openSetupBtn", "closeSetupBtn", "cancelSetupBtn", "runSetupBtn",
    "setupModal", "configSelect", "strategySelect", "datasetSelect",
    "assetPicker", "assetSearch", "assetList", "selectedAssetChips", "selectAllMt5Btn", "clearAssetsBtn",
    "replayModeSelect", "startDateInput", "endDateInput",
    "reuseReportToggle", "setupStatus", "qualityBanner",
    "strategyHint", "strategyParamsCount", "strategyParamsGrid",
    "resetStrategyBtn", "resetEngineBtn",
    "engineGroupAccount", "engineGroupRisk", "engineGroupCosts", "engineGroupInstrument",
    "engineGroupExecution", "engineGroupPortfolio",
    "sumAsset", "sumStrategy", "sumReplay", "sumCapital",
    "reportsPane", "reportTabs", "reportsGallery", "reportsCount", "reportsPath",
    "reportsSummary", "reloadReportsBtn", "exportReportBtn", "reportTooltip", "chartHelpPopover",
    "robustnessPane", "runRobustnessBtn", "robustVerdict", "robustMeta", "robustFlags", "robustSummary", "robustGallery",
    "propfirmPane", "runPropfirmBtn", "propfirmVerdict", "propfirmMeta", "propfirmFlags", "propfirmSummary",
    "pfPresetSelect", "pfAccount", "pfTarget", "pfDaily", "pfTotal", "pfMinDays", "pfMaxDays",
    "pfTrailingEnabled", "pfConsist", "pfWeekend", "pfReqStop",
    "pfEnabled",
    "chartModalBackdrop", "chartModalTitle", "chartModalMeta", "chartModalGlCanvas", "chartModalCanvas", "chartModalTooltip", "chartModalHint", "chartModalViewset", "chartModalViewFrontBtn", "chartModalViewAngleBtn", "chartModalViewTopBtn", "chartModalViewResetBtn", "chartModalCloseBtn", "chartModalFullscreenBtn",
    "title", "eaStatusPill", "eaStatusLabel",
    "metaBroker", "metaCandles", "metaTrades",
    "balanceNow", "balanceSub", "equityNow", "openPnlNow",
    "profitNow", "profitFinal", "ddNow", "maxDd",
    "tradesNow", "tradesSub", "winRate", "streak",
    "profitFactor", "expectancy", "marginNow", "leverageNow",
    "sharpeNow", "sortinoNow", "benchmarkReturn", "benchmarkLabel",
    "clock", "ohlcO", "ohlcH", "ohlcL", "ohlcC", "ohlcCWrap",
    "ohlcSpread", "ohlcVol",
    "portfolioScope", "scopeMode", "scopeTitle", "scopeMeta", "scopeSymbols",
    "priceCanvas", "equityCanvas", "priceTooltip", "equityTooltip",
    "priceWrap", "equityWrap",
    "candleIndex", "openTrades", "lastEvent",
    "eaCurrentState", "eaActionCell", "openPnlCell", "openPnlCellValue",
    "positionBadge", "progressLabel", "progressFill",
    "activityLog", "tradeRows", "tradesSection",
    "stepBack100", "stepBack10", "stepBack1", "stepForward1", "stepForward10", "stepForward100",
    "prevTrade", "nextTrade",
    "playBtn", "playIcon", "playLabel",
    "seekTrack", "seekProgress", "seekThumb",
    "seekCurrent", "seekTotal", "seekDate",
    "windowBars", "windowBarsValue",
    "speedPresets", "zoomIn", "zoomOut", "zoomReset",
    "legend",
  ];
  ids.forEach((id) => {
    els[id] = document.getElementById(id);
  });
}

async function loadSession() {
  startLoadingSequence({ title: "Carregando sessão", estimateMs: 2200 });
  const response = await fetch("/api/session");
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const session = await response.json();
  state.session = session;
  state.reportScope = "account";
  precomputeLookups();
  state.index = Math.max(0, Math.min(state.windowBars, replayMaxIndex()));
  renderStatic();
  resizeCanvases();
  render();
  window.addEventListener("resize", debouncedResize);
  watchDevicePixelRatio();
  finishLoadingSequence();
  setTimeout(hideLoading, 250);
}

const debouncedResize = debounce(() => {
  resizeCanvases();
  render();
  drawReportCanvases();
  if (state.chartModal.open) drawChartModalCanvas();
}, 80);

function precomputeLookups() {
  const { candles, events, trades } = state.session;
  const n = candles.length;
  resetOverlayState();
  state.progressRatio = 0;
  const eventByIndex = new Array(n);
  events.forEach((event) => {
    const arr = eventByIndex[event.index] || [];
    arr.push(event);
    eventByIndex[event.index] = arr;
  });
  // Build "active trades at index" array (count) — using counting via deltas
  const deltas = new Int32Array(n + 1);
  trades.forEach((t) => {
    const a = Math.max(0, Math.min(t.entryIndex, n - 1));
    const b = Math.max(0, Math.min(t.exitIndex, n - 1));
    deltas[a] += 1;
    deltas[b] -= 1;
  });
  const openCounts = new Int32Array(n);
  let running = 0;
  for (let i = 0; i < n; i += 1) {
    running += deltas[i];
    openCounts[i] = running < 0 ? 0 : running;
  }
  // Active trade pointer (last opened, still active)
  const activeTradeAtIndex = new Array(n);
  const sorted = [...trades].sort((a, b) => a.entryIndex - b.entryIndex);
  let pointer = 0;
  const stack = [];
  for (let i = 0; i < n; i += 1) {
    while (pointer < sorted.length && sorted[pointer].entryIndex <= i) {
      stack.push(sorted[pointer]);
      pointer += 1;
    }
    while (stack.length && stack[0].exitIndex < i) {
      stack.shift();
    }
    activeTradeAtIndex[i] = stack.length ? stack[stack.length - 1] : null;
  }
  state.eventByIndex = eventByIndex;
  state.openTradesByIndex = openCounts;
  state.activeTradeAtIndex = activeTradeAtIndex;

  const frames = replayFrames();
  state.replayFrameToCandle = frames.length ? frames.map((frame) => frame[0]) : null;
  if (frames.length) {
    const candleToFrame = new Int32Array(n);
    candleToFrame.fill(-1);
    frames.forEach((frame, frameIndex) => {
      candleToFrame[frame[0]] = frameIndex;
    });
    state.replayCandleToFrame = candleToFrame;
  } else {
    state.replayCandleToFrame = null;
  }
}

function resetOverlayState() {
  state.overlays = { ...DEFAULT_OVERLAYS };
}

function replayFrames() {
  return state.session?.replay?.frames || [];
}

function isTickReplay() {
  return state.session?.replay?.mode === "tick" && replayFrames().length > 0;
}

function replayMaxIndex() {
  return isTickReplay()
    ? replayFrames().length - 1
    : (state.session?.candles?.length || 1) - 1;
}

function currentCandleIndex() {
  if (!state.session) return 0;
  if (!isTickReplay()) return clamp(state.index, 0, state.session.candles.length - 1);
  const frame = replayFrames()[clamp(state.index, 0, replayFrames().length - 1)];
  return clamp(frame ? frame[0] : 0, 0, state.session.candles.length - 1);
}

function currentReplayCandle() {
  if (!state.session) return null;
  if (!isTickReplay()) return state.session.candles[currentCandleIndex()];
  const frame = replayFrames()[clamp(state.index, 0, replayFrames().length - 1)];
  if (!frame) return state.session.candles[currentCandleIndex()];
  return [frame[1], frame[2], frame[3], frame[4], frame[5], frame[6], frame[7]];
}

function candleForDraw(index) {
  if (isTickReplay() && index === currentCandleIndex()) return currentReplayCandle();
  return state.session.candles[index];
}

function replayIndexForCandle(candleIndex) {
  if (!isTickReplay()) return candleIndex;
  const target = clamp(candleIndex, 0, state.session.candles.length - 1);
  for (let i = target; i >= 0; i -= 1) {
    const frame = state.replayCandleToFrame?.[i];
    if (frame !== undefined && frame >= 0) return frame;
  }
  return 0;
}

function setLoadingText(text) {
  if (els.loadingText) els.loadingText.textContent = text;
  if (els.loadingStageText) els.loadingStageText.textContent = text;
}

function hideLoading() {
  stopLoadingSequence();
  if (els.loadingOverlay) els.loadingOverlay.classList.add("hidden");
}

const LOADING_STAGES = [
  { text: "Carregando dataset",       phase: "DADOS",         pct: 12 },
  { text: "Preparando indicadores",   phase: "INDICADORES",   pct: 28 },
  { text: "Executando estratégia",    phase: "ESTRATÉGIA",    pct: 48 },
  { text: "Simulando trades",         phase: "EXECUÇÃO",      pct: 68 },
  { text: "Calculando métricas",      phase: "ANÁLISE",       pct: 85 },
  { text: "Preparando visualização",  phase: "RENDER",        pct: 95 },
];

const loadingState = {
  active: false,
  stageIdx: 0,
  pct: 0,
  visualPct: 0,
  timer: null,
  startTime: 0,
  estimateMs: 4000,
  message: null,   // when set (e.g. from a background job), overrides the stage text
};

function startLoadingSequence(opts) {
  stopLoadingSequence();
  if (els.loadingOverlay) els.loadingOverlay.classList.remove("hidden");
  if (els.loadingTitle) els.loadingTitle.textContent = (opts && opts.title) || "Executando backtest";
  loadingState.active = true;
  loadingState.stageIdx = 0;
  loadingState.pct = 0;
  loadingState.visualPct = 0;
  loadingState.startTime = performance.now();
  loadingState.estimateMs = Math.max(1200, (opts && opts.estimateMs) || 4000);
  loadingState.message = null;
  setLoadingPct(0, { reset: true });
  applyStage(0);
  loadingState.timer = setInterval(tickLoading, 80);
}

function applyStage(idx) {
  const stage = LOADING_STAGES[Math.min(idx, LOADING_STAGES.length - 1)];
  if (!stage) return;
  if (els.loadingStageText) els.loadingStageText.textContent = stage.text;
  if (els.loadingPhase) els.loadingPhase.textContent = stage.phase;
}

function tickLoading() {
  if (!loadingState.active) return;
  const elapsed = performance.now() - loadingState.startTime;
  const r = elapsed / loadingState.estimateMs;
  // Saturating curve: moves quickly toward the estimate, then KEEPS creeping
  // (asymptotic to ~99%, never plateaus, never reaches 100% until the response
  // actually arrives). No more "stuck at 95%": the bar is always honestly moving
  // while the work runs, however long it takes.
  const pctTarget = 99 * (1 - Math.exp(-1.5 * r));
  loadingState.pct += (pctTarget - loadingState.pct) * 0.12;
  setLoadingPct(loadingState.pct);
  // Advance stage when crossing thresholds
  const nextIdx = LOADING_STAGES.findIndex((s) => loadingState.pct < s.pct);
  const idx = nextIdx === -1 ? LOADING_STAGES.length - 1 : Math.max(0, nextIdx - 1);
  if (idx !== loadingState.stageIdx) {
    loadingState.stageIdx = idx;
    applyStage(idx);
  }
  // Honest signal that it's alive: show elapsed seconds, and flag heavy/long runs
  // (e.g. a tick load reading GBs) so the user never thinks it froze.
  if (els.loadingStageText) {
    const stage = LOADING_STAGES[Math.min(loadingState.stageIdx, LOADING_STAGES.length - 1)];
    // A background job reports the real stage ("Carregando ticks…", "Rodando
    // backtest…"); prefer it over the local animation text when present.
    const base = loadingState.message || (stage ? stage.text : "Processando");
    const secs = Math.floor(elapsed / 1000);
    const heavy = r > 1.8 ? " — ainda processando (operação pesada, pode levar minutos)" : "";
    els.loadingStageText.textContent = secs >= 2 ? `${base}${heavy} · ${secs}s` : base;
  }
}

function setLoadingPct(pct, opts = {}) {
  const clamped = Math.max(0, Math.min(100, pct));
  const visual = opts.reset ? clamped : Math.max(clamped, loadingState.visualPct);
  loadingState.visualPct = visual;
  if (els.loadingProgressFill) {
    els.loadingProgressFill.style.transform = `scaleX(${visual / 100})`;
  }
  if (els.loadingPct) {
    els.loadingPct.textContent = `${visual.toFixed(0)}%`;
  }
  if (els.loadingProgress) {
    els.loadingProgress.classList.remove("indeterminate");
  }
}

function finishLoadingSequence() {
  if (!loadingState.active) return;
  if (loadingState.timer) {
    clearInterval(loadingState.timer);
    loadingState.timer = null;
  }
  applyStage(LOADING_STAGES.length - 1);
  setLoadingPct(100);
  loadingState.active = false;
  if (els.loadingStageText) els.loadingStageText.textContent = "Pronto";
  if (els.loadingPhase) els.loadingPhase.textContent = "OK";
}

function stopLoadingSequence() {
  loadingState.active = false;
  if (loadingState.timer) {
    clearInterval(loadingState.timer);
    loadingState.timer = null;
  }
}

// ============================================================
// Wiring: controls + keyboard + interactions
// ============================================================

function wireControls() {
  // Playback
  els.playBtn.addEventListener("click", togglePlay);
  els.stepBack1.addEventListener("click", () => move(-1));
  els.stepForward1.addEventListener("click", () => move(1));
  els.stepBack10.addEventListener("click", () => move(-10));
  els.stepForward10.addEventListener("click", () => move(10));
  els.stepBack100.addEventListener("click", () => move(-100));
  els.stepForward100.addEventListener("click", () => move(100));
  els.prevTrade.addEventListener("click", () => jumpToTrade(-1));
  els.nextTrade.addEventListener("click", () => jumpToTrade(1));

  // Seek
  attachSeekControl();

  // Speed presets
  els.speedPresets.querySelectorAll("button").forEach((btn) => {
    btn.addEventListener("click", () => {
      const value = Number(btn.dataset.speed);
      state.speed = value;
      els.speedPresets.querySelectorAll("button").forEach((b) => b.classList.toggle("active", b === btn));
    });
  });

  // Window bars
  els.windowBars.addEventListener("input", () => {
    state.windowBars = Number(els.windowBars.value);
    els.windowBarsValue.textContent = String(state.windowBars);
    render();
  });
  els.windowBarsValue.textContent = String(state.windowBars);

  // Zoom buttons
  els.zoomIn.addEventListener("click", () => applyZoom(0.8));
  els.zoomOut.addEventListener("click", () => applyZoom(1.25));
  els.zoomReset.addEventListener("click", () => {
    state.zoom = 1.0;
    state.panOffset = 0;
    render();
  });

  // Chart interactions
  attachChartInteractions(els.priceCanvas, els.priceWrap, els.priceTooltip, "price");
  attachChartInteractions(els.equityCanvas, els.equityWrap, els.equityTooltip, "equity");

  // Legend overlay toggles
  els.legend.querySelectorAll(".chip[data-overlay]").forEach((chip) => {
    chip.addEventListener("click", () => {
      const key = chip.dataset.overlay;
      if (chip.classList.contains("unavailable")) return;
      state.overlays[key] = !state.overlays[key];
      chip.classList.toggle("disabled", !state.overlays[key]);
      render();
    });
  });

  // Filters
  document.querySelectorAll("[data-log-filter]").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.logFilter = btn.dataset.logFilter;
      document.querySelectorAll("[data-log-filter]").forEach((b) => b.classList.toggle("active", b === btn));
      renderActivityLog();
    });
  });
  document.querySelectorAll("[data-trade-filter]").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.tradeFilter = btn.dataset.tradeFilter;
      document.querySelectorAll("[data-trade-filter]").forEach((b) => b.classList.toggle("active", b === btn));
      renderTradesTable();
    });
  });

  if (els.scopeSymbols) {
    els.scopeSymbols.addEventListener("click", (event) => {
      const button = event.target.closest("[data-symbol-filter]");
      if (!button) return;
      state.symbolFilter = button.dataset.symbolFilter || "all";
      renderPortfolioScope();
      renderActivityLog();
      renderTradesTable();
    });
  }

  // Click delegated for trade rows
  els.tradeRows.addEventListener("click", (event) => {
    const row = event.target.closest("tr[data-trade]");
    if (!row) return;
    const id = Number(row.dataset.trade);
    selectTradeById(id);
  });
  els.activityLog.addEventListener("click", (event) => {
    const row = event.target.closest(".log-entry[data-index]");
    if (!row) return;
    const idx = Number(row.dataset.index);
    setIndex(idx);
  });
}

function wireKeyboard() {
  document.addEventListener("keydown", (event) => {
    if (event.target.tagName === "INPUT" || event.target.tagName === "TEXTAREA") return;
    switch (event.key) {
      case " ":
      case "Spacebar":
        event.preventDefault();
        togglePlay();
        break;
      case "ArrowLeft":
        event.preventDefault();
        move(event.shiftKey ? -100 : event.ctrlKey || event.metaKey ? -10 : -1);
        break;
      case "ArrowRight":
        event.preventDefault();
        move(event.shiftKey ? 100 : event.ctrlKey || event.metaKey ? 10 : 1);
        break;
      case "j":
      case "J":
        jumpToTrade(-1);
        break;
      case "k":
      case "K":
        jumpToTrade(1);
        break;
      case "Home":
        setIndex(0);
        break;
      case "End":
        setIndex(state.session.candles.length - 1);
        break;
      case "+":
      case "=":
        applyZoom(0.8);
        break;
      case "-":
      case "_":
        applyZoom(1.25);
        break;
      case "0":
        state.zoom = 1.0;
        state.panOffset = 0;
        render();
        break;
    }
  });
}

function attachSeekControl() {
  let dragging = false;
  const track = els.seekTrack;
  const update = (event) => {
    const rect = track.getBoundingClientRect();
    const ratio = clamp((event.clientX - rect.left) / rect.width, 0, 1);
    const max = state.session.candles.length - 1;
    setIndex(Math.round(ratio * max));
  };
  track.addEventListener("mousedown", (event) => {
    dragging = true;
    update(event);
  });
  window.addEventListener("mousemove", (event) => {
    if (dragging) update(event);
  });
  window.addEventListener("mouseup", () => {
    dragging = false;
  });
}

function attachChartInteractions(canvas, wrap, tooltipEl, paneId) {
  let dragging = false;
  let dragStartX = 0;
  let dragStartOffset = 0;

  canvas.addEventListener("mousemove", (event) => {
    const rect = canvas.getBoundingClientRect();
    state.hover = {
      x: event.clientX - rect.left,
      y: event.clientY - rect.top,
      paneId,
    };
    if (dragging) {
      const dx = event.clientX - dragStartX;
      // pan offset in candles (1 candle per ~candleW px)
      const { visibleStart, visibleEnd } = computeVisibleRange();
      const candleW = (rect.width - 60 - 68) / Math.max(visibleEnd - visibleStart, 1);
      state.panOffset = dragStartOffset + Math.round(dx / candleW);
      render();
    } else {
      render();
    }
  });

  canvas.addEventListener("mouseleave", () => {
    state.hover = null;
    tooltipEl.classList.remove("visible");
    render();
  });

  canvas.addEventListener("mousedown", (event) => {
    if (event.button !== 0) return;
    dragging = true;
    dragStartX = event.clientX;
    dragStartOffset = state.panOffset;
    canvas.style.cursor = "grabbing";
  });

  const stopDrag = () => {
    dragging = false;
    canvas.style.cursor = "crosshair";
  };
  window.addEventListener("mouseup", stopDrag);

  canvas.addEventListener("dblclick", () => {
    state.panOffset = 0;
    state.zoom = 1.0;
    render();
  });

  // Wheel = zoom (price pane) or seek (equity pane)
  canvas.addEventListener("wheel", (event) => {
    event.preventDefault();
    if (paneId === "price") {
      const factor = event.deltaY > 0 ? 1.1 : 0.9;
      applyZoom(factor);
    } else {
      const delta = event.deltaY > 0 ? 5 : -5;
      move(delta);
    }
  }, { passive: false });

  canvas.addEventListener("click", (event) => {
    if (paneId !== "equity") return;
    const rect = canvas.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const ratio = clamp((x - 54) / (rect.width - 54 - 68), 0, 1);
    const { visibleStart, visibleEnd } = computeVisibleRange();
    setIndex(Math.round(visibleStart + ratio * (visibleEnd - visibleStart)));
  });
}

// ============================================================
// State updates
// ============================================================

function applyZoom(factor) {
  const next = clamp(state.zoom * factor, 0.2, 4.0);
  state.zoom = next;
  render();
}

function move(delta) {
  if (!state.session) return;
  const max = replayMaxIndex();
  setIndex(clamp(state.index + delta, 0, max));
}

function setIndex(idx) {
  if (!state.session) return;
  const max = replayMaxIndex();
  state.index = clamp(idx, 0, max);
  if (!state.playing) {
    state.progressRatio = max > 0 ? state.index / max : 0;
  }
  render();
}

function togglePlay() {
  state.playing = !state.playing;
  els.playBtn.classList.toggle("playing", state.playing);
  els.playLabel.textContent = state.playing ? "Pause" : "Play";
  els.playIcon.innerHTML = state.playing
    ? '<rect x="4" y="3" width="3" height="10"/><rect x="9" y="3" width="3" height="10"/>'
    : '<path d="M4 3 L13 8 L4 13 Z"/>';
  if (state.playing) {
    state.timer = setInterval(() => {
      const max = replayMaxIndex();
      const next = state.index + Math.max(1, Math.round(state.speed));
      if (next >= max) {
        setIndex(max);
        togglePlay();
        return;
      }
      setIndex(next);
    }, 60);
  } else if (state.timer) {
    clearInterval(state.timer);
    state.timer = null;
  }
}

function jumpToTrade(direction) {
  const { trades } = state.session;
  if (!trades.length) return;
  const candleIndex = currentCandleIndex();
  const target = direction > 0
    ? trades.find((t) => t.entryIndex > candleIndex)
    : [...trades].reverse().find((t) => t.entryIndex < candleIndex);
  if (target) {
    selectTradeById(target.id);
  }
}

function selectTradeById(id) {
  const trade = state.session.trades.find((t) => t.id === id);
  if (!trade) return;
  state.selectedTradeId = id;
  // Jump to a few bars after exit so the user sees the whole trade in context
  const target = Math.min(
    state.session.candles.length - 1,
    trade.exitIndex + Math.max(5, Math.floor((trade.exitIndex - trade.entryIndex) * 0.5))
  );
  setIndex(replayIndexForCandle(target));
}

// ============================================================
// Rendering
// ============================================================

function render() {
  if (!state.session) return;
  drawPrice();
  drawEquity();
  renderNow();
  renderSeek();
  renderActivityLog();
  renderTradesTable();
}

function renderStatic() {
  const { metadata, metrics } = state.session;
  state.symbolFilter = availableSymbols().includes(state.symbolFilter) ? state.symbolFilter : "all";
  document.title = `${metadata.symbol} ${metadata.timeframe} · ${metadata.strategy} — OracleWalk`;
  els.title.textContent = metadata.portfolio
    ? `Portfolio · ${metadata.timeframe} · ${metadata.strategy}`
    : `${metadata.symbol} · ${metadata.timeframe} · ${metadata.strategy}`;
  els.metaBroker.textContent = metadata.broker || "—";
  els.metaCandles.textContent = isTickReplay()
    ? `${metadata.candles.toLocaleString("pt-BR")} · ${metadata.replay_frames.toLocaleString("pt-BR")} ticks`
    : metadata.candles.toLocaleString("pt-BR");
  els.metaTrades.textContent = metadata.trades.toLocaleString("pt-BR");
  els.balanceSub.textContent = `Final ${money(metrics.final_balance)}`;
  els.maxDd.textContent = `Max ${pct(metrics.max_drawdown_pct)}`;
  els.profitFinal.textContent = `Total ${money(metrics.net_profit)} · ${pct(metrics.net_return_pct)}`;
  els.profitFactor.textContent = (metrics.profit_factor || 0).toFixed(2);
  els.expectancy.textContent = `Exp ${money(metrics.expectancy || 0)}`;
  els.leverageNow.textContent = `Alav. 1:${metadata.leverage}`;
  els.tradesSub.textContent = `${(metrics.wins || 0).toLocaleString("pt-BR")} W · ${(metrics.losses || 0).toLocaleString("pt-BR")} L`;
  els.winRate.textContent = pct(metrics.win_rate);
  els.streak.textContent = `Payoff ${(metrics.payoff_ratio || 0).toFixed(2)}`;
  const rm = state.session.risk_metrics || {};
  const bm = state.session.benchmark || {};
  if (els.sharpeNow) els.sharpeNow.textContent = metrics.sharpe_per_trade != null ? metrics.sharpe_per_trade.toFixed(3) : "—";
  if (els.sortinoNow) els.sortinoNow.textContent = rm.sortino != null ? `Sortino ${rm.sortino.toFixed(3)}` : "Sortino —";
  if (els.benchmarkReturn) els.benchmarkReturn.textContent = bm.net_return_pct != null ? `${bm.net_return_pct >= 0 ? "+" : ""}${bm.net_return_pct.toFixed(2)}%` : "—";
  if (els.benchmarkLabel) els.benchmarkLabel.textContent = `Strat ${pct(metrics.net_return_pct)} vs B&H`;
  syncOverlayLegend();
  renderPortfolioScope();
}

function syncOverlayLegend() {
  if (!els.legend || !state.session) return;
  els.legend.querySelectorAll(".chip[data-overlay]").forEach((chip) => {
    const key = chip.dataset.overlay;
    const available = overlayAvailable(key);
    chip.classList.toggle("unavailable", !available);
    chip.classList.toggle("disabled", !available || !state.overlays[key]);
    chip.setAttribute("aria-disabled", available ? "false" : "true");
    chip.title = available ? "" : "Indicador indisponível nesta sessão";
    if (!available) state.overlays[key] = false;
  });
}

function overlayAvailable(key) {
  if (key === "fvg_boxes") return Boolean(state.session?.boxes?.length);
  const series = state.session?.overlays?.[key];
  return Array.isArray(series) && series.some((value) => value !== null && Number.isFinite(Number(value)));
}

function availableSymbols() {
  const metadataSymbols = state.session?.metadata?.symbols || [];
  const tradeSymbols = (state.session?.trades || []).map((trade) => trade.symbol).filter(Boolean);
  return Array.from(new Set([...metadataSymbols, ...tradeSymbols].filter(Boolean))).sort();
}

function renderPortfolioScope() {
  if (!els.portfolioScope || !state.session) return;
  const { metadata, trades } = state.session;
  const symbols = availableSymbols();
  const isPortfolio = Boolean(metadata.portfolio || symbols.length > 1);
  els.portfolioScope.classList.toggle("hidden", !isPortfolio);
  if (!isPortfolio) return;

  const activeSymbol = state.symbolFilter === "all" ? null : state.symbolFilter;
  const scopedTrades = activeSymbol ? trades.filter((trade) => trade.symbol === activeSymbol) : trades;
  const net = scopedTrades.reduce((sum, trade) => sum + (Number(trade.pnl) || 0), 0);
  const wins = scopedTrades.filter((trade) => Number(trade.pnl) > 0).length;
  const losses = scopedTrades.filter((trade) => Number(trade.pnl) < 0).length;

  els.scopeMode.textContent = "Portfolio";
  els.scopeTitle.textContent = activeSymbol ? activeSymbol : "Conta consolidada";
  els.scopeMeta.textContent = `${scopedTrades.length.toLocaleString("pt-BR")} trades · ${wins}W/${losses}L · ${signedMoney(net)}`;

  const allActive = state.symbolFilter === "all";
  const buttons = [
    `<button class="scope-chip ${allActive ? "active" : ""}" type="button" data-symbol-filter="all">Conta</button>`,
    ...symbols.map((symbol) => {
      const count = trades.filter((trade) => trade.symbol === symbol).length;
      const active = state.symbolFilter === symbol;
      return `<button class="scope-chip ${active ? "active" : ""}" type="button" data-symbol-filter="${escapeHtml(symbol)}">${escapeHtml(symbol)}<span>${count}</span></button>`;
    }),
  ];
  els.scopeSymbols.innerHTML = buttons.join("");
}

function renderNow() {
  const { candles, equity, metrics, trades, metadata } = state.session;
  const i = currentCandleIndex();
  const c = currentReplayCandle();
  const e = equity[i];
  if (!c || !e) return;

  const up = c[4] >= c[1];

  els.clock.textContent = fmtTime(c[0]);
  els.ohlcO.textContent = price(c[1]);
  els.ohlcH.textContent = price(c[2]);
  els.ohlcL.textContent = price(c[3]);
  els.ohlcC.textContent = price(c[4]);
  els.ohlcCWrap.classList.toggle("up", up);
  els.ohlcCWrap.classList.toggle("down", !up);
  els.ohlcSpread.textContent = `${formatSpread(c[6])}p`;
  els.ohlcVol.textContent = compact(c[5]);

  // KPIs
  const balance = e[1];
  const equityNow = e[2];
  const openPnl = e[3];
  const openCount = e[4];
  const ddNow = e[5];
  const marginNow = e[6];
  const initial = metadata.initial_capital;
  const profit = balance - initial;

  els.balanceNow.textContent = money(balance);
  els.balanceNow.classList.toggle("value-pos", balance > initial);
  els.balanceNow.classList.toggle("value-neg", balance < initial);

  els.equityNow.textContent = money(equityNow);
  els.equityNow.classList.toggle("value-pos", openPnl > 0);
  els.equityNow.classList.toggle("value-neg", openPnl < 0);
  els.openPnlNow.textContent = `Aberto ${signedMoney(openPnl)}`;
  els.openPnlNow.classList.toggle("delta-pos", openPnl > 0);
  els.openPnlNow.classList.toggle("delta-neg", openPnl < 0);

  els.profitNow.textContent = signedMoney(profit);
  els.profitNow.classList.toggle("value-pos", profit > 0);
  els.profitNow.classList.toggle("value-neg", profit < 0);

  els.ddNow.textContent = pct(ddNow);
  els.ddNow.classList.toggle("value-neg", ddNow < -0.0001);

  const closedTrades = trades.filter((t) => t.exitIndex <= i);
  const wins = closedTrades.filter((t) => t.pnl > 0).length;
  const losses = closedTrades.length - wins;
  const winRateNow = closedTrades.length ? (wins / closedTrades.length) * 100 : 0;
  els.tradesNow.textContent = `${closedTrades.length.toLocaleString("pt-BR")} / ${metrics.total_trades.toLocaleString("pt-BR")}`;
  els.tradesSub.textContent = `${wins.toLocaleString("pt-BR")} W · ${losses.toLocaleString("pt-BR")} L`;
  els.winRate.textContent = pct(winRateNow);

  // Profit factor up to index
  let grossWin = 0;
  let grossLoss = 0;
  closedTrades.forEach((t) => {
    if (t.pnl > 0) grossWin += t.pnl;
    else if (t.pnl < 0) grossLoss += -t.pnl;
  });
  const pf = grossLoss > 0 ? grossWin / grossLoss : grossWin > 0 ? 999 : 0;
  els.profitFactor.textContent = pf >= 999 ? "∞" : pf.toFixed(2);
  els.profitFactor.classList.toggle("value-pos", pf >= 1.5);
  els.profitFactor.classList.toggle("value-neg", pf > 0 && pf < 1);

  const expectancy = closedTrades.length ? closedTrades.reduce((s, t) => s + t.pnl, 0) / closedTrades.length : 0;
  els.expectancy.textContent = `Exp ${signedMoney(expectancy)}`;

  // Streak
  const streak = computeStreak(closedTrades);
  els.streak.textContent = streak === 0 ? "—" : streak > 0 ? `🔥 ${streak} W` : `❄ ${Math.abs(streak)} L`;

  els.marginNow.textContent = money(marginNow);

  // Side panel — EA execution state
  els.candleIndex.textContent = isTickReplay()
    ? `${state.index.toLocaleString("pt-BR")} ticks · candle ${i.toLocaleString("pt-BR")} / ${(candles.length - 1).toLocaleString("pt-BR")}`
    : `${i.toLocaleString("pt-BR")} / ${(candles.length - 1).toLocaleString("pt-BR")}`;
  els.openTrades.textContent = String(openCount);
  els.openPnlCellValue.textContent = signedMoney(openPnl);
  els.openPnlCell.classList.toggle("profit", openPnl > 0);
  els.openPnlCell.classList.toggle("loss", openPnl < 0);

  // EA state pill
  const activeTrade = state.activeTradeAtIndex[i];
  const stateEl = els.eaStatusPill;
  stateEl.classList.remove("status-idle", "status-long", "status-short");
  if (activeTrade) {
    const barsHeld = Math.max(0, i - activeTrade.entryIndex);
    if (activeTrade.direction === "long") {
      stateEl.classList.add("status-long");
      els.eaStatusLabel.textContent = `LONG ${formatLot(activeTrade.size)}`;
      els.eaCurrentState.textContent = `LONG @ ${price(activeTrade.entryPrice)} · ${barsHeld} bars`;
    } else {
      stateEl.classList.add("status-short");
      els.eaStatusLabel.textContent = `SHORT ${formatLot(activeTrade.size)}`;
      els.eaCurrentState.textContent = `SHORT @ ${price(activeTrade.entryPrice)} · ${barsHeld} bars`;
    }
  } else {
    stateEl.classList.add("status-idle");
    els.eaStatusLabel.textContent = "Scanning";
    els.eaCurrentState.textContent = "Aguardando setup…";
  }

  // Last event
  let lastEvent = null;
  for (let k = i; k >= 0 && k > i - 200; k -= 1) {
    const ev = state.eventByIndex[k];
    if (ev && ev.length) {
      lastEvent = ev[ev.length - 1];
      break;
    }
  }
  if (lastEvent) {
    const tag = lastEvent.type === "entry"
      ? `${lastEvent.side === "long" ? "BUY" : "SELL"} #${lastEvent.tradeId}`
      : `EXIT #${lastEvent.tradeId} · ${(lastEvent.result || "").toUpperCase()}`;
    els.lastEvent.textContent = tag;
  } else {
    els.lastEvent.textContent = "—";
  }

  // Position badge
  if (openCount > 0) {
    els.positionBadge.innerHTML = `<span style="color:var(--primary); font-family:var(--font-mono); font-size:11px;">${openCount} aberta(s)</span>`;
  } else {
    els.positionBadge.innerHTML = "";
  }

  // Progress
  const rawProgressRatio = isTickReplay()
    ? state.index / Math.max(replayMaxIndex(), 1)
    : i / Math.max(candles.length - 1, 1);
  const progressRatio = state.playing
    ? Math.max(rawProgressRatio, state.progressRatio || 0)
    : rawProgressRatio;
  state.progressRatio = progressRatio;
  const pctProgress = progressRatio * 100;
  els.progressLabel.textContent = `${pctProgress.toFixed(1)}% · ${closedTrades.length} de ${metrics.total_trades} trades`;
  els.progressFill.style.transform = `scaleX(${pctProgress / 100})`;
}

function renderSeek() {
  const { candles } = state.session;
  const max = replayMaxIndex();
  const ratio = state.index / Math.max(max, 1);
  els.seekProgress.style.transform = `scaleX(${ratio})`;
  els.seekThumb.style.left = `${ratio * 100}%`;
  els.seekCurrent.textContent = state.index.toLocaleString("pt-BR");
  els.seekTotal.textContent = max.toLocaleString("pt-BR");
  els.seekDate.textContent = fmtTime((currentReplayCandle() || candles[currentCandleIndex()])[0]);
}

function computeStreak(closedTrades) {
  if (!closedTrades.length) return 0;
  let streak = 0;
  const lastSign = Math.sign(closedTrades[closedTrades.length - 1].pnl);
  if (lastSign === 0) return 0;
  for (let i = closedTrades.length - 1; i >= 0; i -= 1) {
    if (Math.sign(closedTrades[i].pnl) === lastSign) streak += 1;
    else break;
  }
  return lastSign > 0 ? streak : -streak;
}

// ============================================================
// Canvas: price pane
// ============================================================

function computeVisibleRange() {
  const { candles } = state.session;
  const bars = Math.max(20, Math.round(state.windowBars * state.zoom));
  const center = currentCandleIndex() + state.panOffset;
  const end = clamp(center + Math.floor(bars * 0.18), 0, candles.length - 1);
  const start = clamp(end - bars, 0, candles.length - 1);
  return { visibleStart: start, visibleEnd: end, barsVisible: end - start + 1 };
}

function drawPrice() {
  const canvas = els.priceCanvas;
  const ctx = canvas.getContext("2d");
  const { candles, overlays, events, trades } = state.session;
  const boxes = state.session.boxes || [];
  const currentIdx = currentCandleIndex();
  const currentCandle = currentReplayCandle();
  const w = canvas.width;
  const h = canvas.height;
  ctx.clearRect(0, 0, w, h);

  const { visibleStart: start, visibleEnd: end } = computeVisibleRange();
  const drawEnd = Math.min(end, currentIdx);
  const visible = [];
  for (let i = start; i <= drawEnd; i += 1) visible.push(candleForDraw(i));
  const padPx = { left: 54, right: 68, top: 18, bottom: 60 };
  const pad = scalePad(padPx);
  const plotW = w - pad.left - pad.right;
  const plotH = h - pad.top - pad.bottom;
  const volH = 36 * DPR;
  const priceH = plotH - volH - 8 * DPR;

  // Price range (only candles + visible overlays)
  let min = Infinity;
  let max = -Infinity;
  visible.forEach((c) => {
    min = Math.min(min, c[3]);
    max = Math.max(max, c[2]);
  });
  Object.entries(overlays).forEach(([key, series]) => {
    if (!state.overlays[key]) return;
    for (let i = start; i <= drawEnd; i += 1) {
      const v = series[i];
      if (v !== null && v !== undefined) {
        if (v < min) min = v;
        if (v > max) max = v;
      }
    }
  });

  // Include active trade SL/TP in range so they're visible
  const activeTrade = state.activeTradeAtIndex[currentIdx];
  if (activeTrade) {
    [activeTrade.entryPrice].forEach((v) => {
      if (v) {
        min = Math.min(min, v);
        max = Math.max(max, v);
      }
    });
  }

  const span = Math.max(max - min, 0.00001);
  min -= span * 0.08;
  max += span * 0.08;

  // Volume range
  let volMax = 0;
  for (let i = start; i <= drawEnd; i += 1) {
    const c = candleForDraw(i);
    if (c[5] > volMax) volMax = c[5];
  }
  volMax = Math.max(volMax, 1);

  const xAt = (idx) => pad.left + ((idx - start) / Math.max(end - start, 1)) * plotW;
  const yPrice = (value) => pad.top + ((max - value) / (max - min)) * priceH;
  const yVol = (value) => pad.top + priceH + 8 * DPR + (volH - (value / volMax) * volH);

  // Background separators
  ctx.fillStyle = "rgba(74, 214, 230, 0.015)";
  ctx.fillRect(pad.left, pad.top, plotW, priceH);

  // Grid (price)
  drawHorizontalGrid(ctx, pad, plotW, priceH, min, max, yPrice, w);

  // Time axis
  drawTimeAxis(ctx, candles, start, end, pad, plotW, h, xAt);

  // Active trade visualization (open position): entry line + shaded zone + entry vertical
  if (activeTrade && activeTrade.entryIndex >= start && activeTrade.entryIndex <= end) {
    const entryX = xAt(activeTrade.entryIndex);
    const entryY = yPrice(activeTrade.entryPrice);
    const currentX = xAt(currentIdx);
    const currentClose = currentCandle[4];
    const currentY = yPrice(currentClose);
    const isLong = activeTrade.direction === "long";
    const winning = isLong ? currentClose > activeTrade.entryPrice : currentClose < activeTrade.entryPrice;
    const zoneColor = winning ? "rgba(43, 212, 127, 0.08)" : "rgba(255, 88, 103, 0.08)";
    // Shaded zone between entry and current price
    ctx.fillStyle = zoneColor;
    ctx.fillRect(
      entryX,
      Math.min(entryY, currentY),
      Math.max(currentX - entryX, 1),
      Math.abs(currentY - entryY)
    );
    // Entry vertical line
    ctx.strokeStyle = "rgba(74, 214, 230, 0.4)";
    ctx.lineWidth = 1 * DPR;
    ctx.setLineDash([3 * DPR, 3 * DPR]);
    ctx.beginPath();
    ctx.moveTo(entryX, pad.top);
    ctx.lineTo(entryX, pad.top + priceH);
    ctx.stroke();
    ctx.setLineDash([]);
    // Entry horizontal line
    drawHorizontalLine(ctx, pad.left, w - pad.right, entryY, COLORS.openTradeLine, 1.2, [4 * DPR, 4 * DPR]);
    ctx.fillStyle = COLORS.openTradeLine;
    ctx.font = `600 ${10 * DPR}px ${FONT_MONO}`;
    ctx.textAlign = "left";
    ctx.textBaseline = "bottom";
    ctx.fillText(`${isLong ? "▲" : "▼"} ENTRY ${price(activeTrade.entryPrice)}`, entryX + 4 * DPR, entryY - 4 * DPR);
  }

  // Selected trade halo
  const selectedTrade = state.selectedTradeId !== null
    ? state.session.trades.find((t) => t.id === state.selectedTradeId)
    : null;
  if (selectedTrade && selectedTrade.entryIndex <= end && selectedTrade.exitIndex >= start) {
    const sx1 = xAt(clamp(selectedTrade.entryIndex, start, end));
    const sx2 = xAt(clamp(selectedTrade.exitIndex, start, end));
    const winColor = selectedTrade.pnl >= 0 ? "rgba(43, 212, 127, 0.10)" : "rgba(255, 88, 103, 0.10)";
    ctx.fillStyle = winColor;
    ctx.fillRect(sx1, pad.top, Math.max(sx2 - sx1, 2 * DPR), priceH);
    const borderColor = selectedTrade.pnl >= 0 ? "rgba(43, 212, 127, 0.6)" : "rgba(255, 88, 103, 0.6)";
    ctx.strokeStyle = borderColor;
    ctx.lineWidth = 1.5 * DPR;
    ctx.strokeRect(sx1, pad.top, Math.max(sx2 - sx1, 2 * DPR), priceH);
  }

  // Volume bars
  const candleW = clamp((plotW / Math.max(visible.length, 1)) * 0.65, 1, 14 * DPR);
  for (let i = start; i <= drawEnd; i += 1) {
    const c = candleForDraw(i);
    const x = xAt(i);
    const up = c[4] >= c[1];
    ctx.fillStyle = up ? COLORS.volumeUp : COLORS.volumeDown;
    const vy = yVol(c[5]);
    const vh = pad.top + priceH + 8 * DPR + volH - vy;
    ctx.fillRect(x - candleW / 2, vy, candleW, Math.max(vh, 1));
  }

  // FVG boxes (price inefficiencies) — drawn behind the candles. Perf-optimized:
  // filter to the visible window once, skip per-box stroke/dashes when dense (they
  // become invisible clutter and the per-box setLineDash is a frame killer), and
  // batch the 50% midlines into a single path.
  if (state.overlays.fvg_boxes && boxes.length) {
    const visBoxes = [];
    for (const b of boxes) {
      if (b.endIndex < start || b.startIndex > drawEnd) continue;
      visBoxes.push(b);
    }
    const dense = visBoxes.length > 220;
    for (const b of visBoxes) {
      const x0 = xAt(Math.max(b.startIndex, start));
      const x1 = xAt(Math.min(b.endIndex, drawEnd));
      const yTop = yPrice(b.high);
      const yBot = yPrice(b.low);
      const buy = b.side === "buy";
      const wBox = Math.max(x1 - x0, 1.5 * DPR);
      const hBox = Math.max(yBot - yTop, 1 * DPR);
      ctx.fillStyle = buy ? "rgba(43, 212, 127, 0.12)" : "rgba(255, 88, 103, 0.12)";
      ctx.fillRect(x0, yTop, wBox, hBox);
      if (!dense) {
        ctx.strokeStyle = buy ? "rgba(43, 212, 127, 0.55)" : "rgba(255, 88, 103, 0.55)";
        ctx.lineWidth = 1 * DPR;
        ctx.strokeRect(x0, yTop, wBox, hBox);
      }
    }
    if (!dense) {
      ctx.setLineDash([2 * DPR, 3 * DPR]);
      ctx.strokeStyle = "rgba(207, 214, 255, 0.35)";
      ctx.lineWidth = 1 * DPR;
      ctx.beginPath();
      for (const b of visBoxes) {
        const x0 = xAt(Math.max(b.startIndex, start));
        const x1 = xAt(Math.min(b.endIndex, drawEnd));
        const yMid = yPrice((b.high + b.low) / 2);
        ctx.moveTo(x0, yMid);
        ctx.lineTo(Math.max(x1, x0 + 1.5 * DPR), yMid);
      }
      ctx.stroke();
      ctx.setLineDash([]);
    }
  }

  // Candles
  ctx.lineWidth = Math.max(1, DPR);
  for (let i = start; i <= drawEnd; i += 1) {
    const c = candleForDraw(i);
    const x = xAt(i);
    const open = yPrice(c[1]);
    const high = yPrice(c[2]);
    const low = yPrice(c[3]);
    const close = yPrice(c[4]);
    const up = c[4] >= c[1];
    ctx.strokeStyle = up ? COLORS.candleUp : COLORS.candleDown;
    ctx.beginPath();
    ctx.moveTo(x, high);
    ctx.lineTo(x, low);
    ctx.stroke();
    const bodyTop = Math.min(open, close);
    const bodyH = Math.max(Math.abs(close - open), DPR);
    ctx.fillStyle = up ? COLORS.candleUpFill : COLORS.candleDownFill;
    ctx.fillRect(x - candleW / 2, bodyTop, candleW, bodyH);
  }

  // Overlays
  if (state.overlays.ema9) drawOverlay(ctx, overlays.ema9, start, drawEnd, xAt, yPrice, COLORS.ema9);
  if (state.overlays.ema20) drawOverlay(ctx, overlays.ema20, start, drawEnd, xAt, yPrice, COLORS.ema20);
  if (state.overlays.ema50) drawOverlay(ctx, overlays.ema50, start, drawEnd, xAt, yPrice, COLORS.ema50);
  if (state.overlays.ema200) drawOverlay(ctx, overlays.ema200, start, drawEnd, xAt, yPrice, COLORS.ema200);
  if (state.overlays.sma60 && overlays.sma60) drawOverlay(ctx, overlays.sma60, start, drawEnd, xAt, yPrice, COLORS.sma60);
  if (state.overlays.ml_st_line && overlays.ml_st_line) drawOverlay(ctx, overlays.ml_st_line, start, drawEnd, xAt, yPrice, COLORS.mlSt);

  // Trade lines (entry → exit for closed trades visible) + markers
  ctx.globalAlpha = 0.35;
  trades.forEach((trade) => {
    if (trade.exitIndex < start || trade.entryIndex > end) return;
    if (trade.exitIndex > currentIdx) return;
    const x1 = xAt(clamp(trade.entryIndex, start, end));
    const x2 = xAt(clamp(trade.exitIndex, start, end));
    const y1 = yPrice(trade.entryPrice);
    const y2 = yPrice(trade.exitPrice);
    ctx.strokeStyle = trade.pnl >= 0 ? COLORS.candleUp : COLORS.candleDown;
    ctx.lineWidth = 1.2 * DPR;
    ctx.setLineDash([2 * DPR, 3 * DPR]);
    ctx.beginPath();
    ctx.moveTo(x1, y1);
    ctx.lineTo(x2, y2);
    ctx.stroke();
    ctx.setLineDash([]);
  });
  ctx.globalAlpha = 1;

  // Entry/exit markers — only those <= state.index
  events.forEach((event) => {
    if (event.index < start || event.index > end) return;
    if (event.index > currentIdx) return;
    const x = xAt(event.index);
    const y = yPrice(event.price);
    const isEntry = event.type === "entry";
    let color;
    if (isEntry) {
      color = event.side === "long" ? COLORS.candleUp : COLORS.candleDown;
    } else {
      color = event.result === "win" ? COLORS.win : COLORS.loss;
    }
    drawMarker(ctx, x, y, isEntry ? "up" : "down", color, event.side, isEntry);
  });

  // Current candle line (vertical)
  const currentX = xAt(currentIdx);
  ctx.strokeStyle = COLORS.cursorLine;
  ctx.lineWidth = 1 * DPR;
  ctx.beginPath();
  ctx.moveTo(currentX, pad.top);
  ctx.lineTo(currentX, h - pad.bottom);
  ctx.stroke();

  // Current price label (right axis)
  const currentClose = currentCandle[4];
  const currentY = yPrice(currentClose);
  const currentColor = activeTrade
    ? (activeTrade.direction === "long" ? COLORS.candleUp : COLORS.candleDown)
    : (currentClose >= currentCandle[1] ? COLORS.candleUp : COLORS.candleDown);
  drawPriceLabel(ctx, w - pad.right, currentY, price(currentClose), currentColor, w);

  // Hover crosshair
  if (state.hover && state.hover.paneId === "price") {
    drawCrosshair(ctx, canvas, pad, plotW, priceH, start, end, drawEnd, candles, xAt, yPrice, min, max);
  } else {
    hideTooltip(els.priceTooltip);
  }
}

function drawCrosshair(ctx, canvas, pad, plotW, priceH, start, end, drawEnd, candles, xAt, yPrice, min, max) {
  const rect = canvas.getBoundingClientRect();
  // Map CSS pixels to canvas pixels with the REAL current ratio, not the global
  // DPR captured at load (which goes stale on browser zoom / monitor changes).
  const sx = rect.width ? canvas.width / rect.width : DPR;
  const sy = rect.height ? canvas.height / rect.height : DPR;
  const hoverX = state.hover.x * sx;
  const hoverY = state.hover.y * sy;
  if (hoverY < pad.top || hoverY > pad.top + priceH + 8 * DPR + 36 * DPR) {
    hideTooltip(els.priceTooltip);
    return;
  }
  // Map the mouse x using the SAME [start, end] scale as xAt (so the line snaps to
  // the candle under the cursor), then clamp to the replayed range (drawEnd).
  const cap = Math.min(drawEnd, candles.length - 1);
  const idx = clamp(Math.round(start + ((hoverX - pad.left) / plotW) * (end - start)), start, cap);
  if (idx < start) {
    hideTooltip(els.priceTooltip);
    return;
  }
  const x = xAt(idx);
  ctx.strokeStyle = COLORS.crosshair;
  ctx.lineWidth = 1 * DPR;
  ctx.setLineDash([2 * DPR, 4 * DPR]);
  ctx.beginPath();
  ctx.moveTo(x, pad.top);
  ctx.lineTo(x, pad.top + priceH);
  ctx.stroke();
  // Horizontal at mouse Y
  if (hoverY >= pad.top && hoverY <= pad.top + priceH) {
    ctx.beginPath();
    ctx.moveTo(pad.left, hoverY);
    ctx.lineTo(pad.left + plotW, hoverY);
    ctx.stroke();
    // Right-axis price label
    const value = max - ((hoverY - pad.top) / priceH) * (max - min);
    drawPriceLabel(ctx, canvas.width - pad.right, hoverY, price(value), COLORS.crosshairFill, canvas.width);
  }
  ctx.setLineDash([]);

  // Tooltip
  const c = candles[idx];
  const event = state.eventByIndex[idx];
  const tradeInfo = event && event.length ? eventSummary(event[event.length - 1]) : "";
  const up = c[4] >= c[1];
  const html = `
    <div class="tooltip-row"><span class="label">Time</span><span class="value">${fmtTime(c[0])}</span></div>
    <div class="tooltip-separator"></div>
    <div class="tooltip-row"><span class="label">Open</span><span class="value">${price(c[1])}</span></div>
    <div class="tooltip-row"><span class="label">High</span><span class="value">${price(c[2])}</span></div>
    <div class="tooltip-row"><span class="label">Low</span><span class="value">${price(c[3])}</span></div>
    <div class="tooltip-row"><span class="label">Close</span><span class="value ${up ? "up" : "down"}">${price(c[4])}</span></div>
    <div class="tooltip-row"><span class="label">Volume</span><span class="value">${compact(c[5])}</span></div>
    <div class="tooltip-row"><span class="label">Spread</span><span class="value">${formatSpread(c[6])}p</span></div>
    ${tradeInfo ? `<div class="tooltip-separator"></div><div class="tooltip-trade-info">${tradeInfo}</div>` : ""}
  `;
  showTooltip(els.priceTooltip, html, state.hover.x, state.hover.y, rect);
}

function eventSummary(event) {
  if (event.type === "entry") {
    return `⊕ Entry #${event.tradeId} · ${event.side.toUpperCase()} @ ${price(event.price)}`;
  }
  return `⊖ Exit #${event.tradeId} · ${(event.result || "").toUpperCase()} · ${signedMoney(event.pnl)}`;
}

function drawPriceLabel(ctx, x, y, text, color, canvasW) {
  ctx.fillStyle = color;
  const padX = 4 * DPR;
  const padY = 3 * DPR;
  ctx.font = `600 ${10 * DPR}px ${FONT_MONO}`;
  const tw = ctx.measureText(text).width;
  const h = 16 * DPR;
  const left = Math.min(x + 2 * DPR, canvasW - tw - padX * 2 - 2);
  ctx.fillRect(left, y - h / 2, tw + padX * 2, h);
  ctx.fillStyle = "#04080c";
  ctx.textBaseline = "middle";
  ctx.textAlign = "left";
  ctx.fillText(text, left + padX, y);
}

function drawHorizontalLine(ctx, x1, x2, y, color, lineW, dash) {
  ctx.strokeStyle = color;
  ctx.lineWidth = lineW * DPR;
  if (dash) ctx.setLineDash(dash);
  ctx.beginPath();
  ctx.moveTo(x1, y);
  ctx.lineTo(x2, y);
  ctx.stroke();
  ctx.setLineDash([]);
}

function drawHorizontalGrid(ctx, pad, plotW, plotH, min, max, yAt, canvasW) {
  ctx.strokeStyle = COLORS.bgGrid;
  ctx.lineWidth = 1 * DPR;
  ctx.font = `${10 * DPR}px ${FONT_MONO}`;
  ctx.fillStyle = COLORS.axisText;
  ctx.textBaseline = "middle";
  ctx.textAlign = "left";
  const steps = 6;
  for (let i = 0; i <= steps; i += 1) {
    const y = pad.top + (plotH / steps) * i;
    const value = max - ((max - min) / steps) * i;
    ctx.beginPath();
    ctx.moveTo(pad.left, y);
    ctx.lineTo(pad.left + plotW, y);
    ctx.stroke();
    ctx.fillText(price(value), pad.left + plotW + 8 * DPR, y);
  }
}

function drawTimeAxis(ctx, candles, start, end, pad, plotW, h, xAt) {
  const range = end - start;
  if (range <= 0) return;
  const step = Math.max(1, Math.round(range / 8));
  ctx.fillStyle = COLORS.axisText;
  ctx.font = `${10 * DPR}px ${FONT_MONO}`;
  ctx.textBaseline = "top";
  ctx.textAlign = "center";
  for (let i = start; i <= end; i += step) {
    const x = xAt(i);
    ctx.fillText(fmtTimeShort(candles[i][0]), x, h - pad.bottom + 6 * DPR);
  }
}

function drawOverlay(ctx, series, start, end, xAt, yAt, color) {
  if (!series) return;
  ctx.strokeStyle = color;
  ctx.lineWidth = 1.5 * DPR;
  ctx.beginPath();
  let active = false;
  for (let i = start; i <= end; i += 1) {
    const value = series[i];
    if (value === null || value === undefined) {
      active = false;
      continue;
    }
    const x = xAt(i);
    const y = yAt(value);
    if (!active) {
      ctx.moveTo(x, y);
      active = true;
    } else {
      ctx.lineTo(x, y);
    }
  }
  ctx.stroke();
}

function drawMarker(ctx, x, y, dir, color, side, isEntry) {
  const s = 5 * DPR;
  ctx.fillStyle = color;
  ctx.strokeStyle = "rgba(7, 9, 12, 0.95)";
  ctx.lineWidth = 1.2 * DPR;
  ctx.beginPath();
  if (isEntry) {
    if (side === "long") {
      // Upward triangle below price
      ctx.moveTo(x, y + s * 1.6);
      ctx.lineTo(x - s, y + s * 3.2);
      ctx.lineTo(x + s, y + s * 3.2);
    } else {
      ctx.moveTo(x, y - s * 1.6);
      ctx.lineTo(x - s, y - s * 3.2);
      ctx.lineTo(x + s, y - s * 3.2);
    }
  } else {
    // Diamond at exit price
    ctx.moveTo(x, y - s);
    ctx.lineTo(x + s, y);
    ctx.lineTo(x, y + s);
    ctx.lineTo(x - s, y);
  }
  ctx.closePath();
  ctx.fill();
  ctx.stroke();
}

// ============================================================
// Canvas: equity pane
// ============================================================

function drawEquity() {
  const canvas = els.equityCanvas;
  const ctx = canvas.getContext("2d");
  const { equity, metadata } = state.session;
  const w = canvas.width;
  const h = canvas.height;
  ctx.clearRect(0, 0, w, h);

  // Equity chart is independent of the candle viewport: it always renders
  // from index 0 to the current playback index, growing as trades happen.
  const start = 0;
  const end = Math.max(0, Math.min(currentCandleIndex(), equity.length - 1));

  const padPx = { left: 54, right: 68, top: 12, bottom: 22 };
  const pad = scalePad(padPx);
  const plotW = w - pad.left - pad.right;
  const plotH = h - pad.top - pad.bottom;

  let min = Infinity;
  let max = -Infinity;
  for (let i = start; i <= end; i += 1) {
    const e = equity[i];
    if (e[1] < min) min = e[1];
    if (e[2] < min) min = e[2];
    if (e[1] > max) max = e[1];
    if (e[2] > max) max = e[2];
  }
  const initial = metadata.initial_capital;
  if (initial < min) min = initial;
  if (initial > max) max = initial;
  const span = Math.max(max - min, 1);
  min -= span * 0.1;
  max += span * 0.1;

  // X axis: always spans the whole "elapsed" window. When the user is at the
  // start of the replay, the line starts at the left edge and the rest is empty.
  const denom = Math.max(end - start, 1);
  const xAt = (idx) => pad.left + ((idx - start) / denom) * plotW;
  const yAt = (value) => pad.top + ((max - value) / (max - min)) * plotH;

  drawHorizontalGrid(ctx, pad, plotW, plotH, min, max, yAt, w);

  // Initial capital reference line
  drawHorizontalLine(ctx, pad.left, pad.left + plotW, yAt(initial), COLORS.initialLine, 1, [3 * DPR, 4 * DPR]);
  ctx.fillStyle = COLORS.axisText;
  ctx.font = `${10 * DPR}px ${FONT_MONO}`;
  ctx.textAlign = "left";
  ctx.textBaseline = "bottom";
  ctx.fillText(`Initial ${money(initial)}`, pad.left + 6 * DPR, yAt(initial) - 2 * DPR);

  // Drawdown area: fill between running peak and equity in red
  if (end > start) {
    ctx.beginPath();
    ctx.moveTo(xAt(start), yAt(equity[start][2]));
    let peak = equity[start][2];
    for (let i = start; i <= end; i += 1) {
      if (equity[i][2] > peak) peak = equity[i][2];
      ctx.lineTo(xAt(i), yAt(peak));
    }
    for (let i = end; i >= start; i -= 1) {
      ctx.lineTo(xAt(i), yAt(equity[i][2]));
    }
    ctx.closePath();
    ctx.fillStyle = COLORS.drawdown;
    ctx.fill();
  }

  drawLine(ctx, equity, start, end, xAt, (r) => yAt(r[1]), COLORS.balance, 1.5);
  drawLine(ctx, equity, start, end, xAt, (r) => yAt(r[2]), COLORS.equity, 1.8);

  // Trade-exit markers (only the ones already closed at the current index).
  state.session.trades.forEach((trade) => {
    if (trade.exitIndex > end) return;
    const x = xAt(trade.exitIndex);
    const y = yAt(equity[trade.exitIndex][2]);
    ctx.fillStyle = trade.pnl >= 0 ? COLORS.candleUp : COLORS.candleDown;
    ctx.beginPath();
    ctx.arc(x, y, 2 * DPR, 0, Math.PI * 2);
    ctx.fill();
  });

  // Current value label at the right edge of the drawn curve.
  const currentEquity = equity[end][2];
  drawPriceLabel(ctx, w - pad.right, yAt(currentEquity), money(currentEquity), COLORS.equity, w);

  // Hover tooltip
  if (state.hover && state.hover.paneId === "equity") {
    const rect = canvas.getBoundingClientRect();
    const sx = rect.width ? canvas.width / rect.width : DPR;
    const hoverX = state.hover.x * sx;
    const idx = clamp(Math.round(start + ((hoverX - pad.left) / plotW) * (end - start)), start, end);
    const e = equity[idx];
    if (e) {
      const x = xAt(idx);
      ctx.strokeStyle = COLORS.crosshair;
      ctx.setLineDash([2 * DPR, 4 * DPR]);
      ctx.beginPath();
      ctx.moveTo(x, pad.top);
      ctx.lineTo(x, pad.top + plotH);
      ctx.stroke();
      ctx.setLineDash([]);
      const html = `
        <div class="tooltip-row"><span class="label">Time</span><span class="value">${fmtTime(e[0])}</span></div>
        <div class="tooltip-separator"></div>
        <div class="tooltip-row"><span class="label">Balance</span><span class="value">${money(e[1])}</span></div>
        <div class="tooltip-row"><span class="label">Equity</span><span class="value">${money(e[2])}</span></div>
        <div class="tooltip-row"><span class="label">Open P/L</span><span class="value ${e[3] >= 0 ? "up" : "down"}">${signedMoney(e[3])}</span></div>
        <div class="tooltip-row"><span class="label">Open</span><span class="value">${e[4]}</span></div>
        <div class="tooltip-row"><span class="label">DD</span><span class="value down">${pct(e[5])}</span></div>
      `;
      showTooltip(els.equityTooltip, html, state.hover.x, state.hover.y, rect);
    }
  } else {
    hideTooltip(els.equityTooltip);
  }
}

function drawLine(ctx, rows, start, end, xAt, yOf, color, width) {
  ctx.strokeStyle = color;
  ctx.lineWidth = (width || 1.6) * DPR;
  ctx.beginPath();
  for (let i = start; i <= end; i += 1) {
    const x = xAt(i);
    const y = yOf(rows[i]);
    if (i === start) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }
  ctx.stroke();
}

// ============================================================
// Side panel: activity log + trades table
// ============================================================

function renderActivityLog() {
  const { events, trades } = state.session;
  const tradesById = new Map();
  trades.forEach((t) => tradesById.set(t.id, t));
  const i = currentCandleIndex();
  // Show last 50 events <= i, optionally filtered
  let visible = [];
  for (let k = events.length - 1; k >= 0 && visible.length < 100; k -= 1) {
    const e = events[k];
    if (e.index > i) continue;
    if (state.symbolFilter !== "all" && e.symbol !== state.symbolFilter) continue;
    if (state.logFilter === "wins" && (e.type !== "exit" || e.result !== "win")) continue;
    if (state.logFilter === "losses" && (e.type !== "exit" || e.result !== "loss")) continue;
    visible.push(e);
  }
  visible.reverse();
  visible = visible.slice(-50);

  if (!visible.length) {
    els.activityLog.innerHTML = '<div class="log-empty">Aguardando eventos…</div>';
    return;
  }

  const html = visible.map((e) => {
    const c = state.session.candles[e.index];
    const time = fmtTimeShort(c[0]);
    let cls = "log-entry";
    let msg = "";
    let priceLabel = price(e.price);
    if (e.type === "entry") {
      cls += e.side === "long" ? " entry-long" : " entry-short";
      const symbolTag = e.symbol ? ` <span class="symbol-mini">${escapeHtml(e.symbol)}</span>` : "";
      msg = `${e.side === "long" ? "BUY" : "SELL"} <span style="color:var(--muted)">#${e.tradeId}</span>${symbolTag}`;
    } else {
      cls += e.result === "win" ? " exit-win" : " exit-loss";
      const trade = tradesById.get(e.tradeId);
      const pnlText = trade ? signedMoney(trade.pnl) : signedMoney(e.pnl || 0);
      const pnlSign = (e.pnl || 0) >= 0 ? "pos" : "neg";
      const symbolTag = e.symbol ? ` <span class="symbol-mini">${escapeHtml(e.symbol)}</span>` : "";
      msg = `EXIT <span style="color:var(--muted)">#${e.tradeId}</span>${symbolTag} · ${(e.result || "").toUpperCase()} <span class="pnl-mini ${pnlSign}">${pnlText}</span>`;
      if (trade && trade.reason) {
        msg += ` <span style="color:var(--muted-2); font-size:9px; letter-spacing:0.08em">${trade.reason.toUpperCase()}</span>`;
      }
    }
    return `<div class="${cls}" data-index="${e.index}"><span class="time">${time}</span><span class="msg">${msg}</span><span class="price">${priceLabel}</span></div>`;
  }).join("");
  els.activityLog.innerHTML = html;
  els.activityLog.scrollTop = els.activityLog.scrollHeight;
}

function renderTradesTable() {
  const { trades } = state.session;
  const i = currentCandleIndex();
  let visible = trades.filter((t) => t.exitIndex <= i || t.id === state.selectedTradeId);
  if (state.symbolFilter !== "all") visible = visible.filter((t) => t.symbol === state.symbolFilter);
  if (state.tradeFilter === "long") visible = visible.filter((t) => t.direction === "long");
  else if (state.tradeFilter === "short") visible = visible.filter((t) => t.direction === "short");
  visible = visible.slice(-200).reverse();

  if (!visible.length) {
    els.tradeRows.innerHTML = '<tr><td colspan="6" style="text-align:center; color:var(--muted); padding:20px 12px;">Nenhum trade ainda.</td></tr>';
    return;
  }

  const html = visible.map((t) => {
    const isActive = state.selectedTradeId === t.id;
    const pnlCls = t.pnl >= 0 ? "pos" : "neg";
    const side = t.direction === "long" ? "long" : "short";
    const sideLabel = t.direction === "long" ? "BUY" : "SELL";
    return `<tr data-trade="${t.id}" class="${isActive ? "active" : ""}">
      <td>#${t.id}</td>
      <td><span class="badge ${side}">${sideLabel}</span>${t.symbol ? `<span class="trade-symbol">${escapeHtml(t.symbol)}</span>` : ""}</td>
      <td>${price(t.entryPrice)}</td>
      <td>${price(t.exitPrice)}</td>
      <td class="pnl ${pnlCls}">${signedMoney(t.pnl)}</td>
      <td class="reason">${(t.reason || "").toLowerCase()}</td>
    </tr>`;
  }).join("");
  els.tradeRows.innerHTML = html;
}

// ============================================================
// Tooltip helpers
// ============================================================

function showTooltip(tooltipEl, html, mouseX, mouseY, rect) {
  tooltipEl.innerHTML = html;
  tooltipEl.classList.add("visible");
  // Position: prefer right of cursor, flip if no room
  const ttw = tooltipEl.offsetWidth || 240;
  const tth = tooltipEl.offsetHeight || 100;
  let left = mouseX + 16;
  let top = mouseY + 16;
  if (left + ttw > rect.width - 8) left = mouseX - ttw - 16;
  if (top + tth > rect.height - 8) top = mouseY - tth - 16;
  if (left < 8) left = 8;
  if (top < 8) top = 8;
  tooltipEl.style.left = `${left}px`;
  tooltipEl.style.top = `${top}px`;
}

function hideTooltip(tooltipEl) {
  tooltipEl.classList.remove("visible");
}

function setCanvasVisible(canvas, visible) {
  if (!canvas) return;
  canvas.classList.toggle("hidden", !visible);
}

function hideElement(element) {
  if (!element) return;
  element.classList.add("hidden");
}

// ============================================================
// Canvas sizing + helpers
// ============================================================

function resizeCanvases() {
  // Re-read the CURRENT monitor's density so the backing store matches the display.
  DPR = Math.max(1, window.devicePixelRatio || 1);
  [els.priceCanvas, els.equityCanvas].forEach((canvas) => {
    const rect = canvas.getBoundingClientRect();
    canvas.width = Math.max(1, Math.round(rect.width * DPR));
    canvas.height = Math.max(1, Math.round(rect.height * DPR));
  });
}

// Moving a window between monitors of different density does NOT fire `resize`,
// but it DOES change devicePixelRatio — re-arm a matchMedia listener to catch it.
function watchDevicePixelRatio() {
  if (!window.matchMedia) return;
  const mq = window.matchMedia(`(resolution: ${window.devicePixelRatio}dppx)`);
  const onChange = () => {
    resizeCanvases();
    render();
    drawReportCanvases();
    if (state.chartModal.open) drawChartModalCanvas();
    watchDevicePixelRatio();
  };
  mq.addEventListener("change", onChange, { once: true });
}

function scalePad(pad) {
  return {
    left: pad.left * DPR,
    right: pad.right * DPR,
    top: pad.top * DPR,
    bottom: pad.bottom * DPR,
  };
}

const FONT_MONO = "'JetBrains Mono', ui-monospace, SF Mono, monospace";

// ============================================================
// Format helpers
// ============================================================

function fmtTime(seconds) {
  return new Date(seconds * 1000).toLocaleString("pt-BR", {
    year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit",
  });
}

function fmtTimeShort(seconds) {
  const d = new Date(seconds * 1000);
  const now = state.session ? new Date(state.session.candles[state.session.candles.length - 1][0] * 1000) : d;
  const sameDay = d.toDateString() === now.toDateString();
  if (sameDay) {
    return d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
  }
  return d.toLocaleDateString("pt-BR", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function money(value) {
  return Number(value || 0).toLocaleString("pt-BR", {
    style: "currency", currency: "USD", maximumFractionDigits: 2,
  });
}

function signedMoney(value) {
  const num = Number(value || 0);
  const formatted = Math.abs(num).toLocaleString("pt-BR", {
    style: "currency", currency: "USD", maximumFractionDigits: 2,
  });
  if (num > 0) return `+${formatted}`;
  if (num < 0) return `-${formatted}`;
  return formatted;
}

function pct(value) {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${Number(value).toFixed(2)}%`;
}

function price(value) {
  return Number(value || 0).toFixed(5);
}

function formatLot(value) {
  const num = Number(value || 0);
  if (num === 0) return "0";
  if (num < 0.01) return num.toFixed(4);
  if (num < 1) return num.toFixed(2);
  if (num < 10) return num.toFixed(2);
  return num.toFixed(1);
}

function formatSpread(value) {
  const num = Number(value || 0);
  if (num === 0) return "0";
  if (num < 0.01) return (num * 1e5).toFixed(1);
  return num.toFixed(num < 10 ? 1 : 0);
}

function compact(value) {
  const num = Number(value || 0);
  const abs = Math.abs(num);
  if (abs >= 1_000_000) return `${(num / 1_000_000).toFixed(1)}M`;
  if (abs >= 1_000) return `${(num / 1_000).toFixed(1)}K`;
  if (abs >= 10) return num.toFixed(0);
  return num.toFixed(2);
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function shallowEqual(a, b) {
  if (a === b) return true;
  if (a === null || a === undefined) return b === null || b === undefined || b === "";
  if (b === null || b === undefined) return a === null || a === undefined || a === "";
  if (typeof a === "number" && typeof b === "number") return Math.abs(a - b) < 1e-9;
  return String(a) === String(b);
}

// ============================================================
// Setup modal + catalog
// ============================================================

const catalogState = {
  configs: [],
  strategies: [],
  csvs: [],
  brokerPackages: [],
  engineFields: [],
  current: { config_path: null, broker_package: null, output_dir: null },
};

const ENGINE_GROUP_ELEMENTS = {
  account: "engineGroupAccount",
  risk: "engineGroupRisk",
  execution: "engineGroupExecution",
  costs: "engineGroupCosts",
  instrument: "engineGroupInstrument",
  portfolio: "engineGroupPortfolio",
};

const PACKAGE_OWNED_ENGINE_FIELDS = new Set([
  "leverage",
  "contract_size",
  "point",
  "tick_value",
  "commission_per_lot",
  "commission_perc",
  "swap_long_per_lot",
  "swap_short_per_lot",
  "swap_mode",
  "triple_swap_weekday",
  "use_spread",
  "spread_column",
  "fixed_spread_points",
  "margin_rate",
]);

function wireSetupModal() {
  els.openSetupBtn.addEventListener("click", openSetupModal);
  els.closeSetupBtn.addEventListener("click", closeSetupModal);
  els.cancelSetupBtn.addEventListener("click", closeSetupModal);
  els.setupModal.addEventListener("click", (event) => {
    if (event.target === els.setupModal) closeSetupModal();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && els.setupModal.classList.contains("visible")) {
      closeSetupModal();
    }
  });
  els.runSetupBtn.addEventListener("click", runSetup);

  // Tabs
  document.querySelectorAll(".modal-tabs button[data-tab]").forEach((btn) => {
    btn.addEventListener("click", () => activateTab(btn.dataset.tab));
  });

  // Config select changes -> update summary + reload strategy params + engine defaults
  els.configSelect.addEventListener("change", onConfigChange);
  els.strategySelect.addEventListener("change", onStrategyChange);
  els.datasetSelect.addEventListener("change", () => {
    renderSelectedAssetChips();
    syncEngineFieldsToSelectedAsset({ preserveCurrent: true });
    updateSummary();
  });
  els.assetSearch?.addEventListener("input", renderAssetPicker);
  els.assetList?.addEventListener("change", onAssetPickerChange);
  els.selectAllMt5Btn?.addEventListener("click", selectAllMt5Assets);
  els.clearAssetsBtn?.addEventListener("click", clearAssetSelection);
  els.replayModeSelect.addEventListener("change", updateSummary);

  els.resetStrategyBtn.addEventListener("click", () => {
    renderStrategyParams(getSelectedStrategyId(), getSelectedConfigParams(), /*useDefaults*/ true);
  });
  els.resetEngineBtn.addEventListener("click", () => {
    syncEngineFieldsToSelectedAsset({ preserveCurrent: false });
  });

  // Preset chips: click to fill the target input
  document.addEventListener("click", (e) => {
    const chip = e.target.closest(".preset-chip");
    if (!chip) return;
    const target = chip.dataset.presetTarget;
    const value = chip.dataset.presetValue;
    const input = document.querySelector(`[data-input="${target}"]`);
    if (!input) return;
    input.value = value;
    input.dispatchEvent(new Event("input", { bubbles: true }));
    checkFieldWarn(input);
    syncPresetActive(target, value);
  });

  // Warn validation + preset highlight on input change
  document.addEventListener("input", (e) => {
    if (e.target.dataset && e.target.dataset.input) {
      if (e.target.dataset.warnAbove !== undefined) checkFieldWarn(e.target);
      syncPresetActive(e.target.dataset.input, e.target.value);
    }
  });
}

function activateTab(tab) {
  document.querySelectorAll(".modal-tabs button[data-tab]").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.tab === tab);
  });
  document.querySelectorAll(".tab-pane[data-tab-pane]").forEach((pane) => {
    pane.classList.toggle("active", pane.dataset.tabPane === tab);
  });
}

function openSetupModal() {
  els.setupModal.classList.add("visible");
  els.setupStatus.textContent = "";
  els.setupStatus.className = "status-text";
  activateTab("data");
}

function closeSetupModal() {
  els.setupModal.classList.remove("visible");
}

async function refreshCatalog() {
  try {
    const response = await fetch("/api/catalog");
    if (!response.ok) return;
    const data = await response.json();
    catalogState.configs = data.configs || [];
    catalogState.strategies = data.strategies || [];
    catalogState.csvs = data.datasets?.csvs || [];
    catalogState.brokerPackages = data.datasets?.broker_packages || [];
    catalogState.engineFields = data.engine_fields || [];
    catalogState.current = data.current || {};
    renderCatalog();
  } catch (error) {
    console.error("catalog error", error);
  }
}

function renderCatalog() {
  // Configs
  els.configSelect.innerHTML = catalogState.configs.map((c) => {
    const flags = c.needs_broker_package
      ? " · precisa MT5 package"
      : (c.dataset_exists === false ? " · CSV ausente" : "");
    return `<option value="${escapeHtml(c.path)}">${escapeHtml(c.name)}  (${escapeHtml(c.strategy)})${escapeHtml(flags)}</option>`;
  }).join("");

  // Strategies
  const strategyOpts = catalogState.strategies.map((s) => `<option value="${escapeHtml(s.id)}">${escapeHtml(s.name)}</option>`);
  els.strategySelect.innerHTML = strategyOpts.join("");

  // Datasets
  const datasetOpts = [`<option value="">— Auto (do config) —</option>`];
  if (catalogState.brokerPackages.length) {
    const grouped = groupBy(catalogState.brokerPackages, (p) => p.broker || "MT5");
    Object.entries(grouped).sort(([a], [b]) => a.localeCompare(b)).forEach(([broker, packages]) => {
      datasetOpts.push(`<optgroup label="MT5 · ${escapeHtml(broker)}">`);
      packages
        .slice()
        .sort((a, b) => String(a.short_label || a.label).localeCompare(String(b.short_label || b.label)))
        .forEach((p) => {
          datasetOpts.push(`<option value="pkg:${escapeHtml(p.path)}">${escapeHtml(p.label)}</option>`);
        });
      datasetOpts.push("</optgroup>");
    });
  }
  if (catalogState.csvs.length) {
    const grouped = groupBy(catalogState.csvs, (c) => c.group || "CSVs");
    Object.entries(grouped).sort(([a], [b]) => a.localeCompare(b)).forEach(([group, csvs]) => {
      datasetOpts.push(`<optgroup label="CSV · ${escapeHtml(group)}">`);
      csvs.forEach((c) => {
        const label = `${c.label || c.path} · ${c.source_hint} · ${Number(c.size_kb || 0).toFixed(0)} KB`;
        datasetOpts.push(`<option value="csv:${escapeHtml(c.path)}::${escapeHtml(c.source_hint)}">${escapeHtml(label)}</option>`);
      });
      datasetOpts.push("</optgroup>");
    });
  }
  els.datasetSelect.innerHTML = datasetOpts.join("");
  renderAssetPicker();

  if (catalogState.current.config_path) {
    els.configSelect.value = catalogState.current.config_path;
  }
  if (catalogState.current.replay_mode && els.replayModeSelect) {
    els.replayModeSelect.value = catalogState.current.replay_mode;
  }
  onConfigChange();
}

function selectedDatasetValues() {
  return Array.from(els.datasetSelect.selectedOptions || []).map((opt) => opt.value).filter(Boolean);
}

function selectedBrokerPackages() {
  return selectedDatasetValues()
    .filter((value) => value.startsWith("pkg:"))
    .map((value) => {
      const pkgPath = value.slice(4);
      return catalogState.brokerPackages.find((p) => p.path === pkgPath) || null;
    })
    .filter(Boolean);
}

function getSelectedConfig() {
  return catalogState.configs.find((c) => c.path === els.configSelect.value) || null;
}

function getSelectedConfigParams() {
  return (getSelectedConfig()?.strategy_params) || {};
}

function getSelectedConfigEngine() {
  return (getSelectedConfig()?.engine) || {};
}

function getSelectedStrategyId() {
  const override = els.strategySelect.value;
  if (override) return override;
  return getSelectedConfig()?.strategy || null;
}

function onConfigChange() {
  const cfg = getSelectedConfig();
  if (!cfg) return;
  // Pre-select the config's default strategy in the dropdown (resolve alias → catalog id)
  const cfgStrat = cfg.strategy || "";
  const match = catalogState.strategies.find((s) => s.id === cfgStrat || (s.aliases && s.aliases.includes(cfgStrat)));
  els.strategySelect.value = match ? match.id : cfgStrat;
  clearAssetSelection({ silent: true });
  renderAssetPicker();
  renderStrategyParams(getSelectedStrategyId(), cfg.strategy_params || {});
  syncEngineFieldsToSelectedAsset({ preserveCurrent: false });
  updateSummary();
}

function renderAssetPicker() {
  if (!els.assetList || !els.datasetSelect) return;
  const query = (els.assetSearch?.value || "").trim().toLowerCase();
  const matches = (text) => !query || String(text || "").toLowerCase().includes(query);
  const selected = new Set(selectedDatasetValues());
  const sections = [];

  if (catalogState.brokerPackages.length) {
    const grouped = groupBy(catalogState.brokerPackages, (p) => p.broker || "MT5");
    Object.entries(grouped).sort(([a], [b]) => a.localeCompare(b)).forEach(([broker, packages]) => {
      const rows = packages
        .slice()
        .sort((a, b) => String(a.short_label || a.label).localeCompare(String(b.short_label || b.label)))
        .filter((p) => matches(`${p.label} ${p.symbol} ${p.timeframe} ${p.broker}`))
        .map((p) => assetPackageRow(p, selected));
      if (rows.length) {
        sections.push(`
          <div class="asset-group">
            <div class="asset-group-title">MT5 · ${escapeHtml(broker)}<span>${rows.length}</span></div>
            ${rows.join("")}
          </div>
        `);
      }
    });
  }

  if (catalogState.csvs.length) {
    const grouped = groupBy(catalogState.csvs, (c) => c.group || "CSVs");
    Object.entries(grouped).sort(([a], [b]) => a.localeCompare(b)).forEach(([group, csvs]) => {
      const rows = csvs
        .filter((c) => matches(`${c.label || c.path} ${c.source_hint} ${c.group}`))
        .map((c) => assetCsvRow(c, selected));
      if (rows.length) {
        sections.push(`
          <div class="asset-group">
            <div class="asset-group-title">CSV · ${escapeHtml(group)}<span>${rows.length}</span></div>
            ${rows.join("")}
          </div>
        `);
      }
    });
  }

  els.assetList.innerHTML = sections.join("") || `<div class="asset-empty">Nenhum ativo encontrado.</div>`;
  renderSelectedAssetChips();
}

function assetPackageRow(pkg, selected) {
  const value = `pkg:${pkg.path}`;
  const checked = selected.has(value) ? "checked" : "";
  const ticks = pkg.has_ticks
    ? (pkg.ticks_exported ? `${Number(pkg.ticks_exported).toLocaleString("pt-BR")} ticks` : "ticks")
    : "sem ticks";
  const bars = pkg.bars_exported ? `${Number(pkg.bars_exported).toLocaleString("pt-BR")} candles` : "candles";
  return `
    <label class="asset-row ${checked ? "selected" : ""}" data-asset-value="${escapeHtml(value)}">
      <input type="checkbox" data-asset-kind="pkg" value="${escapeHtml(value)}" ${checked}>
      <span class="asset-check"></span>
      <span class="asset-main">
        <strong>${escapeHtml(pkg.symbol || "Ativo")} <em>${escapeHtml(pkg.timeframe || "")}</em></strong>
        <small>${escapeHtml(bars)} · ${escapeHtml(ticks)}</small>
      </span>
    </label>
  `;
}

function assetCsvRow(csv, selected) {
  const value = `csv:${csv.path}::${csv.source_hint || ""}`;
  const checked = selected.has(value) ? "checked" : "";
  const label = csv.label || csv.path;
  return `
    <label class="asset-row csv ${checked ? "selected" : ""}" data-asset-value="${escapeHtml(value)}">
      <input type="radio" name="csvAsset" data-asset-kind="csv" value="${escapeHtml(value)}" ${checked}>
      <span class="asset-check"></span>
      <span class="asset-main">
        <strong>${escapeHtml(csv.name || label)}</strong>
        <small>${escapeHtml(label)} · ${escapeHtml(csv.source_hint || "csv")}</small>
      </span>
    </label>
  `;
}

function onAssetPickerChange(event) {
  const input = event.target.closest("[data-asset-kind]");
  if (!input) return;
  if (input.dataset.assetKind === "pkg" && input.checked) {
    setDatasetValues(selectedDatasetValues().filter((value) => !value.startsWith("csv:")));
  }
  if (input.dataset.assetKind === "csv" && input.checked) {
    setDatasetValues([input.value]);
  } else {
    const values = Array.from(els.assetList.querySelectorAll("[data-asset-kind='pkg']:checked")).map((item) => item.value);
    setDatasetValues(values);
  }
  renderAssetPicker();
  syncEngineFieldsToSelectedAsset({ preserveCurrent: true });
  updateSummary();
}

function setDatasetValues(values) {
  const selected = new Set(values.filter(Boolean));
  Array.from(els.datasetSelect.options).forEach((opt) => {
    opt.selected = selected.has(opt.value);
  });
}

function clearAssetSelection(options = {}) {
  setDatasetValues([]);
  if (els.assetSearch && !options.keepSearch) els.assetSearch.value = "";
  if (!options.silent) {
    renderAssetPicker();
    updateSummary();
  }
}

function selectAllMt5Assets() {
  const query = (els.assetSearch?.value || "").trim().toLowerCase();
  const values = catalogState.brokerPackages
    .filter((p) => !query || String(`${p.label} ${p.symbol} ${p.timeframe} ${p.broker}`).toLowerCase().includes(query))
    .map((p) => `pkg:${p.path}`);
  setDatasetValues(values);
  renderAssetPicker();
  updateSummary();
}

function renderSelectedAssetChips() {
  if (!els.selectedAssetChips) return;
  const values = selectedDatasetValues();
  if (!values.length) {
    els.selectedAssetChips.innerHTML = `<span class="muted">Auto do config</span>`;
    return;
  }
  const chips = values.map((value) => {
    if (value.startsWith("pkg:")) {
      const pkgPath = value.slice(4);
      const pkg = catalogState.brokerPackages.find((p) => p.path === pkgPath);
      return `<span>${escapeHtml(pkg?.short_label || pkgPath)}</span>`;
    }
    if (value.startsWith("csv:")) {
      const csvPath = value.slice(4).split("::")[0];
      const csv = catalogState.csvs.find((c) => c.path === csvPath);
      return `<span>${escapeHtml(csv?.name || csvPath)}</span>`;
    }
    return "";
  }).join("");
  els.selectedAssetChips.innerHTML = chips;
}

function getSelectedSingleBrokerPackage() {
  const packages = selectedBrokerPackages();
  return packages.length === 1 ? packages[0] : null;
}

function getEffectiveEngineBaseline(configEngine = {}) {
  const baseline = { ...(configEngine || {}) };
  const pkg = getSelectedSingleBrokerPackage();
  const pkgDefaults = pkg?.engine_defaults || {};
  PACKAGE_OWNED_ENGINE_FIELDS.forEach((key) => {
    if (Object.prototype.hasOwnProperty.call(pkgDefaults, key)) {
      baseline[key] = pkgDefaults[key];
    }
  });
  return baseline;
}

function syncEngineFieldsToSelectedAsset({ preserveCurrent = true } = {}) {
  const baseline = getEffectiveEngineBaseline(getSelectedConfigEngine());
  const hasRenderedFields = Boolean(document.querySelector('[data-input^="eng::"]'));
  const currentValues = preserveCurrent && hasRenderedFields ? collectInputs("eng") : {};
  const nextValues = { ...baseline, ...currentValues };
  PACKAGE_OWNED_ENGINE_FIELDS.forEach((key) => {
    if (Object.prototype.hasOwnProperty.call(baseline, key)) {
      nextValues[key] = baseline[key];
    }
  });
  console.log("[syncEngine] pkg:", getSelectedSingleBrokerPackage()?.label, "baseline.commission:", baseline.commission_per_lot, "baseline.tripleSwap:", baseline.triple_swap_weekday, "final.commission:", nextValues.commission_per_lot, "final.tripleSwap:", nextValues.triple_swap_weekday);
  renderEngineFields(nextValues, /*useDefaults*/ false, baseline);
}

function onStrategyChange() {
  const sid = getSelectedStrategyId();
  const cfgParams = (els.strategySelect.value === "" ? getSelectedConfigParams() : {});
  renderStrategyParams(sid, cfgParams);
  updateSummary();
}

function updateSummary() {
  const cfg = getSelectedConfig();
  if (!cfg) return;
  const ds = cfg.dataset || {};
  let asset = "—";
  const selectedPkgs = selectedBrokerPackages();
  const selectedValues = selectedDatasetValues();
  const selectedCsv = selectedValues.find((value) => value.startsWith("csv:"));
  if (selectedPkgs.length > 1) {
    asset = `${selectedPkgs.length} pacotes MT5`;
  } else if (selectedPkgs.length === 1) {
    asset = selectedPkgs[0] ? selectedPkgs[0].label : "pacote MT5";
  } else if (selectedCsv) {
    const csvPath = selectedCsv.slice(4).split("::")[0];
    const csv = catalogState.csvs.find((c) => c.path === csvPath);
    asset = csv ? (csv.label || csv.path) : csvPath;
  } else if (ds.symbol && ds.timeframe) {
    asset = `${ds.symbol} ${ds.timeframe}`;
  } else if (ds.path) {
    asset = ds.path;
  }
  els.sumAsset.textContent = asset;
  const tickOption = els.replayModeSelect.querySelector('option[value="tick"]');
  const canTick = Boolean(selectedPkgs.length === 1 && selectedPkgs[0] && selectedPkgs[0].has_ticks);
  if (tickOption) tickOption.disabled = !canTick;
  if (!canTick && els.replayModeSelect.value === "tick") {
    els.replayModeSelect.value = "candle";
  }
  els.sumReplay.textContent = selectedPkgs.length > 1 ? "Portfolio multi-ativos" : (els.replayModeSelect.value === "tick" ? "Ticks reais" : "Candles fechados");
  const strat = getSelectedStrategyId() || cfg.strategy;
  const stratMeta = catalogState.strategies.find((s) => s.id === strat);
  els.sumStrategy.textContent = stratMeta ? stratMeta.name : strat;
  const engine = cfg.engine || {};
  const cap = engine.initial_capital;
  els.sumCapital.textContent = cap ? Number(cap).toLocaleString("pt-BR", { style: "currency", currency: "USD" }) : "—";
}

// ---------- Strategy params (dynamic) ----------

function renderStrategyParams(strategyId, configParams, useDefaults) {
  const grid = els.strategyParamsGrid;
  const strat = catalogState.strategies.find((s) => s.id === strategyId);
  if (!strat || !strat.params || !strat.params.length) {
    grid.innerHTML = `<div style="grid-column: 1/-1; color: var(--muted); font-size: 11px; text-align: center; padding: 12px;">
      ${strategyId ? "Esta estratégia não expõe parâmetros." : "Selecione uma estratégia para editar os parâmetros."}
    </div>`;
    els.strategyParamsCount.textContent = "0";
    els.strategyHint.textContent = strategyId ? `Estratégia: ${strat ? strat.name : strategyId}` : "Selecione a estratégia.";
    return;
  }
  els.strategyParamsCount.textContent = String(strat.params.length);
  els.strategyHint.textContent = `${strat.name} · ${strat.params.length} parâmetros editáveis.`;

  grid.innerHTML = strat.params.map((p) => {
    const valueFromCfg = configParams && Object.prototype.hasOwnProperty.call(configParams, p.key)
      ? configParams[p.key]
      : undefined;
    const initial = useDefaults || valueFromCfg === undefined ? p.default : valueFromCfg;
    return renderInputField({
      key: `strat::${p.key}`,
      label: humanize(p.key),
      type: p.type,
      options: p.options,
      defaultValue: p.default,
      currentValue: initial,
    });
  }).join("");
}

// ---------- Engine fields ----------

function renderEngineFields(configEngine, useDefaults, baselineEngine) {
  Object.values(ENGINE_GROUP_ELEMENTS).forEach((id) => { els[id].innerHTML = ""; });
  const effectiveBaseline = baselineEngine || configEngine || {};
  catalogState.engineFields.forEach((field) => {
    const groupEl = els[ENGINE_GROUP_ELEMENTS[field.group]];
    if (!groupEl) return;
    const fromCfg = configEngine && Object.prototype.hasOwnProperty.call(configEngine, field.key)
      ? configEngine[field.key]
      : undefined;
    const baselineValue = Object.prototype.hasOwnProperty.call(effectiveBaseline, field.key)
      ? effectiveBaseline[field.key]
      : field.default;
    const initial = useDefaults || fromCfg === undefined ? baselineValue : fromCfg;
    groupEl.insertAdjacentHTML("beforeend", renderInputField({
      key: `eng::${field.key}`,
      label: field.label,
      type: field.type,
      options: field.options,
      defaultValue: baselineValue,
      currentValue: initial,
      hint: field.hint,
      step: field.step,
      min: field.min,
      warnAbove: field.warn_above,
      presets: field.presets,
    }));
  });
  // Hide any group section (header + body) that ended up with no fields, so we never
  // show an empty header like "Execução".
  Object.values(ENGINE_GROUP_ELEMENTS).forEach((id) => {
    const body = els[id];
    if (!body) return;
    const section = body.closest(".section-block");
    if (section) section.hidden = body.children.length === 0;
  });
  initFieldWarns();
}

function cleanFloat(v) {
  if (v === null || v === undefined || v === "") return v;
  const n = Number(v);
  if (isNaN(n)) return v;
  return parseFloat(n.toPrecision(10));
}

function renderInputField({ key, label, type, options, defaultValue, currentValue, hint, step, min, warnAbove, presets }) {
  const dataKey = key;
  const cleanDefault = (type === "number" || type === "integer") ? cleanFloat(defaultValue) : defaultValue;
  const cleanCurrent = (type === "number" || type === "integer") ? cleanFloat(currentValue) : currentValue;
  const defaultStr = cleanDefault === null || cleanDefault === undefined ? "auto" : String(cleanDefault);
  const value = cleanCurrent === null || cleanCurrent === undefined ? "" : cleanCurrent;
  let control = "";
  if (type === "boolean") {
    const checked = value === true || value === "true" ? "checked" : "";
    control = `<label class="checkbox-wrap"><input type="checkbox" data-input="${dataKey}" ${checked}><span>${checked ? "ativo" : "desativado"}</span></label>`;
  } else if (type === "select") {
    const opts = (options || []).map((opt) => {
      const text = selectOptionLabel(key, opt);
      return `<option value="${opt}"${String(opt) === String(value) ? " selected" : ""}>${escapeHtml(text)}</option>`;
    }).join("");
    control = `<select data-input="${dataKey}">${opts}</select>`;
  } else if (type === "integer" || type === "number") {
    const stepAttr = step !== undefined ? `step="${step}"` : (type === "integer" ? 'step="1"' : 'step="any"');
    const minAttr = min !== undefined ? `min="${min}"` : "";
    const warnAttr = warnAbove !== undefined && warnAbove !== null ? `data-warn-above="${warnAbove}"` : "";
    control = `<input type="number" data-input="${dataKey}" value="${value}" placeholder="${defaultStr}" ${stepAttr} ${minAttr} ${warnAttr}>`;
  } else {
    control = `<input type="text" data-input="${dataKey}" value="${value}" placeholder="${defaultStr}">`;
  }
  const hintHtml = hint ? `<span class="field-hint-inline">${hint}</span>` : "";
  let presetsHtml = "";
  if (presets && presets.length) {
    const chips = presets.map((p) => {
      const detailSpan = p.detail ? `<span class="preset-detail">${escapeHtml(p.detail)}</span>` : "";
      return `<button type="button" class="preset-chip" data-preset-target="${dataKey}" data-preset-value="${p.value}"><span class="preset-label">${escapeHtml(p.label)}</span>${detailSpan}</button>`;
    }).join("");
    presetsHtml = `<div class="field-presets">${chips}</div>`;
  }
  const warnHtml = warnAbove !== undefined && warnAbove !== null
    ? `<span class="field-warn-msg" data-warn-for="${dataKey}" style="display:none"></span>`
    : "";
  return `<div class="input-field">
    <span class="input-label">${label}<span class="default-hint">default ${defaultStr}</span></span>
    ${control}
    ${presetsHtml}
    ${hintHtml}
    ${warnHtml}
  </div>`;
}

function syncPresetActive(dataKey, currentValue) {
  document.querySelectorAll(`.preset-chip[data-preset-target="${dataKey}"]`).forEach((chip) => {
    chip.classList.toggle("active", String(chip.dataset.presetValue) === String(currentValue));
  });
}

function checkFieldWarn(input) {
  const warnAbove = parseFloat(input.dataset.warnAbove);
  if (isNaN(warnAbove)) return;
  const val = parseFloat(input.value);
  const dataKey = input.dataset.input;
  const warnEl = document.querySelector(`[data-warn-for="${dataKey}"]`);
  const field = input.closest(".input-field");
  if (!field) return;
  field.classList.remove("value-warn", "value-danger");
  if (warnEl) { warnEl.style.display = "none"; warnEl.textContent = ""; }
  if (isNaN(val) || val === 0) return;
  if (val > warnAbove * 3) {
    field.classList.add("value-danger");
    if (warnEl) { warnEl.style.display = ""; warnEl.textContent = "Valor extremamente alto — verifique a unidade."; }
  } else if (val > warnAbove) {
    field.classList.add("value-warn");
    if (warnEl) { warnEl.style.display = ""; warnEl.textContent = "Acima da faixa típica."; }
  }
}

function initFieldWarns() {
  document.querySelectorAll("[data-warn-above]").forEach((input) => checkFieldWarn(input));
  document.querySelectorAll(".preset-chip").forEach((chip) => {
    const input = document.querySelector(`[data-input="${chip.dataset.presetTarget}"]`);
    if (input) syncPresetActive(chip.dataset.presetTarget, input.value);
  });
}

function selectOptionLabel(key, value) {
  if (key === "eng::triple_swap_weekday") {
    return {
      0: "Segunda",
      1: "Terça",
      2: "Quarta",
      3: "Quinta",
      4: "Sexta",
      5: "Sábado",
      6: "Domingo",
    }[Number(value)] || String(value);
  }
  return String(value);
}

function humanize(key) {
  return key.replace(/_/g, " ").replace(/\b\w/g, (l) => l.toUpperCase());
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function groupBy(items, keyFn) {
  return (items || []).reduce((acc, item) => {
    const key = keyFn(item);
    (acc[key] ||= []).push(item);
    return acc;
  }, {});
}

function collectInputs(prefix) {
  const out = {};
  document.querySelectorAll(`[data-input^="${prefix}::"]`).forEach((input) => {
    const key = input.dataset.input.slice(prefix.length + 2);
    let value;
    if (input.type === "checkbox") {
      value = input.checked;
    } else if (input.tagName === "SELECT") {
      value = input.value;
      // Coerce numeric select values back
      if (!Number.isNaN(Number(value)) && value !== "") value = Number(value);
    } else if (input.type === "number") {
      const raw = input.value.trim();
      value = raw === "" ? null : Number(raw);
      if (Number.isNaN(value)) value = null;
    } else {
      const raw = input.value.trim();
      if (raw === "") {
        value = null;
      } else if (key === "max_exposure_by_symbol" || key === "max_exposure_by_currency") {
        try {
          value = JSON.parse(raw);
        } catch (_) {
          value = raw;
        }
      } else {
        value = raw;
      }
    }
    out[key] = value;
  });
  return out;
}

async function runSetup() {
  const configPath = els.configSelect.value || null;
  const strategyId = els.strategySelect.value || null;
  const datasetValues = selectedDatasetValues();
  const replayMode = els.replayModeSelect.value || "candle";
  const reuseReport = els.reuseReportToggle.checked;

  let brokerPackage = null;
  let brokerPackages = null;
  let datasetPath = null;
  let datasetSource = null;

  const pkgValues = datasetValues.filter((value) => value.startsWith("pkg:")).map((value) => value.slice(4));
  const csvValue = datasetValues.find((value) => value.startsWith("csv:")) || "";

  if (pkgValues.length > 1) {
    brokerPackages = pkgValues;
  } else if (pkgValues.length === 1) {
    brokerPackage = pkgValues[0];
  } else if (csvValue.startsWith("csv:")) {
    const rest = csvValue.slice(4);
    const [pathPart, hint] = rest.split("::");
    datasetPath = pathPart;
    datasetSource = hint || null;
  }

  // Diff strategy params + engine vs config defaults — only send overrides.
  const cfg = getSelectedConfig() || {};
  const cfgParams = cfg.strategy_params || {};
  const cfgEngine = cfg.engine || {};
  const strategyValues = collectInputs("strat");
  const engineValues = collectInputs("eng");

  const strategyParams = {};
  Object.entries(strategyValues).forEach(([k, v]) => {
    const cfgV = cfgParams[k];
    // Send if different from config default (or config has no entry and value is non-null)
    if (!shallowEqual(v, cfgV)) strategyParams[k] = v;
  });
  const engineOverrides = {};
  Object.entries(engineValues).forEach(([k, v]) => {
    const cfgV = cfgEngine[k];
    if (!shallowEqual(v, cfgV)) engineOverrides[k] = v;
  });

  const startDate = (els.startDateInput?.value || "").trim() || null;
  const endDate = (els.endDateInput?.value || "").trim() || null;
  const payload = {
    config_path: configPath,
    broker_package: brokerPackage,
    broker_packages: brokerPackages,
    dataset_path: datasetPath,
    dataset_source: datasetSource,
    replay_mode: replayMode,
    strategy_id: strategyId,
    strategy_params: Object.keys(strategyParams).length ? strategyParams : null,
    engine_overrides: Object.keys(engineOverrides).length ? engineOverrides : null,
    reuse_report: reuseReport,
    start_date: startDate,
    end_date: endDate,
  };

  els.setupStatus.textContent = "Rodando backtest…";
  els.setupStatus.className = "status-text";
  els.runSetupBtn.disabled = true;
  els.qualityBanner.classList.remove("visible");

  // Estimate based on dataset size hints
  const cfgEst = getSelectedConfig();
  const isBig = brokerPackages || brokerPackage || (cfgEst && cfgEst.needs_broker_package);
  const noCache = !reuseReport
    || Object.keys(strategyParams).length > 0
    || Object.keys(engineOverrides).length > 0
    || datasetPath
    || brokerPackage
    || brokerPackages
    || startDate
    || endDate;
  // Tick replay on a broker package can run for minutes; use a long estimate so the
  // animation creeps slowly and the job's REAL progress (12→55→90) drives the bar.
  const isTick = els.replayModeSelect && els.replayModeSelect.value === "tick";
  const estimateMs = noCache
    ? (isTick && isBig ? 240000 : isBig ? 14000 : 3500)
    : (isBig ? 2500 : 900);
  startLoadingSequence({
    title: noCache ? "Executando backtest" : "Carregando sessão",
    estimateMs,
  });

  try {
    // Fresh runs (especially full tick history) execute on a server worker thread
    // and we POLL for progress — no fetch timeout to kill a long run, no held lock.
    // Cached/light loads still resolve on the first poll.
    let session;
    if (noCache) {
      const startResp = await fetch("/api/session/load", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...payload, async: true }),
      });
      const startData = await startResp.json().catch(() => ({}));
      if (!startResp.ok || !startData.ok || !startData.job_id) {
        throw new Error(startData.error || `HTTP ${startResp.status}`);
      }
      session = await pollBacktestJob(startData.job_id);
    } else {
      const response = await fetch("/api/session/load", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!response.ok) {
        const errText = await response.text();
        let message = errText || `HTTP ${response.status}`;
        try { message = (JSON.parse(errText).error) || message; } catch (_) {}
        throw new Error(message);
      }
      const data = await response.json();
      if (!data.ok) throw new Error(data.error || "Falha ao carregar.");
      session = data.session;
    }
    state.session = session;
    state.reportScope = "account";
    precomputeLookups();
    state.index = Math.max(0, Math.min(state.windowBars, replayMaxIndex()));
    state.selectedTradeId = null;
    state.panOffset = 0;
    state.zoom = 1.0;
    renderStatic();
    resizeCanvases();
    render();
    renderInteractiveReports();
    refreshCatalog();
    if (els.pfEnabled && els.pfEnabled.checked) {
      runPropfirm();
    }
    els.setupStatus.textContent = "✓ Backtest carregado.";
    els.setupStatus.className = "status-text success";
    if (session.metadata && !session.metadata.quality_ok) {
      els.qualityBanner.textContent = `Atenção: ${session.metadata.quality_message}`;
      els.qualityBanner.classList.add("visible");
    }
    finishLoadingSequence();
    setTimeout(hideLoading, 300);
    setTimeout(closeSetupModal, 800);
  } catch (error) {
    console.error(error);
    const message = String(error.message || error);
    const friendly = message.includes("Failed to fetch")
      ? "Servidor local não respondeu. Reinicie a UI e tente de novo."
      : message;
    els.setupStatus.textContent = `✕ ${friendly}`;
    els.setupStatus.className = "status-text error";
    hideLoading();
  } finally {
    els.runSetupBtn.disabled = false;
  }
}

// Poll a background backtest job until it finishes, streaming its coarse progress
// into the loading overlay. No timeout: a full tick-history run can take minutes.
async function pollBacktestJob(jobId) {
  while (true) {
    await new Promise((r) => setTimeout(r, 1200));
    let resp;
    try {
      resp = await fetch(`/api/session/job?id=${encodeURIComponent(jobId)}`);
    } catch (_) {
      continue; // transient network hiccup — keep polling
    }
    const data = await resp.json().catch(() => ({}));
    if (resp.status === 404) throw new Error("Job perdido no servidor. Reinicie a UI e tente de novo.");
    if (data.message) loadingState.message = data.message;
    if (typeof data.progress === "number") loadingState.pct = Math.max(loadingState.pct, data.progress);
    if (data.status === "done") return data.session;
    if (data.status === "error") throw new Error(data.error || "Falha no backtest.");
  }
}

// ============================================================
// Reports gallery
// ============================================================

function wireReports() {
  els.reloadReportsBtn.addEventListener("click", renderInteractiveReports);
  els.exportReportBtn.addEventListener("click", exportSessionHtml);
  els.runRobustnessBtn?.addEventListener("click", runRobustness);
  els.runPropfirmBtn?.addEventListener("click", runPropfirm);
  els.pfPresetSelect?.addEventListener("change", applyPropfirmPreset);
  els.reportTabs?.addEventListener("click", (event) => {
    const btn = event.target.closest("[data-report-scope]");
    if (!btn) return;
    state.reportScope = btn.dataset.reportScope || "account";
    closeChartHelp();
    renderInteractiveReports();
  });
  document.addEventListener("click", (event) => {
    if (!els.chartHelpPopover || !els.chartHelpPopover.classList.contains("visible")) return;
    if (event.target.closest(".chart-help-popover") || event.target.closest(".chart-help-btn")) return;
    closeChartHelp();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeChartHelp();
  });
}

const ROBUST_FLAG_COLORS = { good: "#2bd47f", warn: "#ffab00", bad: "#ff5252", "n/a": "#5f6b80" };
const ROBUST_FLAG_LABELS = { oos: "Out-of-Sample", pbo: "Overfit (PBO)", walk_forward: "Walk-Forward", cost: "Stress de Custo" };

async function runRobustness() {
  const btn = els.runRobustnessBtn;
  if (!btn || btn.disabled) return;
  const label0 = btn.textContent;
  btn.disabled = true;
  btn.textContent = "Rodando… (~30-60s)";
  els.robustVerdict.textContent = "…";
  els.robustFlags.innerHTML = "";
  els.robustGallery.innerHTML = "";
  els.robustSummary.innerHTML = '<div class="robust-loading">Rodando a bateria… isso dispara dezenas de backtests (IS/OOS, walk-forward, PBO, sensibilidade, stress de custo, multi-mercado). Pode levar ~30-60s.</div>';
  try {
    const res = await fetch("/api/robustness");
    const data = await res.json();
    if (!data.ok) {
      els.robustSummary.innerHTML = `<div class="robust-loading" style="color:var(--amber);">${escapeHtml(data.error || "Falha ao rodar robustez.")}</div>`;
      return;
    }
    renderRobustness(data);
  } catch (err) {
    els.robustSummary.innerHTML = `<div class="robust-loading" style="color:var(--red);">Erro: ${escapeHtml(err.message || String(err))}</div>`;
  } finally {
    btn.disabled = false;
    btn.textContent = label0;
  }
}

function renderRobustness(data) {
  const card = data.scorecard || {};
  const v = card.verdict || {};
  const rating = v.rating || "—";
  const ratingColor = rating === "Robusta" ? "good" : rating === "Aceitavel" ? "warn" : rating === "Fragil" ? "bad" : "n/a";
  els.robustVerdict.textContent = rating;
  els.robustVerdict.style.background = ROBUST_FLAG_COLORS[ratingColor];
  els.robustVerdict.style.color = "#06090f";

  const flags = v.flags || {};
  els.robustFlags.innerHTML = Object.keys(ROBUST_FLAG_LABELS).map((k) => {
    const f = flags[k] || "n/a";
    const c = ROBUST_FLAG_COLORS[f];
    return `<span class="robust-flag" style="border-color:${c};color:${c};"><span class="dot" style="background:${c};"></span>${ROBUST_FLAG_LABELS[k]}: ${f}</span>`;
  }).join("");

  els.robustSummary.innerHTML = robustSummaryHtml(card);

  const imgs = data.images || [];
  els.robustGallery.innerHTML = imgs.map((im) => `
    <div class="report-card">
      <div class="card-head"><div class="card-title">${escapeHtml(robustChartTitle(im.name))}</div></div>
      <img src="${im.url}?t=${Date.now()}" alt="${escapeHtml(im.name)}" style="width:100%;border-radius:8px;display:block;">
    </div>`).join("");
}

function robustSummaryHtml(card) {
  const io = card.in_out_sample || {};
  const of = card.overfit || {};
  const wf = card.walk_forward || {};
  const cs = card.cost_stress || {};
  const meta = card.meta || {};
  const num = (x, d = 2) => (x === null || x === undefined || Number.isNaN(Number(x))) ? "—" : Number(x).toFixed(d);
  const rows = [
    ["IS Profit Factor", num(io.is && io.is.profit_factor), `OOS: ${num(io.oos && io.oos.profit_factor)}`],
    ["PF Retention (OOS/IS)", num(io.pf_retention), (io.pf_retention >= 1) ? "edge segurou/melhorou" : "edge enfraqueceu"],
    ["PBO (prob. overfit)", num(of.pbo), `${of.n_configs || 0} configs`],
    ["Deflated Sharpe", num(of.dsr), "prob. do Sharpe ser real"],
    ["WFO degradacao IS→OOS", num(wf.is_to_oos_degradation, 3), `${(wf.windows || []).length} janelas`],
    ["Custo breakeven", cs.breakeven_commission == null ? "> faixa testada" : `$${num(cs.breakeven_commission, 1)}`, `atual $${num(cs.current_commission, 1)}`],
  ];
  const grid = rows.map(([l, val, sub]) => `<div class="robust-metric"><span>${l}</span><strong>${val}</strong><small>${escapeHtml(String(sub))}</small></div>`).join("");
  const period = (card.period || []).filter(Boolean).map((d) => String(d).slice(0, 10)).join(" → ");
  const mm = ((card.multi_market || {}).markets || []).map((m) => `${m.symbol} ${m.timeframe}: PF ${num(m.profit_factor)}`).join("  ·  ");
  const note = `Estrategia ${meta.strategy || "?"} · ${meta.bars_used || 0} barras${meta.capped ? ` (de ${meta.bars_total})` : ""}${period ? " · " + period : ""}${mm ? " · Multi: " + mm : ""}`;
  return `<div class="robust-grid">${grid}</div><div class="robust-note">${escapeHtml(note)}</div>`;
}

function robustChartTitle(name) {
  return {
    robust_is_oos: "In-Sample vs Out-of-Sample",
    robust_walk_forward: "Walk-Forward (IS x OOS por janela)",
    robust_sensitivity: "Sensibilidade de parametro",
    robust_heatmap: "Heatmap de sensibilidade",
    robust_cost_stress: "Stress de custo (margem ate quebrar)",
    robust_multi_market: "Multi-mercado (generaliza?)",
  }[name] || name;
}

const PROPFIRM_VERDICT_COLORS = { APPROVES: "#2bd47f", RISKY: "#ffab00", FAILS: "#ff5252", no_data: "#5f6b80" };
const PROPFIRM_PRESETS = {
  ftmo_challenge:    { target: 10, daily: 5, total: 10, minDays: 4, maxDays: "", trailing: "", mode: "equity", basis: "peak", lock: false, consist: "", weekend: false, stop: false },
  ftmo_verification: { target: 5,  daily: 5, total: 10, minDays: 4, maxDays: "", trailing: "", mode: "equity", basis: "peak", lock: false, consist: "", weekend: false, stop: false },
  ftmo_funded:       { target: "", daily: 5, total: 10, minDays: 0, maxDays: "", trailing: "", mode: "equity", basis: "peak", lock: false, consist: "", weekend: false, stop: false },
  trailing_desk:     { target: 8,  daily: 5, total: 99, minDays: 3, maxDays: "", trailing: 6, mode: "equity", basis: "peak", lock: false, consist: 40, weekend: false, stop: false },
};

function applyPropfirmPreset() {
  const p = PROPFIRM_PRESETS[(els.pfPresetSelect && els.pfPresetSelect.value) || "ftmo_challenge"];
  if (!p) return;
  if (els.pfTarget) els.pfTarget.value = p.target;
  if (els.pfDaily) els.pfDaily.value = p.daily;
  if (els.pfTotal) els.pfTotal.value = p.total;
  if (els.pfMinDays) els.pfMinDays.value = p.minDays;
  if (els.pfMaxDays) els.pfMaxDays.value = p.maxDays;
  if (els.pfTrailingEnabled) els.pfTrailingEnabled.checked = Boolean(p.trailing);
  if (els.pfConsist) els.pfConsist.value = p.consist;
  if (els.pfWeekend) els.pfWeekend.checked = p.weekend;
  if (els.pfReqStop) els.pfReqStop.checked = p.stop;
}

async function runPropfirm() {
  const btn = els.runPropfirmBtn;
  if (!btn || btn.disabled) return;
  const label0 = btn.textContent;
  btn.disabled = true;
  btn.textContent = "Avaliando…";
  els.propfirmVerdict.textContent = "…";
  els.propfirmFlags.innerHTML = "";
  els.propfirmSummary.innerHTML = '<div class="robust-loading">Avaliando contra as regras da mesa: simula um challenge começando em cada dia (taxa de aprovação em janela móvel), além do passe único.</div>';
  try {
    const preset = (els.pfPresetSelect && els.pfPresetSelect.value) || "ftmo_challenge";
    const q = new URLSearchParams({ preset });
    const fld = (el, key) => { const v = el && el.value; if (v !== "" && v != null) q.set(key, v); };
    fld(els.pfAccount, "account_size");
    fld(els.pfTarget, "profit_target");
    fld(els.pfDaily, "max_daily_loss");
    fld(els.pfTotal, "max_total_loss");
    fld(els.pfMinDays, "min_trading_days");
    fld(els.pfMaxDays, "max_days");
    if (els.pfTrailingEnabled && els.pfTrailingEnabled.checked) {
      const totalVal = els.pfTotal && els.pfTotal.value;
      if (totalVal) q.set("trailing_dd", totalVal);
      q.set("trailing_mode", "equity");
      q.set("trailing_basis", "peak");
      q.set("trailing_locks_at_initial", "0");
    }
    fld(els.pfConsist, "max_best_day");
    if (els.pfWeekend) q.set("forbid_weekend_holding", els.pfWeekend.checked ? "1" : "0");
    if (els.pfReqStop) q.set("require_stop_loss", els.pfReqStop.checked ? "1" : "0");
    const res = await fetch(`/api/propfirm?${q.toString()}`);
    const data = await res.json();
    if (!data.ok) {
      els.propfirmSummary.innerHTML = `<div class="robust-loading" style="color:var(--amber);">${escapeHtml(data.error || "Falha ao avaliar prop firm.")}</div>`;
      return;
    }
    renderPropfirm(data);
  } catch (err) {
    els.propfirmSummary.innerHTML = `<div class="robust-loading" style="color:var(--red);">Erro: ${escapeHtml(err.message || String(err))}</div>`;
  } finally {
    btn.disabled = false;
    btn.textContent = label0;
  }
}

function renderPropfirm(data) {
  const card = data.scorecard || {};
  const verdict = card.verdict || "no_data";
  const color = PROPFIRM_VERDICT_COLORS[verdict] || PROPFIRM_VERDICT_COLORS.no_data;
  const label = { APPROVES: "APROVA", RISKY: "ARRISCADA", FAILS: "REPROVA", no_data: "—" }[verdict] || verdict;
  els.propfirmVerdict.textContent = label;
  els.propfirmVerdict.style.background = color;
  els.propfirmVerdict.style.color = "#06090f";

  // Flags: each ACTIVE prop-firm rule from the single-pass check, with actual vs limit.
  const single = card.single || {};
  const checks = single.checks || {};
  const rules = card.rules || {};
  const tr = card.trade_rules || {};
  const pct1 = (x, d = 1) => (x == null || Number.isNaN(Number(x))) ? "—" : (Number(x) * 100).toFixed(d) + "%";
  const flagInfo = {
    profit_target: ["Meta", `${(single.max_gain_pct || 0).toFixed(1)}% / ${pct1(rules.profit_target_pct, 0)}`],
    max_daily_loss: ["Perda diária", `${(single.worst_daily_dd_pct || 0).toFixed(1)}% / -${pct1(rules.max_daily_loss_pct, 0)}`],
    max_total_loss: ["Perda total", `${(single.worst_total_dd_pct || 0).toFixed(1)}% / -${pct1(rules.max_total_loss_pct, 0)}`],
    trailing_dd: ["Trailing DD", `${(single.worst_trailing_dd_pct || 0).toFixed(1)}% / -${pct1(rules.trailing_dd_pct, 0)} ${rules.trailing_mode || ""}`],
    min_trading_days: ["Dias", `${single.trading_days || 0} / ${rules.min_trading_days || 0}`],
    consistency: ["Consistência", `${single.consistency_pct == null ? "—" : single.consistency_pct.toFixed(0) + "%"} / ${pct1(rules.max_best_day_pct, 0)}`],
    weekend_holding: ["Fim de semana", `${tr.weekend_holds || 0} holds`],
    stop_loss: ["Stop obrigatório", `${tr.no_stop || 0} sem stop`],
  };
  // Only show flags for rules that are actually active (present in checks).
  els.propfirmFlags.innerHTML = Object.keys(flagInfo).filter((k) => k in checks).map((k) => {
    const ok = checks[k];
    const c = ok ? ROBUST_FLAG_COLORS.good : ROBUST_FLAG_COLORS.bad;
    const [lbl, detail] = flagInfo[k];
    return `<span class="robust-flag" style="border-color:${c};color:${c};"><span class="dot" style="background:${c};"></span>${lbl}: ${escapeHtml(detail)}</span>`;
  }).join("");

  els.propfirmSummary.innerHTML = propfirmSummaryHtml(card);
}

// SVG donut from segments [{v, c, l}]; centerTop/centerBottom render in the hole.
function pfDonut(segments, centerTop, centerBottom) {
  const total = segments.reduce((a, s) => a + (s.v || 0), 0) || 1;
  const R = 42, C = 2 * Math.PI * R;
  let off = 0;
  const rings = segments.filter((s) => (s.v || 0) > 0).map((s) => {
    const len = (s.v / total) * C;
    const ring = `<circle cx="50" cy="50" r="${R}" fill="none" stroke="${s.c}" stroke-width="13"
      stroke-dasharray="${len.toFixed(2)} ${(C - len).toFixed(2)}" stroke-dashoffset="${(-off).toFixed(2)}"
      transform="rotate(-90 50 50)"><title>${s.l}: ${s.v}</title></circle>`;
    off += len;
    return ring;
  }).join("");
  return `<svg viewBox="0 0 100 100" class="pf-donut">
    <circle cx="50" cy="50" r="${R}" fill="none" stroke="rgba(255,255,255,.07)" stroke-width="13"/>
    ${rings}
    <text x="50" y="47" class="pf-donut-top">${centerTop}</text>
    <text x="50" y="64" class="pf-donut-bot">${centerBottom}</text></svg>`;
}

function pfLegend(segments) {
  return `<div class="pf-legend">` + segments.filter((s) => (s.v || 0) > 0).map((s) =>
    `<span><i style="background:${s.c}"></i>${escapeHtml(s.l)} <b>${s.v}</b></span>`).join("") + `</div>`;
}

function propfirmSummaryHtml(card) {
  const single = card.single || {};
  const p1 = card.phase1 || {};
  const p2 = card.phase2 || {};
  const fund = card.funded || {};
  const rules = card.rules || {};
  const meta = card.meta || {};
  const pct = (x, d = 1) => (x == null || Number.isNaN(Number(x))) ? "—" : (Number(x) * 100).toFixed(d) + "%";
  const num = (x, d = 0) => (x == null || Number.isNaN(Number(x))) ? "—" : Number(x).toFixed(d);
  const money = (x) => (x == null || Number.isNaN(Number(x))) ? "—" : "$" + Math.round(Number(x)).toLocaleString();

  const phaseSegs = (ph) => {
    const b = ph.breakdown_counts || {};
    return [
      { v: b.pass || 0, c: "#2bd47f", l: "Aprovou" },
      { v: b.fail_daily || 0, c: "#ff5252", l: "Perda diária" },
      { v: b.fail_total || 0, c: "#c0392b", l: "Perda total" },
      { v: b.fail_trailing || 0, c: "#e67e22", l: "Trailing DD" },
      { v: b.incomplete || 0, c: "#5f6b80", l: "Sem meta" },
    ];
  };
  // Funded: survive vs blow-up (by reason). reasons are % of n_starts -> back to counts.
  const n = fund.n_starts || 0;
  const rc = (p) => Math.round((p || 0) / 100 * n);
  const fr = fund.blowup_reasons_pct || {};
  const fundSegs = [
    { v: n - (fund.blowup_count || 0), c: "#2bd47f", l: "Mantém a conta" },
    { v: rc(fr.fail_daily), c: "#ff5252", l: "Perda diária" },
    { v: rc(fr.fail_total), c: "#c0392b", l: "Perda total" },
    { v: rc(fr.fail_trailing), c: "#e67e22", l: "Trailing DD" },
  ];

  const stages = `
    <div class="pf-stages">
      <div class="pf-stage">
        <div class="pf-stage-title">Fase 1 · Challenge</div>
        ${pfDonut(phaseSegs(p1), pct(p1.pass_rate), "aprova")}
        ${pfLegend(phaseSegs(p1))}
        <div class="pf-stage-stats">
          <div class="pf-stat"><span class="pf-stat-label">Aprovações</span><span class="pf-stat-value">${p1.pass_count || 0} / ${p1.n_starts || 0}</span></div>
          <div class="pf-stat"><span class="pf-stat-label">Tentativas p/ passar</span><span class="pf-stat-value">~${num(p1.expected_attempts, 1)}</span></div>
          <div class="pf-stat"><span class="pf-stat-label">Dias p/ meta</span><span class="pf-stat-value">${num(p1.min_days_to_pass)}–${num(p1.max_days_to_pass)} (méd ${num(p1.median_days_to_pass)})</span></div>
        </div>
      </div>
      <div class="pf-stage">
        <div class="pf-stage-title">Fase 2 · Verificação</div>
        ${pfDonut(phaseSegs(p2), pct(p2.pass_rate), "aprova")}
        ${pfLegend(phaseSegs(p2))}
        <div class="pf-stage-stats">
          <div class="pf-stat"><span class="pf-stat-label">Aprovações</span><span class="pf-stat-value">${p2.pass_count || 0} / ${p2.n_starts || 0}</span></div>
          <div class="pf-stat"><span class="pf-stat-label">Combinada 1→2</span><span class="pf-stat-value highlight">${pct(card.combined_pass_rate)}</span></div>
        </div>
      </div>
      <div class="pf-stage pf-stage-funded">
        <div class="pf-stage-title">Conta Financiada</div>
        ${pfDonut(fundSegs, pct(fund.survive_rate), "mantém")}
        ${pfLegend(fundSegs)}
        <div class="pf-stage-stats">
          <div class="pf-stat"><span class="pf-stat-label">Perde a conta</span><span class="pf-stat-value">${fund.blowup_count || 0} / ${n} (${pct(fund.blowup_rate)})</span></div>
          <div class="pf-stat"><span class="pf-stat-label">Méd dias até perder</span><span class="pf-stat-value">${num(fund.median_days_to_blowup)}d</span></div>
          <div class="pf-stat"><span class="pf-stat-label">Pico de saldo</span><span class="pf-stat-value">${money(fund.peak_balance)}</span></div>
          <div class="pf-stat"><span class="pf-stat-label">Saque máximo</span><span class="pf-stat-value">${money(fund.peak_profit)}</span></div>
        </div>
      </div>
    </div>`;

  const passLabel = single.passed ? "passaria neste período" : `reprova (${single.binding_rule || "—"})`;
  const note = `${escapeHtml(card.preset || "Prop firm")}${card.custom ? " (custom)" : ""} · conta ${money(card.account_size)} · passe único: ${escapeHtml(passLabel)} · ${card.days_evaluated || 0} dias · ${meta.trades || 0} trades · ${escapeHtml(meta.strategy || "?")}`;
  return `${stages}<div class="robust-note">${note}</div>`;
}

function renderInteractiveReports() {
  if (!state.session || !reportScopes().length) {
    els.reportsPane.style.display = "none";
    if (els.robustnessPane) els.robustnessPane.style.display = "none";
    if (els.propfirmPane) els.propfirmPane.style.display = "none";
    document.body.classList.remove("has-reports");
    return;
  }
  if (els.robustnessPane) els.robustnessPane.style.display = "";
  if (els.propfirmPane) els.propfirmPane.style.display = "";

  const activeSession = activeReportSession();
  if (!activeSession) {
    state.reportScope = "account";
    return renderInteractiveReports();
  }

  const charts = getInteractiveReportSpecs();
  els.reportsPane.style.display = "";
  document.body.classList.add("has-reports");
  els.reportsCount.textContent = String(charts.length);
  els.reportsPath.textContent = reportScopeLabel(state.reportScope);
  renderReportTabs();
  renderReportSummary();
  els.reportsGallery.innerHTML = charts.map((chart) => `
    <div class="report-card interactive" data-chart="${chart.id}" data-report-scope="${escapeHtml(state.reportScope)}">
      <div class="card-head">
        <div class="card-title">
          <button class="chart-help-btn" type="button" data-help="${chart.id}" aria-label="Explicar ${chart.title}" title="Como ler este gráfico">?</button>
          <span>${chart.title}</span>
        </div>
        <span class="filename">${chart.meta}</span>
      </div>
      <div class="card-chart">
        <canvas data-chart="${chart.id}" data-report-scope="${escapeHtml(state.reportScope)}"></canvas>
      </div>
    </div>
  `).join("");

  els.reportsGallery.querySelectorAll("canvas").forEach((canvas) => {
    const card = canvas.closest(".report-card");
    canvas.addEventListener("mousemove", (event) => {
      const rect = canvas.getBoundingClientRect();
      if (event.buttons === 1 && canvas.dataset.chart && canvas.dataset.chart.endsWith("3d")) {
        canvas.dataset.rotY = String(Number(canvas.dataset.rotY || "-32") + event.movementX * 0.8);
        canvas.dataset.rotX = String(clamp(Number(canvas.dataset.rotX || "58") - event.movementY * 0.55, 18, 82));
      }
      canvas.dataset.hoverX = String(event.clientX - rect.left);
      canvas.dataset.hoverY = String(event.clientY - rect.top);
      drawReportCanvas(canvas);
    });
    canvas.addEventListener("mouseleave", () => {
      delete canvas.dataset.hoverX;
      delete canvas.dataset.hoverY;
      hideTooltip(els.reportTooltip);
      drawReportCanvas(canvas);
    });
    card.addEventListener("click", (event) => {
      if (event.target.closest(".chart-help-btn")) return;
      openChartModal(canvas.dataset.chart);
    });
  });
  els.reportsGallery.querySelectorAll(".chart-help-btn").forEach((btn) => {
    btn.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      showChartHelp(btn.dataset.help, btn);
    });
  });
  drawReportCanvases();
  if (state.chartModal.open) drawChartModalCanvas();
}

function reportScopes() {
  if (!state.session) return [];
  const scopes = [{ id: "account", label: "Conta", session: state.session }];
  const assets = state.session.asset_sessions || {};
  Object.keys(assets).sort().forEach((symbol) => {
    scopes.push({ id: `asset:${symbol}`, label: symbol, session: assets[symbol] });
  });
  return scopes.filter((scope) => scope.session && Array.isArray(scope.session.trades));
}

function renderReportTabs() {
  if (!els.reportTabs) return;
  const scopes = reportScopes();
  els.reportTabs.hidden = scopes.length <= 1;
  if (scopes.length <= 1) {
    els.reportTabs.innerHTML = "";
    return;
  }
  els.reportTabs.innerHTML = scopes.map((scope) => {
    const trades = scope.session.trades?.length || 0;
    const active = scope.id === state.reportScope;
    return `<button type="button" class="${active ? "active" : ""}" data-report-scope="${escapeHtml(scope.id)}">${escapeHtml(scope.label)}<span>${trades}</span></button>`;
  }).join("");
}

function activeReportSession() {
  return reportSessionForScope(state.reportScope);
}

function reportSessionForScope(scopeId) {
  if (!state.session) return null;
  if (!scopeId || scopeId === "account") return state.session;
  if (scopeId.startsWith("asset:")) {
    const symbol = scopeId.slice(6);
    return state.session.asset_sessions?.[symbol] || null;
  }
  return state.session;
}

function reportScopeLabel(scopeId) {
  const session = reportSessionForScope(scopeId);
  if (!session) return "sessao atual";
  const metadata = session.metadata || {};
  if (scopeId && scopeId.startsWith("asset:")) {
    return `${metadata.symbol || scopeId.slice(6)} · ${metadata.timeframe || ""}`.trim();
  }
  return metadata.output_dir || metadata.source || "Conta consolidada";
}

function withReportSession(session, fn) {
  const previous = state.reportSessionOverride;
  state.reportSessionOverride = session || state.session;
  try {
    return fn();
  } finally {
    state.reportSessionOverride = previous;
  }
}

function reportSession() {
  return state.reportSessionOverride || activeReportSession() || state.session;
}

function wireChartModal() {
  els.chartModalCloseBtn.addEventListener("click", closeChartModal);
  els.chartModalFullscreenBtn.addEventListener("click", toggleChartModalFullscreen);
  els.chartModalViewFrontBtn.addEventListener("click", () => applyChartModalPreset("front"));
  els.chartModalViewAngleBtn.addEventListener("click", () => applyChartModalPreset("angle"));
  els.chartModalViewTopBtn.addEventListener("click", () => applyChartModalPreset("top"));
  els.chartModalViewResetBtn.addEventListener("click", () => applyChartModalPreset("reset"));
  els.chartModalBackdrop.addEventListener("click", (event) => {
    if (event.target === els.chartModalBackdrop) closeChartModal();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && state.chartModal.open) closeChartModal();
    if (!state.chartModal.open || !state.chartModal.chartId || !state.chartModal.chartId.endsWith("3d")) return;
    if (event.key === "1") applyChartModalPreset("front");
    if (event.key === "2") applyChartModalPreset("angle");
    if (event.key === "3") applyChartModalPreset("top");
    if (event.key === "0") applyChartModalPreset("reset");
  });
  els.chartModalCanvas.addEventListener("mousemove", (event) => {
    if (!state.chartModal.open) return;
    const rect = els.chartModalCanvas.getBoundingClientRect();
    if (event.buttons === 1 && state.chartModal.chartId && state.chartModal.chartId.endsWith("3d")) {
      els.chartModalCanvas.dataset.rotY = String(Number(els.chartModalCanvas.dataset.rotY || "-32") + event.movementX * 0.48);
      els.chartModalCanvas.dataset.rotX = String(clamp(Number(els.chartModalCanvas.dataset.rotX || "58") - event.movementY * 0.32, 18, 82));
      syncChartModalViewActive();
    }
    els.chartModalCanvas.dataset.hoverX = String(event.clientX - rect.left);
    els.chartModalCanvas.dataset.hoverY = String(event.clientY - rect.top);
    renderChartModal();
  });
  els.chartModalCanvas.addEventListener("wheel", (event) => {
    if (!state.chartModal.open || !state.chartModal.chartId || !state.chartModal.chartId.endsWith("3d")) return;
    event.preventDefault();
    const current = Number(els.chartModalCanvas.dataset.zoom || "1");
    const next = clamp(current + (event.deltaY < 0 ? 0.06 : -0.06), 0.72, 1.4);
    els.chartModalCanvas.dataset.zoom = String(next);
    syncChartModalViewActive();
    renderChartModal();
  }, { passive: false });
  els.chartModalCanvas.addEventListener("mouseleave", () => {
    delete els.chartModalCanvas.dataset.hoverX;
    delete els.chartModalCanvas.dataset.hoverY;
    hideTooltip(els.chartModalTooltip);
    renderChartModal();
  });
}

function openChartModal(chartId) {
  if (!chartId) return;
  state.chartModal.open = true;
  state.chartModal.chartId = chartId;
  state.chartModal.reportScope = state.reportScope || "account";
  els.chartModalTitle.textContent = getChartTitle(chartId);
  els.chartModalMeta.textContent = getChartMeta(chartId);
  els.chartModalBackdrop.classList.toggle("chart-modal-backdrop-3d", chartId.endsWith("3d"));
  if (chartId === "equity-3d") {
    setCanvasVisible(els.chartModalGlCanvas, false);
    applyChartModalPreset(els.chartModalCanvas.dataset.chartView || "angle", true);
  } else if (chartId.endsWith("3d")) {
    applyChartModalPreset(els.chartModalCanvas.dataset.chartView || "angle", true);
  } else {
    delete els.chartModalCanvas.dataset.zoom;
    delete els.chartModalCanvas.dataset.rotX;
    delete els.chartModalCanvas.dataset.rotY;
    els.chartModalCanvas.dataset.chartView = "";
    setCanvasVisible(els.chartModalGlCanvas, false);
  }
  if (els.chartModalHint) {
    els.chartModalHint.textContent = chartId.endsWith("3d")
      ? (chartId === "equity-3d" ? "1 frente · 2 ângulo · 3 topo · 0 reset · arraste e scroll" : "Arraste para girar · Scroll para zoom · ESC para fechar")
      : "Clique fora para fechar · ESC para fechar";
  }
  els.chartModalBackdrop.classList.remove("hidden");
  els.chartModalBackdrop.setAttribute("aria-hidden", "false");
  renderChartModal();
}

function closeChartModal() {
  if (!state.chartModal.open) return;
  state.chartModal.open = false;
  state.chartModal.chartId = null;
  els.chartModalBackdrop.classList.add("hidden");
  els.chartModalBackdrop.classList.remove("chart-modal-backdrop-3d");
  els.chartModalBackdrop.setAttribute("aria-hidden", "true");
  hideTooltip(els.chartModalTooltip);
  hideElement(els.chartModalGlCanvas);
}

async function toggleChartModalFullscreen() {
  if (!document.fullscreenElement) {
    await els.chartModalBackdrop.requestFullscreen?.().catch(() => {});
  } else {
    await document.exitFullscreen?.().catch(() => {});
  }
}

function drawChartModalCanvas() {
  if (!state.chartModal.open || !state.chartModal.chartId) return;
  const reportSession = reportSessionForScope(state.chartModal.reportScope);
  if (!reportSession) return;
  const rect = els.chartModalCanvas.getBoundingClientRect();
  els.chartModalCanvas.width = Math.max(1, Math.floor(rect.width * DPR));
  els.chartModalCanvas.height = Math.max(1, Math.floor(rect.height * DPR));
  const ctx = els.chartModalCanvas.getContext("2d");
  const hover = els.chartModalCanvas.dataset.hoverX !== undefined
    ? { x: Number(els.chartModalCanvas.dataset.hoverX) * DPR, y: Number(els.chartModalCanvas.dataset.hoverY) * DPR }
    : null;
  els.chartModalCanvas.dataset.hoverTrade = "";
  ctx.clearRect(0, 0, els.chartModalCanvas.width, els.chartModalCanvas.height);
  const is3d = state.chartModal.chartId.endsWith("3d");
  const zoom = is3d ? Number(els.chartModalCanvas.dataset.zoom || "1") : 1;
  if (is3d) {
    ctx.save();
    ctx.translate(els.chartModalCanvas.width * (1 - zoom) * 0.5, els.chartModalCanvas.height * (1 - zoom) * 0.48);
    ctx.scale(zoom, zoom);
  }
  const pad = scalePad(is3d ? { left: 84, right: 38, top: 28, bottom: 56 } : { left: 72, right: 30, top: 24, bottom: 44 });
  withReportSession(reportSession, () => drawChartById(ctx, els.chartModalCanvas, pad, hover, state.chartModal.chartId));
  if (is3d) ctx.restore();
}

function renderChartModal() {
  if (!state.chartModal.open || !state.chartModal.chartId) return;
  drawChartModalCanvas();
}

function setupEquity3dModal() {
  setCanvasVisible(els.chartModalGlCanvas, true);
  state.chartModal.view = state.chartModal.view || "angle";
  state.chartModal.equity3d = state.chartModal.equity3d || {
    camera: { azimuth: -0.45, elevation: 0.95, distance: 3.0 },
    scene: null,
    gl: null,
    program: null,
    buffers: null,
    metrics: null,
  };
  ensureEquity3dRenderer();
}

function ensureEquity3dRenderer() {
  const canvas = els.chartModalGlCanvas;
  const renderer = state.chartModal.equity3d || (state.chartModal.equity3d = {});
  if (!renderer.gl) {
    const gl = canvas.getContext("webgl", {
      alpha: true,
      antialias: true,
      preserveDrawingBuffer: false,
      premultipliedAlpha: false,
    }) || canvas.getContext("experimental-webgl");
    if (!gl) return null;
    renderer.gl = gl;
    const program = createEquity3dProgram(gl);
    if (!program) return null;
    renderer.program = program;
    renderer.buffers = {
      meshPos: gl.createBuffer(),
      meshNormal: gl.createBuffer(),
      meshColor: gl.createBuffer(),
      axesPos: gl.createBuffer(),
      axesColor: gl.createBuffer(),
      points: gl.createBuffer(),
    };
    gl.enable(gl.DEPTH_TEST);
    gl.disable(gl.CULL_FACE);
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
  }
  if (!renderer.scene || renderer.scene.version !== reportSession()?.equity?.length) {
    renderer.scene = buildEquity3dScene();
  }
  return renderer;
}

function buildEquity3dScene() {
  const rows = reportSession()?.equity || [];
  const trades = reportSession()?.trades || [];
  if (rows.length < 2) return { version: rows.length, mesh: null, axes: null, points: null, bounds: null };
  const initial = Number(reportSession()?.metadata?.initial_capital || rows[0][1] || rows[0][2] || 0);
  const sampled = [];
  const step = Math.max(1, Math.ceil(rows.length / 260));
  for (let i = 0; i < rows.length; i += step) sampled.push({ row: rows[i], idx: i });
  if (sampled[sampled.length - 1]?.idx !== rows.length - 1) sampled.push({ row: rows[rows.length - 1], idx: rows.length - 1 });
  const values = sampled.flatMap(({ row }) => [row[1], row[2]]);
  let [minValue, maxValue] = extent(values);
  const span = Math.max(maxValue - minValue, 1);
  minValue = Math.min(minValue, initial - span * 0.16);
  maxValue = Math.max(maxValue, initial + span * 0.16);
  const toZ = (value) => ((value - minValue) / Math.max(maxValue - minValue, 1e-9)) * 2 - 1;
  const xAt = (i) => -1 + (i / Math.max(sampled.length - 1, 1)) * 2;
  const yBalance = -0.62;
  const yEquity = 0.62;

  const mesh = { positions: [], normals: [], colors: [] };
  for (let i = 0; i < sampled.length - 1; i += 1) {
    const a = sampled[i].row;
    const b = sampled[i + 1].row;
    const x0 = xAt(i);
    const x1 = xAt(i + 1);
    const z00 = toZ(a[1]);
    const z10 = toZ(b[1]);
    const z11 = toZ(b[2]);
    const z01 = toZ(a[2]);
    const p00 = [x0, yBalance, z00];
    const p10 = [x1, yBalance, z10];
    const p11 = [x1, yEquity, z11];
    const p01 = [x0, yEquity, z01];
    const normalA = triangleNormal(p00, p10, p11);
    const normalB = triangleNormal(p00, p11, p01);
    const bullish = ((a[2] + b[2]) / 2) >= initial;
    const lowColor = bullish ? [0.96, 0.71, 0.26, 0.46] : [1.0, 0.35, 0.40, 0.48];
    const highColor = bullish ? [0.29, 0.84, 0.92, 0.98] : [1.0, 0.35, 0.40, 0.92];
    pushTriangle(mesh, p00, p10, p11, normalA, lowColor, lowColor, highColor);
    pushTriangle(mesh, p00, p11, p01, normalB, lowColor, highColor, highColor);
  }

  const axes = {
    positions: [
      ...[-1.05, 0, 0, 1.05, 0, 0],
      ...[0, -0.60, 0, 0, 0.60, 0],
      ...[0, 0, -1.10, 0, 0, 1.10],
    ],
    colors: [
      ...[0.32, 0.84, 0.92, 0.80, 0.32, 0.84, 0.92, 0.20],
      ...[0.71, 0.74, 0.79, 0.80, 0.71, 0.74, 0.79, 0.20],
      ...[1.0, 0.73, 0.30, 0.80, 1.0, 0.73, 0.30, 0.20],
    ],
  };

  const points = [];
  trades.forEach((trade) => {
    const idx = clamp(trade.exitIndex, 0, sampled.length - 1);
    const row = rows[clamp(trade.exitIndex, 0, rows.length - 1)];
    if (!row) return;
    const xi = rows.length > 1 ? (trade.exitIndex / (rows.length - 1)) : 0;
    const x = -1 + xi * 2;
    points.push(
      x, yEquity, toZ(row[2]),
      trade.pnl >= 0 ? 0.18 : 1.0,
      trade.pnl >= 0 ? 0.92 : 0.42,
      trade.pnl >= 0 ? 0.56 : 0.48,
      trade.pnl >= 0 ? 1.0 : 0.95,
    );
  });

  return {
    version: rows.length,
    mesh,
    axes,
    points,
    bounds: { minValue, maxValue, initial, yBalance, yEquity },
    sampled,
  };
}

function renderEquity3dModal() {
  const renderer = ensureEquity3dRenderer();
  if (!renderer?.gl || !renderer?.program || !renderer.scene) return;
  const bodyRect = els.chartModalCanvas.getBoundingClientRect();
  const pixelW = Math.max(1, Math.floor(bodyRect.width * DPR));
  const pixelH = Math.max(1, Math.floor(bodyRect.height * DPR));
  if (els.chartModalGlCanvas.width !== pixelW || els.chartModalGlCanvas.height !== pixelH) {
    els.chartModalGlCanvas.width = pixelW;
    els.chartModalGlCanvas.height = pixelH;
  }
  if (els.chartModalCanvas.width !== pixelW || els.chartModalCanvas.height !== pixelH) {
    els.chartModalCanvas.width = pixelW;
    els.chartModalCanvas.height = pixelH;
  }
  const gl = renderer.gl;
  gl.viewport(0, 0, pixelW, pixelH);
  gl.clearColor(0.03, 0.05, 0.08, 0.0);
  gl.clearDepth(1);
  gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);

  const camera = renderer.camera || (renderer.camera = { azimuth: -0.45, elevation: 0.95, distance: 3.0 });
  const target = [0, 0, 0];
  const eye = orbitCameraPosition(camera, target);
  const projection = mat4Perspective(45 * Math.PI / 180, pixelW / pixelH, 0.1, 20);
  const view = mat4LookAt(eye, target, [0, 1, 0]);
  const vp = mat4Multiply(projection, view);

  drawEquity3dMesh(renderer, vp, eye);
  drawEquity3dAxes(renderer, vp, pixelW, pixelH);
  drawEquity3dOverlay(renderer, vp, pixelW, pixelH);
}

function drawEquity3dMesh(renderer, vp, eye) {
  const gl = renderer.gl;
  const program = renderer.program;
  const scene = renderer.scene;
  if (!scene?.mesh?.positions?.length) return;
  gl.useProgram(program.raw);
  gl.uniform1f(program.uPointMode, 0.0);
  bindEquity3dBuffer(gl, program.aPosition, renderer.buffers.meshPos, scene.mesh.positions, 3);
  bindEquity3dBuffer(gl, program.aNormal, renderer.buffers.meshNormal, scene.mesh.normals, 3);
  bindEquity3dBuffer(gl, program.aColor, renderer.buffers.meshColor, scene.mesh.colors, 4);
  gl.uniformMatrix4fv(program.uViewProj, false, vp);
  gl.uniform3f(program.uLightDir, -0.4, 0.9, 0.55);
  gl.uniform1f(program.uFogNear, 3.0);
  gl.uniform1f(program.uFogFar, 7.8);
  gl.drawArrays(gl.TRIANGLES, 0, scene.mesh.positions.length / 3);

  if (scene.points.length) {
    gl.bindBuffer(gl.ARRAY_BUFFER, renderer.buffers.points);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(scene.points), gl.DYNAMIC_DRAW);
    gl.uniform1f(program.uPointMode, 1.0);
    gl.vertexAttribPointer(program.aPosition, 3, gl.FLOAT, false, 28, 0);
    gl.enableVertexAttribArray(program.aPosition);
    gl.vertexAttribPointer(program.aColor, 4, gl.FLOAT, false, 28, 12);
    gl.enableVertexAttribArray(program.aColor);
    gl.disableVertexAttribArray(program.aNormal);
    gl.vertexAttrib3f(program.aNormal, 0, 0, 1);
    gl.uniform1f(program.uPointSize, 7 * DPR);
    gl.drawArrays(gl.POINTS, 0, scene.points.length / 7);
  }
}

function drawEquity3dAxes(renderer, vp, pixelW, pixelH) {
  const gl = renderer.gl;
  const program = renderer.program;
  const scene = renderer.scene;
  gl.uniform1f(program.uPointMode, 0.0);
  gl.bindBuffer(gl.ARRAY_BUFFER, renderer.buffers.axesPos);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(scene.axes.positions), gl.DYNAMIC_DRAW);
  gl.vertexAttribPointer(program.aPosition, 3, gl.FLOAT, false, 0, 0);
  gl.enableVertexAttribArray(program.aPosition);
  gl.bindBuffer(gl.ARRAY_BUFFER, renderer.buffers.axesColor);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(scene.axes.colors), gl.DYNAMIC_DRAW);
  gl.vertexAttribPointer(program.aColor, 4, gl.FLOAT, false, 0, 0);
  gl.enableVertexAttribArray(program.aColor);
  gl.disableVertexAttribArray(program.aNormal);
  gl.vertexAttrib3f(program.aNormal, 0, 0, 1);
  gl.uniformMatrix4fv(program.uViewProj, false, vp);
  gl.uniform1f(program.uFogNear, 5.8);
  gl.uniform1f(program.uFogFar, 10.0);
  gl.drawArrays(gl.LINES, 0, scene.axes.positions.length / 3);
}

function drawEquity3dOverlay(renderer, vp, pixelW, pixelH) {
  const canvas = els.chartModalCanvas;
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, pixelW, pixelH);
  const scene = renderer.scene;
  if (!scene?.bounds) return;
  const origin = project3dToScreen(vp, [0, 0, 0], pixelW, pixelH);
  const xAxis = project3dToScreen(vp, [1.05, 0, 0], pixelW, pixelH);
  const yAxis = project3dToScreen(vp, [0, 0.60, 0], pixelW, pixelH);
  const zAxis = project3dToScreen(vp, [0, 0, 1.10], pixelW, pixelH);
  ctx.save();
  ctx.lineWidth = 1.2 * DPR;
  ctx.strokeStyle = "rgba(233,238,244,0.10)";
  ctx.beginPath();
  ctx.moveTo(origin.x, origin.y);
  ctx.lineTo(xAxis.x, xAxis.y);
  ctx.stroke();
  ctx.strokeStyle = "rgba(183,138,255,0.22)";
  ctx.beginPath();
  ctx.moveTo(origin.x, origin.y);
  ctx.lineTo(yAxis.x, yAxis.y);
  ctx.stroke();
  ctx.strokeStyle = "rgba(74,214,230,0.22)";
  ctx.beginPath();
  ctx.moveTo(origin.x, origin.y);
  ctx.lineTo(zAxis.x, zAxis.y);
  ctx.stroke();
  ctx.fillStyle = COLORS.axisText;
  ctx.font = `${10 * DPR}px ${FONT_MONO}`;
  ctx.fillText("Tempo", xAxis.x + 8 * DPR, xAxis.y);
  ctx.fillText("Faixa", yAxis.x + 8 * DPR, yAxis.y);
  ctx.fillText("Saldo", zAxis.x + 8 * DPR, zAxis.y);
  ctx.fillStyle = "rgba(233,238,244,0.82)";
  ctx.font = `${12 * DPR}px ${FONT_MONO}`;
  ctx.fillText(`Initial ${money(scene.bounds.initial)}`, 18 * DPR, 26 * DPR);
  ctx.fillText(`Z: equity premium`, 18 * DPR, 44 * DPR);
  ctx.fillStyle = COLORS.axisText;
  ctx.font = `${10 * DPR}px ${FONT_MONO}`;
  ctx.fillText(`Drag · rotate  |  Wheel · zoom  |  1/2/3/0 presets`, 18 * DPR, pixelH - 18 * DPR);
  ctx.restore();
}

function createEquity3dProgram(gl) {
  const vsSource = `
    attribute vec3 aPosition;
    attribute vec3 aNormal;
    attribute vec4 aColor;
    uniform mat4 uViewProj;
    uniform float uPointMode;
    uniform float uPointSize;
    varying vec4 vColor;
    varying vec3 vNormal;
    varying float vDepth;
    void main() {
      if (uPointMode > 0.5) {
        vColor = aColor;
        vNormal = vec3(0.0, 0.0, 1.0);
        gl_PointSize = uPointSize;
      } else {
        vColor = aColor;
        vNormal = aNormal;
        gl_PointSize = 1.0;
      }
      vec4 clip = uViewProj * vec4(aPosition, 1.0);
      gl_Position = clip;
      vDepth = clip.z / clip.w;
    }
  `;
  const fsSource = `
    precision mediump float;
    varying vec4 vColor;
    varying vec3 vNormal;
    varying float vDepth;
    uniform vec3 uLightDir;
    uniform float uFogNear;
    uniform float uFogFar;
    void main() {
      float facing = abs(dot(normalize(vNormal), normalize(uLightDir)));
      float light = 0.58 + facing * 0.42;
      float fog = clamp((uFogFar - abs(vDepth)) / max(uFogFar - uFogNear, 0.0001), 0.0, 1.0);
      vec3 color = min(vColor.rgb * light + vColor.rgb * 0.12, vec3(1.0));
      gl_FragColor = vec4(color, vColor.a * fog);
    }
  `;
  const program = linkEquity3dProgram(gl, vsSource, fsSource);
  if (!program) return null;
  return {
    raw: program,
    aPosition: gl.getAttribLocation(program, "aPosition"),
    aNormal: gl.getAttribLocation(program, "aNormal"),
    aColor: gl.getAttribLocation(program, "aColor"),
    uViewProj: gl.getUniformLocation(program, "uViewProj"),
    uPointMode: gl.getUniformLocation(program, "uPointMode"),
    uLightDir: gl.getUniformLocation(program, "uLightDir"),
    uFogNear: gl.getUniformLocation(program, "uFogNear"),
    uFogFar: gl.getUniformLocation(program, "uFogFar"),
    uEye: gl.getUniformLocation(program, "uEye"),
    uPointSize: gl.getUniformLocation(program, "uPointSize"),
  };
}

function linkEquity3dProgram(gl, vsSource, fsSource) {
  const vs = gl.createShader(gl.VERTEX_SHADER);
  gl.shaderSource(vs, vsSource);
  gl.compileShader(vs);
  if (!gl.getShaderParameter(vs, gl.COMPILE_STATUS)) return null;
  const fs = gl.createShader(gl.FRAGMENT_SHADER);
  gl.shaderSource(fs, fsSource);
  gl.compileShader(fs);
  if (!gl.getShaderParameter(fs, gl.COMPILE_STATUS)) return null;
  const program = gl.createProgram();
  gl.attachShader(program, vs);
  gl.attachShader(program, fs);
  gl.linkProgram(program);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) return null;
  return program;
}

function bindEquity3dBuffer(gl, attribLocation, buffer, values, size) {
  if (attribLocation < 0) return;
  gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(values), gl.DYNAMIC_DRAW);
  gl.vertexAttribPointer(attribLocation, size, gl.FLOAT, false, 0, 0);
  gl.enableVertexAttribArray(attribLocation);
}

function pushTriangle(mesh, p0, p1, p2, normal, c0, c1, c2) {
  mesh.positions.push(...p0, ...p1, ...p2);
  mesh.normals.push(...normal, ...normal, ...normal);
  mesh.colors.push(...c0, ...c1, ...c2);
}

function triangleNormal(a, b, c) {
  const ab = [b[0] - a[0], b[1] - a[1], b[2] - a[2]];
  const ac = [c[0] - a[0], c[1] - a[1], c[2] - a[2]];
  const n = cross3(ab, ac);
  return normalize3(n);
}

function cross3(a, b) {
  return [
    a[1] * b[2] - a[2] * b[1],
    a[2] * b[0] - a[0] * b[2],
    a[0] * b[1] - a[1] * b[0],
  ];
}

function normalize3(v) {
  const len = Math.hypot(v[0], v[1], v[2]) || 1;
  return [v[0] / len, v[1] / len, v[2] / len];
}

function mat4Identity() {
  return [1, 0, 0, 0,
          0, 1, 0, 0,
          0, 0, 1, 0,
          0, 0, 0, 1];
}

function mat4Multiply(a, b) {
  const out = new Array(16);
  const a00 = a[0], a01 = a[4], a02 = a[8], a03 = a[12];
  const a10 = a[1], a11 = a[5], a12 = a[9], a13 = a[13];
  const a20 = a[2], a21 = a[6], a22 = a[10], a23 = a[14];
  const a30 = a[3], a31 = a[7], a32 = a[11], a33 = a[15];

  let b0; let b1; let b2; let b3;

  b0 = b[0]; b1 = b[1]; b2 = b[2]; b3 = b[3];
  out[0] = a00 * b0 + a01 * b1 + a02 * b2 + a03 * b3;
  out[1] = a10 * b0 + a11 * b1 + a12 * b2 + a13 * b3;
  out[2] = a20 * b0 + a21 * b1 + a22 * b2 + a23 * b3;
  out[3] = a30 * b0 + a31 * b1 + a32 * b2 + a33 * b3;

  b0 = b[4]; b1 = b[5]; b2 = b[6]; b3 = b[7];
  out[4] = a00 * b0 + a01 * b1 + a02 * b2 + a03 * b3;
  out[5] = a10 * b0 + a11 * b1 + a12 * b2 + a13 * b3;
  out[6] = a20 * b0 + a21 * b1 + a22 * b2 + a23 * b3;
  out[7] = a30 * b0 + a31 * b1 + a32 * b2 + a33 * b3;

  b0 = b[8]; b1 = b[9]; b2 = b[10]; b3 = b[11];
  out[8] = a00 * b0 + a01 * b1 + a02 * b2 + a03 * b3;
  out[9] = a10 * b0 + a11 * b1 + a12 * b2 + a13 * b3;
  out[10] = a20 * b0 + a21 * b1 + a22 * b2 + a23 * b3;
  out[11] = a30 * b0 + a31 * b1 + a32 * b2 + a33 * b3;

  b0 = b[12]; b1 = b[13]; b2 = b[14]; b3 = b[15];
  out[12] = a00 * b0 + a01 * b1 + a02 * b2 + a03 * b3;
  out[13] = a10 * b0 + a11 * b1 + a12 * b2 + a13 * b3;
  out[14] = a20 * b0 + a21 * b1 + a22 * b2 + a23 * b3;
  out[15] = a30 * b0 + a31 * b1 + a32 * b2 + a33 * b3;

  return out;
}

function mat4Perspective(fovy, aspect, near, far) {
  const f = 1 / Math.tan(fovy / 2);
  const nf = 1 / (near - far);
  return [
    f / aspect, 0, 0, 0,
    0, f, 0, 0,
    0, 0, (far + near) * nf, -1,
    0, 0, (2 * far * near) * nf, 0,
  ];
}

function mat4LookAt(eye, target, up) {
  const zAxis = normalize3([eye[0] - target[0], eye[1] - target[1], eye[2] - target[2]]);
  const xAxis = normalize3(cross3(up, zAxis));
  const yAxis = cross3(zAxis, xAxis);
  return [
    xAxis[0], xAxis[1], xAxis[2], 0,
    yAxis[0], yAxis[1], yAxis[2], 0,
    zAxis[0], zAxis[1], zAxis[2], 0,
    -dot3(xAxis, eye), -dot3(yAxis, eye), -dot3(zAxis, eye), 1,
  ];
}

function dot3(a, b) {
  return a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
}

function orbitCameraPosition(camera, target) {
  const az = camera.azimuth;
  const el = camera.elevation;
  const d = camera.distance;
  return [
    target[0] + d * Math.cos(el) * Math.sin(az),
    target[1] + d * Math.sin(el),
    target[2] + d * Math.cos(el) * Math.cos(az),
  ];
}

function project3dToScreen(vp, point, width, height) {
  const clip = multiplyMat4Vec4(vp, [point[0], point[1], point[2], 1]);
  const w = clip[3] || 1;
  const ndcX = clip[0] / w;
  const ndcY = clip[1] / w;
  return {
    x: ((ndcX + 1) / 2) * width,
    y: ((1 - ndcY) / 2) * height,
  };
}

function multiplyMat4Vec4(m, v) {
  return [
    m[0] * v[0] + m[4] * v[1] + m[8] * v[2] + m[12] * v[3],
    m[1] * v[0] + m[5] * v[1] + m[9] * v[2] + m[13] * v[3],
    m[2] * v[0] + m[6] * v[1] + m[10] * v[2] + m[14] * v[3],
    m[3] * v[0] + m[7] * v[1] + m[11] * v[2] + m[15] * v[3],
  ];
}

function applyChartModalPreset(preset, silent = false) {
  if (!state.chartModal.open || !state.chartModal.chartId || !state.chartModal.chartId.endsWith("3d")) return;
  const current = preset || "angle";
  const presets = {
    front: { rotX: -58, rotY: 0, zoom: 1.0 },
    angle: { rotX: -62, rotY: -34, zoom: 1.0 },
    top: { rotX: -22, rotY: -30, zoom: 0.96 },
    reset: { rotX: -58, rotY: -32, zoom: 1.0 },
  };
  const view = presets[current] || presets.angle;
  els.chartModalCanvas.dataset.rotX = String(view.rotX);
  els.chartModalCanvas.dataset.rotY = String(view.rotY);
  els.chartModalCanvas.dataset.zoom = String(view.zoom);
  els.chartModalCanvas.dataset.chartView = current;
  syncChartModalViewActive();
  if (!silent) drawChartModalCanvas();
}

function syncChartModalViewActive() {
  if (!els.chartModalViewset) return;
  const active = state.chartModal.view || els.chartModalCanvas.dataset.chartView || "angle";
  els.chartModalViewset.querySelectorAll(".chart-modal-view-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.id === `chartModalView${capitalize(active)}Btn`);
  });
}

function capitalize(value) {
  return value ? value.charAt(0).toUpperCase() + value.slice(1) : value;
}

function drawChartById(ctx, canvas, pad, hover, chartId) {
  if (chartId === "equity-full") drawReportLineChart(ctx, canvas, pad, hover, "equity");
  if (chartId === "equity-3d") drawEquity3dChart(ctx, canvas, pad, hover);
  if (chartId === "drawdown-full") drawReportLineChart(ctx, canvas, pad, hover, "drawdown");
  if (chartId === "z-sharp") drawZSharpChart(ctx, canvas, pad, hover);
  if (chartId === "drawdown-monthly") drawMonthlyDrawdownChart(ctx, canvas, pad, hover);
  if (chartId === "histograms") drawHistogramsChart(ctx, canvas, pad, hover);
  if (chartId === "trade-pnl") drawTradePnlChart(ctx, canvas, pad, hover);
  if (chartId === "monthly-pnl") drawMonthlyPnlChart(ctx, canvas, pad, hover);
  if (chartId === "profit-factor-month") drawProfitFactorMonthChart(ctx, canvas, pad, hover);
  if (chartId === "yearly-pnl") drawYearlyPnlChart(ctx, canvas, pad, hover);
  if (chartId === "best-worst") drawBestWorstChart(ctx, canvas, pad, hover);
  if (chartId === "boxplot-weekday") drawBoxplotChart(ctx, canvas, pad, hover, "weekday");
  if (chartId === "boxplot-hour") drawBoxplotChart(ctx, canvas, pad, hover, "hour");
  if (chartId === "monte-carlo-shuffle") drawMonteCarloEquity(ctx, canvas, pad, hover, "shuffle");
  if (chartId === "monte-carlo-bootstrap") drawMonteCarloEquity(ctx, canvas, pad, hover, "bootstrap");
  if (chartId === "monte-carlo-block-bootstrap") drawMonteCarloEquity(ctx, canvas, pad, hover, "block_bootstrap");
  if (chartId === "monte-carlo-distribution") drawMonteCarloDistribution(ctx, canvas, pad, hover);
  if (chartId === "r-multiples") drawRMultiplesChart(ctx, canvas, pad, hover);
  if (chartId === "volatility-pnl") drawVolatilityPnlChart(ctx, canvas, pad, hover);
  if (chartId === "atr-volume-price") drawAtrVolumePriceChart(ctx, canvas, pad, hover);
  if (chartId === "rolling-performance") drawRollingPerformanceChart(ctx, canvas, pad, hover);
  if (chartId === "risk-exposure") drawRiskExposureChart(ctx, canvas, pad, hover);
  if (chartId === "regime-surface-3d") drawRegimeSurface3d(ctx, canvas, pad, hover);
  if (chartId === "trade-efficiency-3d") drawTradeEfficiency3d(ctx, canvas, pad, hover);
  if (chartId === "heatmap-hour") drawHourlyHeatmap(ctx, canvas, pad, hover);
  if (chartId === "scatter-relations") drawScatterRelationsChart(ctx, canvas, pad, hover);
}

function getChartTitle(chartId) {
  const chart = getInteractiveReportSpecs().find((item) => item.id === chartId);
  return chart ? chart.title : "Grafico";
}

function getChartMeta(chartId) {
  const chart = getInteractiveReportSpecs().find((item) => item.id === chartId);
  return chart ? chart.meta : "—";
}

async function exportSessionHtml() {
  if (!state.session) return;
  const button = els.exportReportBtn;
  const original = button.textContent;
  button.disabled = true;
  button.textContent = "Exportando...";
  try {
    const response = await fetch("/api/session/export");
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const blob = await response.blob();
    const disposition = response.headers.get("Content-Disposition") || "";
    const match = disposition.match(/filename="([^"]+)"/i);
    const filename = match ? match[1] : `dashboard_export_${Date.now()}.html`;
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1500);
  } catch (error) {
    console.error("Falha ao exportar HTML:", error);
    button.textContent = "Erro ao exportar";
    setTimeout(() => {
      button.textContent = original;
    }, 1500);
    return;
  } finally {
    button.disabled = false;
    button.textContent = original;
  }
}

function renderReportSummary() {
  const session = reportSession();
  const { metrics = {}, trades = [], risk_metrics, benchmark } = session || {};
  if (!trades.length) {
    els.reportsSummary.innerHTML = `
      <div><span>Escopo</span><strong>${escapeHtml(session?.metadata?.symbol || "Sem trades")}</strong></div>
      <div><span>Trades</span><strong>0</strong></div>
      <div><span>Net</span><strong>—</strong></div>
      <div><span>Win Rate</span><strong>—</strong></div>
      <div><span>Profit Factor</span><strong>—</strong></div>
    `;
    return;
  }
  const best = trades.reduce((acc, trade) => trade.pnl > acc.pnl ? trade : acc, trades[0]);
  const worst = trades.reduce((acc, trade) => trade.pnl < acc.pnl ? trade : acc, trades[0]);
  const insights = reportInsights();
  const rm = risk_metrics || {};
  const bm = benchmark || {};
  const fmtRisk = (v) => v != null ? v.toFixed(3) : "—";
  const fmtPctRisk = (v) => v != null ? (v * 100).toFixed(2) + "%" : "—";
  els.reportsSummary.innerHTML = `
    <div><span>Net</span><strong class="${metrics.net_profit >= 0 ? "up" : "down"}">${signedMoney(metrics.net_profit)}</strong></div>
    <div><span>Profit Factor</span><strong>${(metrics.profit_factor || 0).toFixed(2)}</strong></div>
    <div><span>Win Rate</span><strong>${pct(metrics.win_rate)}</strong></div>
    <div><span>Melhor Trade</span><strong class="up">${signedMoney(best.pnl)}</strong></div>
    <div><span>Pior Trade</span><strong class="down">${signedMoney(worst.pnl)}</strong></div>
    <div><span>Expectancy</span><strong class="${(metrics.expectancy || 0) >= 0 ? "up" : "down"}">${signedMoney(metrics.expectancy || 0)}</strong></div>
    <div><span>Recovery</span><strong>${insights.recovery.toFixed(2)}</strong></div>
    <div><span>Max Loss Streak</span><strong class="down">${insights.maxLossStreak}</strong></div>
    <div><span>VaR 5%</span><strong class="down">${signedMoney(insights.var5)}</strong></div>
    <div><span>CVaR 5%</span><strong class="down">${signedMoney(insights.cvar5)}</strong></div>
    <div><span>Sortino</span><strong>${fmtRisk(rm.sortino)}</strong></div>
    <div><span>Calmar</span><strong>${fmtRisk(rm.calmar)}</strong></div>
    <div><span>Ulcer Index</span><strong>${fmtRisk(rm.ulcer_index)}</strong></div>
    <div><span>Tail Ratio</span><strong>${fmtRisk(rm.tail_ratio)}</strong></div>
    <div><span>Gain/Pain</span><strong>${fmtRisk(rm.gain_to_pain)}</strong></div>
    <div><span>VaR 95%</span><strong class="down">${fmtPctRisk(rm.var_95)}</strong></div>
    <div><span>CVaR 95%</span><strong class="down">${fmtPctRisk(rm.cvar_95)}</strong></div>
    <div><span>Max Underwater</span><strong class="down">${rm.tuw_max_tuw != null ? rm.tuw_max_tuw + " trades" : "—"}</strong></div>
    <div><span>Buy&Hold Net</span><strong class="${(bm.net_profit || 0) >= 0 ? "up" : "down"}">${bm.net_profit != null ? signedMoney(bm.net_profit) : "—"}</strong></div>
    <div><span>Buy&Hold Return</span><strong>${bm.net_return_pct != null ? bm.net_return_pct.toFixed(2) + "%" : "—"}</strong></div>
  `;
}

function getInteractiveReportSpecs() {
  return [
    { id: "equity-full", title: "Equity Total", meta: "linha" },
    { id: "equity-3d", title: "Equity 3D", meta: "tempo x balance x equity" },
    { id: "drawdown-full", title: "Drawdown Curve", meta: "area" },
    { id: "z-sharp", title: "Z-Sharp", meta: "close z-score" },
    { id: "drawdown-monthly", title: "Drawdown Mensal", meta: "barras" },
    { id: "histograms", title: "Histogramas", meta: "distribuicoes" },
    { id: "heatmap-hour", title: "Heatmap Hora x Dia", meta: "heatmap" },
    { id: "scatter-relations", title: "Scatter MFE / MAE / Duracao", meta: "scatter" },
    { id: "monthly-pnl", title: "Lucro Mensal", meta: "barras" },
    { id: "profit-factor-month", title: "Profit Factor por Mes", meta: "barras" },
    { id: "yearly-pnl", title: "Lucro Anual", meta: "barras" },
    { id: "best-worst", title: "Melhores x Piores Trades", meta: "ranking" },
    { id: "boxplot-weekday", title: "Boxplot por Dia", meta: "boxplot" },
    { id: "boxplot-hour", title: "Boxplot por Hora", meta: "boxplot" },
    { id: "monte-carlo-shuffle", title: "Monte Carlo Shuffle", meta: "permuta trades" },
    { id: "monte-carlo-bootstrap", title: "Monte Carlo Bootstrap", meta: "reposicao" },
    { id: "monte-carlo-block-bootstrap", title: "Monte Carlo Block Bootstrap", meta: "blocos" },
    { id: "monte-carlo-distribution", title: "Monte Carlo Distribuicao", meta: "comparativo final" },
    { id: "r-multiples", title: "R-Multiples", meta: "histograma" },
    { id: "volatility-pnl", title: "Volatilidade x PnL", meta: "scatter" },
    { id: "atr-volume-price", title: "ATR / Volume / Preco", meta: "multi-eixo" },
    { id: "rolling-performance", title: "Performance Rolante", meta: "janela 20 trades" },
    { id: "risk-exposure", title: "Risco / Exposicao", meta: "timeline" },
    { id: "regime-surface-3d", title: "Regime Surface 3D", meta: "ATR x trend x edge" },
    { id: "trade-efficiency-3d", title: "Trade Efficiency 3D", meta: "MAE x MFE x PnL" },
  ];
}

const CHART_HELP = {
  "equity-full": {
    read: "Compare a linha de equity com o balance. Equity reage ao P/L aberto; balance muda apenas quando trades fecham.",
    tells: "Mostra a progressão real da conta, estabilidade da curva e momentos em que a estratégia ficou exposta antes de fechar posições.",
    watch: "Boa leitura: subida gradual com quedas curtas. Atenção: longos platôs, quedas verticais ou equity muito abaixo do balance."
  },
  "equity-3d": {
    read: "Mostra o mesmo fluxo da conta em uma ribbon 3D: tempo no eixo horizontal, balance e equity como faixas paralelas e o valor como altura.",
    tells: "Deixa mais fácil ver aceleração, desaceleração e a distância entre balance e equity sem perder o contexto temporal.",
    watch: "Se a fita afinar demais ou afundar muito, o sistema está ficando mais exposto ou mais instável."
  },
  "drawdown-full": {
    read: "A área vermelha mede quanto a conta caiu a partir do último pico.",
    tells: "Mostra profundidade e duração das perdas. Para um quant, drawdown é o preço psicológico e financeiro da estratégia.",
    watch: "Piora quando os vales ficam mais fundos ou demoram muito para recuperar."
  },
  "z-sharp": {
    read: "Mostra o fechamento padronizado em z-score contra uma janela móvel. Zero é a média; +2 e -2 marcam extremos comuns de atenção.",
    tells: "Ajuda a enxergar quando o preço está esticado demais em relação ao comportamento recente, algo útil para filtros de entrada e reversão à média.",
    watch: "Passar muito tempo acima de +2 ou abaixo de -2 pode indicar tendência forte ou um regime fora da faixa normal."
  },
  "drawdown-monthly": {
    read: "Cada barra mostra o pior drawdown observado dentro daquele mês.",
    tells: "Ajuda a separar um mês ruim isolado de uma degradação recorrente.",
    watch: "Meses consecutivos com drawdown crescente indicam regime adverso ou perda de edge."
  },
  "histograms": {
    read: "Mostra distribuição de PnL, R-multiple e duração dos trades.",
    tells: "Revela se o resultado vem de muitos pequenos ganhos, poucos outliers ou caudas negativas perigosas.",
    watch: "Cauda esquerda longa e frequente costuma ser mais preocupante que win rate baixo."
  },
  "heatmap-hour": {
    read: "Cruza dia da semana com hora de saída; verde é PnL médio positivo e vermelho negativo.",
    tells: "Mostra janelas operacionais onde a estratégia tende a funcionar ou falhar.",
    watch: "Procure clusters consistentes, não células isoladas com poucos trades."
  },
  "scatter-relations": {
    read: "Compara MFE, MAE e duração contra PnL em três painéis.",
    tells: "Ajuda a entender eficiência do trade: quanto sofre, quanto anda a favor e quanto tempo leva.",
    watch: "Perdedores com MFE alto indicam saída tardia. Vencedores com MAE alto indicam entrada antecipada ou stop largo."
  },
  "monthly-pnl": {
    read: "Soma o PnL líquido por mês.",
    tells: "Mostra consistência temporal e dependência de poucos períodos.",
    watch: "Um único mês carregando todo o lucro reduz robustez."
  },
  "profit-factor-month": {
    read: "Profit factor mensal: ganhos brutos divididos pelas perdas brutas.",
    tells: "Mostra qualidade do payoff mês a mês, não apenas lucro absoluto.",
    watch: "PF abaixo de 1 por vários meses sugere edge instável."
  },
  "yearly-pnl": {
    read: "Agrega o PnL por ano.",
    tells: "Mostra se o comportamento sobrevive a blocos longos de mercado.",
    watch: "Poucos anos lucrativos e muitos neutros/negativos pedem walk-forward."
  },
  "best-worst": {
    read: "Lista os maiores ganhos e perdas individuais.",
    tells: "Mostra dependência de outliers e assimetria de risco.",
    watch: "Se os piores trades são muito maiores que os melhores, o sizing/stop precisa revisão."
  },
  "boxplot-weekday": {
    read: "Resume a distribuição de PnL por dia da semana: mediana, quartis e extremos.",
    tells: "Mostra dias com edge mais limpo ou dispersão perigosa.",
    watch: "Mediana positiva com caixa estreita é melhor que média positiva com dispersão enorme."
  },
  "boxplot-hour": {
    read: "Resume a distribuição de PnL por hora.",
    tells: "Ajuda a detectar horários de execução favoráveis e horários ruidosos.",
    watch: "Horas com muitos outliers negativos podem merecer filtro operacional."
  },
  "monte-carlo-shuffle": {
    read: "Permuta a ordem dos mesmos trades sem alterar o conjunto de resultados.",
    tells: "Mede risco de trajetória puro: quanto a ordem dos trades afeta a experiência de drawdown e crescimento.",
    watch: "Se os caminhos abrirem demais, a estratégia depende muito da sequência em que ganha e perde."
  },
  "monte-carlo-bootstrap": {
    read: "Sorteia trades com reposição, repetindo alguns e omitindo outros em cada simulação.",
    tells: "Testa robustez da amostra e quão sensível o sistema é a depender demais de poucos trades fortes.",
    watch: "Distribuição muito espalhada aqui sugere que o backtest pode estar apoiado em uma amostra frágil."
  },
  "monte-carlo-block-bootstrap": {
    read: "Reamostra blocos consecutivos de trades, preservando pedaços de regime em vez de quebrar tudo em trades isolados.",
    tells: "É melhor para avaliar estratégias que mudam de comportamento em clusters de mercado.",
    watch: "Se este teste piora muito frente ao shuffle, existe dependência relevante de regime ou autocorrelação."
  },
  "monte-carlo-distribution": {
    read: "Compara as distribuições finais dos diferentes métodos Monte Carlo em um único painel.",
    tells: "Ajuda a ver rápido qual variante abre mais risco e qual método a estratégia tolera melhor.",
    watch: "Caudas esquerdas longas em bootstrap, blocos ou stress pedem mais cuidado do que um shuffle benigno."
  },
  "r-multiples": {
    read: "Distribui o resultado dos trades em unidades de risco.",
    tells: "Normaliza o desempenho independente do tamanho monetário do trade.",
    watch: "Muitos trades abaixo de -1R ou poucos acima de +1R indicam assimetria ruim."
  },
  "volatility-pnl": {
    read: "Relaciona volatilidade/ATR na entrada com PnL final.",
    tells: "Mostra se a estratégia prefere mercado calmo, volátil ou algum meio-termo.",
    watch: "Se a maioria dos pontos negativos aparece em alta volatilidade, um filtro de regime pode ajudar."
  },
  "atr-volume-price": {
    read: "Mostra preço, ATR e volume ao longo do tempo no mesmo painel.",
    tells: "Ajuda a contextualizar perdas e ganhos dentro de expansão de range, compressão e atividade.",
    watch: "Mudanças bruscas de ATR/volume perto de perdas podem indicar regime que a estratégia não tolera."
  },
  "rolling-performance": {
    read: "Calcula métricas em janela móvel de 20 trades.",
    tells: "Mostra deterioração ou melhora recente antes que apareça no resultado total.",
    watch: "Queda conjunta de win rate, PF e expectancy é sinal forte de regime adverso."
  },
  "risk-exposure": {
    read: "Mostra margem usada, posições abertas e drawdown ao longo do tempo.",
    tells: "Expõe se o risco vem de trades individuais ou de acúmulo de posições.",
    watch: "Drawdown crescendo junto com exposição indica risco estrutural."
  },
  "regime-surface-3d": {
    read: "Cruza volatilidade medida por ATR, força de tendência e expectancy média.",
    tells: "Mostra em quais regimes a estratégia tem edge positivo ou negativo.",
    watch: "Use para decidir filtros de entrada: evitar regiões vermelhas e privilegiar clusters verdes com amostra suficiente."
  },
  "trade-efficiency-3d": {
    read: "Cruza MAE, MFE e PnL em 3D. Arraste para girar.",
    tells: "Mostra a qualidade da trajetória dos trades, não só o resultado final.",
    watch: "Bons trades com MAE baixo e MFE alto são eficientes. Perdedores com MFE alto sugerem saída ruim."
  }
};

function showChartHelp(chartId, button) {
  const help = CHART_HELP[chartId];
  if (!help || !els.chartHelpPopover) return;
  const title = button.closest(".card-head")?.querySelector(".card-title span")?.textContent || "Grafico";
  const card = button.closest(".report-card");
  els.chartHelpPopover.innerHTML = `
    <div class="chart-help-head">
      <strong>${title}</strong>
      <button type="button" class="chart-help-close" aria-label="Fechar">×</button>
    </div>
    <div class="chart-help-body">
      <div><span>Como ler</span><p>${help.read}</p></div>
      <div><span>O que diz</span><p>${help.tells}</p></div>
      <div><span>Sinal de atenção</span><p>${help.watch}</p></div>
    </div>
  `;
  card.appendChild(els.chartHelpPopover);
  els.chartHelpPopover.classList.add("visible");
  els.chartHelpPopover.querySelector(".chart-help-close").addEventListener("click", (event) => {
    event.stopPropagation();
    closeChartHelp();
  });
}

function closeChartHelp() {
  if (els.chartHelpPopover) els.chartHelpPopover.classList.remove("visible");
}

function drawReportCanvases() {
  if (!els.reportsGallery) return;
  els.reportsGallery.querySelectorAll("canvas").forEach((canvas) => drawReportCanvas(canvas));
}

function drawReportCanvas(canvas) {
  const scopedSession = reportSessionForScope(canvas.dataset.reportScope || state.reportScope);
  if (!scopedSession) return;
  const rect = canvas.getBoundingClientRect();
  canvas.width = Math.max(1, Math.floor(rect.width * DPR));
  canvas.height = Math.max(1, Math.floor(rect.height * DPR));
  const ctx = canvas.getContext("2d");
  const chartId = canvas.dataset.chart;
  const hover = canvas.dataset.hoverX !== undefined
    ? { x: Number(canvas.dataset.hoverX) * DPR, y: Number(canvas.dataset.hoverY) * DPR }
    : null;
  canvas.dataset.hoverTrade = "";
  if (hover) hideTooltip(els.reportTooltip);
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  const pad = scalePad({ left: 54, right: 22, top: 18, bottom: 32 });
  withReportSession(scopedSession, () => {
    if (chartId === "equity-full") drawReportLineChart(ctx, canvas, pad, hover, "equity");
    if (chartId === "equity-3d") drawEquity3dChart(ctx, canvas, pad, hover);
    if (chartId === "drawdown-full") drawReportLineChart(ctx, canvas, pad, hover, "drawdown");
    if (chartId === "z-sharp") drawZSharpChart(ctx, canvas, pad, hover);
    if (chartId === "drawdown-monthly") drawMonthlyDrawdownChart(ctx, canvas, pad, hover);
    if (chartId === "histograms") drawHistogramsChart(ctx, canvas, pad, hover);
    if (chartId === "trade-pnl") drawTradePnlChart(ctx, canvas, pad, hover);
    if (chartId === "monthly-pnl") drawMonthlyPnlChart(ctx, canvas, pad, hover);
    if (chartId === "profit-factor-month") drawProfitFactorMonthChart(ctx, canvas, pad, hover);
    if (chartId === "yearly-pnl") drawYearlyPnlChart(ctx, canvas, pad, hover);
    if (chartId === "best-worst") drawBestWorstChart(ctx, canvas, pad, hover);
    if (chartId === "boxplot-weekday") drawBoxplotChart(ctx, canvas, pad, hover, "weekday");
    if (chartId === "boxplot-hour") drawBoxplotChart(ctx, canvas, pad, hover, "hour");
    if (chartId === "monte-carlo-shuffle") drawMonteCarloEquity(ctx, canvas, pad, hover, "shuffle");
    if (chartId === "monte-carlo-bootstrap") drawMonteCarloEquity(ctx, canvas, pad, hover, "bootstrap");
    if (chartId === "monte-carlo-block-bootstrap") drawMonteCarloEquity(ctx, canvas, pad, hover, "block_bootstrap");
    if (chartId === "monte-carlo-distribution") drawMonteCarloDistribution(ctx, canvas, pad, hover);
    if (chartId === "r-multiples") drawRMultiplesChart(ctx, canvas, pad, hover);
    if (chartId === "volatility-pnl") drawVolatilityPnlChart(ctx, canvas, pad, hover);
    if (chartId === "atr-volume-price") drawAtrVolumePriceChart(ctx, canvas, pad, hover);
    if (chartId === "rolling-performance") drawRollingPerformanceChart(ctx, canvas, pad, hover);
    if (chartId === "risk-exposure") drawRiskExposureChart(ctx, canvas, pad, hover);
    if (chartId === "regime-surface-3d") drawRegimeSurface3d(ctx, canvas, pad, hover);
    if (chartId === "trade-efficiency-3d") drawTradeEfficiency3d(ctx, canvas, pad, hover);
    if (chartId === "heatmap-hour") drawHourlyHeatmap(ctx, canvas, pad, hover);
    if (chartId === "scatter-relations") drawScatterRelationsChart(ctx, canvas, pad, hover);
  });
}

function chartPlot(canvas, pad) {
  return {
    w: canvas.width,
    h: canvas.height,
    x: pad.left,
    y: pad.top,
    width: canvas.width - pad.left - pad.right,
    height: canvas.height - pad.top - pad.bottom,
  };
}

function drawReportBackground(ctx, plot) {
  ctx.fillStyle = "#0b1118";
  ctx.fillRect(0, 0, plot.w, plot.h);
  ctx.strokeStyle = COLORS.bgGrid;
  ctx.lineWidth = 1 * DPR;
  for (let i = 0; i <= 4; i += 1) {
    const y = plot.y + (plot.height / 4) * i;
    ctx.beginPath();
    ctx.moveTo(plot.x, y);
    ctx.lineTo(plot.x + plot.width, y);
    ctx.stroke();
  }
}

function drawReportLineChart(ctx, canvas, pad, hover, mode) {
  const rows = reportSession().equity || [];
  const plot = chartPlot(canvas, pad);
  drawReportBackground(ctx, plot);
  if (!rows.length) return;
  const values = [];
  rows.forEach((row) => {
    if (mode === "drawdown") values.push(row[5]);
    else values.push(row[1], row[2]);
  });
  let [min, max] = extent(values);
  if (mode === "drawdown") max = Math.max(max, 0);
  const span = Math.max(max - min, 1);
  min -= span * 0.08;
  max += span * 0.08;
  const xAt = (i) => plot.x + (i / Math.max(rows.length - 1, 1)) * plot.width;
  const yAt = (v) => plot.y + ((max - v) / (max - min)) * plot.height;

  drawReportYAxis(ctx, plot, min, max, yAt, mode === "drawdown" ? pct : money);
  if (mode === "drawdown") {
    drawReportAreaLine(ctx, rows, xAt, (row) => yAt(row[5]), COLORS.drawdown, COLORS.drawdownLine);
  } else {
    drawReportSeries(ctx, rows, xAt, (row) => yAt(row[1]), COLORS.balance, 1.4);
    drawReportSeries(ctx, rows, xAt, (row) => yAt(row[2]), COLORS.equity, 1.8);
  }

  if (hover) {
    const idx = clamp(Math.round(((hover.x - plot.x) / plot.width) * (rows.length - 1)), 0, rows.length - 1);
    const row = rows[idx];
    const x = xAt(idx);
    drawReportCursor(ctx, plot, x);
    showReportTooltip(canvas, hover, `
      <div class="tooltip-row"><span class="label">Tempo</span><span class="value">${fmtTime(row[0])}</span></div>
      <div class="tooltip-separator"></div>
      ${mode === "drawdown"
        ? `<div class="tooltip-row"><span class="label">Drawdown</span><span class="value down">${pct(row[5])}</span></div>`
        : `<div class="tooltip-row"><span class="label">Balance</span><span class="value">${money(row[1])}</span></div>
           <div class="tooltip-row"><span class="label">Equity</span><span class="value">${money(row[2])}</span></div>`}
    `);
  }
}

function computeZSharpSeries(candles, period = 20) {
  const closes = candles.map((row) => Number(row[4]));
  const series = new Array(closes.length).fill(null);
  for (let i = period - 1; i < closes.length; i += 1) {
    let sum = 0;
    let sumSquares = 0;
    for (let j = i - period + 1; j <= i; j += 1) {
      const value = closes[j];
      sum += value;
      sumSquares += value * value;
    }
    const mean = sum / period;
    const variance = Math.max(0, (sumSquares / period) - (mean * mean));
    const std = Math.sqrt(variance);
    series[i] = std > 0 ? (closes[i] - mean) / std : 0;
  }
  return series;
}

function smoothSeries(values, span = 40) {
  const alpha = 2 / (span + 1);
  const out = new Array(values.length).fill(null);
  let ema = null;
  values.forEach((value, index) => {
    if (!Number.isFinite(value)) {
      out[index] = null;
      return;
    }
    ema = ema === null ? value : alpha * value + (1 - alpha) * ema;
    out[index] = ema;
  });
  return out;
}

function drawZSharpChart(ctx, canvas, pad, hover) {
  const candles = reportSession().candles || [];
  const plot = chartPlot(canvas, pad);
  drawReportBackground(ctx, plot);
  if (!candles.length) return;

  const zSeries = computeZSharpSeries(candles, 20);
  const zSmooth = smoothSeries(zSeries, Math.max(20, Math.round(candles.length / 60)));
  const min = -3.5;
  const max = 3.5;

  const xAt = (i) => plot.x + (i / Math.max(candles.length - 1, 1)) * plot.width;
  const yAt = (value) => plot.y + ((max - value) / (max - min)) * plot.height;
  const rawRows = zSeries.map((value) => [value]);
  const smoothRows = zSmooth.map((value) => [value]);

  drawReportYAxis(ctx, plot, min, max, yAt, (value) => value.toFixed(2));
  drawReportXAxis(ctx, plot, 0, candles.length - 1, (value) => fmtTimeShort(candles[clamp(Math.round(value), 0, candles.length - 1)][0]));
  drawHorizontalLine(ctx, plot.x, plot.x + plot.width, yAt(2), "rgba(43,212,127,0.26)", 1 * DPR, [4 * DPR, 4 * DPR]);
  drawHorizontalLine(ctx, plot.x, plot.x + plot.width, yAt(1), "rgba(74,214,230,0.16)", 1 * DPR, [2 * DPR, 4 * DPR]);
  drawHorizontalLine(ctx, plot.x, plot.x + plot.width, yAt(0), "rgba(181,192,207,0.35)", 1 * DPR, []);
  drawHorizontalLine(ctx, plot.x, plot.x + plot.width, yAt(-1), "rgba(74,214,230,0.16)", 1 * DPR, [2 * DPR, 4 * DPR]);
  drawHorizontalLine(ctx, plot.x, plot.x + plot.width, yAt(-2), "rgba(255,88,103,0.26)", 1 * DPR, [4 * DPR, 4 * DPR]);
  ctx.save();
  ctx.beginPath();
  ctx.moveTo(xAt(0), yAt(0));
  smoothRows.forEach((row, i) => {
    const y = yAt(Number.isFinite(row[0]) ? row[0] : 0);
    if (i === 0) ctx.lineTo(xAt(i), y);
    else ctx.lineTo(xAt(i), y);
  });
  ctx.lineTo(xAt(smoothRows.length - 1), yAt(0));
  ctx.closePath();
  ctx.fillStyle = "rgba(74,214,230,0.22)";
  ctx.fill();
  ctx.restore();
  ctx.save();
  ctx.strokeStyle = "rgba(74,214,230,0.24)";
  ctx.lineWidth = 5 * DPR;
  ctx.lineJoin = "round";
  ctx.lineCap = "round";
  ctx.shadowColor = "rgba(74,214,230,0.25)";
  ctx.shadowBlur = 10 * DPR;
  ctx.beginPath();
  smoothRows.forEach((row, i) => {
    const y = yAt(Number.isFinite(row[0]) ? row[0] : 0);
    if (i === 0) ctx.moveTo(xAt(i), y);
    else ctx.lineTo(xAt(i), y);
  });
  ctx.stroke();
  ctx.restore();
  ctx.save();
  ctx.strokeStyle = "rgba(74,214,230,1)";
  ctx.lineWidth = 2.4 * DPR;
  ctx.lineJoin = "round";
  ctx.lineCap = "round";
  ctx.shadowColor = "rgba(74,214,230,0.52)";
  ctx.shadowBlur = 8 * DPR;
  ctx.beginPath();
  smoothRows.forEach((row, i) => {
    const value = Number.isFinite(row[0]) ? row[0] : 0;
    const x = xAt(i);
    const y = yAt(value);
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();
  ctx.restore();
  ctx.save();
  ctx.strokeStyle = "rgba(74,214,230,0.02)";
  ctx.lineWidth = 0.8 * DPR;
  ctx.lineJoin = "round";
  ctx.lineCap = "round";
  ctx.beginPath();
  rawRows.forEach((row, i) => {
    const value = Number.isFinite(row[0]) ? row[0] : 0;
    const x = xAt(i);
    const y = yAt(value);
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();
  ctx.restore();

  ctx.fillStyle = COLORS.axisText;
  ctx.font = `${10 * DPR}px ${FONT_MONO}`;
  ctx.textAlign = "left";
  ctx.textBaseline = "top";
  ctx.fillText("Z-Sharp = (close - média móvel) / desvio-padrão", plot.x, plot.y - 14 * DPR);

  if (hover) {
    const idx = clamp(Math.round(((hover.x - plot.x) / plot.width) * (candles.length - 1)), 0, candles.length - 1);
    const rawValue = zSeries[idx];
    const smoothValue = zSmooth[idx];
    if (Number.isFinite(smoothValue)) {
      showReportTooltip(canvas, hover, `
        <div class="tooltip-row"><span class="label">Time</span><span class="value">${fmtTime(candles[idx][0])}</span></div>
        <div class="tooltip-row"><span class="label">Close</span><span class="value">${price(candles[idx][4])}</span></div>
        <div class="tooltip-row"><span class="label">Z-Sharp suave</span><span class="value ${smoothValue >= 0 ? "up" : "down"}">${smoothValue.toFixed(2)}</span></div>
        <div class="tooltip-row"><span class="label">Z-Sharp bruto</span><span class="value ${rawValue >= 0 ? "up" : "down"}">${Number.isFinite(rawValue) ? rawValue.toFixed(2) : "—"}</span></div>
      `);
    }
  }
}

function drawTradePnlChart(ctx, canvas, pad, hover) {
  const trades = reportSession().trades || [];
  const plot = chartPlot(canvas, pad);
  drawReportBackground(ctx, plot);
  if (!trades.length) return;
  const maxAbs = maxAbsValue(trades.map((trade) => trade.pnl)) * 1.1;
  const yAt = (v) => plot.y + ((maxAbs - v) / (maxAbs * 2)) * plot.height;
  const zeroY = yAt(0);
  drawReportYAxis(ctx, plot, -maxAbs, maxAbs, yAt, money);
  drawZeroLine(ctx, plot, zeroY);
  const bw = Math.max(1 * DPR, plot.width / trades.length);
  let hoverTrade = null;
  trades.forEach((trade, i) => {
    const x = plot.x + i * bw;
    const h = Math.abs(yAt(trade.pnl) - zeroY);
    ctx.fillStyle = trade.pnl >= 0 ? COLORS.buy : COLORS.sell;
    ctx.fillRect(x, Math.min(yAt(trade.pnl), zeroY), Math.max(1 * DPR, bw - 1 * DPR), Math.max(1 * DPR, h));
    if (hover && hover.x >= x && hover.x <= x + bw && hover.y >= plot.y && hover.y <= plot.y + plot.height) {
      hoverTrade = trade;
    }
  });
  if (hoverTrade) {
    canvas.dataset.hoverTrade = String(hoverTrade.id);
    showTradeTooltip(canvas, hover, hoverTrade);
  }
}

function drawMonthlyPnlChart(ctx, canvas, pad, hover) {
  const data = monthlyPnl();
  const plot = chartPlot(canvas, pad);
  drawReportBackground(ctx, plot);
  if (!data.length) return;
  const maxAbs = maxAbsValue(data.map((item) => item.pnl)) * 1.1;
  const yAt = (v) => plot.y + ((maxAbs - v) / (maxAbs * 2)) * plot.height;
  const zeroY = yAt(0);
  drawReportYAxis(ctx, plot, -maxAbs, maxAbs, yAt, money);
  drawZeroLine(ctx, plot, zeroY);
  const gap = 5 * DPR;
  const bw = Math.max(12 * DPR, (plot.width - gap * (data.length - 1)) / data.length);
  let hit = null;
  data.forEach((item, i) => {
    const x = plot.x + i * (bw + gap);
    const h = Math.abs(yAt(item.pnl) - zeroY);
    ctx.fillStyle = item.pnl >= 0 ? COLORS.buy : COLORS.sell;
    ctx.fillRect(x, Math.min(yAt(item.pnl), zeroY), bw, Math.max(1 * DPR, h));
    ctx.fillStyle = COLORS.axisText;
    ctx.font = `${9 * DPR}px ${FONT_MONO}`;
    ctx.textAlign = "center";
    ctx.fillText(item.label, x + bw / 2, plot.y + plot.height + 18 * DPR);
    if (hover && hover.x >= x && hover.x <= x + bw && hover.y >= plot.y && hover.y <= plot.y + plot.height) hit = item;
  });
  if (hit) {
    showReportTooltip(canvas, hover, `
      <div class="tooltip-row"><span class="label">Mes</span><span class="value">${hit.label}</span></div>
      <div class="tooltip-row"><span class="label">PnL</span><span class="value ${hit.pnl >= 0 ? "up" : "down"}">${signedMoney(hit.pnl)}</span></div>
      <div class="tooltip-row"><span class="label">Trades</span><span class="value">${hit.count}</span></div>
    `);
  }
}

function drawMonthlyDrawdownChart(ctx, canvas, pad, hover) {
  const groups = groupedEquityByMonth();
  const plot = chartPlot(canvas, pad);
  drawReportBackground(ctx, plot);
  if (!groups.length) return;
  const min = Math.min(-1, ...groups.map((item) => item.dd));
  const max = 0;
  const yAt = (v) => plot.y + ((max - v) / (max - min)) * plot.height;
  drawReportYAxis(ctx, plot, min, max, yAt, pct);
  drawZeroLine(ctx, plot, yAt(0));
  drawCategoryBars(ctx, canvas, plot, groups, (item) => item.dd, yAt, pct, hover, (item) => `
    <div class="tooltip-row"><span class="label">Mes</span><span class="value">${item.label}</span></div>
    <div class="tooltip-row"><span class="label">Max DD</span><span class="value down">${pct(item.dd)}</span></div>
  `);
}

function drawHistogramsChart(ctx, canvas, pad, hover) {
  const trades = reportSession().trades || [];
  const plot = chartPlot(canvas, pad);
  drawReportBackground(ctx, plot);
  const panes = splitPlot(plot, 3);
  drawHistogramPane(ctx, canvas, panes[0], trades.map((t) => t.pnl), "PnL", money, hover);
  drawHistogramPane(ctx, canvas, panes[1], trades.map((t) => t.riskReward).filter((v) => Number.isFinite(v)), "R", (v) => `${v.toFixed(2)}R`, hover);
  drawHistogramPane(ctx, canvas, panes[2], trades.map((t) => t.durationMinutes || 0), "Min", (v) => `${Math.round(v)}m`, hover);
}

function drawProfitFactorMonthChart(ctx, canvas, pad, hover) {
  const data = monthlyProfitFactor();
  const plot = chartPlot(canvas, pad);
  drawReportBackground(ctx, plot);
  if (!data.length) return;
  const max = Math.max(1, ...data.map((item) => item.pf || 0)) * 1.15;
  const yAt = (v) => plot.y + ((max - v) / max) * plot.height;
  drawReportYAxis(ctx, plot, 0, max, yAt, (v) => v.toFixed(2));
  drawCategoryBars(ctx, canvas, plot, data, (item) => item.pf || 0, yAt, (v) => v.toFixed(2), hover, (item) => `
    <div class="tooltip-row"><span class="label">Mes</span><span class="value">${item.label}</span></div>
    <div class="tooltip-row"><span class="label">PF</span><span class="value">${item.pf === null ? "—" : item.pf.toFixed(2)}</span></div>
    <div class="tooltip-row"><span class="label">Trades</span><span class="value">${item.count}</span></div>
  `, 0);
}

function drawYearlyPnlChart(ctx, canvas, pad, hover) {
  const data = groupedPnl("year");
  const plot = chartPlot(canvas, pad);
  drawReportBackground(ctx, plot);
  if (!data.length) return;
  const maxAbs = maxAbsValue(data.map((item) => item.pnl)) * 1.1;
  const yAt = (v) => plot.y + ((maxAbs - v) / (maxAbs * 2)) * plot.height;
  drawReportYAxis(ctx, plot, -maxAbs, maxAbs, yAt, money);
  drawZeroLine(ctx, plot, yAt(0));
  drawCategoryBars(ctx, canvas, plot, data, (item) => item.pnl, yAt, money, hover, (item) => `
    <div class="tooltip-row"><span class="label">Ano</span><span class="value">${item.label}</span></div>
    <div class="tooltip-row"><span class="label">PnL</span><span class="value ${item.pnl >= 0 ? "up" : "down"}">${signedMoney(item.pnl)}</span></div>
    <div class="tooltip-row"><span class="label">Trades</span><span class="value">${item.count}</span></div>
  `);
}

function drawBestWorstChart(ctx, canvas, pad, hover) {
  const trades = [...(reportSession().trades || [])];
  const plot = chartPlot(canvas, pad);
  drawReportBackground(ctx, plot);
  if (!trades.length) return;
  const top = 8;
  const best = [...trades].sort((a, b) => b.pnl - a.pnl).slice(0, top);
  const worst = [...trades].sort((a, b) => a.pnl - b.pnl).slice(0, top).reverse();
  const data = [...worst, ...best].map((trade) => ({ trade, label: `#${trade.id}`, pnl: trade.pnl }));
  const maxAbs = maxAbsValue(data.map((item) => item.pnl)) * 1.1;
  const yAt = (v) => plot.y + ((maxAbs - v) / (maxAbs * 2)) * plot.height;
  drawReportYAxis(ctx, plot, -maxAbs, maxAbs, yAt, money);
  drawZeroLine(ctx, plot, yAt(0));
  const hit = drawCategoryBars(ctx, canvas, plot, data, (item) => item.pnl, yAt, money, hover, null);
  if (hit) {
    canvas.dataset.hoverTrade = String(hit.trade.id);
    showTradeTooltip(canvas, hover, hit.trade);
  }
}

function drawBoxplotChart(ctx, canvas, pad, hover, mode) {
  const groups = groupedTradeValues(mode);
  const plot = chartPlot(canvas, pad);
  drawReportBackground(ctx, plot);
  const values = groups.flatMap((group) => group.values);
  if (!values.length) return;
  let [min, max] = extent(values);
  const span = Math.max(max - min, 1);
  min -= span * 0.1;
  max += span * 0.1;
  const yAt = (v) => plot.y + ((max - v) / (max - min)) * plot.height;
  drawReportYAxis(ctx, plot, min, max, yAt, money);
  const slot = plot.width / groups.length;
  let hit = null;
  groups.forEach((group, i) => {
    const x = plot.x + i * slot + slot / 2;
    const stats = quantiles(group.values);
    if (!stats) return;
    ctx.strokeStyle = COLORS.axisStrong;
    ctx.lineWidth = 1.2 * DPR;
    ctx.beginPath();
    ctx.moveTo(x, yAt(stats.min));
    ctx.lineTo(x, yAt(stats.max));
    ctx.stroke();
    const boxW = Math.max(8 * DPR, slot * 0.45);
    const q1 = yAt(stats.q1);
    const q3 = yAt(stats.q3);
    ctx.fillStyle = group.avg >= 0 ? "rgba(43,212,127,0.28)" : "rgba(255,88,103,0.28)";
    ctx.strokeStyle = group.avg >= 0 ? COLORS.buy : COLORS.sell;
    ctx.fillRect(x - boxW / 2, Math.min(q1, q3), boxW, Math.max(2 * DPR, Math.abs(q3 - q1)));
    ctx.strokeRect(x - boxW / 2, Math.min(q1, q3), boxW, Math.max(2 * DPR, Math.abs(q3 - q1)));
    drawSmallLine(ctx, x - boxW / 2, x + boxW / 2, yAt(stats.median), COLORS.axisStrong);
    if (hover && hover.x >= x - slot / 2 && hover.x <= x + slot / 2 && hover.y >= plot.y && hover.y <= plot.y + plot.height) hit = { group, stats };
    ctx.fillStyle = COLORS.axisText;
    ctx.font = `${9 * DPR}px ${FONT_MONO}`;
    ctx.textAlign = "center";
    ctx.fillText(group.label, x, plot.y + plot.height + 8 * DPR);
  });
  if (hit) {
    showReportTooltip(canvas, hover, `
      <div class="tooltip-row"><span class="label">${mode === "hour" ? "Hora" : "Dia"}</span><span class="value">${hit.group.label}</span></div>
      <div class="tooltip-row"><span class="label">Mediana</span><span class="value">${signedMoney(hit.stats.median)}</span></div>
      <div class="tooltip-row"><span class="label">Q1 / Q3</span><span class="value">${money(hit.stats.q1)} / ${money(hit.stats.q3)}</span></div>
      <div class="tooltip-row"><span class="label">Trades</span><span class="value">${hit.group.values.length}</span></div>
    `);
  }
}

function drawMonteCarloEquity(ctx, canvas, pad, hover, mode) {
  const paths = monteCarloPaths(mode, 60);
  const plot = chartPlot(canvas, pad);
  drawReportBackground(ctx, plot);
  if (!paths.length) return;
  const values = paths.flat();
  let [min, max] = extent(values);
  const span = Math.max(max - min, 1);
  min -= span * 0.08;
  max += span * 0.08;
  const xAt = (i, len) => plot.x + (i / Math.max(len - 1, 1)) * plot.width;
  const yAt = (v) => plot.y + ((max - v) / (max - min)) * plot.height;
  drawReportYAxis(ctx, plot, min, max, yAt, money);
  paths.forEach((path, i) => {
    drawReportSeries(ctx, path.map((value) => [value]), (idx) => xAt(idx, path.length), (row) => yAt(row[0]), i === 0 ? COLORS.equity : "rgba(74,214,230,0.13)", i === 0 ? 2.0 : 0.8);
  });
}

function drawMonteCarloDistribution(ctx, canvas, pad, hover) {
  const modes = [
    { key: "shuffle", color: COLORS.equity, label: "Shuffle" },
    { key: "bootstrap", color: COLORS.buy, label: "Bootstrap" },
    { key: "block_bootstrap", color: COLORS.violet, label: "Block" },
    { key: "execution_stress", color: COLORS.sell, label: "Stress" },
  ];
  const plot = chartPlot(canvas, pad);
  drawReportBackground(ctx, plot);
  const series = modes.map((mode) => ({
    ...mode,
    values: monteCarloPaths(mode.key, 220).map((path) => path[path.length - 1]),
  })).filter((item) => item.values.length);
  if (!series.length) return;

  const allValues = series.flatMap((item) => item.values);
  const bins = histogramBins(allValues, 20);
  if (!bins.length) return;
  const maxCount = Math.max(
    1,
    ...series.flatMap((item) => histogramBins(item.values, 20).map((bin) => bin.count)),
  );
  const min = bins[0].a;
  const max = bins[bins.length - 1].b;
  const xAt = (v) => plot.x + ((v - min) / Math.max(max - min, 1e-9)) * plot.width;
  const yAt = (v) => plot.y + plot.height - (v / maxCount) * plot.height;
  drawReportYAxis(ctx, plot, 0, maxCount, yAt, (v) => String(Math.round(v)));
  drawReportXAxis(ctx, plot, min, max, money);

  const binWidth = plot.width / bins.length;
  series.forEach((item) => {
    const itemBins = histogramBins(item.values, 20);
    ctx.strokeStyle = item.color;
    ctx.lineWidth = 1.5 * DPR;
    ctx.beginPath();
    itemBins.forEach((bin, index) => {
      const x = plot.x + index * binWidth + binWidth / 2;
      const y = yAt(bin.count);
      if (index === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();
  });

  ctx.font = `${10 * DPR}px ${FONT_MONO}`;
  ctx.textAlign = "left";
  ctx.textBaseline = "top";
  series.forEach((item, index) => {
    ctx.fillStyle = item.color;
    ctx.fillText(item.label, plot.x + index * 92 * DPR, plot.y + 8 * DPR);
  });
}

function drawRMultiplesChart(ctx, canvas, pad, hover) {
  const values = (reportSession().trades || []).map((t) => t.riskReward).filter((v) => Number.isFinite(v) && v !== 0);
  const plot = chartPlot(canvas, pad);
  drawReportBackground(ctx, plot);
  drawHistogramPane(ctx, canvas, plot, values, "R", (v) => `${v.toFixed(2)}R`, hover, COLORS.violet);
}

function drawVolatilityPnlChart(ctx, canvas, pad, hover) {
  const atr = computeAtrSeries(14);
  const points = (reportSession().trades || []).map((trade) => ({
    trade,
    x: atr[trade.entryIndex] || 0,
    y: trade.pnl,
  })).filter((p) => p.x > 0);
  drawGenericScatter(ctx, canvas, pad, hover, points, "ATR", (v) => price(v), true);
}

function drawAtrVolumePriceChart(ctx, canvas, pad, hover) {
  const candles = reportSession().candles || [];
  const atr = computeAtrSeries(14);
  const plot = chartPlot(canvas, pad);
  drawReportBackground(ctx, plot);
  if (!candles.length) return;
  const step = Math.max(1, Math.ceil(candles.length / 700));
  const sampled = candles.filter((_, i) => i % step === 0).map((c, i) => ({ candle: c, atr: atr[i * step] || 0 }));
  const prices = sampled.map((p) => p.candle[4]);
  let [minP, maxP] = extent(prices);
  const priceSpan = Math.max(maxP - minP, 1e-8);
  minP -= priceSpan * 0.08;
  maxP += priceSpan * 0.08;
  const maxAtr = maxAbsValue(sampled.map((p) => p.atr));
  const maxVol = maxAbsValue(sampled.map((p) => p.candle[5]));
  const xAt = (i) => plot.x + (i / Math.max(sampled.length - 1, 1)) * plot.width;
  const yPrice = (v) => plot.y + ((maxP - v) / (maxP - minP)) * plot.height;
  const yAtr = (v) => plot.y + plot.height - (v / maxAtr) * plot.height * 0.4;
  drawReportYAxis(ctx, plot, minP, maxP, yPrice, price);
  sampled.forEach((point, i) => {
    const x = xAt(i);
    const volH = (point.candle[5] / maxVol) * plot.height * 0.22;
    ctx.fillStyle = "rgba(255,181,71,0.16)";
    ctx.fillRect(x, plot.y + plot.height - volH, Math.max(1, plot.width / sampled.length), volH);
  });
  drawReportSeries(ctx, sampled, xAt, (row) => yPrice(row.candle[4]), COLORS.equity, 1.6);
  drawReportSeries(ctx, sampled, xAt, (row) => yAtr(row.atr), COLORS.violet, 1.2);
  if (hover) {
    const idx = clamp(Math.round(((hover.x - plot.x) / plot.width) * (sampled.length - 1)), 0, sampled.length - 1);
    const point = sampled[idx];
    drawReportCursor(ctx, plot, xAt(idx));
    showReportTooltip(canvas, hover, `
      <div class="tooltip-row"><span class="label">Tempo</span><span class="value">${fmtTime(point.candle[0])}</span></div>
      <div class="tooltip-row"><span class="label">Preco</span><span class="value">${price(point.candle[4])}</span></div>
      <div class="tooltip-row"><span class="label">ATR</span><span class="value">${price(point.atr)}</span></div>
      <div class="tooltip-row"><span class="label">Volume</span><span class="value">${compact(point.candle[5])}</span></div>
    `);
  }
}

function drawMonteCarloDistribution3d(ctx, canvas, pad, hover) {
  const finals = monteCarloPaths(260).map((path) => path[path.length - 1]);
  const plot = chartPlot(canvas, pad);
  drawReportBackground(ctx, plot);
  const bins = histogramBins(finals, 18);
  const points = [];
  bins.forEach((bin, i) => {
    for (let z = 0; z < Math.max(1, bin.count); z += 1) {
      points.push({
        x: i / Math.max(bins.length - 1, 1),
        y: z / Math.max(...bins.map((b) => b.count), 1),
        z: 0.15 + (bin.mid - bins[0].mid) / Math.max(bins[bins.length - 1].mid - bins[0].mid, 1),
        value: bin.mid,
        count: bin.count,
      });
    }
  });
  draw3dBars(ctx, canvas, plot, points, hover, {
    xLabel: "Faixa",
    yLabel: "Qtd",
    zLabel: "Final",
    tooltip: (p) => `
      <div class="tooltip-row"><span class="label">Final</span><span class="value">${money(p.value)}</span></div>
      <div class="tooltip-row"><span class="label">Qtd</span><span class="value">${p.count}</span></div>
    `,
  });
}

function drawAtrVolumePrice3d(ctx, canvas, pad, hover) {
  const candles = reportSession().candles || [];
  const atr = computeAtrSeries(14);
  const plot = chartPlot(canvas, pad);
  drawReportBackground(ctx, plot);
  if (!candles.length) return;
  const step = Math.max(1, Math.ceil(candles.length / 180));
  const sampled = candles.filter((_, i) => i % step === 0).map((c, i) => ({ candle: c, atr: atr[i * step] || 0 }));
  const prices = sampled.map((p) => p.candle[4]);
  const volumes = sampled.map((p) => p.candle[5]);
  const atrs = sampled.map((p) => p.atr);
  const [minP, maxP] = extent(prices);
  const maxVol = maxAbsValue(volumes);
  const maxAtr = maxAbsValue(atrs);
  const points = sampled.map((p, i) => ({
    x: i / Math.max(sampled.length - 1, 1),
    y: (p.candle[5] || 0) / maxVol,
    z: (p.atr || 0) / maxAtr,
    priceValue: p.candle[4],
    time: p.candle[0],
    volume: p.candle[5],
    atr: p.atr,
    colorValue: (p.candle[4] - minP) / Math.max(maxP - minP, 1e-9),
  }));
  draw3dScatter(ctx, canvas, plot, points, hover, {
    xLabel: "Tempo",
    yLabel: "Volume",
    zLabel: "ATR",
    tooltip: (p) => `
      <div class="tooltip-row"><span class="label">Tempo</span><span class="value">${fmtTime(p.time)}</span></div>
      <div class="tooltip-row"><span class="label">Preco</span><span class="value">${price(p.priceValue)}</span></div>
      <div class="tooltip-row"><span class="label">ATR</span><span class="value">${price(p.atr)}</span></div>
      <div class="tooltip-row"><span class="label">Volume</span><span class="value">${compact(p.volume)}</span></div>
    `,
  });
}

function drawEquity3dChart(ctx, canvas, pad, hover) {
  const rows = reportSession().equity || [];
  const plot = chartPlot(canvas, pad);
  drawReportBackground(ctx, plot);
  if (rows.length < 2) return;

  const initial = Number(reportSession().metadata?.initial_capital || rows[0][1] || rows[0][2] || 0);
  const limit = canvas.closest(".chart-modal-body") ? 260 : 180;
  const step = Math.max(1, Math.ceil(rows.length / limit));
  const sampled = [];
  for (let i = 0; i < rows.length; i += step) {
    sampled.push({ row: rows[i], idx: i });
  }
  if (sampled[sampled.length - 1]?.idx !== rows.length - 1) {
    sampled.push({ row: rows[rows.length - 1], idx: rows.length - 1 });
  }
  const values = sampled.flatMap(({ row }) => [row[1], row[2]]);
  let [min, max] = extent(values);
  const span = Math.max(max - min, 1);
  min = Math.min(min, initial - span * 0.12);
  max = Math.max(max, initial + span * 0.18);
  min -= span * 0.06;
  max += span * 0.12;

  const project = makeProjector(canvas, plot);
  const xOf = (i) => i / Math.max(sampled.length - 1, 1);
  const zOf = (value) => (value - min) / Math.max(max - min, 1e-9);
  const balanceLane = 0.14;
  const equityLane = 0.88;

  draw3dAxes(ctx, plot, project, {
    xLabel: "Tempo",
    yLabel: "Fita",
    zLabel: "Saldo",
  });

  const ribbons = [];
  for (let i = 0; i < sampled.length - 1; i += 1) {
    const a = sampled[i];
    const b = sampled[i + 1];
    const quad = [
      { x: xOf(i), y: balanceLane, z: zOf(a.row[1]) },
      { x: xOf(i + 1), y: balanceLane, z: zOf(b.row[1]) },
      { x: xOf(i + 1), y: equityLane, z: zOf(b.row[2]) },
      { x: xOf(i), y: equityLane, z: zOf(a.row[2]) },
    ];
    const screens = quad.map((point) => project(point));
    const depth = screens.reduce((sum, point) => sum + point.depth, 0) / screens.length;
    const avgBalance = (a.row[1] + b.row[1]) / 2;
    const avgEquity = (a.row[2] + b.row[2]) / 2;
    ribbons.push({ quad, screens, depth, avgBalance, avgEquity });
  }

  ribbons.sort((left, right) => left.depth - right.depth);
  ribbons.forEach((ribbon) => {
    const gain = ribbon.avgEquity - initial;
    const bullish = gain >= 0;
    const fillAlpha = clamp(Math.abs(gain) / Math.max(span * 1.8, 1), 0.06, 0.28);
    const startColor = bullish ? `rgba(255,181,71,${0.10 + fillAlpha * 0.35})` : `rgba(255,88,103,${0.10 + fillAlpha * 0.35})`;
    const endColor = bullish ? `rgba(74,214,230,${0.18 + fillAlpha * 0.55})` : `rgba(255,88,103,${0.18 + fillAlpha * 0.55})`;
    const gradient = ctx.createLinearGradient(
      ribbon.screens[0].x, ribbon.screens[0].y,
      ribbon.screens[2].x, ribbon.screens[2].y,
    );
    gradient.addColorStop(0, startColor);
    gradient.addColorStop(1, endColor);
    ctx.save();
    ctx.shadowColor = bullish ? "rgba(74,214,230,0.20)" : "rgba(255,88,103,0.18)";
    ctx.shadowBlur = 18 * DPR;
    ctx.fillStyle = gradient;
    ctx.beginPath();
    ctx.moveTo(ribbon.screens[0].x, ribbon.screens[0].y);
    for (let i = 1; i < ribbon.screens.length; i += 1) {
      ctx.lineTo(ribbon.screens[i].x, ribbon.screens[i].y);
    }
    ctx.closePath();
    ctx.fill();
    ctx.shadowBlur = 0;
    ctx.strokeStyle = "rgba(233,238,244,0.08)";
    ctx.lineWidth = 1 * DPR;
    ctx.stroke();
    ctx.restore();
  });

  draw3dPolyline(ctx, project, sampled.map((item, i) => ({
    x: xOf(i),
    y: balanceLane,
    z: zOf(item.row[1]),
  })), COLORS.balance, 2.0 * DPR, "rgba(255,181,71,0.38)");
  draw3dPolyline(ctx, project, sampled.map((item, i) => ({
    x: xOf(i),
    y: equityLane,
    z: zOf(item.row[2]),
  })), COLORS.equity, 2.4 * DPR, "rgba(74,214,230,0.40)");

  draw3dPolyline(ctx, project, sampled.map((item, i) => ({
    x: xOf(i),
    y: 0.50,
    z: zOf(initial),
  })), COLORS.initialLine, 1.1 * DPR, "rgba(110,125,143,0.28)");

  drawLegendInline(ctx, plot, [
    ["Balance", COLORS.balance],
    ["Equity", COLORS.equity],
    ["Initial", COLORS.initialLine],
  ]);

  let hit = null;
  if (hover) {
    sampled.forEach((item, i) => {
      const balancePoint = project({ x: xOf(i), y: balanceLane, z: zOf(item.row[1]) });
      const equityPoint = project({ x: xOf(i), y: equityLane, z: zOf(item.row[2]) });
      const balanceDistance = Math.hypot(hover.x - balancePoint.x, hover.y - balancePoint.y);
      const equityDistance = Math.hypot(hover.x - equityPoint.x, hover.y - equityPoint.y);
      const candidate = balanceDistance < equityDistance
        ? { distance: balanceDistance, point: balancePoint, row: item.row }
        : { distance: equityDistance, point: equityPoint, row: item.row };
      if (candidate.distance < 12 * DPR && (!hit || candidate.distance < hit.distance)) {
        hit = candidate;
      }
    });
  }

  (reportSession().trades || []).forEach((trade) => {
    if (trade.exitIndex < 0 || trade.exitIndex >= rows.length) return;
    const row = rows[trade.exitIndex];
    const x = trade.exitIndex / Math.max(rows.length - 1, 1);
    const point = project({ x, y: equityLane, z: zOf(row[2]) });
    ctx.save();
    ctx.fillStyle = trade.pnl >= 0 ? "rgba(43,212,127,0.96)" : "rgba(255,88,103,0.96)";
    ctx.shadowColor = trade.pnl >= 0 ? "rgba(43,212,127,0.42)" : "rgba(255,88,103,0.42)";
    ctx.shadowBlur = 12 * DPR;
    ctx.beginPath();
    ctx.arc(point.x, point.y, 2.4 * DPR, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
  });

  draw3dHint(ctx, plot, canvas);
  if (hit) {
    showReportTooltip(canvas, hover, `
      <div class="tooltip-row"><span class="label">Tempo</span><span class="value">${fmtTime(hit.row[0])}</span></div>
      <div class="tooltip-separator"></div>
      <div class="tooltip-row"><span class="label">Balance</span><span class="value">${money(hit.row[1])}</span></div>
      <div class="tooltip-row"><span class="label">Equity</span><span class="value">${money(hit.row[2])}</span></div>
      <div class="tooltip-row"><span class="label">Open PnL</span><span class="value ${hit.row[3] >= 0 ? "up" : "down"}">${signedMoney(hit.row[3])}</span></div>
      <div class="tooltip-row"><span class="label">Drawdown</span><span class="value down">${pct(hit.row[5])}</span></div>
    `);
  }
}

function draw3dPolyline(ctx, project, points, color, width, glowColor = color) {
  const screens = points.map((point) => project(point));
  if (screens.length < 2) return;
  ctx.save();
  ctx.lineJoin = "round";
  ctx.lineCap = "round";
  ctx.strokeStyle = glowColor;
  ctx.globalAlpha = 0.32;
  ctx.lineWidth = width * 3.2;
  ctx.beginPath();
  ctx.moveTo(screens[0].x, screens[0].y);
  for (let i = 1; i < screens.length; i += 1) {
    ctx.lineTo(screens[i].x, screens[i].y);
  }
  ctx.stroke();
  ctx.globalAlpha = 1;
  ctx.strokeStyle = color;
  ctx.lineWidth = width;
  ctx.beginPath();
  ctx.moveTo(screens[0].x, screens[0].y);
  for (let i = 1; i < screens.length; i += 1) {
    ctx.lineTo(screens[i].x, screens[i].y);
  }
  ctx.stroke();
  ctx.restore();
}

function drawRollingPerformanceChart(ctx, canvas, pad, hover) {
  const trades = reportSession().trades || [];
  const plot = chartPlot(canvas, pad);
  drawReportBackground(ctx, plot);
  const rows = rollingStats(trades, 20);
  if (!rows.length) return;
  const pfValues = rows.map((r) => Math.min(r.pf || 0, 5));
  const winValues = rows.map((r) => r.winRate);
  const expValues = rows.map((r) => r.expectancy);
  const [minExp, maxExp] = extent(expValues);
  const expPad = Math.max(maxExp - minExp, 1) * 0.1;
  const xAt = (i) => plot.x + (i / Math.max(rows.length - 1, 1)) * plot.width;
  const yPct = (v) => plot.y + ((100 - v) / 100) * plot.height;
  const yPf = (v) => plot.y + ((5 - v) / 5) * plot.height;
  const yExp = (v) => plot.y + ((maxExp + expPad - v) / (maxExp - minExp + expPad * 2)) * plot.height;
  drawReportYAxis(ctx, plot, 0, 100, yPct, pct);
  drawReportSeries(ctx, rows, xAt, (r) => yPct(r.winRate), COLORS.buy, 1.5);
  drawReportSeries(ctx, rows, xAt, (r) => yPf(Math.min(r.pf || 0, 5)), COLORS.violet, 1.4);
  drawReportSeries(ctx, rows, xAt, (r) => yExp(r.expectancy), COLORS.amber, 1.4);
  drawLegendInline(ctx, plot, [
    ["Win%", COLORS.buy],
    ["PF cap 5", COLORS.violet],
    ["Expectancy", COLORS.amber],
  ]);
  if (hover) {
    const idx = clamp(Math.round(((hover.x - plot.x) / plot.width) * (rows.length - 1)), 0, rows.length - 1);
    const row = rows[idx];
    drawReportCursor(ctx, plot, xAt(idx));
    showReportTooltip(canvas, hover, `
      <div class="tooltip-row"><span class="label">Trade</span><span class="value">#${row.tradeId}</span></div>
      <div class="tooltip-row"><span class="label">Win Rate</span><span class="value">${pct(row.winRate)}</span></div>
      <div class="tooltip-row"><span class="label">PF</span><span class="value">${row.pf === null ? "—" : row.pf.toFixed(2)}</span></div>
      <div class="tooltip-row"><span class="label">Expectancy</span><span class="value">${signedMoney(row.expectancy)}</span></div>
    `);
  }
}

function drawRiskExposureChart(ctx, canvas, pad, hover) {
  const rows = reportSession().equity || [];
  const plot = chartPlot(canvas, pad);
  drawReportBackground(ctx, plot);
  if (!rows.length) return;
  const maxMargin = maxAbsValue(rows.map((r) => r[6]));
  const maxOpen = maxAbsValue(rows.map((r) => r[4]));
  const minDd = Math.min(-1, ...rows.map((r) => r[5]));
  const xAt = (i) => plot.x + (i / Math.max(rows.length - 1, 1)) * plot.width;
  const yMargin = (v) => plot.y + plot.height - (v / maxMargin) * plot.height;
  const yOpen = (v) => plot.y + plot.height - (v / maxOpen) * plot.height;
  const yDd = (v) => plot.y + (v / minDd) * plot.height;
  drawReportYAxis(ctx, plot, 0, maxMargin, yMargin, money);
  drawReportAreaLine(ctx, rows, xAt, (r) => yMargin(r[6]), "rgba(255,181,71,0.14)", COLORS.amber);
  drawReportSeries(ctx, rows, xAt, (r) => yOpen(r[4]), COLORS.violet, 1.2);
  drawReportSeries(ctx, rows, xAt, (r) => yDd(r[5]), COLORS.sell, 1.2);
  drawLegendInline(ctx, plot, [
    ["Margin", COLORS.amber],
    ["Open", COLORS.violet],
    ["DD", COLORS.sell],
  ]);
  if (hover) {
    const idx = clamp(Math.round(((hover.x - plot.x) / plot.width) * (rows.length - 1)), 0, rows.length - 1);
    const row = rows[idx];
    drawReportCursor(ctx, plot, xAt(idx));
    showReportTooltip(canvas, hover, `
      <div class="tooltip-row"><span class="label">Tempo</span><span class="value">${fmtTime(row[0])}</span></div>
      <div class="tooltip-row"><span class="label">Margin</span><span class="value">${money(row[6])}</span></div>
      <div class="tooltip-row"><span class="label">Abertas</span><span class="value">${row[4]}</span></div>
      <div class="tooltip-row"><span class="label">DD</span><span class="value down">${pct(row[5])}</span></div>
    `);
  }
}

function drawRegimeSurface3d(ctx, canvas, pad, hover) {
  const trades = reportSession().trades || [];
  const candles = reportSession().candles || [];
  const plot = chartPlot(canvas, pad);
  drawReportBackground(ctx, plot);
  if (!trades.length || !candles.length) return;

  const atr = computeAtrSeries(14);
  const trend = computeTrendStrengthSeries(20, atr);
  const samples = trades.map((trade) => {
    const idx = clamp(trade.entryIndex, 0, candles.length - 1);
    const close = candles[idx][4] || 1;
    return {
      trade,
      vol: (atr[idx] || 0) / close * 10000,
      trend: trend[idx] || 0,
      pnl: trade.pnl,
    };
  }).filter((sample) => Number.isFinite(sample.vol) && Number.isFinite(sample.trend));

  const bins = 6;
  const [minVol, maxVol] = extent(samples.map((s) => s.vol));
  const [minTrend, maxTrend] = extent(samples.map((s) => s.trend));
  const grid = Array.from({ length: bins }, () => Array.from({ length: bins }, () => ({
    pnl: 0,
    count: 0,
    trades: [],
  })));

  samples.forEach((sample) => {
    const x = clamp(Math.floor(((sample.vol - minVol) / Math.max(maxVol - minVol, 1e-9)) * bins), 0, bins - 1);
    const y = clamp(Math.floor(((sample.trend - minTrend) / Math.max(maxTrend - minTrend, 1e-9)) * bins), 0, bins - 1);
    grid[x][y].pnl += sample.pnl;
    grid[x][y].count += 1;
    grid[x][y].trades.push(sample.trade);
  });

  const cells = [];
  for (let x = 0; x < bins; x += 1) {
    for (let y = 0; y < bins; y += 1) {
      const cell = grid[x][y];
      if (!cell.count) continue;
      cell.avg = cell.pnl / cell.count;
      cell.xBin = x;
      cell.yBin = y;
      cell.volLabel = `${(minVol + ((maxVol - minVol) / bins) * x).toFixed(2)}-${(minVol + ((maxVol - minVol) / bins) * (x + 1)).toFixed(2)} bp`;
      cell.trendLabel = `${(minTrend + ((maxTrend - minTrend) / bins) * y).toFixed(2)}-${(minTrend + ((maxTrend - minTrend) / bins) * (y + 1)).toFixed(2)} ATR`;
      cells.push(cell);
    }
  }
  if (!cells.length) return;
  const [minAvg, maxAvg] = extent(cells.map((cell) => cell.avg));
  const points = cells.map((cell) => ({
    x: (cell.xBin + 0.5) / bins,
    y: (cell.yBin + 0.5) / bins,
    z: 0.1 + ((cell.avg - minAvg) / Math.max(maxAvg - minAvg, 1e-9)) * 0.8,
    cell,
    count: cell.count,
    colorValue: cell.avg >= 0 ? 0 : 1,
    color: cell.avg >= 0 ? "rgba(43,212,127,0.78)" : "rgba(255,88,103,0.78)",
  }));

  draw3dSurfacePoints(ctx, canvas, plot, points, hover, {
    xLabel: "ATR bp",
    yLabel: "Trend",
    zLabel: "Edge",
    tooltip: (p) => `
      <div class="tooltip-row"><span class="label">ATR</span><span class="value">${p.cell.volLabel}</span></div>
      <div class="tooltip-row"><span class="label">Trend</span><span class="value">${p.cell.trendLabel}</span></div>
      <div class="tooltip-row"><span class="label">Expectancy</span><span class="value ${p.cell.avg >= 0 ? "up" : "down"}">${signedMoney(p.cell.avg)}</span></div>
      <div class="tooltip-row"><span class="label">Trades</span><span class="value">${p.cell.count}</span></div>
    `,
  });
}

function drawTradeEfficiency3d(ctx, canvas, pad, hover) {
  const trades = reportSession().trades || [];
  const plot = chartPlot(canvas, pad);
  drawReportBackground(ctx, plot);
  const maxMae = maxAbsValue(trades.map((trade) => trade.mae || 0));
  const maxMfe = maxAbsValue(trades.map((trade) => trade.mfe || 0));
  const [minPnl, maxPnl] = extent(trades.map((trade) => trade.pnl));
  const points = trades.map((trade) => ({
    x: Math.abs(trade.mae || 0) / maxMae,
    y: Math.max(trade.mfe || 0, 0) / maxMfe,
    z: 0.08 + ((trade.pnl - minPnl) / Math.max(maxPnl - minPnl, 1e-9)) * 0.84,
    trade,
    colorValue: trade.pnl >= 0 ? 0 : 1,
    color: trade.pnl >= 0 ? "rgba(43,212,127,0.78)" : "rgba(255,88,103,0.78)",
    maeValue: trade.mae || 0,
    mfeValue: trade.mfe || 0,
  })).filter((point) => Number.isFinite(point.x) && Number.isFinite(point.y) && Number.isFinite(point.z));

  draw3dScatter(ctx, canvas, plot, points, hover, {
    xLabel: "MAE",
    yLabel: "MFE",
    zLabel: "PnL",
    tooltip: (p) => `
      <div class="tooltip-row"><span class="label">Trade</span><span class="value">#${p.trade.id} · ${p.trade.direction}</span></div>
      <div class="tooltip-separator"></div>
      <div class="tooltip-row"><span class="label">MAE</span><span class="value down">${signedMoney(p.maeValue)}</span></div>
      <div class="tooltip-row"><span class="label">MFE</span><span class="value up">${signedMoney(p.mfeValue)}</span></div>
      <div class="tooltip-row"><span class="label">PnL</span><span class="value ${p.trade.pnl >= 0 ? "up" : "down"}">${signedMoney(p.trade.pnl)}</span></div>
      <div class="tooltip-row"><span class="label">Motivo</span><span class="value">${p.trade.reason || "—"}</span></div>
    `,
  });
}

function drawScatterRelationsChart(ctx, canvas, pad, hover) {
  const plot = chartPlot(canvas, pad);
  drawReportBackground(ctx, plot);
  const panes = splitPlot(plot, 3);
  const trades = reportSession().trades || [];
  drawScatterPane(ctx, canvas, panes[0], trades.map((t) => ({ trade: t, x: t.mfe || 0, y: t.pnl })), "MFE", money, hover);
  drawScatterPane(ctx, canvas, panes[1], trades.map((t) => ({ trade: t, x: Math.abs(t.mae || 0), y: t.pnl })), "MAE", money, hover);
  drawScatterPane(ctx, canvas, panes[2], trades.map((t) => ({ trade: t, x: t.durationMinutes || 0, y: t.pnl })), "Min", (v) => `${Math.round(v)}m`, hover);
}

function drawHourlyHeatmap(ctx, canvas, pad, hover) {
  const plot = chartPlot(canvas, pad);
  drawReportBackground(ctx, plot);
  const grid = Array.from({ length: 7 }, () => Array.from({ length: 24 }, () => ({ pnl: 0, count: 0 })));
  (reportSession().trades || []).forEach((trade) => {
    const d = new Date(trade.exitTime * 1000);
    const weekday = (d.getDay() + 6) % 7;
    const hour = d.getHours();
    grid[weekday][hour].pnl += trade.pnl;
    grid[weekday][hour].count += 1;
  });
  const avgs = grid.flat().map((cell) => cell.count ? cell.pnl / cell.count : 0);
  const maxAbs = maxAbsValue(avgs);
  const cellW = plot.width / 24;
  const cellH = plot.height / 7;
  let hit = null;
  for (let d = 0; d < 7; d += 1) {
    for (let h = 0; h < 24; h += 1) {
      const cell = grid[d][h];
      const avg = cell.count ? cell.pnl / cell.count : 0;
      const alpha = Math.min(0.9, Math.abs(avg) / maxAbs * 0.85 + 0.08);
      ctx.fillStyle = cell.count ? (avg >= 0 ? `rgba(43,212,127,${alpha})` : `rgba(255,88,103,${alpha})`) : "rgba(42,52,69,0.35)";
      const x = plot.x + h * cellW;
      const y = plot.y + d * cellH;
      ctx.fillRect(x, y, Math.max(1, cellW - DPR), Math.max(1, cellH - DPR));
      if (hover && hover.x >= x && hover.x <= x + cellW && hover.y >= y && hover.y <= y + cellH) {
        hit = { weekday: d, hour: h, avg, count: cell.count, pnl: cell.pnl };
      }
    }
  }
  drawHeatmapLabels(ctx, plot);
  if (hit) {
    const days = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sab", "Dom"];
    showReportTooltip(canvas, hover, `
      <div class="tooltip-row"><span class="label">Janela</span><span class="value">${days[hit.weekday]} ${String(hit.hour).padStart(2, "0")}:00</span></div>
      <div class="tooltip-row"><span class="label">Media</span><span class="value ${hit.avg >= 0 ? "up" : "down"}">${signedMoney(hit.avg)}</span></div>
      <div class="tooltip-row"><span class="label">Total</span><span class="value">${signedMoney(hit.pnl)}</span></div>
      <div class="tooltip-row"><span class="label">Trades</span><span class="value">${hit.count}</span></div>
    `);
  }
}

function drawScatterReport(ctx, canvas, pad, hover, mode) {
  const trades = reportSession().trades || [];
  const plot = chartPlot(canvas, pad);
  drawReportBackground(ctx, plot);
  const points = trades.map((trade) => {
    if (mode === "duration") {
      return { trade, x: trade.durationMinutes || Math.max(1, (trade.exitTime - trade.entryTime) / 60), y: trade.pnl };
    }
    return { trade, x: Math.abs(trade.mae || 0), y: trade.mfe || trade.pnl };
  }).filter((p) => Number.isFinite(p.x) && Number.isFinite(p.y));
  if (!points.length) return;
  const minX = 0;
  const maxX = maxAbsValue(points.map((p) => p.x)) * 1.08;
  let [minY, maxY] = extent(points.map((p) => p.y));
  const ySpan = Math.max(maxY - minY, 1);
  minY -= ySpan * 0.1;
  maxY += ySpan * 0.1;
  const xAt = (v) => plot.x + ((v - minX) / (maxX - minX)) * plot.width;
  const yAt = (v) => plot.y + ((maxY - v) / (maxY - minY)) * plot.height;
  drawReportYAxis(ctx, plot, minY, maxY, yAt, money);
  drawReportXAxis(ctx, plot, minX, maxX, mode === "duration" ? (v) => `${Math.round(v)}m` : money);
  let hit = null;
  points.forEach((point) => {
    const x = xAt(point.x);
    const y = yAt(point.y);
    ctx.fillStyle = point.trade.pnl >= 0 ? "rgba(43,212,127,0.72)" : "rgba(255,88,103,0.72)";
    ctx.beginPath();
    ctx.arc(x, y, 3.2 * DPR, 0, Math.PI * 2);
    ctx.fill();
    if (hover && Math.hypot(hover.x - x, hover.y - y) < 8 * DPR) hit = point;
  });
  if (hit) {
    canvas.dataset.hoverTrade = String(hit.trade.id);
    showTradeTooltip(canvas, hover, hit.trade, mode === "duration"
      ? `<div class="tooltip-row"><span class="label">Duracao</span><span class="value">${Math.round(hit.x)} min</span></div>`
      : `<div class="tooltip-row"><span class="label">MAE</span><span class="value down">${signedMoney(-hit.x)}</span></div>
         <div class="tooltip-row"><span class="label">MFE</span><span class="value up">${signedMoney(hit.y)}</span></div>`);
  }
}

function drawReportSeries(ctx, rows, xAt, yOf, color, width) {
  ctx.strokeStyle = color;
  ctx.lineWidth = width * DPR;
  ctx.beginPath();
  rows.forEach((row, i) => {
    const x = xAt(i);
    const y = yOf(row);
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();
}

function extent(values) {
  let min = Infinity;
  let max = -Infinity;
  values.forEach((value) => {
    const num = Number(value);
    if (!Number.isFinite(num)) return;
    if (num < min) min = num;
    if (num > max) max = num;
  });
  if (!Number.isFinite(min) || !Number.isFinite(max)) return [0, 1];
  return [min, max];
}

function maxAbsValue(values) {
  let max = 1;
  values.forEach((value) => {
    const num = Math.abs(Number(value));
    if (Number.isFinite(num) && num > max) max = num;
  });
  return max;
}

function drawReportAreaLine(ctx, rows, xAt, yOf, fill, stroke) {
  const firstY = yOf(rows[0]);
  const baseY = yOf([0, 0, 0, 0, 0, 0]);
  ctx.beginPath();
  ctx.moveTo(xAt(0), baseY);
  rows.forEach((row, i) => ctx.lineTo(xAt(i), yOf(row)));
  ctx.lineTo(xAt(rows.length - 1), baseY);
  ctx.closePath();
  ctx.fillStyle = fill;
  ctx.fill();
  drawReportSeries(ctx, rows, xAt, yOf, stroke, 1.8);
  if (Number.isFinite(firstY)) {
    ctx.fillStyle = stroke;
  }
}

function drawReportYAxis(ctx, plot, min, max, yAt, formatter) {
  ctx.fillStyle = COLORS.axisText;
  ctx.font = `${9 * DPR}px ${FONT_MONO}`;
  ctx.textAlign = "right";
  ctx.textBaseline = "middle";
  for (let i = 0; i <= 4; i += 1) {
    const value = min + ((max - min) / 4) * i;
    ctx.fillText(formatter(value), plot.x - 8 * DPR, yAt(value));
  }
}

function drawReportXAxis(ctx, plot, min, max, formatter) {
  ctx.fillStyle = COLORS.axisText;
  ctx.font = `${9 * DPR}px ${FONT_MONO}`;
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  for (let i = 0; i <= 4; i += 1) {
    const value = min + ((max - min) / 4) * i;
    const x = plot.x + (plot.width / 4) * i;
    ctx.fillText(formatter(value), x, plot.y + plot.height + 8 * DPR);
  }
}

function drawZeroLine(ctx, plot, y) {
  ctx.strokeStyle = "rgba(181,192,207,0.45)";
  ctx.lineWidth = 1 * DPR;
  ctx.beginPath();
  ctx.moveTo(plot.x, y);
  ctx.lineTo(plot.x + plot.width, y);
  ctx.stroke();
}

function drawReportCursor(ctx, plot, x) {
  ctx.strokeStyle = COLORS.crosshair;
  ctx.setLineDash([2 * DPR, 4 * DPR]);
  ctx.beginPath();
  ctx.moveTo(x, plot.y);
  ctx.lineTo(x, plot.y + plot.height);
  ctx.stroke();
  ctx.setLineDash([]);
}

function drawHeatmapLabels(ctx, plot) {
  ctx.fillStyle = COLORS.axisText;
  ctx.font = `${9 * DPR}px ${FONT_MONO}`;
  ctx.textAlign = "right";
  ctx.textBaseline = "middle";
  ["Seg", "Ter", "Qua", "Qui", "Sex", "Sab", "Dom"].forEach((day, i) => {
    ctx.fillText(day, plot.x - 8 * DPR, plot.y + (i + 0.5) * (plot.height / 7));
  });
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  for (let h = 0; h < 24; h += 3) {
    ctx.fillText(String(h).padStart(2, "0"), plot.x + (h + 0.5) * (plot.width / 24), plot.y + plot.height + 8 * DPR);
  }
}

function monthlyPnl() {
  return groupedPnl("month");
}

function groupedPnl(mode) {
  const groups = new Map();
  (reportSession().trades || []).forEach((trade) => {
    const d = new Date(trade.exitTime * 1000);
    const key = mode === "year"
      ? String(d.getFullYear())
      : `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
    const item = groups.get(key) || { label: mode === "year" ? key : key.slice(2), pnl: 0, count: 0 };
    item.pnl += trade.pnl;
    item.count += 1;
    groups.set(key, item);
  });
  return [...groups.entries()].sort((a, b) => a[0].localeCompare(b[0])).map(([, value]) => value);
}

function groupedEquityByMonth() {
  const groups = new Map();
  (reportSession().equity || []).forEach((row) => {
    const d = new Date(row[0] * 1000);
    const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
    const item = groups.get(key) || { label: key.slice(2), peak: -Infinity, dd: 0 };
    item.peak = Math.max(item.peak, row[2]);
    const dd = item.peak ? (row[2] / item.peak - 1) * 100 : 0;
    item.dd = Math.min(item.dd, dd);
    groups.set(key, item);
  });
  return [...groups.entries()].sort((a, b) => a[0].localeCompare(b[0])).map(([, value]) => value);
}

function monthlyProfitFactor() {
  const groups = new Map();
  (reportSession().trades || []).forEach((trade) => {
    const d = new Date(trade.exitTime * 1000);
    const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
    const item = groups.get(key) || { label: key.slice(2), wins: 0, losses: 0, count: 0, pf: null };
    if (trade.pnl > 0) item.wins += trade.pnl;
    if (trade.pnl < 0) item.losses += trade.pnl;
    item.count += 1;
    groups.set(key, item);
  });
  return [...groups.entries()].sort((a, b) => a[0].localeCompare(b[0])).map(([, item]) => {
    item.pf = item.losses < 0 ? item.wins / Math.abs(item.losses) : null;
    return item;
  });
}

function groupedTradeValues(mode) {
  const labels = mode === "hour"
    ? Array.from({ length: 24 }, (_, i) => String(i).padStart(2, "0"))
    : ["Seg", "Ter", "Qua", "Qui", "Sex", "Sab", "Dom"];
  const groups = labels.map((label) => ({ label, values: [], avg: 0 }));
  (reportSession().trades || []).forEach((trade) => {
    const d = new Date(trade.exitTime * 1000);
    const idx = mode === "hour" ? d.getHours() : (d.getDay() + 6) % 7;
    groups[idx].values.push(trade.pnl);
  });
  groups.forEach((group) => {
    group.avg = group.values.length ? group.values.reduce((a, b) => a + b, 0) / group.values.length : 0;
  });
  return groups.filter((group) => group.values.length);
}

function quantiles(values) {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const q = (p) => {
    const idx = (sorted.length - 1) * p;
    const lo = Math.floor(idx);
    const hi = Math.ceil(idx);
    const t = idx - lo;
    return sorted[lo] * (1 - t) + sorted[hi] * t;
  };
  return { min: sorted[0], q1: q(0.25), median: q(0.5), q3: q(0.75), max: sorted[sorted.length - 1] };
}

function splitPlot(plot, count) {
  const gap = 18 * DPR;
  const width = (plot.width - gap * (count - 1)) / count;
  return Array.from({ length: count }, (_, i) => ({
    ...plot,
    x: plot.x + i * (width + gap),
    width,
  }));
}

function drawCategoryBars(ctx, canvas, plot, data, valueOf, yAt, formatter, hover, tooltipHtml, zeroValue = 0) {
  const gap = 5 * DPR;
  const bw = Math.max(7 * DPR, (plot.width - gap * (data.length - 1)) / data.length);
  const zeroY = yAt(zeroValue);
  let hit = null;
  data.forEach((item, i) => {
    const value = valueOf(item);
    const x = plot.x + i * (bw + gap);
    const y = yAt(value);
    const h = Math.abs(y - zeroY);
    ctx.fillStyle = value >= 0 ? COLORS.buy : COLORS.sell;
    ctx.fillRect(x, Math.min(y, zeroY), bw, Math.max(1 * DPR, h));
    if (data.length <= 18 || i % Math.ceil(data.length / 12) === 0) {
      ctx.fillStyle = COLORS.axisText;
      ctx.font = `${9 * DPR}px ${FONT_MONO}`;
      ctx.textAlign = "center";
      ctx.fillText(item.label, x + bw / 2, plot.y + plot.height + 8 * DPR);
    }
    if (hover && hover.x >= x && hover.x <= x + bw && hover.y >= plot.y && hover.y <= plot.y + plot.height) hit = item;
  });
  if (hit && tooltipHtml) showReportTooltip(canvas, hover, tooltipHtml(hit));
  return hit;
}

function drawHistogramPane(ctx, canvas, plot, values, label, formatter, hover, color = COLORS.buy) {
  const clean = values.map(Number).filter(Number.isFinite);
  if (!clean.length) return;
  let [min, max] = extent(clean);
  if (min === max) {
    min -= 1;
    max += 1;
  }
  const bins = 18;
  const counts = Array.from({ length: bins }, () => 0);
  clean.forEach((value) => {
    const idx = clamp(Math.floor(((value - min) / (max - min)) * bins), 0, bins - 1);
    counts[idx] += 1;
  });
  const maxCount = maxAbsValue(counts);
  const bw = plot.width / bins;
  ctx.fillStyle = COLORS.axisText;
  ctx.font = `${10 * DPR}px ${FONT_MONO}`;
  ctx.textAlign = "left";
  ctx.fillText(label, plot.x, plot.y + 10 * DPR);
  let hit = null;
  counts.forEach((count, i) => {
    const h = (count / maxCount) * (plot.height - 28 * DPR);
    const x = plot.x + i * bw;
    const y = plot.y + plot.height - h;
    ctx.fillStyle = color;
    ctx.globalAlpha = 0.72;
    ctx.fillRect(x, y, Math.max(1, bw - DPR), h);
    ctx.globalAlpha = 1;
    if (hover && hover.x >= x && hover.x <= x + bw && hover.y >= plot.y && hover.y <= plot.y + plot.height) {
      const a = min + ((max - min) / bins) * i;
      const b = min + ((max - min) / bins) * (i + 1);
      hit = { a, b, count };
    }
  });
  drawReportXAxis(ctx, plot, min, max, formatter);
  if (hit) {
    showReportTooltip(canvas, hover, `
      <div class="tooltip-row"><span class="label">Faixa</span><span class="value">${formatter(hit.a)} - ${formatter(hit.b)}</span></div>
      <div class="tooltip-row"><span class="label">Qtd</span><span class="value">${hit.count}</span></div>
    `);
  }
}

function drawScatterPane(ctx, canvas, plot, points, label, formatX, hover) {
  drawGenericScatterInPlot(ctx, plot, points, label, formatX, hover, canvas);
}

function drawGenericScatter(ctx, canvas, pad, hover, points, label, formatX, clickable = false) {
  const plot = chartPlot(canvas, pad);
  drawReportBackground(ctx, plot);
  drawGenericScatterInPlot(ctx, plot, points, label, formatX, hover, canvas, clickable);
}

function drawGenericScatterInPlot(ctx, plot, points, label, formatX, hover, canvas = null, clickable = true) {
  const clean = points.filter((p) => Number.isFinite(p.x) && Number.isFinite(p.y));
  if (!clean.length) return;
  const minX = 0;
  const maxX = maxAbsValue(clean.map((p) => p.x)) * 1.08;
  let [minY, maxY] = extent(clean.map((p) => p.y));
  const ySpan = Math.max(maxY - minY, 1);
  minY -= ySpan * 0.1;
  maxY += ySpan * 0.1;
  const xAt = (v) => plot.x + ((v - minX) / (maxX - minX)) * plot.width;
  const yAt = (v) => plot.y + ((maxY - v) / (maxY - minY)) * plot.height;
  drawReportYAxis(ctx, plot, minY, maxY, yAt, money);
  drawReportXAxis(ctx, plot, minX, maxX, formatX);
  ctx.fillStyle = COLORS.axisText;
  ctx.font = `${10 * DPR}px ${FONT_MONO}`;
  ctx.textAlign = "left";
  ctx.fillText(label, plot.x, plot.y + 10 * DPR);
  let hit = null;
  clean.forEach((point) => {
    const x = xAt(point.x);
    const y = yAt(point.y);
    ctx.fillStyle = point.trade.pnl >= 0 ? "rgba(43,212,127,0.72)" : "rgba(255,88,103,0.72)";
    ctx.beginPath();
    ctx.arc(x, y, 3 * DPR, 0, Math.PI * 2);
    ctx.fill();
    if (hover && Math.hypot(hover.x - x, hover.y - y) < 8 * DPR) hit = point;
  });
  if (hit) {
    const targetCanvas = canvas || document.elementFromPoint(hover.x / DPR, hover.y / DPR)?.closest("canvas");
    if (targetCanvas) {
      if (clickable) targetCanvas.dataset.hoverTrade = String(hit.trade.id);
      showTradeTooltip(targetCanvas, hover, hit.trade, `<div class="tooltip-row"><span class="label">${label}</span><span class="value">${formatX(hit.x)}</span></div>`);
    }
  }
}

function monteCarloPaths(mode, count, options = {}) {
  const trades = (reportSession().trades || []).map((t) => Number(t.pnl)).filter((v) => Number.isFinite(v));
  const initial = reportSession().metadata.initial_capital || 0;
  if (!trades.length) return [];
  const paths = [];
  for (let run = 0; run < count; run += 1) {
    const sample = sampleMonteCarloTrades(trades, mode, run + 17, options);
    let total = initial;
    const path = [total];
    sample.forEach((pnl) => {
      total += pnl;
      path.push(total);
    });
    paths.push(path);
  }
  return paths;
}

function seededGenerator(seed) {
  let s = seed >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 4294967296;
  };
}

function deterministicShuffle(values, seed) {
  const out = [...values];
  const rand = seededGenerator(seed);
  for (let i = out.length - 1; i > 0; i -= 1) {
    const j = Math.floor(rand() * (i + 1));
    [out[i], out[j]] = [out[j], out[i]];
  }
  return out;
}

function sampleMonteCarloTrades(values, mode, seed, options = {}) {
  if (mode === "shuffle") return deterministicShuffle(values, seed);
  if (mode === "bootstrap") return deterministicBootstrap(values, seed);
  if (mode === "block_bootstrap") return deterministicBlockBootstrap(values, seed, options.blockSize || 5);
  if (mode === "execution_stress") return deterministicExecutionStress(values, seed);
  return deterministicShuffle(values, seed);
}

function deterministicBootstrap(values, seed) {
  const rand = seededGenerator(seed);
  const out = [];
  for (let i = 0; i < values.length; i += 1) {
    out.push(values[Math.floor(rand() * values.length)]);
  }
  return out;
}

function deterministicBlockBootstrap(values, seed, blockSize = 5) {
  const rand = seededGenerator(seed);
  const out = [];
  const size = Math.max(1, Math.min(blockSize, values.length));
  while (out.length < values.length) {
    const start = Math.floor(rand() * values.length);
    for (let i = 0; i < size && out.length < values.length; i += 1) {
      out.push(values[(start + i) % values.length]);
    }
  }
  return out;
}

function deterministicExecutionStress(values, seed) {
  const rand = seededGenerator(seed);
  const base = deterministicShuffle(values, seed);
  const nonZero = base.map((v) => Math.abs(v)).filter((v) => v > 0);
  const medianAbs = quantileValue(nonZero.length ? nonZero : [1], 0.5);
  const std = standardDeviation(base);
  return base.map((value) => {
    const noise = randomNormal(rand) * Math.max(std, medianAbs) * 0.08;
    const extraCost = rand() * medianAbs * 0.06 + Math.abs(value) * rand() * 0.03;
    return value + noise - extraCost;
  });
}

function randomNormal(rand) {
  const u1 = Math.max(rand(), 1e-9);
  const u2 = rand();
  return Math.sqrt(-2 * Math.log(u1)) * Math.cos(2 * Math.PI * u2);
}

function standardDeviation(values) {
  if (!values.length) return 0;
  const avg = values.reduce((sum, value) => sum + value, 0) / values.length;
  const variance = values.reduce((sum, value) => sum + ((value - avg) ** 2), 0) / Math.max(values.length, 1);
  return Math.sqrt(variance);
}

function quantileValue(values, q) {
  const sorted = [...values].sort((a, b) => a - b);
  if (!sorted.length) return 0;
  const pos = (sorted.length - 1) * q;
  const base = Math.floor(pos);
  const rest = pos - base;
  const next = sorted[Math.min(base + 1, sorted.length - 1)];
  return sorted[base] + rest * (next - sorted[base]);
}

function computeAtrSeries(period) {
  const candles = reportSession().candles || [];
  const tr = candles.map((c, i) => {
    const prevClose = i > 0 ? candles[i - 1][4] : c[4];
    return Math.max(c[2] - c[3], Math.abs(c[2] - prevClose), Math.abs(c[3] - prevClose));
  });
  return tr.map((_, i) => {
    if (i < period) return 0;
    let sum = 0;
    for (let j = i - period + 1; j <= i; j += 1) sum += tr[j];
    return sum / period;
  });
}

function computeTrendStrengthSeries(lookback, atr) {
  const candles = reportSession().candles || [];
  const ema20 = reportSession().overlays?.ema20 || [];
  return candles.map((candle, i) => {
    if (i < lookback) return 0;
    const now = Number.isFinite(Number(ema20[i])) ? Number(ema20[i]) : candle[4];
    const prevValue = Number.isFinite(Number(ema20[i - lookback])) ? Number(ema20[i - lookback]) : candles[i - lookback][4];
    const denom = Math.max(atr[i] || 0, Math.abs(candle[4]) * 0.0001, 1e-9);
    return (now - prevValue) / denom;
  });
}

function drawSmallLine(ctx, x1, x2, y, color) {
  ctx.strokeStyle = color;
  ctx.lineWidth = 1 * DPR;
  ctx.beginPath();
  ctx.moveTo(x1, y);
  ctx.lineTo(x2, y);
  ctx.stroke();
}

function reportInsights() {
  const trades = reportSession().trades || [];
  const pnls = trades.map((t) => t.pnl).sort((a, b) => a - b);
  const maxLossStreak = trades.reduce((acc, trade) => {
    const current = trade.pnl < 0 ? acc.current + 1 : 0;
    return { current, max: Math.max(acc.max, current) };
  }, { current: 0, max: 0 }).max;
  const cutoff = Math.max(1, Math.ceil(pnls.length * 0.05));
  const tail = pnls.slice(0, cutoff);
  const var5 = tail[tail.length - 1] || 0;
  const cvar5 = tail.length ? tail.reduce((a, b) => a + b, 0) / tail.length : 0;
  const eq = reportSession().equity || [];
  let peak = eq.length ? eq[0][2] : 0;
  let maxDdMoney = 0;
  eq.forEach((row) => {
    peak = Math.max(peak, row[2]);
    maxDdMoney = Math.min(maxDdMoney, row[2] - peak);
  });
  const net = reportSession().metrics.net_profit || 0;
  const recovery = maxDdMoney < 0 ? net / Math.abs(maxDdMoney) : 0;
  return { maxLossStreak, var5, cvar5, recovery };
}

function rollingStats(trades, windowSize) {
  const rows = [];
  for (let i = 0; i < trades.length; i += 1) {
    const slice = trades.slice(Math.max(0, i - windowSize + 1), i + 1);
    const wins = slice.filter((t) => t.pnl > 0);
    const losses = slice.filter((t) => t.pnl < 0);
    const grossWin = wins.reduce((sum, t) => sum + t.pnl, 0);
    const grossLoss = losses.reduce((sum, t) => sum + t.pnl, 0);
    rows.push({
      tradeId: trades[i].id,
      winRate: slice.length ? wins.length / slice.length * 100 : 0,
      pf: grossLoss < 0 ? grossWin / Math.abs(grossLoss) : null,
      expectancy: slice.reduce((sum, t) => sum + t.pnl, 0) / slice.length,
    });
  }
  return rows;
}

function histogramBins(values, bins) {
  const clean = values.map(Number).filter(Number.isFinite);
  if (!clean.length) return [];
  let [min, max] = extent(clean);
  if (min === max) {
    min -= 1;
    max += 1;
  }
  const out = Array.from({ length: bins }, (_, i) => {
    const a = min + ((max - min) / bins) * i;
    const b = min + ((max - min) / bins) * (i + 1);
    return { a, b, mid: (a + b) / 2, count: 0 };
  });
  clean.forEach((value) => {
    const idx = clamp(Math.floor(((value - min) / (max - min)) * bins), 0, bins - 1);
    out[idx].count += 1;
  });
  return out;
}

function drawLegendInline(ctx, plot, items) {
  ctx.font = `${10 * DPR}px ${FONT_MONO}`;
  ctx.textAlign = "left";
  ctx.textBaseline = "top";
  let x = plot.x + 6 * DPR;
  const y = plot.y + 6 * DPR;
  items.forEach(([label, color]) => {
    ctx.fillStyle = color;
    ctx.fillRect(x, y + 3 * DPR, 10 * DPR, 2 * DPR);
    ctx.fillStyle = COLORS.axisText;
    ctx.fillText(label, x + 14 * DPR, y);
    x += (label.length * 7 + 34) * DPR;
  });
}

function draw3dAxes(ctx, plot, project, labels) {
  const origin = project({ x: 0, y: 0, z: 0 });
  const axes = [
    [{ x: 1, y: 0, z: 0 }, labels.xLabel],
    [{ x: 0, y: 1, z: 0 }, labels.yLabel],
    [{ x: 0, y: 0, z: 1 }, labels.zLabel],
  ];
  ctx.strokeStyle = "rgba(181,192,207,0.55)";
  ctx.fillStyle = COLORS.axisText;
  ctx.font = `${10 * DPR}px ${FONT_MONO}`;
  axes.forEach(([endPoint, label]) => {
    const end = project(endPoint);
    ctx.beginPath();
    ctx.moveTo(origin.x, origin.y);
    ctx.lineTo(end.x, end.y);
    ctx.stroke();
    ctx.fillText(label, end.x + 5 * DPR, end.y);
  });
}

function makeProjector(canvas, plot) {
  const rotX = Number(canvas.dataset.rotX || "58") * Math.PI / 180;
  const rotY = Number(canvas.dataset.rotY || "-32") * Math.PI / 180;
  const scale = Math.min(plot.width, plot.height) * 0.58;
  const cx = plot.x + plot.width * 0.52;
  const cy = plot.y + plot.height * 0.58;
  return (p) => {
    let x = p.x - 0.5;
    let y = p.y - 0.5;
    let z = p.z - 0.5;
    const cosY = Math.cos(rotY), sinY = Math.sin(rotY);
    const x1 = x * cosY - z * sinY;
    const z1 = x * sinY + z * cosY;
    const cosX = Math.cos(rotX), sinX = Math.sin(rotX);
    const y1 = y * cosX - z1 * sinX;
    const z2 = y * sinX + z1 * cosX;
    const perspective = 1.25 / (1.65 - z2 * 0.45);
    return {
      x: cx + x1 * scale * perspective,
      y: cy - y1 * scale * perspective,
      depth: z2,
    };
  };
}

function draw3dScatter(ctx, canvas, plot, points, hover, labels) {
  const project = makeProjector(canvas, plot);
  draw3dAxes(ctx, plot, project, labels);
  let hit = null;
  points
    .map((point) => ({ point, screen: project(point) }))
    .sort((a, b) => a.screen.depth - b.screen.depth)
    .forEach(({ point, screen }) => {
      const hue = 190 - (point.colorValue || 0) * 130;
      ctx.fillStyle = point.color || `hsla(${hue}, 75%, 62%, 0.78)`;
      ctx.beginPath();
      ctx.arc(screen.x, screen.y, 3.2 * DPR, 0, Math.PI * 2);
      ctx.fill();
      if (hover && Math.hypot(hover.x - screen.x, hover.y - screen.y) < 8 * DPR) hit = { point, screen };
    });
  draw3dHint(ctx, plot, canvas);
  if (hit) {
    if (hit.point.trade) canvas.dataset.hoverTrade = String(hit.point.trade.id);
    showReportTooltip(canvas, hover, labels.tooltip(hit.point));
  }
}

function draw3dSurfacePoints(ctx, canvas, plot, points, hover, labels) {
  const project = makeProjector(canvas, plot);
  draw3dAxes(ctx, plot, project, labels);
  let hit = null;
  const maxCount = maxAbsValue(points.map((p) => p.count));
  points
    .map((point) => ({ point, screen: project(point) }))
    .sort((a, b) => a.screen.depth - b.screen.depth)
    .forEach(({ point, screen }) => {
      const size = (5 + (point.count / maxCount) * 10) * DPR;
      ctx.fillStyle = point.color || COLORS.equity;
      ctx.beginPath();
      ctx.moveTo(screen.x, screen.y - size * 0.65);
      ctx.lineTo(screen.x + size * 0.65, screen.y);
      ctx.lineTo(screen.x, screen.y + size * 0.65);
      ctx.lineTo(screen.x - size * 0.65, screen.y);
      ctx.closePath();
      ctx.fill();
      ctx.strokeStyle = "rgba(233,238,244,0.18)";
      ctx.stroke();
      if (hover && Math.hypot(hover.x - screen.x, hover.y - screen.y) < size) hit = { point, screen };
    });
  draw3dHint(ctx, plot, canvas);
  if (hit) showReportTooltip(canvas, hover, labels.tooltip(hit.point));
}

function draw3dBars(ctx, canvas, plot, points, hover, labels) {
  const project = makeProjector(canvas, plot);
  draw3dAxes(ctx, plot, project, labels);
  let hit = null;
  const maxCount = maxAbsValue(points.map((p) => p.count));
  points
    .map((point) => ({ point, screen: project(point) }))
    .sort((a, b) => a.screen.depth - b.screen.depth)
    .forEach(({ point, screen }) => {
      const size = (3 + point.count / maxCount * 7) * DPR;
      ctx.fillStyle = `rgba(74,214,230,${0.18 + point.count / maxCount * 0.62})`;
      ctx.fillRect(screen.x - size / 2, screen.y - size / 2, size, size);
      if (hover && Math.abs(hover.x - screen.x) < size && Math.abs(hover.y - screen.y) < size) hit = { point, screen };
    });
  draw3dHint(ctx, plot, canvas);
  if (hit) showReportTooltip(canvas, hover, labels.tooltip(hit.point));
}

function draw3dHint(ctx, plot, canvas) {
  ctx.fillStyle = COLORS.axisText;
  ctx.font = `${10 * DPR}px ${FONT_MONO}`;
  ctx.textAlign = "right";
  ctx.fillText(`rot X ${Math.round(Number(canvas.dataset.rotX || "58"))} · Y ${Math.round(Number(canvas.dataset.rotY || "-32"))}`, plot.x + plot.width, plot.y + plot.height + 20 * DPR);
}

function showReportTooltip(canvas, hover, html) {
  const modalBody = canvas.closest(".chart-modal-body");
  const card = canvas.closest(".report-card");
  const host = modalBody || card;
  if (!host) return;
  const hostRect = host.getBoundingClientRect();
  const canvasRect = canvas.getBoundingClientRect();
  const tooltipEl = modalBody ? els.chartModalTooltip : els.reportTooltip;
  tooltipEl.innerHTML = html;
  tooltipEl.classList.add("visible");
  tooltipEl.style.left = `${canvasRect.left - hostRect.left + hover.x / DPR + 14}px`;
  tooltipEl.style.top = `${canvasRect.top - hostRect.top + hover.y / DPR + 14}px`;
  host.appendChild(tooltipEl);
}

function showTradeTooltip(canvas, hover, trade, extra = "") {
  showReportTooltip(canvas, hover, `
    <div class="tooltip-row"><span class="label">Trade</span><span class="value">#${trade.id} · ${trade.direction}</span></div>
    <div class="tooltip-separator"></div>
    ${extra}
    <div class="tooltip-row"><span class="label">PnL</span><span class="value ${trade.pnl >= 0 ? "up" : "down"}">${signedMoney(trade.pnl)}</span></div>
    <div class="tooltip-row"><span class="label">Entrada</span><span class="value">${fmtTime(trade.entryTime)}</span></div>
    <div class="tooltip-row"><span class="label">Saida</span><span class="value">${fmtTime(trade.exitTime)}</span></div>
    <div class="tooltip-row"><span class="label">Motivo</span><span class="value">${trade.reason || "—"}</span></div>
  `);
}

// ============================================================
// Misc helpers
// ============================================================

function debounce(fn, wait) {
  let t;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn.apply(null, args), wait);
  };
}
