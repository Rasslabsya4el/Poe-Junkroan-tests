"""#865 unit 3: the spare-point reader's formatter and arguments (no PoB)."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import benchmark  # noqa: E402
import check_spare_865  # noqa: E402


def test_format_line_exact():
    line = check_spare_865.format_line({"slug": "fireball", "extra_points": 8, "spent": 120, "available": 123, "unspent": 3,
                                        "value": 12345.6789, "violation": 0.0123456789})
    assert line == "fireball ExtraPoints 8 spent/available 120/123 unspent 3 value 12345.679 violation 0.012346"


def test_help_parses(capsys):
    with pytest.raises(SystemExit) as e:
        check_spare_865.main(["--help"])
    assert e.value.code == 0
    assert "--loop-seconds" in capsys.readouterr().out


def test_default_slugs_are_smoke_six():
    args = check_spare_865.build_parser().parse_args([])
    assert args.slugs == benchmark.SETS["smoke"]
    assert len(args.slugs) == 6
    assert args.loop_seconds == 60.0
