"""The spectre corpus: PoB's own `Data/Spectres.lua` (`minions["Metadata/Monsters/..."] = { name = "...", ... }`).

A request names a spectre by id or by `name`; this reader resolves either to the id (#173). Never a hand list."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from .game_corpus import DEFAULT_SOURCE_ROOT

SPECTRES_LUA = DEFAULT_SOURCE_ROOT / "src" / "Data" / "Spectres.lua"
_ENTRY = re.compile(r'^minions\["([^"]+)"\]\s*=\s*\{\s*$')
_NAME = re.compile(r'^\s*name\s*=\s*"([^"]*)"')


@lru_cache(maxsize=1)
def spectres() -> dict[str, str]:
    """id -> name, in file order."""

    out: dict[str, str] = {}
    current: str | None = None
    for line in SPECTRES_LUA.read_text(encoding="utf-8").splitlines():
        m = _ENTRY.match(line)
        if m:
            current = m.group(1)
            continue
        if current is not None:
            n = _NAME.match(line)
            if n:
                out[current] = n.group(1)
                current = None
    return out


def resolve_spectre(query: str) -> str | None:
    """The id a request's `--spectre` names, else None. Order: the id itself; a `name` of the corpus; the last
    path segment of an id (`Pyromaniac` -> `.../LeagueCrucible/Cold/Pyromaniac`). All match case-insensitively; when
    one rule matches several ids (some names repeat) the first in `Spectres.lua` order wins."""

    q = query.strip().lower()
    table = spectres()
    for rule in (lambda i, n: i.lower() == q, lambda i, n: n.lower() == q, lambda i, n: i.rsplit("/", 1)[-1].lower() == q):
        for sid, name in table.items():
            if rule(sid, name):
                return sid
    return None
