import type { DatasetListItem } from "../preprocess/api";
import { datasetOptionLabel } from "../preprocess/labels";

type Props = {
  items: DatasetListItem[];
  value: string;
  onChange: (datasetId: string) => void;
  disabled?: boolean;
  loading?: boolean;
  id?: string;
};

export function DatasetPicker({ items, value, onChange, disabled, loading, id }: Props) {
  return (
    <label className="inline">
      Dataset
      <select
        id={id}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(String(e.target.value || ""))}
      >
        <option value="">{loading ? "Loading…" : "Select…"}</option>
        {items.map((d) => (
          <option key={d.dataset_id} value={d.dataset_id}>
            {datasetOptionLabel(d)}
          </option>
        ))}
      </select>
    </label>
  );
}
