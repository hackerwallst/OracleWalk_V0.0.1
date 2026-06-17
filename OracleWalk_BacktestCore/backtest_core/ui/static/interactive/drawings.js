import { formatPrice, normalizeTime } from "./chart.js";

const STORAGE_KEY = "oraclewalk.interactive.drawings.v1";
const DRAW_TOOLS = new Set(["trend", "horizontal", "ray", "vertical", "fib", "text", "brush", "measure", "eraser"]);

export class DrawingLayer {
  constructor({ overlay, chart, onStatus }) {
    this.overlay = overlay;
    this.chart = chart;
    this.onStatus = onStatus || (() => {});
    this.tool = "cursor";
    this.drawings = [];
    this.selectedId = null;
    this.active = null;
    this.drag = null;
    this.syncFrame = 0;
    this.lastSignature = "";
  }

  init() {
    this.load();
    this.overlay.addEventListener("pointerdown", (event) => this.pointerDown(event));
    window.addEventListener("pointermove", (event) => this.pointerMove(event));
    window.addEventListener("pointerup", () => this.pointerUp());
    this.startSyncLoop();
  }

  setTool(tool) {
    this.tool = DRAW_TOOLS.has(tool) ? tool : "cursor";
    this.overlay.classList.toggle("active", this.tool !== "cursor");
    this.overlay.dataset.tool = this.tool;
  }

  clear() {
    this.drawings = [];
    this.save();
    this.render();
    this.onStatus("Desenhos removidos");
  }

  startSyncLoop() {
    const tick = () => {
      this.syncFrame = requestAnimationFrame(tick);
      const signature = this.viewportSignature();
      if (signature !== this.lastSignature) {
        this.lastSignature = signature;
        this.render();
      }
    };
    this.syncFrame = requestAnimationFrame(tick);
  }

  viewportSignature() {
    const ref = this.chart.lastBar?.();
    const price = Number.isFinite(Number(ref?.close)) ? Number(ref.close) : 1;
    return [
      this.chart.timeToX(ref?.time),
      this.chart.priceToY(price),
      this.chart.priceToY(price * 1.001 || price + 1),
      this.overlay.clientWidth,
      this.overlay.clientHeight,
      this.drawings.length,
      this.tool,
    ].join("|");
  }

  pointerDown(event) {
    const drawingId = event.target?.dataset?.drawingId;
    if (this.tool === "cursor") {
      if (!drawingId) return;
      event.preventDefault();
      event.stopPropagation();
      this.startMove(event, drawingId);
      return;
    }
    event.preventDefault();
    const point = this.chartPoint(event);
    if (!point) return;
    if (this.tool === "eraser") {
      if (drawingId) {
        this.deleteDrawing(drawingId);
        return;
      }
      this.eraseNear(event);
      return;
    }
    if (this.tool === "horizontal") {
      this.drawings.push({ id: uid(), type: "horizontal", price: point.price, screenYRatio: point.screenYRatio });
      this.saveAndRender("Linha horizontal");
      return;
    }
    if (this.tool === "vertical") {
      this.drawings.push({ id: uid(), type: "vertical", time: point.time, screenXRatio: point.screenXRatio });
      this.saveAndRender("Linha vertical");
      return;
    }
    if (this.tool === "text") {
      const text = window.prompt("Texto do grafico", "Nota");
      if (!text) return;
      this.drawings.push({ id: uid(), type: "text", ...point, text: text.slice(0, 80) });
      this.saveAndRender("Texto criado");
      return;
    }
    this.active = {
      id: uid(),
      type: this.tool,
      start: point,
      end: point,
      points: this.tool === "brush" ? [point] : undefined,
    };
    this.render();
  }

  pointerMove(event) {
    if (this.drag) {
      this.moveSelected(event);
      return;
    }
    if (!this.active) return;
    const point = this.chartPoint(event);
    if (!point) return;
    this.active.end = point;
    if (this.active.type === "brush") this.active.points.push(point);
    this.render();
  }

  pointerUp() {
    if (this.drag) {
      this.drag = null;
      this.save();
      this.onStatus("Desenho atualizado");
      return;
    }
    if (!this.active) return;
    const active = this.active;
    this.active = null;
    if (active.type !== "brush" && samePoint(active.start, active.end)) {
      this.render();
      return;
    }
    this.drawings.push(active);
    this.saveAndRender(labelForType(active.type));
  }

  startMove(event, id) {
    const drawing = this.drawings.find((item) => item.id === id);
    if (!drawing) return;
    this.selectedId = id;
    const point = this.chartPoint(event);
    const screen = this.screenPoint(event);
    this.drag = {
      id,
      startPoint: point,
      startScreen: screen,
      original: structuredCloneSafe(drawing),
    };
    this.render();
  }

  moveSelected(event) {
    const drawing = this.drawings.find((item) => item.id === this.drag.id);
    if (!drawing) return;
    const point = this.chartPoint(event);
    const screen = this.screenPoint(event);
    const original = this.drag.original;
    const deltaPrice = Number.isFinite(point?.price) && Number.isFinite(this.drag.startPoint?.price)
      ? point.price - this.drag.startPoint.price
      : 0;
    const deltaTime = Number.isFinite(point?.time) && Number.isFinite(this.drag.startPoint?.time)
      ? normalizeTime(point.time) - normalizeTime(this.drag.startPoint.time)
      : 0;
    const deltaScreenX = screen.xRatio - this.drag.startScreen.xRatio;
    const deltaScreenY = screen.yRatio - this.drag.startScreen.yRatio;
    moveDrawing(drawing, original, { deltaPrice, deltaTime, deltaScreenX, deltaScreenY });
    this.render();
  }

  chartPoint(event) {
    const rect = this.overlay.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    let time = this.chart.xToTime?.(x);
    if (time == null) {
      const cursor = this.chart.xToCursor?.(x);
      time = Number.isFinite(cursor) ? this.chart.getBarTimeByIndex?.(cursor) : null;
    }
    if (time == null) time = this.chart.lastBar?.()?.time ?? null;
    let price = this.chart.yToPrice?.(y);
    if (!Number.isFinite(price)) price = this.estimatedPriceFromY(y);
    const screen = {
      screenXRatio: x / Math.max(1, rect.width),
      screenYRatio: y / Math.max(1, rect.height),
    };
    if (time == null || !Number.isFinite(price)) return screen;
    return { time, price, ...screen };
  }

  screenPoint(event) {
    const rect = this.overlay.getBoundingClientRect();
    return {
      xRatio: (event.clientX - rect.left) / Math.max(1, rect.width),
      yRatio: (event.clientY - rect.top) / Math.max(1, rect.height),
    };
  }

  estimatedPriceFromY(y) {
    const close = Number(this.chart.lastBar?.()?.close);
    if (!Number.isFinite(close)) return NaN;
    const height = Math.max(1, this.overlay.clientHeight || 1);
    const spanPct = Math.abs(close) >= 10 ? 0.08 : 0.012;
    return close * (1 + ((height / 2 - y) / height) * spanPct);
  }

  eraseNear(event) {
    const rect = this.overlay.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    const before = this.drawings.length;
    this.drawings = this.drawings.filter((drawing) => distanceToDrawing(drawing, x, y, this.chart) > 14);
    if (this.drawings.length !== before) this.saveAndRender("Desenho apagado");
  }

  deleteDrawing(id) {
    const before = this.drawings.length;
    this.drawings = this.drawings.filter((drawing) => drawing.id !== id);
    if (this.selectedId === id) this.selectedId = null;
    if (this.drawings.length !== before) this.saveAndRender("Desenho apagado");
  }

  saveAndRender(message) {
    this.save();
    this.render();
    this.onStatus(`${message} salvo no layout local`);
  }

  render() {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("class", "drawing-svg");
    svg.setAttribute("width", String(this.overlay.clientWidth || 1));
    svg.setAttribute("height", String(this.overlay.clientHeight || 1));
    svg.append(...[...this.drawings, this.active].filter(Boolean).flatMap((drawing) => {
      const selected = drawing.id === this.selectedId;
      return renderDrawing(drawing, this.chart, selected);
    }));

    const labels = [...this.drawings, this.active].filter(Boolean)
      .flatMap((drawing) => renderLabels(drawing, this.chart, drawing.id === this.selectedId));
    this.overlay.replaceChildren(svg, ...labels);
  }

  load() {
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      const parsed = raw ? JSON.parse(raw) : [];
      this.drawings = Array.isArray(parsed) ? parsed : [];
    } catch {
      this.drawings = [];
    }
  }

  save() {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(this.drawings));
    } catch {
      /* localStorage can be disabled; drawing still works for this session. */
    }
  }
}

function renderDrawing(drawing, chart, selected = false) {
  if (!drawing) return [];
  if (drawing.type === "horizontal") return tagElements([line(0, pointY(drawing, chart), 99999, pointY(drawing, chart), `drawing-line horizontal${selected ? " selected" : ""}`)], drawing);
  if (drawing.type === "vertical") return tagElements([line(pointX(drawing, chart), 0, pointX(drawing, chart), 99999, `drawing-line vertical${selected ? " selected" : ""}`)], drawing);
  if (drawing.type === "brush") return tagElements([polyline((drawing.points || []).map((point) => [pointX(point, chart), pointY(point, chart)]), `drawing-line brush${selected ? " selected" : ""}`)], drawing);
  const start = drawing.start;
  const end = drawing.end;
  if (!start || !end) return [];
  if (drawing.type === "fib") return tagElements(renderFib(start, end, chart, selected), drawing);
  if (drawing.type === "ray") {
    const x1 = pointX(start, chart);
    const y1 = pointY(start, chart);
    const x2 = pointX(end, chart);
    const y2 = pointY(end, chart);
    const dx = Math.max(1, x2 - x1);
    const slope = (y2 - y1) / dx;
    return tagElements([line(x1, y1, 99999, y1 + slope * (99999 - x1), `drawing-line ray${selected ? " selected" : ""}`)], drawing);
  }
  return tagElements([line(pointX(start, chart), pointY(start, chart), pointX(end, chart), pointY(end, chart), `drawing-line ${drawing.type}${selected ? " selected" : ""}`)], drawing);
}

function renderLabels(drawing, chart, selected = false) {
  if (drawing.type === "text") {
    const label = document.createElement("div");
    label.className = `drawing-label text${selected ? " selected" : ""}`;
    label.dataset.drawingId = drawing.id;
    label.style.left = `${pointX(drawing, chart)}px`;
    label.style.top = `${pointY(drawing, chart)}px`;
    label.textContent = drawing.text || "Nota";
    return [label];
  }
  if (drawing.type !== "measure" || !drawing.start || !drawing.end) return [];
  const label = document.createElement("div");
  label.className = `drawing-label measure${selected ? " selected" : ""}`;
  label.dataset.drawingId = drawing.id;
  const x1 = pointX(drawing.start, chart);
  const x2 = pointX(drawing.end, chart);
  const y1 = pointY(drawing.start, chart);
  const y2 = pointY(drawing.end, chart);
  const delta = drawing.end.price - drawing.start.price;
  const pct = drawing.start.price ? (delta / drawing.start.price) * 100 : 0;
  label.style.left = `${(x1 + x2) / 2}px`;
  label.style.top = `${(y1 + y2) / 2}px`;
  label.textContent = `${formatPrice(delta)} (${pct.toFixed(2)}%)`;
  return [label];
}

function renderFib(start, end, chart, selected = false) {
  const x1 = pointX(start, chart);
  const x2 = pointX(end, chart);
  const minX = Math.min(x1, x2);
  const maxX = Math.max(x1, x2);
  const levels = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1];
  return levels.map((level) => {
    const price = start.price + (end.price - start.price) * level;
    const el = line(minX, y(price, chart), maxX, y(price, chart), `drawing-line fib${selected ? " selected" : ""}`);
    el.dataset.level = String(level);
    return el;
  });
}

function line(x1, y1, x2, y2, className) {
  const el = document.createElementNS("http://www.w3.org/2000/svg", "line");
  el.setAttribute("x1", finite(x1));
  el.setAttribute("y1", finite(y1));
  el.setAttribute("x2", finite(x2));
  el.setAttribute("y2", finite(y2));
  el.setAttribute("class", className);
  return el;
}

function polyline(points, className) {
  const el = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
  el.setAttribute("points", points.map(([px, py]) => `${finite(px)},${finite(py)}`).join(" "));
  el.setAttribute("class", className);
  el.setAttribute("fill", "none");
  return el;
}

function tagElements(elements, drawing) {
  for (const el of elements) {
    el.dataset.drawingId = drawing.id;
  }
  return elements;
}

function moveDrawing(drawing, original, delta) {
  if (drawing.type === "horizontal") {
    shiftPoint(drawing, original, delta, { x: false, y: true });
    return;
  }
  if (drawing.type === "vertical") {
    shiftPoint(drawing, original, delta, { x: true, y: false });
    return;
  }
  if (drawing.type === "text") {
    shiftPoint(drawing, original, delta);
    return;
  }
  if (drawing.type === "brush") {
    drawing.points = (original.points || []).map((point) => shiftedPoint(point, delta));
    return;
  }
  if (drawing.start && drawing.end && original.start && original.end) {
    drawing.start = shiftedPoint(original.start, delta);
    drawing.end = shiftedPoint(original.end, delta);
  }
}

function shiftPoint(target, original, delta, axes = { x: true, y: true }) {
  const shifted = shiftedPoint(original, delta, axes);
  Object.assign(target, shifted);
}

function shiftedPoint(point, delta, axes = { x: true, y: true }) {
  const next = { ...point };
  if (axes.x && Number.isFinite(Number(point.screenXRatio))) {
    next.screenXRatio = clamp01(Number(point.screenXRatio) + delta.deltaScreenX);
  }
  if (axes.x && Number.isFinite(Number(point.time)) && Number.isFinite(delta.deltaTime)) {
    next.time = normalizeTime(point.time) + delta.deltaTime;
  }
  if (axes.y && Number.isFinite(Number(point.screenYRatio))) {
    next.screenYRatio = clamp01(Number(point.screenYRatio) + delta.deltaScreenY);
  }
  if (axes.y && Number.isFinite(Number(point.price))) {
    next.price = Number(point.price) + delta.deltaPrice;
  }
  return next;
}

function structuredCloneSafe(value) {
  if (typeof structuredClone === "function") return structuredClone(value);
  return JSON.parse(JSON.stringify(value));
}

function clamp01(value) {
  if (!Number.isFinite(value)) return value;
  return Math.max(0, Math.min(1, value));
}

function distanceToDrawing(drawing, px, py, chart) {
  const points = [];
  if (drawing.type === "horizontal") points.push([px, pointY(drawing, chart)]);
  else if (drawing.type === "vertical") points.push([pointX(drawing, chart), py]);
  else if (drawing.type === "text") points.push([pointX(drawing, chart), pointY(drawing, chart)]);
  else if (drawing.type === "brush") points.push(...(drawing.points || []).map((point) => [pointX(point, chart), pointY(point, chart)]));
  else if (drawing.start && drawing.end) points.push([pointX(drawing.start, chart), pointY(drawing.start, chart)], [pointX(drawing.end, chart), pointY(drawing.end, chart)]);
  return Math.min(...points.map(([x1, y1]) => Math.hypot(x1 - px, y1 - py)), Number.POSITIVE_INFINITY);
}

function pointX(point, chart) {
  const anchored = point?.time != null ? x(point.time, chart) : NaN;
  if (Number.isFinite(anchored) && anchored > -9000) return anchored;
  return finite(Number(point?.screenXRatio) * (chart.container?.clientWidth || 1));
}

function pointY(point, chart) {
  const anchored = point?.price != null ? y(point.price, chart) : NaN;
  if (Number.isFinite(anchored) && anchored > -9000) return anchored;
  return finite(Number(point?.screenYRatio) * (chart.container?.clientHeight || 1));
}

function x(time, chart) {
  return finite(chart.timeToX?.(normalizeTime(time)));
}

function y(price, chart) {
  return finite(chart.priceToY?.(price));
}

function finite(value) {
  return Number.isFinite(Number(value)) ? Number(value) : -9999;
}

function uid() {
  return `d${Date.now().toString(36)}${Math.random().toString(36).slice(2, 7)}`;
}

function samePoint(a, b) {
  if (a.time != null && b.time != null && a.price != null && b.price != null) {
    return normalizeTime(a.time) === normalizeTime(b.time) && Math.abs(Number(a.price) - Number(b.price)) < 1e-12;
  }
  return Math.abs(Number(a.screenXRatio) - Number(b.screenXRatio)) < 0.0001
    && Math.abs(Number(a.screenYRatio) - Number(b.screenYRatio)) < 0.0001;
}

function labelForType(type) {
  const labels = {
    trend: "Linha de tendencia",
    ray: "Raio",
    fib: "Fibonacci",
    brush: "Brush",
    measure: "Regua",
  };
  return labels[type] || "Desenho";
}
