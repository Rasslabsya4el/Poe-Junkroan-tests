# Give the laptop back to the queue after the owner has finished with the browser: close the
# browsers, restore the host's `normal` budget, put PoB back to Normal priority.
#
# Registered as the scheduled task "junkroan restore after movie", pointed at THIS path in the repo.
# It used to live in C:\Coding\laptop-baseline; when it moved here the task kept the old path and
# would have failed silently, leaving the laptop at the browser budget for good (2026-09-30).
$log = 'C:\Coding\poe-junkroan-v2\artifacts\runs\restore-after-movie.log'
function W($m) { Add-Content -Path $log -Value ((Get-Date).ToString('yyyy-MM-dd HH:mm:ss') + ' ' + $m) }
W 'restore after movie: start'
$n = 0
foreach ($p in 'chrome','msedge','firefox','brave','opera') {
  Get-Process $p -ErrorAction SilentlyContinue | ForEach-Object { try { $_.CloseMainWindow() | Out-Null } catch {} }
}
Start-Sleep -Seconds 20
foreach ($p in 'chrome','msedge','firefox','brave','opera') {
  Get-Process $p -ErrorAction SilentlyContinue | ForEach-Object { try { Stop-Process -Id $_.Id -Force; $n++ } catch {} }
}
W ("closed browser processes: " + $n)

# The budget comes from config/hosts.json through `runs.py mode`, never from a JSON literal here: a
# hand-written copy drifts from the real `normal` mode (this script used to write others=3 and no
# strict_reserve), and one written with Set-Content put a BOM in it that the reader could not parse,
# stalling the laptop for 1 h 30 min (2026-09-24).
# --local is not optional here: this script runs ON the laptop, whose entry in config/hosts.json
# carries an ssh alias for OTHER machines, so without the flag the command ssh-es into this same
# machine and the nested session dies with no output at all (#364).
Set-Location 'C:\Coding\poe-junkroan-v2'
$out = & 'C:\Program Files\Python312\python.exe' scripts\runs.py mode laptop normal --local 2>&1
W ("mode laptop normal --local: " + ($out -join ' '))
$b = [IO.File]::ReadAllBytes('C:\Coding\poe-junkroan-v2\var\machine_budget.json')
W ("budget first bytes " + ($b[0..2] -join ',') + " (123,32,34 or 123,10,32 = no BOM)")
W ("budget now: " + ([IO.File]::ReadAllText('C:\Coding\poe-junkroan-v2\var\machine_budget.json') -replace '\s+', ' '))

$m = 0
Get-Process python -ErrorAction SilentlyContinue | ForEach-Object { try { $_.PriorityClass = 'Normal'; $m++ } catch {} }
W ("priority Normal on " + $m + " python processes")
$os = Get-CimInstance Win32_OperatingSystem
W ("free RAM GB " + [math]::Round($os.FreePhysicalMemory/1MB,1))
W 'restore after movie: done'
