# Spec (harness): a machine-wide budget of PoB sessions, enforced where a PoB session is born

Incident 2026-09-20 07:10 (diagnosed read-only): 12 logical cores at 99.9% for minutes, 5.9 GB of 31.9 GB free,
pagefile churn 963 -> 6,800 pages/s, the owner's desktop lagging, the queued production run getting 2-3 cores instead
of its 5. Cause: FIVE PoB-backed jobs at once (the queue's 5 workers, an agent's `replay_bench.py --workers 5`, another
agent's `gear_transplant.py` + pytest, a GPT worker's whole suite): 13 worker slots on 12 cores, 9 live PoB processes
of ~1 GB each, none of the jobs knowing of the others. The owner works on this machine by day. Rules in words exist
(CLAUDE.md "The machine has a budget"); this task makes them hold no matter who launches what.

## 1. The slot semaphore (in `src/junkroan/pob/`, used by `PobSession` and nothing else)

- A PoB session acquires ONE machine-wide slot before it starts its headless runtime and releases it when the session
  closes (context-manager exit, `close()`, interpreter exit, and -- because processes get killed -- by lock ownership:
  use OS file locks on `var/locks/pob-slot-<n>.lock` (`msvcrt.locking` on Windows, `fcntl` elsewhere; the lock dies with
  the process, so a killed worker frees its slot; no stale-PID cleanup needed). `var/` is shared by every worktree
  through a junction, so one directory serves the whole machine: resolve it from the MAIN checkout
  (`git rev-parse --git-common-dir`), never relative to a worktree.
- The budget is read LIVE from `var/machine_budget.json` on every acquire attempt (the lead edits it while jobs run):

      {"day":   {"hours": [8, 25], "total": 7,  "others": 2, "min_free_ram_gb": 8},
       "night": {"hours": [1, 8],  "total": 10, "others": 5, "min_free_ram_gb": 3}}

  ("hours" [8, 25] = 08:00 to 01:00 next day.) Missing file = these defaults, written on first use.
- Two roles. The QUEUE (`scripts/run_queue.py` sets `JUNKROAN_POB_ROLE=queue` for what it starts; children inherit
  it) may take any slot `1..total`. EVERYONE ELSE (agents, GPT workers, pytest, scripts run by hand) may take only
  slots `1..others` -- so the queue always finds `total - others` slots that nobody else can hold.
- RAM guard: no new slot while available physical memory is below `min_free_ram_gb` (`psutil` if installed, else
  `ctypes` `GlobalMemoryStatusEx`; no new dependency required).
- Waiting: poll every 2 s, log one line when the wait starts (`waiting for a PoB slot: 2/2 in use by pids [...]`) and
  one when it ends with the seconds waited; never time out by itself (a caller's own timeout still applies).
  `JUNKROAN_POB_SLOTS=off` disables the whole mechanism (fast unit tests that fake PoB never reach it anyway).
- Each lock file holds one line: pid, role, the process's command line cut to 120 characters, the start time -- for
  the report below; written after the lock is taken.

## 2. `python scripts/machine_load.py`

Prints in under 3 seconds, no PoB: now / day-or-night and the budget in force; CPU % (one 1-second sample); RAM free;
the slots in use (slot, pid, role, age, command) and who is waiting; per-role process counts (queue, `tools.agentops` /
opencode, pytest, replay_bench / benchmark / gear_transplant); and one verdict line for a planned launch:
`python scripts/machine_load.py --need 2 --role other` -> `GO` / `WAIT: 2 of 2 'other' slots in use (pids ...), RAM
free 5.1 GB < 8 GB`. Exit code 0 = GO, 3 = WAIT.

## 3. Tests (fast; temp directories for the lock dir; fake clock; no PoB)

Two acquirers of role `other` with `others = 1`: the second waits until the first releases; a role `queue` acquirer
gets a slot above `others` while both `other` slots are held; a holder process that is KILLED (spawn a child that
takes a slot and sleeps; terminate it) frees its slot; the budget file edited between two attempts is honoured; the
day / night switch at the hour boundaries ([8, 25] contains 00:30, not 01:30); the RAM guard with a faked memory
reader; `JUNKROAN_POB_SLOTS=off`; `machine_load.py --need` exit codes. One PoB-backed smoke (skips without the
runtime): opening a real `PobSession` writes and releases a slot file.

Whole suite once at the end, ALONE on the machine if possible (`python scripts/machine_load.py` first), with
`-p no:cacheprovider -p no:faulthandler`. Do not edit `docs/ROADMAP.md`, `docs/DECISIONS.md`, `CLAUDE.md`. Commit
early; begin the final message with `=== FINAL REPORT ===`.
