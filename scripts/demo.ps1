$ErrorActionPreference = 'Stop'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONUTF8 = '1'
$runtimePython = $env:FINAL_ASSEMBLY_PYTHON
if (-not $runtimePython) { $runtimePython = (Get-Command python -ErrorAction Stop).Source }
Push-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
try {
    & $runtimePython -B (Join-Path $PSScriptRoot 'demo.py') @args
    $result = $LASTEXITCODE
} finally { Pop-Location }
exit $result
