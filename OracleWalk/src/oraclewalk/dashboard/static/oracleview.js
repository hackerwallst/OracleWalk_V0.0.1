// ======================================================
//  OracleView v10 — preço + volume separado + RSI + desenho (trendline)
// ======================================================
console.log("OracleView v10 JS carregado");

let priceChart, volumeChart, rsiChart;
let candleSeries, volumeSeries, ema50Series;
let rsiSeries;

let firstLoad = true;
let lastPriceRef = null;
let latestEquity = null;
let positionsPanelHeight = 190;
let lastTradesCache = [];

// mapas para tooltip
let ema50Map = new Map();
let rsiMap = new Map();

// FVG Primitive
let fvgPrimitive = null;

// =====================
// CLASSES FVG (Custom Primitive)
// =====================
class FVGPrimitive {
  constructor(chart, series) {
    this._chart = chart;
    this._series = series;
    this._data = [];
    this._paneView = new FVGPaneView(this);
  }

  setData(data) {
    this._data = data;
    // Força update
    this._chart.timeScale().applyOptions({});
  }

  paneViews() {
    return [this._paneView];
  }
}

class FVGPaneView {
  constructor(source) {
    this._source = source;
  }

  renderer() {
    return new FVGRenderer(
      this._source._data,
      this._source._chart,
      this._source._series
    );
  }
}

class FVGRenderer {
  constructor(data, chart, series) {
    this._data = data;
    this._chart = chart;
    this._series = series;
  }

  draw(target) {
    target.useBitmapCoordinateSpace((scope) => {
      const ctx = scope.context;
      const timeScale = this._chart.timeScale();

      // Debug
      if (this._data.length > 0 && Math.random() < 0.1) {
        console.log(`[FVG Renderer] Tentando desenhar ${this._data.length} FVGs`);
      }

      // Verifica se o método existe (v4.0+)
      if (!timeScale.coordinateToLogical) {
        console.warn("[FVG] coordinateToLogical não disponível");
        return;
      }

      ctx.save();

      let drawnCount = 0;

      this._data.forEach((fvg, idx) => {
        if (!fvg.start_time) return;

        const x1 = timeScale.timeToCoordinate(fvg.start_time);

        // Se x1 é null, o candle de início não está visível
        if (x1 === null) return;

        // Usa end_time se disponível, senão estende 50 barras
        let x2;
        if (fvg.end_time) {
          x2 = timeScale.timeToCoordinate(fvg.end_time);
        } else {
          const logical1 = timeScale.coordinateToLogical(x1);
          if (logical1 === null) return;
          const logical2 = logical1 + 100;
          x2 = timeScale.logicalToCoordinate(logical2);
        }

        // Fallback: se end_time existir mas estiver fora da tela, estende 100 barras
        if (x2 === null) {
          const logical1 = timeScale.coordinateToLogical(x1);
          if (logical1 === null) return;
          const logical2 = logical1 + 100;
          x2 = timeScale.logicalToCoordinate(logical2);
        }

        if (x2 === null) return;

        const yTop = this._series.priceToCoordinate(fvg.top);
        const yBottom = this._series.priceToCoordinate(fvg.bottom);
        const yMid = this._series.priceToCoordinate(fvg.mid);

        if (yTop === null || yBottom === null || yMid === null) return;

        const width = x2 - x1;
        const height = yBottom - yTop;

        // Cores translúcidas
        if (fvg.type === "bullish") {
          ctx.fillStyle = "rgba(0, 255, 0, 0.12)";
          ctx.strokeStyle = "rgba(0, 255, 0, 0.5)";
        } else {
          ctx.fillStyle = "rgba(255, 0, 0, 0.12)";
          ctx.strokeStyle = "rgba(255, 0, 0, 0.5)";
        }

        // Desenha retângulo
        ctx.lineWidth = 1;
        ctx.fillRect(x1, yTop, width, height);
        ctx.strokeRect(x1, yTop, width, height);

        // Desenha linha pontilhada no meio (midline)
        ctx.setLineDash([4, 4]);
        ctx.beginPath();
        ctx.moveTo(x1, yMid);
        ctx.lineTo(x2, yMid);
        ctx.stroke();
        ctx.setLineDash([]); // Reset dash

        // Desenha label "FVG" no canto direito
        ctx.font = "11px -apple-system, sans-serif";
        ctx.fillStyle = fvg.type === "bullish" ? "rgba(0, 255, 0, 0.8)" : "rgba(255, 0, 0, 0.8)";
        ctx.textAlign = "right";
        ctx.textBaseline = "middle";
        ctx.fillText("FVG", x2 - 4, yMid);

        drawnCount++;
      });

      if (drawnCount > 0 && Math.random() < 0.1) {
        console.log(`[FVG Renderer] Desenhou ${drawnCount} retângulos`);
      }

      ctx.restore();
    });
  }
}

// =====================
// SISTEMA DE DESENHO
// =====================

let drawingMode = null;      // "trendline" | null
let firstPoint = null;
let drawnShapes = [];

window.enableTrendline = function () {
  drawingMode = "trendline";
  firstPoint = null;
  console.log("[DRAW] Trendline mode ON");
};

window.undoShape = function () {
  const last = drawnShapes.pop();
  if (last && priceChart) {
    try {
      priceChart.removeSeries(last);
    } catch (e) {
      console.warn("Erro ao remover shape:", e);
    }
  }
};

// Cores padrão
const UP_COLOR_BODY = "#26a69a";
const DOWN_COLOR_BODY = "#ef5350";
const UP_COLOR_WICK = "#26a69a";
const DOWN_COLOR_WICK = "#ef5350";

function setDebug(msg) {
  const el = document.getElementById("dbg-msg");
  if (el) el.textContent = msg;
}

// =====================
// EQUITY PANEL HELPERS
// =====================
function fmtMoney(v) {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return "--";
  try {
    return Number(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  } catch (e) {
    return String(v);
  }
}

function updateEquityPanel(data) {
  const balEl = document.getElementById("eq-balance");
  const eqEl = document.getElementById("eq-equity");
  const openEl = document.getElementById("eq-open");
  const tsEl = document.getElementById("eq-ts");

  if (!balEl || !eqEl || !openEl || !tsEl) return;

  const balance = data?.balance ?? null;
  const equity = data?.equity ?? null;
  const open = data?.open_pnl ?? null;
  const ts = data?.timestamp ?? null;

  balEl.textContent = fmtMoney(balance);
  eqEl.textContent = fmtMoney(equity);
  openEl.textContent = fmtMoney(open);

  openEl.classList.remove("up", "down");
  if (Number.isFinite(open)) {
    if (open > 0) openEl.classList.add("up");
    else if (open < 0) openEl.classList.add("down");
  }

  if (ts) {
    try {
      const d = new Date(ts * 1000);
      tsEl.textContent = d.toISOString().slice(0, 19).replace("T", " ");
    } catch (e) {
      tsEl.textContent = "--";
    }
  } else {
    tsEl.textContent = "--";
  }
}

// =====================
// POSITIONS PANEL
// =====================
function computeLocalEquity() {
  const open = lastTradesCache.filter(t => !(t.time_exit || t.exit_time || t.close_time));
  const closed = lastTradesCache.filter(t => (t.time_exit || t.exit_time || t.close_time));

  let realized = 0;
  closed.forEach((t) => {
    const side = (t.side || "").toLowerCase();
    const isBuy = side === "buy" || side === "long";
    const entry = t.price_entry ?? t.entry_price;
    const exit = t.price_exit ?? t.exit_price;
    const qty = (t.quantity != null && t.quantity !== 0) ? t.quantity : 1;
    if (t.pnl_exec != null) {
      realized += Number(t.pnl_exec);
      return;
    }
    if (entry == null || exit == null) return;
    const delta = isBuy ? (exit - entry) : (entry - exit);
    realized += delta * qty;
  });

  let openPnl = 0;
  open.forEach((t) => {
    const side = (t.side || "").toLowerCase();
    const isBuy = side === "buy" || side === "long";
    const entry = t.price_entry ?? t.entry_price;
    const qty = (t.quantity != null && t.quantity !== 0) ? t.quantity : 1;
    const ref = lastPriceRef ?? entry;
    if (entry != null && ref != null) {
      const delta = isBuy ? (ref - entry) : (entry - ref);
      openPnl += delta * qty;
    }
  });

  const balance = realized;
  const equity = balance + openPnl;
  return {
    balance,
    equity,
    open_pnl: openPnl,
    timestamp: Math.floor(Date.now() / 1000),
  };
}

function initPositionResizer() {
  const resizer = document.getElementById("pos-resizer");
  const panel = document.getElementById("positions-panel");
  if (!resizer || !panel) return;

  panel.style.height = `${positionsPanelHeight}px`;

  let dragging = false;
  let startY = 0;
  let startH = positionsPanelHeight;

  resizer.addEventListener("mousedown", (e) => {
    dragging = true;
    startY = e.clientY;
    startH = panel.getBoundingClientRect().height;
    document.body.style.userSelect = "none";
  });

  window.addEventListener("mousemove", (e) => {
    if (!dragging) return;
    const dy = e.clientY - startY;
    const newH = Math.min(320, Math.max(140, startH + dy));
    positionsPanelHeight = newH;
    panel.style.height = `${newH}px`;
  });

  window.addEventListener("mouseup", () => {
    dragging = false;
    document.body.style.userSelect = "";
  });
}

function renderPositionsOpen(trades) {
  const body = document.getElementById("positions-body");
  if (!body) return;

  if (!Array.isArray(trades) || trades.length === 0) {
    body.innerHTML = `<tr><td colspan="8" style="text-align:center; padding:10px; color:#9ca3af;">Sem posições...</td></tr>`;
    return;
  }

  const fmt = (v) => {
    if (v === null || v === undefined || Number.isNaN(Number(v))) return "--";
    return Number(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  };

  const fmtTs = (ts) => {
    if (!ts) return "--";
    try {
      if (typeof ts === "string") return ts;
      const d = new Date(ts * 1000);
      return d.toISOString().slice(0, 19).replace("T", " ");
    } catch (e) {
      return "--";
    }
  };

  const rows = trades.map((t) => {
    const side = (t.side || "").toLowerCase();
    const isBuy = side === "buy" || side === "long";
    const badgeClass = isBuy ? "pos-long" : "pos-short";
    const badgeText = isBuy ? "LONG" : "SHORT";

    const entry = t.price_entry ?? t.entry_price;
    const exit = t.price_exit ?? t.exit_price;
    const refPrice = exit || lastPriceRef || entry;
    const sl = t.sl ?? t.stop_loss;
    const tp = t.tp ?? t.take_profit;
    const qty = t.quantity ?? null;

    let pnl = null;
    if (entry != null && refPrice != null) {
      if (qty != null) {
        pnl = isBuy ? (refPrice - entry) * qty : (entry - refPrice) * qty;
      } else {
        pnl = isBuy ? refPrice - entry : entry - refPrice;
      }
    }

    let pnlClass = "pn-flat";
    if (pnl != null) {
      if (pnl > 0) pnlClass = "pn-up";
      else if (pnl < 0) pnlClass = "pn-down";
    }

    const timeEntry = t.time_entry || t.entry_time || t.open_time;
    const timeStr = fmtTs(timeEntry);
    const refLabel = exit ? "Saída" : "Último";

    return `
      <tr>
        <td>${t.symbol || "BTCUSDT"}</td>
        <td><span class="pos-badge ${badgeClass}">${badgeText}</span></td>
        <td>${fmt(entry)}</td>
        <td>${fmt(refPrice)} <span class="sub">(${refLabel})</span></td>
        <td>${fmt(sl)}</td>
        <td>${fmt(tp)}</td>
        <td class="${pnlClass}">${pnl != null ? fmt(pnl) : "--"}</td>
        <td class="sub">${timeStr}</td>
      </tr>
    `;
  });

  body.innerHTML = rows.join("");
}

function renderPositionsHistory(trades) {
  const body = document.getElementById("positions-body");
  if (!body) return;

  if (!Array.isArray(trades) || trades.length === 0) {
    body.innerHTML = `<tr><td colspan="8" style="text-align:center; padding:10px; color:#9ca3af;">Sem histórico...</td></tr>`;
    return;
  }

  const fmt = (v) => {
    if (v === null || v === undefined || Number.isNaN(Number(v))) return "--";
    return Number(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  };
  const fmtTs = (ts) => {
    if (!ts) return "--";
    try {
      if (typeof ts === "string") return ts;
      const d = new Date(ts * 1000);
      return d.toISOString().slice(0, 19).replace("T", " ");
    } catch (e) {
      return "--";
    }
  };

  const rows = trades.map((t) => {
    const side = (t.side || "").toLowerCase();
    const isBuy = side === "buy" || side === "long";
    const badgeClass = isBuy ? "pos-long" : "pos-short";
    const badgeText = isBuy ? "LONG" : "SHORT";

    const entry = t.price_entry ?? t.entry_price;
    const exit = t.price_exit ?? t.exit_price;
    const sl = t.sl ?? t.stop_loss;
    const tp = t.tp ?? t.take_profit;
    const qty = t.quantity ?? null;

    let pnl = t.pnl_exec ?? t.pnl_mid ?? null;
    if (pnl == null && entry != null && exit != null) {
      if (qty != null) {
        pnl = isBuy ? (exit - entry) * qty : (entry - exit) * qty;
      } else {
        pnl = isBuy ? exit - entry : entry - exit;
      }
    }

    let pnlClass = "pn-flat";
    if (pnl != null) {
      if (pnl > 0) pnlClass = "pn-up";
      else if (pnl < 0) pnlClass = "pn-down";
    }

    const timeExit = t.time_exit || t.exit_time || t.close_time;
    const timeStr = fmtTs(timeExit);

    return `
      <tr>
        <td>${t.symbol || "BTCUSDT"}</td>
        <td><span class="pos-badge ${badgeClass}">${badgeText}</span></td>
        <td>${fmt(entry)}</td>
        <td>${fmt(exit)}</td>
        <td>${fmt(sl)}</td>
        <td>${fmt(tp)}</td>
        <td class="${pnlClass}">${pnl != null ? fmt(pnl) : "--"}</td>
        <td class="sub">${timeStr}</td>
      </tr>
    `;
  });

  body.innerHTML = rows.join("");
}

function showTab(tab) {
  document.querySelectorAll(".pos-tab").forEach((el) => {
    el.classList.toggle("active", el.dataset.tab === tab);
  });

  const tableWrap = document.getElementById("positions-table-wrap");
  const equityArea = document.getElementById("equity-area");
  if (tab === "equity") {
    if (tableWrap) tableWrap.style.display = "none";
    if (equityArea) equityArea.style.display = "block";
    if (latestEquity) {
      updateEquityPanel(latestEquity);
    } else {
      const derived = computeLocalEquity();
      if (derived) updateEquityPanel(derived);
    }
  } else {
    if (tableWrap) tableWrap.style.display = "block";
    if (equityArea) equityArea.style.display = "none";
    const open = lastTradesCache.filter(t => !(t.time_exit || t.exit_time || t.close_time));
    const hist = lastTradesCache.filter(t => (t.time_exit || t.exit_time || t.close_time));
    if (tab === "open") renderPositionsOpen(open);
    if (tab === "history") renderPositionsHistory(hist);
  }
}

function initTabs() {
  document.querySelectorAll(".pos-tab").forEach((el) => {
    el.onclick = () => showTab(el.dataset.tab);
  });
}

// ======================================================
// FUNÇÕES AUXILIARES: EMA & RSI (calculadas no front)
// ======================================================
function calcEMA(values, period) {
  const k = 2 / (period + 1);
  const ema = [];
  let prev;

  for (let i = 0; i < values.length; i++) {
    const price = values[i];
    if (price == null) {
      ema.push(null);
      continue;
    }
    if (prev == null) {
      if (i < period - 1) {
        ema.push(null);
        continue;
      }
      // primeira EMA = média simples dos N anteriores
      let sum = 0;
      for (let j = i - period + 1; j <= i; j++) sum += values[j];
      prev = sum / period;
      ema.push(prev);
    } else {
      prev = price * k + prev * (1 - k);
      ema.push(prev);
    }
  }
  return ema;
}

function calcRSI(values, period = 14) {
  const rsi = new Array(values.length).fill(null);
  if (values.length < period + 1) return rsi;

  let gainSum = 0;
  let lossSum = 0;

  for (let i = 1; i <= period; i++) {
    const diff = values[i] - values[i - 1];
    if (diff >= 0) gainSum += diff;
    else lossSum -= diff;
  }

  let avgGain = gainSum / period;
  let avgLoss = lossSum / period;

  const firstRS = avgLoss === 0 ? Infinity : avgGain / avgLoss;
  rsi[period] = 100 - 100 / (1 + firstRS);

  for (let i = period + 1; i < values.length; i++) {
    const diff = values[i] - values[i - 1];
    const gain = diff > 0 ? diff : 0;
    const loss = diff < 0 ? -diff : 0;

    avgGain = (avgGain * (period - 1) + gain) / period;
    avgLoss = (avgLoss * (period - 1) + loss) / period;

    const rs = avgLoss === 0 ? Infinity : avgGain / avgLoss;
    rsi[i] = 100 - 100 / (1 + rs);
  }

  return rsi;
}

// ======================================================
// CREATE CHARTS
// ======================================================
function createCharts() {
  const priceEl = document.getElementById("pane-price");
  const volumeEl = document.getElementById("pane-volume");
  const rsiEl = document.getElementById("pane-rsi");

  if (!priceEl || !volumeEl || !rsiEl) {
    console.error("Pane(s) não encontrados no DOM");
    setDebug("ERRO: panes não encontrados");
    return;
  }

  const baseConfig = {
    layout: {
      background: { color: "#0b101a" },
      textColor: "#d1d4dc",
    },
    rightPriceScale: {
      borderColor: "#2a2e39",
    },
    timeScale: {
      borderColor: "#2a2e39",
      rightOffset: 10,
      barSpacing: 7,
      minBarSpacing: 3,
    },
    grid: {
      vertLines: { color: "#1e222d" },
      horzLines: { color: "#1e222d" },
    },
    crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
  };

  // =====================
  //  PREÇO (CANDLES + EMAs)
  // =====================
  priceChart = LightweightCharts.createChart(priceEl, {
    ...baseConfig,
  });

  candleSeries = priceChart.addCandlestickSeries({
    upColor: UP_COLOR_BODY,
    downColor: DOWN_COLOR_BODY,
    borderUpColor: UP_COLOR_BODY,
    borderDownColor: DOWN_COLOR_BODY,
    wickUpColor: UP_COLOR_WICK,
    wickDownColor: DOWN_COLOR_WICK,
  });

  // Attach FVG Primitive
  fvgPrimitive = new FVGPrimitive(priceChart, candleSeries);
  candleSeries.attachPrimitive(fvgPrimitive);

  ema50Series = priceChart.addLineSeries({
    color: "#ffeb3b",
    lineWidth: 2,
    priceLineVisible: false,
    title: "EMA 50",
  });

  priceChart.priceScale("right").applyOptions({
    scaleMargins: { top: 0.05, bottom: 0.05 },
  });

  // =====================
  //  VOLUME (PANE SEPARADO)
  // =====================
  volumeChart = LightweightCharts.createChart(volumeEl, {
    ...baseConfig,
    crosshair: { mode: LightweightCharts.CrosshairMode.Hidden },
  });

  volumeSeries = volumeChart.addHistogramSeries({
    priceFormat: { type: "volume" },
    color: "#6b7280",
  });

  volumeChart.priceScale("right").applyOptions({
    scaleMargins: { top: 0.05, bottom: 0.02 },
  });

  // =====================
  //  RSI (PANE SEPARADO)
  // =====================
  rsiChart = LightweightCharts.createChart(rsiEl, {
    ...baseConfig,
    crosshair: { mode: LightweightCharts.CrosshairMode.Hidden },
  });

  rsiSeries = rsiChart.addLineSeries({
    color: "#B26FFF",
    lineWidth: 2,
  });

  // Linhas de 30 e 70 usando priceLine da própria série
  rsiSeries.createPriceLine({
    price: 30,
    color: "rgba(124,179,66,0.5)",
    lineWidth: 1,
    lineStyle: LightweightCharts.LineStyle.Dotted,
    axisLabelVisible: false,
    title: "",
  });

  rsiSeries.createPriceLine({
    price: 70,
    color: "rgba(239,83,80,0.5)",
    lineWidth: 1,
    lineStyle: LightweightCharts.LineStyle.Dotted,
    axisLabelVisible: false,
    title: "",
  });

  // =====================
  // TOOLTIP FIXO (CANTO ESQUERDO SUPERIOR)
  // =====================
  const tooltip = document.createElement("div");
  tooltip.id = "price-tooltip";
  tooltip.style.position = "absolute";
  tooltip.style.top = "8px";
  tooltip.style.left = "8px";
  tooltip.style.padding = "6px 10px";
  tooltip.style.borderRadius = "6px";
  tooltip.style.background = "rgba(11,16,26,0.9)";
  tooltip.style.color = "#f5f5f5";
  tooltip.style.fontSize = "11px";
  tooltip.style.lineHeight = "1.4";
  tooltip.style.pointerEvents = "none";
  tooltip.style.zIndex = "20";
  tooltip.style.display = "none";
  priceEl.style.position = "relative";
  priceEl.appendChild(tooltip);

  function updateTooltip(param) {
    if (!param || !param.time) {
      tooltip.style.display = "none";
      return;
    }
    const data = param.seriesData.get(candleSeries);
    if (!data) {
      tooltip.style.display = "none";
      return;
    }

    const t = data.time;
    const ema50Val = ema50Map.get(t);
    const rsi = rsiMap.get(t);

    tooltip.innerHTML = `
      <div><strong>O</strong> ${data.open?.toFixed(2) ?? "-"}  
      <strong>H</strong> ${data.high?.toFixed(2) ?? "-"}</div>
      <div><strong>L</strong> ${data.low?.toFixed(2) ?? "-"}  
      <strong>C</strong> ${data.close?.toFixed(2) ?? "-"}</div>
      <div><strong>EMA 50</strong> ${ema50Val != null ? ema50Val.toFixed(2) : "-"}</div>
      <div><strong>RSI</strong> ${rsi != null ? rsi.toFixed(2) : "-"}</div>
      <div><strong>Vol</strong> ${data.volume != null ? data.volume.toFixed(3) : "-"}</div>
    `;
    tooltip.style.display = "block";
  }

  priceChart.subscribeCrosshairMove(updateTooltip);

  // =====================
  // ZOOM (sincronizar 3 charts)
  // =====================
  const zoomInBtn = document.getElementById("zoom-in");
  const zoomOutBtn = document.getElementById("zoom-out");

  function applyZoom(delta) {
    const tsMain = priceChart.timeScale();
    const opts = tsMain.options();
    const current = opts.barSpacing || 7;
    const next = Math.max(1, Math.min(50, current + delta));

    tsMain.applyOptions({ barSpacing: next });
    volumeChart.timeScale().applyOptions({ barSpacing: next });
    rsiChart.timeScale().applyOptions({ barSpacing: next });
  }

  if (zoomInBtn) zoomInBtn.onclick = () => applyZoom(1);
  if (zoomOutBtn) zoomOutBtn.onclick = () => applyZoom(-1);

  // =====================
  // SYNC SCROLL (preço → volume + rsi)
  // =====================
  const tsMain = priceChart.timeScale();
  const tsVol = volumeChart.timeScale();
  const tsRsi = rsiChart.timeScale();

  let syncing = false;

  tsMain.subscribeVisibleLogicalRangeChange((range) => {
    if (!range || syncing) return;
    syncing = true;
    tsVol.setVisibleLogicalRange(range);
    tsRsi.setVisibleLogicalRange(range);
    syncing = false;
  });

  // =====================
  // CLIQUES PARA DESENHO
  // =====================
  priceChart.subscribeClick((param) => {
    if (!drawingMode) return;
    if (!param || !param.point || !param.time) return;

    const price = candleSeries.coordinateToPrice(param.point.y);
    const time = param.time;
    if (price == null || time == null) return;

    if (drawingMode === "trendline") {
      handleTrendlineClick({ time, price });
    }
  });

  console.log("[OracleView] Charts criados");
  setDebug("Charts criados (v10)");
}

// ======================================================
// FUNÇÃO DE DESENHO — TRENDLINE
// ======================================================
function handleTrendlineClick(clicked) {
  const { time, price } = clicked;

  if (!firstPoint) {
    firstPoint = { time, price };
    console.log("[DRAW] Primeiro ponto:", firstPoint);
    return;
  }

  const secondPoint = { time, price };
  console.log("[DRAW] Segundo ponto:", secondPoint);

  const line = priceChart.addLineSeries({
    color: "#ffffff",
    lineWidth: 2,
    lastValueVisible: false,
    priceLineVisible: false,
  });

  line.setData([
    { time: firstPoint.time, value: firstPoint.price },
    { time: secondPoint.time, value: secondPoint.price },
  ]);

  drawnShapes.push(line);

  firstPoint = null;
  drawingMode = null;
  console.log("[DRAW] Trendline criada!");
}

// ======================================================
// MAP BACKEND DATA
// ======================================================
function mapBackendData(data) {
  const candles = data.map((c) => ({
    time: Number(c.time),
    open: Number(c.open),
    high: Number(c.high),
    low: Number(c.low),
    close: Number(c.close),
    volume: c.volume != null ? Number(c.volume) : 0,
  }));

  const last = candles.at(-1);
  setDebug(`Candles: ${candles.length} | Vol último: ${last?.volume ?? "n/a"}`);
  return candles;
}

// ======================================================
// FETCH & UPDATE CANDLES
// ======================================================
async function fetchCandles() {
  try {
    const res = await fetch("/api/candles");
    const raw = await res.json();

    if (!Array.isArray(raw) || raw.length === 0) {
      setDebug("Nenhum dado em /api/candles");
      return;
    }

    const candles = mapBackendData(raw);

    // ===== PREÇO =====
    const candleData = candles.map((c) => ({
      time: c.time,
      open: c.open,
      high: c.high,
      low: c.low,
      close: c.close,
      volume: c.volume,
    }));
    window.latestCandleTimes = candleData.map(c => c.time);

    candleSeries.setData(candleData);
    if (candleData.length > 0) {
      lastPriceRef = candleData[candleData.length - 1].close;
    }

    // ===== CALC EMA & RSI NO FRONT =====
    const closes = candles.map(c => c.close);

    const ema50 = calcEMA(closes, 50);   // EMA 50 da estratégia ICT
    const rsiVals = calcRSI(closes, 14);  // RSI 14

    ema50Map = new Map();
    rsiMap = new Map();

    const ema50Data = [];
    const rsiPoints = [];

    for (let i = 0; i < candles.length; i++) {
      const t = candles[i].time;

      if (ema50[i] != null) {
        ema50Data.push({ time: t, value: ema50[i] });
        ema50Map.set(t, ema50[i]);
      }
      if (rsiVals[i] != null) {
        rsiPoints.push({ time: t, value: rsiVals[i] });
        rsiMap.set(t, rsiVals[i]);
      }
    }

    ema50Series.setData(ema50Data);

    // ===== VOLUME =====
    volumeSeries.setData(
      candles.map(c => ({
        time: c.time,
        value: c.volume,
        color: c.close >= c.open
          ? "rgba(38,166,154,0.7)"
          : "rgba(239,83,80,0.7)",
      }))
    );

    // ===== RSI =====
    rsiSeries.setData(rsiPoints);

    if (firstLoad) {
      priceChart.timeScale().fitContent();
      volumeChart.timeScale().fitContent();
      rsiChart.timeScale().fitContent();
      firstLoad = false;
    }
  } catch (err) {
    console.error("Erro ao buscar /api/candles:", err);
    setDebug("Erro fetch /api/candles (ver console)");
  }
}

// ======================================================
// TRADES & MARKERS
// ======================================================
function renderPositionsOpen(trades) {
  const body = document.getElementById("positions-body");
  if (!body) return;

  if (!Array.isArray(trades) || trades.length === 0) {
    body.innerHTML = `<tr><td colspan="8" style="text-align:center; padding:10px; color:#9ca3af;">Sem posições...</td></tr>`;
    return;
  }

  const fmt = (v) => {
    if (v === null || v === undefined || Number.isNaN(Number(v))) return "--";
    return Number(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  };

  const fmtTs = (ts) => {
    if (!ts) return "--";
    try {
      if (typeof ts === "string") return ts;
      const d = new Date(ts * 1000);
      return d.toISOString().slice(0, 19).replace("T", " ");
    } catch (e) {
      return "--";
    }
  };

  const rows = trades.map((t) => {
    const side = (t.side || "").toLowerCase();
    const isBuy = side === "buy" || side === "long";
    const badgeClass = isBuy ? "pos-long" : "pos-short";
    const badgeText = isBuy ? "LONG" : "SHORT";

    const entry = t.price_entry ?? t.entry_price;
    const exit = t.price_exit ?? t.exit_price;
    const refPrice = exit || lastPriceRef || entry;
    const sl = t.sl ?? t.stop_loss;
    const tp = t.tp ?? t.take_profit;
    const qty = t.quantity ?? null;

    let pnl = null;
    if (entry != null && refPrice != null) {
      if (qty != null) {
        pnl = isBuy ? (refPrice - entry) * qty : (entry - refPrice) * qty;
      } else {
        pnl = isBuy ? refPrice - entry : entry - refPrice;
      }
    }

    let pnlClass = "pn-flat";
    if (pnl != null) {
      if (pnl > 0) pnlClass = "pn-up";
      else if (pnl < 0) pnlClass = "pn-down";
    }

    const timeEntry = t.time_entry || t.entry_time || t.open_time;
    const timeStr = fmtTs(timeEntry);
    const refLabel = exit ? "Saída" : "Último";

    return `
      <tr>
        <td>${t.symbol || "BTCUSDT"}</td>
        <td><span class="pos-badge ${badgeClass}">${badgeText}</span></td>
        <td>${fmt(entry)}</td>
        <td>${fmt(refPrice)} <span class="sub">(${refLabel})</span></td>
        <td>${fmt(sl)}</td>
        <td>${fmt(tp)}</td>
        <td class="${pnlClass}">${pnl != null ? fmt(pnl) : "--"}</td>
        <td class="sub">${timeStr}</td>
      </tr>
    `;
  });

  body.innerHTML = rows.join("");
}

function renderPositionsHistory(trades) {
  const body = document.getElementById("positions-body");
  if (!body) return;

  if (!Array.isArray(trades) || trades.length === 0) {
    body.innerHTML = `<tr><td colspan="8" style="text-align:center; padding:10px; color:#9ca3af;">Sem histórico...</td></tr>`;
    return;
  }

  const fmt = (v) => {
    if (v === null || v === undefined || Number.isNaN(Number(v))) return "--";
    return Number(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  };
  const fmtTs = (ts) => {
    if (!ts) return "--";
    try {
      if (typeof ts === "string") return ts;
      const d = new Date(ts * 1000);
      return d.toISOString().slice(0, 19).replace("T", " ");
    } catch (e) {
      return "--";
    }
  };

  const rows = trades.map((t) => {
    const side = (t.side || "").toLowerCase();
    const isBuy = side === "buy" || side === "long";
    const badgeClass = isBuy ? "pos-long" : "pos-short";
    const badgeText = isBuy ? "LONG" : "SHORT";

    const entry = t.price_entry ?? t.entry_price;
    const exit = t.price_exit ?? t.exit_price;
    const sl = t.sl ?? t.stop_loss;
    const tp = t.tp ?? t.take_profit;
    const qty = t.quantity ?? null;

    let pnl = t.pnl_exec ?? t.pnl_mid ?? null;
    if (pnl == null && entry != null && exit != null) {
      if (qty != null) {
        pnl = isBuy ? (exit - entry) * qty : (entry - exit) * qty;
      } else {
        pnl = isBuy ? exit - entry : entry - exit;
      }
    }

    let pnlClass = "pn-flat";
    if (pnl != null) {
      if (pnl > 0) pnlClass = "pn-up";
      else if (pnl < 0) pnlClass = "pn-down";
    }

    const timeExit = t.time_exit || t.exit_time || t.close_time;
    const timeStr = fmtTs(timeExit);

    return `
      <tr>
        <td>${t.symbol || "BTCUSDT"}</td>
        <td><span class="pos-badge ${badgeClass}">${badgeText}</span></td>
        <td>${fmt(entry)}</td>
        <td>${fmt(exit)}</td>
        <td>${fmt(sl)}</td>
        <td>${fmt(tp)}</td>
        <td class="${pnlClass}">${pnl != null ? fmt(pnl) : "--"}</td>
        <td class="sub">${timeStr}</td>
      </tr>
    `;
  });

  body.innerHTML = rows.join("");
}

function showTab(tab) {
  document.querySelectorAll(".pos-tab").forEach((el) => {
    el.classList.toggle("active", el.dataset.tab === tab);
  });

  const tableWrap = document.getElementById("positions-table-wrap");
  const equityArea = document.getElementById("equity-area");
  if (tab === "equity") {
    if (tableWrap) tableWrap.style.display = "none";
    if (equityArea) equityArea.style.display = "block";
    if (latestEquity) updateEquityPanel(latestEquity);
  } else {
    if (tableWrap) tableWrap.style.display = "block";
    if (equityArea) equityArea.style.display = "none";
    const open = lastTradesCache.filter(t => !(t.time_exit || t.exit_time || t.close_time));
    const hist = lastTradesCache.filter(t => (t.time_exit || t.exit_time || t.close_time));
    if (tab === "open") renderPositionsOpen(open);
    if (tab === "history") renderPositionsHistory(hist);
  }
}

function initTabs() {
  document.querySelectorAll(".pos-tab").forEach((el) => {
    el.onclick = () => showTab(el.dataset.tab);
  });
}

async function fetchTrades() {
  try {
    const res = await fetch("/api/trades");
    if (!res.ok) return;
    const trades = await res.json();

    if (Array.isArray(trades)) {
      lastTradesCache = trades;
      renderTradeMarkers(trades);
      const activeTab = document.querySelector(".pos-tab.active")?.dataset?.tab || "open";
      showTab(activeTab);
    }
  } catch (e) {
    console.error("Erro ao buscar /api/trades", e);
  }
}

// ======================================================
// EQUITY
// ======================================================
async function fetchEquity() {
  try {
    const res = await fetch("/api/equity");
    if (!res.ok) {
      // Fallback: se a rota não existir (404), tenta derivar do último preço + posição aberta
      if (res.status === 404) {
        const derived = computeLocalEquity();
        if (derived) updateEquityPanel(derived);
      }
      return;
    }
    const data = await res.json();
    latestEquity = data;
    updateEquityPanel(data);
  } catch (e) {
    // Fallback silencioso
    const derived = computeLocalEquity();
    if (derived) updateEquityPanel(derived);
  }
}

// ======================================================
// GERENCIAMENTO DE LINHAS DE SL/TP (PriceLines)
// ======================================================
// Armazena as linhas ativas para poder removê-las depois
window.activePriceLines = window.activePriceLines || [];
window.activeLineSeries = window.activeLineSeries || [];

function clearAllTradeLines() {
  // Remove todas as price lines (SL/TP)
  if (window.activePriceLines) {
    window.activePriceLines.forEach(line => {
      try {
        candleSeries.removePriceLine(line);
      } catch (e) {
        // Linha já removida, ignora
      }
    });
    window.activePriceLines = [];
  }

  // Remove todas as line series (linhas conectoras)
  if (window.activeLineSeries && priceChart) {
    window.activeLineSeries.forEach(series => {
      try {
        priceChart.removeSeries(series);
      } catch (e) {
        // Série já removida, ignora
      }
    });
    window.activeLineSeries = [];
  }
}

function renderTradeMarkers(trades) {
  if (!candleSeries) return;

  const markers = [];

  // 🧹 Limpa todas as linhas antigas antes de desenhar novas
  clearAllTradeLines();

  trades.forEach(t => {
    // Fallback de nomes de propriedades
    const entryTime = t.time_entry || t.entry_time || t.open_time;
    const exitTime = t.time_exit || t.exit_time || t.close_time;
    const entryPrice = t.price_entry || t.entry_price || t.open_price;
    const exitPrice = t.price_exit || t.exit_price || t.close_price;
    const side = t.side || "buy"; // buy ou sell

    // ✅ Extrai SL e TP
    const sl = t.sl || t.stop_loss;
    const tp = t.tp || t.take_profit;

    // 🎯 MARKER DE ENTRADA (seta premium com emoji)
    if (entryTime && entryPrice) {
      const isBuy = side === "buy";
      markers.push({
        time: Number(entryTime),
        position: isBuy ? "belowBar" : "aboveBar",
        color: isBuy ? "#00E676" : "#FF1744", // Verde neon / Vermelho vibrante
        shape: isBuy ? "arrowUp" : "arrowDown",
        text: isBuy ? "🟢 LONG" : "🔴 SHORT",
        size: 2,
      });
    }

    // 🏁 MARKER DE SAÍDA (seta premium com emoji)
    if (exitTime && exitPrice) {
      const isBuy = side === "buy";

      // Calcula se foi lucro ou prejuízo
      const isProfitable = isBuy
        ? exitPrice > entryPrice
        : exitPrice < entryPrice;

      markers.push({
        time: Number(exitTime),
        position: isBuy ? "aboveBar" : "belowBar",
        color: isProfitable ? "#FFD700" : "#9E9E9E", // Dourado se lucro, cinza se loss
        shape: isBuy ? "arrowDown" : "arrowUp",
        text: isProfitable ? "💰 WIN" : "❌ LOSS",
        size: 2,
      });

      // 📏 LINHA CONECTORA entre entrada e saída (linha pontilhada)
      if (entryTime && entryPrice) {
        try {
          const connectorLine = priceChart.addLineSeries({
            color: isProfitable ? "rgba(0, 230, 118, 0.4)" : "rgba(255, 23, 68, 0.4)",
            lineWidth: 1,
            lineStyle: LightweightCharts.LineStyle.Dotted,
            lastValueVisible: false,
            priceLineVisible: false,
          });

          connectorLine.setData([
            { time: Number(entryTime), value: entryPrice },
            { time: Number(exitTime), value: exitPrice }
          ]);

          window.activeLineSeries.push(connectorLine);
        } catch (e) {
          console.warn("[TRADES] Erro ao criar linha conectora:", e);
        }
      }
    }

    // 📍 LINHA DE ENTRADA (mostra enquanto o trade estiver aberto)
    if (entryPrice && entryTime && !exitTime) {
      try {
        const entryVal = Number(entryPrice);
        if (!Number.isFinite(entryVal)) {
          throw new Error("entryPrice inválido para priceLine");
        }

        const entryLine = candleSeries.createPriceLine({
          price: entryVal,
          color: '#FFFFFF',
          lineWidth: 2,
          lineStyle: LightweightCharts.LineStyle.Dashed,
          axisLabelVisible: true,
          title: 'ENTRY',
        });
        window.activePriceLines.push(entryLine);
      } catch (e) {
        console.warn("[TRADES] Erro ao criar ENTRY line:", e);
      }
    }

    // 🛑 LINHA DE STOP LOSS (só mostra se trade ainda não fechou)
    if (sl && !exitTime) {
      try {
        const slLine = candleSeries.createPriceLine({
          price: sl,
          color: '#FF1744', // Vermelho vibrante
          lineWidth: 2,
          lineStyle: LightweightCharts.LineStyle.Dashed,
          axisLabelVisible: true,
          title: '🛑 SL',
        });
        window.activePriceLines.push(slLine);
      } catch (e) {
        console.warn("[TRADES] Erro ao criar SL line:", e);
      }
    }

    // 🎯 LINHA DE TAKE PROFIT (só mostra se trade ainda não fechou)
    if (tp && !exitTime) {
      try {
        const tpLine = candleSeries.createPriceLine({
          price: tp,
          color: '#00E676', // Verde neon
          lineWidth: 2,
          lineStyle: LightweightCharts.LineStyle.Dashed,
          axisLabelVisible: true,
          title: '🎯 TP',
        });
        window.activePriceLines.push(tpLine);
      } catch (e) {
        console.warn("[TRADES] Erro ao criar TP line:", e);
      }
    }
  });

  // Atualiza markers na série de candles
  candleSeries.setMarkers(markers);

  // Log para debug
  if (markers.length > 0) {
    console.log(`[TRADES] Renderizados ${markers.length} markers, ${window.activePriceLines.length} price lines, ${window.activeLineSeries.length} connectors`);
  }
}

// ======================================================
// FVG FETCH
// ======================================================
async function fetchFVG() {
  try {
    const res = await fetch("/api/fvg");
    if (!res.ok) return;
    const raw = await res.json();

    if (fvgPrimitive && Array.isArray(raw)) {
      const candleTimes = Array.isArray(window.latestCandleTimes) ? window.latestCandleTimes : [];

      function snapTime(ts) {
        if (!Number.isFinite(ts) || candleTimes.length === 0) return ts;
        if (candleTimes.includes(ts)) return ts;
        // Escolhe o candle mais próximo para garantir coordenada
        let nearest = candleTimes[0];
        let bestDiff = Math.abs(ts - nearest);
        for (let i = 1; i < candleTimes.length; i++) {
          const diff = Math.abs(ts - candleTimes[i]);
          if (diff < bestDiff) {
            bestDiff = diff;
            nearest = candleTimes[i];
          }
        }
        return nearest;
      }

      // Normaliza tipos para evitar problemas de coordenada/time
      const data = raw
        .map(f => ({
          ...f,
          start_time: f.start_time != null ? snapTime(Number(f.start_time)) : null,
          end_time: f.end_time != null ? snapTime(Number(f.end_time)) : null,
          top: f.top != null ? Number(f.top) : null,
          bottom: f.bottom != null ? Number(f.bottom) : null,
          mid: f.mid != null ? Number(f.mid) : null,
        }))
        .filter(f => Number.isFinite(f.start_time));

      fvgPrimitive.setData(data);
    }
  } catch (e) {
    console.error("Erro ao buscar /api/fvg", e);
  }
}

// ======================================================
// INIT
// ======================================================
function initOracleView() {
  console.log("[OracleView] initOracleView chamado");
  createCharts();
  initTabs();
  initPositionResizer();
  showTab("open");
  fetchCandles();
  fetchTrades();
  fetchFVG();
  fetchEquity();
  setInterval(() => {
    fetchCandles();
    fetchTrades();
    fetchFVG();
    fetchEquity();
  }, 1000);
}

// Garante que o init rode mesmo se o load já tiver acontecido
if (document.readyState === "complete" || document.readyState === "interactive") {
  setTimeout(initOracleView, 0);
} else {
  window.addEventListener("load", initOracleView);
}

// ======================================================
// ORDERBOOK
// ======================================================
async function fetchOrderBook() {
  try {
    const res = await fetch("/api/orderbook");
    if (!res.ok) return;
    const data = await res.json();

    const bids = data.bids || [];
    const asks = data.asks || [];

    const obAsks = document.getElementById("ob-asks");
    const obBids = document.getElementById("ob-bids");
    const obLast = document.getElementById("ob-midprice");

    if (!obAsks || !obBids || !obLast) return;

    const allSizes = [...bids, ...asks].map(x => Number(x[1]));
    const maxSize = Math.max(...allSizes, 1e-9);

    obAsks.innerHTML = "";
    obBids.innerHTML = "";

    // ASKS (ordem decrescente, como Binance)
    const asksSorted = [...asks].sort((a, b) => Number(b[0]) - Number(a[0]));
    asksSorted.forEach(([p, s]) => {
      const price = Number(p);
      const size = Number(s);

      const row = document.createElement("div");
      row.className = "ob-row";

      const bar = document.createElement("div");
      bar.className = "ob-bar ask";
      bar.style.width = (size / maxSize) * 100 + "%";
      row.appendChild(bar);

      const content = document.createElement("div");
      content.className = "ob-content";
      content.innerHTML = `
        <span class="ob-price ask">${price.toFixed(1)}</span>
        <span class="ob-size">${size.toFixed(3)}</span>
      `;
      row.appendChild(content);

      obAsks.appendChild(row);
    });

    // BIDS (ordem decrescente)
    const bidsSorted = [...bids].sort((a, b) => Number(b[0]) - Number(a[0]));
    bidsSorted.forEach(([p, s]) => {
      const price = Number(p);
      const size = Number(s);

      const row = document.createElement("div");
      row.className = "ob-row";

      const bar = document.createElement("div");
      bar.className = "ob-bar bid";
      bar.style.width = (size / maxSize) * 100 + "%";
      row.appendChild(bar);

      const content = document.createElement("div");
      content.className = "ob-content";
      content.innerHTML = `
          <span class="price ${side}">${price.toFixed(1)}</span>
          <span class="amount">${size.toFixed(3)}</span>
          <span class="total">${(price * size).toFixed(2)}</span>
      `;
      row.appendChild(content);

      obBids.appendChild(row);
    });

    if (bidsSorted.length && asksSorted.length) {
      const bestBid = Number(bidsSorted[0][0]);
      const bestAsk = Number(asksSorted[0][0]);
      const mid = (bestBid + bestAsk) / 2;
      obLast.textContent = mid.toFixed(1);
    }
  } catch (e) {
    console.error("Erro carregando /api/orderbook", e);
  }
}

// atualiza a cada 300ms
setInterval(fetchOrderBook, 300);
