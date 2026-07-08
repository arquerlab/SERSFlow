import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { clampSplitWidth, readSplitWidth, writeSplitWidth } from "./splitWidth";

const MOBILE_MAX_PX = 920;

type ResizableSplitProps = {
  storageKey: string;
  defaultWidth: number;
  minWidth?: number;
  maxWidth?: number;
  left: ReactNode;
  right: ReactNode;
  className?: string;
};

export function ResizableSplit({
  storageKey,
  defaultWidth,
  minWidth = 280,
  maxWidth = 720,
  left,
  right,
  className,
}: ResizableSplitProps) {
  const [width, setWidth] = useState(() => readSplitWidth(storageKey, defaultWidth, minWidth, maxWidth));
  const [stacked, setStacked] = useState(() =>
    typeof window !== "undefined" ? window.matchMedia(`(max-width: ${MOBILE_MAX_PX}px)`).matches : false
  );
  const [dragging, setDragging] = useState(false);
  const dragRef = useRef<{ startX: number; startW: number } | null>(null);

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
      dragRef.current = { startX: ev.clientX, startW: width };
      setDragging(true);
      ev.currentTarget.setPointerCapture(ev.pointerId);
    },
    [stacked, width]
  );

  const onPointerMove = useCallback(
    (ev: React.PointerEvent<HTMLDivElement>) => {
      const drag = dragRef.current;
      if (!drag) return;
      const next = clampSplitWidth(drag.startW + (ev.clientX - drag.startX), minWidth, maxWidth);
      setWidth(next);
    },
    [minWidth, maxWidth]
  );

  const onPointerUp = useCallback(
    (ev: React.PointerEvent<HTMLDivElement>) => {
      if (!dragRef.current) return;
      dragRef.current = null;
      setDragging(false);
      writeSplitWidth(storageKey, width);
      try {
        ev.currentTarget.releasePointerCapture(ev.pointerId);
      } catch {
        // ignore
      }
    },
    [storageKey, width]
  );

  if (stacked) {
    return (
      <div className={["resizable-split resizable-split-stacked", className].filter(Boolean).join(" ")}>
        <div className="resizable-split-pane resizable-split-left">{left}</div>
        <div className="resizable-split-pane resizable-split-right">{right}</div>
      </div>
    );
  }

  return (
    <div
      className={["resizable-split", dragging ? "is-dragging" : "", className].filter(Boolean).join(" ")}
      style={{ ["--split-left-width" as string]: `${width}px` }}
    >
      <div className="resizable-split-pane resizable-split-left">{left}</div>
      <div
        className="column-split-handle"
        role="separator"
        aria-orientation="vertical"
        aria-valuenow={width}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
      />
      <div className="resizable-split-pane resizable-split-right">{right}</div>
    </div>
  );
}
