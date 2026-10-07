# Cloud-auth gate for Windows; mirrors scripts/check_auth.sh.
# Exit codes: 0 verified, 2 auth tool missing, 3 local startup problem, 4 auth denied.
# Never prints the token or the backend response.
param([switch]$AllowRecent)

$ErrorActionPreference = 'Stop'
$RootDir = Split-Path -Parent $PSScriptRoot

function Write-Stderr([string]$Text) { [Console]::Error.WriteLine($Text) }

# -AllowRecent is passed ONLY by setup_runner.ps1 and the launcher's install/doctor
# commands: inside one installation a successful check exported as
# LC_AUTH_VERIFIED_AT (Unix seconds) is reused for at most 10 minutes.
# Crawl commands never pass it and always re-check.
if ($AllowRecent) {
    $verifiedAt = [string]$env:LC_AUTH_VERIFIED_AT
    if ($verifiedAt -match '^\d{1,12}$') {
        $age = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() - [int64]$verifiedAt
        if ($age -ge 0 -and $age -le 600) { exit 0 }
    }
}

# Windows on ARM runs the amd64 build through emulation, as check_auth.sh does.
$AuthBin = [IO.Path]::Combine($RootDir, 'tools', 'bin', 'lc-auth-check-windows-amd64.exe')

function Stop-StartupFailed([string]$Reason) {
    Write-Stderr ('鉴权程序启动准备失败：' + $Reason + '。本轮不继续执行。')
    Write-Stderr ('文件：' + $AuthBin)
    exit 3
}

if (-not (Test-Path -LiteralPath $AuthBin -PathType Leaf)) {
    Write-Stderr '云端鉴权工具缺失，本轮不继续执行。'
    exit 2
}

# A downloaded zip marks files with Mark-of-the-Web (the Windows counterpart of
# the macOS quarantine flag). Removing it is best effort.
try { Unblock-File -LiteralPath $AuthBin -ErrorAction Stop } catch { }

# A published Skill keeps config.json empty; each installation stores its own
# token in the ignored config.local.json.
$AuthConfig = Join-Path $RootDir 'config.json'
$LocalConfig = Join-Path $RootDir 'config.local.json'
if (Test-Path -LiteralPath $LocalConfig -PathType Leaf) { $AuthConfig = $LocalConfig }

$exitCode = $null
try {
    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = $AuthBin
    $startInfo.Arguments = '--config "' + $AuthConfig + '"'
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    # Keep credentials and backend responses out of terminal output.
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $process = [System.Diagnostics.Process]::Start($startInfo)
    $null = $process.StandardOutput.ReadToEndAsync()
    $null = $process.StandardError.ReadToEndAsync()
    $process.WaitForExit()
    $exitCode = [int]$process.ExitCode
} catch {
    Stop-StartupFailed '鉴权程序无法执行，请确认安全软件没有拦截，并将 Skill 安装在当前用户可写的目录'
}

if ($exitCode -eq 0) { exit 0 }
if ($exitCode -lt 0 -or $exitCode -gt 255) {
    Stop-StartupFailed ('鉴权程序无法执行或被系统终止（退出码 ' + $exitCode + '）')
}
Write-Stderr '云端鉴权未通过，本轮不继续执行。'
exit 4
