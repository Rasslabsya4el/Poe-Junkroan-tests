# Wi-Fi guard for the laptop (#1188). A scheduled task runs this once a minute (SYSTEM, hidden).
# Each run: take a lock, check the internet (NCSI + 1.1.1.1 + one DNS name; the gateway is journalled only), decide with
# Get-WifiGuardAction (wifi-guard-decision.ps1). After 15 continuous minutes without internet it cycles the
# Wi-Fi adapter (disable, 10 s, enable, wait up to 60 s for a link and internet) and checks again at once, with
# no growing pause, until internet is back; then it writes a `back` line with the drop's length in minutes.
# Every check and every toggle step is one JSON line in var\wifi-guard\journal.jsonl (the input of the cause hunt).
# The state (NoInternetSince, Toggles, LastCheck) is saved after every decision and in a finally.
# It changes no other setting: no profile, driver, router or power plan.
#
# Test hooks (defaults = the real machine): -ProbeJson <file> gives the probe results (a JSON array, one element
# per probe, the last element repeats) and makes the toggle fake too (no Disable-NetAdapter, no waits);
# -FakeToggle does the same without the probes; -Now 'yyyy-MM-dd HH:mm:ss' overrides the clock, and each fake
# toggle cycle moves that clock on by -ToggleCostSeconds; -Repo points at a tmp root. -Tick is the default single
# run; it is kept so the tests read like power-guard's.
param(
    [string]$Repo = 'C:\Coding\poe-junkroan-v2',
    [string]$Adapter = 'Wi-Fi 2',
    [switch]$Tick,
    [string]$Now = '',
    [string]$ProbeJson = '',
    [switch]$FakeToggle,
    [int]$ToggleCostSeconds = 0
)
$ErrorActionPreference = 'Continue'
. (Join-Path $PSScriptRoot 'wifi-guard-decision.ps1')

$inv = [Globalization.CultureInfo]::InvariantCulture
$utf8 = New-Object System.Text.UTF8Encoding($false)
$dir = Join-Path $Repo 'var\wifi-guard'
$journal = Join-Path $dir 'journal.jsonl'
$journalOld = Join-Path $dir 'journal.old.jsonl'
$stateFile = Join-Path $dir 'state.json'
$lockFile = Join-Path $dir 'guard.lock'
$lockStaleMinutes = 10
$fake = [bool]$ProbeJson
$fakeToggle = $fake -or [bool]$FakeToggle
$script:fakes = @()
# ConvertFrom-Json (Windows PowerShell 5.1) emits a JSON array as one object: the ForEach-Object unrolls it
if ($fake) { $script:fakes = @(Get-Content -LiteralPath $ProbeJson -Raw -Encoding UTF8 | ConvertFrom-Json | ForEach-Object { $_ }) }
$script:fakeIndex = 0
$script:lastFake = $null
# seconds the fake clock has moved on: one toggle cycle each (only the -Now clock reads it)
$script:clockAdd = 0
# the state of this run: saved after every decision and toggle, and in the finally
$script:since = $null
$script:toggles = 0

function Clock {
    if ($Now) { return ([datetime]::ParseExact($Now, 'yyyy-MM-dd HH:mm:ss', $inv)).AddSeconds($script:clockAdd) }
    return Get-Date
}
# the clock for journal lines and the final state save: a bad -Now must not stop them (the error is the line)
function Get-SafeTime {
    try { return (Clock) } catch { return (Get-Date) }
}
function Fmt($t) {
    if ($null -eq $t) { return $null }
    return ([datetime]$t).ToString('yyyy-MM-dd HH:mm:ss', $inv)
}
function ParseTime($s) {
    if (-not $s) { return $null }
    return [datetime]::ParseExact([string]$s, 'yyyy-MM-dd HH:mm:ss', $inv)
}
# Every field collection goes through here: a failure of one writes null for it and the run goes on.
# Write-Output -NoEnumerate keeps an empty or one-element array whole (a plain return would unroll it to $null).
function Get-Field([scriptblock]$Block) {
    try { Write-Output -NoEnumerate (& $Block) } catch { Write-Output -NoEnumerate $null }
}
function Limit-Text([string]$Text, [int]$Max = 1500) {
    if (-not $Text) { return $null }
    if ($Text.Length -gt $Max) { return $Text.Substring(0, $Max) }
    return $Text
}

# "No internet": Windows does not say Internet AND 1.1.1.1 and the DNS name both fail. The gateway is never part
# of the rule (journalled only): the router may still answer while there is no internet.
function Test-NoInternet([string]$Ncsi, [bool]$OutsideReach, [bool]$DnsOk) {
    return (($Ncsi -ne 'Internet') -and (-not $OutsideReach) -and (-not $DnsOk))
}

# One ICMP echo bounded to 2 s (Test-Connection has no timeout parameter in PS 5.1).
function Test-Reach([string]$Address) {
    if (-not $Address) { return $false }
    try {
        $ping = New-Object Net.NetworkInformation.Ping
        try { return ($ping.Send($Address, 2000).Status -eq 'Success') } finally { $ping.Dispose() }
    }
    catch { return $false }
}

function Get-RealProbe {
    $ncsi = Get-Field { (Get-NetConnectionProfile -InterfaceAlias $Adapter -ErrorAction Stop).IPv4Connectivity.ToString() }
    $gw = Get-Field { (Get-NetIPConfiguration -InterfaceAlias $Adapter -ErrorAction Stop).IPv4DefaultGateway.NextHop }
    $gwReach = Test-Reach ([string]$gw)
    $outside = Test-Reach '1.1.1.1'
    # Resolve-DnsName -QuickTimeout bounds the lookup (measured on this PC)
    $dns = Get-Field { (Resolve-DnsName -Name 'www.msftconnecttest.com' -Type A -QuickTimeout -ErrorAction Stop | Where-Object { $_.IPAddress } | Select-Object -First 1).IPAddress }
    return @{ ncsi = $ncsi; gateway = $gw; gateway_reach = [bool]$gwReach; outside_reach = [bool]$outside; dns_result = $dns }
}

function Get-Probe {
    if ($fake) {
        $i = [Math]::Min($script:fakeIndex, $script:fakes.Count - 1)
        $script:fakeIndex++
        $f = $script:fakes[$i]
        $script:lastFake = $f
        $p = @{ ncsi = $f.ncsi; gateway = $f.gateway; gateway_reach = [bool]$f.gateway_reach; outside_reach = [bool]$f.outside_reach; dns_result = $f.dns_result }
    }
    else {
        $p = Get-RealProbe
    }
    $p.internet_ok = -not (Test-NoInternet -Ncsi $p.ncsi -OutsideReach ([bool]$p.outside_reach) -DnsOk ($null -ne $p.dns_result))
    return $p
}

# netsh prints the labels in the Windows display language: a label that does not match gives null (best effort).
# $Label is a regex fragment.
function Find-Wlan([string]$Text, [string]$Label) {
    if (-not $Text) { return $null }
    $m = [regex]::Match($Text, "(?m)^\s*(?:$Label)\s*:\s*(.+?)\s*$")
    if ($m.Success) { return $m.Groups[1].Value }
    return $null
}

# The netsh interface text: signal is the first NN% (any language); the other labels are English and best effort.
function Read-Wlan([string]$Text) {
    $w = @{ ssid = $null; signal_pct = $null; bssid = $null; band = $null; channel = $null; raw = (Limit-Text $Text) }
    if (-not $Text) { return $w }
    $sig = [regex]::Match($Text, '(\d{1,3})\s*%')
    if ($sig.Success) { $w.signal_pct = [int]$sig.Groups[1].Value }
    $w.ssid = Find-Wlan $Text 'SSID'
    $w.bssid = Find-Wlan $Text 'BSSID'
    $ch = Find-Wlan $Text 'Channel'
    if ($ch -match '^\d+$') { $w.channel = [int]$ch }
    $w.band = Find-Wlan $Text 'Band'
    # netsh prints no Band line on some builds: derive it from the channel (1-14 = 2.4 GHz, else 5 GHz)
    if (-not $w.band -and $w.channel) { $w.band = if ($w.channel -le 14) { '2.4 GHz' } else { '5 GHz' } }
    return $w
}

# An empty result throws NoMatchingEventsFound, a missing log NoMatchingLogsFound: both mean "no events".
# Any other error is a failed read and goes to the caller.
function Get-WinEventsSafe([hashtable]$Filter) {
    try { return @(Get-WinEvent -FilterHashtable $Filter -ErrorAction Stop) }
    catch {
        $id = [string]$_.FullyQualifiedErrorId
        if ($id -like 'NoMatchingEventsFound*' -or $id -like 'NoMatchingLogsFound*') { return @() }
        throw
    }
}

function Get-Events {
    # Wi-Fi (WLAN-AutoConfig) ids of the last hour, the named ones included (8003, 11006), and every DHCP client event.
    $since = (Get-Date).AddHours(-1)
    $wlanIds = @(8000, 8001, 8002, 8003, 8011, 11000, 11001, 11002, 11004, 11005, 11006, 11010, 11015, 11032, 12011)
    $all = New-Object System.Collections.ArrayList
    foreach ($e in @(Get-WinEventsSafe @{ LogName = 'Microsoft-Windows-WLAN-AutoConfig/Operational'; Id = $wlanIds; StartTime = $since })) {
        [void]$all.Add(@{ id = [int]$e.Id; time = $e.TimeCreated.ToString('HH:mm:ss', $inv); log = 'wlan' })
    }
    foreach ($e in @(Get-WinEventsSafe @{ LogName = 'Microsoft-Windows-Dhcp-Client/Admin'; StartTime = $since })) {
        [void]$all.Add(@{ id = [int]$e.Id; time = $e.TimeCreated.ToString('HH:mm:ss', $inv); log = 'dhcp' })
    }
    $last = @($all | Select-Object -Last 60)
    return ,$last
}

function Get-RealEnv {
    $wlanText = Get-Field { (netsh wlan show interfaces | Out-String) }
    $w = Read-Wlan ([string]$wlanText)
    $ip = Get-Field { (Get-NetIPAddress -InterfaceAlias $Adapter -AddressFamily IPv4 -ErrorAction Stop | Where-Object { $_.IPAddress -notlike '127.*' } | Select-Object -First 1).IPAddress }
    return @{
        ssid = $w.ssid; signal_pct = $w.signal_pct; bssid = $w.bssid; band = $w.band; channel = $w.channel; wlan_raw = $w.raw
        ipv4 = $ip
        link_local = if ($ip) { [bool]($ip -like '169.254.*') } else { $null }
        dns_servers = Get-Field { (Get-DnsClientServerAddress -InterfaceAlias $Adapter -AddressFamily IPv4 -ErrorAction Stop).ServerAddresses }
        adapter_power_mgmt = Get-Field { (Get-NetAdapterPowerManagement -Name $Adapter -ErrorAction Stop).AllowComputerToTurnOffDevice.ToString() }
        events = Get-Field { Get-Events }
    }
}

# A field the fake probe gives explicitly wins; otherwise the same parser as the real path reads the fake's netsh text.
function Get-Pick($Explicit, $Parsed) {
    if ($null -ne $Explicit) { return $Explicit }
    return $Parsed
}

function Get-FakeEnv {
    $f = $script:lastFake
    if ($null -eq $f) { $f = [pscustomobject]@{} }
    $w = Read-Wlan ([string]$f.wlan_raw)
    $ip = $f.ipv4
    return @{
        ssid = Get-Pick $f.ssid $w.ssid
        signal_pct = Get-Pick $f.signal_pct $w.signal_pct
        bssid = Get-Pick $f.bssid $w.bssid
        band = Get-Pick $f.band $w.band
        channel = Get-Pick $f.channel $w.channel
        wlan_raw = $w.raw
        ipv4 = $ip; link_local = if ($ip) { [bool]($ip -like '169.254.*') } else { $null }
        dns_servers = $f.dns_servers; adapter_power_mgmt = $f.adapter_power_mgmt; events = $f.events
    }
}

function Write-Journal([string]$Kind, $Probe, [hashtable]$Fields) {
    try {
        $envf = if ($fake) { Get-FakeEnv } else { Get-RealEnv }
        $rec = [ordered]@{ time = (Fmt (Get-SafeTime)); kind = $Kind }
        foreach ($k in 'internet_ok', 'ncsi', 'gateway', 'gateway_reach', 'outside_reach', 'dns_result') {
            $rec[$k] = if ($Probe) { $Probe[$k] } else { $null }
        }
        foreach ($k in $Fields.Keys) { $rec[$k] = $Fields[$k] }
        foreach ($k in 'ssid', 'signal_pct', 'bssid', 'band', 'channel', 'wlan_raw', 'ipv4', 'link_local', 'adapter_power_mgmt') {
            $rec[$k] = $envf[$k]
        }
        # dns_servers is always an array (empty for none, one string stays a list)
        $rec['dns_servers'] = [string[]]@($envf['dns_servers'] | Where-Object { $null -ne $_ -and "$_" -ne '' })
        # events is an array (empty when none was found) and null only when its read failed
        $rec['events'] = $null
        if ($null -ne $envf['events']) { $rec['events'] = [object[]]@($envf['events'] | ForEach-Object { $_ }) }
        $line = $rec | ConvertTo-Json -Compress -Depth 6
        if ((Test-Path -LiteralPath $journal) -and ((Get-Item -LiteralPath $journal).Length -gt 5MB)) {
            Move-Item -LiteralPath $journal -Destination $journalOld -Force
        }
        [IO.File]::AppendAllText($journal, $line + "`n", $utf8)
    }
    catch {
        # the journal must never stop the guard; a line that cannot be written is lost, the run goes on
    }
}

function Read-State {
    $s = @{ NoInternetSince = $null; Toggles = 0; LastCheck = $null }
    if (-not (Test-Path -LiteralPath $stateFile)) { return $s }
    try {
        $j = Get-Content -LiteralPath $stateFile -Raw -Encoding UTF8 | ConvertFrom-Json
        $s.NoInternetSince = ParseTime $j.NoInternetSince
        if ($null -ne $j.Toggles) { $s.Toggles = [int]$j.Toggles }
        $s.LastCheck = ParseTime $j.LastCheck
    }
    catch {
        return @{ NoInternetSince = $null; Toggles = 0; LastCheck = $null }
    }
    return $s
}

function Save-State($Since, [int]$Toggles, $At) {
    $obj = [ordered]@{ NoInternetSince = (Fmt $Since); Toggles = $Toggles; LastCheck = (Fmt $At) }
    [IO.File]::WriteAllText($stateFile, ($obj | ConvertTo-Json), $utf8)
}

# Saves the run's state; never throws (it runs in the finally and after every decision).
function Save-RunState {
    try { Save-State $script:since $script:toggles (Get-SafeTime) } catch { }
}

function Test-LinkUp {
    if ($fakeToggle) { return $true }
    $st = Get-Field { (Get-NetAdapter -Name $Adapter -ErrorAction Stop).Status }
    return ([string]$st -eq 'Up')
}

# One toggle cycle: disable, 10 s, enable. The fake path (-ProbeJson / -FakeToggle) never calls the adapter cmdlets.
function Invoke-Toggle($Probe, [int]$Toggles) {
    Write-Journal 'toggle-off' $Probe @{ toggles = $Toggles }
    $err = $null
    if (-not $fakeToggle) {
        try { Disable-NetAdapter -Name $Adapter -Confirm:$false -ErrorAction Stop } catch { $err = 'disable: ' + $_.Exception.Message }
    }
    Start-Sleep -Seconds $(if ($fakeToggle) { 0 } else { 10 })
    if (-not $fakeToggle) {
        try { Enable-NetAdapter -Name $Adapter -Confirm:$false -ErrorAction Stop } catch { $err = 'enable: ' + $_.Exception.Message }
    }
    $script:clockAdd += $ToggleCostSeconds
    Write-Journal 'toggle-on' $null @{ toggles = $Toggles; error = $err }
    Save-RunState
}

# After the enable: poll every 5 s for up to 60 s until the link is up and internet answers (fake: one probe).
# The budget is checked before each sleep, so the last probe starts by ~60 s; each probe is bounded (two 2 s pings
# and Resolve-DnsName -QuickTimeout), so the wait ends by about 68 s.
function Wait-Internet {
    $budget = if ($fakeToggle) { 0 } else { 60 }
    $start = Get-Date
    $p = Get-Probe
    Touch-Lock
    while (-not ($p.internet_ok -and (Test-LinkUp))) {
        $left = $budget - ((Get-Date) - $start).TotalSeconds
        if ($left -le 0) { break }
        Start-Sleep -Seconds ([int][Math]::Ceiling([Math]::Min(5, $left)))
        Touch-Lock
        $p = Get-Probe
    }
    return $p
}

function Invoke-Tick {
    $st = Read-State
    $script:since = $st.NoInternetSince
    $script:toggles = $st.Toggles
    $gap = $false
    $tickAt = Clock
    if ($null -ne $st.LastCheck -and ($tickAt - $st.LastCheck).TotalMinutes -gt 5) {
        # the task did not run for over 5 min (laptop asleep): the drop cannot be known to be continuous, start again
        $script:since = $null
        $script:toggles = 0
        $gap = $true
    }
    $probe = Get-Probe
    while ($true) {
        Touch-Lock
        # the real clock at each decision (not the tick start): after toggle cycles the drop must count them
        $at = Clock
        $dec = Get-WifiGuardAction -State @{ NoInternetSince = $script:since; Toggles = $script:toggles } -InternetOk ([bool]$probe.internet_ok) -Now $at
        $dropMin = $null
        if ($null -ne $script:since) { $dropMin = [math]::Round(($at - [datetime]$script:since).TotalMinutes, 1) }
        $before = $script:toggles
        $script:since = $dec.State.NoInternetSince
        $script:toggles = [int]$dec.State.Toggles
        if ($dec.Action -eq 'done') {
            Write-Journal 'check' $probe @{ action = 'done'; toggles = $before; drop_minutes = $dropMin; gap_reset = $gap }
            Write-Journal 'back' $probe @{ toggles = $before; drop_minutes = $dropMin }
            Save-RunState
            break
        }
        Write-Journal 'check' $probe @{ action = $dec.Action; toggles = $script:toggles; drop_minutes = $dropMin; gap_reset = $gap }
        Save-RunState
        $gap = $false
        if ($dec.Action -ne 'toggle') { break }
        Invoke-Toggle $probe $script:toggles
        $probe = Wait-Internet
    }
}

# The lock file holds the pid of the run that took it; its last write time is the last refresh.
# A lock is held when that refresh is under 10 min old AND the pid is alive; otherwise it is taken over.
function Test-LockHeld {
    try {
        if (-not (Test-Path -LiteralPath $lockFile)) { return $false }
        $raw = Get-Content -LiteralPath $lockFile -Raw -ErrorAction SilentlyContinue
        $heldPid = 0
        if (-not ($raw -and [int]::TryParse($raw.Trim(), [ref]$heldPid))) { return $false }
        $age = (Get-Date) - (Get-Item -LiteralPath $lockFile).LastWriteTime
        return ($age.TotalMinutes -lt $lockStaleMinutes -and [bool](Get-Process -Id $heldPid -ErrorAction SilentlyContinue))
    }
    catch { return $false }
}

# Atomic create (CreateNew fails when the file exists): two runs cannot both take it.
function Enter-Lock {
    for ($attempt = 0; $attempt -lt 2; $attempt++) {
        try {
            $fs = [IO.File]::Open($lockFile, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
            try {
                $bytes = [Text.Encoding]::ASCII.GetBytes([string]$PID)
                $fs.Write($bytes, 0, $bytes.Length)
            }
            finally { $fs.Close() }
            return $true
        }
        catch {
            if (Test-LockHeld) { return $false }
            Remove-Item -LiteralPath $lockFile -Force -ErrorAction SilentlyContinue
        }
    }
    return $false
}

# Refresh the lock's timestamp: called every loop cycle and before each wait step.
function Touch-Lock {
    try { [IO.File]::SetLastWriteTime($lockFile, (Get-Date)) } catch { }
}

# Delete the lock only while it still holds this run's pid (a takeover by another run must not be removed).
function Remove-OwnLock {
    try {
        if ((Test-Path -LiteralPath $lockFile) -and ((Get-Content -LiteralPath $lockFile -Raw).Trim() -eq [string]$PID)) {
            Remove-Item -LiteralPath $lockFile -Force
        }
    }
    catch { }
}

New-Item -ItemType Directory -Force -Path $dir | Out-Null
if (-not (Enter-Lock)) { exit 0 }
try {
    Invoke-Tick
}
catch {
    Write-Journal 'error' $null @{ error = $_.Exception.Message }
}
finally {
    Save-RunState
    Remove-OwnLock
}
exit 0
