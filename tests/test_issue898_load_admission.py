"""#898 unit 1: the PC-load admission rule (pure, no PoB)."""

from junkroan.pob import slot_budget as sb

NOW = 10_000.0


def _s(value, n=10, newest_age=0.0):
    return [(NOW - newest_age - 60.0 * i, value) for i in range(n)]


def _ask(value, mode="day", prev=None, cores=12, **kw):
    return sb.load_admission(_s(value, **kw), NOW, mode, prev, cores)


def test_row1_day_9_2_waits():
    a = _ask(9.2)
    assert not a.go and a.cap == 9.0 and abs(a.mean - 9.2) < 1e-9 and "9.2" in a.line()


def test_row2_day_prev_wait_8_5_waits():
    assert not _ask(8.5, prev=True).go


def test_row3_day_prev_wait_7_9_goes():
    assert _ask(7.9, prev=True).go


def test_row4_day_no_prev_8_5_goes():
    assert _ask(8.5).go and _ask(8.5, prev=False).go


def test_row5_night():
    assert _ask(9.2, "night").go
    assert not _ask(11.0, "night").go
    assert _ask(9.9, "night", prev=True).go


def test_row6_play_waits_even_without_samples():
    assert not _ask(0.5, "play").go
    assert not sb.load_admission([], NOW, "play", None, 12).go


def test_row7_no_reading():
    a = _ask(11.5, n=4)
    assert a.go and a.reason == "no reading"
    b = _ask(11.5, newest_age=121.0)
    assert b.go and b.reason == "no reading"


def test_row8_16_cores():
    assert round(sb.admission_caps("day", 16)[0], 2) == 12.0
    assert round(sb.admission_caps("night", 16)[0], 2) == 14.67
    assert sb.admission_caps("day", 12) == (9.0, 8.0)
    assert sb.admission_caps("night", 12) == (11.0, 10.0)


def test_append_trims_old_and_reads(tmp_path):
    f = tmp_path / "s.jsonl"
    sb.append_busy_sample(NOW - 1300, 3.0, f)
    sb.append_busy_sample(NOW, 4.0, f)
    assert sb.read_busy_samples(f) == [(NOW, 4.0)]


def test_corrupt_line_and_missing_file(tmp_path):
    f = tmp_path / "s.jsonl"
    assert sb.read_busy_samples(f) == []
    f.write_text('garbage\n{"t": 5, "busy_cores": 1.5}\n', encoding="utf-8")
    assert sb.read_busy_samples(f) == [(5.0, 1.5)]
    sb.append_busy_sample(10.0, 2.0, f)
    assert sb.read_busy_samples(f) == [(5.0, 1.5), (10.0, 2.0)]
