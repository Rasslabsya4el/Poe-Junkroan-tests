"""tools/agentops/research.py: the reddit-URL rejection rule (requirement 2, ported from the
GPT-era harness's `good`, now removed, #65) -- a report from tooltips alone is a failed task -- and
(2026-09-26 follow-up, issue #46) that a model call which produced nothing is reported as an
explicit failure, never conflated with a rejected-but-real report."""

from __future__ import annotations

from pathlib import Path

from tools.agentops import ocserver
from tools.agentops.research import report_is_good, report_path_from_brief, run_research

# Reuses the fake `opencode serve` stand-in from test_agentops_ocserver.py: no real network call,
# no real opencode, same rule as every other agentops test.
from tests.test_agentops_ocserver import fake_server, make_client  # noqa: F401  (fake_server is a fixture)


def _long_report(extra: str = "") -> str:
    body = "See https://poewiki.net/wiki/Fireball for details. " * 60
    return body + extra


def test_report_without_reddit_url_is_rejected():
    text = _long_report()
    assert not report_is_good(text, require_reddit=True)


def test_report_with_reddit_url_is_accepted():
    text = _long_report("Also see https://www.reddit.com/r/PathOfExile/comments/abc123/ for a live report.")
    assert report_is_good(text, require_reddit=True)


def test_report_with_reddit_url_but_no_reddit_check_needed_still_accepted():
    text = _long_report()
    assert report_is_good(text, require_reddit=False)


def test_short_report_is_rejected_even_with_reddit_url():
    text = "Found it on https://www.reddit.com/r/x, not found for the rest."
    assert not report_is_good(text, require_reddit=True)


def test_report_path_from_brief_reads_the_named_target(tmp_path: Path):
    brief = tmp_path / "brief.md"
    brief.write_text(
        "Numbered questions here.\n\nWrite the report to `docs/research/2026-09-26-topic.md`.\n"
        "(a `docs/research/briefs/2026-09-26-topic.md` self-reference must be ignored)\n",
        encoding="utf-8",
    )
    target = report_path_from_brief(brief)
    assert target is not None
    assert target.as_posix().endswith("docs/research/2026-09-26-topic.md")


def _brief(tmp_path: Path, report_rel: str) -> Path:
    brief = tmp_path / "brief.md"
    brief.write_text(f"Numbered questions here.\n\nWrite the report to `{report_rel}`.\n", encoding="utf-8")
    return brief


def _wire_research(monkeypatch, fake_server, tmp_path: Path):
    """Bind run_research's opencode calls to the fake server, skip the real ~seconds-long poll,
    and keep the meter log inside tmp_path."""
    client = make_client(fake_server)
    monkeypatch.setattr(ocserver, "ensure", lambda **kw: client)
    monkeypatch.setattr(ocserver, "register", lambda *a, **kw: None)
    monkeypatch.setattr(ocserver, "unregister", lambda *a, **kw: None)
    monkeypatch.setattr(ocserver, "wait_for_idle", lambda *a, **kw: "finished")
    monkeypatch.setattr(ocserver, "read_opencode_config", lambda path=None: {
        "provider": {"codex-sale-oai": {"models": {"gpt-6-luna": {}}}}})
    log = tmp_path / "agentops.jsonl"
    return log


def test_run_research_reports_explicit_failure_on_zero_tokens(monkeypatch, fake_server, tmp_path):
    """The 2026-09-26 smoke run: a model call that produced no assistant reply (no `info.tokens`
    at all) must come back as a call failure, never as "no reddit.com URL" (which implies a real,
    just-rejected report)."""
    log = _wire_research(monkeypatch, fake_server, tmp_path)
    brief = _brief(tmp_path, "docs/research/smoke.md")
    # No messages at all in the fake store for this session: client.usage(...) -> None.

    result = run_research(brief, model="luna", directory=tmp_path, config_path=tmp_path / "opencode.json")
    from tools.agentops.metering import record_run
    record_run(kind="research", model="gpt-6-luna", outcome=result.reason, wall_s=result.elapsed_s,
              tokens_in=result.tokens_in, tokens_out=result.tokens_out, log_path=log)

    assert not result.accepted
    assert result.reason.startswith("model call failed:")
    assert "no reddit.com" not in result.reason
    assert result.tokens_in == 0 and result.tokens_out == 0


def test_run_research_reports_explicit_failure_on_provider_error(monkeypatch, fake_server, tmp_path):
    log = _wire_research(monkeypatch, fake_server, tmp_path)
    brief = _brief(tmp_path, "docs/research/smoke.md")

    # Create the session through the same client so the fake server knows its id, then attach an
    # error message directly (simulating opencode reporting a failed model call).
    client = make_client(fake_server)
    session = client.create_session(str(tmp_path), title="pre")
    fake_server.store["messages"][session["id"]] = [
        {"info": {"role": "assistant", "error": {"name": "ProviderModelNotFoundError", "message": "unknown model"}},
         "parts": []},
    ]
    monkeypatch.setattr(client, "create_session", lambda directory, title: session)
    monkeypatch.setattr(ocserver, "ensure", lambda **kw: client)

    result = run_research(brief, model="luna", directory=tmp_path, config_path=tmp_path / "opencode.json")

    assert not result.accepted
    assert result.reason.startswith("model call failed:")
    assert "unknown model" in result.reason


def test_run_research_still_rejects_a_real_report_without_reddit(monkeypatch, fake_server, tmp_path):
    """A real, complete reply that simply cites no reddit.com URL keeps its original reason --
    the fix must not turn every rejection into "model call failed"."""
    log = _wire_research(monkeypatch, fake_server, tmp_path)
    brief = _brief(tmp_path, "docs/research/smoke.md")

    client = make_client(fake_server)
    session = client.create_session(str(tmp_path), title="pre")
    fake_server.store["messages"][session["id"]] = [
        {"info": {"role": "assistant", "tokens": {"input": 500, "output": 300}},
         "parts": [{"type": "text", "text": _long_report()}]},
    ]
    monkeypatch.setattr(client, "create_session", lambda directory, title: session)
    monkeypatch.setattr(ocserver, "ensure", lambda **kw: client)

    result = run_research(brief, model="luna", directory=tmp_path, config_path=tmp_path / "opencode.json")

    assert not result.accepted
    assert result.reason == "no reddit.com URL"
    assert result.tokens_in == 500 and result.tokens_out == 300


# --- #488: `--no-reddit` ---

OLD_TAIL = (
    "\n\nUse live web search for every question; open Reddit threads (reddit.com / old.reddit.com), "
    "the wiki and forum posts, not tooltips alone. Report format, per question: the VERBATIM passages "
    "that answer it, each with its URL, the post date and who says it, the conditions the sources "
    "attach, where sources disagree both sides quoted, then one line 'what it says' with no "
    "recommendation. Do not write any other file: put the complete final report in this message, "
    "in markdown."
)


def _cli_kwargs(monkeypatch, tmp_path: Path, extra: list[str]) -> dict:
    from tools.agentops import cli
    seen: dict = {}

    def fake(brief, **kw):
        seen.update(kw)
        from tools.agentops.research import ResearchResult
        return ResearchResult(slug="b", report_path=None, accepted=False, reason="stub", text="", elapsed_s=0.0)

    monkeypatch.setattr(cli, "run_research", fake)
    cli.main(["research", str(tmp_path / "b.md"), *extra])
    return seen


def test_cli_no_reddit_passes_require_reddit_false(monkeypatch, tmp_path):
    assert _cli_kwargs(monkeypatch, tmp_path, ["--no-reddit"])["require_reddit"] is False


def test_cli_default_requires_reddit(monkeypatch, tmp_path):
    assert _cli_kwargs(monkeypatch, tmp_path, [])["require_reddit"] is True


def _run_capturing_prompt(monkeypatch, fake_server, tmp_path, *, require_reddit: bool):
    from tools.agentops import research as research_mod
    _wire_research(monkeypatch, fake_server, tmp_path)
    monkeypatch.setattr(research_mod, "ROOT", tmp_path)
    brief = _brief(tmp_path, "docs/research/nr.md")
    client = make_client(fake_server)
    session = client.create_session(str(tmp_path), title="pre")
    fake_server.store["messages"][session["id"]] = [
        {"info": {"role": "assistant", "tokens": {"input": 5, "output": 3}},
         "parts": [{"type": "text", "text": _long_report()}]},
    ]
    monkeypatch.setattr(client, "create_session", lambda directory, title: session)
    monkeypatch.setattr(ocserver, "ensure", lambda **kw: client)
    sent: dict = {}
    monkeypatch.setattr(client, "prompt_async", lambda *a, **kw: sent.update(kw))
    result = run_research(brief, model="luna", directory=tmp_path, config_path=tmp_path / "opencode.json",
                          require_reddit=require_reddit)
    return result, sent["text"], tmp_path / "docs" / "research" / "nr.md"


def test_no_reddit_tail_has_no_reddit_and_keeps_web_search(monkeypatch, fake_server, tmp_path):
    _, text, _ = _run_capturing_prompt(monkeypatch, fake_server, tmp_path, require_reddit=False)
    assert "reddit" not in text.lower()
    assert "live web search" in text


def test_default_tail_is_unchanged(monkeypatch, fake_server, tmp_path):
    from tools.agentops.research import TAIL
    assert TAIL == OLD_TAIL
    _, text, _ = _run_capturing_prompt(monkeypatch, fake_server, tmp_path, require_reddit=True)
    assert text.endswith(OLD_TAIL)


def test_good_report_without_reddit_accepted_under_no_reddit(monkeypatch, fake_server, tmp_path):
    result, _, written = _run_capturing_prompt(monkeypatch, fake_server, tmp_path, require_reddit=False)
    assert result.accepted and result.reason == "accepted"
    assert written.is_file()
