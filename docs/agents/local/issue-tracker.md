# Issue tracker: what this repo adds

Local counterpart of `docs/agents/issue-tracker.md` (issue #148, D109). The core file holds the basic `gh`
conventions, the wayfinding operations and the rules for issue text; `docs/agents/workflow.md` holds the
category / blocking / parent-sub-issue `gh` conventions (moved there, #224); the lines below stand here verbatim,
with this installation's repo and this repo's product.

## This installation

Issues and specs for this repo live as GitHub issues of `Rasslabsya4el/Poe-Junkroan` (private). Use the `gh` CLI for all operations.

## Issue text in this repo

- English, like every doc in the repo. Game and PoB terms verbatim as PoB writes them (CLAUDE.md principle 8).
- An issue that touches the optimizer, the pipeline, gear, config or search names the PoB metric and the benchmark that prove it, and the numbers a test must reproduce (principle 6). Done means those numbers, not a schema check.

So: the metric is PoB's (`CombinedDPS` and the objective of D11), the benchmark is `scripts/benchmark.py` (D56), and
"Done" is the benchmark's numbers on the reference builds.

## Pull requests as a triage surface

The number-space example with this repo's own numbers:

GitHub shares one number space across issues and PRs, so a bare `#42` may be either: resolve with `gh pr view 42` and fall back to `gh issue view 42`.

## Where the rules came from

- The repo name and the private tracker: the owner's account, this installation.
- Game and PoB terms verbatim, the benchmark's numbers as "Done": CLAUDE.md principles 8 and 6.
- The five triage labels and the sub-issue / blocking conventions: #45, #53, #54.

## Areas and program labels

The five areas (`gh label list`, the `area:*` labels):

- `area:builds`: the main project, the search for builds (optimizer, gear, benchmark, skeletons).
- `area:orchestration`: agents, the dispatcher, ORCH, the port, the autopilot.
- `area:crafting`: the crafting oracle.
- `area:runs`: the PoB runs (the queue, the daemon, the keymaster, the laptop, the fillers).
- `area:monitor`: the monitor (the local page, its data and its design); the owner, 2026-09-29 16:34 (#310). Its
  main ticket is #334, and every other ticket of the monitor is a native sub-issue of #334.

The 8 labels a program reads as a switch, with the module that reads each (checked by grep):

| label | read by |
|---|---|
| `pob-free`, `in-cloud`, `cloud-lane` | `tools/agentops/cloud_lane.py` (`cloud-lane` also `tools/agentops/monitor.py`) |
| `autopilot`, `autopilot-stuck` | `tools/agentops/autopilot.py` |
| `provisional` | `tools/agentops/provisional.py` |
| `core-issue`, `core-epic` | `tools/agentops/core_issue.py` (`core-issue` also `tools/agentops/core_update.py`) |

The parents beside the map (the monitor, the cloud lane): their numbers are in #318's closing comment.
