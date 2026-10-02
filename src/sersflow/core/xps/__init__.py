"""XPS reference catalogs: chemical states and fitting recipes."""

from __future__ import annotations

from sersflow.core.xps.chemical_states import (
    ChemicalStateEntry,
    ChemicalStateSection,
    ChemicalStatesCatalog,
    list_chemical_state_entries,
    load_chemical_states_catalog,
)
from sersflow.core.xps.fitting_recipes import (
    CompoundFit,
    FittingRecipesCatalog,
    MethodDefault,
    list_compound_fits,
    list_method_defaults,
    load_fitting_recipes_catalog,
)

__all__ = [
    "ChemicalStateEntry",
    "ChemicalStateSection",
    "ChemicalStatesCatalog",
    "CompoundFit",
    "FittingRecipesCatalog",
    "MethodDefault",
    "list_chemical_state_entries",
    "list_compound_fits",
    "list_method_defaults",
    "load_chemical_states_catalog",
    "load_fitting_recipes_catalog",
]
