"""#534: a recorded transcript depends on the build and the commit only."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from junkroan.optimizer.config_rules import clear_parse_mods_cache, parse_mods_batch  # noqa: E402
from junkroan.recording_pob import canonical  # noqa: E402
import replay_bench  # noqa: E402


class FakePob:
    def parse_mods(self, lines):
        return [{"line": line, "ok": True, "mods": []} for line in lines]


def _transcript(path: Path) -> list[str]:
    return [json.loads(line)["method"] for line in path.read_text(encoding="utf-8").splitlines()]


def _replay(tmp_path: Path, name: str, begin) -> list[str]:
    target = tmp_path / f"{name}.calls.jsonl"
    rec = begin(FakePob(), target)
    parse_mods_batch(rec, ["25% chance to gain a power charge when you block spell damage"])
    rec._rec_file.close()
    return _transcript(target)


def test_second_build_in_one_process_records_parse_mods(tmp_path):
    clear_parse_mods_cache()
    first = _replay(tmp_path, "a", replay_bench.begin_recording)
    second = _replay(tmp_path, "b", replay_bench.begin_recording)
    assert first == second == ["parse_mods"]


def test_without_clear_the_second_transcript_lacks_the_call(tmp_path):
    from junkroan.recording_pob import RecordingPob

    clear_parse_mods_cache()
    plain = lambda pob, target: RecordingPob(pob, target)  # noqa: E731
    _replay(tmp_path, "a", plain)
    assert _replay(tmp_path, "b", plain) == []


def _xml(attrs: str, value: str = "1") -> str:
    return f'<PathOfBuilding><Build {attrs} level="{value}"/>' + "<Items>" + "x" * 300 + "</Items></PathOfBuilding>"


def test_attribute_order_gives_one_sha_and_a_changed_value_another():
    one = canonical(_xml('className="Witch" ascendClassName="Elementalist"'))
    two = canonical(_xml('ascendClassName="Elementalist" className="Witch"'))
    other = canonical(_xml('className="Witch" ascendClassName="Elementalist"', value="2"))
    assert one["sha256"] == two["sha256"]
    assert one["sha256"] != other["sha256"]


def _sections(order: list[str]) -> str:
    parts = {
        "Build": '<Build level="90"/>',
        "Config": '<Config><ConfigSet id="1"><Input name="b" boolean="true"/><Input name="a" number="2"/></ConfigSet></Config>',
        "Items": '<Items><ItemSet id="1"><Slot name="Belt" itemId="3"/><Slot name="Weapon 1" itemId="1"/></ItemSet></Items>',
        "Skills": '<Skills><Skill><Gem name="Fireball"/><Gem name="Spell Echo"/></Skill></Skills>',
    }
    return "<PathOfBuilding>" + "".join(parts[name] for name in order) + "<Notes>" + "x" * 300 + "</Notes></PathOfBuilding>"


def test_table_ordered_children_give_one_sha_and_gem_order_stays_meaningful():
    one = canonical(_sections(["Build", "Config", "Items", "Skills"]))
    shuffled = (_sections(["Skills", "Items", "Build", "Config"])
                .replace('<Input name="b" boolean="true"/><Input name="a" number="2"/>',
                         '<Input name="a" number="2"/><Input name="b" boolean="true"/>')
                .replace('<Slot name="Belt" itemId="3"/><Slot name="Weapon 1" itemId="1"/>',
                         '<Slot name="Weapon 1" itemId="1"/><Slot name="Belt" itemId="3"/>'))
    gems_swapped = _sections(["Build", "Config", "Items", "Skills"]).replace(
        '<Gem name="Fireball"/><Gem name="Spell Echo"/>', '<Gem name="Spell Echo"/><Gem name="Fireball"/>')
    assert one["sha256"] == canonical(shuffled)["sha256"]
    assert one["sha256"] != canonical(gems_swapped)["sha256"]
