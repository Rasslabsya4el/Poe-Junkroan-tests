"""#436: a Flask slot's mod lines are audited like a gear line (they were skipped before)."""

from __future__ import annotations

from junkroan.optimizer.audit import audit_unsupported_mods


class _Pob:
    def __init__(self, slots: dict) -> None:
        self.slots = slots
        self.parsed: list[str] = []

    def read_state(self) -> dict:
        return {"items_state": {"slots": self.slots}, "tree_state": {}}

    def parse_mods(self, lines: list[str]) -> list[dict]:
        self.parsed = list(lines)
        return [{"line": ln, "ok": True, "unsupported": ln.startswith("BAD")} for ln in lines]

    def export_xml(self) -> str:
        return "<PathOfBuilding/>"


def _slot(lines: list[str]) -> dict:
    return {"item": {"implicit_affixes": [], "explicit_affixes": lines}}


def test_flask_line_is_audited_and_counted() -> None:
    pob = _Pob({"Flask 1": _slot(["BAD flask line"]), "Helmet": _slot(["BAD helmet line"])})
    findings = audit_unsupported_mods(pob)
    assert sorted(pob.parsed) == ["BAD flask line", "BAD helmet line"]
    flask = [f for f in findings if "BAD flask line" in f.detail]
    assert len(flask) == 1 and "Flask 1" in flask[0].detail


def test_non_flask_slot_behaviour_is_unchanged() -> None:
    pob = _Pob({"Helmet": _slot(["BAD helmet line"])})
    findings = audit_unsupported_mods(pob)
    assert [f.detail for f in findings] == ["BAD helmet line (Helmet): worth zero in every number here"]
