# Runs: the queue and the machine

Moved from the ROADMAP's "Autonomy protocol (the machine never idles)" on 2026-09-26. The machine budget, the hidden
launches and the slot semaphore are in `docs/agents/machine.md` (moved from CLAUDE.md, #45) and still apply. Since
orchestration v2 (#45) the queue belongs to the keymaster (`docs/agents/keymaster.md`): every other agent submits a
long run with `scripts/runs.py submit`; until the runs daemon (#48) starts jobs, the keymaster feeds them into the
queue below. A bisect or probe job whose exit code is the reading is submitted with `--rc-is-reading`, so its failing pins start no keymaster (#501); until a host's daemon runs this code, wrap the command so it exits 0 and prints pytest's rc. A submit names where its result goes: `--issue N` (the hand-back comments there and parks the issue) or `--no-issue`; neither, or both, is refused with rc 2. `--issue N --no-label` comments without touching the issue's labels (#515); `--no-label` with `--no-issue` is refused.

- The **run queue**: `artifacts/runs/queue.txt` holds one benchmark command per line; `scripts/run_queue.py`
  (detached, `--after-pid` optional) runs them one after another, writes `artifacts/runs/<name>.out`, re-reads the
  file after each run (append while it runs; `#` comments; a line is consumed once). Both runs daemons keep at
  least one run queued at all times (their fillers, when the switch is on, #751); a session waiting on a run puts a Monitor
  on the `.out` for "report:|FAILED|Traceback" (`python scripts/runs.py watch` replaces the Monitor once #48 lands; never a polling
  loop, never hourly posts). While a run goes: read the previous run's logs and audits, write rules and tests, append
  the next run. When nothing else is pending, queue 3-seed runs of references not yet at 3 seeds, then the weekly
  all-fixtures run.
- **Ticket run names** (#578): `submit` names a ticket run after its ticket, `P<priority>-#<issue>-<dd.mm>` (example
  `P1-#575-06.10`); its command is the `--issue N` form in the first paragraph above.
- **Reading the status table** (#1070): `python scripts/runs.py status` prints the queued and running jobs plus the
  jobs that ended in the last 24 h (the default); the footer adds `N older jobs hidden (--all)` when some are left out.
  `--all` prints every job; `--state X` prints that state whatever its age; `--host H` keeps one host's jobs; `--json`
  prints every job (no window) as before. The `--state`, `--host` and `--all` switches combine with the default window
  as stated; the JSON shape is unchanged.
- Machine: 6 cores / 12 threads; benchmark at the workers the daemon gives it (`--workers auto`; PoB is single-threaded Lua). One run at a time.
- Detached means outside the app's job object: a PowerShell `Start-Process` child still dies when the desktop app
  restarts (21:07 on 2026-09-15: the runner, the benchmark and its workers all died at once). Launch the runner with
  `Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{CommandLine='cmd.exe /c "cd /d
  C:\Coding\poe-junkroan-v2 && python scripts\run_queue.py >> artifacts\runs\queue-runner.out 2>>
  artifacts\runs\queue-runner.err"'; CurrentDirectory='C:\Coding\poe-junkroan-v2'}` (the parent is the WMI host, not
  the session). A new chat checks `tasklist` for `run_queue.py` before anything else and relaunches it the same way.
  Since 2026-09-16 14:54 the whole stack runs as `junkroan.exe` (a copy of
  `C:/Users/user/AppData/Local/Programs/Python/Python312/python.exe` next to it): another project's harness on this
  machine runs `Get-Process python | Stop-Process -Force` and killed the runner, the benchmark and the workers twice
  (14:44, 14:47). Check with `tasklist | findstr junkroan`, and launch the runner and every queue line with that exe
  (absolute path).
- A run sees one commit: since 2026-09-18 07:33 the runner executes every long command from a detached git worktree
  of HEAD taken at the run's start (`snapshots/<name>` since #360, the older ones under `artifacts/runs/snap/`
  frozen, `docs/agents/machine.md`; `var`, `artifacts`, `vendor` are junctions to the
  live checkout; the queue.log start line carries `@<sha> (snapshot)`), so commits and merges on main during a run
  are safe. Before that, a merge seven minutes into `speed-both` changed `rails_default.json` under the run's live
  worker processes and voided it (13 of 18 builds against `viol inf`). Only `compare_runs.py` lines run on the live
  checkout (their `--revert-commit` reverts main): keep the working tree clean when a weekly core run is due, or the revert
  fails. Replacing a runner under a running benchmark: kill the runner's PID only, relaunch with
  `--after-pid <benchmark pid> --adopt <run name>`.
- Never: a full run right after an unproven change (smoke first, 1 seed of the touched references); per-build tuning;
  a long run used to find a bug that the first finished seed already shows (read the first seed's log when it lands).
- **A `median of medians` line is never quoted before the counted references are compared on both sides** (the keymaster,
  2026-09-26, twice in three days). `compare_runs.py` takes each run's median over ITS OWN counted references, so a
  reference that one side lost to the audit or to a failed load silently shifts the headline: `ziz-rules` against
  `ziz-main3` read -9.8 over 20 against 26 references and +5.4 over the shared 20; `ziz-main3` against `ziz-main3-s4`
  read +12.0 over 26 against 25 and -1.0 over the shared 25 (one low reference, `z326_necromancer_zombie_army_early`,
  dropped out). So: count the counted references per side, recompute the median over the shared set, and report the
  shared-set number with the population next to it. The `--per-build` table is already restricted to builds present in
  both runs; the reference table is not. FIXED IN THE SCRIPT since 2026-09-26 18:00 (the lead): `compare_runs.py` now
  takes its verdict (and `--revert-commit`) over the shared references only, names the one-sided ones and prints each
  side's own median as a separate line. `compare_runs.py` lines always run on the LIVE checkout (`LIVE_SCRIPTS`), never
  from a snapshot, so every comparison still queued gets the fixed version; the manual cross-check stays needed only
  when reading a `.out` written before that commit.
- Every result: a comment with its numbers on the issue it serves, a commit with the numbers, `docs/STATE.md`
  rewritten.
- **Fillers** (#132, #517; the rule is #751). A
  Filler is a PoB job no issue waits for: class `filler`, priority P2, ordered UNDER P2 (`store.next_job`), no issue,
  one row = one worker. What it makes is a build of the weekly core run (`junkroan.runs.weekly_fillers`,
  `Daemon.filler_pass`). The rule, in order:
  1. **When.** A host's daemon submits fillers only while all hold: the host's filler switch is on (OFF by default
     since 2026-10-03, the owner's word); its mode is `normal`; no job that is not a filler is running or queued for
     the host; the spike ladder is at step 0.
  2. **How many.** `min(free slots of the mode, floor((free memory - memory floor) / memory per worker),
     floor(logical cores x (1 - CPU share over the last 60 s)))`, read at each start; 0 starts nothing. The memory per
     worker is `ram_per_worker_gb` of the host in `config/hosts.json` (measured, the peak of one build's process
     tree); a host without the number gets no fillers; no fixed count anywhere.
  3. **What, from the cut until the week's folder is full.** The next stem of `benchmark.py --resume <week's folder>
     --missing` that no running or queued filler of either host already makes: `--resume <folder> --row <stem>`,
     pinned at the cut.
  4. **What, otherwise** (the folder is full or no cut is in force for the coming Monday): a base row on current main
     for the early warning, `benchmark.py <slug> --seed <n> --seeds 1 --no-variants --gear wishlist --tag
     warn-<this week's Monday YYYYmmdd>`, pinned at main at submit; the 42 base rows of the weekly set in a fixed
     order, then again from the first. After each such job ends rc 0 the daemon runs the early-warning command (#749)
     for the week with `--post`.
  5. **Giving way: a stop, never a pause.** The tick that sees a job that is not a filler, of any priority (the
     Monday line included), running or queued for the host kills every filler of that host (the whole process tree,
     `Daemon.preempt_fillers_pass`) before anything else; so does a mode change away from `normal` and spike step 2.
     The arriving job starts at most 60 s after its submit when its own gates let it. A killed filler leaves no row
     file: its row is simply missing again, finished builds stay. If a kill fails, the filler stays and the job waits.
  6. **A daemon restart adopts running fillers** like any other job (`recover()`); none is stopped for it.
  7. **The switch has a command:** `python scripts/runs.py fillers <host> on|off` and `--current`; it writes only
     `<host>.fillers` in `config/hosts.json` (the daemon's `--fillers` / `--no-fillers` flags still force it for one
     daemon). The weekly cut (#750) reads the same switch.
- **Fillers stay switched off on both hosts** (#1189, the owner's word 2026-10-17, option 1): the weekly core run lives on the laptop (#1165, his word 2026-10-13), and a switch on moves its line back to the PC (`scripts/runs.py` `cmd_weekly`). `python scripts/runs.py fillers --current` prints `pc fillers off`, `laptop fillers off`; the brain runs no `fillers <host> on`. Between weekly runs the laptop takes the brain's own end-to-end build requests (his word 2026-10-13).
- **Settled by the owner on 2026-10-10 (#743), re-settled 2026-10-17 (#1189)**: fillers stay switched off while the weekly core run runs on the laptop. The older meaning of a filler (any PoB job from a standing list that no issue waits for) is retired.
- A filler's builds end up in `Documents\Path of Building\Builds\Junkroan\fillers\<run>`, never in the
  `Junkroan\benchmark <date time>` folders the owner reads: the daemon MOVES what the run wrote
  (`Daemon.sweep_filler_exports`) every tick while the filler runs and once more when it ends. A filler opens no
  issue, never appears in "Waiting on you" and never wakes ORCH. The heavy rule (#117) does not count a filler as a
  holder.

## A small job behind a head that waits for room (#834)

When the first job in line is blocked by room only, `Daemon.fill` goes on down the same order (a worse priority
too). A later job starts when it fits the room now AND `need(J) + need(head) <= the queue's total`, where `need(J)`
is summed over every job already passed that way and still running, so the head still fits the moment the jobs that
ran before the block end; a passed job never takes a slot the head needs, and no later submit starts once that sum
would go over. The head keeps its place. A job waiting behind the head prints `gate <id>: behind <head id> (needs N,
free M)`; `room (used X/Y, need N)` is printed only for the job that was weighed against the room. Fillers stay off
while a head waits; the heavy-job and over-limit holds are unchanged.

## Which runs are not fillers (D113, 2026-10-02)

A ticket's PoB run is chosen by the kind of its change; the ticket names the kind before the first submit, and the
closing comment shows the numbers of that kind. Anything else a host runs is a filler.

- **Kind A, a search-space rule** (an allowed option or a restriction: the rulebook tickets): NO paired set run.
  Proof = rail / unit tests without PoB + the trace counter on a replay-bench pass of 1-2 delivered builds where the
  option is legal (`python scripts/replay_bench.py --builds "artifacts/proof-575/builds/*.pob.txt" --move <the filler it enters> --seed 1 --tag
  trace-<issue>`, minutes on the workers the free slots give): `generated(x) > 0 and evaluated(x) > 0` for an option, `evaluated(forbidden)
  = 0 and output(forbidden) = 0` on every build for a restriction, plus one witness fixture where x is the known-best
  move. A lower median is not a failure; a metric gain proves nothing here. Quote the `--builds` glob: an unquoted
  glob is expanded by the shell and refused at `python scripts/runs.py submit` (#551).
- **Kind B, a loop or evaluation fix**: a bug-specific test first, then D84's bench (`replay_bench.py --move <m>` on
  the smoke six delivered builds, base and head at one seed, `--against`, 21-25 min at the free-slot count), per-build paired
  deltas and structural counts. A full paired set run (`benchmark.py`, same set and seeds both sides, through
  `python scripts/runs.py submit`) only when the bench alerts (a build under -15, D84) or the whole loop changes: 14 x 1 seed first, a
  further seed block only by a rule written before the run.
- **Kind C, a refactor**: identical PoB call transcripts (`replay_bench.py --record-calls`, `scripts/compare_calls.py`)
  and finals equal to the digit (D95); the first-difference clause of #35/#42 until #493 fixes the call order.
- **Kind D, speed only**: C's equality plus interleaved base/head timings on one host.
- **The weekly core run on main** (#750; the laptop since #1165): one command each Monday, `python scripts/runs.py weekly` (P2, `--no-issue`, note `weekly core run week-<Monday>: ...`). With no host's filler switch on it submits today's line, pinned at main, no `--resume`, host fixed to the laptop (#1165: the same PoB calls as on the PC at one pin, #978, so rows stay comparable week to week):
  `python scripts/runs.py submit --host laptop --priority P2 --no-issue --note "weekly core run week-<Monday>: laptop, comparable week to week: the same PoB calls as on the PC at one pin (#978, #1165)" -- python scripts/benchmark.py --set core14 --gear wishlist --seed 4 --seeds 3 --workers auto`. With a switch on it stays on the PC (the folder lives there, note "PC only"); this branch is unused while fillers are off (#1189) and takes the week's folder `artifacts/benchmark/<stamp>-week-<YYYYmmdd>` (opened at the cut, `origin/main` at Fri 20:00 local, if missing) and submits `--resume <folder> --workers auto` pinned at the cut, so fillers and the Monday line fill one folder (`--resume <folder> --missing` lists the rows still to make). A re-cut, `python scripts/runs.py recut` (owner: «пересрез»): cancels the week's filler jobs and the Monday line, renames the folder aside as `-dropped-<7 chars>` (nothing deleted), records `origin/main` now in `config/weekly_cut.json` (committed through `python -m tools.agentops commit --detach`), opens a fresh folder, resubmits the line if it was running or queued, and prints one line: old cut, new cut, builds dropped.
  An unchanged tree is refused as identical to the last weekly core run; `python scripts/runs.py weekly --again` runs it as a second sample of the same code (the difference from the earlier run is the noise of the weekly core run, never a quality verdict).
  Its row count: the 42 base rows, plus one `without <keystone>` row for each structural keystone a row took (D40), all in the same run and not a second run: 2026-10-05: 42 base rows + 19 keystone rows = 61.
  The Monday line and the `--resume` line pass no `--loop-seconds` (#956, test `tests/test_weekly_no_loop_seconds_956.py`): a run given `--loop-seconds` by hand depends on the machine, because its clock stops each build where that machine's speed puts it.
  (the run is named `P2-core[-<n>]` by `submit` itself, which also sets the benchmark's `--tag` to that name, #578; the report: `python scripts/weekly_report.py --core P2-core[-<n>]`)
  (`--workers auto`: the daemon resolves it at start to the free room, slots and RAM, and writes the number into the job's command and record; 7 by day on an empty PC, about 6 h; D113 amd 2, superseding amd 1's fixed 6), and reads it against the previous weekly core run with `compare_runs.py` paired per reference (shared references only, the
  rule above). The first sample is `392-before` (Run #479, main 9e7df88). An alert = exactly one fresh seed block,
  never "rerun until green"; a confirmed regression reverts the commit. This is the only place "did overall quality
  move" is answered; no ticket is judged by it. The worker count is the daemon's, so it can differ between gates and no wall clock stops a build's search (#956: `loop_max_seconds` defaults to None in
  `src/junkroan/optimizer/pipeline.py`; only a `--loop-seconds` given by hand stops it, and its result then depends on the
  machine); a row with `loop_stop` = `time` in a weekly core run is a defect to report (the first `auto` weekly core run named such rows against
  `gate-20261005` in the #538 report).
- A queued pair whose ticket turns out to be kind A is cancelled, not run (the 2026-10-02 cut: 10 tickets' pairs
  and the running `392-after`, #485; #447, a pair for an evaluation fix, became a kind-B bench instead). `python scripts/runs.py submit` still refuses an identical pinned run (#468), so one `before` per main commit
  serves every kind-B pair branched from it.
- Rebalance (#403, #518): the PC daemon moves a queued job that has waited to the laptop; a job submitted with an explicit `--host pc|laptop` is fixed to it (host fixed) and never moved, `--host auto` (the default) and `any` stay movable. Since #594 the documented submit lines name no `--host`, so a ticket run is movable; `--host pc` is written only for a job of `--workers` >= 5 (`HEAVY_WORKERS`), a pair a ticket pins to the PC for a measured reason, or the weekly core run, with `--note` saying why; "paired" alone is never a host reason, and a replay run (`--against`/`--builds`) names no `--host` (#701): the PC daemon copies the missing `artifacts/replay/<dir>` and `artifacts/benchmark/<dir>` it reads to the laptop, then moves the job (a failed copy keeps it on the PC, one log line). A paired run (D95) needs no `--host` (#648): a follower submitted with `--after <base>` and no `--host` is placed in the queue of the host holding its base, fixed there with `host_reason` `after:<base id>`; it never moves on its own, only together with its still-queued base.
- A job fixed with `--host laptop` is never moved, also when the laptop's runs daemon has been dead 10 min. A movable job queued on the laptop is queued again on the PC once that daemon has been dead 10 min (`host_daemon_dead`, #1183).
- Rebalance never moves a job to a host whose remote read failed within the last 10 min (#518): the host is held as unreachable until one later read succeeds; the daemon logs `rebalance: job <id> stays; <host> unreachable N min ago` once per job and host.

## Starting and restarting a daemon

- The PC daemon (hidden, detached; `-WorkDir` is always given: from an agent's shell `$PSScriptRoot` is empty and the
  default raised, #340):
  `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\launch_hidden.ps1 -CommandLine "<python> scripts\runs.py daemon --host pc >> artifacts\runs\daemon-pc.out 2>> artifacts\runs\daemon-pc.err" -WorkDir C:\Coding\poe-junkroan-v2`
  (`<python>` is the `junkroan.exe` copy, see above).
- The laptop's daemon runs from its own checkout, `C:\Coding\poe-junkroan-v2-daemon`, with `--handback remote`. Its job list is not in that checkout: it is the laptop's main checkout `artifacts\runs\jobs.jsonl`, the path `config/hosts.json` names as the laptop's `jobs_log_path` (#910); only the daemon's own logs (`daemon-laptop.err/.out`, the job `.out` files) live in the daemon checkout.
- The laptop's daemon never starts a keymaster (no `claude` login there, #467): it detects and queues in its own
  `var/anomalies.json`; the PC's daemon reads that queue over ssh each remote pass, starts the keymaster ON THE PC
  (prompt: `host: laptop`, the job id, read the laptop's files over `ssh laptop`) and drops the entry on the laptop
  with `runs.py anomaly-taken <key>`.
- A detached daemon checkout that fails `git checkout --detach origin/main` 3 times in a row raises one
  `follow_main_failed:<host>:<streak id>` (git's own error line in the detail; a 4th failure adds 0, a success ends
  the streak, the next streak is a new key, #861). It travels this same queue, so a laptop one reaches the PC's keymaster.
- `job_failed` of a job that has queued `--after` followers, and `held_by_failed_predecessor`, never reach a keymaster
  (#862): the daemon's own handler (`AnomalyGuard._close_chain`) ends the chain in the same tick, on the host that
  holds the job. A failure the out tail proves to be a gh / network flake and a job not yet run twice (`attempts` 1,
  no `requeued_from`) is requeued once under the same id, its followers follow it; anything else (a missing script
  included) cancels every follower, recursively. One comment on the failed job's ticket, then the label step
  (`runs.py relabel --issue N`) once for a cancelled chain. A `job_failed` without followers still goes to a keymaster.
- It is kept alive by a watchdog (#353): `python scripts/runs.py daemon --ensure --host <host>` (the same as
  `python -m junkroan.runs.watchdog --host <host>`), run from the host's own checkout, prints `alive pid N` and starts
  nothing when `artifacts/runs/daemon-<host>.json` shows a live pid with a fresh `last_tick`; otherwise it starts ONE
  daemon with the command above (`--handback remote` on the laptop) and prints `pid N`. Exit 0 = alive or started,
  1 = the launch failed (one stderr line), 2 = `--host` is not this machine. It runs as the Task Scheduler entry
  `junkroan runs daemon ensure` every 5 min on each host (`tools/hosts/install.ps1`,
  `tools/hosts/<host>/runs-daemon-ensure.ps1`), installed by the keymaster.
- It restarts itself (#340, #598). A change under `src/junkroan/runs`, `scripts/runs.py` or
  `config/hosts.json` moves HEAD past the commit the daemon started on. Starts are never held for it: queued jobs
  start as if HEAD had not moved (the heavy rule and the slot budget still apply). The daemon restarts at the first tick
  with no running job, or `RESTART_MAX_WAIT_SECONDS` (900 s) after it first saw the move, whichever comes first (a
  second move does not reset the wait). It logs `restart at boundary: <start> -> <head>` (with `, adopting N running
  job(s)` when jobs run), starts its replacement with the same command line, and the new one waits for the old pid to
  exit, then adopts what the store holds. A running filler is stopped first (#517). A commit touching none of those
  paths (a State commit) restarts nothing. `--no-self-restart` turns it off (`--ticks N` runs never restart).
- This is THE way to put new daemon code live: no outside watcher. `python -m tools.agentops stop <daemon pid>` is
  the owner's one-time switch only (#489, 2026-10-02): `taskkill /PID /F` without `/T` leaves the jobs running and
  the watchdog's replacement adopts them (PC 14:47: `392-after` adopted; laptop 14:59: `f71c` adopted), but the
  adopted job ends with its own rc since #598 on Windows (the replacement holds a handle on its pid); `lost pid`
  remains only for a job that ended before the replacement adopted it. Still never routine.
- A queued job writes its outputs under `artifacts/`; whatever else it changes in its snapshot comes back as `artifacts/runs/jobs/<job id>/snapshot.diff` (the END line carries `snapshot_diff`), applied by hand with `git apply`.
- `python scripts/runs.py submit` (and `status`, `cancel`) run inside a linked worktree use the main checkout's `artifacts/runs/jobs.jsonl`, so the job lands in the daemon's queue (#180).
- Run issues (#164): the daemon opens a Run issue for every whole-set benchmark (`--set`) that ends rc 0, a sub-issue of #404; for jobs that ended before that, `python scripts/runs.py run-issues --backfill [--since 2026-09-26] [--dry-run]` opens the missing ones (a second run creates 0).
