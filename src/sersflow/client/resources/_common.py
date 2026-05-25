from __future__ import annotations

from typing import Any

from pydantic import BaseModel


def dump_json(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(mode="json", by_alias=True, exclude_none=True)


class _Base:
    __slots__ = ("_root",)

    def __init__(self, root: Any):
        self._root = root
