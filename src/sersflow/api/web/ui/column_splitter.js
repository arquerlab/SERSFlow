export function clampSplitWidth(width, minWidth, maxWidth) {
  const n = Number(width);
  if (!Number.isFinite(n)) return minWidth;
  return Math.min(maxWidth, Math.max(minWidth, n));
}

export function readSplitWidth(storageKey, defaultWidth, minWidth, maxWidth) {
  try {
    const raw = localStorage.getItem(storageKey);
    if (raw == null || raw === "") return defaultWidth;
    return clampSplitWidth(Number(raw), minWidth, maxWidth);
  } catch {
    return defaultWidth;
  }
}

export function writeSplitWidth(storageKey, width) {
  try {
    localStorage.setItem(storageKey, String(Math.round(width)));
  } catch {
    // ignore
  }
}

/**
 * @param {object} opts
 * @param {HTMLElement} opts.layoutEl
 * @param {HTMLElement} opts.leftEl
 * @param {HTMLElement} opts.handleEl
 * @param {string} opts.storageKey
 * @param {number} opts.defaultWidth
 * @param {number} [opts.minWidth]
 * @param {number} [opts.maxWidth]
 * @param {() => void} [opts.onResizeEnd]
 */
export function wireColumnSplitter({
  layoutEl,
  leftEl,
  handleEl,
  storageKey,
  defaultWidth,
  minWidth = 280,
  maxWidth = 720,
  onResizeEnd,
}) {
  if (!layoutEl || !leftEl || !handleEl) return;

  const mq = window.matchMedia("(max-width: 920px)");
  let width = readSplitWidth(storageKey, defaultWidth, minWidth, maxWidth);
  let dragging = false;
  let startX = 0;
  let startW = 0;

  function applyWidth() {
    if (mq.matches) {
      layoutEl.style.removeProperty("--split-left-width");
      handleEl.hidden = true;
      return;
    }
    handleEl.hidden = false;
    layoutEl.style.setProperty("--split-left-width", `${width}px`);
  }

  function onPointerDown(ev) {
    if (mq.matches) return;
    ev.preventDefault();
    dragging = true;
    startX = ev.clientX;
    startW = width;
    layoutEl.classList.add("is-dragging");
    handleEl.setPointerCapture(ev.pointerId);
  }

  function onPointerMove(ev) {
    if (!dragging) return;
    width = clampSplitWidth(startW + (ev.clientX - startX), minWidth, maxWidth);
    applyWidth();
  }

  function onPointerUp(ev) {
    if (!dragging) return;
    dragging = false;
    layoutEl.classList.remove("is-dragging");
    writeSplitWidth(storageKey, width);
    try {
      handleEl.releasePointerCapture(ev.pointerId);
    } catch {
      // ignore
    }
    if (typeof onResizeEnd === "function") onResizeEnd();
  }

  handleEl.addEventListener("pointerdown", onPointerDown);
  handleEl.addEventListener("pointermove", onPointerMove);
  handleEl.addEventListener("pointerup", onPointerUp);
  handleEl.addEventListener("pointercancel", onPointerUp);
  mq.addEventListener("change", applyWidth);
  applyWidth();
}
