"""Every build step in order, with its group (#711). Pure data; imports nothing from the pipeline.

The names are those the pipeline records (`pipeline.py` `run()`, `improvement_loop.py`); the AST test in
tests/test_issue711_stage_catalog.py fails when a recorded name is missing here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

CONSTRUCTION = "construction"
IMPROVEMENT_LOOP = "improvement loop"
FINISH = "finish"
GROUPS = (CONSTRUCTION, IMPROVEMENT_LOOP, FINISH)


@dataclass(frozen=True)
class Step:
    name: str  # the display key (the pattern's plain form)
    pattern: str  # a regex the whole stage name must match
    group: str
    label: str  # plain words for the monitor

    def matches(self, stage_name: str) -> bool:
        return re.fullmatch(self.pattern, stage_name) is not None


def _s(name: str, group: str, label: str, pattern: str | None = None) -> Step:
    return Step(name, pattern if pattern is not None else re.escape(name), group, label)


STEPS: tuple[Step, ...] = (
    _s("skeleton applied", CONSTRUCTION, "skeleton applied"),
    _s("config (conservative lane)", CONSTRUCTION, "first config"),
    _s("rig gear", CONSTRUCTION, "rig gear (rig-first only)"),
    _s("rig tree", CONSTRUCTION, "rig tree (rig-first only)"),
    _s("gear pass 1 (rig tree)", CONSTRUCTION, "first gear pass on the rig tree"),
    _s("gear pass 1 (empty tree)", CONSTRUCTION, "first gear pass on an empty tree"),
    _s("config re-derived (after gear pass 1)", CONSTRUCTION, "config re-derived after the first gear pass"),
    _s("flat-reservation aura levels", CONSTRUCTION, "flat-reservation aura levels"),
    _s("supports re-picked (no number)", CONSTRUCTION, "supports re-picked (no number)"),
    _s("tree seed toward <stat>", CONSTRUCTION, "tree seed toward the scaling stat", r"tree seed toward .+"),
    _s("tree greedy", CONSTRUCTION, "tree greedy"),
    _s("gear pass 2 (with tree)", CONSTRUCTION, "second gear pass with the tree"),
    _s("tree rebuilt on gear", CONSTRUCTION, "tree rebuilt on gear"),
    _s("anoint", CONSTRUCTION, "amulet anoint"),
    _s("flasks", CONSTRUCTION, "flasks"),
    _s("clusters", CONSTRUCTION, "cluster jewels"),
    _s("jewels", CONSTRUCTION, "jewels"),
    _s("supports re-picked", CONSTRUCTION, "supports re-picked"),
    _s("utility links", CONSTRUCTION, "utility links"),
    _s("fill", CONSTRUCTION, "fill free sockets"),
    _s("tree refine", CONSTRUCTION, "tree refine (screen run)"),
    _s("loop opening", IMPROVEMENT_LOOP, "improvement loop opening"),
    _s("loop pass <N>", IMPROVEMENT_LOOP, "improvement loop pass", r"loop pass \d+"),
    _s("repair pass <N>", IMPROVEMENT_LOOP, "improvement loop repair pass", r"repair pass \d+"),  # #1064
    _s("fixed point check", IMPROVEMENT_LOOP, "fixed point check"),
    _s("anoint re-pick", FINISH, "anoint re-pick on the final tree"),
    _s("config (final lanes)", FINISH, "final config lanes"),
)

LOOP_MOVES = ("refine", "swaps", "regions", "corridors", "ascendancy-swap", "gear", "weapon-base", "picks", "aura levels", "lanes",
              "kick-tree", "kick-joint")


# #720: the steps and moves that run only under a condition, one plain-words line each (the build-steps page prints
# it instead of a time when no build of the set met it; the monitor reads the flag). A move's key is "move: <name>".
CONDITIONS: dict[str, str] = {
    "rig gear": "the request asks for the rig-first construction",
    "rig tree": "the request asks for the rig-first construction",
    "gear pass 1 (rig tree)": "the request asks for the rig-first construction",
    "config re-derived (after gear pass 1)":
        "the build has a flat-reservation aura and a config input changed when the first gear pass was judged again",
    "supports re-picked (no number)":
        "the build has no score after the first gear pass and some of its supports can be swapped",
    "tree seed toward <stat>": "the skeleton names a stat to scale toward",
    "supports re-picked": "the request switches the supports re-pick on",
    "utility links": "the utility link picking is on and the build has fewer link groups than the limit",
    "fill": "the utility link picking is on, the run is not a screen, the fill_step rail is on",
    "tree refine": "the screen runs are on",
    "repair pass <N>": "a keystone choice is repaired on a finished build (the repair rule of #1064)",
    "move: regions": "the plan of the pass names the regions move",
    "move: corridors": "the plan of the pass names the corridors move",
    "move: ascendancy-swap": "the rails give ascendancy points",
}


def condition_of(key: str) -> str | None:
    return CONDITIONS.get(key)


def step_of(stage_name: str) -> Step | None:
    for step in STEPS:
        if step.matches(stage_name):
            return step
    return None


def group_of(stage_name: str) -> str | None:
    step = step_of(stage_name)
    return step.group if step else None


# -- log lines the monitor / scripts read back ---------------------------------------------------------

_START = "step start: "
_SKIPPED = "step skipped: "
_LOOP_MOVE = re.compile(r"loop pass (\d+) move (.+)")
_CHECK_MOVE = re.compile(r"(fixed point check) move (.+)")


def start_line(name: str) -> str:
    return f"{_START}{name}"


def skipped_line(name: str) -> str:
    return f"{_SKIPPED}{name}"


def loop_move_line(pass_no: int, move: str, where: str | None = None, *, prefix: str = "loop") -> str:
    if where == "fixed point check":  # the check pass is not "pass 1" of the loop
        return f"{where} move {move}"
    return f"{prefix} pass {pass_no} move {move}"  # prefix "repair" for the repair (#1064)


def parse_log_line(line: str) -> tuple[str | None, object]:
    """("start", name) | ("skipped", name) | ("loop_move", (pass_no | "fixed point check", move)) | (None, None)."""

    text = line.strip()
    if text.startswith(_START):
        return "start", text[len(_START):]
    if text.startswith(_SKIPPED):
        return "skipped", text[len(_SKIPPED):]
    found = _LOOP_MOVE.fullmatch(text)
    if found:
        return "loop_move", (int(found.group(1)), found.group(2))
    found = _CHECK_MOVE.fullmatch(text)
    if found:
        return "loop_move", (found.group(1), found.group(2))
    return None, None


# -- the descriptions (#713) ---------------------------------------------------------------------------

def descriptions() -> dict:
    """Every description written so far, by step name (a loop move: "move: <name>"). The texts live in step_text_*.py."""

    from junkroan.optimizer import step_text_c1, step_text_c2, step_text_c3, step_text_loop1, step_text_loop2

    merged: dict = {}
    for module in (step_text_c1, step_text_c2, step_text_c3, step_text_loop1, step_text_loop2):
        merged.update(module.TEXT)
    return merged
