"""The call recorder of #35 (M1): transparent to the code it wraps, one stable line per call."""

from __future__ import annotations

import json

from junkroan.recording_pob import RecordingPob, call_line, canonical


class _Session:
    def __init__(self) -> None:
        self.mean_parts = None
        self.calls: list[tuple] = []

    def stats(self, keys):
        self.calls.append(("stats", tuple(keys)))
        return {key: 1.0 for key in keys}

    def load_xml(self, xml: str) -> None:
        self.calls.append(("load_xml", len(xml)))

    def config_inputs(self) -> dict:
        return {"usePowerCharges": True}


def _lines(path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_the_proxy_forwards_calls_and_attribute_writes_and_records_each_call(tmp_path) -> None:
    session = _Session()
    out = tmp_path / "calls" / "build.calls.jsonl"
    pob = RecordingPob(session, out)

    assert pob.stats(("Life", "CombinedDPS")) == {"Life": 1.0, "CombinedDPS": 1.0}
    pob.mean_parts = (1, 2)  # an attribute write lands on the session, as without the proxy
    assert session.mean_parts == (1, 2) and pob.mean_parts == (1, 2)
    pob.load_xml("<Build>" + "x" * 5000 + "</Build>")
    assert hasattr(pob, "config_inputs") and not hasattr(pob, "no_such_surface")
    pob.close_recording()

    lines = _lines(out)
    assert [(line["seq"], line["method"]) for line in lines] == [(1, "stats"), (2, "load_xml")]
    assert session.calls == [("stats", ("Life", "CombinedDPS")), ("load_xml", 5015)]
    assert "sha256" in lines[1]["preview"], "a long string enters the transcript as its hash"
    assert pob.recorded_calls == 2


def test_equal_arguments_hash_equal_on_every_run_and_different_ones_do_not() -> None:
    first = call_line(1, "set_config", (), {"inputs": {"b": 2, "a": 1}, "nodes": {3, 1, 2}})
    again = call_line(1, "set_config", (), {"nodes": frozenset({2, 3, 1}), "inputs": {"a": 1, "b": 2}})
    other = call_line(1, "set_config", (), {"inputs": {"a": 1, "b": 3}, "nodes": {3, 1, 2}})

    assert first["args"] == again["args"] and first["args"] != other["args"]
    assert canonical(object()) == "<object>", "no memory address ever enters the transcript"
    assert canonical((1, "x" * 300))[1]["len"] == 300


def test_511_a_trials_trace_only_path_leaves_the_transcript_unchanged():
    from junkroan.recording_pob import call_line

    plain = call_line(1, "trial_stats", ([{"add": [5], "mastery": {}}], ["Life"]), {"mode": "fast"})
    traced = call_line(1, "trial_stats", ([{"add": [5], "mastery": {}, "path": [4, 5]}], ["Life"]), {"mode": "fast"})
    assert traced == plain
    other = call_line(1, "trial_stats", ([{"add": [6], "mastery": {}, "path": [6]}], ["Life"]), {"mode": "fast"})
    assert other["args"] != plain["args"]
