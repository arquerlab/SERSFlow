import { useEffect, useState } from "react";
import type { FittingParamLink } from "./fittingUtils";

type Props = {
  link: FittingParamLink;
  isAmp: boolean;
  onChange: (next: FittingParamLink) => void;
};

/** F4 expression link editor: `{A.pos} + 0.5*({B.pos} - {A.pos})`; commits on blur or Enter. */
export function ExpressionLinkInput({ link, isAmp, onChange }: Props) {
  const [draft, setDraft] = useState(link.expr ?? "");
  useEffect(() => setDraft(link.expr ?? ""), [link.expr]);
  const commit = () => {
    if (draft !== (link.expr ?? "")) onChange({ ...link, expr: draft });
  };
  return (
    <div style={{ display: "grid", gap: 2, width: "100%" }}>
      <input
        type="text"
        data-testid="link-expr-input"
        value={draft}
        placeholder="{A.pos} + 0.5*({B.pos} - {A.pos})"
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter") commit();
        }}
        style={{ width: "100%", fontFamily: "monospace", fontSize: 12 }}
        title={
          "Expression over other peaks: {peak.param} references (e.g. {A.pos}, {B.fwhm}); {A.area} = peak area.\n" +
          "Allowed: numbers, + - * / **, abs sqrt exp log min max. The linked value ignores its own bounds."
        }
      />
      {isAmp ? (
        <label className="inline" style={{ fontSize: 11, gap: 4 }}>
          defines
          <select
            value={link.defines === "area" ? "area" : "value"}
            onChange={(e) => onChange({ ...link, defines: e.target.value === "area" ? "area" : undefined })}
          >
            <option value="value">amplitude (height)</option>
            <option value="area">area</option>
          </select>
        </label>
      ) : null}
    </div>
  );
}
