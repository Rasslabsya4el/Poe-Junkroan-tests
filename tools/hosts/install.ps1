<#
.SYNOPSIS
    Registers this repo's host scripts (tools/hosts/<host>/*.ps1) as Windows Task Scheduler jobs,
    under their current names and triggers, idempotently (issue #75).

.DESCRIPTION
    Run locally, on the host it targets (Task Scheduler has no remote registration path here):

        powershell -File tools\hosts\install.ps1 -Host pc [-WhatIf]
        powershell -File tools\hosts\install.ps1 -Host laptop [-WhatIf]
        powershell -File tools\hosts\install.ps1 -HostName pc -Check [-RegisteredJson <file>]
        powershell -File tools\hosts\install.ps1 -HostName laptop -Only 'junkroan telemetry' [-WhatIf|-Check]

    -Only <name>[,<name>] (#888) limits registration / -Check to the named tasks; it also skips the pip and wifi
    steps. A live PoB run refuses the install unless -Only names only tasks with `TouchesRun = $false` (then it prints
    `left alone: live run pid(s) ...` and registers). -Check prints a not-registered one-shot (`restore after movie`) as `absent (one-shot)`, not `missing`.

    Each task is (re-)created with schtasks /Create /F from the definitions below, which mirror
    what `schtasks /query /tn "<name>" /xml` printed on 2026-09-26 for the laptop's four jobs
    (`tools/hosts/laptop/*.ps1`) -- see that folder's README for the source dump. The PC currently
    runs no junkroan-owned scheduled task (searched 2026-09-26: only third-party jobs -- Hermes WSL
    Keepalive, LimitHub CLIProxyAPI, Lun1z SSH Keepalive, OneDrive, NVIDIA, Google -- none of it
    ours), so `-Host pc` registers an empty set until a PC script is added under tools\hosts\pc\.

    Refuses (without -WhatIf) when a PoB run looks live on this host: a `junkroan.exe` process, or
    any process whose command line matches `spawn_main` (the queue's worker marker) or `LuaJIT`
    (PathOfBuilding's own runtime). -WhatIf still prints the plan (and the same live-run check) but
    registers nothing regardless.

    -Check is read-only (#887): it skips the live-run refusal, pip and wifi steps, changes nothing, and prints
    `<TaskName>: same|differs|missing` per task this host would register, comparing the installer's own action
    string with the one Task Scheduler holds (Get-ScheduledTask, or the JSON stand-in
    `[{"TaskName": "...", "Action": "..."}]` given by -RegisteredJson). Exit 0 only when every task is `same`,
    else 1; the last line is `check: N same, N differs, N missing`.
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('pc', 'laptop')]
    [string]$HostName,

    [switch]$Check,

    [string]$RegisteredJson,

    # #888: register (or -Check) exactly the named tasks and no other; an unknown name is an error.
    [string[]]$Only
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$hostDir = Join-Path $PSScriptRoot $HostName

# -- task definitions, mirrored from the live laptop's `schtasks /query /xml` (2026-09-26) --------
# Each entry: TaskName (Task Scheduler name, verbatim) / Script (file under tools/hosts/<host>/) /
# Trigger (schtasks /SC + /MO//ST as needed) / RunAsSystem (SYSTEM vs the interactive user) /
# Hidden (adds -WindowStyle Hidden to a SYSTEM task's action; a task run as the interactive user goes through
# wscript.exe + run-hidden.vbs instead, so no console window is drawn on the desktop, #396) /
# TouchesRun (#888, default $true when absent: registering the task can disturb a live PoB run; $false only for
# a task that merely re-points a script path and never stops anything).
$taskDefs = @{
    laptop = @(
        [pscustomobject]@{ TaskName = 'junkroan telemetry';           Script = 'laptop-telemetry.ps1';     Sc = 'ONSTART'; Hidden = $true;  System = $true; TouchesRun = $false }
        [pscustomobject]@{ TaskName = 'junkroan power guard';         Script = 'power-guard.ps1';          Sc = 'ONSTART'; Hidden = $true;  System = $true }
        # One-time jobs: the live host registers these with a specific past StartBoundary each time
        # it fires (created ad hoc, e.g. after a movie or before closing browsers for a run). We
        # reinstall the *mechanism* (schtasks entry, /SC ONCE) verbatim; a fresh StartBoundary is
        # set to "now" so a reinstall does not silently create a task scheduled in the past.
        [pscustomobject]@{ TaskName = 'junkroan restore after movie'; Script = 'restore-after-movie.ps1'; Sc = 'ONCE'; Hidden = $false; System = $true; OneShot = $true }
        [pscustomobject]@{ TaskName = 'junkroan close browsers';      Script = 'close-browsers.ps1';      Sc = 'ONCE'; Hidden = $true;  System = $true }
        [pscustomobject]@{ TaskName = 'junkroan runs daemon ensure';  Script = 'runs-daemon-ensure.ps1';   Sc = 'MINUTE'; Mo = '5'; Hidden = $true; System = $false; TouchesRun = $false }
        # #1188: the Wi-Fi guard checks the internet every minute and cycles the Wi-Fi adapter after 15 min without it;
        # SYSTEM (the adapter needs admin rights), hidden; it never stops a PoB run.
        [pscustomobject]@{ TaskName = 'junkroan wifi guard'; Script = 'wifi-guard.ps1'; Sc = 'MINUTE'; Mo = '1'; Hidden = $true; System = $true; TouchesRun = $false }
    )
    # #353: the watchdog runs as the interactive user on both hosts (laptop above too), so the daemon it starts
    # is the user's, not SYSTEM's: its git fetch and ssh need the user's profile.
    pc     = @(
        [pscustomobject]@{ TaskName = 'junkroan runs daemon ensure';  Script = 'runs-daemon-ensure.ps1';   Sc = 'MINUTE'; Mo = '5'; Hidden = $true; System = $false; TouchesRun = $false }
    )
}

$script:LivePids = @()
function Test-PobRunLive {
    <# True when a PoB RUN looks live on this machine: a run launcher, the queue's worker marker, or
       PathOfBuilding's own LuaJIT runtime, on any process's command line.

       Deliberately NOT `Get-Process -Name 'junkroan'`: on the PC the interpreter itself is named
       junkroan.exe (the runner was renamed on 2026-09-16 so a stray `taskkill python.exe` could not
       take a bench down), so the runs daemon is a junkroan.exe process too. That made this check
       always true on the PC and the installer unable to register 'junkroan runs daemon ensure' at
       all -- the one task whose whole job is to keep that daemon alive after the 26 h stall of
       2026-09-27 (#353). Found 2026-09-30 with daemon pid 27956 as the only match.

       The daemon is excluded by name: its command line is `runs.py daemon`, which matches no needle
       below, and registering a Task Scheduler entry cannot disturb a run in any case -- the guard is
       about not reinstalling the host's scripts under a run, not about the daemon. #>
    $needles = @(
        'spawn_main',              # a multiprocessing pool worker of a bench
        'LuaJIT',                  # PathOfBuilding's own runtime
        'headless_runtime_worker', # our PoB runtime worker
        'benchmark.py', 'replay_bench.py', 'run_queue.py',
        'gear_transplant.py', 'search.py', 'build_from_skeleton.py'
    )
    # Only an interpreter process can BE a run. Without this, the needles also match any process
    # whose command line merely MENTIONS one of those scripts -- which on 2026-09-30 meant two
    # claude.exe agent sessions, whose prompts name `benchmark.py`. A substring over every process on
    # the machine is what made the original check wrong too; the name filter is the half that was
    # missing.
    $interpreters = @('python.exe', 'pythonw.exe', 'py.exe', 'junkroan.exe')
    $live = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        if ($interpreters -notcontains $_.Name) { return $false }
        $line = $_.CommandLine
        if (-not $line) { return $false }
        if ($line -match 'runs\.py\s+daemon') { return $false }
        foreach ($n in $needles) { if ($line -like "*$n*") { return $true } }
        return $false
    }
    if ($live) {
        # Write-Warning, not Write-Output: anything this function writes to the success stream would
        # be returned alongside the boolean and make the caller's `if` test an array.
        $script:LivePids = @($live | ForEach-Object { $_.ProcessId })
        Write-Warning ("live-run check matched: " + (($live | Select-Object -First 3 | ForEach-Object { "pid $($_.ProcessId) $($_.Name)" }) -join '; '))
    }
    return [bool]$live
}

function Get-TaskAction {
    <# The one source of a task's action string (exactly what /TR receives): used by registration and -Check. #>
    param($Def, [string]$HostDir)
    $def = $Def; $hostDir = $HostDir
    $scriptPath = Join-Path $hostDir $def.Script
    if (-not (Test-Path $scriptPath)) {
        throw "Task '$($def.TaskName)' names script '$($def.Script)' which is not in $hostDir"
    }
    if ($def.System) {
        $styleArg = if ($def.Hidden) { '-WindowStyle Hidden ' } else { '' }
        $action = "powershell.exe -NoProfile $styleArg-ExecutionPolicy Bypass -File `"$scriptPath`""
    }
    else {
        $runHidden = Join-Path $PSScriptRoot 'run-hidden.vbs'
        $action = "wscript.exe //B //Nologo `"$runHidden`" `"$scriptPath`""
    }
    return $action
}

$defs = $taskDefs[$HostName]
if ($Only) {
    # powershell -File hands 'a,b' over as one string, so split it here too.
    $Only = @($Only | ForEach-Object { $_ -split ',' } | ForEach-Object { $_.Trim() } | Where-Object { $_ })
    $unknown = @($Only | Where-Object { $_ -notin $defs.TaskName })
    if ($unknown.Count -gt 0) {
        throw "-Only names unknown task(s) for host ${HostName}: $($unknown -join ', '). Known: $($defs.TaskName -join ', ')"
    }
    $defs = @($defs | Where-Object { $_.TaskName -in $Only })
}
Write-Output "Host: $HostName -- $($defs.Count) task(s) defined in tools\hosts\install.ps1"

if ($Check) {
    # Read-only: no live-run refusal, no schtasks, no pip, no wifi.
    $registered = $null
    if ($RegisteredJson) { # the extra ForEach-Object unrolls the array Windows PowerShell 5.1's ConvertFrom-Json returns as one object
        $registered = @((Get-Content -Raw -LiteralPath $RegisteredJson | ConvertFrom-Json) | ForEach-Object { $_ }) }
    # Task Scheduler may quote Execute differently from /TR, so double quotes and whitespace runs are
    # dropped on both sides before comparing.
    function ConvertTo-ComparableAction([string]$s) { return (($s -replace '"', '') -replace '\s+', ' ').Trim() }
    $nSame = 0; $nDiff = 0; $nMissing = 0
    foreach ($def in $defs) {
        $expected = Get-TaskAction -Def $def -HostDir $hostDir
        $actual = $null
        if ($RegisteredJson) {
            $hit = $registered | Where-Object { $_.TaskName -eq $def.TaskName } | Select-Object -First 1
            if ($hit) { $actual = [string]$hit.Action }
        }
        else {
            $task = Get-ScheduledTask -TaskName $def.TaskName -ErrorAction SilentlyContinue
            if ($task) { $actual = ("$($task.Actions[0].Execute) $($task.Actions[0].Arguments)").Trim() }
        }
        if ($null -eq $actual -and $def.OneShot) {
            # #888: a one-shot that has already run is gone from Task Scheduler; not a defect.
            Write-Output "$($def.TaskName): absent (one-shot)"
        }
        elseif ($null -eq $actual) {
            Write-Output "$($def.TaskName): missing"; $nMissing++
        }
        elseif ((ConvertTo-ComparableAction $actual) -eq (ConvertTo-ComparableAction $expected)) {
            Write-Output "$($def.TaskName): same"; $nSame++
        }
        else {
            Write-Output "$($def.TaskName): differs"
            Write-Output "  registered: $actual"
            Write-Output "  expected:   $expected"
            $nDiff++
        }
    }
    Write-Output "check: $nSame same, $nDiff differs, $nMissing missing"
    if ($nDiff -gt 0 -or $nMissing -gt 0) { exit 1 }
    exit 0
}

if (Test-PobRunLive) {
    # #888: with -Only, when every named task has TouchesRun false, a live run is left alone, not refused.
    $touching = @($defs | Where-Object { $null -eq $_.TouchesRun -or $_.TouchesRun })
    if ($Only -and $touching.Count -eq 0) {
        Write-Output "left alone: live run pid(s) $($script:LivePids -join ', ')"
    }
    elseif ($WhatIfPreference) {
        Write-Warning "A PoB run looks live on this host (junkroan.exe / spawn_main / LuaJIT) -- would refuse without -WhatIf."
    }
    else {
        throw "Refusing: a PoB run looks live on this host (junkroan.exe / spawn_main / LuaJIT). Re-run once it has ended."
    }
}

foreach ($def in $defs) {
    $action = Get-TaskAction -Def $def -HostDir $hostDir
    $runAs = if ($def.System) { 'SYSTEM' } else { $env:USERNAME }

    # HIGHEST only for the SYSTEM tasks that need it. Asking for it on a task that runs as the
    # interactive user makes schtasks answer "Access is denied." in a shell that is not elevated,
    # which is every agent shell here -- and that is what blocked 'junkroan runs daemon ensure', the
    # one task standing between the daemon dying and another 26 h stall (#353, 2026-09-30). The
    # watchdog only launches a daemon as that same user, so LIMITED is all it ever needed.
    $runLevel = if ($def.System) { 'HIGHEST' } else { 'LIMITED' }

    $createArgs = @(
        '/Create', '/F',
        '/TN', $def.TaskName,
        '/TR', $action,
        '/SC', $def.Sc,
        '/RU', $runAs,
        '/RL', $runLevel
    )
    if ($def.System) { $createArgs += @('/RP', '') }
    if ($def.Mo) { $createArgs += @('/MO', $def.Mo) }
    if ($def.Sc -eq 'ONCE') {
        $start = (Get-Date).AddMinutes(1).ToString('HH:mm')
        $createArgs += @('/ST', $start, '/SD', (Get-Date).ToString('MM/dd/yyyy'))
    }

    if ($PSCmdlet.ShouldProcess($def.TaskName, "schtasks $($createArgs -join ' ')")) {
        schtasks @createArgs
    }
    else {
        Write-Output "WhatIf: schtasks $($createArgs -join ' ')"
    }

    # #1188: the wifi guard must keep running on battery (a laptop that is unplugged is the case it is for)
    if ($def.TaskName -eq 'junkroan wifi guard') {
        $batterySettings = 'New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries'
        if ($PSCmdlet.ShouldProcess($def.TaskName, "Set-ScheduledTask -Settings $batterySettings")) {
            Set-ScheduledTask -TaskName $def.TaskName -Settings (New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries) | Out-Null
        }
        else {
            Write-Output "WhatIf: Set-ScheduledTask -TaskName '$($def.TaskName)' -Settings ($batterySettings)"
        }
    }
}

if ($Only) {
    # #888: -Only registers the named tasks and nothing else: no pip, no wifi tasks.
    Write-Output "Done: $HostName (-Only: $($defs.Count) task(s))."
    exit 0
}

# #463: the laptop daemon's python needs pytest for the queue's test jobs; install once when missing.
if ($HostName -eq 'laptop') {
    $py = 'C:\Program Files\Python312\python.exe'
    if ($PSCmdlet.ShouldProcess($py, 'pip install --user pytest (when pytest --version fails)')) {
        & $py -m pytest --version *> $null
        if ($LASTEXITCODE -ne 0) { & $py -m pip install --user --quiet pytest }
    }
    else {
        Write-Output "WhatIf: $py -m pip install --user --quiet pytest (when pytest --version fails)"
    }
}

# #382: the wifi adapter's power saving stays off after a reinstall (the script is idempotent and takes -WhatIf).
if ($HostName -eq 'laptop') {
    $wifiPower = Join-Path $hostDir 'wifi-power.ps1'
    if ($WhatIfPreference) { & $wifiPower -WhatIf } else { & $wifiPower }
    # #522: VHT 2.4G IOT = Disable through a one-shot task with a rollback guard (idempotent, takes -WhatIf).
    $wifiVht = Join-Path $hostDir 'wifi-vht.ps1'
    if ($WhatIfPreference) { & $wifiVht -WhatIf } else { & $wifiVht }
    # #522 (d): Wireless Mode = IEEE 802.11b/g/n through a one-shot task with a rollback guard (idempotent, takes -WhatIf).
    $wifiMode = Join-Path $hostDir 'wifi-mode.ps1'
    if ($WhatIfPreference) { & $wifiMode -WhatIf } else { & $wifiMode }
}

Write-Output "Done: $HostName ($($defs.Count) task(s))."
