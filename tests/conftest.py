"""Shared pytest skip helpers.

The PoB-*runtime* tests already skip when `var/cache/pob` is missing (grep
`skipif` in this directory). Tests that call into `junkroan.pob.skill_facts`
or `junkroan.pob.skill_requirements` directly -- no `PobSession`, just PoB's
vendored Lua skill data (`vendor/pob/source/src/Data/Skills/*.lua`) -- had no
equivalent gate: `vendor/pob/source` is gitignored and reaches the main
checkout only through a symlink/junction a worktree never gets (CLAUDE.md
"Worktrees hold junctions"), so those tests FAILED instead of skipping there
(issue #43). `needs_skill_source` is the one shared marker for that case.

`pytest_collection_modifyitems` below is the `JUNKROAN_NO_POB` switch (#114):
every one of those existing `skipif` markers already carries a reason string
that says why it would skip ("PoB runtime not present", "PoB skill data not
present", "PoB skill source data not present"...); when the switch is on, this
hook turns every one of them into an unconditional skip, regardless of what a
given checkout actually has on disk (the main checkout's `var/cache/pob` and
`vendor/pob/source` junctions included). One place, no per-file edits.

Issue #198: every test that opens a `PobSession` or the headless PoB runtime also carries the
registered `pob` mark (`pytest.ini`), next to its existing `skipif` (module-level `pytestmark` or
per test, whichever the file already used). Under the switch, this hook force-skips a `pob`-marked
item directly by the mark too -- a second path next to the reason-string one above, so a `pob` test
whose own `skipif` reason does not happen to match `_POB_REASON_MARKERS` still cannot run.
`guard_pob_launch` (`junkroan.pob.no_pob_switch`) is the last line of defence: it sits at the one
place that starts the real PoB worker process and raises -- failing the test outright, and counting
the attempt -- if something slips past both skips.

`pytest_runtest_setup` below is the issue #94 fix: dozens of test files add `scripts/` to
`sys.path` (to `import search` / `import benchmark` / ... as top-level modules) and some of
them never re-insert `src` after it, unlike the documented "scripts first, then src in front
of it" pattern in `scripts/benchmark.py:39`. Once one of those files is collected, `scripts/`
sits ahead of `src` in `sys.path` for the rest of the session (pytest collects every module
before running any test body), and `scripts/junkroan.py` -- a plain module, not a package --
shadows the `junkroan` package for any spawn-mode child started afterwards, whose bootstrap
inherits that `sys.path` verbatim and dies importing it (issue #94, TEST RUNS:
`ModuleNotFoundError: No module named 'junkroan.cli'; 'junkroan' is not a package`), which then
hangs a `multiprocessing.Pool` forever (a dead worker never returns a result). Re-pinning `src`
to `sys.path[0]` before every test body runs guarantees any process that test starts sees the
package, regardless of what earlier test modules left behind.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from junkroan.pob.no_pob_switch import ENV_VAR, launch_attempts, pob_disabled

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = str(PROJECT_ROOT / "src")

# vendor/pob/source/src/Data/Skills is what junkroan.pob.skill_facts.SKILL_DATA_DIRS[0]
# points at, and junkroan.pob.game_corpus.DEFAULT_SOURCE_ROOT (vendor/pob/source) is its
# parent's parent's parent: both come from the same clone, so one presence check covers both.
SKILL_SOURCE_DIR = PROJECT_ROOT / "vendor" / "pob" / "source" / "src" / "Data" / "Skills"

needs_skill_source = pytest.mark.skipif(
    not SKILL_SOURCE_DIR.is_dir(),
    reason=f"PoB skill source data not present at {SKILL_SOURCE_DIR} (vendor/pob/source is gitignored; a worktree has no junction to it)",
)

def not_on_pc(host: str | None = None) -> bool:
    """True when JUNKROAN_HOST names a host other than the PC (the daemon / suite_on_host set it); unset = the PC."""

    value = os.environ.get("JUNKROAN_HOST") if host is None else host
    return bool(value) and value != "pc"


pc_only = pytest.mark.skipif(
    not_on_pc(),
    reason="needs the PC: the runs queue of this machine, gitignored PC result files, an interactive desktop or the `claude` CLI (JUNKROAN_HOST is not pc)",
)

# Substrings of the `reason=` every PoB-needing `skipif` in this suite already carries (grep
# `skipif` across `tests/`): the pinned runtime ("PoB runtime not present" / "pinned PoB runtime
# not present", both contain "PoB runtime"), PoB's Lua skill data via `skill_facts`/
# `skill_requirements` ("PoB skill data not present"), and the vendored skill *source* above
# ("PoB skill source data not present"). A reason matching none of these (an unrelated fixture,
# e.g. "archived benchmark build not present") is left alone.
_POB_REASON_MARKERS = ("PoB runtime", "PoB skill data", "PoB skill source data")


# #779: no test (nor a subprocess it starts) ever reads or writes the real ~/.claude/agentops/machine_mode.json.
# Import time: a path that is never created (nothing writes it: the per-test fixture below replaces it for every
# test), so a stray import-time reader sees `normal` and no directory is left behind. A test that wants its own
# dir sets AGENTOPS_MACHINE_DIR itself (monkeypatch) and wins.
import os as _os_779
import tempfile as _tempfile_779

_os_779.environ["AGENTOPS_MACHINE_DIR"] = _os_779.path.join(
    _tempfile_779.gettempdir(), f"agentops_machine_unused_{_os_779.getpid()}")


@pytest.fixture(autouse=True)
def _machine_mode_dir_per_test(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch):
    """Every test gets its own machine-mode dir (#779). One dir per session was not enough: `runs.py mode pc play`
    and `hosts.revert_expired_modes` write the machine mode, so a test of them left `play` in the dir of its xdist
    worker and every later test of that worker saw a held machine (the merge line's `_acquire` waited for ever in
    play; the dispatcher tests started nothing), 10 failed and the run stood at 99 %."""
    monkeypatch.setenv("AGENTOPS_MACHINE_DIR", str(tmp_path_factory.mktemp("machine")))


@pytest.fixture(autouse=True)
def _pass_guard_fresh_per_test():
    """Every test starts with a guard that was never begun (#1031). `pass_guard.GUARD` is one module global: a daemon
    test's `tick()` calls `GUARD.begin()`, and from then on the guard answers `down` for EVERY key once its 45 s pass
    budget is spent, so in a worker of a 15-19 min full run `pin_ref._git` skipped every network git call ("origin did
    not answer this pass") and the laptop pin / snapshot tests failed; alone, in a fresh process, they passed."""
    from junkroan.runs import pass_guard

    def fresh() -> None:
        guard = pass_guard.GUARD
        guard._down.clear()
        guard._steps.clear()
        guard._begun = False
        guard._started = guard._clock()

    fresh()
    yield
    fresh()


@pytest.fixture(autouse=True)
def _hold_never_touches_the_real_root(monkeypatch: pytest.MonkeyPatch):
    """A keeper pass on this checkout's own root is a no-op in every test (#779): `var/` is linked to the main
    checkout's, so a dispatcher-tick test calling `hold.keeper_pass(mode, ROOT)` rewrote the real
    `var/agentops/hold_record.json` (and, in `normal`, would resume what the live keeper suspended). A test of the
    hold itself passes its own tmp root and runs the real pass."""
    from pathlib import Path

    from tools.agentops import hold

    real, root_of_repo = hold.keeper_pass, Path(hold.ROOT).resolve()

    def guarded(mode, root=hold.ROOT, **kwargs):
        if Path(root).resolve() == root_of_repo:
            return {"suspended": [], "resumed": []}
        return real(mode, root, **kwargs)

    monkeypatch.setattr(hold, "keeper_pass", guarded)


@pytest.fixture(autouse=True, scope="session")
def _agentops_run_log_in_tmp(tmp_path_factory: pytest.TempPathFactory):
    """No test writes the real `artifacts/runs/agentops.jsonl` (issue #256).

    `tools.agentops.metering.record_run` falls back to `DEFAULT_LOG` when no `log_path` is
    given, and `run_research` / the GPT worker call it that way, so three research tests had
    added 289 fixture rows to the real log (shared by every worktree through the junction).
    The default is pointed at a temporary file for the whole session.
    """
    log = tmp_path_factory.mktemp("agentops_log") / "agentops.jsonl"
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("tools.agentops.metering.DEFAULT_LOG", log)
        yield log


@pytest.fixture(autouse=True)
def _busy_samples_in_tmp(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch):
    """#898: no test reads or writes the live `var/pc_busy_cores.jsonl`: the dispatcher's and the full
    run's load gate would answer from the real PC's load, and the daemon's tick would write into it.
    An empty file in a tmp dir answers `no reading` = go."""
    from junkroan.pob import slot_budget
    path = tmp_path_factory.mktemp("busy_samples") / "pc_busy_cores.jsonl"
    monkeypatch.setattr(slot_budget, "busy_samples_path", lambda: path)


@pytest.fixture(autouse=True)
def _merge_share_never_scans_the_pc(monkeypatch: pytest.MonkeyPatch):
    """#1118: no test reads the live process table or the merge locks. The daemon takes its merge reader from
    `merge_share.merge_cores` when it is built, so the stand-in answers "no merge" (0.0) for every daemon;
    a test that wants another reading sets `daemon.merge_reader` itself."""
    from junkroan.runs import merge_share
    monkeypatch.setattr(merge_share, "merge_cores", lambda prev, now_s, **kwargs: (0.0, {}))


@pytest.fixture(autouse=True)
def _suite_reservations_in_tmp(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch):
    """#397: no test claims workers in the live `var/suite_workers.json` (the merge suite's and the full
    run's shared reservation); every test has its own file."""
    monkeypatch.setenv("AGENTOPS_SUITE_RESERVATIONS", str(tmp_path_factory.mktemp("suite_res") / "suite_workers.json"))


@pytest.fixture(autouse=True)
def _no_laptop_suite(monkeypatch: pytest.MonkeyPatch):
    """No test reads the live laptop (#457, #685): the merge's laptop suite route is off for every
    test; a test of that route deletes the variable and injects fakes."""
    monkeypatch.setenv("JUNKROAN_NO_LAPTOP_SUITE", "1")


@pytest.fixture(autouse=True)
def _agentops_merge_paths_in_tmp(tmp_path_factory: pytest.TempPathFactory,
                                 monkeypatch: pytest.MonkeyPatch):
    """No test writes the live `var/agentops/` (merge.log, merge_suite/, results/) (issue #417).

    #399 only patched the module constants in two of the six merge test files, and a constant
    patch never reaches a child process (`--detach` runner, `python -m tools.agentops merge`).
    Here every one of those paths is redirected for each test twice: the module constants
    (in-process) and the env overrides merge.py / detach.py read at call time (children
    inherit the environment). One dir per test: the suite-output pruning of one test must not
    delete another test's output file.
    """
    from tools.agentops import detach, merge
    base = tmp_path_factory.mktemp("agentops_var")
    for key, val in ((merge.ENV_MERGE_LOG, base / "merge.log"),
                     (merge.ENV_SUITE_OUTPUT_DIR, base / "merge_suite"),
                     (detach.ENV_RESULTS_DIR, base / "results"),
                     (detach.ENV_MERGE_LOG, base / "detach_merge.log")):
        monkeypatch.setenv(key, str(val))
    monkeypatch.setattr(merge, "MERGE_LOG_PATH", base / "merge.log")
    monkeypatch.setattr(merge, "SUITE_OUTPUT_DIR", base / "merge_suite")
    monkeypatch.setattr(detach, "RESULTS_DIR", base / "results")
    monkeypatch.setattr(detach, "MERGE_LOG", base / "detach_merge.log")
    yield base


def _skipif_reasons(item: pytest.Item) -> list[str]:
    reasons: list[str] = []
    for marker in item.iter_markers(name="skipif"):
        reason = marker.kwargs.get("reason")
        if reason is None and len(marker.args) > 1:
            reason = marker.args[1]
        if isinstance(reason, str):
            reasons.append(reason)
    return reasons


def _mark_red_on_main(items: list[pytest.Item]) -> None:
    """#1205: the tests red on main before the move to GitHub tests, listed in `tests/red_on_main.txt`.

    A line `xfail <nodeid>` marks that test `xfail(strict=False)`; a line `skip <path or nodeid>` skips it (a hang).
    Removing this function and the file is the whole undo; the listed tests are fixed under their own issue."""

    path = Path(__file__).parent / "red_on_main.txt"
    if not path.is_file():
        return
    xfail_ids: set[str] = set()
    skip_ids: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        kind, _, target = line.partition(" ")
        (skip_ids if kind == "skip" else xfail_ids).add(target.strip())
    for item in items:
        nodeid = item.nodeid.replace("\\", "/")
        file_id = nodeid.split("::", 1)[0]
        if nodeid in skip_ids or file_id in skip_ids:
            item.add_marker(pytest.mark.skip(reason="red on main before #1205, see #1206"))
        elif nodeid in xfail_ids:
            item.add_marker(pytest.mark.xfail(reason="red on main before #1205, see #1206", strict=False))


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Under `JUNKROAN_NO_POB`, force-skip every test whose own `skipif` reason says it needs
    PoB (see `_POB_REASON_MARKERS`) -- instead of relying on each one's own file-presence check,
    which would only skip on a checkout that happens to lack `var/cache/pob` / `vendor/pob/source`.
    Also force-skip every test carrying the `pob` mark directly (issue #198): the reason-string
    check above and the mark check here are independent, so a `pob` test whose `skipif` reason
    happens not to match `_POB_REASON_MARKERS` is still caught."""

    _mark_red_on_main(items)
    if not pob_disabled():
        return
    skip = pytest.mark.skip(reason=f"{ENV_VAR} is set (issue #114): PoB-needing tests are skipped")
    for item in items:
        needs_pob_reason = any(
            marker in reason for reason in _skipif_reasons(item) for marker in _POB_REASON_MARKERS
        )
        if needs_pob_reason or item.get_closest_marker("pob") is not None:
            item.add_marker(skip)


def pytest_terminal_summary(terminalreporter, exitstatus, config) -> None:
    for finding in _GUARD_FINDINGS:
        terminalreporter.write_line(f"#875 REAL QUEUE FILE WRITTEN BY TEST {finding}", red=True)
    """Issue #198: under `JUNKROAN_NO_POB`, the count of PoB launches refused in this session."""

    if pob_disabled():
        terminalreporter.write_line(f"{ENV_VAR}: PoB launches attempted in this session: {launch_attempts()}")


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Issue #198: a suite run under `JUNKROAN_NO_POB` that tried to start PoB even once fails,
    even if the test that tried swallowed the guard's error."""

    if pob_disabled() and launch_attempts() > 0 and session.exitstatus == 0:
        session.exitstatus = 1
    if _GUARD_FINDINGS and session.exitstatus == 0:
        session.exitstatus = 1  # #875: a test wrote a made-up job id into a real queue file


def pytest_runtest_setup(item: pytest.Item) -> None:
    """Issue #94: pin `src` back to `sys.path[0]` before every test body, undoing whatever a
    test file collected earlier left `sys.path` looking like (see the module docstring)."""

    while SRC_DIR in sys.path:
        sys.path.remove(SRC_DIR)
    sys.path.insert(0, SRC_DIR)


@pytest.fixture(autouse=True)
def _no_area_rule(monkeypatch):
    """#319: the dispatcher one-area rule (`areas` in config/orchestration.json) is off in every
    test unless that test turns it on by patching `tools.agentops.dispatch._load_settings`."""

    try:
        import tools.agentops.dispatch as dispatch
    except ImportError:
        return
    real = dispatch._load_settings
    monkeypatch.setattr(dispatch, "_load_settings", lambda: {**real(), "areas": []})
    try:
        import tools.agentops.cloud_lane as cloud_lane
    except ImportError:
        return
    real_lane = cloud_lane._settings
    monkeypatch.setattr(cloud_lane, "_settings", lambda: {**real_lane(), "areas": []})


@pytest.fixture(autouse=True)
def _no_real_untracked_scan(monkeypatch):
    """#365: a daemon tick scans this machine's real processes and PoB slots for untracked trees;
    in a test that would raise an anomaly about the owner's own PoB. Tests inject their own."""

    try:
        from junkroan.runs import untracked
    except ImportError:
        return
    monkeypatch.setattr(untracked, "collect_local", lambda store: [])


@pytest.fixture(autouse=True)
def _modes_file_in_tmp(monkeypatch, tmp_path):
    """#376: the mode store resolves to the MAIN checkout's var/modes.json (`hosts.modes_path`) even
    from a worktree; a test that reaches `record_mode` / `apply_timed_mode` (or starts `runs.py mode`
    as a subprocess, which inherits this env) must never write the owner's real file."""

    monkeypatch.setenv("JUNKROAN_MODES_FILE", str(tmp_path / "modes.json"))


@pytest.fixture(autouse=True)
def _reservations_file_in_tmp(monkeypatch, tmp_path):
    """#411: `slot_budget.reservations_file()` falls back to the MAIN checkout's live
    var/reservations.json; with `strict_reserve` on, a live `runs reserve` is added to `others` and
    changed slot-budget limits under test (and `machine_load.py` subprocesses inherit this env). Every
    test reads an empty reservations file of its own unless it writes one or passes a path."""

    monkeypatch.setenv("JUNKROAN_POB_RESERVATIONS", str(tmp_path / "no_live_reservations.json"))


@pytest.fixture(autouse=True)
def _runs_events_in_tmp(monkeypatch, tmp_path):
    """#138: `hosts.events_path()` resolves to the MAIN checkout's artifacts/runs/events.jsonl even from a
    worktree, and that feed drives the anomaly detector that starts keymaster sessions; a test that
    appends an event (`echo x`, `wrong-host`, `keymaster_start`) must never write the live one."""

    monkeypatch.setenv("JUNKROAN_RUNS_EVENTS", str(tmp_path / "events.jsonl"))


@pytest.fixture(autouse=True)
def _run_queue_runs_in_tmp(monkeypatch, tmp_path_factory):
    """#875: `run_queue.log()` appends to `RUNS / "queue.log"`, the real `artifacts/runs/queue.log`
    shared with the live daemon; the #756 snapshot-failure tests added `snapshot failed for
    20261011-1855-run1: boom` / `... job-b: unknown commit ...` lines to it. `run_queue.RUNS` is
    a tmp dir for every test; a test that wants its own patches it again."""

    try:
        import run_queue
    except ImportError:
        return
    runs = tmp_path_factory.mktemp("run_queue_runs")  # not under tmp_path: a test lists its own tmp_path
    monkeypatch.setattr(run_queue, "RUNS", runs)


# -- the owner's home is never written (#1176) ----------------------------------------------------

_REAL_HOME = Path.home()  # read at conftest import, before any test redirects the home
# #1205: a checkout that lives under the real home (a CI runner's workspace) is not "the real home's state":
# its own constants (config/, src/ data files) must stay where they are, or every test reads a path that does not exist.
_CHECKOUT = Path(__file__).resolve().parents[1]
_REPO_ROOT = Path(__file__).resolve().parents[1]
_OURS: dict[str, bool] = {}  # module name -> is a module of this repo (src/, tools/, scripts/)


def _is_ours(module) -> bool:
    if module.__name__ not in _OURS:
        file = getattr(module, "__file__", None)
        real = os.path.normcase(os.path.realpath(file)) if file else ""
        repo = os.path.normcase(str(_REPO_ROOT))
        _OURS[module.__name__] = any(real.startswith(os.path.join(repo, top) + os.sep)
                                     for top in ("src", "tools", "scripts"))
    return _OURS[module.__name__]


def _under_home(value, home: Path, base: Path, memo: dict | None = None):
    """`value` (a path a module constant or a default captured at import) moved to the same relative path under the
    test's `home`, or returned unchanged when it is no home path. A path under pytest's basetemp is some earlier test's
    own home (a module first imported inside that test): it is re-based onto this test's `home`, never used as it is.
    Constants that the guard moved are restored by monkeypatch after each test, so the next test starts again from
    the real values (test_h1/test_h2 prove no leak between two tests).

    `memo` is one redirect's `id(original) -> (original, moved)`: a name copied from another module is one object, and
    it must stay one object after the move (`monitor.DEFAULT_PROJECTS_DIR is monitor_agents.DEFAULT_PROJECTS_DIR`),
    so the same original is moved once. The original is kept in the entry, so its id cannot be reused meanwhile."""
    from pathlib import PurePath

    if memo is not None and id(value) in memo:
        return memo[id(value)][1]
    moved = _moved_under_home(value, home, base, memo)
    if memo is not None:
        memo[id(value)] = (value, moved)
    return moved


def _moved_under_home(value, home: Path, base: Path, memo: dict | None):
    from pathlib import PurePath

    if type(value) in (list, tuple):  # a constant that holds several paths (scripts/brain_misread_extract.py DEFAULT_FOLDERS)
        moved_items = [_under_home(item, home, base, memo) for item in value]
        if all(new is old for new, old in zip(moved_items, value)):
            return value
        return type(value)(moved_items)
    if not isinstance(value, (PurePath, str)):
        return value
    if isinstance(value, str) and ":" not in value[:3] and not value.startswith(("/", "\\")):
        return value  # cheap cut: no drive letter and no root, so not an absolute path
    path = Path(value)
    if not path.is_absolute() or path.is_relative_to(home):
        return value
    if path.is_relative_to(base):
        rel = path.relative_to(base).parts  # test_name0 / home / ... for an earlier test's home
        if len(rel) < 2 or rel[1] != "home":
            return value
        moved = home.joinpath(*rel[2:])
    elif path.is_relative_to(_REAL_HOME) and not path.is_relative_to(_CHECKOUT):
        moved = home / path.relative_to(_REAL_HOME)
    else:
        return value
    return str(moved) if isinstance(value, str) else moved


def _functions_of(module):
    import inspect

    for value in list(vars(module).values()):
        if inspect.isclass(value) and value.__module__ == module.__name__:
            members = [getattr(m, "__func__", m) for m in vars(value).values()]
        elif inspect.isfunction(value) and value.__module__ == module.__name__:
            members = [value]
        else:
            continue
        yield from (m for m in members if inspect.isfunction(m) and m.__module__ == module.__name__)


def _redirect_home(monkeypatch: pytest.MonkeyPatch, home: Path, base: Path) -> None:
    """Every module of this repo that is loaded now: each module attribute, and each function's positional and
    keyword defaults, that holds a path under the real home is moved under the test's `home` (restored after the test).
    One memo for the whole walk: one original path object becomes one moved object in every module."""
    memo: dict = {}
    for module in list(sys.modules.values()):
        if module is None or not hasattr(module, "__name__") or not _is_ours(module):
            continue
        for attr, value in list(vars(module).items()):
            if not attr.startswith("__"):
                moved = _under_home(value, home, base, memo)
                if moved is not value:
                    monkeypatch.setattr(module, attr, moved)
        for fn in _functions_of(module):
            if fn.__defaults__:
                moved_pos = tuple(_under_home(v, home, base, memo) for v in fn.__defaults__)
                if any(a is not b for a, b in zip(moved_pos, fn.__defaults__)):
                    monkeypatch.setattr(fn, "__defaults__", moved_pos)
            if fn.__kwdefaults__:
                moved_kw = {k: _under_home(v, home, base, memo) for k, v in fn.__kwdefaults__.items()}
                if any(moved_kw[k] is not v for k, v in fn.__kwdefaults__.items()):
                    monkeypatch.setattr(fn, "__kwdefaults__", moved_kw)


@pytest.fixture(autouse=True)
def _home_is_tmp_per_test(tmp_path: Path, tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch):
    """#1176: no test writes the owner's real ~/.claude (settings.json, mods, commands, the plugin cache). Each test
    gets a home folder in a sibling folder of its tmp_path (`tmp_path_factory.mktemp`, never inside it: a test that
    lists its tmp_path sees only its own files): HOME and USERPROFILE point at it (on Windows `Path.home()` reads
    USERPROFILE), AGENTOPS_MODS_DIR sits in it, and every path under the real home that a loaded module of this repo
    holds (a module constant, a function default captured at import, a name copied from another module) is moved
    under it. This is general, not per name: a new constant or default is covered without a line here. A test that
    really needs a real value patches it itself (its own monkeypatch wins). Limit: a module first imported inside a
    test body is not in the walk; it binds the test's own home, since HOME already points there."""
    root = tmp_path_factory.mktemp("home")
    home = root / "home"
    (home / ".claude").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("AGENTOPS_MODS_DIR", str(home / ".claude" / "mods"))
    # `guard install` prints one extra line while ~/.claude.json lacks the accepted bypassPermissions disclaimer
    (home / ".claude.json").write_text('{"bypassPermissionsModeAccepted": true}', encoding="utf-8")
    # git reads its global config from the home the guard moved: a test identity of its own and the owner's default
    # branch name, so a commit a test makes never depends on the owner's ~/.gitconfig (no `-c user.name` in the tests)
    gitconfig = root / "gitconfig"
    gitconfig.write_text("[user]\n\tname = junkroan test\n\temail = junkroan-test@example.invalid\n"
                         "[init]\n\tdefaultBranch = main\n", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(gitconfig))
    _redirect_home(monkeypatch, home, tmp_path_factory.getbasetemp())


@pytest.fixture(autouse=True)
def _core_test_without_the_homes_full_run(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch):
    """#1176: the core's test_select_wire.py::test_53_map_run_is_the_core_subcommand_and_full_run_is_gone expects
    `agentops full-run` to be unknown (exit 2), as in a target without that module; this repo's own `.full_run`
    local module (config/orchestration.json `local_modules`) registers it. For that one test only, the registry
    lists no command named `full-run` (`registry.commands` is the list `main()` builds its parser from); every other
    test sees the home's full registry, and monkeypatch restores the list after the test."""
    if (request.module.__name__ != "test_select_wire"
            or request.node.name != "test_53_map_run_is_the_core_subcommand_and_full_run_is_gone"):
        return
    from tools.agentops.extensions import registry

    registry.load()  # the first load fills the list; load() is idempotent, so main() will not add the command again
    monkeypatch.setattr(registry, "commands", [c for c in registry.commands if c.name != "full-run"])


#: #1176: the marketplace a fake plugin install is filed under (the name a machine enables it by).
PLUGIN_MARKETPLACE = "claude-plugins-official"


def fill_plugin_cache(cache: Path, marketplace: str = PLUGIN_MARKETPLACE, version: str = "1.3.1") -> Path:
    """A fake plugin install under `cache`, in the layout `port.resolve_plugin` reads
    (`<cache>/<marketplace>/mattpocock-skills/<version>/skills/engineering/<name>/SKILL.md`), with one SKILL.md for
    every skill the core names (`port.named_pocock_skills`): no test needs the owner's installed plugin.
    Returns the marketplace's plugin folder. Shared by `plugin_home` below and tests/test_agentops_port.py."""
    from tools.agentops import port

    for name in port.named_pocock_skills():
        skill = cache / marketplace / port.PLUGIN_ID / version / "skills" / "engineering" / name / "SKILL.md"
        skill.parent.mkdir(parents=True, exist_ok=True)
        skill.write_text("# skill\n", encoding="utf-8")
    return cache / marketplace / port.PLUGIN_ID


@pytest.fixture
def plugin_home() -> Path:
    """#1176, opt-in (not autouse): the test's own home enables the plugin and holds a fake plugin cache. The guard
    above moves `DEFAULT_USER_SETTINGS_PATH` and `PLUGIN_CACHE_ROOT` under the per-test home, so a call that takes
    those defaults (`home seed`, `core update`) reads what is written here and never the owner's ~/.claude.
    Returns the settings path."""
    import json

    from tools.agentops import port

    settings = port.DEFAULT_USER_SETTINGS_PATH
    # not Path.home(): a file whose own autouse fixture repoints HOME (machine-home) would fail it; the real file is
    # compared, since pytest's basetemp itself sits under the real home
    assert settings != _REAL_HOME / ".claude" / "settings.json", "the guard must move the default user settings"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(json.dumps({"enabledPlugins": {f"{port.PLUGIN_ID}@{PLUGIN_MARKETPLACE}": True}}),
                        encoding="utf-8")
    plugin = fill_plugin_cache(port.PLUGIN_CACHE_ROOT)
    # the setup skill's templates (Pocock 1.3.1, the repo's own copies in tests/fixtures), where a home check reads them
    templates = plugin / "1.3.1" / "skills" / "engineering" / "setup-matt-pocock-skills"
    templates.mkdir(parents=True, exist_ok=True)
    fixtures = Path(__file__).resolve().parent / "fixtures" / "mattpocock_setup_1.3.1"
    for source in fixtures.iterdir():
        (templates / source.name).write_bytes(source.read_bytes())
    return settings


# -- the real queue files stay untouched (#875) ---------------------------------------------------

import json as _json
import re as _re

_REAL_JOB_ID = _re.compile(r"^j-\d{8}-\d{4}-[0-9a-f]{4}$")
_JOB_TOKEN = _re.compile(r"\bj-[\w-]+")
# the name a queue.log line is about: `snapshot NAME:`, `snapshot failed for NAME:`, `job NAME:`, `start NAME`, `end NAME:`
_LOG_NAME = _re.compile(r"^\S+ \S+ (?:snapshot failed for|snapshot|job|start|end|archive benchmark) ([^\s:]+)")
_GUARD_FINDINGS: list[str] = []


def _real_paths() -> dict[str, Path]:
    """The three real files, as production resolves them from the MAIN checkout. `JUNKROAN_GUARD_REAL_ROOT`
    stands in for that checkout (the test of the guard points it at a tmp tree; never the real files)."""
    import os

    override = os.environ.get("JUNKROAN_GUARD_REAL_ROOT")
    if override:
        root = Path(override)
    else:
        from junkroan.runs.store import MAIN_ROOT
        root = Path(MAIN_ROOT)
    return {"queue.log": root / "artifacts" / "runs" / "queue.log",
            "jobs.jsonl": root / "artifacts" / "runs" / "jobs.jsonl",
            "anomalies.json": root / "var" / "anomalies.json"}


def _read_lines(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []


def _store_job_ids(jobs_lines: list[str]) -> set[str]:
    ids: set[str] = set()
    for line in jobs_lines:
        try:
            job = _json.loads(line).get("job")
        except (ValueError, AttributeError):
            continue
        if job:
            ids.add(str(job))
    return ids


def _made_up_lines(before: dict[str, list[str]], after: dict[str, list[str]], runs_dir: Path) -> list[str]:
    """Lines the real files gained whose job id the suite made up. A line a real daemon wrote carries an id the
    real store, the real log (earlier lines) or a real run output file `<name>.out` already knows; a made-up id
    (`job-b`, a name `run1`) is known to none of them. Size and mtime play no part."""
    found: list[str] = []
    store_ids = _store_job_ids(after["jobs.jsonl"])
    old_log = "\n".join(before["queue.log"])
    for line in after["queue.log"][len(before["queue.log"]):]:
        m = _LOG_NAME.match(line)
        if not m:
            continue  # a line about no job (waiting for pid, queue empty): no made-up id
        name = m.group(1)
        if name in store_ids or name in old_log or (runs_dir / f"{name}.out").exists():
            continue
        found.append(f"queue.log: {line}")
    for line in after["jobs.jsonl"][len(before["jobs.jsonl"]):]:
        try:
            job = str(_json.loads(line).get("job") or "")
        except (ValueError, AttributeError):
            job = ""
        if job and not _REAL_JOB_ID.match(job):
            found.append(f"jobs.jsonl: {line[:160]}")
    seen = set(before["anomalies.json"])
    for line in after["anomalies.json"]:
        if line in seen:
            continue
        # a real job id: in the local store, or shaped like one (a remote host's job, `laptop:job_stuck:j-...`, and a
        # running job a daemon writes about are not in this checkout's jobs.jsonl)
        if any(i not in store_ids and not _REAL_JOB_ID.match(i) for i in _JOB_TOKEN.findall(line)):
            found.append(f"anomalies.json: {line.strip()[:160]}")
    return found


@pytest.fixture(autouse=True)
def _real_queue_files_untouched(request: pytest.FixtureRequest):
    """#875: after each test, the real `queue.log`, `jobs.jsonl` and `var/anomalies.json` are read again; lines
    that appeared with a job id the suite made up are recorded under this test's name and fail the session
    (`pytest_sessionfinish`). The tie is the made-up id, not size or mtime: a real daemon appending lines about
    real jobs during the run never trips it."""
    paths = _real_paths()
    before = {k: _read_lines(v) for k, v in paths.items()}
    yield
    after = {k: _read_lines(v) for k, v in paths.items()}
    for finding in _made_up_lines(before, after, paths["queue.log"].parent):
        _GUARD_FINDINGS.append(f"{request.node.nodeid}: {finding}")


# -- no real ssh from a test (#451) ---------------------------------------------------------------

import os as _os
import subprocess as _subprocess

_SSH_REFUSAL = "real host call from a test: fake run_on_host"
_REAL_RUN = _subprocess.run
_REAL_POPEN = _subprocess.Popen


def _is_ssh_call(args) -> bool:
    """True when `args` (a Popen/run argv or a shell string) starts an ssh client."""

    if isinstance(args, (str, bytes, _os.PathLike)):
        text = _os.fsdecode(args).strip()
        first = text.split(None, 1)[0] if text else ""
    else:
        try:
            first = _os.fsdecode(args[0]) if args else ""
        except (TypeError, IndexError):
            return False
    return _os.path.basename(first.replace("\\", "/")).lower() in ("ssh", "ssh.exe")


class _SshGuardState:
    """`real_run` is the function beneath the guard (a test may swap it for a recorder);
    `passed` records every argv the guard let through."""

    def __init__(self) -> None:
        self.real_run = _REAL_RUN
        self.passed: list = []


class _GuardedPopen(_REAL_POPEN):
    def __init__(self, args, *a, **kw):
        if _is_ssh_call(args):
            raise RuntimeError(_SSH_REFUSAL)
        super().__init__(args, *a, **kw)


@pytest.fixture(autouse=True)
def ssh_guard(monkeypatch: pytest.MonkeyPatch) -> _SshGuardState:
    """No test reaches a real host over ssh (#451): on 2026-10-01 `runs.py mode laptop off` with no
    fake switched the real laptop to `off`. `subprocess.run` / `Popen` raise before spawning when the
    argv is ssh; a test's own later monkeypatch (of `run_on_host`, an injected transport, or
    `subprocess.run`) replaces the guard and still works."""

    state = _SshGuardState()

    def guarded_run(*popenargs, **kwargs):
        args = popenargs[0] if popenargs else kwargs.get("args")
        if _is_ssh_call(args):
            raise RuntimeError(_SSH_REFUSAL)
        state.passed.append(args)
        return state.real_run(*popenargs, **kwargs)

    monkeypatch.setattr(_subprocess, "run", guarded_run)
    monkeypatch.setattr(_subprocess, "Popen", _GuardedPopen)
    return state


@pytest.fixture(autouse=True)
def no_remote_read_from_test_daemon(monkeypatch: pytest.MonkeyPatch) -> list:
    """#457: a runs `Daemon` built in a test with neither its own `hosts_config` nor a
    `remote_store_reader` would run `remote_handback_pass` over the LIVE config/hosts.json and read
    every other host (the laptop) over ssh; with the laptop up that returned real jobs and the test
    daemon tried to make their Run issues. Such a daemon now stops in `_read_remote` before any
    transport; a test passes `hosts_config=` or `remote_store_reader=` to exercise the pass.
    Returns the list of refused host reads."""

    refused: list = []
    try:
        from junkroan.runs import daemon as daemon_mod
    except ImportError:
        return refused
    real = daemon_mod.Daemon._read_remote

    def guarded(self, host_cfg, host):
        if getattr(self, "_hosts_config", None) is None and getattr(self, "_remote_store_reader", None) is None:
            refused.append(host)
            raise RuntimeError("remote read from a test daemon: pass your own hosts config")
        return real(self, host_cfg, host)

    monkeypatch.setattr(daemon_mod.Daemon, "_read_remote", guarded)
    return refused


@pytest.fixture(autouse=True)
def _no_pobbin_network_or_live_cache(request, monkeypatch, tmp_path_factory: pytest.TempPathFactory):
    """The suite never reaches pobb.in and never reads the live id cache (#572)."""
    from junkroan import pobbin

    def _refuse(code: str, *, timeout: float = 15.0) -> str:
        raise RuntimeError("network call refused in tests (#572)")

    # tests/test_pobbin.py exercises the real upload_code with urllib.request.urlopen faked (no network)
    if request.module.__name__ != "test_pobbin":
        monkeypatch.setattr(pobbin, "upload_code", _refuse)
    monkeypatch.setattr(pobbin, "DEFAULT_CACHE", tmp_path_factory.mktemp("pobbin") / "ids.json")


@pytest.fixture(autouse=True)
def _fresh_active_gem_records():
    """#577: `config_rules._active_gem_records` is an `lru_cache` over `hypothesis.active_gems()`.
    A test that patches `active_gems` (tests/test_construction_rig.py `_run_construction`, `{}`) and then
    reaches `build_text` fills that cache with the patched value, and every later test in the process read
    the empty corpus (test_picks_memo's brand-memo key stops seeing Zealotry). Cleared before each test."""

    try:
        from junkroan.optimizer import config_rules
    except ImportError:
        return
    config_rules._active_gem_records.cache_clear()


@pytest.fixture(autouse=True)
def _no_merge_test_selection(monkeypatch):
    """#690: `merge_select_tests` is true in config/orchestration.json; a test that lands a pytest-shaped
    suite through `run_merge` must neither select tests nor spawn a real `full-run`. A test of the
    selection turns it on by patching `tools.agentops.merge.resolve_select_tests`."""

    try:
        import tools.agentops.merge as merge
    except ImportError:
        return
    monkeypatch.setattr(merge, "resolve_select_tests", lambda: False)


@pytest.fixture(autouse=True)
def _no_real_claude_program(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch):
    """#759: a test that reaches the default launcher's real Claude program fails by name.

    The anomaly guard's default launcher finds the real `claude.exe` (`anomalies._find_claude_exe`);
    that call is replaced by one that records and raises with the running test's name. The guard's
    own thread swallows the raise, so the teardown fails the test from the record. A test that
    really needs the program carries the `real_claude` mark. Yields the record (a list of messages).
    """

    violations: list[str] = []
    if request.node.get_closest_marker("real_claude") is None:
        import os

        from junkroan.runs import anomalies

        def refuse():
            name = os.environ.get("PYTEST_CURRENT_TEST", request.node.nodeid)
            message = (f"the real Claude program was started by test {name}; "
                       "hand the guard a fake launcher or mark the test real_claude")
            violations.append(message)
            raise RuntimeError(message)

        monkeypatch.setattr(anomalies, "_find_claude_exe", refuse)
    yield violations
    if violations:
        pytest.fail(violations[0], pytrace=False)


@pytest.fixture(autouse=True)
def _boot_time_is_never_the_real_one(monkeypatch: pytest.MonkeyPatch):
    """No test reads the machine's real boot time (the home's #259 fixture, which the core does not ship).

    A dispatcher rig's fake session start is an old date; a machine booted after it makes
    `_restart_boot_time` call the end a `machine_restart`, so core tests failed here while they
    passed in the home. A test that injects `Dispatcher.boot_time` itself is unaffected.
    """

    try:
        import psutil
    except ImportError:
        return
    monkeypatch.setattr(psutil, "boot_time", lambda: 0.0)
