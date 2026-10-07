# Create or refresh a runner on Windows; mirrors scripts/setup_runner.sh.
# Keeps existing configs, inputs, outputs and credentials. The runner gets both
# launchers (lc-amazon-data-crawl.cmd/.ps1 and lc-amazon-data-crawl.sh).
param([string]$TargetDir = '')

$ErrorActionPreference = 'Stop'
$SkillDir = Split-Path -Parent $PSScriptRoot
if (-not $TargetDir) { $TargetDir = Join-Path (Get-Location).Path 'lc-amazon-data-crawl-runner' }
if (-not [IO.Path]::IsPathRooted($TargetDir)) { $TargetDir = Join-Path (Get-Location).Path $TargetDir }
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)

function Write-Stderr([string]$Text) { [Console]::Error.WriteLine($Text) }

function Get-SkillPath([string[]]$Parts) {
    return [IO.Path]::Combine([string[]](@($SkillDir) + $Parts))
}

function Get-TargetPath([string[]]$Parts) {
    return [IO.Path]::Combine([string[]](@($TargetDir) + $Parts))
}

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

function Copy-IfMissing([string]$Source, [string]$Destination) {
    if (-not (Test-Path -LiteralPath $Destination -PathType Leaf)) {
        Copy-Item -LiteralPath $Source -Destination $Destination
    }
}

# --- cloud auth first: nothing is written when it fails ----------------------
$authScript = Get-SkillPath @('scripts', 'check_auth.ps1')
$global:LASTEXITCODE = 3
& $authScript -AllowRecent
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

foreach ($directory in @('scripts', 'config', 'inputs', 'outputs', 'chrome_profiles', 'tools\bin')) {
    New-Item -ItemType Directory -Force -Path (Join-Path $TargetDir $directory) | Out-Null
}

# Skill-maintenance tools are not copied: nothing in a runner imports them.
foreach ($scriptFile in @(Get-ChildItem -LiteralPath (Get-SkillPath @('scripts')) -Filter '*.py' -File)) {
    if (@('migrate_unique_runner.py', 'package_skill.py') -contains $scriptFile.Name) { continue }
    Copy-Item -LiteralPath $scriptFile.FullName -Destination (Get-TargetPath @('scripts', $scriptFile.Name)) -Force
}
foreach ($authEntry in @('check_auth.sh', 'check_auth.ps1')) {
    $source = Get-SkillPath @('scripts', $authEntry)
    if (Test-Path -LiteralPath $source -PathType Leaf) {
        Copy-Item -LiteralPath $source -Destination (Get-TargetPath @('scripts', $authEntry)) -Force
    }
}
Copy-Item -LiteralPath (Get-SkillPath @('assets', 'requirements.txt')) -Destination (Get-TargetPath @('requirements.txt')) -Force

foreach ($configFile in @(Get-ChildItem -LiteralPath (Get-SkillPath @('assets', 'config')) -Filter '*.json' -File)) {
    if (@('doubao_embedding_vision.example.json', 'doubao_same_product_mini.example.json') -contains $configFile.Name) { continue }
    Copy-IfMissing $configFile.FullName (Get-TargetPath @('config', $configFile.Name))
}

foreach ($doubaoName in @('doubao_embedding_vision', 'doubao_same_product_mini')) {
    $doubaoConfig = Get-TargetPath @('config', ($doubaoName + '.json'))
    Copy-IfMissing (Get-SkillPath @('assets', 'config', ($doubaoName + '.example.json'))) $doubaoConfig
    Protect-UserFile $doubaoConfig
}

$GitIgnore = Get-TargetPath @('.gitignore')
if (-not (Test-Path -LiteralPath $GitIgnore -PathType Leaf)) { [IO.File]::WriteAllText($GitIgnore, '', $Utf8NoBom) }
function Add-IgnoreLine([string]$Line, [string]$Comment = '') {
    $existing = @([IO.File]::ReadAllLines($GitIgnore))
    if ($existing -ccontains $Line) { return }
    $text = ''
    if ($Comment) { $text += "`n" + $Comment + "`n" }
    [IO.File]::AppendAllText($GitIgnore, $text + $Line + "`n", $Utf8NoBom)
}
Add-IgnoreLine 'config/doubao_embedding_vision.json' '# Local API credentials'
Add-IgnoreLine 'config/doubao_same_product_mini.json'
foreach ($ignored in @('outputs/', 'chrome_profiles/', '_archive/', '.venv/', '.venv-scrapling/', 'inputs/', 'config.local.json')) {
    Add-IgnoreLine $ignored
}

$runnerConfig = Get-TargetPath @('config.json')
Copy-IfMissing (Get-SkillPath @('config.json')) $runnerConfig
Protect-UserFile $runnerConfig
$skillLocalConfig = Get-SkillPath @('config.local.json')
$runnerLocalConfig = Get-TargetPath @('config.local.json')
if (Test-Path -LiteralPath $skillLocalConfig -PathType Leaf) { Copy-IfMissing $skillLocalConfig $runnerLocalConfig }
if (Test-Path -LiteralPath $runnerLocalConfig -PathType Leaf) { Protect-UserFile $runnerLocalConfig }
Add-IgnoreLine 'config.json'

$skillTools = Get-SkillPath @('tools', 'bin')
if (Test-Path -LiteralPath $skillTools -PathType Container) {
    foreach ($tool in @(Get-ChildItem -LiteralPath $skillTools -File)) {
        Copy-Item -LiteralPath $tool.FullName -Destination (Get-TargetPath @('tools', 'bin', $tool.Name)) -Force
    }
}

foreach ($inputFile in @(Get-ChildItem -LiteralPath (Get-SkillPath @('assets', 'inputs')) -File)) {
    Copy-IfMissing $inputFile.FullName (Get-TargetPath @('inputs', $inputFile.Name))
}
Copy-IfMissing (Get-TargetPath @('config', 'amazon_front_keyword_search.json')) (Get-TargetPath @('config', 'amazon_front_crawler.json'))

# --- config migration (same script the bash setup runs) ----------------------
$migrationPython = $null
$migrationPrefix = @()
foreach ($candidate in @(
        [IO.Path]::Combine($TargetDir, '.venv-scrapling', 'Scripts', 'python.exe'),
        [IO.Path]::Combine($TargetDir, '.venv', 'Scripts', 'python.exe'))) {
    if (Test-Path -LiteralPath $candidate -PathType Leaf) { $migrationPython = $candidate; break }
}
if ($null -eq $migrationPython) {
    foreach ($spec in @('py -3', 'python', 'python3')) {
        $parts = $spec.Split(' ')
        $exe = $parts[0]
        $prefix = @($parts | Select-Object -Skip 1)
        if (Get-Command $exe -CommandType Application -ErrorAction SilentlyContinue) {
            $ErrorActionPreference = 'Continue'
            & $exe @prefix -c 'import sys; raise SystemExit(sys.version_info < (3, 8))' 2>$null
            $probe = $LASTEXITCODE
            $ErrorActionPreference = 'Stop'
            if ($probe -eq 0) {
                $migrationPython = $exe
                $migrationPrefix = $prefix
                break
            }
        }
    }
}
if ($null -eq $migrationPython) {
    Write-Stderr '没有找到 Python 3（需要 3.10+，用于 install）。请先安装 Python 后重试。'
    exit 2
}
$ErrorActionPreference = 'Continue'
& $migrationPython @migrationPrefix (Get-SkillPath @('scripts', 'migrate_operation_config.py')) (Get-TargetPath @('config'))
$migrationStatus = $LASTEXITCODE
$ErrorActionPreference = 'Stop'
if ($migrationStatus -ne 0) { exit $migrationStatus }

# --- launchers ---------------------------------------------------------------
# The bash launcher is defined once, inside setup_runner.sh; extract it so a
# runner created on Windows also works from macOS/Linux.
$setupText = [IO.File]::ReadAllText((Get-SkillPath @('scripts', 'setup_runner.sh')), [Text.Encoding]::UTF8)
$launcherMatch = [regex]::Match(
    $setupText,
    '(?ms)^cat > "\$TARGET_DIR/lc-amazon-data-crawl\.sh" <<''EOF''\r?\n(.*?)^EOF\r?$'
)
if (-not $launcherMatch.Success) {
    Write-Stderr 'setup_runner.sh 中没有找到 bash 启动器定义；请使用完整的 Skill 发布包。'
    exit 2
}
$bashLauncher = $launcherMatch.Groups[1].Value -replace "`r`n", "`n"
[IO.File]::WriteAllText((Get-TargetPath @('lc-amazon-data-crawl.sh')), $bashLauncher, $Utf8NoBom)
foreach ($launcherFile in @('lc-amazon-data-crawl.ps1', 'lc-amazon-data-crawl.cmd')) {
    Copy-Item -LiteralPath (Get-SkillPath @('scripts', 'runner', $launcherFile)) -Destination (Get-TargetPath @($launcherFile)) -Force
}

Write-Output ('Created runner at: ' + $TargetDir)
Write-Output 'Next:'
Write-Output ('  cd "' + $TargetDir + '"')
Write-Output '  .\lc-amazon-data-crawl.cmd install'
Write-Output '  .\lc-amazon-data-crawl.cmd doctor'
exit 0
