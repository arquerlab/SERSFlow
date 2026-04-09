import { fetchJson, fetchText } from "./api.js";

export function createUploadsModel() {
  let uploadedItems = [];
  let selected = new Set();

  function getUploadedItems() {
    return uploadedItems;
  }
  function getSelectedSet() {
    return selected;
  }
  function setSelectedSet(next) {
    selected = next;
  }
  function toggle(relativePath, checked) {
    const rel = String(relativePath || "");
    if (!rel) return;
    const next = checked == null ? !selected.has(rel) : !!checked;
    if (next) selected.add(rel);
    else selected.delete(rel);
  }

  async function refreshUploadedList() {
    const data = await fetchJson("/io/uploads");
    uploadedItems = data.items || [];
    const existing = new Set(uploadedItems.map((x) => x.relative_path));
    selected = new Set(Array.from(selected).filter((p) => existing.has(p)));
    return { items: uploadedItems, count: data.count || uploadedItems.length };
  }

  return { refreshUploadedList, getUploadedItems, getSelectedSet, setSelectedSet, toggle };
}

export function createUploadsController({ uploadedListEl, uploadsMetaEl }) {
  let uploadedItems = [];
  let selected = new Set();

  function getUploadedItems() {
    return uploadedItems;
  }

  function getSelectedSet() {
    return selected;
  }

  function setSelectedSet(next) {
    selected = next;
  }

  function renderUploadList() {
    uploadedListEl.innerHTML = "";
    const existing = new Set(uploadedItems.map((x) => x.relative_path));
    selected = new Set(Array.from(selected).filter((p) => existing.has(p)));

    for (const item of uploadedItems) {
      const rel = item.relative_path;
      const row = document.createElement("div");
      row.className = "uploads-item";

      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = selected.has(rel);
      cb.addEventListener("change", () => {
        if (cb.checked) selected.add(rel);
        else selected.delete(rel);
        uploadsMetaEl.textContent = `${uploadedItems.length} file(s) • ${selected.size} selected`;
      });

      const label = document.createElement("label");
      label.textContent = `${item.saved_at} | ${item.filename} (${Number(item.size_bytes || 0).toLocaleString()} bytes)`;
      label.addEventListener("click", () => {
        cb.checked = !cb.checked;
        cb.dispatchEvent(new Event("change"));
      });

      row.appendChild(cb);
      row.appendChild(label);
      uploadedListEl.appendChild(row);
    }
    uploadsMetaEl.textContent = `${uploadedItems.length} file(s) • ${selected.size} selected`;
  }

  async function refreshUploadedList() {
    try {
      const data = await fetchJson("/io/uploads");
      uploadedItems = data.items || [];
      uploadsMetaEl.textContent = `${data.count || uploadedItems.length} file(s)`;
      renderUploadList();
      return uploadedItems;
    } catch {
      return uploadedItems;
    }
  }

  async function unloadSelected() {
    const paths = Array.from(selected);
    if (paths.length === 0) return { ok: true, message: "No files selected." };
    const { res, text } = await fetchText("/io/unload", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ relative_paths: paths }),
    });
    if (!res.ok) return { ok: false, message: text || `Unload failed (${res.status}).` };
    selected = new Set();
    await refreshUploadedList();
    return { ok: true, message: text || "Unloaded." };
  }

  async function unloadAll() {
    if (!uploadedItems || uploadedItems.length === 0) return { ok: true, message: "No uploaded files to unload." };
    const paths = uploadedItems.map((x) => x.relative_path);
    const { res, text } = await fetchText("/io/unload", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ relative_paths: paths }),
    });
    if (!res.ok) return { ok: false, message: text || `Unload failed (${res.status}).` };
    selected = new Set();
    await refreshUploadedList();
    return { ok: true, message: text || "Unloaded." };
  }

  return {
    refreshUploadedList,
    renderUploadList,
    unloadSelected,
    unloadAll,
    getUploadedItems,
    getSelectedSet,
    setSelectedSet,
  };
}

