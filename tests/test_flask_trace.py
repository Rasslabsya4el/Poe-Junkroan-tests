import pytest

from junkroan.optimizer.flask_step import run_flask_step
from junkroan.optimizer.flask_trace import FORBIDDEN_CLASSES, TracingFlaskProbe, count_generated
from junkroan.optimizer.trace import TRACE
from tests.test_flask_step import BASES, MODS, Cand, FakeProbe, gain


@pytest.fixture(autouse=True)
def _fresh_trace():
    TRACE.reset()
    yield
    TRACE.reset()


def test_allowed_classes_counted_forbidden_zero():
    made = []

    def mk(b, p, s):
        c = Cand(b, p, s)
        made.append(c)
        return c

    inner = FakeProbe(gain)
    with TRACE.move("flask"):
        run_flask_step(TracingFlaskProbe(inner), BASES, lambda b: MODS, mk, item_level=84, base_level_max=70)
        count_generated(made)
    moves = TRACE.considered()["flask"]
    for cls in ("flask-base:life", "flask-base:utility", "flask-base:tincture", "flask-mods:0", "flask-mods:1", "flask-mods:2"):
        assert moves[cls]["generated"] > 0 and moves[cls]["evaluated"] > 0, cls
    for cls in FORBIDDEN_CLASSES:
        assert moves[cls] == {"generated": 0, "evaluated": 0}


def _flask_xml(active1: str, active2: str) -> str:
    return (
        "<PathOfBuilding><Items activeItemSet=\"1\">"
        "<Item id=\"1\">Flask A</Item><Item id=\"2\">Flask B</Item>"
        "<ItemSet id=\"1\">"
        f"<Slot name=\"Flask 1\" itemId=\"1\" active=\"{active1}\"/>"
        f"<Slot name=\"Flask 2\" itemId=\"2\" active=\"{active2}\"/>"
        "<Slot name=\"Flask 3\" itemId=\"0\" active=\"true\"/>"
        "</ItemSet></Items></PathOfBuilding>"
    )


def test_flask_active_and_below_100_counts():
    from junkroan.optimizer.trace_output import trace_output_from_xml

    ups = {"Flask 1": {"full": True}, "Flask 2": {"full": False}}
    out = trace_output_from_xml(_flask_xml("true", "true"), flask_uptimes=ups)
    assert out["flask-active"] == 2 and out["flask-active-uptime-below-100"] == 1
    out = trace_output_from_xml(_flask_xml("false", "false"), flask_uptimes=ups)
    assert out["flask-active"] == 0 and out["flask-active-uptime-below-100"] == 0
    out = trace_output_from_xml(_flask_xml("true", "true"))
    assert out["flask-active"] == 2 and "flask-active-uptime-below-100" not in out


def test_count_generated_writes_below_100_zero():
    with TRACE.move("flask"):
        count_generated([])
    assert TRACE.considered()["flask"]["flask-active-uptime-below-100"] == {"generated": 0, "evaluated": 0}


def test_divine_class_for_the_divine_only_and_no_divine_written_zero():
    from types import SimpleNamespace

    from junkroan.optimizer.flask_trace import NO_DIVINE_CLASS, flask_classes

    def cand(name):
        return SimpleNamespace(base=SimpleNamespace(name=name, kind="life"), prefix=None, suffix=None)

    assert "flask-divine-life" in flask_classes(cand("Divine Life Flask"))
    assert "flask-divine-life" not in flask_classes(cand("Greater Life Flask"))
    with TRACE.move("flask"):
        count_generated([])
    assert TRACE.considered()["flask"][NO_DIVINE_CLASS] == {"generated": 0, "evaluated": 0}
