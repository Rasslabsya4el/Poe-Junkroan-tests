"""scripts/progress.py without PoB: the benchmark-measured stage rows (coverage, stability) and the
per-reference standing it derives from artifacts/benchmark/*/results.json, plus the tracker rows
(#1's sub-issues, open issues by triage label) against a faked `gh` (issue #30)."""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import progress  # noqa: E402
from progress import GhUnavailable, report, tracker_rows  # noqa: E402

ROADMAP = """## Phase 7. Prototype

### State

- Updated: test.
{marker}

### Work order

#### 7.1 Pipeline architecture freeze (target: 4-6 days)

- [x] 7.1a done
- [~] 7.1b in flight
- [ ] 7.1 exit

#### 7.2 Archetype campaign (target: 2 weeks)

- [x] The readback rule landed
- [ ] Brand count derived (D57 rule 1): the skill's attach base
      and a wrapped continuation line that is not an item
- [ ] Corpse supply: for corpse-fed skills

#### 7.3 Stability (target: 1 week)

- [ ] Spread per reference

#### 7.4 Acceptance

- [ ] All fixtures x 3 seeds

## Later
"""


def roadmap(marker: str = "") -> str:
    return ROADMAP.format(marker=f"- Runs count from: {marker}" if marker else "")


def make_row(slug, seed, ratio, *, variant="", audit_errors=0, violation=0.0, ours=1000.0, ok=True):
    return {"ok": ok, "slug": slug, "seed": seed, "variant": variant, "ratio_lane": ratio,
            "audit_errors": audit_errors, "ours": ours,
            "stages": [{"name": "final", "value": ours, "violation": violation}]}


def make_repo(tmp_path, slugs, runs):
    """slugs -> empty fixtures; runs = {stamp: [row, ...]} -> artifacts/benchmark/<stamp>."""
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir(exist_ok=True)
    for slug in slugs:
        (fixtures / f"{slug}.pob.txt").write_text("", encoding="utf-8")
    bench = tmp_path / "benchmark"
    bench.mkdir(exist_ok=True)
    for stamp, rows in runs.items():
        (bench / stamp).mkdir()
        (bench / stamp / "results.json").write_text(json.dumps(rows), encoding="utf-8")
    return fixtures, bench


def stage(stages, name):
    return next(s for s in stages if s["stage"] == name)


def test_three_seeds_give_median_spread_and_coverage(tmp_path):
    fixtures, bench = make_repo(tmp_path, ["cold_dot"], {
        "20260301-0900": [make_row("cold_dot", s, r) for s, r in [(1, 1.1), (2, 1.3), (3, 1.2)]],
    })
    stages, refs, _ = report(roadmap(), fixtures, bench)
    assert refs[0]["median"] == 1.2 and refs[0]["min"] == 1.1 and refs[0]["max"] == 1.3
    assert abs(refs[0]["spread"] - 0.2) < 1e-9 and refs[0]["status"] == "covered"
    assert stage(stages, "7.2 coverage")["done"] == 1
    assert stage(stages, "7.3 stability")["done"] == 0  # spread 20 points > 10
    assert stage(stages, "7.3 stability")["of"] == 1


def test_the_state_file_carries_the_marker_instead_of_the_roadmap(tmp_path):
    fixtures, bench = make_repo(tmp_path, ["spark"], {
        "20260301-0900": [make_row("spark", s, 1.5) for s in (1, 2, 3)],
    })
    live = "# State\n\n- Runs count from: 20260302-0000\n"
    stages, refs, state = report(roadmap(), fixtures, bench, state=live)
    assert state == live and refs[0]["status"] == "no run"
    assert stage(stages, "7.2 coverage")["note"] == "runs since 20260302-0000"


def test_latest_three_seed_run_wins_over_an_older_one(tmp_path):
    fixtures, bench = make_repo(tmp_path, ["smite"], {
        "20260301-0900": [make_row("smite", s, 1.5) for s in (1, 2, 3)],
        "20260302-1100": [make_row("smite", s, r) for s, r in [(1, 0.8), (2, 0.85), (3, 0.9)]],
    })
    _stages, refs, _ = report(roadmap(), fixtures, bench)
    assert refs[0]["run"] == "20260302-1100"
    assert refs[0]["median"] == 0.85 and refs[0]["status"] == "below author"


def test_the_marker_excludes_older_runs(tmp_path):
    fixtures, bench = make_repo(tmp_path, ["spark"], {
        "20260301-0900": [make_row("spark", s, 1.5) for s in (1, 2, 3)],
    })
    stages, refs, _ = report(roadmap("20260302-0000"), fixtures, bench)
    assert refs[0]["status"] == "no run"
    assert stage(stages, "7.2 coverage")["note"] == "runs since 20260302-0000"
    assert stage(stages, "7.2 coverage")["done"] == 0


def test_a_variant_row_with_a_better_key_wins_the_seed(tmp_path):
    rows = []
    for seed in (1, 2, 3):
        rows.append(make_row("winter_orb", seed, 3.0, audit_errors=2, ours=9e6))  # louder but dirty
        rows.append(make_row("winter_orb", seed, 1.1, variant="no Eldritch Battery"))
    fixtures, bench = make_repo(tmp_path, ["winter_orb"], {"20260301-0900": rows})
    _stages, refs, _ = report(roadmap(), fixtures, bench)
    assert refs[0]["median"] == 1.1 and refs[0]["errors"] == 0 and refs[0]["status"] == "covered"


def test_an_infeasible_seed_is_not_clean_and_blocks_the_reference(tmp_path):
    fixtures, bench = make_repo(tmp_path, ["impale_ballista"], {
        "20260301-0900": [make_row("impale_ballista", 1, 1.4), make_row("impale_ballista", 2, 1.5),
                          make_row("impale_ballista", 3, 1.6, violation=0.523)],
    })
    stages, refs, _ = report(roadmap(), fixtures, bench)
    assert refs[0]["status"] == "infeasible" and refs[0]["seeds"] == 2 and refs[0]["median"] is None
    assert refs[0]["measured"] is True  # measured, but not covered
    assert stage(stages, "7.2 coverage")["done"] == 0
    assert stage(stages, "7.3 stability")["of"] == 1 and stage(stages, "7.3 stability")["done"] == 0


def test_a_run_with_fewer_than_three_seeds_reports_one_seed_only(tmp_path):
    fixtures, bench = make_repo(tmp_path, ["arc_archmage", "pyroclast_mine"], {
        "20260301-0900": [make_row("arc_archmage", 1, 0.87),
                          make_row("pyroclast_mine", 1, 1.47, audit_errors=1)],
    })
    _stages, refs, _ = report(roadmap(), fixtures, bench)
    assert refs[0]["status"] == "1 seed only: 87%" and refs[0]["seeds"] == 1
    assert refs[1]["status"] == "1 seed only: 147% (audit errors)"
    assert refs[1]["seeds"] == 0 and refs[1]["errors"] == 1


def test_the_state_text_still_comes_through_report(tmp_path):
    fixtures, bench = make_repo(tmp_path, [], {})
    _stages, _refs, state = report(roadmap("20260302-0000"), fixtures, bench)
    assert state.startswith("- Updated: test.")


def test_excluded_words_skip_experimental_runs(tmp_path):
    fixtures, bench = make_repo(tmp_path, ["spark"], {
        "20260301-0900-full": [make_row("spark", s, 1.5) for s in (1, 2, 3)],
        "20260302-1100-loop-smoke": [make_row("spark", s, 0.8) for s in (1, 2, 3)],
    })
    text = roadmap().replace("- Updated: test.", "- Updated: test.\n- Runs excluded: loop, ablation (experimental)")
    _stages, refs, _ = report(text, fixtures, bench)
    assert refs[0]["run"] == "20260301-0900-full" and refs[0]["status"] == "covered"
    _stages, refs, _ = report(roadmap(), fixtures, bench)
    assert refs[0]["run"] == "20260302-1100-loop-smoke"


# --------------------------------------------------------- tracker (issue #30) ---


class _FakeCompleted:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout, self.stderr, self.returncode = stdout, stderr, returncode


def fake_gh(responses):
    """responses: {(arg, arg, ...) prefix: _FakeCompleted}. Matches a gh call by the longest
    registered prefix of its argument list (after the leading "gh")."""
    def _run(cmd, capture_output=True, text=True, timeout=30, check=False):
        assert cmd[0] == "gh"
        key = tuple(cmd[1:])
        for prefix, result in responses.items():
            if key[: len(prefix)] == prefix:
                return result
        raise AssertionError(f"unexpected gh call: {cmd}")
    return _run


def raising_gh(exc):
    def _run(cmd, capture_output=True, text=True, timeout=30, check=False):
        raise exc
    return _run


def test_sub_issues_api_gives_closed_over_total_and_names_the_open_ones(monkeypatch):
    monkeypatch.setattr(progress.subprocess, "run", fake_gh({
        ("api", f"repos/{progress.REPO}/issues/1/sub_issues"): _FakeCompleted(json.dumps([
            {"number": 2, "state": "closed", "title": "Acceptance run"},
            {"number": 3, "state": "open", "title": "Owner reads the top build"},
            {"number": 4, "state": "open", "title": "junkroan build on three requests"},
        ])),
        ("issue", "list"): _FakeCompleted(json.dumps([
            {"number": 10, "state": "OPEN", "labels": [{"name": "ready-for-agent"}], "title": "X"},
            {"number": 11, "state": "OPEN", "labels": [{"name": "needs-triage"}], "title": "Y"},
            {"number": 12, "state": "OPEN", "labels": [], "title": "Z"},
            {"number": 13, "state": "CLOSED", "labels": [{"name": "wontfix"}], "title": "W"},
        ])),
    }))
    rows = tracker_rows()
    acceptance = stage(rows, "#1 acceptance")
    assert acceptance["done"] == 1 and acceptance["of"] == 3
    assert acceptance["note"] == "Owner reads the top build; junkroan build on three requests"
    assert stage(rows, "ready-for-agent")["done"] == 1
    assert stage(rows, "needs-triage")["done"] == 1
    assert stage(rows, "wontfix")["done"] == 0  # only the OPEN #13 would count, and it's closed
    assert stage(rows, "no label")["done"] == 1
    assert stage(rows, "needs-info")["done"] == 0 and stage(rows, "needs-info")["of"] == 3


def test_an_empty_sub_issues_api_falls_back_to_the_body_task_list(monkeypatch):
    monkeypatch.setattr(progress.subprocess, "run", fake_gh({
        ("api", f"repos/{progress.REPO}/issues/1/sub_issues"): _FakeCompleted("[]"),
        ("issue", "list"): _FakeCompleted(json.dumps([
            {"number": 2, "state": "CLOSED", "labels": [], "title": "T2"},
            {"number": 3, "state": "OPEN", "labels": [], "title": "T3"},
        ])),
        ("issue", "view", "1"): _FakeCompleted(json.dumps({
            "body": "- [ ] whatever #2\n- [ ] whatever #3\n- [ ] untracked #99\n",
        })),
    }))
    rows = tracker_rows()
    acceptance = stage(rows, "#1 acceptance")
    # #2's real state (closed) overrides its stale " " checkbox; #99 isn't in the issue list.
    assert acceptance["done"] == 1 and acceptance["of"] == 3
    assert acceptance["note"] == "T3; "


def test_gh_missing_raises_gh_unavailable(monkeypatch):
    monkeypatch.setattr(progress.subprocess, "run", raising_gh(FileNotFoundError("gh: not found")))
    with pytest.raises(GhUnavailable):
        tracker_rows()


def test_gh_nonzero_exit_raises_gh_unavailable_with_its_stderr(monkeypatch):
    monkeypatch.setattr(progress.subprocess, "run", fake_gh({
        ("issue", "list"): _FakeCompleted("", stderr="HTTP 401: Bad credentials", returncode=1),
    }))
    with pytest.raises(GhUnavailable, match="Bad credentials"):
        tracker_rows()


def test_main_prints_one_offline_line_and_still_prints_everything_else(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(progress.subprocess, "run", raising_gh(FileNotFoundError("gh: not found")))
    rc = progress.main([])
    out = capsys.readouterr().out
    assert rc == 0
    assert "tracker rows unavailable" in out
    assert "7.2 coverage" in out and "7.3 stability" in out
    assert "#1 acceptance" not in out
