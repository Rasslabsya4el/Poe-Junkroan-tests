"""`PobSession.read_state` is cached until a call that may change the build (7.1h, exact speed-up):
a full state read is ~0.9 s, the tree optimizer asked for it on every greedy step and
`derive_config` four times per derivation. The proxy invalidates by default: only the calls listed
as read-only keep the cache, so an adapter call added later is safe before it is classified."""

from junkroan.pob.session import PobSession, _StateCacheAdapter


class _Inner:
    def __init__(self) -> None:
        self.reads = 0
        self.version = 0

    def read_state(self, _handle):
        self.reads += 1
        return {"tree_state": {"user_allocated_node_ids": [1, 2], "version": self.version}}

    def read_stats(self, _handle, _request):
        return {"stats": {}}

    def mutate_tree_nodes(self, _handle, _request):
        self.version += 1
        return {}

    def trial_stats(self, _handle, request):
        return {"outcomes": []}

    def something_new(self, _handle):
        self.version += 1


def _session(inner: _Inner) -> PobSession:
    s = PobSession.__new__(PobSession)
    s._state_cache = None
    s._handle = object()
    s._adapter = _StateCacheAdapter(inner, s._drop_state_cache)
    return s


def test_reads_between_mutations_cost_one_read_and_each_caller_gets_its_own_copy() -> None:
    inner = _Inner(); s = _session(inner)
    first = s.read_state(); first["tree_state"]["user_allocated_node_ids"].append(99)  # a caller's edit
    assert s.read_state()["tree_state"]["user_allocated_node_ids"] == [1, 2]
    s._adapter.read_stats(s._handle, {})  # a read-only call keeps the cache
    s._adapter.trial_stats(s._handle, {"mode": "fast", "trials": []})  # so does a what-if trial
    assert s.read_state()["tree_state"]["version"] == 0 and inner.reads == 1


def test_a_mutation_a_full_trial_or_an_unlisted_call_drops_the_cache() -> None:
    inner = _Inner(); s = _session(inner)
    s.read_state()
    s._adapter.mutate_tree_nodes(s._handle, {"add": [3]})
    assert s.read_state()["tree_state"]["version"] == 1 and inner.reads == 2
    s._adapter.trial_stats(s._handle, {"mode": "full", "trials": []})  # really allocates and restores
    s.read_state(); assert inner.reads == 3
    s._adapter.something_new(s._handle)  # not classified: treated as a mutation
    assert s.read_state()["tree_state"]["version"] == 2 and inner.reads == 4
