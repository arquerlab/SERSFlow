/**
 * Full-page login gate for the legacy shell.
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

function showLogin(message) {
  const overlay = $("loginOverlay");
  const app = $("appContent");
  if (overlay) {
    overlay.hidden = false;
    overlay.style.display = "flex";
  }
  if (app) {
    app.hidden = true;
    app.style.display = "none";
  }
  const err = $("loginError");
  if (err) err.textContent = message || "";
}

function hideLogin(username) {
  const overlay = $("loginOverlay");
  const app = $("appContent");
  if (overlay) {
    overlay.hidden = true;
    overlay.style.display = "none";
  }
  if (app) {
    app.hidden = false;
    app.style.display = "";
  }
  const label = $("authUserLabel");
  if (label && username) label.textContent = username;
}

export async function ensureAuthenticated() {
  try {
    const data = await fetchJson("/auth/me");
    hideLogin(data?.user?.username || "");
    return data.user;
  } catch (e) {
    if (e.status === 401) {
      showLogin("");
      return null;
    }
    throw e;
  }
}

export function wireLoginForm() {
  const form = $("loginForm");
  if (!form) return;
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const username = ($("loginUsername")?.value || "").trim();
    const password = $("loginPassword")?.value || "";
    try {
      await fetchJson("/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
      await ensureAuthenticated();
    } catch (e) {
      showLogin(e.message || "Login failed");
    }
  });

  const logoutBtn = $("logoutBtn");
  if (logoutBtn) {
    logoutBtn.addEventListener("click", async () => {
      try {
        await fetchJson("/auth/logout", { method: "POST" });
      } catch (_) {
        /* ignore */
      }
      showLogin("");
    });
  }
}
