"""#550 unit 5: supports written through `set_skills` reach a forced spectre's FullDPS.

The witness (`artifacts/trace-550/witness-173.pob.txt`: Raise Spectre alone, count 2, Pyromaniac) read 53,095 alone and
208,466 with four supports when the supports were edited into the XML, yet the pipeline's support re-pick scored every
one-support trial equal to the bare link. This writes the trials through the path the generator uses
(`Skeleton.skill_payload(main_link=...)` -> `PobSession.set_skills`).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from junkroan.pob.session import PobSession, decode_import_code  # noqa: E402
from junkroan.search.skeleton import Skeleton  # noqa: E402

WITNESS = ROOT / "artifacts" / "trace-550"
LOCK = json.loads((ROOT / "locks" / "pob.lock.json").read_text(encoding="utf-8"))
RUNTIME_ROOT = ROOT / "var" / "cache" / "pob" / LOCK["tag"] / LOCK["extract_subdir"]
needs_pob = pytest.mark.skipif(
    not (RUNTIME_ROOT / "lua51.dll").is_file() or not (WITNESS / "witness-173.pob.txt").is_file(),
    reason="pinned PoB runtime or the #550 witness is not present",
)

ALONE = ["Raise Spectre"]
ONE = ["Raise Spectre", "Minion Damage"]
FOUR = ["Raise Spectre", "Elemental Penetration", "Spell Echo", "Minion Damage", "Concentrated Effect"]


def _fulldps(pob: PobSession, skeleton: Skeleton, link: list[str]) -> float:
    pob.set_skills(**skeleton.skill_payload(main_link=link))
    return float(pob.stats(["FullDPS"])["FullDPS"])


@pytest.mark.pob
@needs_pob
def test_supports_move_fulldps_through_set_skills(tmp_path: Path) -> None:
    skeleton = Skeleton.from_json(json.loads((WITNESS / "witness-173.json").read_text(encoding="utf-8"))["skeleton"])
    assert skeleton.forced_spectres and skeleton.main_link == ALONE
    xml = decode_import_code((WITNESS / "witness-173.pob.txt").read_text(encoding="utf-8").strip())
    seen: list[tuple[str, float]] = []
    with PobSession(run_id="test-550-u5", artifacts_root=tmp_path) as pob:
        pob.load_xml(xml)
        # the pipeline's order: bare, one support, bare again, four supports, one support again
        for label, link in (("a", ALONE), ("b", ONE), ("a2", ALONE), ("c", FOUR), ("b2", ONE), ("a3", ALONE)):
            seen.append((label, _fulldps(pob, skeleton, link)))
    values = dict(seen)
    print("\n" + "  ".join(f"{k}={v:,.0f}" for k, v in seen))
    assert values["a"] == values["a2"] == values["a3"] > 0, seen  # no stale value after a support came and went
    assert values["b"] > values["a"] * 1.01, seen
    assert values["b2"] == values["b"], seen
    assert values["c"] > values["b"], seen


def _pipeline_at_pick_time(pob: PobSession, skeleton: Skeleton):
    """The pipeline's own judging and generator over the witness, the main link holding the screen's four supports
    (the state `_improvement` hands to the support re-pick)."""

    from junkroan.optimizer.objective_select import objective_for
    from junkroan.optimizer.pipeline import BuildPipeline
    from junkroan.optimizer.rails import Rails

    rails = Rails.load()
    pipeline = BuildPipeline(pob, rails, objective=objective_for(rails, "Raise Spectre"), log=lambda _m: None)
    skeleton.main_link = list(FOUR)
    skeleton.apply_skills(pob, gem_level=rails.gems.level, gem_quality=rails.gems.quality, main_quality=rails.gems.main_quality)
    lanes = pipeline.judging.relane(skeleton)
    pipeline.judging.open_contexts(skeleton, lanes)
    pipeline.judging.rejudge(skeleton)
    return rails, pipeline


@pytest.mark.pob
@needs_pob
def test_a_rejudge_after_a_trial_link_keeps_the_trial_link_in_pob(tmp_path: Path) -> None:
    """A trial link is on the build before it is on the skeleton: `rejudge` (the support pick's `full` re-derivation)
    must not put the skeleton's own link back through `refresh_minion_counts`."""

    skeleton = Skeleton.from_json(json.loads((WITNESS / "witness-173.json").read_text(encoding="utf-8"))["skeleton"])
    xml = decode_import_code((WITNESS / "witness-173.pob.txt").read_text(encoding="utf-8").strip())
    with PobSession(run_id="test-550-u5-rejudge", artifacts_root=tmp_path) as pob:
        pob.load_xml(xml)
        _rails, pipeline = _pipeline_at_pick_time(pob, skeleton)
        four = float(pob.stats(["FullDPS"])["FullDPS"])
        gen = pipeline._generator()
        gen._set_main_link(skeleton, ONE)
        trial = float(pob.stats(["FullDPS"])["FullDPS"])
        pipeline.judging.rejudge(skeleton)
        after = float(pob.stats(["FullDPS"])["FullDPS"])
    print(f"\nfour={four:,.0f} trial(one support)={trial:,.0f} after rejudge={after:,.0f}")
    assert four > trial > 0
    assert after == trial


@pytest.mark.pob
@needs_pob
def test_the_support_repick_keeps_supports_that_move_fulldps(tmp_path: Path) -> None:
    skeleton = Skeleton.from_json(json.loads((WITNESS / "witness-173.json").read_text(encoding="utf-8"))["skeleton"])
    xml = decode_import_code((WITNESS / "witness-173.pob.txt").read_text(encoding="utf-8").strip())
    with PobSession(run_id="test-550-u5-repick", artifacts_root=tmp_path) as pob:
        pob.load_xml(xml)
        rails, pipeline = _pipeline_at_pick_time(pob, skeleton)
        pipeline.judging.rejudge(skeleton)
        gen = pipeline._generator()
        gen.pick_supports(skeleton, n_supports=rails.gems.main_link_max - 1, reconfigure=pipeline.judging.rejudger(skeleton))
        picked = list(skeleton.main_link)
        score = pipeline.objective.score(pob.stats(pipeline.objective.stat_keys)).value
    print(f"\nre-picked link {picked[1:]} score {score:,.0f}")
    assert len(picked) > 1, picked  # the bare link was the only thing the re-pick ever kept
    assert score > 53_095 * 1.5
