"""#9: scripts/benchmark.py defaults to template gear; `wishlist` is its alias; `loot` stays loot."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import benchmark  # noqa: E402

real = benchmark.resolve_run_config


@pytest.fixture(autouse=True)
def _scratch_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(benchmark, "ROOT", tmp_path)


def _config(monkeypatch: pytest.MonkeyPatch, *gear: str) -> dict:
    """Parse the argv through main() and capture the config main() resolves, before any run starts."""

    captured: dict = {}


    def stop_after_resolving(args):
        captured["config"] = real(args)
        raise SystemExit(0)

    monkeypatch.setattr(benchmark, "resolve_run_config", stop_after_resolving)
    monkeypatch.setattr(sys, "argv", ["benchmark.py", "alpha", "--tag", "gear-default", *gear])
    with pytest.raises(SystemExit):
        benchmark.main()
    return captured["config"]


def test_template_is_the_default_and_wishlist_its_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    default = _config(monkeypatch)
    assert default == _config(monkeypatch, "--gear", "template")
    assert default == _config(monkeypatch, "--gear", "wishlist")
    assert default["gear"] == "wishlist"  # the pipeline's mode name, so rows compare with earlier template runs
    assert default["template_path"].endswith("day1_gear_templates.json")


def test_loot_differs_only_in_the_gear_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    template = _config(monkeypatch)
    loot = _config(monkeypatch, "--gear", "loot")
    assert loot["gear"] == "loot"
    differing = {k for k in template if template[k] != loot[k]}
    assert "gear" in differing
    assert differing <= {"gear", "template_path"}
