"""#1166: a weekly core run finished on the laptop reaches the PC's gate folders.

The PC-only pass beside ``row_sync_pass``. A laptop ``artifacts/benchmark/<name>`` folder whose name is a gate name
(``gates.GATE_DIR_RE``), absent on the PC, and finished (``finished_tag``: ``results.json``, and ``report.md`` not
``partial:``) is copied into ``<name>.partial`` on the PC and renamed to ``<name>``; then ``record_gate`` for ``pc``
AND ``laptop``. The laptop record is what keeps ``gate_sync_pass`` from copying the folder straight back.

The laptop folder is ``<laptop daemon checkout>\\artifacts\\benchmark\\<name>`` (``hosts.daemon_repo_path``): a laptop
job's snapshot ``artifacts`` is a junction to that checkout (``daemon.py`` gate_sync_pass docstring).

A link that is down is a quiet skip; a copy that fails is logged and retried on a later pass.
"""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol

from junkroan.runs import gates as gates_mod
from junkroan.runs import hosts as runs_hosts
from junkroan.runs import row_sync as row_sync_mod
from junkroan.runs.bounded import run_bounded
from junkroan.runs.finished_tag import _is_finished as folder_is_finished
from junkroan.runs.hosts import SKIPPED_SSH_STDERR, note_ssh_failure, ssh_key
from junkroan.runs.pass_guard import GUARD

#: The pass runs at most this often (the laptop listing is one ssh call); a finished folder is copied within one of these.
GATE_PULL_SECONDS = 300.0
#: One `scp -r` of a whole gate folder; past it the copy is killed and retried on a later pass.
GATE_PULL_COPY_SECONDS = 600.0
#: benchmark.py rewrites results.json and report.md after the last row and again at its end (`benchmark.py:1686-1687`,
#: the rows' own writes `:692`/`:714` come before): a marker read this soon after a write may not be the run's end.
GATE_PULL_SETTLE_SECONDS = 180.0

_LAST_RUN: dict[str, float] = {}  # artifacts root -> clock of the last pass that reached the laptop


def folder_settled(folder: Path, now: float | None = None) -> bool:
    """The Python mirror of ``SshGateTransport.is_finished``: finished (``finished_tag``'s rule), and neither
    ``results.json`` nor ``report.md`` written in the last ``GATE_PULL_SETTLE_SECONDS``."""

    if not folder_is_finished(folder):
        return False
    now = time.time() if now is None else now
    for rel in ("results.json", "report.md"):
        path = folder / rel
        if path.is_file() and now - path.stat().st_mtime < GATE_PULL_SETTLE_SECONDS:
            return False
    return True


class GateTransport(Protocol):
    """The laptop side. Every method raises on any failure (link down, rc != 0); the pass treats that as quiet."""

    def list_gates(self) -> list[str]:
        """The names of the laptop's ``artifacts/benchmark`` folders."""

    def is_finished(self, name: str) -> bool:
        """Whether the laptop's folder ``name`` holds the finished marker (``finished_tag``'s rule)."""

    def fetch(self, name: str, dest: Path) -> None:
        """Copy the laptop's folder ``name`` into the directory ``dest`` (absent before the call)."""


class SshGateTransport(row_sync_mod.SshTransport):
    """The real laptop: ``ssh`` for the listing and the finished check, one ``scp -r`` for the folder."""

    def _root(self) -> str:
        return "\\".join([str(runs_hosts.daemon_repo_path(self.cfg)), "artifacts", "benchmark"])

    def list_gates(self) -> list[str]:
        script = (f"$r='{self._root()}'; if (Test-Path -LiteralPath $r) {{ Get-ChildItem -LiteralPath $r "
                  "-Directory | ForEach-Object { $_.Name } }")
        return [line.strip() for line in self._ssh(script).splitlines() if line.strip()]

    def is_finished(self, name: str) -> bool:
        """Finished and settled on the laptop's own clock: the Python mirror is ``folder_settled``."""
        folder = f"{self._root()}\\{name}"
        script = ("$f='" + folder + "'; $ok = Test-Path -LiteralPath \"$f\\results.json\"; "
                  "if ($ok -and (Test-Path -LiteralPath \"$f\\report.md\")) { "
                  "if ((Get-Content -LiteralPath \"$f\\report.md\" -TotalCount 1) -like 'partial:*') { $ok = $false } }; "
                  "if ($ok) { $now = (Get-Date).ToUniversalTime(); "
                  "foreach ($n in 'results.json', 'report.md') { $p = \"$f\\$n\"; "
                  "if (Test-Path -LiteralPath $p) { $age = ($now - (Get-Item -LiteralPath $p).LastWriteTimeUtc).TotalSeconds; "
                  "if ($age -lt " + f"{GATE_PULL_SETTLE_SECONDS:g}" + ") { $ok = $false } } } }; "
                  "if ($ok) { 'yes' } else { 'no' }")
        return self._ssh(script).strip() == "yes"

    def fetch(self, name: str, dest: Path) -> None:
        if GUARD.down(ssh_key(self.cfg)):
            raise RuntimeError(SKIPPED_SSH_STDERR)
        remote = f"{self._root()}\\{name}".replace("\\", "/")
        argv = ["scp", "-r", "-q", "-o", "BatchMode=yes", f"{self.cfg['ssh']}:{remote}", str(dest)]
        try:
            res = run_bounded(argv, capture_output=True, text=True, timeout=GATE_PULL_COPY_SECONDS)
        except Exception as exc:
            note_ssh_failure(self.cfg, exc)
            raise
        if res.returncode != 0:
            raise RuntimeError(f"scp rc {res.returncode}")


def gate_pull(artifacts: Path, transport: GateTransport, *, gates_path: Path | None,
              log: Callable[[str], None]) -> list[str]:
    """One pass: copy every finished, settled laptop gate folder absent on the PC; the names copied.

    Idempotent: a folder already on the PC is a copy that landed (the rename is the last step of a copy), so a pass
    only records what is missing for it (a record that failed after the rename) and never copies it twice. A failure
    is logged and the next pass tries again; nothing is retried inside the pass."""

    bench = Path(artifacts) / "benchmark"
    pulled: list[str] = []
    for name in sorted(transport.list_gates()):
        if not gates_mod.GATE_DIR_RE.match(name):
            continue
        final = bench / name
        if final.exists():
            if not _recorded(name, gates_path) and transport.is_finished(name) and _record(name, gates_path, log):
                log(f"gate_pull: recorded {name} for the PC and the laptop")
            continue
        if not transport.is_finished(name):
            continue
        partial = bench / (name + ".partial")
        try:
            shutil.rmtree(partial, ignore_errors=True)  # a half copy of an earlier pass
            bench.mkdir(parents=True, exist_ok=True)
            transport.fetch(name, partial)
            os.replace(partial, final)
        except Exception as exc:
            shutil.rmtree(partial, ignore_errors=True)
            log(f"gate_pull: copy of {name} from the laptop failed ({exc!r}); retried on a later pass")
            continue
        if _record(name, gates_path, log):
            log(f"gate_pull: PC now holds {name} from the laptop")
            pulled.append(name)
    return pulled


def _recorded(name: str, gates_path: Path | None) -> bool:
    return name in gates_mod.gates_present("pc", gates_path) and name in gates_mod.gates_present("laptop", gates_path)


def _record(name: str, gates_path: Path | None, log: Callable[[str], None]) -> bool:
    """``record_gate`` for both hosts; a failure is logged and False, so the next pass records it."""
    try:
        gates_mod.record_gate("pc", name, gates_path)
        gates_mod.record_gate("laptop", name, gates_path)
    except Exception as exc:
        log(f"gate_pull: recording {name} failed ({exc!r}); the next pass records it")
        return False
    return True


def gate_pull_pass(daemon: Any) -> list[str]:
    """The daemon's tick step: PC only, only with an artifacts root, at most every ``GATE_PULL_SECONDS``.
    A lost link is a quiet skip. ``daemon._gate_pull_transport`` (a test's stub) replaces the ssh transport."""

    if daemon.host != "pc" or daemon._gate_artifacts is None or "laptop" in daemon._remote_fail_at:
        return []
    now = daemon.clock()
    key = str(daemon._gate_artifacts)
    last = _LAST_RUN.get(key)
    if last is not None and now - last < GATE_PULL_SECONDS:
        return []
    _LAST_RUN[key] = now
    try:
        config = daemon._hosts_config if daemon._hosts_config is not None else runs_hosts.load_hosts_config()
        cfg: Mapping[str, Any] | None = config.get("laptop")
        if not cfg or not cfg.get("ssh"):
            return []
        transport = getattr(daemon, "_gate_pull_transport", None) or SshGateTransport(cfg)
        return gate_pull(Path(daemon._gate_artifacts), transport, gates_path=daemon._gates_path, log=daemon.log)
    except Exception:
        return []                       # a lost link (listing failed): quiet, retried after the cadence
