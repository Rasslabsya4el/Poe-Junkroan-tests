"""#495: the hand-off and the first reply after a clear list every live external run (docs test, no PoB)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRAIN = ROOT / "docs" / "agents" / "brain.md"
SESSIONS = ROOT / "docs" / "agents" / "sessions.md"

# The three points of #495, each as phrases both files must carry.
POINT_1 = ("machines line", "live external run", "end time or cap", "log or output path", "who reads the result")
POINT_2 = ("first reply", "before any other work", "what it checked")
POINT_3 = ("without being asked", "the moment it sees it", "never on the owner's reminder")


def _flat(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


def test_brain_and_sessions_carry_the_three_points():
    for path in (BRAIN, SESSIONS):
        text = _flat(path)
        for phrase in POINT_1 + POINT_2 + POINT_3:
            assert phrase in text, f"{path.name} lacks: {phrase}"


def test_brain_hand_off_names_live_external_runs_inside_the_machines_line():
    text = _flat(BRAIN)
    reset = text[text.index("## Reset"):text.index("## Working with the owner")]
    assert "The State entry's machines line names the live external runs" in reset
    assert 'the "Machines at HH:MM" part of the brain\'s State entry' in reset


def test_every_run_kind_is_named():
    for path in (BRAIN, SESSIONS):
        text = _flat(path)
        for kind in ("research run", "heavy tool", "detached driver", "ORCH session"):
            assert kind in text, f"{path.name} lacks the run kind: {kind}"
