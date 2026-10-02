import { useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchJson } from "../../lib/http";

export const UPLOADS_LIST_QUERY_KEY = ["io", "uploads"] as const;

export type UploadListItem = {
  relative_path: string;
  filename?: string;
  size_bytes?: number;
  labels?: Record<string, unknown>;
  technique_family?: string | null;
  xps_regions?: string[] | null;
  spectrum_count?: number | null;
  wn_min?: number | null;
  wn_max?: number | null;
};

export type UploadsListResponse = {
  items: UploadListItem[];
  count?: number;
};

async function fetchUploadsList(limit = 5000): Promise<UploadsListResponse> {
  return fetchJson<UploadsListResponse>(`/io/uploads?limit=${encodeURIComponent(String(limit))}`);
}

export { fetchUploadsList };

/** Single shared React Query for `/io/uploads`. Invalidate after upload/purge. */
export function useUploadsList(opts?: { enabled?: boolean; limit?: number }) {
  return useQuery({
    queryKey: [...UPLOADS_LIST_QUERY_KEY, opts?.limit ?? 5000],
    queryFn: () => fetchUploadsList(opts?.limit ?? 5000),
    enabled: opts?.enabled !== false,
    staleTime: 30_000,
  });
}

export function useInvalidateUploadsList() {
  const qc = useQueryClient();
  return () => qc.invalidateQueries({ queryKey: UPLOADS_LIST_QUERY_KEY });
}
