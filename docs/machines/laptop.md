# Second machine: the owner's laptop (`avent-laptop`)

Set up 2026-09-22 by the Opus session of the limit handover, at the owner's request. The keymaster runs benchmark
lines here (`docs/agents/keymaster.md`; what runs now: `docs/STATE.md`, "Runs"); how laptop results are compared with
desktop ones stays open below and is the brain's call (#45; before it, the handover backlog 2026-09-20 left it to Fable).

## The owner's standing instructions (2026-09-22)

- **Agents have full rights on the laptop.** Any change, any process, any file, over SSH or locally, without asking.
- **The one hard limit: nothing that can brick it.** No BIOS / EC / firmware flashing of any kind. (The board was
  repaired years ago with replacement parts; the owner said "не спалить ноут".)
- **When the owner uses it:** only Chrome + YouTube before sleep, usually around **02:00, at most about an hour**.
  The rest of the day it idles and stays switched on, plugged in, lid open or closed (lid close on AC does nothing).
  So it can run jobs around the clock; around 02:00-03:00 expect Chrome (~1-1.5 GB RAM) next to them.
- **No browser is opened on the laptop unless the owner asks for it that night** (the owner, 2026-09-24 00:05:
  "это ночью не надо ставить эконом режим на ноуте, я не буду юзать его", then "нет я имел в виду браузер ночью"). The evening of
  2026-09-23 a browser was opened for him and closed on a timer two hours later; that was a one-off, NOT a nightly
  routine. On a night he says nothing, or says he will not use it: no browser, no `junkroan close browsers` armed, and
  nothing held back -- full throughput, 4 workers, High performance, PL1 20 W (free RAM then sits near 1.3 GB, which is
  fine with no browser open). When he DOES say he is taking the laptop, the next line drops to 3 workers for that hour,
  never the running one.

## Hardware

| | |
|---|---|
| model | Xiaomi Mi Notebook Pro 15.6" (2017), code `TM1701`, BIOS `XMAKB5R0P0502` (2017-10-13, never updated -- and must not be) |
| CPU | Intel i7-8550U, 4 cores / 8 threads, TjMax 100 C (thermal throttle at 98 C) |
| GPU | Intel UHD 620 + NVIDIA GeForce MX150 (not used by PoB) |
| RAM | 7.9 GB (2 x 4 GB DDR4-2400); **~5.6 GB free at idle** with nothing open |
| disk | Samsung NVMe 256 GB, ~188 GB free |
| OS | Windows 10 Home 22H2 (build 19045), clean reinstall 2026-09-22 (the owner's Jinn'sLiveUSB build) |
| network | Wi-Fi through a USB TP-Link adapter (the internal Intel card's driver did not install); IP `192.168.1.190` from the router's DHCP (not reserved) |
| charger | non-original 65 W USB-C PD (VB-073961); enough even for CPU + MX150 at 100 % (measured: no battery drain) |

## Access from the desktop

- `ssh laptop` -- key `C:\Users\user\.ssh\junkroan_laptop` (used only for this), alias in `C:\Users\user\.ssh\config`.
  Since 2026-09-23 it points at the laptop's **Tailscale** address `100.77.22.117` (the desktop is `100.109.33.36`;
  both machines are under the owner's account as `avent-laptop` / `junkroan-desktop`), so the laptop is reachable from
  whatever network it is on -- home Wi-Fi, the owner's phone hotspot, anywhere. `ssh laptop-lan` is the old path by
  hostname on the home LAN, kept as a fallback. Password login is disabled on the laptop; port 22 on the LAN is open
  only to the local subnet on the Private profile. Why this was needed: the phone hotspot is a second NAT, so from the
  home LAN there is no route into the laptop at all -- it was invisible for eight hours on the night of 2026-09-22
  while its run went on fine.
- The remote shell is **Windows PowerShell 5.1**, and the SSH session is **elevated** (the account is an administrator).
  Quote `$` as `` `$ `` when the command is built in the desktop's PowerShell.
- **Copy files with `sftp`, not `scp`** (scp breaks on the PowerShell default shell). Example batch file:
  `put "C:/local/file" /C:/Coding/laptop-baseline/file`, then `sftp -q -o BatchMode=yes -b <batch> laptop`.
- A process started inside an SSH session dies when the session closes: keep the session open (a background task on
  the desktop) or start the job through Task Scheduler on the laptop.
- Folders: `C:\Coding` (work; excluded from Defender scanning), `C:\Coding\tools` (LibreHardwareMonitor, ThrottleStop),
  `C:\Coding\laptop-baseline` (the setup: `REPORT.md`, `changes.md` with every change and how to undo it, probes, logs).
- Python 3.12.10 (`py -3.12`, `C:\Program Files\Python312\python.exe`), Git 2.55. Not there yet: the repo, the PoB
  runtime (`var/cache/pob`, 2.4 GB), a queue runner. The repo has no remote: copy it from the desktop (git bundle over
  sftp, or a bare repo on the laptop pushed to over ssh).

## Tuning in place (all reversible; details and undo steps in `C:\Coding\laptop-baseline\REPORT.md` / `changes.md`)

- **PL1 = 20 W** (factory 15 W; PL2 44 W and 28 s unchanged), set in both MSR and MMIO by ThrottleStop 9.7.3.
  23 W was tried and rejected: the current limit fired in 15 % of the sustained phase; +6 % speed was not worth running
  a repaired board against its current protection for hours. 25 W (Intel's cTDP-up) not tried.
- ThrottleStop starts at the owner's **interactive** logon (Task Scheduler "ThrottleStop (junkroan PL1)", highest
  privileges). **After a reboot with nobody logged on at the laptop, the limit stays at the factory 15 W.** Before a
  long job check it: `ssh laptop "powershell -File C:\Coding\laptop-baseline\check-pl.ps1"` (expects `PL1 20 W`).
- Intel DPST (content-adaptive backlight) off -- the owner's old complaint of the brightness "going mad" is gone
  (1 197 polls at 100 ms under load: no change).
- Power plan High performance; on AC: never sleep, never hibernate on a timer, lid close does nothing, screen off 10 min.
- The Windows ACPI temperature sensor is fake (always 44 C); real temperatures need LibreHardwareMonitor + the PawnIO
  driver (`C:\Coding\laptop-baseline\probe-telemetry.ps1`).
- **Always-on telemetry** (2026-09-23): the scheduled task `junkroan telemetry` writes one row a minute into
  `artifacts/runs/telemetry.csv` -- core temperature (max and mean), CPU package watts, clock, load, battery percent,
  an on-mains flag, how many PoB workers run, free RAM. It starts at boot, runs as SYSTEM and trims itself at 3 MB.
  Under a four-worker run it reads 68-73 C at 20 W, far from the 85 C ceiling.
- **Power guard** (2026-09-23): the scheduled task `junkroan power guard` polls the battery every minute; after two
  minutes on battery it remembers the host's mode in `artifacts/runs/power-guard.mode` and sets the mode to `off` (`runs.py mode laptop off --local --who power-guard`, every job ends `stopped by power-guard`); when mains return it puts the remembered mode back unless someone changed it meanwhile (#367). Log:
  `artifacts/runs/power-guard.log`. Lid close now does nothing on both power sources; sleep on battery after 30 min is
  deliberate -- sleep preserves a run rather than losing it.
- Remote helpers: `close-browsers.ps1` (frees 1-2 GB), and `open-url2.ps1`, which opens a URL on the laptop's own
  screen through a one-shot interactive scheduled task -- an SSH session cannot show a window by itself.

## Measured speed (the same fixed C# work on both machines; lower = faster)

Short test (`laptop-check.bat`, seconds for one fixed piece of work per thread):

| | 1 thread | 4 threads at once | 8 threads |
|---|---|---|---|
| laptop, old Windows (before the reinstall) | 1.04 s | 1.68 s | 2.90 s |
| laptop, clean Windows, factory 15 W | 0.76 s | 0.87 s | 1.48 s |
| desktop (i5-12400F), under the queue's load | 0.56-0.62 s | 0.79 s | -- |

Sustained: 4 threads for 15 minutes (`laptop-sustained.ps1` / `probe-telemetry.ps1`, mean seconds per round):

| run | PL1 | mean round | MHz mean | cores C after 1st minute | note |
|---|---|---|---|---|---|
| `before` | 15 W | 1.26 s | ~2290 | (no real sensor) | nothing else open |
| `stock-cpu` | 15 W | 1.48 s | 2309 | 62 | Claude app + telemetry open |
| `pl1-20-cpu` | 20 W | 1.36 s | 2612 | 72 | Claude app + telemetry open |
| `pl1-23-cpu` | 23 W | 1.28 s | 2775 | 79 | rejected (current limit 15 %) |
| `pl1-20-cpu-gpu` | 20 W | -- | -- | 84 | + MX150 at 100 %; no battery drain |
| `final-pl1-20` | 20 W | **1.11 s** | **2900** | -- | nothing else open: **the number to plan with** |

Rough capacity: on this synthetic work a laptop worker is about **1.4x slower** than a desktop worker (1.11 s against
0.79 s), and the laptop holds its speed over the whole 15 minutes (last quarter = first quarter, 99 %). 3 workers fit
comfortably in RAM, 4 is tight and not around 02:00 when Chrome is open. That is roughly **50-60 %** of the desktop
queue's throughput, around the clock. The real multiplier for the loop's time budget must come from a paired PoB run,
not from this number (Fable, 2026-09-22).

## For whoever integrates it (open, the brain's call)

- The loop is time-budgeted (`--loop-seconds 5400`): on a slower machine a build gets less work in the same time.
  About 80 % of builds converge before the budget anyway ("kept nothing" in the fixed-point column of this week's
  reports: new18-r3 45 of 54, core14-r3 33 of 42, ziz-rules 53 of 66 counted). The owner's proposal: run laptop jobs
  with about 3x the budget and ignore their wall-clock times, so the builds stay comparable.
- The owner's proposal for the start: give the laptop the tail of the current queue (the priority-3 extra-seed runs)
  once it is ready; design the proper integration later.
- `var/machine_budget.json` and the slot semaphore are per machine; the laptop needs its own budget (e.g. 3 PoB slots,
  a RAM floor around 1.5 GB).
- **The laptop drops off the network on its own, repeatedly, and the runs do not care.** Three times inside 36 hours,
  each while a benchmark was running: 2026-09-24 about 20:30-21:37, 2026-09-25 about 05:09-06:02, 2026-09-26 from 08:36
  (Tailscale says `offline, last seen ...`, ICMP and `tailscale ping` both silent, the LAN name does not resolve and no
  local address answers on port 22). Every time the run kept computing -- PoB needs no network -- and every time the
  laptop came back by itself on a different radio of the same router, twice with a much better link (14.4 Mbps at 46%
  signal before the first drop, 195 Mbps at 68% after it, 260 Mbps at 73% after the second). So a drop is reported to
  the owner as a fact and a return watcher is armed (poll every 2 min); nothing is restarted and nothing is assumed
  lost until the machine answers. What it costs: only the transfers and the checks, not the builds. The standing
  recommendation for a real fix is still the USB extension or a repeater near the usual spot.
- **The budget shape changed on 2026-09-26 23:31 (#87, the owner's yes, applied by the brain):** one window
  `day [0, 24]`, `total 3`, `others 0`, `min_free_ram_gb 1`, `strict_reserve: true`. So the queue keeps its 3 slots and
  ANY role-other work on the laptop -- a hand-run script, a smoke outside `run_queue.py` -- now gets no slot at all and
  waits for ever. Run such work through the queue, or ask for the mode to change. The laptop has no `scripts/runs.py`
  (its checkout is still fab680c), so `runs.py mode laptop <mode>` cannot be used there; the file is written directly.
  When the owner wants the browser: lower `total` (2 keeps one slot free for him), never `others`, and restore this
  exact shape afterwards -- `C:\Coding\laptop-baseline
estore-after-movie.ps1` was updated the same evening, because
  the older version wrote `total 3 / others 3` with no `strict_reserve` and would have quietly undone #87.
- **After the laptop moves to the new code the movie evening stops being mine** (#73, the brain's cutover item, comment
  5850096315): it goes through the monitor's "Free the laptop" timer (`apply_timed_mode`, the laptop's `browser` mode for
  2 h, which is exactly `total 2`), `hosts.json` becomes the single source of the laptop's budget, and the scheduled task
  `junkroan restore after movie` is cut down to closing the browsers or removed. Until the laptop is pulled (our #73
  condition: after `new18-tpl-main3-s4-lap` ends, ~Monday 06:00), the task above stays the mechanism.
- **`var/machine_budget.json` is written WITHOUT a BOM, never with PowerShell's `Set-Content -Encoding utf8`**
  (incident 2026-09-24 20:50-22:23, this session's fault). Lowering the laptop's slots for the owner and restoring
  them afterwards was done with `Set-Content -Encoding utf8`, which in Windows PowerShell 5.1 writes UTF-8 WITH a BOM;
  `slot_budget` then logs `cannot read ... (Unexpected UTF-8 BOM ...); using the defaults` and falls back to the
  DESKTOP defaults, whose RAM floor a 7.9 GB laptop can never meet. The running builds finished (61 of 78 by 21:37) and
  then nothing started: 11,733 of those log lines, the machine at 1% CPU, no PoB runtime alive, three workers waiting
  1 h 27 min, 1 h 36 min and 17 h 43 min. Rewriting the file BOM-free
  (`[IO.File]::WriteAllText(path, json, (New-Object System.Text.UTF8Encoding $false))`) unblocked all three slots
  within one second. Cost: about 1 h 30 min of laptop time. Verify every budget write with
  `[IO.File]::ReadAllBytes(path)[0..2]` -- it must be `123,32,34`, not `239,187,191`.
- **DONE and measured (2026-09-22 19:43, the file's own timestamp): the laptop's budget is `total 3, others 3,
  min_free_ram_gb 1` day and night. So EVERY laptop line is written `--workers 3`.** A line asking for 4 gets three PoB
  runtimes and one process blocked on the semaphore for hours (main2-tpl-smoke-lap: one worker waited 6 h 3 min;
  ziz-tpl-main3-lap: about an hour per round), which costs nothing but makes the run look like a four-worker run when
  reading its times. Why 3 and not 4, measured 2026-09-24 12:10 with three workers busy: the three PoB runtimes hold
  1.18 + 1.03 + 1.00 GB, their three driver processes 0.2 GB each, Defender 0.2 GB, and of 7.9 GB total 1.1 GB is free
  with commit already at 7.9 GB. A fourth runtime (~1.1 GB) would page, and the 1 GB floor in the budget file would
  refuse it anyway. Nothing on the laptop degraded and the owner changed nothing: the cap has been 3 since the day it
  was set up, and the `--workers 4` in the laptop queue lines was this session's inconsistency, fixed 2026-09-24 12:05.
