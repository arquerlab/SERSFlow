from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

import bcrypt

from sersflow.infra.sqlite_db import connect, schema_once


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class UserRecord:
    user_id: str
    username: str
    created_at: str
    is_superuser: bool = False


def _row_to_user(row: sqlite3.Row) -> UserRecord:
    return UserRecord(
        user_id=row["user_id"],
        username=row["username"],
        created_at=row["created_at"],
        is_superuser=bool(int(row["is_superuser"] or 0)),
    )


@schema_once
def ensure_schema() -> None:
    with connect() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
              user_id TEXT PRIMARY KEY,
              username TEXT NOT NULL UNIQUE,
              password_hash TEXT NOT NULL,
              created_at TEXT NOT NULL,
              is_superuser INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
            """
        )
        for ddl in (
            "ALTER TABLE users ADD COLUMN is_superuser INTEGER NOT NULL DEFAULT 0",
            # Bumped on password change / disable: every session cookie signed before the bump stops working.
            "ALTER TABLE users ADD COLUMN session_version INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE users ADD COLUMN disabled INTEGER NOT NULL DEFAULT 0",
        ):
            try:
                con.execute(ddl)
            except sqlite3.OperationalError:
                pass


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def create_user(*, username: str, password: str, is_superuser: bool = False) -> UserRecord:
    ensure_schema()
    name = username.strip()
    if not name:
        raise ValueError("username is required")
    if not password:
        raise ValueError("password is required")
    user_id = f"usr_{uuid4().hex}"
    now = _utc_now_iso()
    pw_hash = _hash_password(password)
    with connect() as con:
        try:
            con.execute(
                """
                INSERT INTO users(user_id, username, password_hash, created_at, is_superuser)
                VALUES (?,?,?,?,?)
                """,
                (user_id, name, pw_hash, now, 1 if is_superuser else 0),
            )
        except sqlite3.IntegrityError as e:
            if "UNIQUE" in str(e).upper():
                raise ValueError(f"username already exists: {name}") from e
            raise
    return UserRecord(user_id=user_id, username=name, created_at=now, is_superuser=is_superuser)


_DUMMY_HASH: bytes | None = None


def _burn_password_check(password: str) -> None:
    """Spend the bcrypt time of a real check, so an unknown username is not rejected faster than a wrong password."""
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = bcrypt.hashpw(b"sersflow-no-such-user", bcrypt.gensalt())
    try:
        bcrypt.checkpw(password.encode("utf-8"), _DUMMY_HASH)
    except ValueError:
        pass


def verify_user(*, username: str, password: str) -> UserRecord | None:
    ensure_schema()
    name = username.strip()
    if not name or not password:
        return None
    with connect() as con:
        row = con.execute(
            """
            SELECT user_id, username, password_hash, created_at, is_superuser, disabled
            FROM users WHERE username = ?
            """,
            (name,),
        ).fetchone()
    stored = str(row["password_hash"] or "") if row is not None else ""
    if not stored:
        _burn_password_check(password)
        return None
    try:
        ok = bcrypt.checkpw(password.encode("utf-8"), stored.encode("ascii"))
    except ValueError:
        return None
    if not ok or int(row["disabled"] or 0):
        return None
    return _row_to_user(row)


# --- session state (revocation) ---------------------------------------------------------------------------------

_SESSION_STATE_TTL_S = 15.0
_session_state_cache: dict[str, tuple[float, tuple[int, bool] | None]] = {}
_session_state_lock = threading.Lock()


def invalidate_session_state_cache() -> None:
    with _session_state_lock:
        _session_state_cache.clear()


def session_state(user_id: str) -> tuple[int, bool] | None:
    """
    (session_version, disabled) of a user, None when the user does not exist.

    Checked on every authenticated request, so it is cached for a few seconds: a password change or disable made
    with ``sersflow-admin`` (another process) takes effect within ``_SESSION_STATE_TTL_S``.
    """
    now = time.monotonic()
    with _session_state_lock:
        hit = _session_state_cache.get(user_id)
        if hit is not None and now - hit[0] < _SESSION_STATE_TTL_S:
            return hit[1]
    ensure_schema()
    with connect() as con:
        row = con.execute("SELECT session_version, disabled FROM users WHERE user_id = ?", (user_id,)).fetchone()
    state = (int(row["session_version"] or 0), bool(int(row["disabled"] or 0))) if row is not None else None
    with _session_state_lock:
        if len(_session_state_cache) > 4096:
            _session_state_cache.clear()
        _session_state_cache[user_id] = (now, state)
    return state


def set_password(*, username: str, password: str) -> UserRecord:
    """Change a password and sign the user out everywhere (existing session cookies stop working)."""
    ensure_schema()
    if not password:
        raise ValueError("password is required")
    user = get_user_by_username(username)
    if user is None:
        raise ValueError(f"user not found: {username}")
    with connect() as con:
        con.execute(
            "UPDATE users SET password_hash = ?, session_version = session_version + 1 WHERE user_id = ?",
            (_hash_password(password), user.user_id),
        )
    invalidate_session_state_cache()
    return user


def set_disabled(*, username: str, disabled: bool) -> UserRecord:
    """Disable (or re-enable) an account. Disabling also ends the user's sessions; their data is kept."""
    ensure_schema()
    user = get_user_by_username(username)
    if user is None:
        raise ValueError(f"user not found: {username}")
    with connect() as con:
        con.execute(
            "UPDATE users SET disabled = ?, session_version = session_version + 1 WHERE user_id = ?",
            (1 if disabled else 0, user.user_id),
        )
    invalidate_session_state_cache()
    return user


def get_user_by_id(user_id: str) -> UserRecord | None:
    ensure_schema()
    with connect() as con:
        row = con.execute(
            "SELECT user_id, username, created_at, is_superuser FROM users WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    if row is None:
        return None
    return _row_to_user(row)


def get_user_by_username(username: str) -> UserRecord | None:
    ensure_schema()
    name = username.strip()
    if not name:
        return None
    with connect() as con:
        row = con.execute(
            "SELECT user_id, username, created_at, is_superuser FROM users WHERE username = ?",
            (name,),
        ).fetchone()
    if row is None:
        return None
    return _row_to_user(row)


def is_superuser(user_id: str) -> bool:
    user = get_user_by_id(user_id)
    return bool(user and user.is_superuser)


def list_users(*, limit: int = 200) -> list[UserRecord]:
    ensure_schema()
    lim = max(1, min(500, int(limit)))
    with connect() as con:
        rows = con.execute(
            """
            SELECT user_id, username, created_at, is_superuser
            FROM users
            ORDER BY username ASC
            LIMIT ?
            """,
            (lim,),
        ).fetchall()
    return [_row_to_user(row) for row in rows]


def set_superuser(*, username: str, superuser: bool) -> UserRecord:
    ensure_schema()
    user = get_user_by_username(username)
    if user is None:
        raise ValueError(f"user not found: {username}")
    with connect() as con:
        con.execute(
            "UPDATE users SET is_superuser = ? WHERE user_id = ?",
            (1 if superuser else 0, user.user_id),
        )
    updated = get_user_by_id(user.user_id)
    assert updated is not None
    return updated
