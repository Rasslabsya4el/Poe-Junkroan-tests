$log = 'C:\Coding\poe-junkroan-v2\artifacts\runs\power-guard.log'
$n = (Get-Process chrome, msedge, firefox, opera, brave -ErrorAction SilentlyContinue | Measure-Object).Count
Get-Process chrome, msedge, firefox, opera, brave -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
$free = (Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1MB
('{0} closed {1} browser processes, free RAM now {2:N1} GB' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $n, $free) | Add-Content -Encoding utf8 $log
