import { formatPrice, normalizeBar } from "./chart.js";

const VALUE_AREA_RATIO = 0.7;

export class VolumeProfile {
  constructor({ overlay, chart, onStatus }) {
    this.overlay = overlay;
    this.chart = chart;
    this.onStatus = onStatus || (() => {});
    this.enabled = true;
    this.mode = "visible";
    this.rangeStart = null;
    this.rangeEnd = null;
    this.rows = 64;
    this.widthRatio = 0.27;
    this.minWidth = 150;
    this.maxWidth = 310;
    this.lastSignature = "";
    this.frame = 0;
  }

  init() {
    this.startLoop();
  }

  setEnabled(enabled) {
    this.enabled = Boolean(enabled);
    this.overlay.classList.toggle("disabled", !this.enabled);
    if (!this.enabled) {
      this.overlay.replaceChildren();
      this.onStatus("Volume Profile oculto");
      return;
    }
    this.render(true);
    this.onStatus("Volume Profile ativo");
  }

  setVisibleRangeMode() {
    this.mode = "visible";
    this.rangeStart = null;
    this.rangeEnd = null;
    this.render(true);
  }

  setFixedRange(startTime, endTime = null) {
    this.mode = "fixed";
    this.rangeStart = startTime;
    this.rangeEnd = endTime;
    this.render(true);
  }

  completeFixedRange(endTime) {
    if (this.rangeStart == null) return;
    this.rangeEnd = endTime;
    if (this.rangeEnd < this.rangeStart) {
      const tmp = this.rangeStart;
      this.rangeStart = this.rangeEnd;
      this.rangeEnd = tmp;
    }
    this.mode = "fixed";
    this.render(true);
  }

  startLoop() {
    const tick = () => {
      this.frame = requestAnimationFrame(tick);
      if (!this.enabled) return;
      const signature = this.signature();
      if (signature !== this.lastSignature) {
        this.lastSignature = signature;
        this.render();
      }
    };
    this.frame = requestAnimationFrame(tick);
  }

  signature() {
    const bars = this.chart.visibleBars?.() || [];
    const first = bars[0];
    const last = bars[bars.length - 1];
    return [
      this.overlay.clientWidth,
      this.overlay.clientHeight,
      bars.length,
      first?.time,
      last?.time,
      first?.close,
      last?.close,
      this.mode,
      this.rangeStart,
      this.rangeEnd,
      this.chart.priceToY?.(last?.close),
    ].join("|");
  }

  render(force = false) {
    if (!this.enabled) return;
    const rawBars = this.profileBars();
    this.overlay.dataset.mode = this.mode;
    this.overlay.dataset.rangeStart = String(this.rangeStart ?? "");
    this.overlay.dataset.rangeEnd = String(this.rangeEnd ?? "");
    this.overlay.dataset.profileBars = String(rawBars.length);
    const bars = rawBars.map(normalizeBar)
      .filter((bar) => Number.isFinite(bar.high) && Number.isFinite(bar.low) && Number.isFinite(bar.volume));
    if (bars.length < 2) {
      this.overlay.replaceChildren();
      return;
    }
    const profile = buildProfile(bars, this.rows);
    if (!profile?.bins?.length) {
      this.overlay.replaceChildren();
      return;
    }
    const width = Math.max(this.minWidth, Math.min(this.maxWidth, Math.round(this.overlay.clientWidth * this.widthRatio)));
    const fragment = document.createDocumentFragment();
    const wrap = document.createElement("div");
    wrap.className = "volume-profile";
    wrap.style.width = `${width}px`;

    const maxVolume = Math.max(...profile.bins.map((bin) => bin.total), 1);
    for (const bin of profile.bins) {
      const yHigh = this.chart.priceToY(bin.high);
      const yLow = this.chart.priceToY(bin.low);
      if (!Number.isFinite(yHigh) || !Number.isFinite(yLow)) continue;
      const top = Math.max(0, Math.min(yHigh, yLow));
      const height = Math.max(1, Math.abs(yLow - yHigh));
      const row = document.createElement("div");
      row.className = [
        "vp-row",
        bin.index === profile.pocIndex ? "poc" : "",
        bin.inValueArea ? "value-area" : "",
      ].filter(Boolean).join(" ");
      row.style.top = `${top}px`;
      row.style.height = `${height}px`;
      row.style.width = `${Math.max(2, (bin.total / maxVolume) * width)}px`;

      const down = document.createElement("span");
      down.className = "vp-down";
      down.style.width = `${bin.total ? (bin.down / bin.total) * 100 : 0}%`;
      const up = document.createElement("span");
      up.className = "vp-up";
      up.style.width = `${bin.total ? (bin.up / bin.total) * 100 : 0}%`;
      row.append(down, up);
      wrap.appendChild(row);
    }

    const labels = profileLabels(profile, this.chart);
    wrap.append(...labels);
    fragment.append(wrap);
    // The range boundary lines/tags are positioned with chart-relative X
    // coordinates (`left: x`), so they must be siblings of the FULL-WIDTH overlay —
    // not children of the narrow, right-aligned `.volume-profile` box, which would
    // shove them out of bounds and let `overflow:hidden` clip them away.
    fragment.append(...this.rangeLabels());
    this.overlay.replaceChildren(fragment);
  }

  profileBars() {
    const bars = this.mode === "fixed" ? this.chart.bars || [] : this.chart.visibleBars?.() || [];
    if (this.mode !== "fixed" || this.rangeStart == null) return bars;
    const start = Math.min(this.rangeStart, this.rangeEnd ?? this.chart.lastBar?.()?.time ?? this.rangeStart);
    const end = Math.max(this.rangeStart, this.rangeEnd ?? this.chart.lastBar?.()?.time ?? this.rangeStart);
    return bars.filter((bar) => bar.time >= start && bar.time <= end);
  }

  rangeLabels() {
    if (this.mode !== "fixed" || this.rangeStart == null) return [];
    const nodes = [];
    const points = [
      ["INICIO", this.rangeStart, "start"],
      ["FIM", this.rangeEnd, "end"],
    ].filter(([, time]) => time != null);
    for (const [label, time, tone] of points) {
      const x = this.chart.timeToX(time);
      if (!Number.isFinite(x)) continue;
      const line = document.createElement("div");
      line.className = `vp-range-line ${tone}`;
      line.style.left = `${x}px`;
      const tag = document.createElement("div");
      tag.className = `vp-range-tag ${tone}`;
      tag.style.left = `${x}px`;
      tag.textContent = label;
      nodes.push(line, tag);
    }
    return nodes;
  }
}

function buildProfile(bars, rows) {
  const low = Math.min(...bars.map((bar) => bar.low));
  const high = Math.max(...bars.map((bar) => bar.high));
  if (!Number.isFinite(low) || !Number.isFinite(high) || high <= low) return null;
  const rowCount = Math.max(24, Math.min(120, Number(rows) || 64));
  const step = (high - low) / rowCount;
  const bins = Array.from({ length: rowCount }, (_, index) => ({
    index,
    low: low + step * index,
    high: low + step * (index + 1),
    up: 0,
    down: 0,
    total: 0,
    inValueArea: false,
  }));

  for (const bar of bars) {
    const volume = Math.max(0, Number(bar.volume || 0));
    if (!volume) continue;
    const first = clamp(Math.floor((bar.low - low) / step), 0, rowCount - 1);
    const last = clamp(Math.floor((bar.high - low) / step), 0, rowCount - 1);
    const touched = Math.max(1, last - first + 1);
    const part = volume / touched;
    const isUp = Number(bar.close) >= Number(bar.open);
    for (let i = first; i <= last; i += 1) {
      if (isUp) bins[i].up += part;
      else bins[i].down += part;
      bins[i].total += part;
    }
  }

  const totalVolume = bins.reduce((sum, bin) => sum + bin.total, 0);
  const pocIndex = bins.reduce((best, bin, index) => (bin.total > bins[best].total ? index : best), 0);
  markValueArea(bins, pocIndex, totalVolume * VALUE_AREA_RATIO);
  return { bins, low, high, step, pocIndex, totalVolume };
}

function markValueArea(bins, pocIndex, targetVolume) {
  let left = pocIndex;
  let right = pocIndex;
  let volume = bins[pocIndex]?.total || 0;
  bins[pocIndex].inValueArea = true;
  while (volume < targetVolume && (left > 0 || right < bins.length - 1)) {
    const leftVolume = left > 0 ? bins[left - 1].total : -1;
    const rightVolume = right < bins.length - 1 ? bins[right + 1].total : -1;
    if (rightVolume >= leftVolume) {
      right += 1;
      volume += bins[right].total;
      bins[right].inValueArea = true;
    } else {
      left -= 1;
      volume += bins[left].total;
      bins[left].inValueArea = true;
    }
  }
}

function profileLabels(profile, chart) {
  const nodes = [];
  const valueBins = profile.bins.filter((bin) => bin.inValueArea);
  const poc = profile.bins[profile.pocIndex];
  const vah = valueBins[valueBins.length - 1];
  const val = valueBins[0];
  const specs = [
    ["POC", (poc.low + poc.high) / 2, "poc"],
    ["VAH", vah?.high, "vah"],
    ["VAL", val?.low, "val"],
  ];
  for (const [label, price, tone] of specs) {
    const y = chart.priceToY(price);
    if (!Number.isFinite(y)) continue;
    const node = document.createElement("div");
    node.className = `vp-label ${tone}`;
    node.style.top = `${y}px`;
    node.textContent = `${label} ${formatPrice(price)}`;
    nodes.push(node);
  }
  return nodes;
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}
