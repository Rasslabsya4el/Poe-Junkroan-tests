import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import pane_look as pl  # noqa: E402

RECT = (0, 0, 1000, 800)
LINE = "owner active: last input 30 s ago, need 120 s; nothing moved"


@pytest.fixture(autouse=True)
def chain_env(tmp_path, monkeypatch):
    """No test writes the real var/ folder or reads the real last-input tick (#837)."""
    tick = [1_000_000]
    monkeypatch.setattr(pl, "CHAIN_PATH", tmp_path / "var" / "pane_look_chain.json")
    monkeypatch.setattr(pl, "last_input_tick", lambda: tick[0])
    return tick


def write_chain(tick, age=0.0, started=True):
    pl.CHAIN_PATH.parent.mkdir(parents=True, exist_ok=True)
    pl.CHAIN_PATH.write_text(json.dumps({"own_last_input_tick": tick, "chain_started_idle": started,
                                         "recorded_at": time.time() - age}), encoding="utf-8")


class FakePointer:
    def __init__(self, pos):
        self.pos = pos
        self.log = []

    def move(self, x, y):
        self.log.append(("move", x, y))
        self.pos = (x, y)

    def button(self, down):
        self.log.append(("down" if down else "up",))

    def get(self):
        return self.pos


def test_press_idle_30_nothing_moved():
    p, out = FakePointer((5, 6)), []
    code = pl.do_press(150, 120, rect_fn=lambda: RECT, get_pos=p.get, move=p.move, button=p.button,
                       sleep=lambda s: None, say=out.append, idle_seconds=lambda: 30)
    assert code == 3 and p.log == [] and out == [LINE]


def test_hover_idle_30_nothing_moved(tmp_path):
    p, out = FakePointer((5, 6)), []
    code = pl.do_hover(150, 120, tmp_path / "h.png", rect_fn=lambda: RECT, get_pos=p.get, move=p.move,
                       capture=lambda: (1, 1, bytes(3)), sleep=lambda s: None, say=out.append,
                       idle_seconds=lambda: 30)
    assert code == 3 and p.log == [] and out == [LINE] and not (tmp_path / "h.png").exists()


def test_press_idle_300_restores_pointer():
    p = FakePointer((11, 22))
    code = pl.do_press(150, 120, rect_fn=lambda: RECT, get_pos=p.get, move=p.move, button=p.button,
                       sleep=lambda s: None, say=lambda s: None, idle_seconds=lambda: 300)
    assert code == 0
    assert p.log == [("move", 150, 120), ("down",), ("up",), ("move", 11, 22)]
    assert p.pos == (11, 22)


def test_series_stops_when_owner_moves_pointer(tmp_path):
    p, out, looks = FakePointer((11, 22)), [], []

    def cap():
        looks.append(1)
        if len(looks) == 2:           # the owner grabs the mouse right after the 2nd look
            p.pos = (11 + 40, 22)
        return 1, 1, bytes(3)

    real_move = p.move

    def move(x, y):
        if len(looks) == 2 and p.log and p.log[-1][0] == "move" and (x, y) == (11, 22):
            # the move back of look 2 lands, then the owner has already moved away
            real_move(x, y)
            p.pos = (51, 22)
            return
        real_move(x, y)

    idle_reads = []
    code = pl.do_hover_series([(100, 100)] * 5, str(tmp_path / "s_{k}.png"), rect_fn=lambda: RECT,
                              get_pos=p.get, move=move, capture=cap, sleep=lambda s: None, say=out.append,
                              idle_seconds=lambda: idle_reads.append(1) or 300)
    n_moves = len([e for e in p.log if e[0] == "move"])
    assert code == 3 and len(looks) == 2 and idle_reads == [1]
    assert out[-1] == "owner back: series stopped after 2 of 5"
    assert n_moves == 4  # 2 looks x (to point, back); nothing after the stop


def test_scroll_idle_30_nothing_moved(tmp_path):
    p, wheels, lines = FakePointer((5, 6)), [], []
    code = pl.do_scroll(150, 120, -3, out=tmp_path / "s.png", rect_fn=lambda: RECT, get_pos=p.get, move=p.move,
                        wheel=wheels.append, capture=lambda: (1, 1, bytes(3)), sleep=lambda s: None,
                        say=lines.append, idle_seconds=lambda: 30)
    assert code == 3 and p.log == [] and wheels == [] and lines == [LINE] and not (tmp_path / "s.png").exists()


def test_scroll_idle_300_restores_pointer():
    p, wheels = FakePointer((11, 22)), []
    code = pl.do_scroll(150, 120, -2, rect_fn=lambda: RECT, get_pos=p.get, move=p.move,
                        wheel=wheels.append, sleep=lambda s: None, say=lambda s: None, idle_seconds=lambda: 300)
    assert code == 0 and wheels == [-120, -120]
    assert p.log == [("move", 150, 120), ("move", 11, 22)]
    assert p.pos == (11, 22)


def test_look_makes_no_pointer_call_and_no_idle_read(tmp_path):
    out = tmp_path / "l.png"
    code = pl.do_look(out, capture=lambda: (2, 1, bytes(6)), say=lambda s: None)
    assert code == 0 and out.exists()
    # the look has no pointer or idle seam in its signature
    import inspect
    assert set(inspect.signature(pl.do_look).parameters) == {"out", "capture", "say"}


def test_wait_for_pause_bounded():
    t, sleeps = [0], []
    def idle():
        return 10
    def sleep(s):
        sleeps.append(s)
    out = []
    assert pl.wait_for_pause(idle, sleep=sleep, say=out.append) is False
    assert sum(sleeps) == 600 and out == ["no pause"]
    vals = iter([10, 20, 200])
    assert pl.wait_for_pause(lambda: next(vals), sleep=lambda s: None, say=out.append) is True


def test_idle_wraparound():
    assert pl.idle_from_ticks(tick=1000, last=4294967000) == (1000 - 4294967000) % 2**32 / 1000


def test_chain_second_action_passes_when_tick_unchanged(chain_env):
    p, out = FakePointer((11, 22)), []
    kw = dict(rect_fn=lambda: RECT, get_pos=p.get, move=p.move, button=p.button, sleep=lambda s: None, say=out.append)
    assert pl.do_press(150, 120, idle_seconds=lambda: 300, **kw) == 0       # first action: real 120 s
    assert pl.CHAIN_PATH.exists()
    assert pl.do_press(150, 120, idle_seconds=lambda: 30, **kw) == 0        # owner idle 30 s, tick unchanged
    assert out[-1].startswith("pressed") and LINE not in out
    assert len([e for e in p.log if e[0] == "move"]) == 4


def test_chain_refused_when_owner_moved_tick(chain_env):
    p, out = FakePointer((11, 22)), []
    kw = dict(rect_fn=lambda: RECT, get_pos=p.get, move=p.move, button=p.button, sleep=lambda s: None, say=out.append)
    assert pl.do_press(150, 120, idle_seconds=lambda: 300, **kw) == 0
    chain_env[0] += 5000                                                     # owner input moves the tick
    n_before = len(p.log)
    assert pl.do_press(150, 120, idle_seconds=lambda: 30, **kw) == 3
    assert out[-1] == LINE and len(p.log) == n_before


def test_chain_record_older_than_ten_minutes_ignored(chain_env):
    p, out = FakePointer((11, 22)), []
    kw = dict(rect_fn=lambda: RECT, get_pos=p.get, move=p.move, button=p.button, sleep=lambda s: None, say=out.append)
    write_chain(chain_env[0], age=599)
    assert pl.do_press(150, 120, idle_seconds=lambda: 30, **kw) == 0        # 599 s: still the chain
    write_chain(chain_env[0], age=601)
    assert pl.do_press(150, 120, idle_seconds=lambda: 30, **kw) == 3        # 601 s: plain 120 s rule
    assert out[-1] == LINE


@pytest.mark.parametrize("content", [
    "{not json",
    "[1, 2]",
    json.dumps({"own_last_input_tick": "1000000", "chain_started_idle": True, "recorded_at": 0}),
    json.dumps({"own_last_input_tick": 1000000, "chain_started_idle": False, "recorded_at": 0}),
    json.dumps({"own_last_input_tick": 1000000, "chain_started_idle": True}),
])
def test_chain_corrupt_file_plain_rule(chain_env, content):
    p, out = FakePointer((11, 22)), []
    pl.CHAIN_PATH.parent.mkdir(parents=True, exist_ok=True)
    pl.CHAIN_PATH.write_text(content, encoding="utf-8")
    code = pl.do_press(150, 120, rect_fn=lambda: RECT, get_pos=p.get, move=p.move, button=p.button,
                       sleep=lambda s: None, say=out.append, idle_seconds=lambda: 30)
    assert code == 3 and p.log == [] and out == [LINE]


@pytest.mark.parametrize("action", ["press", "hover", "series", "scroll"])
def test_each_action_records_tick_after_put_back(chain_env, tmp_path, action):
    p = FakePointer((11, 22))

    def move(x, y):
        chain_env[0] += 1000          # the tool's own injected move stamps the tick
        p.move(x, y)

    def cap():
        return 1, 1, bytes(3)

    common = dict(rect_fn=lambda: RECT, get_pos=p.get, move=move, sleep=lambda s: None, say=lambda s: None,
                  idle_seconds=lambda: 300)
    if action == "press":
        code = pl.do_press(150, 120, button=lambda d: None, **common)
    elif action == "hover":
        code = pl.do_hover(150, 120, tmp_path / "h.png", capture=cap, **common)
    elif action == "series":
        code = pl.do_hover_series([(150, 120), (160, 120)], str(tmp_path / "s_{k}.png"), capture=cap, **common)
    else:
        code = pl.do_scroll(150, 120, -2, wheel=lambda d: None, **common)
    rec = json.loads(pl.CHAIN_PATH.read_text(encoding="utf-8"))
    assert code == 0
    assert rec["own_last_input_tick"] == chain_env[0]     # read after the last move (the put-back)
    assert rec["chain_started_idle"] is True
    assert time.time() - rec["recorded_at"] < 60


def test_look_writes_no_chain_record(chain_env, tmp_path):
    pl.do_look(tmp_path / "l.png", capture=lambda: (1, 1, bytes(3)), say=lambda s: None)
    assert not pl.CHAIN_PATH.exists()


def test_series_owner_back_writes_no_record(chain_env, tmp_path):
    p, out = FakePointer((11, 22)), []

    def move(x, y):
        p.move(x, y)
        if (x, y) == (11, 22):
            p.pos = (51, 22)          # the owner moves the pointer right after the put-back
    code = pl.do_hover_series([(100, 100)], str(tmp_path / "s_{k}.png"), rect_fn=lambda: RECT, get_pos=p.get,
                              move=move, capture=lambda: (1, 1, bytes(3)), sleep=lambda s: None,
                              say=out.append, idle_seconds=lambda: 300)
    assert code == 3 and out[-1] == "owner back: series stopped after 1 of 1"
    assert not pl.CHAIN_PATH.exists()


def test_wait_for_pause_passes_at_once_on_chain(chain_env):
    write_chain(chain_env[0])
    sleeps = []
    assert pl.wait_for_pause(lambda: 10, sleep=sleeps.append, say=lambda s: None) is True
    assert sleeps == []


def test_wait_for_pause_still_polls_without_chain(chain_env):
    sleeps, out = [], []
    assert pl.wait_for_pause(lambda: 10, sleep=sleeps.append, say=out.append) is False
    assert sum(sleeps) == 600 and out == ["no pause"]


def test_wait_for_pause_flag_reaches_the_gate(monkeypatch):
    seen = []
    monkeypatch.setattr(pl, "idle_seconds", lambda: 999)     # owner away: the wait passes at once
    monkeypatch.setattr(pl, "do_press", lambda x, y, **kw: seen.append((x, y)) or 0)
    assert pl.main(["press", "150", "120", "--wait-for-pause"]) == 0
    assert seen == [(150, 120)]
