# One-step Windows installer; mirrors scripts/install_for_user.sh.
# The user runs it in their own terminal (the token prompt is hidden):
#   powershell -ExecutionPolicy Bypass -File <skill>\scripts\install_for_user.ps1 [runner-dir]
param([string]$TargetDir = '')

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

function Test-ConfiguredToken([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $false }
    try {
        $data = [IO.File]::ReadAllText($Path, [Text.Encoding]::UTF8) | ConvertFrom-Json
    } catch {
        return $false
    }
    if (-not ($data -is [System.Management.Automation.PSCustomObject])) { return $false }
    $token = $data.backend_token
    return ($null -ne $token -and -not [string]::IsNullOrWhiteSpace([string]$token))
}

# Atomic write: temp file in the same folder, restricted, then replace.
function Write-LocalConfig([string]$Token) {
    $config = [IO.File]::ReadAllText($PublicConfig, [Text.Encoding]::UTF8) | ConvertFrom-Json
    if (-not ($config -is [System.Management.Automation.PSCustomObject]) -or [string]::IsNullOrWhiteSpace([string]$config.backend_url)) {
        throw '公开配置缺少 backend_url。'
    }
    if ($config.PSObject.Properties.Name -contains 'backend_token') {
        $config.backend_token = $Token
    } else {
        $config | Add-Member -NotePropertyName 'backend_token' -NotePropertyValue $Token
    }
    $json = ($config | ConvertTo-Json -Depth 20) + "`n"
    $temporary = Join-Path $SkillDir ('.config.local.' + [Guid]::NewGuid().ToString('N') + '.tmp')
    try {
        [IO.File]::WriteAllText($temporary, $json, (New-Object System.Text.UTF8Encoding($false)))
        Protect-UserFile $temporary
        if (Test-Path -LiteralPath $LocalConfig -PathType Leaf) {
            [IO.File]::Replace($temporary, $LocalConfig, $null)
        } else {
            [IO.File]::Move($temporary, $LocalConfig)
        }
        Protect-UserFile $LocalConfig
    } finally {
        if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue }
    }
}

if (-not (Test-Path -LiteralPath $PublicConfig -PathType Leaf)) {
    Write-Stderr '缺少 config.json；请使用完整的 Skill 发布包。'
    exit 2
}

if (-not (Test-ConfiguredToken $LocalConfig) -and -not (Test-ConfiguredToken $PublicConfig)) {
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
        Write-LocalConfig $token.Trim()
    } catch {
        Write-Stderr ('写入 config.local.json 失败，安装已停止：' + $_.Exception.Message)
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
