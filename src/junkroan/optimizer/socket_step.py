"""The socket-colour step of `_finish` (#435): whiten every socket, then colour at most N of them by PoB's numbers.

Since 3.29 a socket is white by default and takes any gem; a socket of the gem's colour gives the gem +10 %
quality (PoB's `matchesSocket`). Rulebook row `gm-sockets`: on day 1 at most 2 coloured sockets per build.
Which sockets get a colour is an optimizer decision: each candidate is tried in PoB and kept only when the
objective's own comparison says it beats the build without it.

The socket a gem sits in is PoB's own rule (SkillsTab.lua `UpdateSocketGroups`): the gem at index i of a
group in slot S sits in socket `gemOffset + i`, where `gemOffset` is the number of gems (enabled or not) of
the earlier groups in the same slot; an item with SocketAlwaysMatches matches every gem and is left alone.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from junkroan.optimizer.socket_colours import ColourCandidate, ColourPick, pick_colours
from junkroan.optimizer.trace import TRACE
from junkroan.pob.session import raw_with_sockets
from junkroan.search.sockets import coloured_max, gem_colour, linked_white, whiten

# weapons, armour, jewellery; jewels and flasks have no gem sockets
SOCKET_SLOTS = ("Weapon 1", "Weapon 2", "Helmet", "Body Armour", "Gloves", "Boots", "Amulet", "Ring 1", "Ring 2", "Belt")
ALWAYS_MATCHES = "Gems Socketed always have the Quality bonus from Socket Colour"


def _sockets_line(raw: str) -> str | None:
    for line in raw.splitlines():
        if line.strip().startswith("Sockets:"):
            return line.split(":", 1)[1].strip()
    return None


def candidate_sockets(incumbent_raw: str | None, base: str, default: str | None) -> str | None:
    """The `Sockets:` text a loop gear candidate of ``base`` is rolled with (#548): the incumbent's own line
    verbatim (count, links, colours the colour step wrote), so the candidate is judged under the socket
    colours the incumbent is. ``default`` (the skeleton's) when the slot has no incumbent, the incumbent has no
    line, or its item class is not ``base``'s (a Quiver against a Shield cannot hold the incumbent's sockets)."""

    line = _sockets_line(incumbent_raw) if isinstance(incumbent_raw, str) else None
    if not line:
        return default
    from junkroan.optimizer.item_bases import type_of
    from junkroan.optimizer.trace import _base_type

    own, wanted = _base_type(incumbent_raw), type_of(base)
    if own and wanted and own != wanted:
        return default
    return line


def _letters(sockets: str) -> list[str]:
    """The sockets in PoB's order (links and spaces dropped): the index a gem's position is read against."""

    return [ch for ch in sockets if ch not in "- " and not ch.isspace()]


def slot_groups(pob: Any) -> dict[str, list[tuple[str, bool]]]:
    """Per item slot, the gems of its socket groups in PoB's socket order: (gem name, enabled).

    Every gem takes a socket index, enabled or not (SkillsTab.lua:1243 `slotSocketedCounts[slot] += #gemList`)."""

    skills = (pob.read_state() or {}).get("skills_state") or {}
    out: dict[str, list[tuple[str, bool]]] = {}
    for group in skills.get("socket_groups") or []:
        slot = group.get("slot") if isinstance(group, dict) else None
        if not isinstance(slot, str) or not slot:
            continue
        for gem in group.get("gems") or []:
            if isinstance(gem, dict):
                name = str(gem.get("gem_name") or gem.get("name") or "")
                out.setdefault(slot, []).append((name, gem.get("enabled") is not False))
    return out


def whiten_equipped(pob: Any, raws: Mapping[str, str], groups: Mapping[str, list[tuple[str, bool]]]) -> dict[str, str]:
    """Make every socket of every equipped item white; returns the new raw per slot that changed.

    Links and the socket count stay. A slot that holds a socket group while its item has no `Sockets:` line
    gets `linked_white(<gems in the slot's groups>)`. A SocketAlwaysMatches item is left as it is."""

    changed: dict[str, str] = {}
    for slot in SOCKET_SLOTS:
        raw = raws.get(slot)
        if raw is None or ALWAYS_MATCHES in raw:
            continue
        current = _sockets_line(raw)
        if current is None:
            n = len(groups.get(slot) or ())
            if n:
                changed[slot] = raw_with_sockets(raw, linked_white(n))
        elif whiten(current) != current:
            changed[slot] = raw_with_sockets(raw, whiten(current))
    if changed:
        pob.equip(changed)
    return changed


def colour_candidates(raws: Mapping[str, str], groups: Mapping[str, list[tuple[str, bool]]]) -> list[ColourCandidate]:
    """Every enabled R/G/B gem at a socket the item has (and that is not an abyss socket)."""

    out: list[ColourCandidate] = []
    for slot, gems in groups.items():
        raw = raws.get(slot)
        if slot not in SOCKET_SLOTS or raw is None or ALWAYS_MATCHES in raw:  # a weapon-swap slot is not the build's gear
            continue
        letters = _letters(_sockets_line(raw) or "")
        for position, (name, enabled) in enumerate(gems):
            colour = gem_colour(name.removesuffix(" Support"))
            if enabled and colour in ("R", "G", "B") and position < len(letters) and letters[position] != "A":
                out.append(ColourCandidate(slot, position, name, colour))
    return out


def colour_step(
    pob: Any,
    objective: Any,
    better: Callable[[Any, Any], bool],
    log: Callable[[str], None],
    *,
    stage: str = "day1",
) -> ColourPick:
    """Whiten the build's sockets, then colour the best at most `coloured_max(stage)` of them; log the result.

    `better(new, current)` is the objective's own acceptance rule over Scores (`objective.better_score`)."""

    keys = objective.stat_keys
    groups = slot_groups(pob)
    raws = dict(pob.equipped_item_raws())
    before_whitening = objective.score(pob.stats(keys))  # the build as it came: the whitening's own share of the drop (#547)
    changed = whiten_equipped(pob, raws, groups)
    raws.update(changed)
    base = objective.score(pob.stats(keys))
    candidates = colour_candidates(raws, groups)

    def count_round(options: list[list[ColourCandidate]]) -> None:
        for option in options:  # a candidate retried after a pick is a different build: generated again
            TRACE.add_generated({f"socket-colour:{option[-1].colour}"})

    def with_picks(picks: list[ColourCandidate]) -> dict[str, str]:
        chosen: dict[str, dict[int, str]] = {}
        for p in picks:
            chosen.setdefault(p.slot, {})[p.position] = p.colour
        return {
            slot: raw_with_sockets(raws[slot], whiten(_sockets_line(raws[slot]) or "", pos))
            for slot, pos in chosen.items()
        }

    def trial(picks: list[ColourCandidate]) -> Any:
        touched = with_picks(picks)
        pob.equip(touched)
        try:
            TRACE.add_evaluated({f"socket-colour:{picks[-1].colour}"})
            return objective.score(pob.stats(keys))
        finally:
            pob.equip({slot: raws[slot] for slot in touched})

    result = pick_colours(candidates, trial, base, coloured_max(stage), better=better, on_round=count_round)
    if result.picks:
        pob.equip(with_picks(result.picks))
        names = ", ".join(f"{p.gem} {p.colour}" for p in result.picks)
        log(f"sockets coloured: {names}, score {before_whitening.value:,.0f} -> whitened {result.score_before.value:,.0f} -> {result.score_after.value:,.0f}")
    else:
        log(f"sockets coloured: none, score {before_whitening.value:,.0f} -> whitened {base.value:,.0f}")
    return result


def sync_gear_sockets(gear: Any, pob: Any) -> None:
    """Carry the new `Sockets:` lines to the gear lane's incumbents, so a later gear move that keeps the
    incumbent keeps its white (and coloured) sockets."""

    current = gear.current_raw
    if not isinstance(current, dict) or not current:
        return
    raws = pob.equipped_item_raws()
    for slot, old in list(current.items()):
        line = _sockets_line(raws.get(slot) or "")
        if slot in SOCKET_SLOTS and line is not None and isinstance(old, str) and ALWAYS_MATCHES not in old:
            current[slot] = raw_with_sockets(old, line)


def socket_lines(pob: Any) -> dict[str, str | None]:
    """The `Sockets:` string of every socket-slot item PoB holds now."""

    return {slot: _sockets_line(raw) for slot, raw in pob.equipped_item_raws().items() if slot in SOCKET_SLOTS}


def socket_state(pob: Any) -> tuple:
    """What the colour step's answer depends on: the sockets strings and the gems (and their order) in each slot.
    `_ensure_sockets` runs the step again only when this differs from what the last step left (#547)."""

    groups = slot_groups(pob)
    return (tuple(sorted(socket_lines(pob).items())), tuple(sorted((slot, tuple(gems)) for slot, gems in groups.items())))
