"""#877 rule 4: submit refuses a job whose script is not in the checkout at the pin (no PoB)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import runs  # noqa: E402
from junkroan.runs import pin_ref  # noqa: E402
from junkroan.runs.store import Store  # noqa: E402

HEAD = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()


def _submit(tmp_path: Path, *cmd: str, pin: str | None = HEAD) -> tuple[int, Path]:
    store_path = tmp_path / "jobs.jsonl"
    pin_args = ["--pin", pin] if pin else []
    rc = runs.main(["--store", str(store_path), "submit", "--issue", "1", "--host", "pc", "--priority", "P1",
                    *pin_args, "--", *cmd])
    return rc, store_path


def _jobs(store_path: Path) -> int:
    return len(Store(store_path).jobs()) if store_path.exists() else 0


def test_missing_script_at_pin_is_refused(tmp_path: Path, capsys, monkeypatch) -> None:
    monkeypatch.setenv("JUNKROAN_HOST", "pc")
    rc, sp = _submit(tmp_path, "python", "scripts/does_not_exist_877.py", "--x", "1")
    assert rc != 0
    err = capsys.readouterr().err
    assert "scripts/does_not_exist_877.py" in err and HEAD[:12] in err
    assert _jobs(sp) == 0


def test_missing_script_without_pin_is_refused_at_head(tmp_path: Path, capsys, monkeypatch) -> None:
    monkeypatch.setenv("JUNKROAN_HOST", "pc")
    rc, sp = _submit(tmp_path, "python scripts/does_not_exist_877.py --x 1", pin=None)
    assert rc != 0 and "does_not_exist_877.py" in capsys.readouterr().err and _jobs(sp) == 0


def test_existing_script_submits(tmp_path: Path, capsys, monkeypatch) -> None:
    monkeypatch.setenv("JUNKROAN_HOST", "pc")
    rc, sp = _submit(tmp_path, "python", "scripts/runs.py", "status")
    assert rc == 0 and _jobs(sp) == 1


def test_non_py_commands_are_not_refused(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("JUNKROAN_HOST", "pc")
    assert _submit(tmp_path, "echo", "hi")[0] == 0
    assert _submit(tmp_path, "python", "-c", "pass")[0] == 0
    assert _submit(tmp_path, "python", "-m", "pytest", "-q")[0] == 0  # third-party module: skipped


def test_unresolvable_pin_is_a_skip(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("JUNKROAN_HOST", "pc")
    assert _submit(tmp_path, "python", "scripts/does_not_exist_877.py", pin="deadbeef0000")[0] == 0


def test_forms() -> None:
    f = pin_ref.script_candidates
    assert f(["set", "X=1", "&&", "python.exe", "-u", "scripts/a.py"]) == (["scripts/a.py"], None)
    assert f(["python", "-m", "junkroan.cli"])[0][0] == "src/junkroan/cli.py"
    assert f(["python", "-c", "pass"]) is None and f(["bash", "x.sh"]) is None
    assert f(["python", "/abs/a.py"]) is None
