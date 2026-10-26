param(
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"
$projectDirectory = $PSScriptRoot
$buildPython = Join-Path $projectDirectory ".venv-build\Scripts\python.exe"

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [scriptblock]$Command,
        [Parameter(Mandatory = $true)]
        [string]$Description
    )
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed with exit code $LASTEXITCODE"
    }
}

Set-Location -LiteralPath $projectDirectory

if (-not (Test-Path -LiteralPath $buildPython)) {
    Invoke-Checked {
        python -m venv (Join-Path $projectDirectory ".venv-build")
    } "Creating build environment"
}

if (-not $SkipInstall) {
    Invoke-Checked {
        & $buildPython -m pip install --upgrade pip
    } "Upgrading pip"
    Invoke-Checked {
        & $buildPython -m pip install -r (Join-Path $projectDirectory "requirements-build.txt")
    } "Installing build dependencies"
}

Invoke-Checked {
    & $buildPython -m unittest discover -s tests -v
} "Tests"
Invoke-Checked {
    & $buildPython -m PyInstaller `
        --noconfirm `
        --clean `
        --onefile `
        --windowed `
        --icon (Join-Path $projectDirectory "assets\app.ico") `
        --add-data "$projectDirectory\assets;assets" `
        --name "SZU-NetSentinel-v2.5.0" `
        (Join-Path $projectDirectory "main.py")
} "PyInstaller build"

Write-Host ""
Copy-Item -LiteralPath "$projectDirectory\dist\SZU-NetSentinel-v2.5.0.exe" -Destination "$projectDirectory\SZU-NetSentinel-v2.5.0.exe" -Force
Copy-Item -LiteralPath "$projectDirectory\dist\SZU-NetSentinel-v2.5.0.exe" -Destination "$projectDirectory\SZU-NetSentinel.exe" -Force
Write-Host "Build complete: $projectDirectory\SZU-NetSentinel-v2.5.0.exe"
