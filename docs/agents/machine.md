# The machine: PoB budget, launches, worktree junctions

Moved verbatim from CLAUDE.md on 2026-09-26 (#45); it binds every agent as if it were still written there. The first two bullets come from
docs/agents/local/research.md "Game-knowledge research", the junction rules are the section "Worktrees hold junctions" below.
PoB runs longer than ~5 min or wider than 1 slot go through the keymaster (`docs/agents/keymaster.md`).

## The budget and how long jobs are launched

- **The machine has a budget (incident 2026-09-20 07:10: 12 logical cores at 99.9%, 5.9 GB free, the owner's desktop
  lagging, the queued run starved).** Every PoB worker is a ~1 GB process that wants a whole core. Five PoB-backed jobs
  ran at once -- the queue (its workers), an agent's `replay_bench.py` at its own count, another agent's `gear_transplant.py`
  plus its pytest, a GPT worker's whole suite -- because the lead launched them without counting. The budget: the queue
  owns its reserved share; EVERYTHING ELSE together gets the `others` key of the current period (the cores left after
  the queue's share and a reserve for the desktop, Claude, Chrome, Defender). So: an agent's or worker's bench /
  benchmark / transplant runs with the workers the free slots allow (`machine_load.py --need N`), never next to its own
  pytest; one whole-suite run on the machine at a time; at most two code workers in a PoB-measuring phase at once.
  Every prompt and spec that starts PoB work says so. Wall-clock numbers and time-budgeted runs made under an
  overloaded machine are distorted (PoB's values are not): mark them. The owner WORKS on this machine by day (the
  user, 2026-09-20: capacity management is part of the orchestrator's job): DAY 08:00-01:00 = the `day` block of
  `var/machine_budget.json` (`total` slots in all, `others` for everything else, `min_free_ram_gb` free); NIGHT
  01:00-08:00 = the `night` block of the same file.
  Before launching anything that uses PoB: `python scripts/machine_load.py --need N --role other` (GO / WAIT, exit 0 / 3;
  it lists who holds which slot). The budget is ENFORCED since 2026-09-20 by a machine-wide slot semaphore inside
  `PobSession` (`src/junkroan/pob/slot_budget.py`: OS file locks under the shared `var/locks`, a reserved share for the
  queue, a RAM floor; `var/machine_budget.json` is re-read live -- lower `others` or `total` there when the owner needs
  a quieter machine; `JUNKROAN_POB_SLOTS=off` switches it off). A process started before the merge holds no slot: count
  `PoB runtime workers` in the script's output too. Prefer queueing work BEHIND the running job to running it beside it.

- **The `merge_suite` role (#666, #684).** The merge test suite's pytest workers hold no PoB slot and read no slot locks.
  `python scripts/machine_load.py --suite-workers` prints the count the merge uses, as its first line
  (`workers N: cores free X of 12 (cpu Y%), RAM free Z GB -> W by RAM, cap 6`): `N = max(1, min(cap, free_cores,
  free_ram_workers))` from one CPU reading (psutil, 1 s) and one RAM reading; `free_cores = floor(logical_cores *
  (100 - cpu%) / 100)`, `free_ram_workers = floor((free_RAM_GB - reserve) / 0.4)`. The pure function is
  `slot_budget.suite_workers_from_readings`; `0.4` GB is `slot_budget.SUITE_PER_WORKER_GB` (#666 measured 2.04 GB in total at
  the `merge_suite` cap, 2.04 / cap = 0.34 rounded up to 0.1); `reserve` is the key `merge_suite_reserve_gb` (default 3) and
  `cap` the key `merge_suite` (6), both in every mode/period block of `config/hosts.json` (a live
  `var/machine_budget.json` without them falls back to `slot_budget.DEFAULT_BUDGET`). CPU reader fails -> RAM-only
  count, line says `cpu n/a`; RAM reader fails -> 1 worker. `--need N --role merge_suite` still answers GO/WAIT for
  agents (GO iff `N <= merge_suite` and the `min_free_ram_gb` floor holds); the merge no longer uses it.

- **How agents and long runs are launched (the user, 2026-09-19: no pile of cmd windows, and the task panel must
  say what is running).** The standing rule (#490): on Windows a process an agent starts is exactly one of
  (a) inheriting the session's hidden console (a plain `subprocess.run` / `Popen`, a Bash child, no creation flags),
  (b) started with `CREATE_NO_WINDOW`, (c) detached only through `scripts/launch_hidden.ps1` /
  `tools/agentops/detach.py` (WMI, `ShowWindow = 0`). Never `DETACHED_PROCESS`, `CREATE_NEW_CONSOLE`,
  `Start-Process` without `-WindowStyle Hidden` / `-NoNewWindow`, `cmd /k`, a shell `start`, or a scheduled-task
  action that is a console exe (`tools/hosts/run-hidden.vbs` instead); and never a first run of anything that can
  get a window on the owner's desktop (use a private desktop object: `scripts/probe_console_windows.py`). The
  permission guard refuses the inline shell forms (red line 7) but sees command text only; a driver written to a
  file passes it, which is why a job launch itself carries `CREATE_NO_WINDOW`. The owner's own shortcut
  `Claude agents.lnk` (desktop and taskbar) runs `cmd.exe /k tools\agentops\agents.cmd`: its `/k` keeps a console
  window alive after `claude agents` exits, so a bare cmd prompt titled `claude agents` is that shortcut's, not an
  agent's (#490: pid 20436, started from `explorer.exe`). The dispatcher (`python -m tools.agentops dispatch`, #46/#50) and the queue runner are
  started DETACHED and HIDDEN through WMI `Win32_Process.Create` with `ShowWindow = 0` (no console window, and the process
  survives the end of the Claude Code session -- a plain background task would die with it): the dispatcher only as
  `python -m tools.agentops dispatch --ensure` (it wraps the command in `cmd /c ... >> artifacts/runs/dispatch.out 2>&1`;
  a bare `launch_hidden.ps1 -CommandLine "<exe> -m tools.agentops dispatch"` runs it with no redirect and its log is lost:
  pid 9372 of 2026-10-03, 10:59-12:37), the queue runner through `scripts/launch_hidden.ps1` with the redirect inside
  `-CommandLine` (`docs/agents/runs.md`). A dispatcher restart is `python -m tools.agentops stop <pid>` (the guard's own
  way; `taskkill` is red line 5) and then `dispatch --ensure`; it adopts live sessions and holds nothing across the gap. GPT code and research
  workers run over the `tools/agentops` bridge (`python -m tools.agentops worker|research ...`, #46): the call blocks
  until the run ends, so no separate watcher process is needed; the dispatcher polls `claude agents --json --all`
  itself for ORCH and its subagents (`docs/agents/orch.md`), and the monitor (#52,
  `python -m tools.agentops monitor`) shows what is running.
- **No CPU burner on the PC by day (#842).** Between 08:00 and 01:00, in any mode, no agent starts a process whose
  only job is to use the processor (a `while True` loop, a stress tool, N no-op loops). A row that needs a loaded
  machine is proven on the laptop, or on the PC between 01:00 and 08:00, as a job of the run queue
  (`python scripts/runs.py submit --issue N`), through the one helper `python scripts/burner.py --count N --seconds S`: BELOW_NORMAL,
  bounded, waits and kills what is left, and by day on the PC refuses any count above 1 (non-zero exit, names the
  laptop and 01:00-08:00). Its tests force the period; a worker never proves a row by a real day-time load.

## Machine mode: one switch per user (D117, #779)

- **The file**: `~/.claude/agentops/machine_mode.json` = `{"mode": "play" | "normal", "since": <iso>}`, outside every
  repo, naming none. Absent = `normal`. A file that does not parse raises (`MachineModeUnreadable`) and a loop whose
  read raised starts nothing on that tick. `machine_spans.jsonl` beside it logs every switch.
- **The switch**: `python -m tools.agentops machine play | normal | --current`, from any repo root that has the core;
  nothing but the owner's word or his button sets `normal`. `runs.py mode pc play | normal` also writes it (this
  repo's part, `src/junkroan/runs/machine_hold.py`); a timed play that expires sets it back.
- **Tests and rigs** set `AGENTOPS_MACHINE_DIR` to a folder of their own and never touch the real file: a real
  switch freezes the session that runs the test.
- **In play, nothing starts**: the dispatcher starts no session and sends no wake or hand-back (`--ensure` still keeps
  the loop alive); the merge line starts no suite and no line check, a queued entry waits; no full run is spawned;
  the runs daemon starts no job. Each loop reads the mode at least every tick (30 s).
- **What freezes** (`tools/agentops/hold.py`, suspended, never killed): the whole tree of every `background` session
  whose cwd is this repo's root, and the detached core launches found by their record files (merge lock holder, line
  checks, full-run lock, opencode server, job trees of the runs daemon). A keeper pass every tick suspends what
  appeared since; within 60 s of the switch every target is held, and on `normal` everything this installation
  suspended is resumed within 30 s (the record `var/agentops/hold_record.json` keeps pid + create_time, so a reused
  pid is never touched).
- **What does not freeze**: the dispatcher loop, the runs daemon loop, an interactive session (the brain's chat)
  and its tree, the desktop app, the caller and its ancestors. A repo adds loops of its own that must keep running as
  word lists in `config/hold_protected.json`, and its own job runners name their pids in
  `var/agentops/hold_roots/<name>.json`.
- **Stood time**: `machine_mode.stood_seconds(start, end)` gives the seconds of an interval spent in play; every
  watchdog (silent / stuck session, merge lock age, full-run lock, waiter timeouts, the daemon's anomalies)
  subtracts it, so a frozen job is not judged late.
- **How a repo obeys**: it takes the core (`tools/agentops/machine_mode.py`, `hold.py`, the manifest lines); there is
  no registry and no repo name, each installation tells itself apart by its own root, locks and records. A kind of
  work that does not survive a freeze is stopped at the switch and offered again at `normal`.

## Worktrees hold junctions: never delete one carelessly (incident 2026-09-18)

GPT worker worktrees (`tools/agentops/worktree.py`; in a harness worktree `python -m tools.agentops junctions` makes the three, idempotent) and `run_queue.py` snapshots reach `var/`, `vendor/` and `artifacts/` through
directory junctions. `git worktree remove --force`, Git Bash `rm -rf`, PowerShell `Remove-Item -Recurse` and
`git clean -fdx` all recurse THROUGH a junction and delete the shared target. On 2026-09-18 17:27:45 the main
model's `git worktree remove --force` on a fresh GPT worktree wiped every run under `artifacts/benchmark/` (both
frozen campaigns, rules-smoke, 25+ runs) and stopped only at a log the running benchmark held open; `var/` (the
PoB runtime) was next. Proven from the session transcript; the GPT worker's session was clean.

- Do not delete worktrees unless the user asks. Leftover worktrees cost nothing.
- If one must go: `cmd /c rmdir <link>` (non-recursive) for every junction, including those of nested worktrees;
  verify with `cmd /c dir /AL /S <worktree>` that no reparse point is left; only then `git worktree remove`
  (never `--force` to get past an error). `run_queue.py`'s snapshot removal already works this way.
- Snapshots live at `<repo root>/snapshots/<name>` (gitignored) since #360. Nothing under `var/`, `artifacts/` or
  `vendor/` links back to the root, so no link lies under its own target. The snapshots under
  `artifacts/runs/snap/<name>` are frozen legacy: each holds a junction `artifacts` -> `artifacts/`, a loop for
  every recursive walk, `find`, `rm -rf` and `Remove-Item -Recurse`. No agent deletes or moves one. The owner
  alone removes a finished one, its junction entries first (`cmd /c rmdir` each, as above). The junction check
  (`check_junction_target`, and `junction_target_refusal` in `run_queue.py`) refuses such a link. Recursive walks
  in `tools/` and `scripts/` never descend a junction (`tools/agentops/util.py` `walk_paths`).
- Finished runs are archived outside the repository (`C:\Coding\poe-junkroan-archive`, `JUNKROAN_ARCHIVE`).
- Who ran what: Claude transcripts `~/.claude/projects/C--Coding-poe-junkroan-v2/*.jsonl`; opencode's
  `~/.local/share/opencode/opencode.db` (tables `session`, `part`; its subagents are separate sessions). A GPT
  worker's session can outlive its first commit: check the branch again before and after merging.
