# Wait for the laptop to be reachable again, then give it back to the queue: pull its checkouts,
# restore its `normal` budget FROM THIS MACHINE, close any browser left open, PoB back to Normal.
#
# Why this exists: the owner freed the laptop at 20:0x on 2026-09-30 while it was in the middle of one
# of its known network drops (docs/machines/laptop.md: three in 36 h), so the restore could not be
# done then. The laptop's own scheduled task is the other half of the safety net; this half runs from
# the PC so the restore does not depend on that task, or on this session still being alive.
#
# The mode command runs HERE, not on the laptop: from the PC the ssh branch is the correct one. On
# the laptop itself it would need --local, or it ssh-es into itself and dies silently (#364).
param(
    [string]$Repo = "C:\Coding\poe-junkroan-v2",
    [string]$Python = "C:\Users\user\AppData\Local\Programs\Python\Python312\junkroan.exe",
    [int]$DeadlineHours = 12,
    [int]$PollSeconds = 60,
    # Hold off this long before restoring: the owner asked for the laptop "for a couple of hours".
    # 0 = restore as soon as it is reachable (the original case, where he had already finished).
    [int]$DelayMinutes = 0
)
$log = Join-Path $Repo "artifacts\runs\restore-laptop-on-return.log"
function Say([string]$m) {
    "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $m" | Add-Content -Path $log -Encoding utf8
}
if ($DelayMinutes -gt 0) {
    $due = (Get-Date).AddMinutes($DelayMinutes)
    Say "holding off until $($due.ToString('yyyy-MM-dd HH:mm')) ($DelayMinutes min) before restoring the laptop"
    while ((Get-Date) -lt $due) { Start-Sleep -Seconds 60 }
    Say "hold-off over"
}
Say "watcher started, deadline $DeadlineHours h, poll every $PollSeconds s; waiting for the laptop"
$deadline = (Get-Date).AddHours($DeadlineHours)
Set-Location $Repo
while ((Get-Date) -lt $deadline) {
    $probe = & ssh -n -o BatchMode=yes -o ConnectTimeout=15 laptop "Write-Output UP" 2>&1
    if ($probe -match "UP") {
        Say "laptop is back; restoring it"

        $pull = & ssh -n -o BatchMode=yes -o ConnectTimeout=25 laptop "cd C:\Coding\poe-junkroan-v2; git fetch origin main; git merge --ff-only origin/main; git rev-parse --short HEAD; cd C:\Coding\poe-junkroan-v2-daemon; git checkout --detach origin/main; git rev-parse --short HEAD" 2>&1
        Say ("pull: " + (($pull | Select-Object -Last 4) -join ' | '))

        $mode = & $Python scripts\runs.py mode laptop normal 2>&1
        Say ("mode laptop normal: " + ($mode -join ' '))

        $tail = & ssh -n -o BatchMode=yes -o ConnectTimeout=25 laptop "
            `$n = 0
            foreach (`$p in 'chrome','msedge','firefox','brave','opera') {
              Get-Process `$p -ErrorAction SilentlyContinue | ForEach-Object { try { Stop-Process -Id `$_.Id -Force; `$n++ } catch {} }
            }
            Write-Output ('closed browser processes: ' + `$n)
            `$m = 0
            Get-Process python -ErrorAction SilentlyContinue | ForEach-Object { try { `$_.PriorityClass = 'Normal'; `$m++ } catch {} }
            Write-Output ('priority Normal on ' + `$m + ' python processes')
            Write-Output ('budget: ' + ([IO.File]::ReadAllText('C:\Coding\poe-junkroan-v2\var\machine_budget.json') -replace '\s+',' '))
            Write-Output ('free RAM GB ' + [math]::Round((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory/1MB,1))
            Unregister-ScheduledTask -TaskName 'junkroan restore after movie' -Confirm:`$false -ErrorAction SilentlyContinue
            Write-Output 'pending restore task removed'
        " 2>&1
        Say ("laptop: " + (($tail | Where-Object { $_ -ne "" }) -join ' | '))
        Say "restore done"
        exit 0
    }
    Say "laptop still unreachable"
    Start-Sleep -Seconds $PollSeconds
}
Say "deadline passed with the laptop still unreachable; NOT restored"
exit 1
