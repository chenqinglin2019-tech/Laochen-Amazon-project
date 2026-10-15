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

# config.local.json value selection and diagnostics are shared with bash.
# The Python runtime captures raw account output and never prints credentials.
try {
    . (Join-Path $PSScriptRoot 'auth_python.ps1')
    $arguments = @('check', '--root', $RootDir, '--binary', $AuthBin)
    if ($AllowRecent) { $arguments += '--allow-recent' }
    $status = Invoke-AuthRuntime -Root $RootDir -Arguments $arguments
} catch {
    Stop-StartupFailed '共享鉴权入口无法启动；请安装 Python 3.8+ 并更新完整 Skill 或 runner'
}
exit $status
