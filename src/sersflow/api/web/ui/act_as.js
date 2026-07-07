/**
 * Superuser data-scope selector (view all users or one specific user).
 */

function $(id) {
  return document.getElementById(id);
}

async function fetchJson(url, options) {
  const res = await fetch(url, { cache: "no-store", credentials: "include", ...options });
  const text = await res.text();
  if (!res.ok) {
    let detail = text;
    try {
      const j = JSON.parse(text);
      if (j && j.detail) detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch (_) {
      /* ignore */
    }
    const err = new Error(detail || `Request failed (${res.status})`);
    err.status = res.status;
    throw err;
  }
  return text ? JSON.parse(text) : null;
}

function currentScopeValue(me, users) {
  const act = me?.act_as;
  if (!act || act.scope === "all") return "all";
  if (act.user_id) return act.user_id;
  const match = (users || []).find((u) => u.username === act.label);
  return match ? match.user_id : "all";
}

export async function wireActAsSelector() {
  const wrap = $("actAsWrap");
  const select = $("actAsSelect");
  if (!wrap || !select) return;

  let me;
  try {
    me = await fetchJson("/auth/me");
  } catch (_) {
    wrap.hidden = true;
    return;
  }

  if (!me?.user?.is_superuser) {
    wrap.hidden = true;
    return;
  }

  let users = [];
  try {
    users = await fetchJson("/auth/users");
  } catch (e) {
    console.error("Failed to load users for act-as selector", e);
    wrap.hidden = true;
    return;
  }

  select.innerHTML = "";
  const allOpt = document.createElement("option");
  allOpt.value = "all";
  allOpt.textContent = "All users";
  select.appendChild(allOpt);

  for (const u of users) {
    const opt = document.createElement("option");
    opt.value = u.user_id;
    opt.textContent = u.username;
    select.appendChild(opt);
  }

  select.value = currentScopeValue(me, users);
  wrap.hidden = false;

  select.addEventListener("change", async () => {
    const scope = select.value || "all";
    select.disabled = true;
    try {
      await fetchJson("/auth/act-as", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ scope }),
      });
      window.location.reload();
    } catch (e) {
      console.error(e);
      select.disabled = false;
      alert(e.message || "Failed to change data scope");
    }
  });
}
