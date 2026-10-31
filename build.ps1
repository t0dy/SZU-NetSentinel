param(
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"
$projectDirectory = $PSScriptRoot

# 优先使用已安装完整依赖的当前 Python 环境；若缺失则降级使用 .venv-build
$systemPythonOk = $false
try {
    & python -c "import requests, PIL, cryptography, PyInstaller" 2>$null
    if ($LASTEXITCODE -eq 0) {
        $systemPythonOk = $true
    }
} catch {
    $systemPythonOk = $false
}

if ($systemPythonOk) {
    $buildPython = "python"
} else {
    $buildPython = Join-Path $projectDirectory ".venv-build\Scripts\python.exe"
}

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

$appVersion = (& $buildPython -c "import szu_sentinel; print(szu_sentinel.__version__)").Trim()
if (-not $appVersion) { $appVersion = "2.6.0" }
$targetName = "SZU-NetSentinel-v$appVersion"

Invoke-Checked {
    & $buildPython -m PyInstaller `
        --noconfirm `
        --clean `
        --onefile `
        --windowed `
        --icon (Join-Path $projectDirectory "assets\app.ico") `
        --add-data "$projectDirectory\assets;assets" `
        --name $targetName `
        (Join-Path $projectDirectory "main.py")
} "PyInstaller build"

Write-Host ""
Copy-Item -LiteralPath "$projectDirectory\dist\$targetName.exe" -Destination "$projectDirectory\$targetName.exe" -Force
Copy-Item -LiteralPath "$projectDirectory\dist\$targetName.exe" -Destination "$projectDirectory\SZU-NetSentinel.exe" -Force
Write-Host "Build complete: $projectDirectory\$targetName.exe"
