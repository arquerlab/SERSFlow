from __future__ import annotations

from pathlib import Path

import pytest

from sersflow.core.io.upload_registry import ensure_within_root


def test_ensure_within_root_allows_nested(tmp_path: Path) -> None:
    root = tmp_path / "uploads"
    root.mkdir()
    nested = root / "a" / "b.txt"
    nested.parent.mkdir(parents=True)
    nested.write_text("x", encoding="utf-8")
    assert ensure_within_root(root, nested) == nested.resolve()


def test_ensure_within_root_blocks_traversal(tmp_path: Path) -> None:
    root = tmp_path / "uploads"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("nope", encoding="utf-8")
    with pytest.raises(ValueError, match="Path traversal"):
        ensure_within_root(root, outside)

