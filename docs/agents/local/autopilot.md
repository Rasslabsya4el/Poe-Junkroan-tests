# Autopilot: what this repo adds

Local counterpart of `docs/agents/autopilot.md`. The core file holds how the autopilot works; this file keeps the
history behind each rule: the issue, date or source each one came from, removed from the core text so the core stays
free of history.

## Where the rules came from

- The autopilot as a whole (provisional decisions, hard stops, checkpoints): issue #108.
- The dispatcher starts the session with the prompt "Autopilot on #N. Follow docs/agents/autopilot.md.": #116
  (`tools/agentops/dispatch.py`).
- ORCH works every ticket, never the autopilot, no exception for a doc or a one-line change: the owner, 2026-09-27,
  #142 ("the most expensive model must not do the ticket work").
- How a provisional decision is recorded (label, `Provisional:` trailer, `provisional`/`veto`/`approve` commands):
  #113, `tools/agentops/provisional.py`.
- The checkpoint's seven fields and their order: decided on #143 and #145.
- A fresh session after a reset loses 0 steps and starts with ~38.7k tokens of context: measured on #109.
- The next session starts only when a ticket changes or after 15 min, not every tick: #146.
- What counts as a change that wakes the session (child closed/reopened, labels changed, non-checkpoint comment on the
  goal; a progress comment on a child does not): #270.
- The stop rule's limits are named in the review: #127.
- Stopping when the goal is finished, removing the `autopilot` label so the dispatcher does not restart on a closed
  goal for ever: #116.
- `PushNotification` from a `--bg` session is refused ("this terminal is active"): measured on #110.
- `SendMessage` to the chat brain wakes it in under 10 s `--bg` to `--bg`, seconds `--bg` to the desktop chat: measured
  on #110.
- A desktop chat with Remote Control on, woken with no owner input, gets "Mobile push requested." and the push reaches
  the phone; while the owner is at that chat it is dropped: measured on #115.
- The checkpoint cap of 10,000 characters and the fold that DELETES old comments, never minimizes: #564 (the owner,
  2026-10-05). Seen on #486, the night of 2026-10-03/04: the cumulative checkpoint grew from 6,300 chars (session 1)
  to 39,549 (session 24). Worked example of a fold: #486's of 2026-10-04/05 (commit d29d9e3); the 37 minimized bodies (760 KB) were still
  downloaded by the hook until they were deleted, and the thread went from 47 to 10 comments, nothing lost.
- A `done` end waits like an `idle` end, and the `started` line names its reason: #544 (2026-10-05; on #486 24 of 38 sessions were nothing-moved restarts after `done`).
- Why "Check the result, not the report" exists, two cases: #837 pass 1 (2026-10-11): the monitor repair met its measured rows (row pitch 19 px, slot squares) and the owner found ten faults on the live pane in two minutes, the autopilot having measured only the rows the ticket named (his standing rule: #780 comment 6109883501); #839 (2026-10-11): the checkpoints carried "parked on the laptop jobs" from 12:27 to 16:16 while the first job had failed at 12:26:40 and its two followers could never start, the jobs carried by name and never read by state (comment 6109926998).
- The relay through the chat brain and the one push are withdrawn, and the leaving grill and the take-back rule came in their place (D108 amd 1, #1103, 2026-10-15, under #1105). The count behind it, from 11 to 14 October: 3 days 18 h in 279 sessions, the autopilot and the chat brain each made about 4,900 model calls over the same tickets (the owner: it felt like paying twice).
