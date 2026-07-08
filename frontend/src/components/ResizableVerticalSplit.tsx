import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { clampSplitWidth, readSplitWidth, writeSplitWidth } from "./splitWidth";

const MOBILE_MAX_PX = 920;

type ResizableVerticalSplitProps = {
  storageKey: string;
  /** Height (px) of the bottom pane. */
  defaultHeight: number;
  minHeight?: number;
  maxHeight?: number;
  /**
   * When true, the bottom pane will not clamp height and will not use an internal scroll container.
   * This lets the whole page scroll instead (useful for tall editors inside the bottom pane).
   */
  allowPageScroll?: boolean;
  top: ReactNode;
  bottom: ReactNode;
  className?: string;
};

export function ResizableVerticalSplit({
  storageKey,
  defaultHeight,
  minHeight = 260,
  maxHeight = 900,
  allowPageScroll = false,
  top,
  bottom,
  className,
}: ResizableVerticalSplitProps) {
  const [height, setHeight] = useState(() => readSplitWidth(storageKey, defaultHeight, minHeight, maxHeight));
  const [stacked, setStacked] = useState(() =>
    typeof window !== "undefined" ? window.matchMedia(`(max-width: ${MOBILE_MAX_PX}px)`).matches : false
  );
  const [dragging, setDragging] = useState(false);
  const dragRef = useRef<{ startY: number; startH: number } | null>(null);

  useEffect(() => {
    const mq = window.matchMedia(`(max-width: ${MOBILE_MAX_PX}px)`);
    const onChange = () => setStacked(mq.matches);
    onChange();
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  const onPointerDown = useCallback(
    (ev: React.PointerEvent<HTMLDivElement>) => {
      if (stacked) return;
      ev.preventDefault();
      dragRef.current = { startY: ev.clientY, startH: height };
      setDragging(true);
      ev.currentTarget.setPointerCapture(ev.pointerId);
    },
    [stacked, height]
  );

  const onPointerMove = useCallback(
    (ev: React.PointerEvent<HTMLDivElement>) => {
      const drag = dragRef.current;
      if (!drag) return;
      const next = clampSplitWidth(drag.startH + (ev.clientY - drag.startY), minHeight, maxHeight);
      setHeight(next);
    },
    [minHeight, maxHeight]
  );

  const onPointerUp = useCallback(
    (ev: React.PointerEvent<HTMLDivElement>) => {
      if (!dragRef.current) return;
      dragRef.current = null;
      setDragging(false);
      writeSplitWidth(storageKey, height);
      try {
        ev.currentTarget.releasePointerCapture(ev.pointerId);
      } catch {
        // ignore
      }
    },
    [storageKey, height]
  );

  if (stacked) {
    return (
      <div className={["resizable-vsplit resizable-vsplit-stacked", className].filter(Boolean).join(" ")}>
        <div className="resizable-vsplit-pane resizable-vsplit-top">{top}</div>
        <div className="resizable-vsplit-pane resizable-vsplit-bottom">{bottom}</div>
      </div>
    );
  }

  return (
    <div className={["resizable-vsplit", dragging ? "is-dragging" : "", className].filter(Boolean).join(" ")}>
      <div className="resizable-vsplit-pane resizable-vsplit-top">{top}</div>
      <div
        className="row-split-handle"
        role="separator"
        aria-orientation="horizontal"
        aria-valuenow={height}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
      />
      <div
        className="resizable-vsplit-pane resizable-vsplit-bottom"
        style={{
          maxHeight: allowPageScroll ? undefined : height,
          overflowY: allowPageScroll ? "visible" : "auto",
        }}
      >
        {bottom}
      </div>
    </div>
  );
}

