import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "build_scaling_vectors", Path(__file__).resolve().parents[1] / "scripts" / "build_scaling_vectors.py"
)
mod = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(mod)


def test_enablers_keep_every_provider_in_order():
    providers = [{"source": f"unique:{i}", "family": "unique", "name": f"n{i}", "line": "l"} for i in range(120)]
    out = mod.enablers_for({"Life": providers}, "Life")
    assert len(out) == 120
    assert [p["source"] for p in out] == [f"unique:{i}" for i in range(120)]


def test_enablers_missing_stat_is_empty():
    assert mod.enablers_for({}, "Life") == []
