"""#1118 unit 1: the PC-load admission reads each sample minus the merge queue's own CPU share (pure, no PoB)."""

import json

import pytest

from junkroan.pob import slot_budget as sb

NOW = 10_000.0


def _rows(path, value, merge=None, n=10):
    """n samples, one a minute, the newest at NOW; every row carries merge_cores when given."""
    for i in range(n):
        sb.append_busy_sample(NOW - 60.0 * (n - 1 - i), value, path, merge_cores=merge)


def test_row1_merge_share_subtracted_and_gate_goes(tmp_path, monkeypatch):
    path = tmp_path / "pc_busy_cores.jsonl"
    monkeypatch.setattr(sb, "busy_samples_path", lambda: path)
    _rows(path, 9.6, merge=3.5)
    assert sb.read_admission_samples(path)[-1] == (NOW, pytest.approx(6.1))
    adm = sb.admission_now(now=NOW, previous_wait=True, cores=12, mode="day")
    assert adm.go and adm.reason == "back under"
    assert adm.mean == pytest.approx(6.1) and adm.cap == 9.0
    assert "6.1" in adm.line()
    assert sb.read_busy_samples(path)[-1] == (NOW, 9.6)


def test_floor_at_zero_when_merge_exceeds_busy(tmp_path):
    path = tmp_path / "s.jsonl"
    sb.append_busy_sample(NOW, 2.0, path, merge_cores=3.5)
    assert sb.read_admission_samples(path) == [(NOW, 0.0)]


def test_rows_without_merge_cores_are_whole_value(tmp_path):
    path = tmp_path / "s.jsonl"
    sb.append_busy_sample(NOW - 60.0, 9.2, path)
    sb.append_busy_sample(NOW, 7.0, path, merge_cores=None)
    assert sb.read_admission_samples(path) == [(NOW - 60.0, 9.2), (NOW, 7.0)]
    raw = path.read_text(encoding="utf-8")
    assert "merge_cores" not in raw


def test_old_row_format_still_read_by_admission(tmp_path):
    path = tmp_path / "s.jsonl"
    path.write_text('{"t": 5, "busy_cores": 1.5}\n', encoding="utf-8")
    assert sb.read_admission_samples(path) == [(5.0, 1.5)]


def test_round_trip_writes_and_reads_merge_field(tmp_path):
    path = tmp_path / "s.jsonl"
    sb.append_busy_sample(NOW - 60.0, 9.6, path, merge_cores=3.5)
    # a later append without merge rewrites the file: the earlier row keeps its merge_cores
    sb.append_busy_sample(NOW, 4.0, path)
    lines = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]
    assert lines[0] == {"t": NOW - 60.0, "busy_cores": 9.6, "merge_cores": 3.5}
    assert lines[1] == {"t": NOW, "busy_cores": 4.0}
    assert sb.read_busy_samples(path) == [(NOW - 60.0, 9.6), (NOW, 4.0)]
    assert sb.read_admission_samples(path) == [(NOW - 60.0, pytest.approx(6.1)), (NOW, 4.0)]


def test_admission_now_without_samples_uses_effective_values(tmp_path, monkeypatch):
    path = tmp_path / "s.jsonl"
    monkeypatch.setattr(sb, "busy_samples_path", lambda: path)
    # whole PC 9.6 would hold (line 9.0); with merge 3.5 the mean is 6.1 and the gate goes
    _rows(path, 9.6, merge=3.5, n=8)
    assert not sb.admission_now(now=NOW, previous_wait=True, cores=12, mode="day", samples=[
        (NOW - 10.0 * i, 9.6) for i in range(8)
    ]).go
    assert sb.admission_now(now=NOW, previous_wait=True, cores=12, mode="day").go


def test_merge_above_whole_pc_floors_at_zero_through_the_reader(tmp_path):
    path = tmp_path / "s.jsonl"
    _rows(path, 9.6, merge=12.0, n=3)
    assert sb.read_admission_samples(path)[-1] == (NOW, 0.0)


def test_five_rows_of_9_6_whole_3_5_merge_go_through_load_admission(tmp_path):
    path = tmp_path / "s.jsonl"
    _rows(path, 9.6, merge=3.5, n=5)
    samples = sb.read_admission_samples(path)
    adm = sb.load_admission(samples, NOW, "day", None, 12)
    assert adm.go and adm.mean == pytest.approx(6.1)
