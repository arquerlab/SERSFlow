from __future__ import annotations

import os
import sqlite3
from pathlib import Path


def db_path() -> Path:
    """
    SQLite DB location for datasets/sessions metadata.

    Override with SERSFLOW_DB_PATH.
    """
    p = os.environ.get("SERSFLOW_DB_PATH")
    if p:
        return Path(p).expanduser().resolve()
    return (Path.cwd() / "sersflow.db").resolve()


def connect() -> sqlite3.Connection:
    p = db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(p))
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON;")
    return con

