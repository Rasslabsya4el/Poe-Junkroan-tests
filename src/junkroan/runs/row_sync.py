"""#753: rows the laptop finished ahead of the weekly core run travel to the PC's week folder.

The PC's week folder is the one that counts. Per pass (at most every :data:`ROW_SYNC_SECONDS`, link permitting):
the laptop's copy of the folder (``args.json`` and every row file) is brought up to date, then every finished row
there is copied to the PC's folder, only when its ``commit`` is the cut's and its ``loop_stop`` is ``converged``
(a search stopped by the clock depends on the machine's speed); anything else is refused with one log line and
stays in ``--missing``. A row file the PC already has is never overwritten. A link that is down is a quiet skip:
no log line, no anomaly, retried next pass.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol

from junkroan.runs.hosts import SKIPPED_SSH_STDERR, SSH_TIMEOUT_SECONDS, note_ssh_failure, ssh_key
from junkroan.runs.pass_guard import GUARD

ROW_SYNC_SECONDS = 300.0
#: #998: one ssh/scp call of a pass is bounded like every other ssh call (was 120 s); a hung link costs one timeout per pass.
_TIMEOUT = SSH_TIMEOUT_SECONDS


class Transport(Protocol):
    """The laptop side. Every method raises on any failure (link down, rc != 0); the pass treats that as quiet."""

    def list_rows(self, name: str) -> Mapping[str, Mapping[str, Any]]:
        """``{stem: {"commit", "loop_stop", "ok", "has_pob"}}`` of the laptop's ``<name>/rows/*.json``."""

    def fetch(self, name: str, stem: str, dest: Path, with_pob: bool) -> None:
        """Copy the laptop's ``rows/<stem>.json`` (and ``<stem>.pob.txt``) into the directory ``dest``."""

    def push(self, folder: Path, files: list[str]) -> None:
        """Copy ``files`` (paths relative to ``folder``) into the laptop's copy of ``folder``."""


class SshTransport:
    """The real laptop: ``ssh`` for listing, ``scp`` for files, under the laptop daemon's checkout."""

    def __init__(self, cfg: Mapping[str, Any]) -> None:
        self.cfg = cfg

    def _remote(self, name: str) -> str:
        from junkroan.runs import hosts as runs_hosts
        return "\\".join([str(runs_hosts.daemon_repo_path(self.cfg)), "artifacts", "benchmark", name])

    def _call(self, argv: list[str]) -> Any:
        """One ssh or scp call (#998): skipped with an error when this host already failed to answer in this pass;
        a timeout or an OS error marks the host down for the rest of the pass."""
        from junkroan.runs.bounded import run_bounded
        if GUARD.down(ssh_key(self.cfg)):
            raise RuntimeError(SKIPPED_SSH_STDERR)
        try:
            return run_bounded(argv, capture_output=True, text=True, timeout=_TIMEOUT)
        except Exception as exc:
            note_ssh_failure(self.cfg, exc)
            raise

    def _ssh(self, script: str) -> str:
        from junkroan.runs.ssh_transport import build_ssh_argv
        res = self._call(build_ssh_argv(self.cfg, script))
        if res.returncode != 0:
            raise RuntimeError(f"ssh rc {res.returncode}")
        return res.stdout

    def _scp(self, argv: list[str]) -> None:
        res = self._call(argv)
        if res.returncode != 0:
            raise RuntimeError(f"scp rc {res.returncode}")

    def list_rows(self, name: str) -> Mapping[str, Mapping[str, Any]]:
        folder = self._remote(name)
        script = (
            f"$d='{folder}\\rows'; $o=@{{}}; "
            "if (Test-Path -LiteralPath $d) { Get-ChildItem -LiteralPath $d -Filter *.json | ForEach-Object { try { "
            "$j = Get-Content -Raw -LiteralPath $_.FullName | ConvertFrom-Json; "
            f"$o[$_.BaseName] = @{{commit=$j.commit; loop_stop=$j.loop_stop; ok=$j.ok; "
            f"has_pob=(Test-Path -LiteralPath ('{folder}\\' + $_.BaseName + '.pob.txt'))}} }} catch {{}} }} }}; "
            "$o | ConvertTo-Json -Compress -Depth 4"
        )
        out = self._ssh(script).strip()
        data = json.loads(out) if out else {}
        return data if isinstance(data, dict) else {}

    def fetch(self, name: str, stem: str, dest: Path, with_pob: bool) -> None:
        remote = self._remote(name).replace("\\", "/")
        files = [f"rows/{stem}.json"] + ([f"{stem}.pob.txt"] if with_pob else [])
        for rel in files:
            target = dest / rel.rsplit("/", 1)[-1]
            self._scp(["scp", "-q", "-o", "BatchMode=yes", f"{self.cfg['ssh']}:{remote}/{rel}", str(target)])

    def push(self, folder: Path, files: list[str]) -> None:
        remote = self._remote(folder.name)
        self._ssh(f"New-Item -ItemType Directory -Force -Path '{remote}\\rows' | Out-Null")
        rem = remote.replace("\\", "/")
        for rel in files:
            self._scp(["scp", "-q", "-o", "BatchMode=yes", str(folder / rel), f"{self.cfg['ssh']}:{rem}/{rel}"])


def refusal(row: Mapping[str, Any], cut: str) -> str | None:
    """Why a finished laptop row is not taken, or None."""

    if row.get("commit") != cut:
        return f"commit {str(row.get('commit') or 'none')[:7]} is not the cut {cut[:7]}"
    if row.get("loop_stop") != "converged":
        return f"loop_stop is {row.get('loop_stop')!r}, not 'converged'"
    if row.get("ok") and not row.get("has_pob"):
        return "no .pob.txt next to the row"
    return None


class RowSync:
    def __init__(self, transport: Transport, log: Callable[[str], None], seconds: float = ROW_SYNC_SECONDS) -> None:
        self.transport = transport
        self.log = log
        self.seconds = seconds
        self._last: float | None = None
        self._logged: set[tuple[str, str]] = set()

    def run(self, folder: Path, now: float) -> int:
        """One pass over the PC's week ``folder``; the number of rows copied. Never raises."""

        if self._last is not None and now - self._last < self.seconds:
            return 0
        self._last = now
        try:
            cut = json.loads((folder / "args.json").read_text(encoding="utf-8")).get("commit")
            if not cut:
                return 0
            return self._pass(folder, cut)
        except Exception:
            return 0                    # link down or a half-written file: quiet, retried next pass

    def _pass(self, folder: Path, cut: str) -> int:
        name = folder.name
        theirs = dict(self.transport.list_rows(name))
        rows_dir = folder / "rows"
        mine = {p.stem for p in rows_dir.glob("*.json")} if rows_dir.is_dir() else set()
        self.transport.push(folder, ["args.json"] + [f"rows/{s}.json" for s in sorted(mine - set(theirs))])
        copied = 0
        for stem in sorted(set(theirs) - mine):
            row = theirs[stem]
            why = refusal(row, cut)
            if why is not None:
                if (stem, why) not in self._logged:
                    self._logged.add((stem, why))
                    self.log(f"row_sync: refused {stem}: {why}")
                continue
            copied += self._take(folder, name, stem, bool(row.get("ok")))
        return copied

    def _take(self, folder: Path, name: str, stem: str, with_pob: bool) -> int:
        rows_dir = folder / "rows"
        rows_dir.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=folder, prefix=".row_sync_") as tmp:
            stage = Path(tmp)
            self.transport.fetch(name, stem, stage, with_pob)
            target = rows_dir / f"{stem}.json"
            if target.exists():
                return 0                # the first finished row of a stem stays
            if with_pob:
                pob = folder / f"{stem}.pob.txt"
                if not pob.exists():
                    os.replace(stage / f"{stem}.pob.txt", pob)
            os.replace(stage / f"{stem}.json", target)   # the row file lands last: its presence means complete
        self.log(f"row_sync: took {stem} from the laptop")
        return 1
