import { useEffect, useState } from "react";
import { fetchJson } from "./lib/http";

type UserRow = { user_id: string; username: string; is_superuser: boolean };
type MeResponse = {
  user: { username: string; is_superuser: boolean };
  act_as?: { scope: string; label: string; user_id?: string | null };
};

export default function UserScopeSelect() {
  const [users, setUsers] = useState<UserRow[]>([]);
  const [value, setValue] = useState("all");
  const [visible, setVisible] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const me = await fetchJson<MeResponse>("/auth/me");
        if (cancelled || !me.user?.is_superuser) return;
        const rows = await fetchJson<UserRow[]>("/auth/users");
        if (cancelled) return;
        setUsers(rows);
        setVisible(true);
        const act = me.act_as;
        if (!act || act.scope === "all") {
          setValue("all");
        } else if (act.user_id) {
          setValue(act.user_id);
        } else {
          const match = rows.find((u) => u.username === act.label);
          setValue(match?.user_id ?? "all");
        }
      } catch {
        /* not superuser or not logged in */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (!visible) return null;

  async function onChange(next: string) {
    setBusy(true);
    try {
      await fetchJson("/auth/act-as", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ scope: next }),
      });
      window.location.reload();
    } catch {
      setBusy(false);
    }
  }

  return (
    <label className="hint" style={{ margin: 0, display: "inline-flex", alignItems: "center", gap: "6px" }}>
      View as
      <select
        className="mini"
        value={value}
        disabled={busy}
        onChange={(e) => void onChange(e.target.value)}
        title="Superuser: filter data to one user or show everyone"
      >
        <option value="all">All users</option>
        {users.map((u) => (
          <option key={u.user_id} value={u.user_id}>
            {u.username}
          </option>
        ))}
      </select>
    </label>
  );
}
