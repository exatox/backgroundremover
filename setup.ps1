# One-time setup for the Background Remover GUI:
#   1. creates the .venv virtual environment
#   2. installs pinned dependencies into it
#   3. draws the icon and builds BackgroundRemover.exe
#
# Run from this folder:  powershell -ExecutionPolicy Bypass -File setup.ps1
# Add -Cpu on a machine without an NVIDIA GPU.
param([switch]$Cpu)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$torchVersion = "2.14.1"
$visionVersion = "0.29.1"
$torchIndex = if ($Cpu) { "https://download.pytorch.org/whl/cpu" } else { "https://download.pytorch.org/whl/cu130" }
$python = ".\.venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    Write-Host "Creating virtual environment (.venv)..."
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "Could not create the virtual environment. Is Python installed?" }
}

Write-Host "Installing PyTorch from $torchIndex ..."
& $python -m pip install --disable-pip-version-check --index-url $torchIndex "torch==$torchVersion" "torchvision==$visionVersion"
if ($LASTEXITCODE -ne 0) { throw "PyTorch installation failed." }

Write-Host "Installing the remaining packages from PyPI..."
& $python -m pip install --disable-pip-version-check --only-binary=:all: -r requirements-gui.txt
if ($LASTEXITCODE -ne 0) { throw "Package installation failed." }

Write-Host "Building BackgroundRemover.exe..."
& $python launcher\make_icon.py
$csc = Join-Path $env:WINDIR "Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if (-not (Test-Path $csc)) { throw "The .NET Framework C# compiler was not found at $csc" }
& $csc /nologo /target:winexe /optimize+ /win32icon:bgremover_gui\web\icon.ico /reference:System.Windows.Forms.dll /out:BackgroundRemover.exe launcher\Launcher.cs
if ($LASTEXITCODE -ne 0) { throw "Launcher build failed." }

Write-Host ""
Write-Host "Done. Double-click BackgroundRemover.exe to start."
