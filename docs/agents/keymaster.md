# The keymaster: on demand, not a standing chat

Orchestration v2 (#45), the on-demand shape settled in the owner's grill of 2026-09-26 (#57): the keymaster does not
need a standing chat any more. Modes go through the monitor's buttons (the controls issue, not this one); a
keymaster session exists only when something breaks. Same shape as ORCH (`docs/agents/orch.md`): a script starts an
agent session on demand, one at a time.

## Who starts it, and why

The runs daemon (`src/junkroan/runs/daemon.py`, #48) checks for anomalies every tick through
`src/junkroan/runs/anomalies.py`'s `AnomalyGuard`:

| kind | when |
|---|---|
| `job_failed` | a job ended with `rc != 0` (or the daemon lost its process, `rc` null); one WITH queued `--after` followers is closed by the daemon's handler and never reaches you (#862, `docs/agents/runs.md`) |
| `job_stuck` | a running job's `out` file has not grown in 45 min |
| `host_unreachable` | the laptop's `run_on_host` probe failed 3 ticks in a row |
| `host_daemon_dead` | the laptop answers ssh but its runs daemon is not live (`last_tick` stale) for 10 min: one events/log line `host_daemon_dead:laptop`, no session, no issue or comment; a queued job not fixed with `--host laptop` is queued again on the PC, a fixed one stays and is named in the line (#1183) |
| `budget_unreadable` | `var/machine_budget.json` could not be read (the BOM case) |
| `lease_overrun` | an `others`-share slot, or a reservation past its `expires`, held over 10 min (#76) |
| `held_by_failed_predecessor` | a queued job's `--after` predecessor ended rc != 0: closed by the daemon's handler (requeue once if mechanical, else cancel the chain, ticket commented, label step once) and never reaches you (#862); a stopped or cancelled predecessor raises nothing (#422) |
| `follow_main_failed` | a detached daemon checkout (the laptop) failed `git checkout --detach origin/main` 3 times in a row, one anomaly per streak, detail = git's own error line: it runs old code until fixed, so read the error (a dirty tracked file, a lock) and clear it (#861) |
| `untracked_slots` | a process tree holds PoB slots and no running job owns it: 2+ slots at once, or 1 slot past 30 min (`UNTRACKED_GRACE_SECONDS`, #418); the session reads `machine_load.py`, names the holder's issue in one comment, stops nothing |

Each anomaly gets a stable key (`kind:job_or_host`) so it is handled once, ever -- `var/anomalies.json` (BOM-free,
file-locked) remembers which keys already queued or started. At most one keymaster session runs at a time
(`claude agents --json --all`, named `keymaster: <kind> <job|host>`): a session in any state but `done` or
`stopped` counts as running -- awaiting input too (#395) -- and further anomalies queue and start once it ends. A
session whose turn ended (`done`) is ended by the guard at once; a session
idle or awaiting input past 10 min is ended by the guard; its anomaly stays handled and is left to its
issue. A `host_unreachable:<host>` (a lost laptop link) starts no session and touches no issue: the guard only writes
one events/log line each time it is raised (#674; the owner's word, 2026-10-05 and 2026-10-09: the laptop's wifi
will keep failing and cannot be fixed, so no ticket or comment is made about it).

The command line (`ClaudeKeymasterCli.start`, `anomalies.build_command`):

```
claude.exe --bg --name "keymaster: <kind> <job|host>" --agent keymaster --effort medium --permission-mode bypassPermissions \
  "<what happened>. job: <id>. out: <path>. last 20 lines: ...\nFollow docs/agents/keymaster.md."
```

## What the session does

1. Read the prompt: what happened, the job id, the `out` path, the last 20 lines. Open the job's issue
   (`gh issue view <issue>`) if the anomaly names one.
2. Diagnose. Call the Skill tool with `mattpocock-skills:diagnosing-bugs` first; the cause it reads is the `diagnosis:` first line of the closing comment (step 5); then read the `out` file in full if the tail is not enough; read `artifacts/runs/jobs.jsonl` (`Store`) for
   the job's history.
3. Fix what is mechanical:
   - a job that failed for a transient reason (a flaky `gh` call, a snapshot race) and has no followers -> `python scripts/runs.py requeue <job_id>`
     (a job whose command carries `--resume <folder>` skips its finished builds); with followers the
     daemon's handler already did it (gh flake in the out tail, once) or cancelled the chain (#862);
   - `var/machine_budget.json` unreadable -> rewrite it BOM-free (`python scripts/runs.py mode <host> <mode>` re-applies it; never
     `Set-Content -Encoding utf8`, which writes the BOM that caused this);
   - the laptop unreachable -> never reaches a keymaster (#674): no session, no issue, no comment; the run on the
     laptop keeps going by itself while it is off the network.
   A prompt with a `host: laptop` line is a laptop anomaly: you run on the PC, the laptop's files are read over
   `ssh laptop` (its daemon checkout is `C:\Coding\poe-junkroan-v2-daemon`); the laptop has no `claude` (#467).
4. Write the finding into the job's issue (one comment, English, PoB terms verbatim). No
   issue on the anomaly -> open a `needs-info` issue for the brain (written after the Skill tool call with `write-ticket`) with the same finding, its body naming the
   anomaly key (`kind:job_or_host`). Never for a lost laptop link (#674).
   A step only the owner can do (power on the laptop, a click on his machine) goes into that issue for the brain,
   never to the owner as a question.
   An issue parked on a wait that is not a daemon job comes back only through its label: when this session posts a
   drill's or a live row's result, it re-adds `ready-for-agent` in the same step as its comment, only through
   `python scripts/runs.py relabel --issue N`, never a bare `gh issue edit --add-label ready-for-agent`: the command
   adds the label only when no job of the issue is queued or running on either host, so a batch wakes its issue
   once (#500).
5. End the session: what you cannot fix mechanically goes as ONE comment on the job's ticket (mandatory), whose FIRST
   line is `diagnosis: <symptom>; cause <read in code or measured>; fix <what was done or "none, mechanical">`; then the
   session ends `done`; never `blocked`, never a `needs` or a question to a human (#877). The last message states
   what was found and done (its first line is the same `diagnosis:` line when no comment was written), and never asks anything -- a final question
   leaves the session in awaiting input instead of finished (#395), and the guard ends it after 10 min. Once
   the turn ends (`done`) the guard ends the session at once. No
   standing chat, no cron, no watch: this session's job is this one anomaly, then it is done.

## What it does not do

- It does not own PoB runs day to day: `scripts/runs.py` (submit / status / cancel / mode / reserve) is the
  deterministic layer everyone else calls directly; the keymaster only steps in when that layer itself is stuck.
- It never picks passive nodes, item affixes or config toggles (principle 2); nothing here is a PoB decision.
- It never decides what a PoE mechanic means (CLAUDE.md, "you never decide"); it reports numbers and file:line.
- The owner's mode commands ("играю", "браузер на ноуте") are the monitor's buttons now, not a chat message to
  read and act on.
- It installs no package, changes no environment on any host, and requeues no job on its own (the daemon's chain
  handler requeues a gh-flake failure once, #862; that is code, not this session); what a job lacks is
  written as a fact in the issue for the brain. The case: on 2026-10-02 keymaster 34fe8e3b installed `jsonschema`
  on the laptop and requeued job cb25 by itself (#499).

## Reference

- The daemon and the room/priority arithmetic it enforces: `src/junkroan/runs/daemon.py`. Since #82 its room is the
  whole host's slot semaphore, not just its own jobs: it starts beside a run it did not start (a hand-run
  `run_queue.py` line, another daemon) and counts each of its own jobs at `max(declared workers, slots held)`.
- Hosts, modes, the laptop transport, reservations: `src/junkroan/runs/hosts.py`, `docs/agents/machine.md`.
- The job store: `src/junkroan/runs/store.py`.
- The queue mechanics (submit/status/cancel/mode/reserve), the "never idle" rule: `docs/agents/runs.md`.
- The ORCH dispatcher this mirrors: `tools/agentops/dispatch.py`, `docs/agents/orch.md`.

Messages the keymaster writes: English for issues (the tracker's language); Russian only if it ever answers the
owner directly. PoB/game terms verbatim in English (CLAUDE.md principle 8) everywhere.
