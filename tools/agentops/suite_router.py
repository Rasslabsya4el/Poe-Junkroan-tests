"""This installation's merge-suite router (#685): the suite runs on the laptop when it has more room.

``merge._run_merge_suite`` calls ``route`` for a suite the budget sized; ``None`` = run it on the PC as
before. A laptop suite is only a candidate list: its FAILED / ERROR ids and collection-error files are
re-run on the PC through ``merge._recheck_failed``. Every merge helper is looked up on the ``merge``
module at call time.
"""

from __future__ import annotations

import os
from pathlib import Path

from . import merge as m
from . import suite_host
from .suite_candidates import parse_candidates, too_many_message


def route_enabled() -> bool:
    """Settings key ``merge_suite_laptop`` (default false) and env ``JUNKROAN_NO_LAPTOP_SUITE`` unset."""
    if os.environ.get("JUNKROAN_NO_LAPTOP_SUITE"):
        return False
    try:
        from .core_settings import load as load_settings
        return bool(load_settings().get("merge_suite_laptop", False))
    except Exception:
        return False


def pc_readings() -> dict:
    """The PC's readings the way ``scripts/machine_load.py --suite-workers`` takes them."""
    import machine_load  # scripts/ is on sys.path (suite_host)
    from junkroan.pob import slot_budget
    try:
        free_ram: float | None = slot_budget.available_ram_gb()
    except Exception:
        free_ram = None
    cpu, pob = machine_load.cpu_shares()  # #715: the daemon's PoB workers count as free cores for the suite
    return {"logical_cores": machine_load.cpu_count() or os.cpu_count() or 1,
            "cpu_percent": cpu, "pob_cpu_percent": pob, "free_ram_gb": free_ram,
            "full_run_cpu_percent": machine_load.last_full_run_cpu}  # #744: same shares as machine_load's probe


def _host_line_first(head_line: str, host_line: str) -> str:
    """The host line goes BEFORE the ``workers k:`` line, which must stay the last line: the #687 restart
    watcher reads the last line of the head."""
    lines = head_line.splitlines()
    return "\n".join([*lines[:-1], host_line, lines[-1]]) if lines else host_line


def route(run_cmd: str, suite_cmd: str, workers: int, head_line: str, suite_dir: Path,
          run_env: dict[str, str] | None, output_path: Path) -> "m.SuiteRun | None":
    if not route_enabled():
        return None

    def pc_run(head: str) -> "m.SuiteRun":
        ok, out = m._run_suite(run_cmd, suite_dir, run_env, output_path, head)
        return m.SuiteRun(ok, out, workers, "pc")

    try:
        laptop, why = suite_host.read_laptop()
        choice = suite_host.choose_suite_host(pc_readings(), laptop, laptop_failure=why,
                                              **suite_host.caps_from_config())
    except Exception as exc:  # noqa: BLE001 -- the choice never blocks a merge
        return pc_run(_host_line_first(
            head_line, f"host pc: host choice failed: {m._first_line(str(exc)) or type(exc).__name__}"))
    if choice.host != "laptop":
        return pc_run(_host_line_first(head_line, choice.line))

    def full_pc(why_line: str) -> "m.SuiteRun":
        with open(output_path, "a", encoding="utf-8") as fh:
            fh.write(why_line + "\n")
        ok, out = m._run_suite(run_cmd, suite_dir, run_env, output_path, head_line, append=True,
                               restart=m._default_restart(suite_dir, head_line, False))
        return m.SuiteRun(ok, out, workers, "pc")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(choice.line + "\n", encoding="utf-8")
    laptop_out = output_path.with_name(output_path.name + ".laptop")
    import suite_on_host
    try:
        sha = m._git(suite_dir, "rev-parse", "HEAD").stdout.strip()
        rc = suite_on_host.run_suite("laptop", sha, choice.laptop_workers, laptop_out)
    except suite_on_host.HostBusy as exc:
        return full_pc(f"host pc: laptop busy ({exc})")
    except Exception as exc:  # noqa: BLE001 -- a transport failure is never a red result
        return full_pc(f"laptop unreachable ({m._first_line(str(exc)) or type(exc).__name__}), full suite on the PC")
    text = laptop_out.read_text(encoding="utf-8", errors="replace") if laptop_out.exists() else ""
    with open(output_path, "a", encoding="utf-8") as fh:
        fh.write(text)
    n = choice.laptop_workers or 0
    skipped = suite_host.skipped_note(text)
    if rc == 0:
        return m.SuiteRun(True, text, n, "laptop", skipped_note=skipped)
    if rc == 75:
        return full_pc("laptop unreachable (rc 75), full suite on the PC")
    cand = parse_candidates(text)
    if cand.count == 0:
        return full_pc(f"laptop suite red (rc {rc}) with no test ids, full suite on the PC")
    if cand.too_many:
        return full_pc(f"{too_many_message(cand)}, full suite on the PC")
    targets = cand.targets()
    still, recheck_out = m._recheck_failed(suite_cmd, targets, suite_dir, run_env, output_path)
    if still:
        return m.SuiteRun(False, recheck_out, n, "laptop", True, targets, still, " (laptop)", skipped)
    return m.SuiteRun(True, text, n, "laptop", True, targets, [], " (laptop)", skipped)
