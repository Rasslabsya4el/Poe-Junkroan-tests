"""#897: two recordings of one build give one digest when PoB writes Sockets in another order."""

from pathlib import Path

import pytest

from junkroan.recording_pob import _canonical_xml, _digest

ROOT = Path(__file__).resolve().parent.parent
TRY2 = ROOT / "artifacts/probe-896/try-2/first-load-2.xml"
TRY3 = ROOT / "artifacts/probe-896/try-3/first-load-2.xml"


def _xml(sockets: str, nodes: str = '<Node id="1"/><Node id="2"/>') -> str:
    return f"<PathOfBuilding><Tree><Spec><Nodes>{nodes}</Nodes><Sockets>{sockets}</Sockets></Spec></Tree></PathOfBuilding>"


A = '<Socket nodeId="10532" itemId="20"/><Socket nodeId="2491" itemId="19"/>'
B = '<Socket nodeId="2491" itemId="19"/><Socket nodeId="10532" itemId="20"/>'


def test_probe_files_equal():
    if not (TRY2.exists() and TRY3.exists()):
        pytest.skip("artifacts/probe-896 absent")
    a = _canonical_xml(TRY2.read_text(encoding="utf-8"))
    b = _canonical_xml(TRY3.read_text(encoding="utf-8"))
    assert a == b and _digest(a) == _digest(b)


def test_swapped_sockets_equal_but_other_node_differs():
    assert _digest(_canonical_xml(_xml(A))) == _digest(_canonical_xml(_xml(B)))
    other = A.replace("10532", "10533")
    assert _digest(_canonical_xml(_xml(A))) != _digest(_canonical_xml(_xml(other)))


def test_ordered_children_still_differ():
    assert _canonical_xml(_xml(A, '<Node id="1"/><Node id="2"/>')) != _canonical_xml(_xml(A, '<Node id="2"/><Node id="1"/>'))
