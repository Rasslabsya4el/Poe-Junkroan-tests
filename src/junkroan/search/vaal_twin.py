"""#802: the Vaal version of a plain active skill gem, read from the corpus (never a hand-written list)."""

from __future__ import annotations

from functools import lru_cache

from junkroan.search.hypothesis import active_gems


@lru_cache(maxsize=1)
def vaal_twins() -> dict[str, str]:
    """Plain active gem name (lower case) -> the corpus's name of its Vaal version.

    A Vaal version is a corpus record with `is_vaal_gem` whose name is "Vaal " + the name of a plain (not Vaal) active
    gem the corpus also holds. Supports are never in `active_gems()`, so the two support names "Vaal ..." are not here."""

    gems = active_gems()
    out: dict[str, str] = {}
    for record in gems.values():
        name = record["name"]
        if not record.get("is_vaal_gem") or not name.startswith("Vaal "):
            continue
        plain = gems.get(name[5:].lower())
        if plain is not None and not plain.get("is_vaal_gem"):
            out[plain["name"].lower()] = name
    return out


def vaal_twin(name: str) -> str | None:
    """The Vaal version of the plain active skill gem ``name``; None when it has none (or is not an active gem)."""

    return vaal_twins().get(str(name).strip().lower())


def plain_of_vaal(name: str) -> str | None:
    """The plain active gem of the Vaal version ``name`` (the inverse of `vaal_twin`); None when ``name`` is not one."""

    key = str(name).strip().lower()
    return next((active_gems()[plain]["name"] for plain, vaal in vaal_twins().items() if vaal.lower() == key), None)
