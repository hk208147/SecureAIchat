# Build Lambda deployment package
# Creates dist/lambda.zip from lambda/ directory
# Run from project root: .\scripts\build-lambda.ps1

param(
    [string]$OutputDir = "dist",
    [string]$LambdaDir = "lambda"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot

Set-Location $ProjectRoot

if (-not (Test-Path $OutputDir)) {
    New-Item -ItemType Directory -Path $OutputDir | Out-Null
}

$ZipPath = Join-Path $ProjectRoot "$OutputDir\lambda.zip"

if (Test-Path $ZipPath) {
    Remove-Item $ZipPath -Force
}

# Collect files to include (exclude tests, __pycache__, .pyc, requirements*.txt)
$SourceFiles = Get-ChildItem -Path $LambdaDir -File |
    Where-Object {
        $_.Extension -ne ".pyc" -and
        $_.Name -notlike "requirements*.txt" -and
        $_.DirectoryName -notlike "*tests*" -and
        $_.DirectoryName -notlike "*__pycache__*"
    }

Write-Host "Packaging Lambda files:"
$SourceFiles | ForEach-Object { Write-Host "  $($_.Name)" }

Compress-Archive -Path ($SourceFiles | Select-Object -ExpandProperty FullName) -DestinationPath $ZipPath

$Size = (Get-Item $ZipPath).Length / 1KB
Write-Host "Created: $ZipPath ($([math]::Round($Size, 1)) KB)"
