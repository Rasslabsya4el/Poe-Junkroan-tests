"""Option classes of #429's day-1 template rule: resistance line tier, resistance lines per item, weapon line count.

Importing this module registers the class function with `trace.register_class`; PoB-free."""

from __future__ import annotations

import re
from typing import Iterable

from junkroan.optimizer.trace import register_class

_RES = re.compile(r"^\+(\d+(?:\.\d+)?)% to (?:Fire|Cold|Lightning) Resistance$")
_IMPLICITS = re.compile(r"^Implicits:\s*(\d+)$")
_NOT_A_MOD = ("Corrupted", "Mirrored", "Split", "Unidentified", "Crafted")
_AFFIX_HEADER = re.compile(r"^(?:Prefix|Suffix):\s*(?:\{[^}]*\})*\s*(\S+)$")


def _strip(line: str) -> str:
    return re.sub(r"^(?:\{[^}]*\})+", "", line).strip()


def _is_weapon(item: dict, lines: list[str]) -> bool:
    """A weapon by its slot, not by header lines: PoB's BuildRaw (what the gear move stores) has no "Physical Damage:" line."""

    if any(ln.startswith(("Physical Damage:", "Attacks per Second:")) for ln in lines):
        return True
    if item.get("slot") not in ("Weapon 1", "Weapon 2"):
        return False
    base = lines[2] if len(lines) > 2 else ""
    return not base.endswith(("Shield", "Buckler", "Quiver"))


def _affix_count(lines: list[str], mods: list[str]) -> int:
    """Affixes on the item, not text lines: a hybrid mod or a two-line bench craft is one affix (#429 u3).

    The count comes from the data the raw carries: one `Prefix:`/`Suffix:` header per picked mod (id "None" = empty
    slot), and one for the bench craft (every `{crafted}` line belongs to the one craft). A raw without those headers
    falls back to its non-crafted text lines."""

    ids = [m.group(1) for m in (_AFFIX_HEADER.match(ln) for ln in lines) if m]
    crafted = any(ln.startswith("{crafted}") for ln in mods)
    if ids:
        explicit = sum(1 for i in ids if i != "None")
    else:
        explicit = sum(1 for ln in mods if not ln.startswith("{crafted}"))
    return explicit + (1 if crafted else 0)


def template_classes(trial: dict) -> Iterable[str]:
    item = trial.get("item") if isinstance(trial, dict) else None
    raw = item.get("raw") if isinstance(item, dict) else None
    if not isinstance(raw, str):
        return []
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    if not any(ln.lower() == "rarity: rare" for ln in lines):
        return []
    idx = next((i for i, ln in enumerate(lines) if _IMPLICITS.match(ln)), None)
    if idx is None:
        return []
    n_impl = int(_IMPLICITS.match(lines[idx]).group(1))
    mods = [ln for ln in lines[idx + 1 + n_impl :] if _strip(ln) not in _NOT_A_MOD]
    out: list[str] = []
    res = [m for m in (_RES.match(_strip(ln)) for ln in mods) if m]
    for m in res:
        out.append("res-line:36-41" if 36 <= float(m.group(1)) <= 41 else "res-line:other")
    if res:
        out.append(f"res-lines:{len(res)}")
    if _is_weapon(item, lines):
        out.append(f"weapon-lines:{_affix_count(lines, mods)}")
    return out


register_class(template_classes)
