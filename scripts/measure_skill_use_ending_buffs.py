"""Measure conservative lanes before and after excluding skill-use-ending buffs.

This is a one-session report helper, not a test.  The previous behavior is
reconstructed from each loaded build by restoring the old Withering Step
gem-only proof; it never imports another checkout's code.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "src")]

from benchmark import SETS, fixture_path  # noqa: E402
from junkroan.optimizer.config_rules import _gem_names, config_surfaces, derive_config  # noqa: E402
from junkroan.pob.session import PobSession, decode_import_code  # noqa: E402


KEYS = ("EffectiveMovementSpeedMod", "TotalEHP", "CombinedDPS")
OLD_WITHERING_STEP_INPUTS = frozenset({"buffElusive", "buffPhasing"})


def apply_lane(pob: PobSession, inputs: dict[str, object], conditional: dict[str, object]) -> None:
    state = pob.read_state()["config_state"]
    valid = set(config_surfaces()) - {"enemyIsBoss"}
    pob.set_config(
        bandit=state.get("bandit") or "None",
        pantheon_major=state.get("pantheon_major") or "None",
        pantheon_minor=state.get("pantheon_minor") or "None",
        enemy_state={"is_boss": "Pinnacle"},
        inputs={key: value for key, value in inputs.items() if key in valid},
        conditional={"inputs": {key: value for key, value in conditional.items() if key in valid}},
        preserve="none",
    )


def main() -> None:
    slugs = [*SETS["new18"], *SETS["core14"], *SETS["ziz"]]
    changed: list[tuple[str, dict[str, object], dict[str, object], list[str]]] = []
    with PobSession(run_id="measure-skill-use-ending-buffs") as pob:
        for slug in slugs:
            pob.load_xml(decode_import_code(fixture_path(slug).read_text(encoding="utf-8").strip()))
            derived = derive_config(pob, prefer_rules=True)
            old_inputs = dict(derived.conservative.inputs)
            shown = {str(option.get("var")) for option in derived.shown}
            if "withering step" in {name.lower() for name in _gem_names(pob)}:
                old_inputs.update({var: True for var in OLD_WITHERING_STEP_INPUTS & shown})
            apply_lane(pob, old_inputs, dict(derived.optimistic.inputs))
            before = pob.stats(KEYS)
            apply_lane(pob, dict(derived.conservative.inputs), dict(derived.optimistic.inputs))
            after = pob.stats(KEYS)
            removed = sorted(set(old_inputs) - set(derived.conservative.inputs))
            if removed:
                changed.append((slug, before, after, removed))

    print("changed", len(changed), "of", len(slugs))
    for slug, before, after, removed in changed:
        print(
            slug,
            ", ".join(removed),
            "|",
            " ".join(f"{key} {before.get(key)} -> {after.get(key)}" for key in KEYS),
        )


if __name__ == "__main__":
    main()
