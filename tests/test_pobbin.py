import io
import json
import urllib.error
import urllib.request

import pytest

from junkroan import pobbin
from junkroan.pobbin import HttpStatusError, PobbinRun


class Fake:
    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    def __call__(self, code):
        self.calls += 1
        r = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if isinstance(r, Exception):
            raise r
        return r


def run(fake, tmp_path):
    return PobbinRun(fake, tmp_path / "ids.json")


def test_row1(tmp_path):
    f = Fake(["abc123"])
    r = run(f, tmp_path)
    assert r.upload("c", "A") == {"pobbin_id": "abc123", "pobbin_url": "https://pobb.in/abc123"}
    assert f.calls == 1


def test_row2(tmp_path):
    f = Fake([HttpStatusError(500), HttpStatusError(500), "id2"])
    r = run(f, tmp_path)
    assert r.upload("a", "A") == {"pobbin_error": "HTTP 500"}
    assert r.offline is None
    assert r.upload("b", "B")["pobbin_id"] == "id2"
    assert f.calls == 3


def test_row2b(tmp_path):
    f = Fake([HttpStatusError(404)])
    r = run(f, tmp_path)
    assert r.upload("a", "A") == {"pobbin_error": "HTTP 404"}
    assert f.calls == 1


def test_row3(tmp_path):
    f = Fake([ConnectionError("down")])
    r = run(f, tmp_path)
    assert r.upload("cA", "A") == {"pobbin_error": "ConnectionError: down"}
    msg = "skipped: offline since A: ConnectionError: down"
    assert r.upload("cB", "B") == {"pobbin_error": msg}
    assert r.upload("cC", "C") == {"pobbin_error": msg}
    assert f.calls == 2
    assert r.retry_pass([("A", "cA"), ("B", "cB"), ("C", "cC")]) == {}
    assert f.calls == 3


def test_row3b(tmp_path):
    f = Fake([ConnectionError("down"), "ok1"])
    r = run(f, tmp_path)
    assert r.upload("cA", "A")["pobbin_id"] == "ok1"
    assert r.offline is None
    assert f.calls == 2


def test_row3c_retry_pass_after_offline(tmp_path):
    f = Fake([ConnectionError("x"), ConnectionError("x"), "late"])
    r = run(f, tmp_path)
    r.upload("cA", "A")
    assert r.offline
    out = r.retry_pass([("A", "cA")])
    assert out["A"]["pobbin_id"] == "late"


def test_row4(tmp_path):
    f = Fake(["same"])
    r = run(f, tmp_path)
    a = r.upload("code", "A")
    b = r.upload("code", "B")
    assert a == b and f.calls == 1
    assert len(json.loads((tmp_path / "ids.json").read_text())) == 1


def test_row4b(tmp_path):
    f = Fake(["same"])
    run(f, tmp_path).upload("code", "A")
    f2 = Fake(["other"])
    assert run(f2, tmp_path).upload("code", "A")["pobbin_id"] == "same"
    assert f2.calls == 0


def test_row5(tmp_path, monkeypatch):
    seen = {}

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def ok(req, timeout=None):
        seen["req"] = req
        return Resp(b" xyz\n")

    monkeypatch.setattr(urllib.request, "urlopen", ok)
    assert pobbin.upload_code("CODE") == "xyz"
    req = seen["req"]
    assert req.get_header("User-agent") == "junkroan-benchmark"
    assert req.get_method() == "POST"
    assert req.full_url == pobbin.UPLOAD_URL
    assert req.data == b"CODE"

    def bad(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 503, "x", {}, None)

    monkeypatch.setattr(urllib.request, "urlopen", bad)
    with pytest.raises(HttpStatusError) as ei:
        pobbin.upload_code("CODE")
    assert ei.value.status == 503
