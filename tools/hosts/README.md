# Host scripts (issue #75)

Scripts each host's Task Scheduler runs, copied verbatim so they live in the repo instead of only
on the machine. `install.ps1` re-registers them idempotently (`schtasks /Create /F`); it must be
run locally, on the host it targets, and refuses when a PoB run looks live there.

## laptop (`tools/hosts/laptop/`)

Copied 2026-09-26 over `ssh laptop` from `C:\Coding\laptop-baseline\`, verbatim (no edits).

| script | Task Scheduler name | trigger (from `schtasks /query /xml`) |
|---|---|---|
| `laptop-telemetry.ps1` | `junkroan telemetry` | `BootTrigger` (at system start up), runs as SYSTEM |
| `power-guard.ps1` | `junkroan power guard` | `BootTrigger` (at system start up), runs as SYSTEM |
| `restore-after-movie.ps1` | `junkroan restore after movie` | one-time `TimeTrigger` (ad hoc, created at need), runs as SYSTEM |
| `close-browsers.ps1` | `junkroan close browsers` | one-time `TimeTrigger` (ad hoc, created at need), runs as SYSTEM |
| `wifi-guard.ps1` (+ `wifi-guard-decision.ps1`) | `junkroan wifi guard` | `MINUTE` every 1 min, runs as SYSTEM, hidden; after 15 min without internet cycles the Wi-Fi adapter, journal `var\wifi-guard\journal.jsonl` (#1188) |

`ThrottleStop (junkroan PL1)` also showed up in `Get-ScheduledTask` on the laptop, but it only runs
`ThrottleStop.exe` (a third-party binary, `C:\Coding\tools\ThrottleStop\ThrottleStop.exe`) with no
script of ours to copy; it is out of scope here.

`laptop-telemetry.ps1` already writes what the monitor needs to `artifacts\runs\telemetry.csv`
(one CSV row a minute): `time`, `cpu_temp_max_c`/`cpu_temp_avg_c`, `clock_avg_mhz`, `battery_pct`,
`on_mains` (AC vs battery), plus `pob_workers` and `free_ram_gb`. No second commit was needed for
requirement 3 of #75.

The laptop watchdog (`runs-daemon-ensure.ps1`) also checks the wifi each tick (`junkroan.runs.wifi`): log `artifacts/runs/wifi-laptop.log`, saved profile `artifacts/runs/wifi-laptop.json`.

## pc (`tools/hosts/pc/`)

Searched 2026-09-26 (`Get-ScheduledTask | Where TaskPath -notlike '\Microsoft\*'`): no junkroan-owned
scheduled task on the PC, only third-party ones (Hermes WSL Keepalive, LimitHub CLIProxyAPI, Lun1z
SSH Keepalive, OneDrive, NVIDIA, Google). Nothing to copy; `install.ps1 -HostName pc` registers an
empty set until a PC script exists here.
