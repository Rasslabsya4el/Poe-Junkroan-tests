"""`junkroan build --level N` is refused outside rulebook row `c-level`'s day-1 range (75-80)."""

import pytest

from junkroan import cli


def _run(monkeypatch, *extra):
    calls = []
    monkeypatch.setattr(cli, "_run", lambda script, argv: calls.append(script) or 0)
    rc = cli.main(["build", "--skill", "Fireball", *extra])
    return rc, calls


@pytest.mark.parametrize("level", ["74", "81"])
def test_day1_level_outside_range_refused(monkeypatch, level):
    with pytest.raises(SystemExit) as e:
        _run(monkeypatch, "--level", level)
    assert "75-80" in str(e.value) and "c-level" in str(e.value)


def test_day1_level_inside_range_passes(monkeypatch):
    rc, calls = _run(monkeypatch, "--level", "78")
    assert rc == 0 and calls == ["search.py"]


def test_non_day1_level_90_passes(monkeypatch, tmp_path):
    req = tmp_path / "r.json"
    req.write_text('{"skill": "Fireball", "stage": "t16"}')
    monkeypatch.setattr(cli, "_run", lambda script, argv: 0)
    assert cli.main(["build", str(req), "--level", "90"]) == 0
