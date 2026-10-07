@echo off
rem Windows shim: runs lc-amazon-data-crawl.ps1 without changing the machine's execution policy.
rem The PowerShell exit code (crawler codes 0/10/20/21/30/40/50/2) is returned unchanged.
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0lc-amazon-data-crawl.ps1" %*
exit /b %ERRORLEVEL%
