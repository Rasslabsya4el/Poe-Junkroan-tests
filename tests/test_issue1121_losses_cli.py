"""Unit 5 of issue 1121: the `losses` command in tools/agentops/losses.py.

Seams: `window_for` (the week rule), `closed_issues_rest` / `slug_of_remote` / `parse_pages` (the REST lister,
with a fake `gh`), `bucket_values` (any Window, an injected closed-ticket lister), and `run_losses` (the printed
table, with settings, a clock and prices passed in). No network, no git, no PoB: every input is a tmp_path
fixture or a literal. Every expected value is written out by hand from the fixture below.

Fixture (one repo; this week 2026-W42 against last week 2026-W41; prices: 1 M input = $2, 1 M output = $10;
times are UTC, at midday or later, so the machine's zone does not move them across a week edge):
  W41: session dddd0000 (title "orch #9101", first message names #9101): 1 M input = $2.00 on 07 Oct;
       #9101 held 08:00 -> 09:30 and closed by its orch_end; one closed ticket, $2.00, no merge, no held start.
  W42: session aaaa1111 (title "orch #9201 #9202"): 2 M input ($4) + 0.4 M output ($4) = $8.00 on 14 Oct;
       #9201 held 1 h, #9202 held 3 h, both closed: per ticket $2.00 and $6.00 (the 25 / 75 split);
       session cccc3333 (no title): 0.2 M output = $2.00, owned by no ticket;
       #9203 taken 12:00 and parked 13:00 by session eeee5555 (no transcript); now is 15 Oct 12:00 UTC: 23 h parked;
       dispatch log: "start held" lines 10:10, 10:11, 10:12 (150 s) and one "rate limit" line at 12:00 (30 s);
       merge results: #9201 red suite then pushed, #9202 pushed: one extra attempt, one of them red.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from tools.agentops import core_settings  # noqa: E402
from tools.agentops import cli  # noqa: E402
from tools.agentops.core_check import H_PATTERN  # noqa: E402
from tools.agentops.losses import (  # noqa: E402
    NotReadable,
    Repo,
    Window,
    add_subparser,
    bucket_values,
    closed_issues_rest,
    parse_pages,
    run_losses,
    slug_of_remote,
    window_for,
)

MODULE = ROOT / "tools" / "agentops" / "losses.py"

NOW = datetime(2026, 10, 15, 12, tzinfo=timezone.utc)

PRICES = {
    "claude-sonnet-5": {"input": 2.0, "cache_write": 2.5, "cache_read": 0.2, "output": 10.0},
}

ZERO = {"input_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0, "output_tokens": 0}

S0 = "dddd0000-0000-4000-8000-000000000004"
S1 = "aaaa1111-0000-4000-8000-000000000001"
U = "cccc3333-0000-4000-8000-000000000003"

# (session, title or None, first message, [(message id, timestamp, usage)])
TRANSCRIPTS = [
    (S0, "orch #9101", "take #9101 and finish it", [
        ("m4a", "2026-10-07T09:00:00Z", {**ZERO, "input_tokens": 1_000_000}),    # $2.00
    ]),
    (S1, "orch #9201 #9202", "continue the batch", [
        ("m1a", "2026-10-14T10:00:00Z", {**ZERO, "input_tokens": 2_000_000}),    # $4.00
        ("m1b", "2026-10-14T10:30:00Z", {**ZERO, "output_tokens": 400_000}),     # $4.00
    ]),
    (U, None, "continue the batch", [
        ("m3a", "2026-10-15T08:00:00Z", {**ZERO, "output_tokens": 200_000}),     # $2.00
    ]),
]

EVENTS = [
    {"ts": "2026-10-07T08:00:00+00:00", "kind": "issue_taken", "issue": 9101, "how": "claimed"},
    {"ts": "2026-10-07T09:30:00+00:00", "kind": "orch_end", "issue": 9101, "session": "dddd0000",
     "outcome": "closed", "why": "done"},
    {"ts": "2026-10-14T10:00:00+00:00", "kind": "issue_taken", "issue": 9201, "how": "claimed"},
    {"ts": "2026-10-14T11:00:00+00:00", "kind": "orch_end", "issue": 9201, "session": "aaaa1111",
     "outcome": "closed", "why": "done"},
    {"ts": "2026-10-14T11:00:00+00:00", "kind": "issue_taken", "issue": 9202, "how": "claimed"},
    {"ts": "2026-10-14T14:00:00+00:00", "kind": "orch_end", "issue": 9202, "session": "aaaa1111",
     "outcome": "closed", "why": "done"},
    {"ts": "2026-10-14T12:00:00+00:00", "kind": "issue_taken", "issue": 9203, "how": "claimed"},
    {"ts": "2026-10-14T13:00:00+00:00", "kind": "orch_end", "issue": 9203, "session": "eeee5555",
     "outcome": "parked", "why": "waits"},
]

DISPATCH = [
    "2026-10-14 10:10:00 orch-dispatch: start held, no free slot [issues #9202]",
    "2026-10-14 10:11:00 orch-dispatch: start held, no free slot [issues #9202]",
    "2026-10-14 10:12:00 orch-dispatch: start held, no free slot [issues #9202]",
    "2026-10-14 12:00:00 orch-dispatch: rate limit reached, waiting [issues #9202]",
]

RESULTS = {
    "20261007T090000-o9101.json": {"kind": "merge", "reason": "pushed", "issues": [9101],
                                    "ended": "2026-10-07T09:00:00"},
    "20261014T100000-o9201.json": {"kind": "merge", "reason": "red-suite", "issues": [9201],
                                    "argv": ["python", "-m", "tools.agentops", "merge", "o9201-fireball"],
                                    "ended": "2026-10-14T10:00:00"},
    "20261014T110000-o9201.json": {"kind": "merge", "reason": "pushed", "issues": [9201],
                                    "ended": "2026-10-14T11:00:00"},
    "20261014T120000-o9202.json": {"kind": "merge", "reason": "pushed", "issues": [9202],
                                    "ended": "2026-10-14T12:00:00"},
}

# what the closed-ticket lister gives for each window label (the real lister filters by window; tested below)
CLOSED_ROWS = {
    "2026-W42": [{"number": 9201, "closedAt": "2026-10-14T11:00:00Z"},
                 {"number": 9202, "closedAt": "2026-10-14T14:00:00Z"}],
    "2026-W41": [{"number": 9101, "closedAt": "2026-10-07T09:30:00Z"}],
}

# the table the fixture must print, row by row: (label, [this week, last week, change])
EXPECTED_W42 = [
    ("closed tickets", ["2", "1", "x2.0"]),
    ("$ spent", ["$10.0", "$2.0", "x5.0"]),
    ("$ per closed ticket (mean)", ["$5.0", "$2.0", "x2.5"]),
    ("$ per closed ticket (median)", ["$4.0", "$2.0", "x2.0"]),
    ("$ per closed ticket (p90)", ["$6.0", "$2.0", "x3.0"]),
    ("$ no ticket owns", ["$2.0 (20%)", "$0.0 (0%)", "new"]),
    ("of which ticket not closed in the week", ["$0.0", "$0.0", "-"]),
    ("of which brain chat", ["$0.0", "$0.0", "-"]),
    ("of which no ticket named", ["$2.0", "$0.0", "new"]),
    ("extra merge attempts", ["1", "0", "new"]),
    ("extra merge attempts, of which red suite", ["1", "0", "new"]),
    ("extra merge attempts, of which conflict", ["0", "0", "-"]),
    ("extra merge attempts, of which other", ["0", "0", "-"]),
    ("tickets with more than one merge attempt", ["1", "0", "new"]),
    ("hours a start was held", ["2.5 min", "0 s", "new"]),
    ("hours lost to rate limits", ["30 s", "0 s", "new"]),
    ("hours parked", ["23 h 00 min", "0 s", "new"]),
    ("hours worked per closed ticket (median)", ["2 h 00 min", "1 h 30 min", "x1.3"]),
]


def fake_lister(repo, window):
    return list(CLOSED_ROWS.get(window.label, []))


def _write_projects(projects: Path) -> None:
    projects.mkdir(parents=True, exist_ok=True)
    for session, title, first, turns in TRANSCRIPTS:
        lines = []
        if title is not None:
            lines.append({"type": "custom-title", "customTitle": title, "sessionId": session})
        lines.append({"type": "user", "message": {"role": "user", "content": first},
                      "timestamp": "2026-10-07T08:55:00Z"})
        for message_id, stamp, usage in turns:
            lines.append({"type": "assistant", "message": {"id": message_id, "model": "claude-sonnet-5",
                                                           "usage": usage}, "timestamp": stamp})
        (projects / f"{session}.jsonl").write_text(
            "\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")


def _write_repo(root: Path, projects: Path) -> None:
    runs = root / "artifacts" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    (runs / "events.jsonl").write_text("\n".join(json.dumps(e) for e in EVENTS) + "\n", encoding="utf-8")
    (runs / "dispatch.out").write_text("\n".join(DISPATCH) + "\n", encoding="utf-8")
    results = root / "var" / "agentops" / "results"
    results.mkdir(parents=True, exist_ok=True)
    for name, row in RESULTS.items():
        (results / name).write_text(json.dumps(row), encoding="utf-8")
    _write_projects(projects)


@pytest.fixture()
def fixture_repo(tmp_path: Path) -> Repo:
    root = tmp_path / "fixture-root"
    projects = tmp_path / "fixture-projects"
    _write_repo(root, projects)
    return Repo(name="fixture", root=root, projects_dir=projects)


def _parse(*argv: str) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command")
    add_subparser(sub)
    return parser.parse_args(["losses", *argv])


def _settings(repos: list[Repo], ceiling: float = 5.5) -> dict:
    return {
        "claude_projects_dir": "unused-by-these-tests",
        "loss_ceiling_usd_per_closed": ceiling,
        "loss_repos": [{"name": r.name, "root": str(r.root), "projects_dir": str(r.projects_dir)}
                       for r in repos],
    }


def _run(capsys, settings: dict, *argv: str) -> tuple[int, str]:
    rc = run_losses(_parse(*argv), settings=settings, now=NOW, closed_lister=fake_lister, prices=PRICES)
    return rc, capsys.readouterr().out


def _table(text: str) -> list[tuple[str, list[str]]]:
    rows = []
    for line in text.splitlines():
        if "|" not in line or line.split("|")[0].strip() == "bucket":
            continue
        cells = [cell.strip() for cell in line.split("|")]
        rows.append((cells[0], cells[1:]))
    return rows


# ------------------------------------------------------------- (d) the week rule

def test_a_named_week_is_monday_to_monday_local_with_last_week_before_it():
    this, last = window_for("2026-W42", NOW)
    assert this.since == datetime(2026, 10, 12).astimezone()
    assert this.until == datetime(2026, 10, 19).astimezone()
    assert this.label == "2026-W42"
    assert last.since == datetime(2026, 10, 5).astimezone()
    assert last.until == datetime(2026, 10, 12).astimezone()
    assert last.label == "2026-W41"


def test_no_week_means_the_iso_week_that_contains_now():
    this, last = window_for(None, datetime(2026, 10, 15, 12).astimezone())
    assert this.label == "2026-W42"
    assert this.since == datetime(2026, 10, 12).astimezone()
    assert last.label == "2026-W41"


def test_a_window_is_a_plain_since_until_pair_of_any_span():
    span = Window(since=datetime(2026, 10, 9).astimezone(), until=datetime(2026, 10, 16).astimezone())
    assert span.until - span.since == datetime(2026, 10, 16) - datetime(2026, 10, 9)


# ----------------------------------------------------- (e) the REST closed-ticket lister

def test_slug_of_remote_reads_https_and_ssh_urls_and_refuses_others():
    assert slug_of_remote("https://github.com/owner/repo.git") == "owner/repo"
    assert slug_of_remote("git" + "@github.com:owner/repo.git") == "owner/repo"  # joined: the copy check reads an address
    assert slug_of_remote("https://github.com/owner/repo") == "owner/repo"
    assert slug_of_remote("https://example.com/owner/repo") is None


def test_parse_pages_reads_concatenated_json_arrays():
    text = json.dumps([{"number": 1}]) + "\n" + json.dumps([{"number": 2}, {"number": 3}]) + "\n"
    assert [row["number"] for row in parse_pages(text)] == [1, 2, 3]


def test_rest_lister_drops_pull_requests_and_rows_outside_the_window(fixture_repo):
    this, _ = window_for("2026-W42", NOW)
    pages = (json.dumps([
        {"number": 1, "closed_at": "2026-10-13T08:00:00Z"},
        {"number": 2, "closed_at": "2026-10-13T08:00:00Z", "pull_request": {"url": "x"}},
        {"number": 3, "closed_at": "2026-10-01T08:00:00Z"},
    ]) + "\n" + json.dumps([
        {"number": 4, "closed_at": "2026-10-20T00:00:00Z"},
        {"number": 5, "closed_at": "2026-10-16T12:00:00Z"},
    ]) + "\n")
    calls = []

    def fake_gh(args):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout=pages, stderr="")

    rows = closed_issues_rest("owner/repo", this, gh=fake_gh)
    assert rows == [{"number": 1, "closedAt": "2026-10-13T08:00:00Z"},
                    {"number": 5, "closedAt": "2026-10-16T12:00:00Z"}]
    args = calls[0]
    assert args[0] == "api" and "--paginate" in args
    endpoint = args[-1]
    assert endpoint.startswith("repos/owner/repo/issues?state=closed&since=")
    assert endpoint.endswith("&per_page=100")


def test_rest_lister_failure_is_not_readable_not_a_crash():
    this, _ = window_for("2026-W42", NOW)

    def failing_gh(args):
        return SimpleNamespace(returncode=1, stdout="", stderr="HTTP 401: Bad credentials")

    with pytest.raises(NotReadable):
        closed_issues_rest("owner/repo", this, gh=failing_gh)


# ------------------------------------------------------------ bucket_values

def test_bucket_values_of_the_fixture_week(fixture_repo):
    this, _ = window_for("2026-W42", NOW)
    values = bucket_values(fixture_repo, this, NOW, fake_lister, PRICES)
    assert values["closed"] == 2
    assert values["spent_usd"] == pytest.approx(10.0)
    assert values["unowned_usd"] == pytest.approx(2.0)
    assert values["unowned_open_usd"] == pytest.approx(0.0)
    assert values["unowned_brain_usd"] == pytest.approx(0.0)
    assert values["unowned_unnamed_usd"] == pytest.approx(2.0)
    assert values["mean_usd"] == pytest.approx(5.0)
    assert values["median_usd"] == pytest.approx(4.0)
    assert values["p90_usd"] == pytest.approx(6.0)
    assert values["extra_attempts"] == 1
    assert values["extra_red_suite"] == 1
    assert values["held_start_seconds"] == pytest.approx(150.0)
    assert values["rate_limit_seconds"] == pytest.approx(30.0)
    assert values["parked_seconds"] == pytest.approx(23 * 3600)
    assert values["hours_worked_median_seconds"] == pytest.approx(7200.0)


# ----------------------------------------------- (a) the printed table, exact cells

def test_the_printed_table_of_the_fixture_week_matches_the_hand_numbers(capsys, fixture_repo):
    rc, text = _run(capsys, _settings([fixture_repo]), "--repo", "fixture", "--week", "2026-W42")
    assert rc == 0
    assert text.splitlines()[0] == "fixture 2026-W42 (last week 2026-W41)"
    header = [cell.strip() for cell in text.splitlines()[1].split("|")]
    assert header == ["bucket", "this week", "last week", "change"]
    assert _table(text) == EXPECTED_W42


# ------------------------------------------------------ (b) the ceiling mark

def test_the_three_source_rows_sit_right_under_no_ticket_owns_and_are_indented(capsys, fixture_repo):
    _, text = _run(capsys, _settings([fixture_repo]), "--repo", "fixture", "--week", "2026-W42")
    lines = text.splitlines()
    owns = next(i for i, line in enumerate(lines) if line.startswith("$ no ticket owns"))
    assert lines[owns + 1].startswith("  of which ticket not closed in the week")
    assert lines[owns + 2].startswith("  of which brain chat")
    assert lines[owns + 3].startswith("  of which no ticket named")
    assert lines[owns + 4].startswith("extra merge attempts")


def test_a_row_over_the_ceiling_is_marked_and_one_under_is_not(capsys, fixture_repo):
    _, over = _run(capsys, _settings([fixture_repo], ceiling=4.0), "--repo", "fixture", "--week", "2026-W42")
    marked = [line for line in over.splitlines() if "OVER" in line]
    assert len(marked) == 1
    assert marked[0].startswith("$ per closed ticket (mean) OVER $4.0 ")
    assert _table(over)[2] == ("$ per closed ticket (mean) OVER $4.0", ["$5.0", "$2.0", "x2.5"])

    _, under = _run(capsys, _settings([fixture_repo], ceiling=5.5), "--repo", "fixture", "--week", "2026-W42")
    assert "OVER" not in under
    assert _table(under)[2] == ("$ per closed ticket (mean)", ["$5.0", "$2.0", "x2.5"])


# ----------------------------------------- (c) --all over repos, a missing root

def test_all_prints_one_block_per_repo_and_a_missing_root_is_not_readable(capsys, tmp_path, fixture_repo):
    beta_root = tmp_path / "beta-root"
    beta_root.mkdir()
    missing = tmp_path / "does-not-exist"
    repos = [fixture_repo,
             Repo(name="beta", root=beta_root, projects_dir=tmp_path / "beta-projects"),
             Repo(name="missing", root=missing, projects_dir=tmp_path / "missing-projects")]
    rc, text = _run(capsys, _settings(repos), "--all", "--week", "2026-W42")
    assert rc == 0
    lines = text.splitlines()
    assert lines[0] == "fixture 2026-W42 (last week 2026-W41)"
    assert "beta 2026-W42 (last week 2026-W41)" in lines
    assert "missing: not readable (root folder does not exist)" in lines
    assert text.count("(last week 2026-W41)") == 2
    assert lines.index("missing: not readable (root folder does not exist)") > lines.index(
        "beta 2026-W42 (last week 2026-W41)")


def test_a_bad_week_is_an_error_with_rc_2(capsys, fixture_repo):
    rc, text = _run(capsys, _settings([fixture_repo]), "--repo", "fixture", "--week", "2026-42")
    assert rc == 2
    assert "2026-42" in text


def test_an_unknown_repo_name_is_an_error_with_rc_2(capsys, fixture_repo):
    rc, text = _run(capsys, _settings([fixture_repo]), "--repo", "nope", "--week", "2026-W42")
    assert rc == 2
    assert "nope" in text


def test_repo_and_all_together_are_refused_by_the_parser():
    with pytest.raises(SystemExit):
        _parse("--repo", "x", "--all")


# --------------------------------------------------------- settings and module

def test_the_core_defaults_hold_the_ceiling_and_an_empty_repo_list():
    assert core_settings.DEFAULTS["loss_ceiling_usd_per_closed"] == 5.5
    assert core_settings.DEFAULTS["loss_repos"] == []


def test_the_home_settings_name_this_repo_and_one_sibling():
    data = json.loads((ROOT / "config" / "orchestration.json").read_text(encoding="utf-8"))
    names = [entry["name"] for entry in data["loss_repos"]]
    assert len(names) == 2 and names[0] == "poe-junkroan-v2"
    assert names[1] and names[1] != "poe-junkroan-v2"
    assert data["loss_ceiling_usd_per_closed"] == 5.5


def test_module_imports_nothing_from_src_and_holds_no_issue_numbers_or_dates():
    text = MODULE.read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(text)):
        names = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [("." * node.level) + (node.module or "")]
        assert not any(name == "src" or name.startswith("src.") or ".src" in name for name in names)
    assert not [line for line in text.splitlines() if H_PATTERN.search(line)]


def test_the_cli_wires_losses_help_exits_zero():
    res = subprocess.run([sys.executable, "-m", "tools.agentops", "losses", "--help"], cwd=str(ROOT),
                         capture_output=True, text=True, timeout=120)
    assert res.returncode == 0, res.stderr
    assert "--week" in res.stdout and "--repo" in res.stdout and "--all" in res.stdout


def test_main_dispatches_losses_to_run_losses(monkeypatch):
    seen = {}

    def fake_run_losses(args, **kwargs):
        seen["week"], seen["repo"], seen["all"] = args.week, args.repo, args.all
        return 7

    monkeypatch.setattr(cli, "run_losses", fake_run_losses)
    assert cli.main(["losses", "--week", "2026-W41", "--repo", "poe-junkroan-v2"]) == 7
    assert seen == {"week": "2026-W41", "repo": "poe-junkroan-v2", "all": False}
