# Runner launcher for Windows PowerShell 5.1+ (use lc-amazon-data-crawl.cmd).
# Same command set and exit codes as lc-amazon-data-crawl.sh; crawler exit codes
# (0/10/20/21/30/40/50/2) are passed through unchanged.

# Native tools write progress to stderr; with 'Stop' Windows PowerShell 5.1 can
# turn that into a terminating error, so every step checks $LASTEXITCODE instead.
$ErrorActionPreference = 'Continue'
$RootDir = $PSScriptRoot
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
try { [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false) } catch { }

function Write-Stderr([string]$Text) { [Console]::Error.WriteLine($Text) }

function Get-VenvPython([string]$VenvDir) {
    $windowsPython = [IO.Path]::Combine($VenvDir, 'Scripts', 'python.exe')
    $posixPython = [IO.Path]::Combine($VenvDir, 'bin', 'python')
    if (Test-Path -LiteralPath $windowsPython -PathType Leaf) { return $windowsPython }
    if (Test-Path -LiteralPath $posixPython -PathType Leaf) { return $posixPython }
    return $windowsPython
}

function Get-RunnerScript([string]$Name) {
    return [IO.Path]::Combine($RootDir, 'scripts', $Name)
}

$script:VenvDir = Join-Path $RootDir '.venv'
if (Test-Path -LiteralPath (Get-VenvPython (Join-Path $RootDir '.venv-scrapling')) -PathType Leaf) {
    $script:VenvDir = Join-Path $RootDir '.venv-scrapling'
}
$script:PythonBin = Get-VenvPython $script:VenvDir

function Show-Usage([switch]$ToStderr) {
    $text = @'
Usage:
  .\lc-amazon-data-crawl.cmd install
  .\lc-amazon-data-crawl.cmd install-browser
  .\lc-amazon-data-crawl.cmd doctor
  .\lc-amazon-data-crawl.cmd amazon-front-dry-run [--config config/amazon_front_keyword_search.json] [--operation-mode supervised|unattended]
  .\lc-amazon-data-crawl.cmd amazon-front-run [--config config/amazon_front_storefront.json] [--operation-mode supervised|unattended]
  .\lc-amazon-data-crawl.cmd category-rank-dry-run [--config config/category_rank_crawler.json]
  .\lc-amazon-data-crawl.cmd category-rank-run [--config config/category_rank_crawler.json] [--operation-mode supervised|unattended]
  .\lc-amazon-data-crawl.cmd image-competitor-dry-run [--config config/amazon_image_competitors.json]
  .\lc-amazon-data-crawl.cmd image-competitor-run [--config config/amazon_image_competitors.json] [--operation-mode supervised|unattended]
  .\lc-amazon-data-crawl.cmd cdp-browser-start --config <config-file>
  .\lc-amazon-data-crawl.cmd sellersprite-check --config <config-file>
  .\lc-amazon-data-crawl.cmd safety-status
  .\lc-amazon-data-crawl.cmd safety-clear --confirm-reviewed
'@
    if ($ToStderr) { Write-Stderr $text } else { Write-Output $text }
}

function Stop-OnFailure {
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

function Invoke-CloudAuth([switch]$AllowRecent) {
    $authScript = Get-RunnerScript 'check_auth.ps1'
    if (-not (Test-Path -LiteralPath $authScript -PathType Leaf)) {
        Write-Stderr '云端鉴权工具缺失，本轮不继续执行。'
        exit 2
    }
    # check_auth.ps1 always ends with an explicit exit; anything else is a startup failure.
    $global:LASTEXITCODE = 3
    if ($AllowRecent) { & $authScript -AllowRecent } else { & $authScript }
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

function Assert-Installed {
    if (-not (Test-Path -LiteralPath $script:PythonBin -PathType Leaf)) {
        Write-Stderr 'Missing .venv. Run: .\lc-amazon-data-crawl.cmd install'
        exit 2
    }
}

function Find-BasePython {
    # 'py -3' is the py launcher's newest 3.x (e.g. a python.org 3.14 install
    # without python.exe on PATH); the version check below still applies.
    foreach ($spec in @('py -3.13', 'py -3.12', 'py -3.11', 'py -3.10', 'py -3', 'python', 'python3')) {
        $parts = $spec.Split(' ')
        $exe = $parts[0]
        $prefix = @($parts | Select-Object -Skip 1)
        if (-not (Get-Command $exe -CommandType Application -ErrorAction SilentlyContinue)) { continue }
        $version = & $exe @prefix -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $version) { continue }
        try { $parsed = [version]([string]$version).Trim() } catch { continue }
        if ($parsed -ge [version]'3.10') {
            return @{ Exe = $exe; Prefix = $prefix }
        }
    }
    return $null
}

function Install-Runner {
    $base = Find-BasePython
    if ($null -eq $base) {
        Write-Stderr 'Scrapling requires Python 3.10 or newer.'
        exit 2
    }
    if (Test-Path -LiteralPath $script:PythonBin -PathType Leaf) {
        & $script:PythonBin -c 'import sys; raise SystemExit(sys.version_info < (3, 10))'
        if ($LASTEXITCODE -ne 0) {
            $script:VenvDir = Join-Path $RootDir '.venv-scrapling'
            $script:PythonBin = Get-VenvPython $script:VenvDir
        }
    }
    if (-not (Test-Path -LiteralPath $script:PythonBin -PathType Leaf)) {
        $prefix = $base.Prefix
        & $base.Exe @prefix -m venv $script:VenvDir
        Stop-OnFailure
        $script:PythonBin = Get-VenvPython $script:VenvDir
    }
    & $script:PythonBin -m pip install --upgrade pip
    Stop-OnFailure
    & $script:PythonBin -m pip install -r (Join-Path $RootDir 'requirements.txt')
    Stop-OnFailure
    # Deliberately no browser download here: run install-browser once when
    # doctor reports chrome_for_testing: missing.
    & $script:PythonBin -c "from playwright.sync_api import sync_playwright; print('playwright CDP runtime: ok')"
    Stop-OnFailure
}

function Install-Browser {
    # Playwright's Chromium honors --load-extension and is found by
    # chrome_binary:auto under %LOCALAPPDATA%\ms-playwright.
    & $script:PythonBin -m playwright install chromium
    Stop-OnFailure
}

function Write-DoubaoStatus([string]$Name, [string]$RelativePath, [string[]]$Fields) {
    $path = Join-Path $RootDir $RelativePath
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        Write-Output ($Name + ': missing')
        return
    }
    $ready = $false
    try {
        $payload = [IO.File]::ReadAllText($path, [Text.Encoding]::UTF8) | ConvertFrom-Json
        if ($payload -is [System.Management.Automation.PSCustomObject]) {
            $ready = $true
            foreach ($field in $Fields) {
                $value = $payload.$field
                if (-not ($value -is [string]) -or [string]::IsNullOrWhiteSpace($value)) { $ready = $false }
            }
        }
    } catch {
        $ready = $false
    }
    if ($ready) { Write-Output ($Name + ': ready') } else { Write-Output ($Name + ': unconfigured') }
}

function Invoke-Doctor {
    Write-Output ('runner: ' + $RootDir)
    if (Test-Path -LiteralPath $script:PythonBin -PathType Leaf) {
        Write-Output ('python: ok (' + $script:PythonBin + ')')
        & $script:PythonBin -c "import playwright; print('playwright: ok')"
        Stop-OnFailure
        & $script:PythonBin -c "import selenium; print('selenium: ok')"
        Stop-OnFailure
        & $script:PythonBin (Get-RunnerScript 'start_cdp_browser.py') --diagnose
        Stop-OnFailure
    } else {
        Write-Output 'python: missing .venv'
    }
    foreach ($file in @(
            'config/amazon_delivery_locations.json',
            'config/amazon_front_keyword_search.json',
            'config/amazon_front_storefront.json',
            'config/amazon_front_bsr_category.json',
            'config/category_rank_crawler.json',
            'config/amazon_image_competitors.json',
            'inputs/keywords.example.csv',
            'inputs/storefronts.example.csv',
            'inputs/image_competitors.example.csv')) {
        if (Test-Path -LiteralPath (Join-Path $RootDir $file) -PathType Leaf) {
            Write-Output ($file + ': ok')
        } else {
            Write-Output ($file + ': missing')
        }
    }
    Write-DoubaoStatus 'doubao_embedding_vision' 'config/doubao_embedding_vision.json' @('api_key', 'model', 'base_url', 'api_path', 'encoding_format')
    Write-DoubaoStatus 'doubao_same_product_mini' 'config/doubao_same_product_mini.json' @('api_key', 'model', 'base_url', 'api_path')
}

function Start-ReuseBrowserIfNeeded([string]$DefaultConfig, [string[]]$Arguments) {
    $configPath = $DefaultConfig
    $previous = ''
    foreach ($argument in $Arguments) {
        if ($previous -eq '--config') {
            $configPath = $argument
            $previous = ''
            continue
        }
        if ($argument -eq '--config') {
            $previous = '--config'
        } elseif ($argument -like '--config=*') {
            $configPath = $argument.Substring('--config='.Length)
        }
    }
    # Never touch the browser while another crawl owns this machine (exit 50).
    & $script:PythonBin (Get-RunnerScript 'safety_cli.py') guard
    Stop-OnFailure
    & $script:PythonBin (Get-RunnerScript 'start_cdp_browser.py') --if-needed --config $configPath
    Stop-OnFailure
}

function Invoke-RunnerPython([string]$ScriptName, [string[]]$Arguments) {
    & $script:PythonBin (Get-RunnerScript $ScriptName) @Arguments
    exit $LASTEXITCODE
}

# PowerShell -File (the .cmd shim) splits '--config=C:\x.json' at the drive
# colon into '--config=C' and '\x.json' (the colon is dropped). Rebuild it;
# when the path part is missing, stop with a config error (exit 40).
function Repair-SplitConfigArgument([string[]]$Arguments) {
    $repaired = New-Object 'System.Collections.Generic.List[string]'
    $index = 0
    while ($index -lt $Arguments.Count) {
        $argument = $Arguments[$index]
        if ($argument -match '^--config=([A-Za-z]):?$' -and ($index + 1) -lt $Arguments.Count) {
            $drive = $Matches[1]
            $next = $Arguments[$index + 1]
            if ([string]::IsNullOrEmpty($next) -or $next -like '-*') {
                Write-Stderr ('--config=' + $drive + ':... 被 PowerShell 在盘符冒号处拆开，读不到配置路径。')
                Write-Stderr '请改用：--config <配置文件路径>（--config 和路径之间用空格，例如 --config "C:\路径\配置.json"）'
                exit 40
            }
            $repaired.Add('--config=' + $drive + ':' + $next)
            $index += 2
            continue
        }
        $repaired.Add($argument)
        $index++
    }
    return $repaired.ToArray()
}

$Command = 'help'
$Rest = @()
if ($args.Count -ge 1) { $Command = [string]$args[0] }
if ($args.Count -ge 2) { $Rest = @($args[1..($args.Count - 1)] | ForEach-Object { [string]$_ }) }
$Rest = @(Repair-SplitConfigArgument $Rest)

switch -Exact ($Command) {
    'install' {
        Invoke-CloudAuth -AllowRecent
        Install-Runner
        exit 0
    }
    'install-browser' {
        Invoke-CloudAuth
        Assert-Installed
        Install-Browser
        exit 0
    }
    'doctor' {
        Invoke-CloudAuth -AllowRecent
        Invoke-Doctor
        exit 0
    }
    'amazon-front-dry-run' {
        Invoke-CloudAuth
        Assert-Installed
        Invoke-RunnerPython 'run_amazon_front_crawl.py' (@('--dry-run') + $Rest)
    }
    'amazon-front-run' {
        Invoke-CloudAuth
        Assert-Installed
        Start-ReuseBrowserIfNeeded 'config/amazon_front_crawler.json' $Rest
        Invoke-RunnerPython 'run_amazon_front_crawl.py' $Rest
    }
    'amazon-front-supervise' {
        Invoke-CloudAuth
        Assert-Installed
        Invoke-RunnerPython 'supervise_amazon_front.py' $Rest
    }
    'verify-output' {
        Invoke-CloudAuth
        Assert-Installed
        Invoke-RunnerPython 'verify_front_output.py' $Rest
    }
    'category-rank-dry-run' {
        Invoke-CloudAuth
        Assert-Installed
        Invoke-RunnerPython 'run_category_rank_crawl.py' (@('--dry-run') + $Rest)
    }
    'category-rank-run' {
        Invoke-CloudAuth
        Assert-Installed
        Start-ReuseBrowserIfNeeded 'config/category_rank_crawler.json' $Rest
        Invoke-RunnerPython 'run_category_rank_crawl.py' $Rest
    }
    'image-competitor-dry-run' {
        Invoke-CloudAuth
        Assert-Installed
        Invoke-RunnerPython 'run_amazon_image_competitor_crawl.py' (@('--dry-run') + $Rest)
    }
    'image-competitor-run' {
        Invoke-CloudAuth
        Assert-Installed
        Start-ReuseBrowserIfNeeded 'config/amazon_image_competitors.json' $Rest
        Invoke-RunnerPython 'run_amazon_image_competitor_crawl.py' $Rest
    }
    'cdp-browser-start' {
        Invoke-CloudAuth
        Assert-Installed
        Invoke-RunnerPython 'start_cdp_browser.py' $Rest
    }
    'sellersprite-check' {
        Invoke-CloudAuth
        Assert-Installed
        Start-ReuseBrowserIfNeeded 'config/amazon_front_keyword_search.json' $Rest
        Invoke-RunnerPython 'run_sellersprite_check.py' $Rest
    }
    'safety-status' {
        Assert-Installed
        Invoke-RunnerPython 'safety_cli.py' @('status')
    }
    'safety-clear' {
        Assert-Installed
        Invoke-RunnerPython 'safety_cli.py' (@('clear') + $Rest)
    }
    { $_ -in @('help', '-h', '--help') } {
        Show-Usage
        exit 0
    }
    default {
        Write-Stderr ('Unknown command: ' + $Command)
        Show-Usage -ToStderr
        exit 2
    }
}
exit 0
