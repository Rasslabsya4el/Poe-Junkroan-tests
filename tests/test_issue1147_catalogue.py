"""#1147 unit 2: the catalogue record (PoB-free).

One JSON line per (bundle, stand) measurement: the fields of the issue, canonical text, gain arithmetic, the
does_not_fit shape, and an append-only writer. No PoB is started; `import_code_for` is tried on a fake PoB that only
has `export_xml`. Expected values come from literals and from the spec, not from the code under test.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from junkroan.optimizer.catalogue import (
    CATALOGUE_PATH,
    CatalogueRecord,
    append,
    import_code_for,
    same_apart_from_seconds,
    stand_sha256,
)
from junkroan.pob.session import decode_import_code

FIELDS = {
    "bundle", "edge", "stand", "stand_sha256", "metric", "base_value", "value", "gain", "verdict", "reason",
    "seconds", "seed", "passes", "commit", "import_code",
}

MEASURED = dict(
    bundle=["notable:a", "notable:b"],
    edge={"from": "notable:a", "to": "notable:b", "kind": "pays", "var": "x", "via": "y", "pob": "z"},
    stand="spark-s4.pob.txt",
    stand_sha256="ab" * 32,
    metric="CombinedDPS",
    base_value=1000.0,
    value=1100.0,
    verdict="take",
    reason="CombinedDPS up 10% on spark",
    seconds=42.5,
    seed=4,
    passes=2,
    commit="c295f035",
    import_code="eJzLSM3JyQcABiwCFQ",
)

DOES_NOT_FIT = dict(
    bundle=["asc:other-ascendancy-node"],
    edge=None,
    stand="smite-s4.pob.txt",
    stand_sha256="cd" * 32,
    metric="CombinedDPS",
    base_value=None,
    value=None,
    verdict="does_not_fit",
    reason="ascendancy node belongs to another ascendancy",
    seconds=0,
    seed=4,
    passes=0,
    commit="c295f035",
    import_code=None,
)


def _record(**overrides) -> CatalogueRecord:
    return CatalogueRecord(**{**MEASURED, **overrides})


def test_line_has_every_field_of_the_issue() -> None:
    parsed = json.loads(_record().to_line())
    assert set(parsed) == FIELDS
    assert parsed["bundle"] == ["notable:a", "notable:b"]
    assert parsed["stand"] == "spark-s4.pob.txt"
    assert parsed["gain"] == pytest.approx(0.1)


def test_line_is_canonical_json_with_sorted_keys_and_no_whitespace() -> None:
    line = _record().to_line()
    assert "\n" not in line
    assert line == json.dumps(json.loads(line), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def test_same_bundle_stand_and_seed_give_the_same_line_apart_from_seconds() -> None:
    first = _record(seconds=42.5).to_line()
    second = _record(seconds=44.1).to_line()
    assert first != second
    assert same_apart_from_seconds(first, second)


def test_a_different_value_is_not_the_same_apart_from_seconds() -> None:
    assert not same_apart_from_seconds(_record().to_line(), _record(value=1150.0).to_line())


def test_gain_is_relative_to_base_value() -> None:
    assert _record(base_value=1000.0, value=1100.0).gain == pytest.approx(0.1)
    assert _record(base_value=1000.0, value=900.0).gain == pytest.approx(-0.1)


def test_gain_is_null_for_base_value_zero_without_raising() -> None:
    record = _record(base_value=0.0, value=5.0)
    assert record.gain is None
    assert json.loads(record.to_line())["gain"] is None


def test_a_missing_field_raises() -> None:
    kwargs = dict(MEASURED)
    del kwargs["stand"]
    with pytest.raises(TypeError):
        CatalogueRecord(**kwargs)
    with pytest.raises(ValueError):
        _record(stand=None)


def test_bundle_must_be_sorted() -> None:
    with pytest.raises(ValueError):
        _record(bundle=["notable:b", "notable:a"])


def test_does_not_fit_record_has_the_null_shape() -> None:
    parsed = json.loads(CatalogueRecord(**DOES_NOT_FIT).to_line())
    assert set(parsed) == FIELDS
    assert parsed["verdict"] == "does_not_fit"
    assert parsed["value"] is None
    assert parsed["base_value"] is None
    assert parsed["gain"] is None
    assert parsed["import_code"] is None
    assert parsed["seconds"] == 0


def test_does_not_fit_with_a_value_raises() -> None:
    with pytest.raises(ValueError):
        CatalogueRecord(**{**DOES_NOT_FIT, "value": 1000.0, "base_value": 1000.0})


def test_unknown_verdict_and_metric_raise() -> None:
    with pytest.raises(ValueError):
        _record(verdict="maybe")
    with pytest.raises(ValueError):
        _record(metric="TotalDPS")


def test_append_writes_one_line_per_call_and_each_line_parses_back(tmp_path) -> None:
    path = tmp_path / "artifacts" / "catalogue" / "day1.jsonl"
    first = _record()
    second = CatalogueRecord(**DOES_NOT_FIT)
    append(path, first)
    append(path, second)
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0]) == json.loads(first.to_line())
    assert json.loads(lines[1]) == json.loads(second.to_line())


def test_catalogue_path_is_the_day1_file_under_artifacts() -> None:
    assert CATALOGUE_PATH.parts[-3:] == ("artifacts", "catalogue", "day1.jsonl")


def test_stand_sha256_is_the_sha256_of_the_file_bytes(tmp_path) -> None:
    stand = tmp_path / "stand.pob.txt"
    stand.write_bytes(b"abc")
    assert stand_sha256(stand) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    assert stand_sha256(stand) == hashlib.sha256(b"abc").hexdigest()


class _FakePoB:
    def __init__(self, xml: str) -> None:
        self._xml = xml

    def export_xml(self) -> str:
        return self._xml


def test_import_code_for_encodes_the_export_xml() -> None:
    xml = "<PathOfBuilding><Build level=\"90\" className=\"Witch\"/></PathOfBuilding>"
    assert decode_import_code(import_code_for(_FakePoB(xml))) == xml
