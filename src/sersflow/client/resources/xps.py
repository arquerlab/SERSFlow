"""XPS chemical-states and fitting-recipes client."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sersflow.client.http import request_json
from sersflow.client.resources._common import _Base

if TYPE_CHECKING:
    from sersflow.client.client import SersflowClient


class XpsResource(_Base):
    def __init__(self, root: SersflowClient):
        super().__init__(root)

    def chemical_states(
        self,
        *,
        element: str | None = None,
        line: str | None = None,
        q: str | None = None,
        provenance: str | None = None,
        include_sections: bool = False,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"include_sections": include_sections}
        if element is not None:
            params["element"] = element
        if line is not None:
            params["line"] = line
        if q is not None:
            params["q"] = q
        if provenance is not None:
            params["provenance"] = provenance
        data = request_json(self._root.http, "GET", "/xps/chemical-states", params=params)
        return dict(data) if isinstance(data, dict) else {}

    def fitting_recipes_index(
        self,
        *,
        element: str | None = None,
        region: str | None = None,
        q: str | None = None,
        source_table: str | None = None,
        limit: int = 25,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit}
        if element is not None:
            params["element"] = element
        if region is not None:
            params["region"] = region
        if q is not None:
            params["q"] = q
        if source_table is not None:
            params["source_table"] = source_table
        data = request_json(self._root.http, "GET", "/xps/fitting-recipes/index", params=params)
        return dict(data) if isinstance(data, dict) else {}

    def fitting_recipes(
        self,
        *,
        element: str | None = None,
        region: str | None = None,
        q: str | None = None,
        source_table: str | None = None,
        chapter: int | None = None,
        include_methods: bool = True,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"include_methods": include_methods}
        if element is not None:
            params["element"] = element
        if region is not None:
            params["region"] = region
        if q is not None:
            params["q"] = q
        if source_table is not None:
            params["source_table"] = source_table
        if chapter is not None:
            params["chapter"] = chapter
        data = request_json(self._root.http, "GET", "/xps/fitting-recipes", params=params)
        return dict(data) if isinstance(data, dict) else {}

    def apply_fitting_recipe(
        self,
        recipe_id: str,
        *,
        pass_energy: int | None = None,
        include_background: bool = True,
        preferred_pass_energy: int | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"include_background": include_background}
        if pass_energy is not None:
            params["pass_energy"] = pass_energy
        if preferred_pass_energy is not None:
            params["preferred_pass_energy"] = preferred_pass_energy
        data = request_json(
            self._root.http,
            "GET",
            f"/xps/fitting-recipes/{recipe_id}/apply",
            params=params,
        )
        return dict(data) if isinstance(data, dict) else {}
