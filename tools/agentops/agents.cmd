@echo off
REM Open the desktop app's agent view for this repo (issue #50). See agents.ps1 for the
REM claude.exe discovery (CLAUDE_EXE overrides it) -- this is a one-line wrapper so the owner
REM can double-click or type `tools\agentops\agents.cmd` without a PowerShell prefix.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0agents.ps1" %*
