"""#1207: Pillow is a `dev` extra, so the Windows CI job that runs
`pip install -e ".[dev,research]" psutil` gets PIL for tests/test_pane_points.py
and tests/test_pane_web.py."""

import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _dev_extra_names() -> list[str]:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    entries = data["project"]["optional-dependencies"]["dev"]
    # the name of a requirement is what stands before any version specifier,
    # extra marker or environment marker
    return [re.split(r"[<>=!~;\[\s]", entry, maxsplit=1)[0].lower() for entry in entries]


def test_dev_extra_lists_pillow():
    assert "pillow" in _dev_extra_names()


def test_import_pil_works_in_this_environment():
    PIL = pytest.importorskip("PIL", reason="PIL (Pillow) is not installed in this environment")
    assert PIL.__file__
