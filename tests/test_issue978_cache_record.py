"""#978 unit 3: the saved support lists a run started with are recorded next to its transcript, and
`compare_calls` refuses to compare two runs that started with different lists (PoB-free)."""

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("compare_calls", ROOT / "scripts" / "compare_calls.py")
compare_calls = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(compare_calls)
sys.path.insert(0, str(ROOT / "scripts"))

from junkroan.search import generator as gen  # noqa: E402
from junkroan.optimizer.castability import CastabilityMetrics  # noqa: E402
from junkroan.optimizer.objective import Objective  # noqa: E402
from junkroan.optimizer.rails import Rails  # noqa: E402
from junkroan.search.skeleton import Skeleton  # noqa: E402

LIST = "legal_supports-arc.json"
HASH_A = "3f2a9c1d8e7b6a50" + "0" * 48
HASH_B = "c41e07b9a2d3f6e8" + "1" * 48
LINK = ["Arc", "Archmage", "Lightning Penetration", "Unleash", "Spell Echo"]


@pytest.fixture(autouse=True)
def _clean_saved_lists():
    saved = getattr(gen, "SAVED_LISTS", {})  # the name exists once the change is in
    saved.clear()
    yield
    saved.clear()


def _call(seq: int, method: str, args: str) -> dict:
    return {"seq": seq, "method": method, "args": args, "preview": ""}


def _write(path: Path, calls: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(c) + "\n" for c in calls), encoding="utf-8")
    return path


def _lists(path: Path, record: dict) -> None:
    path.write_text(json.dumps(record), encoding="utf-8")


def _pair(tmp_path: Path, name: str, left_calls, right_calls, left_lists, right_lists):
    left = _write(tmp_path / "left" / f"{name}.calls.jsonl", left_calls)
    right = _write(tmp_path / "right" / f"{name}.calls.jsonl", right_calls)
    if left_lists is not None:
        _lists(tmp_path / "left" / f"{name}.lists.json", left_lists)
    if right_lists is not None:
        _lists(tmp_path / "right" / f"{name}.lists.json", right_lists)
    return left, right


CALLS_A = [_call(1, "stats", "aa"), _call(2, "set_skills", "bb")]
CALLS_B = [_call(1, "stats", "aa"), _call(2, "set_skills", "cc")]


# -- row 2: two folders, sidecars differ for one list name; the calls differ too ----------

def test_differing_saved_list_is_not_comparable_and_no_call_diff_is_printed(tmp_path, monkeypatch, capsys):
    _pair(tmp_path, "skeleton-arc", CALLS_A, CALLS_B, {LIST: HASH_A}, {LIST: HASH_B})
    monkeypatch.setattr(sys, "argv", ["compare_calls.py", str(tmp_path / "left"), str(tmp_path / "right")])
    assert compare_calls.main() == 1
    out = capsys.readouterr().out
    assert f"NOT COMPARABLE: saved support list differs ({LIST}: left {HASH_A[:16]} / right {HASH_B[:16]})" in out
    assert "first difference" not in out
    assert "calls per method" not in out


def test_compare_pair_returns_false_on_differing_lists(tmp_path, capsys):
    left, right = _pair(tmp_path, "skeleton-arc", CALLS_A, CALLS_A, {LIST: HASH_A}, {LIST: HASH_B})
    assert compare_calls.compare_pair("skeleton-arc", left, right) is False
    assert "NOT COMPARABLE: saved support list differs" in capsys.readouterr().out


# -- row 3: one side absent, the other a hash ----------------------------------------------

@pytest.mark.parametrize("left_value, right_value, shown", [
    ("absent", HASH_B, "left absent / right c41e07b9a2d3f6e8"),
    (HASH_A, "absent", "left 3f2a9c1d8e7b6a50 / right absent"),
])
def test_absent_against_a_hash_is_not_comparable(tmp_path, capsys, left_value, right_value, shown):
    left, right = _pair(tmp_path, "skeleton-arc", CALLS_A, CALLS_A, {LIST: left_value}, {LIST: right_value})
    assert compare_calls.compare_pair("skeleton-arc", left, right) is False
    out = capsys.readouterr().out
    assert f"NOT COMPARABLE: saved support list differs ({LIST}: {shown})" in out
    assert "IDENTICAL" not in out


def test_a_list_consulted_by_one_side_only_is_not_comparable(tmp_path, capsys):
    left, right = _pair(tmp_path, "skeleton-arc", CALLS_A, CALLS_A, {LIST: HASH_A}, {})
    assert compare_calls.compare_pair("skeleton-arc", left, right) is False
    assert f"{LIST}: left {HASH_A[:16]} / right not consulted" in capsys.readouterr().out


# -- row 4: equal sidecars and equal calls -------------------------------------------------

def test_equal_sidecars_and_equal_calls_are_identical(tmp_path, capsys):
    left, right = _pair(tmp_path, "skeleton-arc", CALLS_A, CALLS_A, {LIST: HASH_A, "legal_supports-devour.json": "absent"},
                        {LIST: HASH_A, "legal_supports-devour.json": "absent"})
    assert compare_calls.compare_pair("skeleton-arc", left, right) is True
    out = capsys.readouterr().out
    assert "IDENTICAL" in out
    assert "NOT COMPARABLE" not in out
    assert "(no saved-list record)" not in out
    assert f"saved lists left:  {LIST} {HASH_A[:16]}, legal_supports-devour.json absent" in out


# -- row 5: no sidecar on either side (and on one side) ------------------------------------

def test_no_sidecar_on_either_side_keeps_today_output_plus_one_line(tmp_path, capsys):
    left, right = _pair(tmp_path, "skeleton-arc", CALLS_A, CALLS_A, None, None)
    assert compare_calls.compare_pair("skeleton-arc", left, right) is True
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "== skeleton-arc: 2 calls vs 2 calls: IDENTICAL"
    assert out[1] == "   (no saved-list record)"
    assert len(out) == 2


def test_one_sided_sidecar_still_compares_the_calls(tmp_path, capsys):
    left, right = _pair(tmp_path, "skeleton-arc", CALLS_A, CALLS_B, {LIST: HASH_A}, None)
    assert compare_calls.compare_pair("skeleton-arc", left, right) is False
    out = capsys.readouterr().out
    assert "(no saved-list record)" in out
    assert "first difference at call 2" in out
    assert "NOT COMPARABLE" not in out


def test_transcript_without_calls_suffix_uses_its_stem(tmp_path):
    assert compare_calls.lists_path(tmp_path / "run.jsonl") == tmp_path / "run.lists.json"
    assert compare_calls.lists_path(tmp_path / "skeleton-arc.calls.jsonl") == tmp_path / "skeleton-arc.lists.json"


# -- row 6: legal_supports with the file present / absent (tmp cache, fake PoB) ------------

# every candidate reads back as linked only when it is in ACCEPT; the call list is what PoB is asked
ACCEPT = {"Added Chaos Damage", "Devour", "Multiple Projectiles"}  # candidates 0, 40, 90 of the 144 day-1 supports
PLANT = ["Faster Casting", "Added Fire Damage"]
ABSENT_LEGAL = ["Added Chaos Damage", "Devour", "Multiple Projectiles"]
ABSENT_CALL_COUNT = 145  # 144 candidate links, then the skeleton's own link back
ABSENT_CALL_SHA = "deae46aa5821e4fd0c8d4051cb5356a1972950e29c033973df525bb71775e4c2"  # sha256 of json.dumps(calls), unchanged code


class _FakePob:
    def __init__(self):
        self.calls: list[list[str]] = []
        self._last = list(LINK)

    def set_skills(self, *, main_link, **_kw):
        self._last = list(main_link)
        self.calls.append(list(main_link))

    def read_state(self):
        linked = [{"name": n} for n in self._last[1:] if n in ACCEPT]
        return {"skills_state": {"socket_groups": [{"active_skill_entries": [{"name": self._last[0], "support_links": linked}]}]}}

    def stats(self, keys):
        return {k: 0 for k in keys} | {"CombinedDPS": 1}


def _generator(pob):
    g = gen.SkeletonGenerator.__new__(gen.SkeletonGenerator)
    g.pob = pob
    g.rails = Rails.load()
    g.objective = Objective(maximize="CombinedDPS")
    g.log = lambda _m: None
    g.picks = []
    g.castability_context = None
    g.castability_metrics = CastabilityMetrics()
    return g


def _skeleton():
    return Skeleton(class_name="Templar", ascendancy="Hierophant", main_link=list(LINK))


@pytest.fixture
def cache_root(tmp_path, monkeypatch):
    # cache = CORPUS.parents[2].parent / "artifacts" / "cache": point CORPUS under tmp_path
    monkeypatch.setattr(gen, "CORPUS", tmp_path / "src" / "junkroan" / "pob" / "corpus_data")
    monkeypatch.setattr(gen, "LEGAL_SUPPORTS_CACHE_DIR", tmp_path / "artifacts" / "cache")  # #980: the cache folder is its own variable
    return tmp_path / "artifacts" / "cache"


def test_legal_supports_with_the_file_present_reads_it_and_records_its_hash(cache_root):
    cache_root.mkdir(parents=True)
    cache = cache_root / LIST
    key = gen.legal_supports_key(LINK[0], gen.legal_support_candidates(LINK[0], ()))  # #980: a saved list carries its key
    cache.write_text(json.dumps({"key": key, "legal": PLANT}), encoding="utf-8")
    pob = _FakePob()
    legal = _generator(pob).legal_supports(_skeleton())
    assert legal == PLANT
    assert pob.calls == [], "a saved list read from the cache makes no PoB call"
    assert gen.SAVED_LISTS == {LIST: hashlib.sha256(cache.read_bytes()).hexdigest()}


def test_legal_supports_with_the_file_absent_runs_pob_writes_it_and_records_absent(cache_root):
    pob = _FakePob()
    g = _generator(pob)
    legal = g.legal_supports(_skeleton())
    assert legal == ABSENT_LEGAL
    assert len(pob.calls) == ABSENT_CALL_COUNT
    assert hashlib.sha256(json.dumps(pob.calls).encode("utf-8")).hexdigest() == ABSENT_CALL_SHA
    assert pob.calls[0] == ["Arc", "Added Chaos Damage"]
    assert pob.calls[-1] == LINK, "the skeleton's own link comes back last"
    assert (cache_root / LIST).is_file(), "the cold path still writes the list"
    assert gen.SAVED_LISTS == {LIST: "absent"}


def test_the_first_look_wins_across_a_second_call(cache_root):
    g = _generator(_FakePob())
    g.legal_supports(_skeleton())  # cold: records "absent", then writes the file
    g.legal_supports(_skeleton())  # warm now: reads the file, must not overwrite the start-of-run record
    assert gen.SAVED_LISTS == {LIST: "absent"}


def test_a_forbidden_support_does_not_consult_the_saved_list(cache_root):
    sk = _skeleton()
    sk.forbid_supports = ["Empower"]
    _generator(_FakePob()).legal_supports(sk)
    assert gen.SAVED_LISTS == {}


def test_write_saved_lists_writes_the_record_as_json(tmp_path):
    gen.SAVED_LISTS[LIST] = HASH_A
    gen.SAVED_LISTS["legal_supports-devour.json"] = "absent"
    target = tmp_path / "new" / "run.lists.json"
    gen.write_saved_lists(target)
    assert json.loads(target.read_text(encoding="utf-8")) == {LIST: HASH_A, "legal_supports-devour.json": "absent"}


# -- benchmark: the record is written at the end of each build, the dict reset at its start ---

def test_run_one_resets_the_record_and_writes_the_sidecar(tmp_path, monkeypatch):
    import benchmark

    seen = {}

    def fake_armed_build(slug, **_kw):
        seen["at_start"] = dict(gen.SAVED_LISTS)
        gen.SAVED_LISTS[LIST] = "absent"
        return {"ok": True}

    monkeypatch.setattr(benchmark, "armed_build", fake_armed_build)
    monkeypatch.setattr(benchmark, "provenance", lambda: {})
    gen.SAVED_LISTS["legal_supports-stale.json"] = HASH_B  # a leftover of an earlier build in this process
    benchmark.run_one("stormbrand", log_path=str(tmp_path / "logs" / "stormbrand-s4.log"), seed=4, gear_mode="loot",
                      record_calls=str(tmp_path / "calls"))
    assert seen["at_start"] == {}
    assert json.loads((tmp_path / "calls" / "stormbrand-s4.lists.json").read_text(encoding="utf-8")) == {LIST: "absent"}


def test_run_one_without_record_calls_writes_no_sidecar(tmp_path, monkeypatch):
    import benchmark

    monkeypatch.setattr(benchmark, "armed_build", lambda slug, **_kw: {"ok": True})
    monkeypatch.setattr(benchmark, "provenance", lambda: {})
    benchmark.run_one("stormbrand", log_path=str(tmp_path / "logs" / "stormbrand-s4.log"), seed=4, gear_mode="loot")
    assert not any(tmp_path.rglob("*.lists.json"))
