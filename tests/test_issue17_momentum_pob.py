"""#17: MomentumStacks is a stack option the ramp budget bounds, measured by PoB on a real build.

The reference is tests/fixtures/tuadh_329/elemental_hit.pob.txt with ONE named change, the "Momentum
swap": the author's own Momentum gem (group 6, Weapon 1, level 19) is moved into the main group
(Body Armour: Elemental Hit 19/20 + Trinity + Elemental Damage with Attacks + Close Combat) in place of
Ruthless, so the main link stays a 5-link; group 6 keeps Shield Charge + Faster Attacks. The swap is
applied through `PobSession.set_skills` and verified through `read_state()["skills_state"]`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from junkroan.optimizer.config_rules import config_surfaces, derive_config, is_stack_option
from junkroan.optimizer.ramp_inputs import reached

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = PROJECT_ROOT / "tests" / "fixtures" / "tuadh_329"
LOCK = json.loads((PROJECT_ROOT / "locks" / "pob.lock.json").read_text(encoding="utf-8"))
RUNTIME_ROOT = PROJECT_ROOT / "var" / "cache" / "pob" / LOCK["tag"] / LOCK["extract_subdir"]
needs_pob = pytest.mark.skipif(not (RUNTIME_ROOT / "lua51.dll").is_file(), reason=f"pinned PoB runtime not present at {RUNTIME_ROOT}")

SWAP = "Momentum swap (author's Momentum 19 from the Weapon 1 group replaces Ruthless in the Elemental Hit main link)"
MAIN_LINK = ["Elemental Hit", "Trinity", "Elemental Damage with Attacks", "Close Combat", "Momentum"]
GEM_LEVELS = {"Elemental Hit": 19, "Trinity": 18, "Elemental Damage with Attacks": 18, "Close Combat": 18, "Momentum": 19}


def _extra_group(slot: str, gems: list[tuple[str, int]]) -> dict:
    return {"label": gems[0][0], "slot": slot, "enabled": True, "include_in_full_dps": False, "group_count": 1,
            "main_active_skill_index": 1,
            "gems": [{"gem_name": n, "level": lvl, "quality": 0, "enabled": True, "count": 1} for n, lvl in gems]}


# the author's other groups, in the author's order, with group 6 minus the moved Momentum
EXTRA_GROUPS = [
    _extra_group("Weapon 2", [("Blood Rage", 18)]),
    _extra_group("Weapon 2", [("Flame Dash", 5)]),
    _extra_group("Helmet", [("Punishment", 18), ("Haste", 18)]),
    _extra_group("Boots", [("Grace", 18)]),
    _extra_group("Weapon 1", [("Shield Charge", 12), ("Faster Attacks", 19)]),
]


@pytest.mark.pob
@needs_pob
def test_momentum_stacks_are_a_ramp_bounded_stack_option_that_PoB_scores(tmp_path: Path) -> None:
    from junkroan.pob.session import PobSession, decode_import_code

    with PobSession(run_id="test-issue17-momentum", artifacts_root=tmp_path) as pob:
        pob.load_xml(decode_import_code((FIXTURES / "elemental_hit.pob.txt").read_text(encoding="utf-8").strip()))
        pob.set_skills(main_link=MAIN_LINK, slot="Body Armour", level=18, quality=0, main_quality=20, main_part=1,
                       extra_groups=EXTRA_GROUPS, gem_levels=GEM_LEVELS)

        # the swap, read back through PoB's own skills_state
        skills = pob.read_state()["skills_state"]
        main_id = skills["main_socket_group_id"]
        groups = {g["gems"][0]["gem_entry_id"].rsplit(".gem.", 1)[0]: g for g in skills["socket_groups"]}
        main = groups[main_id]
        gems = {g["gem_name"]: g for g in main["gems"]}
        assert "Momentum" in gems and gems["Momentum"]["enabled"] and gems["Momentum"]["level"] == 19, f"{SWAP}: {main['gems']}"
        assert "Ruthless" not in gems, f"{SWAP}: Ruthless must be gone from the main group"
        assert main["gem_count"] == 5, f"{SWAP}: the main link stays a 5-link, got {main['gem_count']}"
        entry = main["active_skill_entries"][0]
        supports = [s["name"] for s in entry["support_links"]]
        assert entry["name"] == "Elemental Hit" and "Momentum" in supports, f"{SWAP}: PoB reports Momentum as not supporting Elemental Hit: {entry['name']} supported by {supports}"
        assert any(g["gem_name"] == "Shield Charge" for gr in skills["socket_groups"] for g in gr["gems"]), f"{SWAP}: group 6 lost its other gems"

        # 1. the surface is a stack option on this build
        surfaces = config_surfaces()
        assert is_stack_option({**surfaces["MomentumStacks"], "var": "MomentumStacks"}), f"{SWAP}: MomentumStacks is not a stack option"
        shown = {o["var"] for o in pob.config_options({v: (r.get("predicates") or {}) for v, r in surfaces.items()}) if o.get("shown")}
        assert "MomentumStacks" in shown, f"{SWAP}: PoB does not show MomentumStacks on this build"

        # 3. PoB's default (unset, average 2.5) against the optimistic value, on the build's own boss config
        assert "MomentumStacks" not in pob.config_inputs(), "MomentumStacks must be unset for PoB's default average"
        state = pob.read_state()["config_state"]
        ident = dict(bandit=state.get("bandit") or "None", pantheon_major=state.get("pantheon_major") or "None",
                     pantheon_minor=state.get("pantheon_minor") or "None", enemy_state={"is_boss": "Pinnacle"}, preserve="all")
        pob.set_config(inputs={}, **ident)
        speed = float(pob.stats(("Speed",))["Speed"])
        unset_dps = float(pob.stats(("CombinedDPS",))["CombinedDPS"])

        # 2. the lanes
        derived = derive_config(pob, prefer_rules=True)
        cons, opt = derived.conservative.inputs.get("MomentumStacks"), derived.optimistic.inputs.get("MomentumStacks")
        expected = reached(speed, 2.5, 4)
        assert expected >= 1, f"{SWAP}: Speed {speed} reaches no stack inside 2.5 s"
        assert cons == expected, f"{SWAP}: conservative lane {cons} != reached(Speed {speed:.4f}, 2.5, cap 4) = {expected}; reason: {derived.conservative.reasons.get('MomentumStacks')}"
        cap, share = derived.stack_caps["MomentumStacks"]
        assert cap == 4, f"{SWAP}: PoB's cap {cap} != 4 (gem level 19 -> MomentumStacksMax 4)"
        # the optimistic lane holds the rails ceiling input, which PoB itself caps at 4 (judge_stack_options)
        assert opt is not None and opt >= 4, f"{SWAP}: optimistic lane {opt}; reason: {derived.optimistic.reasons.get('MomentumStacks')}"

        dps = {}
        for name, n in (("conservative", cons), ("optimistic", 4), ("lane_input", opt)):
            pob.set_config(inputs={"MomentumStacks": n}, **ident)
            dps[name] = float(pob.stats(("CombinedDPS",))["CombinedDPS"])
        assert dps["lane_input"] == dps["optimistic"], f"{SWAP}: PoB must cap the optimistic lane input {opt} at 4: {dps}"

    print(f"\n#17 {SWAP}\nSpeed {speed:.4f}; MomentumStacks lanes: conservative {cons}, optimistic lane input {opt} (PoB cap {cap}); "
          f"CombinedDPS unset(default 2.5) {unset_dps:.1f}, conservative {dps['conservative']:.1f}, optimistic(4) {dps['optimistic']:.1f}")
    assert unset_dps < dps["optimistic"], (f"{SWAP}: CombinedDPS unset {unset_dps:.1f} must be below MomentumStacks=4 {dps['optimistic']:.1f} "
                                           f"(conservative {dps['conservative']:.1f})")
