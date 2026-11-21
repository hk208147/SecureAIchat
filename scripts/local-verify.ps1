# Local verification script (no AWS operations)
# Run from project root: .\scripts\local-verify.ps1

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Errors = @()
$Warnings = @()
$anyFail = $false

function Pass($msg) { Write-Host "  [PASS] $msg" -ForegroundColor Green }
function Fail($msg) {
    Write-Host "  [FAIL] $msg" -ForegroundColor Red
    $script:Errors += $msg
    $script:anyFail = $true
}
function Warn($msg) { Write-Host "  [WARN] $msg" -ForegroundColor Yellow; $script:Warnings += $msg }
function Skip($msg) { Write-Host "  [SKIP] $msg" -ForegroundColor DarkGray }

Write-Host "`n=== Python syntax check ===" -ForegroundColor Cyan
$PythonExe = (Get-Command python3 -ErrorAction SilentlyContinue).Source
if (-not $PythonExe) { $PythonExe = (Get-Command python -ErrorAction SilentlyContinue).Source }

$PythonIsReal = $false
if ($PythonExe -and $PythonExe -notlike "*WindowsApps*") {
    $ver = & $PythonExe --version 2>&1
    if ($ver -match "Python 3") { $PythonIsReal = $true }
}

if ($PythonIsReal) {
    $LambdaFiles = Get-ChildItem "$ProjectRoot\lambda" -Filter "*.py" | Where-Object { $_.DirectoryName -notlike "*tests*" }
    foreach ($f in $LambdaFiles) {
        $result = & $PythonExe -c "import ast; ast.parse(open(r'$($f.FullName)').read())" 2>&1
        if ($LASTEXITCODE -eq 0) { Pass $f.Name } else { Fail "$($f.Name): $result" }
    }
} else {
    Warn "Python 3 not found (Store stub skipped). Install Python 3.12 to run syntax checks and pytest."
}

Write-Host "`n=== Python tests (pytest) ===" -ForegroundColor Cyan
if ($PythonIsReal) {
    $origDir = Get-Location
    try {
        Set-Location "$ProjectRoot\lambda"
        $pytestOut = & $PythonExe -m pytest tests/ -q --tb=short 2>&1
        $pytestExit = $LASTEXITCODE
        $pytestOut | ForEach-Object { Write-Host "    $_" }
        if ($pytestExit -eq 0) { Pass "pytest" } else { Fail "pytest returned exit $pytestExit" }
    } finally {
        Set-Location $origDir
    }
} else {
    Skip "Python 3 not installed — run pytest manually after install"
}

Write-Host "`n=== Frontend type check + build ===" -ForegroundColor Cyan
$FrontendDir = Join-Path $ProjectRoot "frontend"
if (Test-Path (Join-Path $FrontendDir "package.json")) {
    $origDir = Get-Location
    try {
        Set-Location $FrontendDir
        if (-not (Test-Path "node_modules")) {
            Write-Host "  Installing npm dependencies..."
            npm install --silent
        }
        Write-Host "  Running tsc --noEmit..."
        npm run typecheck 2>&1 | ForEach-Object { Write-Host "    $_" }
        if ($LASTEXITCODE -eq 0) { Pass "TypeScript type check" } else { Fail "TypeScript errors found" }

        Write-Host "  Building..."
        npm run build 2>&1 | Select-Object -Last 5 | ForEach-Object { Write-Host "    $_" }
        if ($LASTEXITCODE -eq 0) { Pass "Vite build" } else { Fail "Build failed" }
    } finally {
        Set-Location $origDir
    }
} else {
    Warn "frontend/package.json not found"
}

Write-Host "`n=== Terraform validation ===" -ForegroundColor Cyan
$TfExe = (Get-Command terraform -ErrorAction SilentlyContinue).Source
if ($TfExe) {
    $origDir = Get-Location
    try {
        Set-Location "$ProjectRoot\terraform"
        Write-Host "  Running terraform fmt -check..."
        terraform fmt -check 2>&1 | ForEach-Object { Write-Host "    $_" }
        $fmtExit = $LASTEXITCODE
        Write-Host "  Running terraform validate..."
        terraform validate 2>&1 | ForEach-Object { Write-Host "    $_" }
        $validateExit = $LASTEXITCODE
        if ($fmtExit -eq 0 -and $validateExit -eq 0) {
            Pass "terraform fmt -check + validate"
        } else {
            Fail "terraform checks failed (fmt=$fmtExit validate=$validateExit)"
        }
    } finally {
        Set-Location $origDir
    }
} else {
    Skip "Terraform CLI not installed — run terraform validate manually after install"
}

Write-Host "`n=== Terraform file presence check ===" -ForegroundColor Cyan
$TfFiles = @("versions.tf","providers.tf","variables.tf","locals.tf","cognito.tf",
             "s3_cloudfront.tf","dynamodb.tf","lambda.tf","apigateway.tf",
             "monitoring.tf","budgets.tf","outputs.tf")
foreach ($f in $TfFiles) {
    if (Test-Path "$ProjectRoot\terraform\$f") { Pass $f } else { Fail "Missing terraform/$f" }
}

Write-Host "`n=== Lambda file presence check ===" -ForegroundColor Cyan
$LFiles = @("config.py","logger.py","metrics.py","conversation.py","bedrock_client.py","chat_handler.py","requirements.txt")
foreach ($f in $LFiles) {
    if (Test-Path "$ProjectRoot\lambda\$f") { Pass $f } else { Fail "Missing lambda/$f" }
}

Write-Host "`n=== dist directory ===" -ForegroundColor Cyan
$DistDir = "$ProjectRoot\dist"
if (-not (Test-Path $DistDir)) {
    New-Item -ItemType Directory -Path $DistDir | Out-Null
    Pass "Created dist/ (required by terraform archive_file data source)"
} else {
    Pass "dist/ exists"
}

Write-Host "`n=== Summary ===" -ForegroundColor Cyan
if ($Errors.Count -eq 0) {
    Write-Host "All checks passed ($($Warnings.Count) warning(s))" -ForegroundColor Green
} else {
    Write-Host "$($Errors.Count) error(s), $($Warnings.Count) warning(s)" -ForegroundColor Red
    $Errors | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }
}
if ($Warnings.Count -gt 0) {
    $Warnings | ForEach-Object { Write-Host "  - $_" -ForegroundColor Yellow }
}

if ($anyFail) { exit 1 } else { exit 0 }
