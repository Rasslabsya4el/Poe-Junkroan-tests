<#
.SYNOPSIS
    Sets the laptop wifi adapter's "Wireless Mode" property with a rollback guard (issue #522, change (d)).

.DESCRIPTION
    Follow-up to wifi-vht.ps1: the laptop's TP-Link Archer T2U Nano ("Wi-Fi 2") still fails the WPA key exchange
    with VHT 2.4G IOT = Disable. Change (d): Wireless Mode = IEEE 802.11b/g/n (it was Auto; -Value Auto restores
    it). Setting an advanced property resets the adapter, so the ssh session that starts this script loses its
    link; the change therefore runs from a one-shot scheduled task, and a second one-shot task, the guard, arms
    first and rolls the value back when the adapter did not reconnect. The previous value is also written to
    artifacts\runs\wifi-mode-state.json.

    Modes:
      (default)  read the property; equal to -Value: say so, exit 0 (no task). Otherwise register two one-shot
                 tasks as SYSTEM (RunLevel Highest, hidden): "junkroan wifi-mode guard" at now + 11 min (10 min after the change), then
                 "junkroan wifi-mode apply" at now + 1 min. Guard is registered BEFORE the change task.
      -Apply     Set-NetAdapterAdvancedProperty to -Value; one line to the log.
      -Guard     count event 8001 (WLAN AutoConfig: successfully connected) since -Since in
                 Microsoft-Windows-WLAN-AutoConfig/Operational; 0 -> set -Previous back; log; unregister both tasks.

    Log: artifacts\runs\wifi-guard.log (one line per event). -WhatIf changes nothing (no task, property, or log line).
    Run by tools\hosts\install.ps1 -Host laptop; also: powershell -File wifi-mode.ps1 [-WhatIf]
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$AdapterName = 'Wi-Fi 2',
    [string]$Value = 'IEEE 802.11b/g/n',
    [switch]$Apply,
    [switch]$Guard,
    [string]$Previous,
    [string]$Since
)

$ErrorActionPreference = 'Stop'
$displayName = 'Wireless Mode'
$statePath = Join-Path $PSScriptRoot '..\..\..\artifacts\runs\wifi-mode-state.json'
$guardTask = 'junkroan wifi-mode guard'
$applyTask = 'junkroan wifi-mode apply'
$logPath = Join-Path $PSScriptRoot '..\..\..\artifacts\runs\wifi-guard.log'
$isoFormat = 'yyyy-MM-ddTHH:mm:ss'

function Write-GuardLog([string]$Line) {
    $dir = Split-Path -Parent $logPath
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    Add-Content -Path $logPath -Value ((Get-Date).ToString($isoFormat) + ' ' + $Line) -Encoding UTF8
}

function Get-Mode {
    (Get-NetAdapterAdvancedProperty -Name $AdapterName -DisplayName $displayName).DisplayValue
}

if ($Apply) {
    $old = Get-Mode
    if ($PSCmdlet.ShouldProcess($AdapterName, "Set-NetAdapterAdvancedProperty '$displayName' = $Value")) {
        Set-NetAdapterAdvancedProperty -Name $AdapterName -DisplayName $displayName -DisplayValue $Value
        Write-GuardLog "apply $displayName $old -> $Value"
    }
    return
}

if ($Guard) {
    $n = 0
    try {
        $n = @(Get-WinEvent -FilterHashtable @{ LogName = 'Microsoft-Windows-WLAN-AutoConfig/Operational'; Id = 8001; StartTime = [datetime]$Since } -ErrorAction Stop).Count
    }
    catch { $n = 0 }
    if ($PSCmdlet.ShouldProcess($AdapterName, "guard: $n x 8001 since $Since")) {
        if ($n -eq 0) {
            Set-NetAdapterAdvancedProperty -Name $AdapterName -DisplayName $displayName -DisplayValue $Previous
            Write-GuardLog "guard ROLLED BACK $displayName -> $Previous (no 8001 since $Since)"
        }
        else {
            Write-GuardLog "guard kept $displayName = $(Get-Mode) ($n x 8001 since $Since)"
        }
        foreach ($t in @($guardTask, $applyTask)) {
            Unregister-ScheduledTask -TaskName $t -Confirm:$false -ErrorAction SilentlyContinue
        }
    }
    return
}

# default mode
$current = Get-Mode
if ($current -eq $Value) {
    Write-Output "$displayName on $AdapterName is already $Value; nothing to do."
    return
}

$now = Get-Date
$guardAt = $now.AddMinutes(11)
$applyAt = $now.AddMinutes(1)
$since = $applyAt.ToString($isoFormat)
$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
$exe = 'powershell.exe'
$common = "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$PSCommandPath`""

if ($PSCmdlet.ShouldProcess($statePath, "write previous value '$current'")) {
    $stateDir = Split-Path -Parent $statePath
    if (-not (Test-Path $stateDir)) { New-Item -ItemType Directory -Path $stateDir -Force | Out-Null }
    [ordered]@{ adapter = $AdapterName; property = $displayName; previous = $current; value = $Value; at = $now.ToString($isoFormat) } |
        ConvertTo-Json | Set-Content -Path $statePath -Encoding UTF8
}
if ($PSCmdlet.ShouldProcess($guardTask, "Register-ScheduledTask once at $($guardAt.ToString($isoFormat)) (rollback to '$current' when no 8001 since $since)")) {
    $action = New-ScheduledTaskAction -Execute $exe -Argument "$common -Guard -AdapterName `"$AdapterName`" -Previous `"$current`" -Since $since"
    $trigger = New-ScheduledTaskTrigger -Once -At $guardAt
    Register-ScheduledTask -TaskName $guardTask -Action $action -Trigger $trigger -Principal $principal -Force | Out-Null
    Write-Output "registered '$guardTask' at $($guardAt.ToString($isoFormat))"
}
if ($PSCmdlet.ShouldProcess($applyTask, "Register-ScheduledTask once at $($applyAt.ToString($isoFormat)) ('$displayName' = $Value)")) {
    $action = New-ScheduledTaskAction -Execute $exe -Argument "$common -Apply -AdapterName `"$AdapterName`" -Value `"$Value`""
    $trigger = New-ScheduledTaskTrigger -Once -At $applyAt
    Register-ScheduledTask -TaskName $applyTask -Action $action -Trigger $trigger -Principal $principal -Force | Out-Null
    Write-Output "registered '$applyTask' at $($applyAt.ToString($isoFormat))"
}
