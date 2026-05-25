"""
Helpers for making feature column names unique when multiple pipeline steps would collide.
"""

from __future__ import annotations


def dedupe_parallel(keys: list[str], owners: list[int]) -> list[str]:
    """
    Return a list of the same length as keys, where the first use of a name is unchanged
    and later collisions get a short numeric suffix ``__{owner}`` (bumped if still taken).
    """
    if len(keys) != len(owners):
        raise ValueError("keys and owners must have the same length")
    seen: set[str] = set()
    out: list[str] = []
    for k, owner in zip(keys, owners):
        nk = k
        if nk not in seen:
            seen.add(nk)
            out.append(nk)
            continue
        sn = int(owner)
        nk = f"{k}__{sn}"
        while nk in seen:
            sn += 1
            nk = f"{k}__{sn}"
        seen.add(nk)
        out.append(nk)
    return out
