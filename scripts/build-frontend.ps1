# Build frontend for deployment
# Run from project root: .\scripts\build-frontend.ps1
# Requires: Node.js, frontend/.env.local with VITE_* vars

param(
    [string]$FrontendDir = "frontend"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$origDir = Get-Location

try {
    Set-Location (Join-Path $ProjectRoot $FrontendDir)

    if (-not (Test-Path ".env.local")) {
        Write-Error ".env.local not found in $FrontendDir. Create it from .env.example after terraform apply."
        exit 1
    }

    Write-Host "Installing dependencies..."
    npm ci
    if ($LASTEXITCODE -ne 0) { Write-Error "npm ci failed with exit code $LASTEXITCODE"; exit 1 }

    Write-Host "Type checking..."
    npm run typecheck
    if ($LASTEXITCODE -ne 0) { Write-Error "npm run typecheck failed with exit code $LASTEXITCODE"; exit 1 }

    Write-Host "Building..."
    npm run build
    if ($LASTEXITCODE -ne 0) { Write-Error "npm run build failed with exit code $LASTEXITCODE"; exit 1 }

    Write-Host "Build complete: $FrontendDir/dist/"
} finally {
    Set-Location $origDir
}
