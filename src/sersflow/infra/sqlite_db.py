from __future__ import annotations

import functools
import os
import sqlite3
import threading
from pathlib import Path
from typing import Any, Callable, TypeVar

_F = TypeVar("_F", bound=Callable[..., Any])


def db_path() -> Path:
    """
    SQLite DB location for datasets/sessions metadata.

    Override with SERSFLOW_DB_PATH.
    """
    p = os.environ.get("SERSFLOW_DB_PATH")
    if p:
        return Path(p).expanduser().resolve()
    return (Path.cwd() / "sersflow.db").resolve()


class _ClosingConnection(sqlite3.Connection):
    """``with connect() as con:`` commits / rolls back (sqlite3 default) AND closes the connection.

    The stock sqlite3 context manager leaves the connection open until garbage collection.
    """

    def __exit__(self, exc_type, exc, tb):  # type: ignore[no-untyped-def]
        try:
            return super().__exit__(exc_type, exc, tb)
        finally:
            self.close()


_prepared_dirs: set[str] = set()


def connect() -> sqlite3.Connection:
    p = db_path()
    parent = str(p.parent)
    if parent not in _prepared_dirs:
        p.parent.mkdir(parents=True, exist_ok=True)
        _prepared_dirs.add(parent)
    con = sqlite3.connect(str(p), factory=_ClosingConnection)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON;")
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA synchronous=NORMAL;")
    return con


_schema_lock = threading.RLock()
_schema_done: set[tuple[str, str, int]] = set()


def _db_identity(con: sqlite3.Connection | None = None) -> tuple[str, int] | None:
    """
    (path, inode) of the DB file, or None while it does not exist. A deleted / replaced file gets a new identity.

    With a connection, the file is the one THAT connection has open, not whatever SERSFLOW_DB_PATH says now: a
    background job may still hold a connection to a previous database (tests switch databases between cases).
    """
    try:
        if con is not None:
            row = con.execute("PRAGMA database_list").fetchone()
            p = str(row[2] or "") if row is not None else ""
            if not p:
                return None
        else:
            p = str(db_path())
        return p, int(os.stat(p).st_ino)
    except (OSError, sqlite3.Error):
        return None


def schema_once(fn: _F) -> _F:
    """
    Run a store's ``ensure_schema`` once per process and database file instead of on every store call.

    The DDL (CREATE TABLE IF NOT EXISTS, ALTER TABLE probes, backfills) used to run before every query, which cost
    far more than the queries themselves. The key includes the DB file identity, so pointing SERSFLOW_DB_PATH at
    another file (tests) or recreating the file sets the schema up again.
    """
    name = f"{fn.__module__}.{fn.__qualname__}"

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        con = args[0] if args and isinstance(args[0], sqlite3.Connection) else None
        ident = _db_identity(con)
        if ident is not None and (name, *ident) in _schema_done:
            return None
        with _schema_lock:
            ident = _db_identity(con)
            if ident is not None and (name, *ident) in _schema_done:
                return None
            out = fn(*args, **kwargs)
            ident = _db_identity(con)
            if ident is not None:
                _schema_done.add((name, *ident))
            return out

    return wrapper  # type: ignore[return-value]
