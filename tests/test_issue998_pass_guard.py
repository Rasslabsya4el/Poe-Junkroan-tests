"""#998: PassGuard marks a service down for the rest of one pass only."""

from junkroan.runs.pass_guard import PassGuard


def test_down_lasts_one_pass_and_logs_once():
    t = [0.0]
    g = PassGuard(clock=lambda: t[0])
    assert not g.down("gh")
    assert g.mark_down("gh", "timeout") is True
    assert g.mark_down("gh", "timeout") is False
    assert g.down("gh") and not g.down("ssh:laptop")
    g.begin()
    assert not g.down("gh")


def test_steps_and_slowest():
    t = [0.0]
    g = PassGuard(clock=lambda: t[0])
    g.begin()
    a = g.now(); t[0] += 5; g.step("reap", a)
    b = g.now(); t[0] += 26; g.step("ticket_closed_pass", b)
    assert g.slowest() == ("ticket_closed_pass", 26.0)
    assert g.pass_seconds() == 31.0


def test_a_mark_expires_in_a_process_that_never_begins_a_pass():
    t = [0.0]
    g = PassGuard(clock=lambda: t[0])
    g.mark_down("ssh:laptop", "timeout")
    t[0] = 59.0
    assert g.down("ssh:laptop")
    t[0] = 61.0
    assert not g.down("ssh:laptop")
    assert g.mark_down("ssh:laptop", "timeout") is True
