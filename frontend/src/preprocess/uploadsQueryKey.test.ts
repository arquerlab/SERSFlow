import { describe, expect, it } from "vitest";
import { UPLOADS_LIST_QUERY_KEY } from "./hooks/useUploadsList";

describe("uploads list query key", () => {
  it("uses a stable shared cache key for /io/uploads", () => {
    expect(UPLOADS_LIST_QUERY_KEY).toEqual(["io", "uploads"]);
  });
});
