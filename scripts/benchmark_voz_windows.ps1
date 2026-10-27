# Windows helper for the Voz execution-provider benchmark.
# Installs the locked dependencies, reports the GPU, and compares CPU against
# WebGPU (and optionally DirectML or OpenVINO) on the same audio file.
#
#   powershell -ExecutionPolicy Bypass -File scripts\benchmark_voz_windows.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\benchmark_voz_windows.ps1 -Variants cpu,webgpu,directml
[CmdletBinding()]
param(
    [string]$Variants = "cpu,webgpu",
    [int]$Runs = 3,
    [string]$Audio,
    [string]$ModelDir,
    [switch]$Keep
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Push-Location $Root
try {
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        throw "uv is required: install it from https://docs.astral.sh/uv/getting-started/installation/"
    }

    Write-Host "== Display adapters ==" -ForegroundColor Cyan
    Get-CimInstance Win32_VideoController | Select-Object Name, DriverVersion | Format-Table -AutoSize

    Write-Host "== Installing locked dependencies ==" -ForegroundColor Cyan
    uv sync --locked
    if ($LASTEXITCODE -ne 0) { throw "uv sync failed" }

    Write-Host "== ONNX Runtime execution providers ==" -ForegroundColor Cyan
    uv run --locked python scripts/check_voz.py
    if ($LASTEXITCODE -ne 0) { throw "check_voz.py failed" }

    if (-not $Audio) {
        $Audio = Join-Path $env:TEMP "neyra-voz-sample.wav"
        Write-Host "== Creating sample audio ==" -ForegroundColor Cyan
        uv run --locked python scripts/make_sample_audio.py --output $Audio
        if ($LASTEXITCODE -ne 0) { throw "sample audio creation failed" }
    }

    $arguments = @("run", "--locked", "python", "scripts/benchmark_voz.py",
                   "--variants", $Variants, "--audio", $Audio, "--runs", $Runs)
    if ($ModelDir) { $arguments += @("--model-dir", $ModelDir) }
    if ($Keep) { $arguments += "--keep" }

    Write-Host "== Benchmark ==" -ForegroundColor Cyan
    uv @arguments
    if ($LASTEXITCODE -ne 0) { throw "benchmark failed" }
}
finally {
    Pop-Location
}
