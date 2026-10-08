param([string]$Python = "python", [int]$Port = 8080)
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPython)) {
    & $Python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.12+ is required.' }
}
$requirementsHash = (Get-FileHash -LiteralPath 'requirements.txt' -Algorithm SHA256).Hash
$installedHashFile = Join-Path $projectRoot '.venv\requirements.sha256'
$installedHash = if (Test-Path -LiteralPath $installedHashFile) { (Get-Content -LiteralPath $installedHashFile -Raw).Trim() } else { '' }
if ($installedHash -ne $requirementsHash) {
    & $venvPython -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
    Set-Content -LiteralPath $installedHashFile -Value $requirementsHash
}
if (-not (Test-Path -LiteralPath '.env')) { Copy-Item -LiteralPath '.env.example' -Destination '.env' }
New-Item -ItemType Directory -Force -Path data | Out-Null
$workerProcess = Start-Process -FilePath $venvPython -ArgumentList @('-m','studio.worker') -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput 'data\worker.log' -RedirectStandardError 'data\worker.err.log'
Write-Host "Impact Studio: http://127.0.0.1:$Port ; NVIDIA key belongs in .env, never in the browser."
try { & $venvPython -m uvicorn studio.api:app --host 127.0.0.1 --port $Port }
finally { & taskkill /PID $workerProcess.Id /T /F | Out-Null }
