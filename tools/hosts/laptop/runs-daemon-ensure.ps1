# Every 5 min (Task Scheduler "junkroan runs daemon ensure", tools/hosts/install.ps1): start the laptop's runs
# daemon when none is alive (#353). Does nothing when the status file shows a live daemon. The laptop's daemon
# runs from its own checkout (config/hosts.json daemon_repo_path).
Set-Location "C:\Coding\poe-junkroan-v2-daemon"
$env:JUNKROAN_HOST = "laptop"
$env:PYTHONPATH = "C:\Coding\poe-junkroan-v2-daemon\src"
$py = 'C:\Program Files\Python312\python.exe'
# #463: the queue's pytest jobs run with this python; keep pytest installed (cheap check, never blocks the watchdog).
try {
    & $py -m pytest --version *> $null
    if ($LASTEXITCODE -ne 0) { & $py -m pip install --user --quiet pytest *> $null }
}
catch { }
& $py -m junkroan.runs.watchdog --host laptop
