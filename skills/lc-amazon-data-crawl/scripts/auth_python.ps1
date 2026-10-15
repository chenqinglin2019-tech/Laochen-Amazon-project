# Shared Python 3.8+ selection for auth/bootstrap; no browser/model dependencies.
function Find-AuthPython {
    foreach ($spec in @('py -3', 'python', 'python3')) {
        $parts = $spec.Split(' ')
        $exe = $parts[0]
        $prefix = @($parts | Select-Object -Skip 1)
        if (Get-Command $exe -CommandType Application -ErrorAction SilentlyContinue) {
            $previous = $ErrorActionPreference
            $ErrorActionPreference = 'Continue'
            & $exe @prefix -c 'import sys; raise SystemExit(sys.version_info < (3, 8))' *> $null
            $probe = $LASTEXITCODE
            $ErrorActionPreference = $previous
            if ($probe -eq 0) { return @{ Exe = $exe; Prefix = $prefix } }
        }
    }
    throw '没有找到 Python 3.8+。'
}

function Invoke-AuthRuntime {
    param([string]$Root, [string[]]$Arguments, [string]$InputText, [switch]$HasInput)
    $python = Find-AuthPython
    $script = [IO.Path]::Combine($Root, 'scripts', 'auth_runtime.py')
    if (-not (Test-Path -LiteralPath $script -PathType Leaf)) { throw '共享鉴权入口缺失。' }
    if (-not $HasInput) {
        $previous = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        & $python.Exe @($python.Prefix) $script @Arguments
        $status = $LASTEXITCODE
        $ErrorActionPreference = $previous
        return [int]$status
    }
    # PowerShell pipelines add a newline and may use a legacy encoding. Write
    # stdin directly as UTF-8; the secret never appears in argv or a temp script.
    $start = New-Object System.Diagnostics.ProcessStartInfo
    $start.FileName = $python.Exe
    $argv = @($python.Prefix) + @($script) + $Arguments
    $quoted = foreach ($value in $argv) {
        '"' + [regex]::Replace([regex]::Replace([string]$value, '(\\*)"', '$1$1\"'), '(\\+)$', '$1$1') + '"'
    }
    $start.Arguments = $quoted -join ' '
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $start.RedirectStandardInput = $true
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    $start.StandardInputEncoding = New-Object System.Text.UTF8Encoding($false)
    $start.StandardOutputEncoding = New-Object System.Text.UTF8Encoding($false)
    $start.StandardErrorEncoding = New-Object System.Text.UTF8Encoding($false)
    $process = [System.Diagnostics.Process]::Start($start)
    $outTask = $process.StandardOutput.ReadToEndAsync()
    $errTask = $process.StandardError.ReadToEndAsync()
    $process.StandardInput.Write($InputText)
    $process.StandardInput.Close()
    $process.WaitForExit()
    # This Python entry emits fixed diagnostics and JSON field names only.
    [Console]::Out.Write($outTask.Result)
    [Console]::Error.Write($errTask.Result)
    return [int]$process.ExitCode
}

function Get-AuthFingerprint([string]$Root) {
    $python = Find-AuthPython
    $script = [IO.Path]::Combine($Root, 'scripts', 'auth_runtime.py')
    $value = & $python.Exe @($python.Prefix) $script fingerprint --root $Root
    if ($LASTEXITCODE -ne 0 -or $value -notmatch '^[a-f0-9]{64}$') { throw '无法核对已验证的云端凭据。' }
    return [string]$value
}
