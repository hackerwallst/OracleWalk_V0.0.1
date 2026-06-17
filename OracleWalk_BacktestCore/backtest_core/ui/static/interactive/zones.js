import { formatPrice } from "./chart.js";

const MIN_ZONE_PIXELS = 8;

export class ZoneLayer {
  constructor({ overlay, chart, api, getCursor, onSelect, onStatus }) {
    this.overlay = overlay;
    this.chart = chart;
    this.api = api;
    this.getCursor = getCursor;
    this.onSelect = onSelect || (() => {});
    this.onStatus = onStatus || (() => {});
    this.zones = new Map();
    this.selectedId = null;
    this.drawing = false;
    this.side = "support";
    this.timeframe = "H1";
    this.drag = null;
    this.preview = null;
    this.syncFrame = 0;
    this._lastSignature = "";
  }

  init() {
    this.overlay.addEventListener("pointerdown", (event) => this.handleOverlayPointerDown(event));
    window.addEventListener("pointermove", (event) => this.handlePointerMove(event));
    window.addEventListener("pointerup", (event) => this.handlePointerUp(event));
    window.addEventListener("keydown", (event) => {
      if (event.key === "Delete" || event.key === "Backspace") {
        const tag = document.activeElement?.tagName?.toLowerCase();
        if (tag !== "input" && tag !== "textarea") this.deleteSelected();
      }
    });
    this.startSyncLoop();
  }

  // Keep zones glued to the chart on ANY transform — vertical price autoscale and
  // mouse-wheel zoom don't fire lightweight-charts' logical-range event, which is
  // what made zones "jump"/lag. We poll a cheap signature of the chart's
  // price/time mapping each frame and re-render only when it actually changes.
  startSyncLoop() {
    const tick = () => {
      this.syncFrame = requestAnimationFrame(tick);
      if (this.drag) return; // mid-drag render() is driven by the drag handlers
      const signature = this.viewportSignature();
      if (signature !== this._lastSignature) {
        this._lastSignature = signature;
        this.render();
      }
    };
    this.syncFrame = requestAnimationFrame(tick);
  }

  viewportSignature() {
    const ref = this.chart.lastBar?.();
    const price = Number.isFinite(Number(ref?.close)) ? Number(ref.close) : 1;
    const yTop = this.chart.priceToY(price);
    const yScale = this.chart.priceToY(price * 1.001 || price + 1);
    const x = ref?.time != null ? this.chart.timeToX(ref.time) : null;
    const w = this.overlay.clientWidth;
    const h = this.overlay.clientHeight;
    return `${yTop}|${yScale}|${x}|${w}|${h}|${this.zones.size}|${this.selectedId}`;
  }

  setDrawing(enabled) {
    this.drawing = Boolean(enabled);
    this.overlay.classList.toggle("is-drawing", this.drawing);
  }

  setSide(side) {
    this.side = side === "resistance" ? "resistance" : "support";
  }

  setTimeframe(timeframe) {
    this.timeframe = timeframe || this.timeframe || "H1";
  }

  sync(zones = []) {
    const next = new Map();
    for (const raw of zones) {
      if (!raw || raw.state === "deleted") continue;
      const zone = this.normalizeZone(raw);
      next.set(zone.id, zone);
    }
    this.zones = next;
    if (this.selectedId && !this.zones.has(this.selectedId)) {
      this.selectedId = null;
      this.onSelect(null);
    } else if (this.selectedId) {
      this.onSelect(this.zones.get(this.selectedId));
    }
    this.render();
  }

  normalizeZone(raw) {
    const low = Number(raw.price_low);
    const high = Number(raw.price_high);
    return {
      ...raw,
      id: String(raw.id),
      price_low: Math.min(low, high),
      price_high: Math.max(low, high),
      side: raw.side === "resistance" ? "resistance" : "support",
      timeframe: raw.timeframe || raw.zone_timeframe || this.timeframe || "H1",
      state: raw.state || "active",
      created_at_bar: Number.isFinite(Number(raw.created_at_bar))
        ? Number(raw.created_at_bar)
        : Number(this.getCursor() || 0),
    };
  }

  handleOverlayPointerDown(event) {
    if (!this.drawing || event.target !== this.overlay) return;
    event.preventDefault();
    this.drag = {
      type: "create",
      startY: this.localY(event),
      currentY: this.localY(event),
    };
    this.preview = document.createElement("div");
    this.preview.className = "zone-preview";
    this.overlay.appendChild(this.preview);
    this.updatePreview();
  }

  startZoneDrag(event, zone, action) {
    event.preventDefault();
    event.stopPropagation();
    this.select(zone.id);
    const startY = this.localY(event);
    this.drag = {
      type: action,
      id: zone.id,
      startY,
      currentY: startY,
      original: { ...zone },
    };
  }

  handlePointerMove(event) {
    if (!this.drag) return;
    this.drag.currentY = this.localY(event);
    if (this.drag.type === "create") {
      this.updatePreview();
      return;
    }
    this.updateDraggedZone();
  }

  async handlePointerUp() {
    if (!this.drag) return;
    const drag = this.drag;
    this.drag = null;

    if (drag.type === "create") {
      const payload = this.payloadFromVerticalRange(drag.startY, drag.currentY);
      this.removePreview();
      if (!payload) return;
      try {
        const zone = this.normalizeZone(await this.api.createZone(payload));
        this.zones.set(zone.id, zone);
        this.select(zone.id);
        this.render();
        this.onStatus(`Zona ${zone.id} criada`);
      } catch (error) {
        this.onStatus(`Erro ao criar zona: ${error.message || error}`);
      }
      return;
    }

    const zone = this.zones.get(drag.id);
    if (!zone) return;
    try {
      const updated = await this.api.updateZone(zone.id, this.toPayload(zone));
      const normalized = this.normalizeZone(updated);
      this.zones.set(normalized.id, normalized);
      this.select(normalized.id);
      this.render();
      this.onStatus(`Zona ${normalized.id} atualizada`);
    } catch (error) {
      this.zones.set(drag.original.id, drag.original);
      this.render();
      this.onStatus(`Erro ao atualizar zona: ${error.message || error}`);
    }
  }

  updateDraggedZone() {
    const drag = this.drag;
    const zone = this.zones.get(drag.id);
    if (!zone) return;
    const price = this.chart.yToPrice(drag.currentY);
    if (!Number.isFinite(price)) return;

    if (drag.type === "move") {
      const startPrice = this.chart.yToPrice(drag.startY);
      if (!Number.isFinite(startPrice)) return;
      const delta = price - startPrice;
      zone.price_low = drag.original.price_low + delta;
      zone.price_high = drag.original.price_high + delta;
    } else if (drag.type === "resize-top") {
      zone.price_high = Math.max(price, zone.price_low);
    } else if (drag.type === "resize-bottom") {
      zone.price_low = Math.min(price, zone.price_high);
    }
    this.zones.set(zone.id, this.normalizeZone(zone));
    this.render();
  }

  payloadFromVerticalRange(startY, endY) {
    if (Math.abs(endY - startY) < MIN_ZONE_PIXELS) return null;
    const priceA = this.chart.yToPrice(startY);
    const priceB = this.chart.yToPrice(endY);
    if (!Number.isFinite(priceA) || !Number.isFinite(priceB)) return null;
    return {
      price_low: Math.min(priceA, priceB),
      price_high: Math.max(priceA, priceB),
      side: this.side,
      timeframe: this.timeframe,
    };
  }

  toPayload(zone) {
    return {
      price_low: zone.price_low,
      price_high: zone.price_high,
      side: zone.side,
      timeframe: zone.timeframe || this.timeframe,
    };
  }

  updatePreview() {
    if (!this.preview || !this.drag) return;
    const top = Math.min(this.drag.startY, this.drag.currentY);
    const height = Math.max(MIN_ZONE_PIXELS, Math.abs(this.drag.currentY - this.drag.startY));
    this.preview.style.top = `${top}px`;
    this.preview.style.height = `${height}px`;
  }

  removePreview() {
    this.preview?.remove();
    this.preview = null;
  }

  localY(event) {
    const rect = this.overlay.getBoundingClientRect();
    return Math.max(0, Math.min(rect.height, event.clientY - rect.top));
  }

  select(id) {
    this.selectedId = id && this.zones.has(id) ? id : null;
    this.onSelect(this.selectedId ? this.zones.get(this.selectedId) : null);
    this.render();
  }

  async setSelectedSide(side) {
    if (!this.selectedId) {
      this.setSide(side);
      return;
    }
    const zone = this.zones.get(this.selectedId);
    if (!zone) return;
    zone.side = side === "resistance" ? "resistance" : "support";
    this.zones.set(zone.id, zone);
    this.render();
    try {
      const updated = await this.api.updateZone(zone.id, this.toPayload(zone));
      const normalized = this.normalizeZone(updated);
      this.zones.set(normalized.id, normalized);
      this.select(normalized.id);
    } catch (error) {
      this.onStatus(`Erro ao alterar lado: ${error.message || error}`);
    }
  }

  async deleteSelected() {
    if (!this.selectedId) return;
    const id = this.selectedId;
    try {
      await this.api.deleteZone(id);
      this.zones.delete(id);
      this.select(null);
      this.render();
      this.onStatus(`Zona ${id} apagada`);
    } catch (error) {
      this.onStatus(`Erro ao apagar zona: ${error.message || error}`);
    }
  }

  render() {
    const fragment = document.createDocumentFragment();
    const width = this.overlay.clientWidth || 0;
    const height = this.overlay.clientHeight || 0;

    for (const zone of this.zones.values()) {
      const topY = this.chart.priceToY(zone.price_high);
      const bottomY = this.chart.priceToY(zone.price_low);
      if (!Number.isFinite(topY) || !Number.isFinite(bottomY)) continue;
      const rawTop = Math.min(topY, bottomY);
      const rawBottom = Math.max(topY, bottomY);
      // Skip zones whose price band is entirely outside the visible chart box.
      if (rawBottom < 0 || rawTop > height) continue;
      // Clamp the band to the chart box so it never paints over the header,
      // replay bar or side panel when price runs far from the zone.
      const zoneTop = Math.max(0, rawTop);
      const zoneBottom = Math.min(height, rawBottom);
      const zoneHeight = Math.max(2, zoneBottom - zoneTop);

      const startTime = this.chart.getBarTimeByIndex(zone.created_at_bar);
      const startXRaw = this.chart.timeToX(startTime);
      const startX = Number.isFinite(startXRaw) ? Math.max(0, Math.min(width, startXRaw)) : 0;
      const zoneWidth = Math.max(24, width - startX);
      const el = document.createElement("div");
      el.className = [
        "zone",
        zone.side,
        zone.state === "broken" ? "broken" : "",
        zone.timeframe ? `tf-${String(zone.timeframe).toLowerCase()}` : "",
        zone.id === this.selectedId ? "selected" : "",
      ].filter(Boolean).join(" ");
      el.style.left = `${startX}px`;
      el.style.top = `${zoneTop}px`;
      el.style.width = `${zoneWidth}px`;
      el.style.height = `${zoneHeight}px`;
      el.dataset.zoneId = zone.id;

      const label = document.createElement("div");
      label.className = "zone-label";
      label.textContent = `${zone.timeframe || "TF"} ${zone.side} ${formatPrice(zone.price_low)}-${formatPrice(zone.price_high)}`;
      el.appendChild(label);

      const badge = document.createElement("div");
      badge.className = "zone-tf-badge";
      badge.textContent = zone.timeframe || "TF";
      el.appendChild(badge);

      const topHandle = document.createElement("div");
      topHandle.className = "zone-handle top";
      topHandle.addEventListener("pointerdown", (event) => this.startZoneDrag(event, zone, "resize-top"));
      el.appendChild(topHandle);

      const bottomHandle = document.createElement("div");
      bottomHandle.className = "zone-handle bottom";
      bottomHandle.addEventListener("pointerdown", (event) => this.startZoneDrag(event, zone, "resize-bottom"));
      el.appendChild(bottomHandle);

      el.addEventListener("pointerdown", (event) => this.startZoneDrag(event, zone, "move"));
      el.addEventListener("click", (event) => {
        event.stopPropagation();
        this.select(zone.id);
      });
      fragment.appendChild(el);
    }

    this.overlay.replaceChildren(fragment);
    if (this.preview) this.overlay.appendChild(this.preview);
  }

  countActive() {
    return [...this.zones.values()].filter((zone) => zone.state !== "deleted").length;
  }
}
