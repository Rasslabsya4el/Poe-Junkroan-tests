from junkroan.optimizer.anoint_step import pick_anoint, repick_anoint


def make(scores):
    calls = []

    def measure(name):
        calls.append(name)
        return scores[name]

    return measure, calls


def test_picks_highest():
    m, calls = make({None: 10, "a": 11, "b": 15, "c": 12})
    p = pick_anoint(["a", "b", "c"], m)
    assert p.chosen == "b" and p.score_before == 10 and p.score_after == 15
    assert p.measured == 3 and [n for n, _ in p.ranked] == ["b", "c", "a"]


def test_none_when_nothing_beats():
    m, _ = make({None: 10, "a": 10, "b": 9})
    p = pick_anoint(["a", "b"], m)
    assert p.chosen is None and p.score_after == p.score_before == 10


def test_exclude_never_measured():
    m, calls = make({None: 1, "a": 2, "b": 3})
    p = pick_anoint(["a", "b"], m, exclude={"b"})
    assert "b" not in calls and p.chosen == "a"
    assert p.measured == len([c for c in calls if c is not None]) == 1


def test_ties_keep_candidate_order():
    m, _ = make({None: 0, "a": 5, "b": 5})
    assert pick_anoint(["a", "b"], m).chosen == "a"


def test_repick_limits_and_switches():
    names = [f"n{i}" for i in range(15)]
    sc = {None: 0, **{n: i + 1 for i, n in enumerate(names)}, "cur": 100}
    first = pick_anoint(names, make(sc)[0])
    m, calls = make(sc)
    p = repick_anoint(first, "n0", m, top=3)
    assert len([c for c in calls if c is not None]) <= 4
    assert p.chosen == "n14"
    m, calls = make(sc)
    p = repick_anoint(first, "cur", m, top=3)
    assert p.chosen == "cur" and p.measured == 4


def test_repick_keeps_current_when_best():
    m, _ = make({None: 0, "a": 5, "b": 3, "cur": 9})
    first = pick_anoint(["a", "b"], make({None: 0, "a": 5, "b": 3})[0])
    assert repick_anoint(first, "cur", m).chosen == "cur"


def test_repick_none_when_all_fall():
    first = pick_anoint(["a", "b"], make({None: 0, "a": 5, "b": 3})[0])
    m, _ = make({None: 10, "a": 5, "b": 3, "cur": 10})
    p = repick_anoint(first, "cur", m)
    assert p.chosen is None and p.score_after == 10


# ---- #432 unit 5: the replay feeds the step the delivered build's raw, which the export XML stores indented ----------

XML_AMULET = "\n\t\t\tRarity: RARE\n\t\t\tRandom 4\n\t\t\tCitrine Amulet\n\t\t\tCrafted: true\n\t\t\tItem Level: 70\n\t\t\tImplicits: 1\n\t\t\t+20 to Strength and Dexterity\n"


def _step_on(raw: str, monkeypatch):
    """`BuildPipeline._anoint_step` on a stub pipeline: what it logs and which notables it measured."""

    from types import SimpleNamespace

    from junkroan.optimizer import pipeline as pipeline_module
    from junkroan.optimizer.anoint_candidates import Candidate

    candidates = [Candidate(n, i, ("Clear", "Clear", "Clear"), "Clear") for i, n in enumerate(("Heart of Oak", "Whispers of Doom"), 100)]
    monkeypatch.setattr(pipeline_module, "anoint_candidates", lambda _oil: candidates)
    logs, measured = [], []
    loot = SimpleNamespace(current_raw={"Amulet": raw}, uniques={})

    def measurer(plain, names, label="anoint", classes=None):
        measured.extend(names)
        scores = {None: SimpleNamespace(value=1.0), **{n: SimpleNamespace(value=2.0) for n in names}}
        return (lambda name: scores[name].value), scores

    stub = SimpleNamespace(
        log=logs.append, rails=SimpleNamespace(anoint=SimpleNamespace(oil_max="Black")), _amulet_holder=pipeline_module.BuildPipeline._amulet_holder,
        _anoint_exclude=lambda _c: set(), _anoint_classes=lambda: {}, _anoint_trace_generated=lambda *_a, **_k: None,
        _set_amulet_anoint=lambda *_a: True, _record=lambda *_a: None, _anoint_measurer=measurer, _step_start=lambda *a, **k: None,
    )
    pipeline_module.BuildPipeline._anoint_step(stub, SimpleNamespace(stages=[]), SimpleNamespace(), loot)
    return logs, measured


def test_xml_shaped_amulet_raw_is_skipped_by_the_step(monkeypatch) -> None:
    """The defect: line 3 of the XML text is the item's name, so the step skipped (no PoB call, no TRACE count)."""

    logs, measured = _step_on(XML_AMULET, monkeypatch)
    assert measured == [] and any("cannot be anointed" in line for line in logs)


def test_compact_raw_makes_the_delivered_amulet_measurable(monkeypatch) -> None:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from replay_bench import compact_raw

    from junkroan.optimizer.anoint_line import anoint_of, apply_anoint

    raw = compact_raw(XML_AMULET)
    assert raw.splitlines()[:3] == ["Rarity: RARE", "Random 4", "Citrine Amulet"] and raw == compact_raw(raw)
    logs, measured = _step_on(raw, monkeypatch)
    assert measured == ["Heart of Oak", "Whispers of Doom"] and not any("skipped" in line for line in logs)
    assert anoint_of(apply_anoint(raw, "Heart of Oak")) == "Heart of Oak" and "Implicits: 2" in apply_anoint(raw, "Heart of Oak")


def test_the_output_class_reads_an_anoint_from_the_indented_export_text() -> None:
    from junkroan.optimizer.anoint_line import anoint_of
    from junkroan.optimizer.trace import output_counts

    xml_raw = XML_AMULET.replace("\t\t\tImplicits: 1\n", "\t\t\tImplicits: 2\n\t\t\t{enchant}{crafted}Allocates Heart of Oak\n")  # the line as PoB exports it
    assert anoint_of(xml_raw) == "Heart of Oak" and anoint_of("{enchant}{crafted}Allocates Heart of Oak") == "Heart of Oak"
    counts = output_counts([xml_raw], [])
    assert counts.get("anoint") == 1 and any(c.startswith("oil:") for c in counts)
