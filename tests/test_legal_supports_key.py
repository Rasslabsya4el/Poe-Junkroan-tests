"""A saved legal-supports list is valid only for the PoB commit, the skill and the candidate list it was built from (#980).
No PoB: a fake session counts `read_state` calls (one per candidate support tried); the cache dir is a tmp folder."""

import json

import pytest

from junkroan.search import generator as gen_mod
from junkroan.search.generator import SkeletonGenerator, legal_support_candidates, legal_supports_cache_path, legal_supports_key
from junkroan.search.skeleton import Skeleton
from tests.test_legal_supports_readback import LINK, _gen


@pytest.fixture(autouse=True)
def _tmp_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(gen_mod, "LEGAL_SUPPORTS_CACHE_DIR", tmp_path)


class _Counting:
    def __init__(self, pob):
        self._pob = pob
        self.reads = 0

    def read_state(self):
        self.reads += 1
        return self._pob.read_state()

    def __getattr__(self, name):
        return getattr(self._pob, name)


def _generator():
    g = _gen([100_000])
    g.pob = _Counting(g.pob)
    return g


def _skeleton(**kw):
    return Skeleton(class_name="Templar", ascendancy="Hierophant", main_link=list(LINK), **kw)


def _key():
    return legal_supports_key(LINK[0], legal_support_candidates(LINK[0], ()))


def test_the_cache_path_lives_in_the_overridable_dir(tmp_path) -> None:
    assert legal_supports_cache_path("Spark Totem") == tmp_path / "legal_supports-spark_totem.json"


def test_a_file_with_the_current_key_is_returned_without_pob() -> None:
    legal_supports_cache_path(LINK[0]).write_text(json.dumps({"key": _key(), "legal": ["Spell Echo", "Unleash"]}), encoding="utf-8")
    g = _generator()
    assert g.legal_supports(_skeleton()) == ["Spell Echo", "Unleash"]
    assert g.pob.reads == 0


@pytest.mark.parametrize("saved", [["Spell Echo"], {"key": "stale", "legal": ["Spell Echo"]}], ids=["old-plain-list", "other-key"])
def test_a_file_without_or_with_another_key_is_rebuilt(saved) -> None:
    path = legal_supports_cache_path(LINK[0])
    path.write_text(json.dumps(saved), encoding="utf-8")
    g = _generator()
    legal = g.legal_supports(_skeleton())
    assert g.pob.reads > 0 and legal != ["Spell Echo"]
    assert json.loads(path.read_text(encoding="utf-8")) == {"key": _key(), "legal": legal}
    reads = g.pob.reads
    assert g.legal_supports(_skeleton()) == legal and g.pob.reads == reads, "the second call reads the rebuilt file, 0 PoB calls"


def test_unreadable_json_is_rebuilt() -> None:
    path = legal_supports_cache_path(LINK[0])
    path.write_text("{not json", encoding="utf-8")
    g = _generator()
    legal = g.legal_supports(_skeleton())
    assert g.pob.reads > 0
    assert json.loads(path.read_text(encoding="utf-8"))["key"] == _key() and legal


def test_forbid_supports_reads_and_writes_no_file(tmp_path) -> None:
    path = legal_supports_cache_path(LINK[0])
    path.write_text(json.dumps({"key": _key(), "legal": ["Spell Echo"]}), encoding="utf-8")
    before = path.read_text(encoding="utf-8")
    g = _generator()
    legal = g.legal_supports(_skeleton(forbid_supports=["Empower"]))
    assert g.pob.reads > 0 and legal != ["Spell Echo"]
    assert path.read_text(encoding="utf-8") == before
    assert [p.name for p in tmp_path.iterdir()] == [path.name]


def test_the_key_follows_the_commit_the_skill_and_the_candidates(monkeypatch, tmp_path) -> None:
    base = legal_supports_key("Arc", ["A", "B"])
    assert legal_supports_key("Arc", ["B", "A"]) == base
    assert legal_supports_key("Arc", ["A"]) != base
    assert legal_supports_key("Fireball", ["A", "B"]) != base
    lock = tmp_path / "lock.json"
    lock.write_text(json.dumps({"pinned_commit": "other"}), encoding="utf-8")
    monkeypatch.setattr(gen_mod, "DEFAULT_SOURCE_LOCK_PATH", lock)
    assert legal_supports_key("Arc", ["A", "B"]) != base
