# The two reproduction session lists (acceptance 1 and 2)

Not read by the automated test suite (the tests never read the owner's transcripts); kept
here so the two one-off reproductions can be rerun later without going back to the research
scripts on their own branches.

- `post_edit_breakdown_sessions.txt`: the 14 ORCH sessions of `post_edit_breakdown.py`
  (`docs/research/scripts/post_edit_breakdown.py` on `research/175-levers-context-line`),
  its own set cut at `2026-09-27T12:13:00Z` (`--until`); `--since` only needs to predate every
  session's own start, e.g. `2026-09-01T00:00:00Z`.

      python scripts/cost_levers.py --since 2026-09-01T00:00:00Z \
          --until 2026-09-27T12:13:00Z \
          --sessions tests/fixtures/cost_levers_acceptance/post_edit_breakdown_sessions.txt

- `lever_orch_thread_sessions.txt`: the 18 ORCH sessions of `lever_orch_thread.py`
  (`docs/research/scripts/lever_orch_thread.py` on `research/175-levers-orch-thread`), the
  set of #130, cut at `2026-09-27T10:03:43Z` (`--until`, the moment session `2ef5b88d` was
  still live and #130's own cost table was written); `--since` is that set's own dispatch
  window start, `2026-09-26T19:19:32Z`.

      python scripts/cost_levers.py --since 2026-09-26T19:19:32Z \
          --until 2026-09-27T10:03:43Z \
          --sessions tests/fixtures/cost_levers_acceptance/lever_orch_thread_sessions.txt
