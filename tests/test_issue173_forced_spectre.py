"""#173 unit 1: `--spectre` grammar, `Skeleton.forced_spectres`, trace class `forced-missing:spectre:<id>` (PoB-free)."""

from __future__ import annotations

import json

import pytest

from junkroan.cli import main
from junkroan.optimizer.trace import forced_classes
from junkroan.pob.spectres import resolve_spectre, spectres
from junkroan.search.forced import forced_of
from junkroan.search.request import BuildRequest, expand

PYRO = "Metadata/Monsters/LeagueCrucible/Cold/Pyromaniac"


def _request(capsys, *argv: str) -> BuildRequest:
    assert main(["build", "--print-request", *argv]) == 0
    return BuildRequest.from_dict(json.loads(capsys.readouterr().out))


def _expand(capsys, *argv: str):
    return expand(_request(capsys, "--max-builds", "99", *argv))


def test_name_and_id_resolve_to_the_same_id() -> None:
    assert PYRO in spectres()
    assert resolve_spectre("Pyromaniac") == PYRO == resolve_spectre(PYRO) == resolve_spectre("Forged Frostbearer")
    assert resolve_spectre("pyromaniac") == PYRO
    assert resolve_spectre("Nonsense") is None


def test_a_repeated_name_picks_the_first_id_in_the_corpus_file() -> None:
    ids = [i for i, n in spectres().items() if n == "Necromancer"]
    assert len(ids) > 1
    assert resolve_spectre("Necromancer") == ids[0]


def test_flag_reaches_the_skeleton(capsys) -> None:
    for spec in ("Pyromaniac", PYRO):
        exp = _expand(capsys, "--skill", "Raise Spectre", "--ascendancy", "Necromancer", "--spectre", spec)
        assert exp.problems == [], exp.problems
        assert [v.skeleton.forced_spectres for v in exp.validations] == [[PYRO]]
        assert forced_of(exp.validations[0].skeleton)["spectres"] == [PYRO]
        assert f"fixed spectre: {spec}" in exp.echo


def test_unknown_spectre_is_rejected(capsys) -> None:
    exp = _expand(capsys, "--skill", "Raise Spectre", "--ascendancy", "Necromancer", "--spectre", "Nonsense")
    assert "unknown spectre 'Nonsense'" in exp.problems


def test_raise_spectre_without_the_flag_is_rejected(capsys) -> None:
    exp = _expand(capsys, "--skill", "Raise Spectre", "--ascendancy", "Necromancer")
    assert any("--spectre" in p for p in exp.problems) and not exp.ok


def test_the_flag_with_another_skill_is_rejected(capsys) -> None:
    exp = _expand(capsys, "--skill", "Fireball", "--ascendancy", "Elementalist", "--spectre", "Pyromaniac")
    assert any("--spectre" in p and "Raise Spectre" in p for p in exp.problems) and not exp.ok


def _xml(*ids: str) -> str:
    return "<PathOfBuilding><Build>" + "".join(f'<Spectre id="{i}"/>' for i in ids) + "</Build></PathOfBuilding>"


def test_trace_class_both_ways() -> None:
    forced = {"spectres": [PYRO]}
    assert forced_classes({"xml": _xml()}, forced) == {f"forced-missing:spectre:{PYRO}"}
    assert forced_classes({"xml": _xml("Metadata/Monsters/Other")}, forced) == {f"forced-missing:spectre:{PYRO}"}
    assert forced_classes({"xml": _xml(PYRO)}, forced) == {"forced:kept"}
    assert forced_classes({"xml": _xml()}, {"spectres": []}) == {"forced:kept"}


# -- wiring: Skeleton.apply / skill_payload ------------------------------------------------------------------------

SECOND = "Metadata/Monsters/BloodChieftain/MonkeyChiefBloodEnrage"


def _skeleton(spectres: list[str]):
    from junkroan.search.skeleton import Skeleton

    return Skeleton(class_name="Witch", ascendancy="Necromancer", main_link=["Raise Spectre"], forced_spectres=spectres)


def test_payload_carries_the_spectre_only_when_forced() -> None:
    plain = _skeleton([]).skill_payload()
    assert "spectres" not in plain and "main_skill_minion" not in plain
    forced = _skeleton([PYRO]).skill_payload()
    assert forced["spectres"] == [PYRO] and forced["main_skill_minion"] == {"Raise Spectre": PYRO}
    assert {k: v for k, v in forced.items() if k not in ("spectres", "main_skill_minion")} == plain


@pytest.mark.pob
def test_apply_writes_the_spectre_and_pob_computes_it(tmp_path) -> None:
    from xml.etree import ElementTree as ET

    from junkroan.pob.session import PobSession

    def run(spectre_id: str) -> tuple[str, float, float]:
        with PobSession(run_id="test-173-u3-apply", artifacts_root=tmp_path) as pob:
            _skeleton([spectre_id]).apply(pob)
            stats = pob.stats(["TotalDPS", "FullDPS", "Minion.TotalDPS"])
            build = ET.fromstring(pob.export_xml())
        assert [s.get("id") for s in build.find("Build").findall("Spectre")] == [spectre_id]
        gems = [g for g in build.iter("Gem") if g.get("nameSpec") == "Raise Spectre"]
        assert gems and all(g.get("skillMinion") == spectre_id for g in gems)
        total = float(stats.get("Minion.TotalDPS") or stats.get("TotalDPS") or 0.0)
        return spectre_id, total, float(stats.get("FullDPS") or 0.0)

    first, second = run(PYRO), run(SECOND)
    print("TotalDPS/FullDPS", first, second)
    assert first[1] > 0 and first[2] > 0, first
    assert second[1] > 0 and second[2] > 0, second
    assert first[1] != second[1]
