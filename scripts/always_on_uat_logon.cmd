@echo off
cd /d "C:\Users\Windows\Chronos Workspace"
set PATH=%PATH%;C:\Program Files (x86)\cloudflared
powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "C:\Users\Windows\Chronos Workspace\scripts\always_on_uat.ps1" -Port 8080
