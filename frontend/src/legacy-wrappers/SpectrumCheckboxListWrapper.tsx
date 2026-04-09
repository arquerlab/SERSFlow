import { useEffect, useRef } from "react";

export function SpectrumCheckboxListWrapper({
  onSelectionChange,
}: {
  onSelectionChange?: (relativePaths: string[]) => void;
}) {
  const listRef = useRef<HTMLDivElement | null>(null);
  const metaRef = useRef<HTMLDivElement | null>(null);
  const ctrlRef = useRef<any>(null);

  useEffect(() => {
    let disposed = false;

    async function mount() {
      if (!listRef.current || !metaRef.current) return;
      // Important: avoid TS/Vite trying to resolve `/static/...` at build time.
      // We load the legacy module at runtime from FastAPI static.
      const url = new URL("/static/ui/uploads.js", window.location.origin).toString();
      const mod = (await import(/* @vite-ignore */ url)) as any;
      if (disposed) return;
      const ctrl = mod.createUploadsController({
        uploadedListEl: listRef.current,
        uploadsMetaEl: metaRef.current,
      });
      ctrlRef.current = ctrl;
      await ctrl.refreshUploadedList();

      const handler = () => {
        if (disposed) return;
        const selected = Array.from(ctrl.getSelectedSet().values()).map((x: any) => String(x));
        onSelectionChange?.(selected);
      };
      listRef.current.addEventListener("change", handler, true);
      return () => listRef.current?.removeEventListener("change", handler, true);
    }

    const cleanupPromise = mount();
    return () => {
      disposed = true;
      ctrlRef.current = null;
      // cleanup handler if mounted
      cleanupPromise?.then((cleanup: any) => cleanup && cleanup());
    };
  }, [onSelectionChange]);

  return (
    <div>
      <div ref={metaRef} style={{ fontFamily: "ui-monospace, Consolas, monospace", fontSize: 12 }} />
      <div style={{ maxHeight: 240, overflow: "auto", border: "1px solid #2e303a", borderRadius: 8, padding: 10 }}>
        <div ref={listRef} />
      </div>
    </div>
  );
}

