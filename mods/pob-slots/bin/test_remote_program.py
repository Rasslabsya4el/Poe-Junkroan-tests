"""The program the collector pipes to another machine (`collect.remote_program`): collector + add-on travel as text and
`main()` runs there with the ssh command line's arguments. A throw-away project with its own add-on stands for it."""
import json
import os
import subprocess
import sys
from pathlib import Path

BIN = Path(__file__).resolve().parent


def test_remote_program_runs_the_addon_mode_from_stdin(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "orchestration.json").write_text(json.dumps({"repo": "o/n", "monitor": {"addon": "add/x.py"}}), encoding="utf-8")
    (tmp_path / "add").mkdir()
    (tmp_path / "add" / "x.py").write_text("from collect import hd\nMODES = {'ping': lambda *a: {'got': list(a), 'hd': hd(125)}}\n",
                                           encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k != "MONITOR_ROOT"}
    make = subprocess.run([sys.executable, "-c", f"import sys; sys.path.insert(0, {str(BIN)!r}); import collect; "
                           "sys.stdout.write(collect.remote_program())"], cwd=tmp_path, env=env, capture_output=True,
                          text=True, encoding="utf-8", timeout=60)
    assert make.returncode == 0, make.stderr
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    run = subprocess.run([sys.executable, "-", "ping", "a", "_", "here"], input=make.stdout, cwd=elsewhere, env=env,
                         capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout) == {"got": ["a", "_", "here"], "hd": "2 min"}
