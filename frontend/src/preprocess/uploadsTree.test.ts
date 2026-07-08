import { describe, expect, it } from "vitest";
import { buildUploadsTree, collectFolderFilePaths, toDisplayParts } from "./uploadsTree";

describe("uploadsTree", () => {
  it("strips batch id from relative paths", () => {
    expect(toDisplayParts("batch-1/exp/file.wdf", "file.wdf")).toEqual(["exp", "file.wdf"]);
  });

  it("groups nested folders and collects descendant paths", () => {
    const tree = buildUploadsTree([
      { relative_path: "b1/a/x.wdf", filename: "x.wdf" },
      { relative_path: "b1/a/y.wdf", filename: "y.wdf" },
      { relative_path: "b1/b/z.wdf", filename: "z.wdf" },
    ]);
    const top = [...tree.folders.values()].sort((a, b) => a.name.localeCompare(b.name));
    expect(top.map((f) => f.name)).toEqual(["a", "b"]);
    const aPaths = collectFolderFilePaths(top[0]!);
    expect(aPaths.sort()).toEqual(["b1/a/x.wdf", "b1/a/y.wdf"]);
  });
});
