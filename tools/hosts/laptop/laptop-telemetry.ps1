# Always-on telemetry for the laptop: one CSV row a minute with core temperature, CPU package power, clock, battery
# and how many PoB workers are running. Read-only: it polls sensors, it never writes to the hardware.
param(
    [string]$Lhm = 'C:\Coding\tools\LibreHardwareMonitor',
    [string]$Out = 'C:\Coding\poe-junkroan-v2\artifacts\runs\telemetry.csv',
    [int]$EverySec = 60
)
$ErrorActionPreference = 'Continue'
Add-Type -Path (Join-Path $Lhm 'LibreHardwareMonitorLib.dll')
$pc = New-Object LibreHardwareMonitor.Hardware.Computer
$pc.IsCpuEnabled = $true; $pc.IsBatteryEnabled = $true
$pc.Open()
$cpu = $pc.Hardware | Where-Object { $_.HardwareType -eq 'Cpu' } | Select-Object -First 1
$bat = $pc.Hardware | Where-Object { $_.HardwareType -eq 'Battery' } | Select-Object -First 1
foreach ($h in $pc.Hardware) { $h.Update() }
if (-not (Test-Path $Out)) {
    'time,cpu_temp_max_c,cpu_temp_avg_c,pkg_power_w,clock_avg_mhz,load_pct,battery_pct,on_mains,pob_workers,free_ram_gb' |
        Set-Content -Encoding ascii $Out
}
$inv = [Globalization.CultureInfo]::InvariantCulture
while ($true) {
    try {
        foreach ($h in $pc.Hardware) { $h.Update() }
        $temps = @($cpu.Sensors | Where-Object { $_.SensorType -eq 'Temperature' -and $_.Name -like 'CPU Core #*' } | ForEach-Object { $_.Value }) | Where-Object { $_ }
        if (-not $temps) { $temps = @($cpu.Sensors | Where-Object { $_.SensorType -eq 'Temperature' } | ForEach-Object { $_.Value }) | Where-Object { $_ } }
        $pwr = ($cpu.Sensors | Where-Object { $_.SensorType -eq 'Power' -and $_.Name -match 'Package' } | Select-Object -First 1).Value
        $clocks = @($cpu.Sensors | Where-Object { $_.SensorType -eq 'Clock' -and $_.Name -like 'CPU Core #*' } | ForEach-Object { $_.Value }) | Where-Object { $_ }
        $load = ($cpu.Sensors | Where-Object { $_.SensorType -eq 'Load' -and $_.Name -eq 'CPU Total' } | Select-Object -First 1).Value
        $b = Get-CimInstance Win32_Battery -ErrorAction SilentlyContinue | Select-Object -First 1
        $workers = (Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -match 'spawn_main' } | Measure-Object).Count
        $free = (Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1MB
        $row = [string]::Format($inv, '{0},{1:F0},{2:F0},{3:F1},{4:F0},{5:F0},{6},{7},{8},{9:F1}',
            (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'),
            $(if ($temps) { ($temps | Measure-Object -Maximum).Maximum } else { 0 }),
            $(if ($temps) { ($temps | Measure-Object -Average).Average } else { 0 }),
            $(if ($pwr) { $pwr } else { 0 }),
            $(if ($clocks) { ($clocks | Measure-Object -Average).Average } else { 0 }),
            $(if ($load) { $load } else { 0 }),
            $(if ($b) { $b.EstimatedChargeRemaining } else { '' }),
            $(if ($b) { [int]($b.BatteryStatus -ne 1) } else { 1 }),
            $workers, $free)
        Add-Content -Encoding ascii $Out $row
        # keep the file small: trim to the last 20000 rows (about two weeks at a row a minute)
        if ((Get-Item $Out).Length -gt 3MB) {
            $keep = Get-Content $Out -Tail 20000
            $keep | Set-Content -Encoding ascii $Out
        }
    }
    catch { ('{0},error,{1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $_.Exception.Message) | Add-Content -Encoding ascii $Out }
    Start-Sleep -Seconds $EverySec
}
