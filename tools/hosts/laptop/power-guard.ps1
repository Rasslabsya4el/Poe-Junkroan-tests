# Power guard for the laptop: after 2 min on battery it sets the host's mode to off (every running job ends
# "stopped by power-guard"); on mains return it puts the remembered mode back, unless someone changed it meanwhile.
# Test hooks (defaults = the real machine): -Tick runs one tick and exits; -Power battery|mains overrides the battery
# read; -Now 'yyyy-MM-dd HH:mm:ss' overrides the clock; -Repo / -Launcher / -LauncherArg / -RunsPy point at a fake.
param(
    [string]$Repo = 'C:\Coding\poe-junkroan-v2',
    [string]$Launcher = 'py',
    [string]$LauncherArg = '-3.12',
    [string]$RunsPy = '',
    [switch]$Tick,
    [string]$Power = '',
    [string]$Now = ''
)
$ErrorActionPreference = 'Continue'
$env:JUNKROAN_HOST = 'laptop'   # every runs.py started below reads this machine as the laptop (#367)
$repo = $Repo
$runs = Join-Path $repo 'artifacts\runs'
$log = Join-Path $runs 'power-guard.log'
$marker = Join-Path $runs 'power-guard.mode'
$stateFile = Join-Path $runs 'power-guard.state'
if (-not $RunsPy) { $RunsPy = Join-Path $repo 'scripts\runs.py' }
if (-not (Test-Path $runs)) { New-Item -ItemType Directory -Force -Path $runs | Out-Null }

function Clock { if ($Now) { return [datetime]::ParseExact($Now, 'yyyy-MM-dd HH:mm:ss', $null) } else { return Get-Date } }
function Say($m) { ('{0} {1}' -f (Clock).ToString('yyyy-MM-dd HH:mm:ss'), $m) | Add-Content -Encoding utf8 $log }
function OnMains {
    if ($Power -eq 'mains') { return $true }
    if ($Power -eq 'battery') { return $false }
    $b = Get-CimInstance Win32_Battery -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $b) { return $true }          # no battery reported: treat as mains, never stop by mistake
    return ($b.BatteryStatus -ne 1)         # 1 = discharging; everything else counts as powered
}
function Runs([string[]]$a) {
    $all = @()
    if ($LauncherArg) { $all += $LauncherArg }
    $all += $RunsPy
    $all += $a
    $lines = @(& $Launcher @all 2>&1 | ForEach-Object { "$_" })
    $script:RunsExit = $LASTEXITCODE        # runs.py's exit code, for callers that care (the off step)
    return $lines
}
function CurrentMode {
    $out = @(Runs @('mode', 'laptop', '--current') | Where-Object { $_.Trim() })
    if (-not $out) { return 'unknown' }    # never a guessed normal: a guard that cannot read the mode must not hand the laptop to the queue
    return $out[-1].Trim()
}
function ReadState {
    if (Test-Path $stateFile) { return (Get-Content $stateFile -Raw | ConvertFrom-Json) }
    return $null
}
function WriteState($offSince, $handled) {
    @{ offSince = $offSince.ToString('yyyy-MM-dd HH:mm:ss'); handled = [bool]$handled } | ConvertTo-Json | Set-Content -Encoding ascii $stateFile
}

function DoTick {
    $state = ReadState
    if (OnMains) {
        if ($state -or (Test-Path $marker)) {
            if (-not (Test-Path $marker)) { Say 'mains back; nothing to do' }
            else {
                $before = (Get-Content $marker -Raw).Trim()
                $cur = CurrentMode
                if ($cur -eq 'off' -and $before -eq 'unknown') {
                    Say 'mains back; mode before was unknown, left off'
                }
                elseif ($cur -eq 'off') {
                    Runs @('mode', 'laptop', $before, '--local') | Out-Null
                    Say ("mains back; mode off -> $before")
                }
                else { Say ("mains back; mode changed by hand to $cur, left") }
                Remove-Item $marker -Force
            }
        }
        if (Test-Path $stateFile) { Remove-Item $stateFile -Force }
        return
    }
    if (-not $state) { WriteState (Clock) $false; return }
    if ($state.handled) { return }
    $since = [datetime]::ParseExact($state.offSince, 'yyyy-MM-dd HH:mm:ss', $null)
    if (((Clock) - $since).TotalSeconds -lt 120) { return }
    WriteState $since $true
    $before = CurrentMode
    if ($before -eq 'off') { return }      # freed on purpose: do nothing, remember nothing
    Set-Content -Encoding ascii $marker $before
    $out = @(Runs @('mode', 'laptop', 'off', '--local', '--who', 'power-guard'))
    if ($script:RunsExit -ne 0) {
        $last = @($out | Where-Object { $_.Trim() }) | Select-Object -Last 1
        Say ("on battery 2 min; mode $before -> off; stop failed: $last")
        return
    }
    $ids = @($out | ForEach-Object { if ($_ -match '^(\S+) -> failed \(stopped by power-guard\)') { $Matches[1] } })
    $list = if ($ids.Count) { $ids -join ', ' } else { 'none' }
    Say ("on battery 2 min; mode $before -> off; stopped $list")
}

if ($Tick) {
    try { DoTick } catch { Say ('error: ' + $_.Exception.Message) }
    return
}
Say 'power guard started'
while ($true) {
    try { DoTick }
    catch { Say ('error: ' + $_.Exception.Message) }
    Start-Sleep -Seconds 60
}
