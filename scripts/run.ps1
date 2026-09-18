# Keep the caller's working directory. --workspace selects materials explicitly.
$ErrorActionPreference = 'Stop'
$sourceRoot = Split-Path -Parent $PSScriptRoot
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONUTF8 = '1'
$runtimePython = $env:FINAL_ASSEMBLY_PYTHON
if (-not $runtimePython) { $runtimePython = (Get-Command python -ErrorAction Stop).Source }
$previousPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = $sourceRoot + [IO.Path]::PathSeparator + $previousPythonPath
    & $runtimePython -B -m final_assembly @args
    $result = $LASTEXITCODE
} finally { $env:PYTHONPATH = $previousPythonPath }
exit $result
