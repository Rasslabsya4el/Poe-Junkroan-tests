"""#434 unit 8: the trace classes of the jewel step. No PoB: a fake probe and a fake XML."""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from pathlib import Path

import pytest

from junkroan.optimizer.jewel_step import SocketOption, run_jewel_step
from junkroan.optimizer.jewel_trace import TracingJewelProbe, count_generated, jewel_classes
from junkroan.optimizer.trace import TRACE
from junkroan.optimizer.trace_output import trace_output_from_xml


@dataclass(frozen=True)
class Cand:
    base: str
    mod_id: str
    lines: tuple[str, ...]
    template_lines: tuple[str, ...] = ()

    @property
    def id(self) -> str:
        return " / ".join(self.lines)


PLAIN = Cand("Crimson Jewel", "m1", ("10% increased Damage",))
HYBRID = Cand("Cobalt Jewel", "m2", ("5% increased Spell Damage", "+10 to Intelligence"))
CANDS = [PLAIN, HYBRID, Cand("Viridian Jewel", "m3", ("+20 to Dexterity",))]


class FakeProbe:
    def __init__(self) -> None:
        self.jewel: Cand | None = None
        self.puts = 0

    def score(self) -> float:
        return {None: 0.0, PLAIN: 5.0, HYBRID: 3.0}.get(self.jewel, 1.0)

    def snapshot(self):
        return self.jewel

    def restore(self, snap) -> None:
        self.jewel = snap

    def sockets(self):
        return [SocketOption(node_id=7, path=(7,), cost=0)]

    def allocate(self, nodes) -> None:
        pass

    def put_jewel(self, socket_id, candidate) -> None:
        self.puts += 1
        self.jewel = candidate

    def remove_jewel(self, socket_id) -> None:
        self.jewel = None

    def removable_leaves(self):
        return []

    def remove(self, node_id) -> None:
        pass

    def points_over(self) -> int:
        return 0


@pytest.fixture(autouse=True)
def _fresh_trace():
    TRACE.reset()
    yield
    TRACE.reset()


def test_classes_of_plain_and_hybrid_are_both_one_mod():
    assert jewel_classes(PLAIN) == ["jewel-base:Crimson Jewel", "jewel-mods:1"]
    assert jewel_classes(HYBRID) == ["jewel-base:Cobalt Jewel", "jewel-mods:1"]


def test_run_through_the_tracing_probe_counts_generated_and_evaluated():
    inner = FakeProbe()
    with TRACE.move("jewel"):
        count_generated(CANDS)
        run_jewel_step(TracingJewelProbe(inner), CANDS, count_max=1)
    moves = TRACE.considered()["jewel"]
    assert inner.puts > 0
    assert moves["jewel-mods:1"] == {"generated": 3, "evaluated": inner.puts}
    assert moves["jewel-base:Crimson Jewel"]["generated"] == 1
    assert moves["jewel-base:Crimson Jewel"]["evaluated"] > 0
    for forbidden in ("jewel-mods:2+", "jewel-corrupted", "jewel-base:other"):
        assert moves[forbidden] == {"generated": 0, "evaluated": 0}


XML = """<PathOfBuilding>
<Tree activeSpec="1"><Spec nodes="1,2,3"><Sockets><Socket nodeId="2" itemId="1"/><Socket nodeId="99" itemId="2"/><Socket nodeId="3" itemId="0"/></Sockets></Spec></Tree>
<Items>
<Item id="1">
	Rarity: RARE
	Doom Eye
	Crimson Jewel
	Implicits: 0
	10% increased Damage
</Item>
<Item id="2">
	Rarity: RARE
	Doom Eye
	Cobalt Jewel
	Implicits: 0
	5% increased Spell Damage
	+10 to Intelligence
</Item>
</Items></PathOfBuilding>"""


def test_output_counts_of_socketed_jewels():
    counts = trace_output_from_xml(XML, jewel_candidates=CANDS)
    assert counts["jewels:2"] == 1
    assert counts["jewel-base:Crimson Jewel"] == 1 and counts["jewel-base:Cobalt Jewel"] == 1
    assert counts["jewel-mods:1"] == 2  # the hybrid's two lines are one mod
    assert counts["jewel-socket:unallocated"] == 1


def test_replay_move_jewel_is_legal():
    spec = importlib.util.spec_from_file_location("replay_bench_t", Path(__file__).resolve().parents[1] / "scripts" / "replay_bench.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.validate_move("jewel") == "jewel"
