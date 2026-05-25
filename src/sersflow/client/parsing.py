from __future__ import annotations

import re
import warnings
from dataclasses import dataclass
from typing import Any

_UPLOAD_RE = re.compile(
    r"Uploaded\s+(\d+)\s+file\(s\)\s+to\s+batch\s+([^\s(]+)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class UploadResult:
    """Parsed response from ``POST /io/upload`` (plain text)."""

    message: str
    files_saved: int | None
    batch_id: str | None


def parse_upload_response(text: str) -> UploadResult:
    m = _UPLOAD_RE.search(text or "")
    if not m:
        return UploadResult(message=text, files_saved=None, batch_id=None)
    return UploadResult(
        message=text,
        files_saved=int(m.group(1)),
        batch_id=m.group(2).strip(),
    )
