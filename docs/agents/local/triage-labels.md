# Triage Labels: what this repo adds

Local counterpart of `docs/agents/triage-labels.md` (issue #148, D109). The core file holds the five states;
`docs/agents/workflow.md` holds the two categories and the parent / parked / blocked rules (moved there, #224); the
bullets below stand here verbatim as they were written, with this repo's own issue numbers and its run queue.

## Parents and parked issues

- **A parent** (an issue with open native sub-issues, e.g. #1, #32, #36) carries a category and no state; its
  sub-issues carry the states. It closes when its sub-issues are done.
- **A parked issue** (ORCH waits on a `python scripts/runs.py submit` job, `docs/agents/orch.md`) has its `ready-for-agent` removed
  and no state until the job's result re-adds `ready-for-agent`.
- **A blocked issue** keeps its real state: an open native blocker (`gh issue edit N --add-blocked-by M`) is what
  holds it back. The dispatcher never hands out an issue with an open blocker (#53), so there is no "blocked" state
  and no label is removed to hold an issue.

The job a parked issue waits on here is a PoB run submitted with `python scripts/runs.py submit`
(`docs/agents/runs.md`, `docs/agents/keymaster.md`); the runs daemon posts the result and re-adds `ready-for-agent`.

## The label `parked` (#1074)

`parked` is a switch a program reads: the dispatcher (`GhCli.ready_for_agent_issues`, `tools/agentops/dispatch.py`
step 4) never offers an issue that carries it, and the tracker guard (`tools/hooks/tracker_guard.py`) refuses the word
in a new title. `tools/agentops/parked_label.py` moved the old "(parked ...)" titles onto the label in both repos.

## Where the rules came from

- The five states and the two categories: the mattpocock-skills triage roles, mapped to this repo's labels.
- The dispatcher never hands out a natively blocked issue: #53.
- A parked issue loses `ready-for-agent` while its PoB job runs: #48, #50.
