# Row 4 of #367: drill the laptop's power guard against the LIVE store, and write every number the
# close rule asks for into one log.
#
# It waits for the conditions the drill needs rather than assuming them: the laptop reachable, its
# mode `normal`, and a job actually running (the drill has to stop something to prove it can). That
# is why this is a detached script and not a command -- on 2026-10-01 the owner took the laptop for
# the browser until 02:57, so the drill could not run until the restore had put it back to work.
#
# Everything is driven through the guard's own test hooks (-Tick -Power -Now), so the mode logic, the
# stop path and the job store are exercised for real; only the Win32_Battery read is not. A physical
# unplug is still worth doing once, and only the owner can do that.
param(
    [string]$Repo = "C:\Coding\poe-junkroan-v2",
    [int]$DeadlineHours = 6,
    [int]$PollSeconds = 60
)
$log = Join-Path $Repo "artifacts\runs\drill-power-guard.log"
function Say([string]$m) {
    "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $m" | Add-Content -Path $log -Encoding utf8
}
function Lap([string]$script) {
    return (& ssh -n -o BatchMode=yes -o ConnectTimeout=20 laptop $script 2>&1 | ForEach-Object { "$_" })
}

# `py -3.12` rather than the full interpreter path: a quoted path inside a string sent over ssh came
# back as CommandNotFoundException, and the launcher needs no quoting at all.
# NOT `mode laptop --current`: that reads only var/modes.json, which plain `runs.py mode` never
# writes (only the monitor's timed path does), so it answers "normal" whatever the host is really on.
# Caught here on 2026-10-01 while the laptop was in `browser` mode for the owner and --current still
# said normal -- this drill would have fired during his turn. The budget file is the truth.
# The budget is machine_load.py's second line. Not Select-String with "^budget": -SimpleMatch makes
# the anchor literal and matches nothing, which cost one more arming round here.
$probeMode = 'Set-Location C:\Coding\poe-junkroan-v2; py -3.12 scripts/machine_load.py | Select-Object -Skip 1 -First 1'
$probeJob = 'Set-Location C:\Coding\poe-junkroan-v2-daemon; py -3.12 scripts/runs.py status --host laptop | Select-String -Pattern running -SimpleMatch | Select-Object -First 1'
$probeSlots = 'Set-Location C:\Coding\poe-junkroan-v2; py -3.12 scripts/machine_load.py | Select-String -Pattern slots -SimpleMatch'

Say "drill armed; waiting for the laptop on mode normal with a running job (deadline $DeadlineHours h)"
$deadline = (Get-Date).AddHours($DeadlineHours)
$jobRow = $null
while ((Get-Date) -lt $deadline) {
    $mode = (Lap $probeMode | Where-Object { $_.Trim() } | Select-Object -Last 1)
    # `normal` on the laptop is total 3; `browser` is 2 and `off` is 0.
    if ("$mode" -match 'total\s+3\b') {
        $row = (Lap $probeJob | Where-Object { $_ -match 'j-\d{8}' } | Select-Object -First 1)
        if ($row) { $jobRow = "$row"; break }
        Say "mode normal, no running job yet"
    }
    else { Say "mode is '$("$mode".Trim())', waiting" }
    Start-Sleep -Seconds $PollSeconds
}
if (-not $jobRow) { Say "deadline passed without a running job on mode normal; drill NOT run"; exit 1 }

$jobId = ([regex]::Match($jobRow, 'j-\d{8}-\d{4}-[0-9a-f]{4}')).Value
Say "BEFORE  job=$jobId"
Say ("BEFORE  " + ((Lap $probeSlots) -join ' '))

$t0 = Get-Date
$g = 'C:\Coding\poe-junkroan-v2\tools\hosts\laptop\power-guard.ps1'
$n1 = $t0.ToString('yyyy-MM-dd HH:mm:ss')
$n2 = $t0.AddMinutes(3).ToString('yyyy-MM-dd HH:mm:ss')
$n3 = $t0.AddMinutes(6).ToString('yyyy-MM-dd HH:mm:ss')

Lap "powershell -NoProfile -ExecutionPolicy Bypass -File $g -Tick -Power battery -Now '$n1'" | Out-Null
Say "tick 1 done (battery, $n1)"
Lap "powershell -NoProfile -ExecutionPolicy Bypass -File $g -Tick -Power battery -Now '$n2'" | Out-Null
Say "tick 2 done (battery, $n2) -- the stop should have happened"
Say ("ON BATTERY  " + ((Lap $probeSlots) -join ' '))
Say ("ON BATTERY  job row: " + ((Lap ("Set-Location C:\Coding\poe-junkroan-v2-daemon; py -3.12 scripts/runs.py status --host laptop | Select-String -Pattern $jobId -SimpleMatch")) -join ' '))

Lap "powershell -NoProfile -ExecutionPolicy Bypass -File $g -Tick -Power mains -Now '$n3'" | Out-Null
Say "tick 3 done (mains, $n3)"
Start-Sleep -Seconds 90
Say ("ON MAINS  mode=" + (("$(Lap $probeMode)").Trim()))
Say ("ON MAINS  " + ((Lap $probeSlots) -join ' '))
Say ("ON MAINS  next job: " + ((Lap $probeJob) -join ' '))
Say "GUARD LOG:"
foreach ($line in (Lap 'Get-Content C:\Coding\poe-junkroan-v2\artifacts\runs\power-guard.log -Tail 6')) { Say ("  " + $line) }
Say "drill done"
exit 0
