import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import rig_839  # noqa: E402


def test_parse_args():
    a = rig_839.parse_args([])
    assert (a.burners, a.burner_priority, a.both, a.samples, a.max_seconds) == (12, "below_normal", False, 2000, 120.0)
    a = rig_839.parse_args(["--burners", "3", "--burner-priority", "normal", "--both", "--max-seconds", "5"])
    assert (a.burners, a.burner_priority, a.both, a.max_seconds) == (3, "normal", True, 5.0)


def test_refuse_reason():
    for h in (8, 12, 23, 0):
        assert rig_839.refuse_reason("pc", h, 12)
    for h in (1, 4, 7):
        assert rig_839.refuse_reason("pc", h, 12) is None
    assert rig_839.refuse_reason("laptop", 12, 12) is None
    assert rig_839.refuse_reason("pc", 12, 1) is None


def test_percentile():
    v = list(range(1, 101))
    assert rig_839.percentile(v, 99) == 99
    assert rig_839.percentile(v, 50) == 50
    assert rig_839.percentile(v, 100) == 100
    assert rig_839.percentile([5.0], 99) == 5.0


def test_tiny_real_run():
    r = subprocess.run([sys.executable, str(Path(rig_839.__file__)), "--burners", "1", "--samples", "50",
                        "--max-seconds", "20"], capture_output=True, text=True, timeout=60,
                       creationflags=rig_839.NO_WINDOW)
    assert r.returncode == 0, r.stderr
    m = re.search(r"RIG839 burners=1 priority=below_normal p99_ms=([\d.]+) median_ms=[\d.]+ max_ms=[\d.]+", r.stdout)
    assert m, r.stdout
    float(m.group(1))
