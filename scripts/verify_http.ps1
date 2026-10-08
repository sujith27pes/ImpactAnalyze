param([string]$Java = 'java')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$fixtureRoot = Join-Path $projectRoot 'examples\banking-platform'
$logRoot = Join-Path $projectRoot 'data\http-verification'
New-Item -ItemType Directory -Force -Path $logRoot | Out-Null
$ownedProcesses = @()
$modules = @('reporting-service','reconciliation-service','ledger-service','payments-service')
function Port-Ready([int]$port) {
    $socket = [System.Net.Sockets.TcpClient]::new()
    try { return $socket.ConnectAsync('127.0.0.1',$port).Wait(150) -and $socket.Connected }
    catch { return $false }
    finally { $socket.Dispose() }
}
try {
    foreach ($port in 9101..9104) { if (Port-Ready $port) { throw "Port $port is already occupied; no existing server will be stopped." } }
    foreach ($module in $modules) {
        $jarPath = Join-Path $fixtureRoot "$module\target\$module-1.0.0-exec.jar"
        if (-not (Test-Path -LiteralPath $jarPath)) { throw "Build the fixture with mvn package first: missing $module jar." }
        $ownedProcesses += Start-Process -FilePath $Java -ArgumentList @('-Xmx128m','-jar',$jarPath,'--server.address=127.0.0.1') -WindowStyle Hidden -PassThru -RedirectStandardOutput "$logRoot\$module.log" -RedirectStandardError "$logRoot\$module.err.log"
    }
    $ready = $false
    foreach ($attempt in 1..45) {
        $ready = (9101..9104 | ForEach-Object { Port-Ready $_ }) -notcontains $false
        if ($ready) { break }
        Start-Sleep -Seconds 1
    }
    if (-not $ready) { throw 'Fixture HTTP services did not become ready; inspect data/http-verification logs.' }
    $paymentId = 'http-smoke-' + [guid]::NewGuid().ToString()
    $body = @{paymentId=$paymentId; amount=125.50; currency='USD'} | ConvertTo-Json
    $first = Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:9101/payments' -ContentType 'application/json' -Body $body
    $second = Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:9101/payments' -ContentType 'application/json' -Body $body
    $reportTotal = Invoke-RestMethod -Uri 'http://127.0.0.1:9104/reporting/total'
    $reconciliationTotal = Invoke-RestMethod -Uri 'http://127.0.0.1:9103/reconciliation/total'
    if ([decimal]$first.amountMajor -ne [decimal]'125.50' -or [decimal]$second.amountMajor -ne [decimal]'125.50' -or [decimal]$reportTotal -ne [decimal]'125.50' -or [decimal]$reconciliationTotal -ne [decimal]'125.50') { throw 'Actual HTTP downstream value / replay assertion failed.' }
    $result = @{status='VERIFIED'; transport='4 independent Spring Boot HTTP services'; paymentId=$paymentId; expected='125.50 USD'; reportingTotal=[string]$reportTotal; reconciliationTotal=[string]$reconciliationTotal; duplicateCountedOnce=$true; created=[DateTimeOffset]::UtcNow.ToUnixTimeSeconds()}
    $result | ConvertTo-Json | Set-Content -LiteralPath "$logRoot\results.json" -Encoding utf8
    $result | ConvertTo-Json
}
finally { foreach ($process in $ownedProcesses) { Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue } }
