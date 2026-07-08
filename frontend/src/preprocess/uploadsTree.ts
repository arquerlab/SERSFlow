export type UploadTreeItem = {
  relative_path: string;
  filename?: string;
  [key: string]: unknown;
};

export type UploadFileNode = {
  type: "file";
  name: string;
  item: UploadTreeItem;
};

export type UploadFolderNode = {
  type: "folder";
  name: string;
  key: string;
  batchId: string | null;
  folders: Map<string, UploadFolderNode>;
  files: UploadFileNode[];
};

function splitRelPath(relativePath: string): string[] {
  return String(relativePath || "")
    .replace(/\\/g, "/")
    .split("/")
    .filter(Boolean);
}

export function toDisplayParts(relativePath: string, fallbackName?: string): string[] {
  const parts = splitRelPath(relativePath);
  if (parts.length >= 2) {
    const withoutBatch = parts.slice(1);
    if (withoutBatch.length >= 2) return withoutBatch;
    const leaf = withoutBatch[0] || String(fallbackName || "unknown");
    return ["(no folder)", leaf];
  }
  return ["(no folder)", String(fallbackName || "unknown")];
}

function makeFolderNode(name: string, key: string, batchId: string | null = null): UploadFolderNode {
  return { type: "folder", name, key, batchId, folders: new Map(), files: [] };
}

export function buildUploadsTree(items: UploadTreeItem[]): UploadFolderNode {
  const root = makeFolderNode("__root__", "__root__");
  for (const item of items || []) {
    const rel = String(item?.relative_path || "");
    if (!rel) continue;
    const parts = toDisplayParts(rel, item?.filename);
    const top = parts[0] || "(no folder)";
    if (!root.folders.has(top)) {
      root.folders.set(top, makeFolderNode(top, `folder:${top}`, null));
    }
    let node = root.folders.get(top)!;
    for (let i = 1; i < parts.length - 1; i += 1) {
      const part = parts[i];
      const key = `${node.key}/${part}`;
      if (!node.folders.has(part)) {
        node.folders.set(part, makeFolderNode(part, key, null));
      }
      node = node.folders.get(part)!;
    }
    node.files.push({
      type: "file",
      name: parts[parts.length - 1],
      item,
    });
  }
  return root;
}

export function sortedFolderEntries(folderNode: UploadFolderNode): UploadFolderNode[] {
  return Array.from(folderNode.folders.values()).sort((a, b) => a.name.localeCompare(b.name));
}

export function sortedFileEntries(folderNode: UploadFolderNode): UploadFileNode[] {
  return folderNode.files.slice().sort((a, b) => a.name.localeCompare(b.name));
}

export function collectFolderFilePaths(folderNode: UploadFolderNode): string[] {
  const out: string[] = [];
  for (const f of folderNode.files) out.push(String(f.item.relative_path));
  for (const child of folderNode.folders.values()) out.push(...collectFolderFilePaths(child));
  return out;
}
