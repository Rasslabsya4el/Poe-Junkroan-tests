# Every 5 min (Task Scheduler "junkroan runs daemon ensure", launched through wscript.exe + tools/hosts/run-hidden.vbs so no window shows, #396): start the pc's runs
# daemon when none is alive (#353). Does nothing when the status file shows a live daemon.
Set-Location "C:\Coding\poe-junkroan-v2"
$env:JUNKROAN_HOST = "pc"
$env:PYTHONPATH = "C:\Coding\poe-junkroan-v2\src"
& "C:\Users\user\AppData\Local\Programs\Python\Python312\junkroan.exe" -m junkroan.runs.watchdog --host pc
