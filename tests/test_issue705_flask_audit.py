"""#705: an empty Flask slot is an audit error (rails allow 5 flask slots)."""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path

import pytest

from junkroan.optimizer.audit import audit_xml
from junkroan.optimizer.rails import Rails
from junkroan.pob.session import decode_import_code

REAL = Path(__file__).resolve().parents[1] / "artifacts/benchmark/20261005-1220-gate-20261005/absolution_minions-s4.pob.txt"


def _rails_on() -> Rails:
    """The rail-on case (#1162): every flask slot is crafted, so an empty Flask 2..5 is an error. Day-1 rails have it off."""

    base = Rails.load()
    return dataclasses.replace(base, gear=dataclasses.replace(base.gear, flasks=dataclasses.replace(base.gear.flasks, flask_utility_crafting=True)))


def _synthetic(skip: int | None = None) -> str:
    items = "".join(f'<Item id="{n}">Rarity: MAGIC\nFlask {n}\n</Item>' for n in range(1, 6))
    slots = "".join(f'<Slot name="Flask {n}" itemId="{0 if n == skip else n}"/>' for n in range(1, 6))
    return f'<PathOfBuilding><Items activeItemSet="1">{items}<ItemSet id="1">{slots}</ItemSet></Items></PathOfBuilding>'


def _flask(findings):
    return [f for f in findings if f.check == "flask-slot-empty"]


def test_five_flasks_no_finding() -> None:
    assert _flask(audit_xml(_synthetic(), _rails_on())) == []


def test_flask_3_removed_one_error() -> None:
    found = _flask(audit_xml(_synthetic(skip=3), _rails_on()))
    assert len(found) == 1 and found[0].severity == "error" and "Flask 3" in found[0].detail


@pytest.mark.skipif(not REAL.exists(), reason="weekly run artifacts not linked")
def test_real_build_rows() -> None:
    xml = decode_import_code(REAL.read_text(encoding="utf-8").strip())
    rails = _rails_on()
    assert _flask(audit_xml(xml, rails)) == []
    cut = re.sub(r'(name="Flask 3" itemId=")\d+', r"\g<1>0", xml)
    found = _flask(audit_xml(cut, rails))
    assert len(found) == 1 and "Flask 3" in found[0].detail
