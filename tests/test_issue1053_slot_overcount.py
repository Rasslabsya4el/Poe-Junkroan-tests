"""#1053: the run queue never counts more slots than the host has, and charges a pool no wider than its builds.

Replay of the 15.10 01:45 state on capacity 10 (night): 083a (a ONE-build benchmark declared with 2 workers) holds 1
lock, 19d8 holds 1, 57b8 and df77 (`junkroan.py build`, declared 1, their pools widen through the lock semaphore
by themselves) hold 5 and 3. Before the fix the count was 2 + 1 + 5 + 3 = 11. Fake launcher, fake slots, fake RAM; no PoB.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import pytest  # noqa: E402

from junkroan.pob import slot_budget  # noqa: E402
from junkroan.runs import build_count  # noqa: E402

from test_runs_daemon import FakeLauncher, FakeSlots, make_daemon  # noqa: E402
from test_runs_daemon import _isolated_daemon_status  # noqa: E402,F401  (autouse fixture of that file)

BUDGET_10 = slot_budget.Budget(period="night", hours=(1, 8), total=10, others=5, min_free_ram_gb=0.0,
                               strict_reserve=False)
HOSTS_RAM = {"pc": {"ram_per_worker_gb": 1.0, "spike": {"window_s": 300}}}

ONE_BUILD = 'python scripts/benchmark.py spark --gear wishlist --seed 4 --seeds 1 --no-variants --force-keystone "Chaos Inoculation" --tag {tag} --workers {n}'
THREE_BUILDS = "python scripts/benchmark.py a b c --no-variants --tag {tag} --workers {n}"
BUILD = 'python scripts/junkroan.py build --skill "{skill}" --mode auto --ascendancy auto'


def _rig(tmp_path: Path, *, hosts=None):
    slots = FakeSlots()
    daemon, store, _ = make_daemon(tmp_path, launcher=FakeLauncher(), budget=BUDGET_10, host="pc", slots=slots,
                                   hosts_config=hosts if hosts is not None else {"pc": {}})
    logs: list[str] = []
    daemon.log = logs.append
    daemon._yield_root = tmp_path / "root"
    return daemon, store, slots, logs


def _hold(slots: FakeSlots, **held: int) -> None:
    slots.rows = []
    for job_id, count in held.items():
        slots.own(job_id, count)


def _total(daemon) -> int:
    return sum(daemon.job_slot_counts().values())


def _status(daemon) -> dict:
    daemon.write_status(interval=5)
    return json.loads(daemon.status_path.read_text(encoding="utf-8"))


# -- spec a/c: the replayed state ------------------------------------------------------------------

def test_replay_0145_one_build_job_declared_2_never_pushes_the_count_past_capacity(tmp_path: Path) -> None:
    daemon, store, slots, logs = _rig(tmp_path)
    spark = store.submit(host="pc", priority="P1", tag="spark", cmd=ONE_BUILD.format(tag="s", n=2), workers=2)
    cold = store.submit(host="pc", priority="P1", tag="cold", cmd=ONE_BUILD.format(tag="c", n=1), workers=1)
    brand = store.submit(host="pc", priority="P1", tag="brand", cmd=BUILD.format(skill="Armageddon Brand"))
    bond = store.submit(host="pc", priority="P1", tag="bond", cmd=BUILD.format(skill="Searing Bond"))
    assert daemon.tick().started == [spark.id, cold.id, brand.id, bond.id]

    steps = [{spark.id: 1, cold.id: 1},
             {spark.id: 1, cold.id: 1, brand.id: 3},
             {spark.id: 1, cold.id: 1, brand.id: 5},
             {spark.id: 1, cold.id: 1, brand.id: 5, bond.id: 2},
             {spark.id: 1, cold.id: 1, brand.id: 5, bond.id: 3}]  # the 01:45 state: 10 locks held
    for held in steps:
        _hold(slots, **held)
        assert _total(daemon) <= 10, (held, daemon.job_slot_counts())
    assert daemon.job_slot_counts() == {spark.id: 1, cold.id: 1, brand.id: 5, bond.id: 3}
    assert _status(daemon)["slots_in_use"] == 10
    assert daemon.room(BUDGET_10) == 0

    # the Contagion job of #1046 asks for 1: it says 10/10 (it said 11/10), not a slot nobody can use
    contagion = store.submit(host="pc", priority="P1", tag="contagion", cmd=BUILD.format(skill="Contagion"))
    assert daemon.tick().started == []
    assert store.get(contagion.id).state == "queued"
    assert any("used 10/10, need 1" in line for line in logs), logs[-3:]


def test_adopted_after_a_restart_the_count_is_the_same(tmp_path: Path) -> None:
    daemon, store, slots, _ = _rig(tmp_path)
    spark = store.submit(host="pc", priority="P1", tag="spark", cmd=ONE_BUILD.format(tag="s", n=2), workers=2)
    brand = store.submit(host="pc", priority="P1", tag="brand", cmd=BUILD.format(skill="Armageddon Brand"))
    daemon.tick()
    _hold(slots, **{spark.id: 1, brand.id: 5})
    before = daemon.job_slot_counts()
    daemon._active.clear()  # a new daemon process: it adopts the running jobs from the store
    assert daemon.recover() == []
    assert daemon.job_slot_counts() == before == {spark.id: 1, brand.id: 5}


def test_a_multi_build_job_still_owes_its_declared_slot_to_every_admission_path(tmp_path: Path) -> None:
    """083a with 3 builds, declared 2, holding 1: nothing is admitted or grown into the slot it still owes."""

    daemon, store, slots, _ = _rig(tmp_path, hosts=HOSTS_RAM)
    free = {"gb": 6.0}
    daemon._ram_reader = lambda: free["gb"]
    t = {"now": 1_000_000.0}
    daemon.clock = lambda: t["now"]
    multi = store.submit(host="pc", priority="P1", tag="multi", cmd=THREE_BUILDS.format(tag="m", n=2), workers=2)
    cold = store.submit(host="pc", priority="P1", tag="cold", cmd=ONE_BUILD.format(tag="c", n=1), workers=1)
    brand = store.submit(host="pc", priority="P1", tag="brand", cmd=BUILD.format(skill="Armageddon Brand"))
    ram = store.submit(host="pc", priority="P1", tag="ram", workers=4,
                       cmd="python scripts/benchmark.py a b c d --no-variants --tag r --workers 4")
    assert daemon.tick().started == [multi.id, cold.id, brand.id, ram.id]
    assert daemon._active[ram.id].ram_give > 0          # started at the RAM bound, the rest withheld
    t["now"] += 600
    free["gb"] = 20.0
    _hold(slots, **{multi.id: 1, cold.id: 1, brand.id: 5})
    assert daemon.room(BUDGET_10) == 10 - (2 + 1 + 5 + daemon._active[ram.id].workers)
    daemon.owner_pass()                                  # _ram_grow: no free room, so no growth
    assert _total(daemon) <= 10
    assert daemon.job_slot_counts()[multi.id] == 2       # still charged its declared 2
    daemon.launcher.finish(daemon._active[brand.id].pid, 0)  # 57b8 ends: room opens, the RAM yield falls to 0
    daemon.tick()
    _hold(slots, **{multi.id: 1, cold.id: 1})
    daemon.owner_pass()
    assert daemon._active[ram.id].ram_give == 0
    assert daemon.job_slot_counts() == {multi.id: 2, cold.id: 1, ram.id: 4}
    assert _total(daemon) <= 10


def test_an_auto_job_gets_what_is_free_beside_the_slot_a_job_still_owes(tmp_path: Path) -> None:
    daemon, store, slots, _ = _rig(tmp_path)
    multi = store.submit(host="pc", priority="P1", tag="multi", cmd=THREE_BUILDS.format(tag="m", n=2), workers=2)
    brand = store.submit(host="pc", priority="P1", tag="brand", cmd=BUILD.format(skill="Armageddon Brand"))
    daemon.tick()
    _hold(slots, **{multi.id: 1, brand.id: 5})
    auto = store.submit(host="pc", priority="P1", tag="auto", workers_auto=True,
                        cmd="python scripts/benchmark.py a b c d e f g h --no-variants --tag x --workers auto")
    assert daemon.tick().started == [auto.id]
    assert store.get(auto.id).workers == 3               # 10 - (multi's 2 = 1 held + 1 owed, brand's 5 held): never the owed slot
    assert _total(daemon) <= 10


# -- spec b: min(declared, builds) ----------------------------------------------------------------------

def test_b_one_build_declared_2_is_charged_1_and_a_wider_build_list_is_unchanged(tmp_path: Path) -> None:
    daemon, store, slots, _ = _rig(tmp_path)
    one = store.submit(host="pc", priority="P1", tag="one", cmd=ONE_BUILD.format(tag="o", n=2), workers=2)
    three = store.submit(host="pc", priority="P1", tag="three", cmd=THREE_BUILDS.format(tag="t", n=2), workers=2)
    unknown = store.submit(host="pc", priority="P1", tag="unk", workers=2,
                           cmd="python scripts/benchmark.py a --tag u --workers 2")  # variants: builds not derivable
    assert daemon.tick().started == [one.id, three.id, unknown.id]
    assert daemon.job_slot_counts() == {one.id: 1, three.id: 2, unknown.id: 2}
    assert daemon.used_workers() == 5


def test_b_the_queued_need_is_the_charge_too(tmp_path: Path) -> None:
    """A 1-build job declared 2 fits one free slot (it would have waited for two)."""

    daemon, store, slots, _ = _rig(tmp_path)
    filler = store.submit(host="pc", priority="P1", tag="f", cmd="python scripts/benchmark.py a b --tag f --workers 9",
                          workers=9)
    one = store.submit(host="pc", priority="P1", tag="one", cmd=ONE_BUILD.format(tag="o", n=2), workers=2)
    assert daemon.tick().started == [filler.id, one.id]   # 9 + 1 <= 10; at 2 it would not fit


def test_b_an_auto_job_over_one_build_resolves_to_1(tmp_path: Path) -> None:
    daemon, store, slots, _ = _rig(tmp_path)
    auto = store.submit(host="pc", priority="P1", tag="auto", workers_auto=True,
                        cmd="python scripts/benchmark.py spark --no-variants --tag x --workers auto")
    assert daemon.tick().started == [auto.id]
    assert store.get(auto.id).workers == 1               # room was 10


@pytest.mark.parametrize("cmd, expected", [
    (ONE_BUILD.format(tag="x", n=2), 1),
    ("python scripts/benchmark.py a b --seeds 2 --no-variants", 4),
    ("python scripts/benchmark.py a b --construction-only", 2),
    ("python scripts/benchmark.py a --seed=7 --seeds=3 --force-keystone Foo --force-keystone Bar", 3),
    ("python scripts/benchmark.py --no-variants --tag t", None),                 # no slugs: every reference
    ("python scripts/benchmark.py --set core14 --no-variants", None),
    ("python scripts/benchmark.py a b", None),                                    # keystone variants add builds
    ("python scripts/benchmark.py a --no-variants --resume some_run", None),
    ("python scripts/benchmark.py a --no-variants --rereport t", None),
    ("python scripts/benchmark.py a --no-variants --unknown-flag 3", None),
    ("python scripts/replay_bench.py a --no-variants", None),
    ("python scripts/junkroan.py build --skill X", None),
    ("", None),
])
def test_builds_in_command(cmd: str, expected: int | None) -> None:
    assert build_count.builds_in_command(cmd) == expected


def test_builds_in_command_reads_argv_like_the_string() -> None:
    argv = ["python", "scripts/benchmark.py", "spark", "--no-variants", "--force-keystone", "Chaos Inoculation",
            "--workers", "2"]
    assert build_count.builds_in_command("ignored", argv) == 1


def test_the_flag_lists_are_every_option_of_the_benchmark_parser() -> None:
    source = (ROOT / "scripts" / "benchmark.py").read_text(encoding="utf-8")
    parser_flags = set(re.findall(r'add_argument\("(--[\w-]+)"', source))
    # BooleanOptionalAction adds its `--no-` twin
    twins = {f"--no-{m}" for m in re.findall(r'add_argument\("--([\w-]+)"[^\n]*BooleanOptionalAction', source)}
    listed = set(build_count.VALUE_FLAGS) | set(build_count.SWITCH_FLAGS)
    assert (parser_flags | twins) <= listed, sorted((parser_flags | twins) - listed)
