' Runs a .ps1 with no window at all (#396): the interactive-user scheduled tasks start through
' wscript.exe, because powershell.exe is a console program and its console flashes on the desktop
' before -WindowStyle Hidden takes effect. Usage: wscript.exe //B //Nologo run-hidden.vbs "<script.ps1>"
Dim sh, cmd, rc
Set sh = CreateObject("WScript.Shell")
cmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File """ & WScript.Arguments(0) & """"
rc = sh.Run(cmd, 0, True)
WScript.Quit rc
