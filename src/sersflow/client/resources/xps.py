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

    # ---- identification (X2) ----
    def line_markers(self, **params: Any) -> dict[str, Any]:
        clean = {k: v for k, v in params.items() if v is not None}
        return dict(request_json(self._root.http, "GET", "/xps/line-markers", params=clean))

    def reference_markers(self, element: str, line: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {"element": element}
        if line:
            params["line"] = line
        return dict(request_json(self._root.http, "GET", "/xps/reference-markers", params=params))

    def survey_detect(self, payload: dict[str, Any]) -> dict[str, Any]:
        return dict(request_json(self._root.http, "POST", "/xps/survey/detect", json_body=payload))

    def list_region_sets(self) -> dict[str, Any]:
        return dict(request_json(self._root.http, "GET", "/xps/region-sets"))

    def get_region_set(self, set_id: str) -> dict[str, Any]:
        return dict(request_json(self._root.http, "GET", f"/xps/region-sets/{set_id}"))

    def create_region_set(self, payload: dict[str, Any]) -> dict[str, Any]:
        return dict(request_json(self._root.http, "POST", "/xps/region-sets", json_body=payload))

    def delete_region_set(self, set_id: str) -> dict[str, Any]:
        return dict(request_json(self._root.http, "DELETE", f"/xps/region-sets/{set_id}"))

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

    def add_spin_orbit_partner(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = request_json(self._root.http, "POST", "/xps/spin-orbit-partner", json_body=payload)
        return dict(data) if isinstance(data, dict) else {}

    def apply_fitting_recipe(
        self,
        recipe_id: str,
        *,
        pass_energy: int | None = None,
        include_background: bool = True,
        preferred_pass_energy: int | None = None,
        lock_satellites: bool = True,
        lock_spin_orbit: bool = True,
        spin_orbit_partner_splitting_eV: float | None = None,
        spin_orbit_partner_subshell: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "include_background": include_background,
            "lock_satellites": lock_satellites,
            "lock_spin_orbit": lock_spin_orbit,
        }
        if spin_orbit_partner_splitting_eV is not None:
            params["spin_orbit_partner_splitting_eV"] = spin_orbit_partner_splitting_eV
        if spin_orbit_partner_subshell:
            params["spin_orbit_partner_subshell"] = spin_orbit_partner_subshell
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
