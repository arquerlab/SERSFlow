import { useEffect, useState } from "react";
import { postValidateLinks } from "./api";
import { flattenFittingForPipeline, type FittingEditorParams } from "./fittingUtils";

/** F4: live check of the step's parameter links (expression syntax, unknown peaks, duplicates, cycles). */
export function LinkValidationNotice({ fp }: { fp: FittingEditorParams }) {
  const [errors, setErrors] = useState<string[]>([]);
  const flat = flattenFittingForPipeline(fp) as { components?: unknown[]; param_links?: unknown[] };
  const key = JSON.stringify([flat.components ?? [], flat.param_links ?? []]);

  useEffect(() => {
    const links = flat.param_links ?? [];
    if (!links.length) {
      setErrors([]);
      return;
    }
    let cancelled = false;
    const t = window.setTimeout(() => {
      postValidateLinks({ components: flat.components ?? [], param_links: links })
        .then((r) => {
          if (!cancelled) setErrors(r.errors ?? []);
        })
        .catch(() => {
          if (!cancelled) setErrors([]);
        });
    }, 350);
    return () => {
      cancelled = true;
      window.clearTimeout(t);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  if (!errors.length) return null;
  return (
    <div className="err" data-testid="link-errors" role="alert">
      <b>Parameter links will fail:</b>
      <ul style={{ margin: "4px 0 0 16px", padding: 0 }}>
        {errors.map((e) => (
          <li key={e}>{e}</li>
        ))}
      </ul>
    </div>
  );
}
