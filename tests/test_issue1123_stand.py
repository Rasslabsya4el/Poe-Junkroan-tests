"""#1123 unit 2: the red-line stand check (`scripts/red_line_stand_check.py`).

The PoB-free tests drive the script's own functions with a fake PobSession whose XML holds the two
config sets (Baseline, Conditional) and whose stats read the custom modifier blocks in each set, so the
real writers (`apply_custom_mods`, the Conditional writer) are exercised. The one `pob` test runs two
fixture records on the spark stand of the newest weekly core run.
"""

from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import red_line_stand_check as check  # noqa: E402

OUTPUT_KEYS = ("CombinedDPS", "TotalEHP", "Life", "EnergyShield", "Mana", "LifeRegenRecovery", "PhysicalMaximumHitTaken")
FAKE_XML = ('<PathOfBuilding><Config><ConfigSet id="1" title="Baseline"></ConfigSet>'
            '<ConfigSet id="2" title="Conditional"></ConfigSet></Config></PathOfBuilding>')


class FakePob:
    """Stand-in for PobSession: `Adds N to Stat` lines in a set's custom blocks add N to Stat."""

    def __init__(self, base: dict | None = None) -> None:
        self.base = {key: 100.0 for key in OUTPUT_KEYS}
        self.base.update(base or {})
        self.xml = FAKE_XML
        self.loads = 0

    def export_xml(self) -> str:
        return self.xml

    def load_xml(self, xml: str) -> None:
        self.xml = xml
        self.loads += 1

    def _effects(self, title: str) -> dict[str, float]:
        body = re.search(rf'<ConfigSet [^>]*title="{title}"[^>]*>(.*?)</ConfigSet>', self.xml, re.S)
        effects: dict[str, float] = {}
        for block in re.findall(r"<CustomModifierBlock[^>]*>(.*?)</CustomModifierBlock>", body.group(1) if body else "", re.S):
            for line in html.unescape(block).splitlines():
                match = re.fullmatch(r"Adds (\d+(?:\.\d+)?) to (\w+)", line.strip())
                if match:
                    effects[match.group(2)] = effects.get(match.group(2), 0.0) + float(match.group(1))
        return effects

    def stats(self, keys=None) -> dict:
        effects = self._effects("Baseline")
        return {key: self.base.get(key, 0.0) + effects.get(key, 0.0) for key in (keys or OUTPUT_KEYS)}

    def calc(self, lane: str = "baseline") -> dict:
        effects = self._effects("Conditional" if lane == "conditional" else "Baseline")
        return {key: self.base[key] + effects.get(key, 0.0) for key in OUTPUT_KEYS}


def record(line: str, *, group: str = "g1", kind: str = "steal_charges", boss=(), optimistic=(), **extra) -> dict:
    return {"line": line, "group": group, "kind": kind, "boss_lane": list(boss), "optimistic_lane": list(optimistic),
            "why": "test reason", **extra}


def pobs() -> dict:
    return {"spell": FakePob(), "attack": FakePob(), "minion": FakePob()}


def test_changed_unchanged_zero_and_new_kind_are_counted():
    records = [
        record("A", group="g1", boss=["Adds 10 to Life"]),  # changed on every stand
        record("B", group="g1", boss=["Adds 3 to Nothing"]),  # moves no PoB output
        record("C", group="g2", kind="newkind", zero_reason="no verdict"),  # both lanes empty
        record("D", group="g2", kind="newkind", optimistic=["Adds 2 to Life"]),  # only the optimistic lane moves
    ]
    result = check.check_records(records, pobs())
    rows = {row.group: row for row in result.rows}
    assert (rows["g1"].records, rows["g1"].changed, rows["g1"].zero, rows["g1"].new_kind) == (2, 1, 0, 0)
    assert (rows["g2"].records, rows["g2"].changed, rows["g2"].zero, rows["g2"].new_kind) == (2, 1, 1, 2)
    assert [item.line for item in result.unchanged] == ["B"]
    assert check.exit_code(result) == 1


def test_all_changed_gives_exit_zero():
    result = check.check_records([record("A", boss=["Adds 10 to Life"]), record("D", optimistic=["Adds 2 to Life"])], pobs())
    assert result.unchanged == []
    assert check.exit_code(result) == 0


def test_optimistic_lane_is_read_from_the_conditional_set_only():
    spell = FakePob()
    result = check.check_records([record("D", optimistic=["Adds 2 to Life"], type="spell")], {"spell": spell, "attack": FakePob(), "minion": FakePob()})
    assert result.unchanged == []
    assert spell.xml == FAKE_XML  # restored after the lane


def test_type_routes_a_record_to_its_stand_only_and_no_type_to_all():
    fakes = pobs()
    check.check_records([record("M", boss=["Adds 10 to Life"], type="minion")], fakes)
    assert fakes["spell"].loads == 0 and fakes["attack"].loads == 0
    assert fakes["minion"].loads > 0
    fakes = pobs()
    check.check_records([record("N", boss=["Adds 10 to Life"])], fakes)
    assert all(fake.loads > 0 for fake in fakes.values())


def test_type_any_is_measured_on_every_selected_stand():
    fakes = pobs()
    check.check_records([record("A", boss=["Adds 10 to Life"], type="any")], fakes)
    assert all(fake.loads > 0 for fake in fakes.values())
    assert check.record_stands({"type": "any"}, ["spell", "minion"]) == ["spell", "minion"]


def test_stands_filter_leaves_other_types_unmeasured():
    fakes = pobs()
    result = check.check_records([record("M", boss=["Adds 10 to Life"], type="minion")], fakes, stands=("spell",))
    assert result.not_measured == ["M"]
    assert result.unchanged == []
    assert fakes["minion"].loads == 0


def test_formula_is_evaluated_from_the_stand_baseline_and_filled_into_the_line():
    fake = FakePob({"Life": 1000.0})
    result = check.check_records([record("F", boss=["Adds {formula} to Life"], formula="Life / 10", type="spell")],
                                 {"spell": fake, "attack": FakePob(), "minion": FakePob()})
    assert result.unchanged == []
    assert check.fill_formula(["Adds {formula} to Life"], 100.0) == ["Adds 100.00 to Life"]


def test_safe_eval_is_arithmetic_over_known_names_only():
    assert check.safe_eval("Life / 10", {"Life": 1000.0}) == pytest.approx(100.0)
    assert check.safe_eval("(Life+2)**2", {"Life": 2}) == pytest.approx(16.0)
    with pytest.raises(ValueError):
        check.safe_eval("__import__('os')", {})
    with pytest.raises(ValueError):
        check.safe_eval("Foo * 2", {})


def test_each_lane_restores_the_stand_so_the_next_record_starts_clean():
    fake = FakePob()
    check.check_records([record("A", boss=["Adds 10 to Life"], type="spell"), record("B", optimistic=["Adds 5 to Life"], type="spell")],
                        {"spell": fake, "attack": FakePob(), "minion": FakePob()})
    assert fake.xml == FAKE_XML
    assert fake.stats(["Life"])["Life"] == pytest.approx(100.0)


def test_table_prints_one_row_per_group_with_the_four_counts():
    result = check.check_records([record("A", group="ramp", boss=["Adds 10 to Life"]), record("C", group="ramp", kind="x")], pobs())
    text = check.format_table(result)
    assert "group" in text and "records" in text and "changed" in text and "zero" in text and "new-kind" in text
    assert any(line.split()[:5] == ["ramp", "2", "1", "1", "1"] for line in text.splitlines())


def test_newest_core_folder_and_stand_files(tmp_path: Path):
    for name in ("20261012-1601-P2-core", "20261013-0027-P2-core-2", "20261013-0101-P2-core-3", "20261015-2312-P1-#1091"):
        (tmp_path / name).mkdir()
    assert check.newest_core_folder(tmp_path).name == "20261013-0101-P2-core-3"
    folder = tmp_path / "20261013-0101-P2-core-3"
    (folder / "rows").mkdir()
    for slug in ("spark", "smite", "summon_raging_spirits"):
        (folder / f"{slug}-s4.pob.txt").write_text("code", encoding="utf-8")
        (folder / "rows" / f"{slug}-s4.json").write_text("{}", encoding="utf-8")
    files = check.stand_files(folder)
    assert files["spell"].name == "spark-s4.pob.txt"
    assert files["attack"].name == "smite-s4.pob.txt"
    assert files["minion"].name == "summon_raging_spirits-s4.pob.txt"
    (folder / "rows" / "smite-s4.json").unlink()
    with pytest.raises(FileNotFoundError):
        check.stand_files(folder)


def test_load_records_reads_a_file_a_wrapped_file_and_a_folder_of_parts(tmp_path: Path):
    marks = tmp_path / "marks"
    marks.mkdir()
    (marks / "part1.json").write_text(json.dumps([record("A")]), encoding="utf-8")
    (marks / "part2.json").write_text(json.dumps({"records": [record("B")]}), encoding="utf-8")
    assert [r["line"] for r in check.load_records(marks)] == ["A", "B"]
    single = tmp_path / "one.json"
    single.write_text(json.dumps({"records": [record("C")]}), encoding="utf-8")
    assert [r["line"] for r in check.load_records(single)] == ["C"]


def test_main_exit_code_and_limit(tmp_path: Path):
    folder = tmp_path / "stands"
    (folder / "rows").mkdir(parents=True)
    for slug in ("spark", "smite", "summon_raging_spirits"):
        (folder / f"{slug}-s4.pob.txt").write_text("code", encoding="utf-8")
        (folder / "rows" / f"{slug}-s4.json").write_text("{}", encoding="utf-8")
    marks = tmp_path / "marks.json"
    marks.write_text(json.dumps([record("A", boss=["Adds 10 to Life"]), record("B", boss=["Adds 3 to Nothing"])]), encoding="utf-8")
    fakes = pobs()
    opened = []

    def open_pob(stand_type: str, path: Path):
        opened.append((stand_type, path.name))
        return fakes[stand_type]

    code = check.main([str(marks), "--stand-folder", str(folder)], open_pob=open_pob)
    assert code == 1
    assert sorted(opened) == [("attack", "smite-s4.pob.txt"), ("minion", "summon_raging_spirits-s4.pob.txt"), ("spell", "spark-s4.pob.txt")]
    code_limited = check.main([str(marks), "--stand-folder", str(folder), "--limit", "1"], open_pob=lambda stand_type, path: pobs()[stand_type])
    assert code_limited == 0


@pytest.mark.pob
def test_spark_stand_two_fixture_records_move_pob_numbers():
    from junkroan.pob.session import PobSession

    folder = check.newest_core_folder(ROOT / "artifacts" / "benchmark")
    stand = check.stand_files(folder)["spell"]
    records = [
        record("+10 to maximum Life", boss=["+10 to maximum Life"], type="spell", group="fixture"),
        record("+15 to maximum Life", optimistic=["+15 to maximum Life"], type="spell", group="fixture"),
    ]
    with PobSession(run_id="issue1123-spark") as pob:
        pob.load_import_code(stand.read_text(encoding="utf-8").strip())
        result = check.check_records(records, {"spell": pob, "attack": None, "minion": None}, stands=("spell",))
    assert result.unchanged == []
    assert [row.changed for row in result.rows if row.group == "fixture"] == [2]


def blind(line: str, *, group: str = "g1", kind: str = "steal_charges", boss=(), optimistic=(),
          reason_kind: str = "trap", why: str = "a trap has no hit of its own") -> dict:
    return record(line, group=group, kind=kind, boss=boss, optimistic=optimistic,
                  stand_blind={"reason_kind": reason_kind, "why": why})


def test_unchanged_record_with_stand_blind_passes_and_is_counted_per_reason():
    records = [
        blind("T1", reason_kind="trap", boss=["Adds 3 to Nothing"]),
        blind("T2", reason_kind="trap", boss=["Adds 4 to Nothing"]),
        blind("S1", group="g2", reason_kind="shield", optimistic=["Adds 5 to Nothing"]),
        record("A", boss=["Adds 10 to Life"]),
    ]
    result = check.check_records(records, pobs())
    assert result.unchanged == []
    assert result.stale_stand_blind == []
    assert [item.line for item in result.stand_blind] == ["T1", "T2", "S1"]
    assert [item.reason_kind for item in result.stand_blind] == ["trap", "trap", "shield"]
    assert check.exit_code(result) == 0
    rows = {row.group: row for row in result.rows}
    assert (rows["g1"].changed, rows["g1"].stand_blind) == (1, 2)
    assert (rows["g2"].changed, rows["g2"].stand_blind) == (0, 1)
    text = check.format_stand_blind(result)
    assert "trap: 2" in text and "shield: 1" in text
    assert "T1" in text and "S1" in text


def test_unchanged_record_without_stand_blind_still_fails_next_to_a_stand_blind_one():
    result = check.check_records([blind("T", boss=["Adds 3 to Nothing"]), record("B", boss=["Adds 3 to Nothing"])], pobs())
    assert [item.line for item in result.unchanged] == ["B"]
    assert [item.line for item in result.stand_blind] == ["T"]
    assert check.exit_code(result) == 1


def test_stand_blind_record_that_moves_an_output_is_stale_and_fails():
    result = check.check_records([blind("X", boss=["Adds 10 to Life"])], pobs())
    assert [item.line for item in result.stale_stand_blind] == ["X"]
    assert result.unchanged == [] and result.stand_blind == []
    assert check.exit_code(result) == 1
    assert "X" in check.format_stale_stand_blind(result)


def test_table_has_a_stand_blind_column_after_new_kind():
    result = check.check_records([blind("T", group="ramp", boss=["Adds 3 to Nothing"])], pobs())
    lines = check.format_table(result).splitlines()
    assert "stand-blind" in lines[0]
    assert any(line.split()[:6] == ["ramp", "1", "0", "0", "0", "1"] for line in lines)


def test_main_passes_with_stand_blind_only_and_prints_the_counts(tmp_path: Path, capsys):
    folder = tmp_path / "stands"
    (folder / "rows").mkdir(parents=True)
    for slug in ("spark", "smite", "summon_raging_spirits"):
        (folder / f"{slug}-s4.pob.txt").write_text("code", encoding="utf-8")
        (folder / "rows" / f"{slug}-s4.json").write_text("{}", encoding="utf-8")
    marks = tmp_path / "marks.json"
    marks.write_text(json.dumps([blind("T", boss=["Adds 3 to Nothing"], reason_kind="totem")]), encoding="utf-8")
    code = check.main([str(marks), "--stand-folder", str(folder)], open_pob=lambda stand_type, path: pobs()[stand_type])
    out = capsys.readouterr().out
    assert code == 0
    assert "totem: 1" in out
    assert out.rstrip().splitlines()[-1].startswith("done in ")
