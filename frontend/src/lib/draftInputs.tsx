import { useEffect, useState, type InputHTMLAttributes } from "react";

/** Parse comma-separated positive integers; ignores empty segments. */
export function parseCommaSeparatedInts(raw: string): number[] {
  return raw
    .split(",")
    .map((x) => Number(x.trim()))
    .filter((n) => Number.isFinite(n) && n >= 1)
    .map((n) => Math.floor(n));
}

type CommaSeparatedIntListInputProps = {
  value: number[];
  onChange: (next: number[]) => void;
  placeholder?: string;
  title?: string;
  allowEmpty?: boolean;
};

export function CommaSeparatedIntListInput({
  value,
  onChange,
  placeholder,
  title,
  allowEmpty = true,
}: CommaSeparatedIntListInputProps) {
  const [draft, setDraft] = useState(() => value.join(","));
  const [focused, setFocused] = useState(false);

  useEffect(() => {
    if (!focused) {
      setDraft(value.join(","));
    }
  }, [value, focused]);

  return (
    <input
      type="text"
      title={title}
      placeholder={placeholder}
      value={draft}
      onFocus={() => setFocused(true)}
      onBlur={() => {
        setFocused(false);
        const parsed = parseCommaSeparatedInts(draft);
        const next = parsed.length ? parsed : allowEmpty ? [] : value;
        onChange(next);
        setDraft(next.join(","));
      }}
      onChange={(e) => setDraft(e.target.value)}
    />
  );
}

type DraftNumberInputProps = Omit<InputHTMLAttributes<HTMLInputElement>, "value" | "onChange" | "type"> & {
  value: unknown;
  onChange: (next: number | null) => void;
  nullable?: boolean;
  integer?: boolean;
  min?: number;
  max?: number;
};

export function DraftNumberInput({ value, onChange, nullable, integer, min, max, ...rest }: DraftNumberInputProps) {
  const display = value == null || value === "" ? "" : String(value);
  const [draft, setDraft] = useState(display);
  const [focused, setFocused] = useState(false);

  useEffect(() => {
    if (!focused) {
      setDraft(display);
    }
  }, [display, focused]);

  const commit = (raw: string) => {
    const trimmed = raw.trim();
    if (trimmed === "") {
      if (nullable) {
        onChange(null);
        setDraft("");
      } else {
        setDraft(display);
      }
      return;
    }
    let n = integer ? Math.trunc(Number(trimmed)) : Number(trimmed);
    if (Number.isFinite(n)) {
      if (min != null) n = Math.max(min, n);
      if (max != null) n = Math.min(max, n);
      onChange(n);
      setDraft(String(n));
    } else {
      setDraft(display);
    }
  };

  return (
    <input
      type="text"
      inputMode={integer ? "numeric" : "decimal"}
      {...rest}
      value={draft}
      onFocus={() => setFocused(true)}
      onBlur={() => {
        setFocused(false);
        commit(draft);
      }}
      onChange={(e) => setDraft(e.target.value)}
    />
  );
}
