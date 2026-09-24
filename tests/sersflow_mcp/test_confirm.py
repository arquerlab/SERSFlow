"""Confirmation gate tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from sersflow.mcp import confirm


def test_upload_size_requires_confirm(tmp_path: Path) -> None:
    big = tmp_path / "a.bin"
    big.write_bytes(b"x" * 200)
    blocked = confirm.check_upload_size([big], threshold=100, confirm=False)
    assert blocked is not None
    assert blocked["needs_confirm"] is True
    assert blocked["reason"] == "upload_exceeds_threshold"
    ok = confirm.check_upload_size([big], threshold=100, confirm=True)
    assert ok is None


def test_fitting_components_gate() -> None:
    pipe = {
        "steps": [
            {
                "name": "fitting",
                "enabled": True,
                "params": {"components": [{"component_id": f"c{i}"} for i in range(7)]},
            }
        ]
    }
    blocked = confirm.check_fitting_components(pipe, max_components=6, confirm=False)
    assert blocked is not None
    assert blocked["details"]["components"] == 7
    assert confirm.check_fitting_components(pipe, max_components=6, confirm=True) is None


def test_overwrite_rejected() -> None:
    assert confirm.reject_overwrite(True)["error"] == "policy"
    assert confirm.reject_overwrite(False) is None


def test_upload_missing_path(tmp_path: Path) -> None:
    missing = tmp_path / "nope.bin"
    with pytest.raises(FileNotFoundError, match="nope.bin"):
        confirm.check_upload_size([missing], threshold=100, confirm=False)


def test_upload_folder_pattern_size(tmp_path: Path) -> None:
    d = tmp_path / "data"
    d.mkdir()
    (d / "a.txt").write_bytes(b"x" * 50)
    (d / "b.bin").write_bytes(b"y" * 5000)
    # Only *.txt counted when pattern set
    blocked = confirm.check_upload_size([d], threshold=100, confirm=False, folder_pattern="*.txt")
    assert blocked is None
    blocked2 = confirm.check_upload_size([d], threshold=10, confirm=False, folder_pattern="*.txt")
    assert blocked2 is not None
    assert blocked2["details"]["files"] == 1
