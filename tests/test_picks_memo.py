"""The picks move asks PoB only for what can have changed (speed audit 2026-09-18, exact).

`Skeleton.brand_attach_extra` is the whole reason the re-judge of the picks reads the build state
back ~400 times per run: every support trial rewrote the skills surface and then paid a full
`read_state` export plus a `build_text` rebuild to count the same "additional Brand Attached to an
Enemy" lines again. The count is a function of the items, the passives and the gems that grant an
active skill, so it is remembered against `PobSession.build_epoch` and the active gems in play.

No PoB here: the fake session counts its state reads, exactly as the improvement-loop tests (tests/loop_fakes.py)
count the loop's calls.
"""

from __future__ import annotations

from junkroan.pob.session import PobSession, _StateCacheAdapter
from junkroan.search.skeleton import brand_attach_extra, derived_counts

from conftest import needs_skill_source

BRAND_LINE = "You can have an additional Brand Attached to an Enemy"


class _Pob:
    """A build whose only mod text is `lines`, read back the way the worker reports it."""

    def __init__(self, lines: list[str], *, stats: dict | None = None) -> None:
        self.lines = list(lines)
        self.build_epoch = 0
        self.reads = 0
        self._stats = stats or {}

    def read_state(self) -> dict:
        self.reads += 1
        return {
            "items_state": {"slots": {"Helmet": {"item": {"raw_item_text": "\n".join(self.lines)}}}},
            "tree_state": {"user_allocated_node_ids": [], "mastery_effect_ids": []},
            "skills_state": {"socket_groups": []},
        }

    def stats(self, keys) -> dict:
        return {k: self._stats.get(k) for k in keys}


def test_the_brand_count_is_read_once_while_only_supports_change() -> None:
    pob = _Pob([BRAND_LINE])
    links = [["Storm Brand", "Arcane Surge"], ["Wrath"]]
    first = brand_attach_extra(pob, ["Storm Brand", "Arcane Surge", "Wrath"], links)
    assert (first, pob.reads) == (1, 1)
    # every support the re-judge tries in the main link's second slot: a different gem set, the same
    # three surfaces behind the number, so the same answer without a second read
    for support in ("Concentrated Effect", "Increased Critical Strikes", "Swiftbrand", "Controlled Destruction"):
        trial = [["Storm Brand", support], ["Wrath"]]
        assert brand_attach_extra(pob, ["Storm Brand", "Arcane Surge", "Wrath"], trial) == first
    assert pob.reads == 1


def test_a_changed_active_gem_or_a_changed_build_is_read_again() -> None:
    pob = _Pob([BRAND_LINE])
    links = [["Storm Brand", "Arcane Surge"], ["Wrath"]]
    assert brand_attach_extra(pob, ["Storm Brand", "Wrath"], links) == 1
    assert pob.reads == 1
    # a utility group swapped to another active gem can carry the line itself: judged again
    assert brand_attach_extra(pob, ["Storm Brand", "Wrath"], [["Storm Brand", "Arcane Surge"], ["Zealotry"]]) == 1
    assert pob.reads == 2
    # and so is the same gem set once the tree or the gear moved
    pob.lines = [BRAND_LINE, BRAND_LINE]
    pob.build_epoch += 1
    assert brand_attach_extra(pob, ["Storm Brand", "Wrath"], links) == 2
    assert pob.reads == 3


@needs_skill_source
def test_derived_counts_caps_the_brand_count_with_the_memoized_extra() -> None:
    pob = _Pob([BRAND_LINE], stats={"ActiveBrandLimit": 5})
    links = [["Storm Brand", "Arcane Surge"]]
    assert derived_counts(pob, ["Storm Brand", "Arcane Surge"], links)["Storm Brand"] == 2  # attach base 1 + the line
    assert pob.reads == 1
    assert derived_counts(pob, ["Storm Brand", "Arcane Surge"], [["Storm Brand", "Swiftbrand"]])["Storm Brand"] == 2
    assert pob.reads == 1


def test_a_session_without_the_counter_is_never_memoized() -> None:
    pob = _Pob([BRAND_LINE])
    del pob.build_epoch  # a test double or an older session object
    assert brand_attach_extra(pob, ["Storm Brand"], [["Storm Brand"]]) == 1
    assert brand_attach_extra(pob, ["Storm Brand"], [["Storm Brand"]]) == 1
    assert pob.reads == 2


# --- the epoch itself -------------------------------------------------------------------


class _Inner:
    def __init__(self) -> None:
        self.reads = 0

    def read_state(self, _handle):
        self.reads += 1
        return {"tree_state": {}}

    def apply_skill_state(self, _handle, _payload):
        return None

    def apply_config_state(self, _handle, _payload):
        return None

    def apply_item_state(self, _handle, _payload):
        return None

    def mutate_tree_nodes(self, _handle, _request):
        return {}

    def something_new(self, _handle):
        return None


def _session(inner: _Inner) -> PobSession:
    s = PobSession.__new__(PobSession)
    s._state_cache = None
    s._handle = object()
    s._adapter = _StateCacheAdapter(inner, s._drop_state_cache)
    return s


def test_a_skills_or_config_write_keeps_the_build_epoch_and_still_drops_the_state_cache() -> None:
    inner = _Inner(); s = _session(inner)
    s.read_state()
    s._adapter.apply_skill_state(s._handle, {})
    s._adapter.apply_config_state(s._handle, {})
    assert s.build_epoch == 0  # neither can touch an item or a passive: the worker writes their own tab
    s.read_state()
    assert inner.reads == 2  # the cache is dropped all the same


def test_everything_else_moves_the_build_epoch() -> None:
    inner = _Inner(); s = _session(inner)
    s._adapter.apply_item_state(s._handle, {})
    assert s.build_epoch == 1
    s._adapter.mutate_tree_nodes(s._handle, {})
    assert s.build_epoch == 2
    s._adapter.something_new(s._handle)  # not classified: treated as a change to everything
    assert s.build_epoch == 3


# --- the worker's gem-id memo ------------------------------------------------------------


def test_the_skills_writer_without_the_gem_id_memo_is_the_writer_minus_the_memo_lines() -> None:
    """The "before" side of scripts/picks_speed_proof.py is the code as it stood, line for line."""

    from junkroan.pob.headless_runtime_worker import (
        _APPLY_SKILLS_LUA,
        _APPLY_SKILLS_LUA_NO_GEM_ID_MEMO,
        _GEM_ID_MEMO_GROUP,
        _GEM_ID_MEMO_LOOKUP,
        _GEM_ID_MEMO_RECORD,
        _GEM_ID_MEMO_SETUP,
    )

    memo = (*_GEM_ID_MEMO_SETUP, *_GEM_ID_MEMO_GROUP, *_GEM_ID_MEMO_LOOKUP, *_GEM_ID_MEMO_RECORD)
    assert len(_APPLY_SKILLS_LUA) - len(_APPLY_SKILLS_LUA_NO_GEM_ID_MEMO) == len(memo)
    assert [line for line in _APPLY_SKILLS_LUA if line not in memo] == list(_APPLY_SKILLS_LUA_NO_GEM_ID_MEMO)
    # every memo line is dropped, and no line the writer needs shares its text with one
    assert not set(memo) & set(_APPLY_SKILLS_LUA_NO_GEM_ID_MEMO)
    assert 'gi.gemId = gem_ids[gi.nameSpec]' in "\n".join(_APPLY_SKILLS_LUA)
