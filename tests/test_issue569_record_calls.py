"""#569 unit 6: `benchmark.py --record-calls DIR` records the PoB calls of each build (PoB-free)."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import benchmark  # noqa: E402


class FakeSession:
    def __init__(self):
        self.flag = 0

    def stats(self, x):
        return {"x": x}


def test_without_flag_session_is_returned_as_is():
    s = FakeSession()
    assert benchmark._session_for(s, None, "/o/logs/stormbrand-s4.log") is s


def test_base_row_file_name_and_forwarding(tmp_path):
    s = FakeSession()
    pob = benchmark._session_for(s, str(tmp_path / "calls"), "/o/logs/stormbrand-s4.log")
    assert pob.stats(3) == {"x": 3}
    pob.flag = 5
    assert s.flag == 5
    path = tmp_path / "calls" / "stormbrand-s4.calls.jsonl"
    pob._rec_file.flush()
    lines = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]
    assert [x["method"] for x in lines] == ["stats"]


def test_variant_row_file_name(tmp_path):
    benchmark._session_for(FakeSession(), str(tmp_path), "/o/logs/stormbrand-s4-no-mind_over_matter.log")
    assert (tmp_path / "stormbrand-s4-no-mind_over_matter.calls.jsonl").is_file()


def test_run_one_takes_record_calls_and_argparse_parses(monkeypatch):
    import inspect

    assert "record_calls" in inspect.signature(benchmark.run_one).parameters
    assert "record_calls" in benchmark._RESUMABLE_ARG_FIELDS
    captured = {}

    class Stop(Exception):
        pass

    def fake_prepare(args):
        captured["record_calls"] = args.record_calls
        raise Stop

    monkeypatch.setattr(benchmark, "_prepare_resume", fake_prepare)
    monkeypatch.setattr(sys, "argv", ["benchmark.py", "--resume", "x", "--record-calls", "D"])
    try:
        benchmark.main()
    except Stop:
        pass
    assert captured["record_calls"] == "D"
