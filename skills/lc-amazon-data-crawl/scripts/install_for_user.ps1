# One-step Windows installer; mirrors scripts/install_for_user.sh.
# The user runs it in their own terminal (the token prompt is hidden):
#   powershell -ExecutionPolicy Bypass -File <skill>\scripts\install_for_user.ps1 [runner-dir]
param([string]$TargetDir = '', [switch]$ReplaceToken)

$ErrorActionPreference = 'Stop'
$SkillDir = Split-Path -Parent $PSScriptRoot
if (-not $TargetDir) { $TargetDir = Join-Path (Split-Path -Parent $SkillDir) 'lc-amazon-data-crawl-runner' }
if (-not [IO.Path]::IsPathRooted($TargetDir)) { $TargetDir = Join-Path (Get-Location).Path $TargetDir }
$PublicConfig = Join-Path $SkillDir 'config.json'
$LocalConfig = Join-Path $SkillDir 'config.local.json'

function Write-Stderr([string]$Text) { [Console]::Error.WriteLine($Text) }

# Best-effort equivalent of chmod 600: only the current user can read the file.
function Protect-UserFile([string]$Path) {
    try {
        $acl = Get-Acl -LiteralPath $Path
        $acl.SetAccessRuleProtection($true, $false)
        foreach ($rule in @($acl.Access)) { [void]$acl.RemoveAccessRule($rule) }
        $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
        $owner = New-Object System.Security.AccessControl.FileSystemAccessRule($identity, 'FullControl', 'Allow')
        $acl.SetAccessRule($owner)
        Set-Acl -LiteralPath $Path -AclObject $acl
    } catch { }
}

try { . (Join-Path $PSScriptRoot 'auth_python.ps1') } catch {
    Write-Stderr '鉴权程序启动准备失败：共享鉴权入口缺失。'
    exit 3
}

if (-not (Test-Path -LiteralPath $PublicConfig -PathType Leaf)) {
    Write-Stderr '缺少 config.json；请使用完整的 Skill 发布包。'
    exit 2
}

$configured = 1
if (-not $ReplaceToken) {
    try { $configured = Invoke-AuthRuntime -Root $SkillDir -Arguments @('configured', '--root', $SkillDir) }
    catch { Write-Stderr '鉴权程序启动准备失败：请安装 Python 3.8+ 并使用完整 Skill。'; exit 3 }
    if ($configured -ne 0 -and $configured -ne 1) { exit $configured }
}
if ($configured -eq 1) {
    $secureToken = $null
    $inputRedirected = $false
    try { $inputRedirected = [Console]::IsInputRedirected } catch { $inputRedirected = $false }
    if (-not $inputRedirected) {
        try {
            $secureToken = Read-Host -AsSecureString -Prompt '请输入你自己的云端授权令牌（输入不会显示）'
        } catch {
            $secureToken = $null
        }
    }
    if ($null -eq $secureToken) {
        Write-Stderr '未读到授权令牌；安装已停止。请在你自己的 PowerShell 窗口中运行此安装程序并输入令牌。'
        exit 2
    }
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureToken)
    try {
        $token = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }
    if ([string]::IsNullOrWhiteSpace($token)) {
        Write-Stderr '授权令牌不能为空；安装已停止。'
        exit 2
    }
    try {
        $saved = Invoke-AuthRuntime -Root $SkillDir -Arguments @('configure', '--root', $SkillDir, '--token-stdin') -HasInput -InputText $token.Trim()
        if ($saved -ne 0) { exit $saved }
        Protect-UserFile $LocalConfig
        Protect-UserFile $PublicConfig
    } catch {
        Write-Stderr '写入 config.local.json 失败，安装已停止；请检查当前用户的目录权限。'
        exit 2
    } finally {
        $token = $null
        $secureToken = $null
    }
}

# One cloud-auth call per installation: setup, install and doctor below honor
# this marker for up to 10 minutes (crawl commands never do).
$global:LASTEXITCODE = 3
& ([IO.Path]::Combine($SkillDir, 'scripts', 'check_auth.ps1'))
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$env:LC_AUTH_VERIFIED_AT = [string][DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
$env:LC_AUTH_VERIFIED_CONFIG = Get-AuthFingerprint $SkillDir

$global:LASTEXITCODE = 3
& ([IO.Path]::Combine($SkillDir, 'scripts', 'setup_runner.ps1')) $TargetDir
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if ($env:LC_AMAZON_INSTALL_SETUP_ONLY -ne '1') {
    $launcher = Join-Path $TargetDir 'lc-amazon-data-crawl.ps1'
    foreach ($step in @('install', 'doctor')) {
        $global:LASTEXITCODE = 3
        & $launcher $step
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
}
Write-Output ('安装完成。Runner：' + $TargetDir)
exit 0
