# PyGen Windows Installer (No Admin Rights Required)
$ErrorActionPreference = "Stop"

$ScriptDir = ""
if ($PSScriptRoot) {
    $ScriptDir = $PSScriptRoot
} elseif ($MyInvocation.MyCommand.Path) {
    $ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
}

if ($ScriptDir -and (Test-Path (Join-Path $ScriptDir "run.py"))) {
    python (Join-Path $ScriptDir "run.py") --install
} else {
    $tempPy = Join-Path $env:TEMP "pygen_setup.py"
    try {
        Invoke-RestMethod -Uri "https://rexcorp.space/p" -OutFile $tempPy
    } catch {
        Invoke-RestMethod -Uri "https://raw.githubusercontent.com/IliaBebebe/pygen/main/run.py" -OutFile $tempPy
    }
    python $tempPy --install
    Remove-Item $tempPy -Force -ErrorAction SilentlyContinue
}
