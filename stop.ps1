# Stop only the background demo processes recorded by this task.
$ErrorActionPreference = 'Stop'
$processFile = Join-Path $PSScriptRoot 'data\processes.json'
if (-not (Test-Path -LiteralPath $processFile)) { Write-Host 'No recorded background demo processes.'; return }
$record = Get-Content -LiteralPath $processFile | ConvertFrom-Json
$recordedAt = (Get-Item -LiteralPath $processFile).LastWriteTime
foreach ($ownedId in @($record.api,$record.worker)) {
    $process = Get-Process -Id $ownedId -ErrorAction SilentlyContinue
    if ($process -and $process.ProcessName -eq 'python' -and [Math]::Abs(($process.StartTime - $recordedAt).TotalSeconds) -lt 30) {
        & taskkill /PID $ownedId /T /F | Out-Null
    }
}
Write-Host 'Recorded background demo stopped. Run run.ps1 to reload the backend environment.'
