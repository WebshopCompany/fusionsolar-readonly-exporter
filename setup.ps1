$ErrorActionPreference = 'Stop'
$UvMinimum = [version]'0.12.18'
$UvMaximum = [version]'0.13'

if ($env:OS -ne 'Windows_NT') {
    throw 'This setup script supports Windows. On macOS/Linux use setup.sh.'
}
Write-Host 'Platform: Windows'

$PythonExe = $null
foreach ($Candidate in @('python', 'python3')) {
    if (Get-Command $Candidate -ErrorAction SilentlyContinue) {
        try {
            $CandidateExe = (& $Candidate -c "import sys; print(sys.executable); raise SystemExit(0 if (3,11) <= sys.version_info[:2] < (3,14) else 1)") | Select-Object -First 1
            if ($LASTEXITCODE -eq 0 -and $CandidateExe) { $PythonExe = $CandidateExe; break }
        } catch {}
    }
}
if (-not $PythonExe -and (Get-Command py -ErrorAction SilentlyContinue)) {
    $CandidateExe = (& py -3 -c "import sys; print(sys.executable); raise SystemExit(0 if (3,11) <= sys.version_info[:2] < (3,14) else 1)") | Select-Object -First 1
    if ($LASTEXITCODE -eq 0 -and $CandidateExe) { $PythonExe = $CandidateExe }
}
if (-not $PythonExe) {
    throw 'Python 3.11, 3.12 or 3.13 is required. Install a supported Python and rerun setup.'
}
$PythonVersion = & $PythonExe -c "import sys; print('.'.join(map(str, sys.version_info[:3])))"
Write-Host "Python: $PythonVersion"

if (Get-Command git -ErrorAction SilentlyContinue) {
    Write-Host 'Git: available'
} else {
    Write-Host 'Git: not found (not required once the source folder has been obtained).'
}

function Show-UvInstructions {
    Write-Host 'Install/upgrade uv explicitly with: winget install --id astral-sh.uv -e  (or: winget upgrade --id astral-sh.uv -e)'
    Write-Host 'Official installation guidance: https://docs.astral.sh/uv/getting-started/installation/'
    Write-Host 'This script does not execute remote installer text automatically.'
}

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Show-UvInstructions
    throw 'uv is required; install it explicitly, then rerun setup.'
}
$UvText = (& uv --version)
$UvToken = ($UvText -split '\s+')[1]
try { $UvVersion = [version]$UvToken } catch { throw "Could not parse uv version: $UvText" }
if ($UvVersion -lt $UvMinimum -or $UvVersion -ge $UvMaximum) {
    Write-Host "Installed uv $UvVersion is outside required range >=0.12.18,<0.13."
    Show-UvInstructions
    throw 'Upgrade/downgrade uv into the declared repository range, then rerun setup.'
}
Write-Host "uv: $UvVersion (supported)"

& uv sync --frozen --python $PythonExe
if ($LASTEXITCODE -ne 0) { throw 'uv sync --frozen failed.' }
& uv run --frozen fusionsolar-stage1 --help | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Stage-1 command smoke test failed.' }

Write-Host 'Setup complete.'
Write-Host 'Next command: .\run.ps1'
