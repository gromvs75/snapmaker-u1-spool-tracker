$ErrorActionPreference = 'Stop'
if ($env:USERNAME -ne 'WDAGUtilityAccount' -or !(Test-Path 'C:\TestInputs\Offline.wsb')) { throw 'Sandbox guest required.' }
$labRoot = Join-Path $env:USERPROFILE 'Desktop\TrackerLab'
$runtime = Get-Content -Raw "$labRoot\runtime.json" | ConvertFrom-Json
$uri = [Uri]$runtime.url
if ($uri.Scheme -ne 'http' -or $uri.Host -ne '127.0.0.1') { throw 'Only the local test API is allowed.' }
$forecast = Invoke-RestMethod ($runtime.url + '/api/forecast')
$data = Invoke-RestMethod ($runtime.url + '/api/data')
$seed = Get-Content -Raw 'C:\TestInputs\inventory.json' | ConvertFrom-Json
$unchanged = $true
foreach ($id in @('test0','test1','test2','test3')) {
    if ($data.spools.$id.remaining_g -ne $seed.spools.$id.remaining_g) { $unchanged = $false }
}
$report = [ordered]@{
    captured_at = (Get-Date).ToString('o')
    watch_root = $forecast.watch_root
    plates = $forecast.entries.Count
    auto_shows = $forecast.auto_shows
    revision = $forecast.revision
    balances_match_seed = $unchanged
    forecast = $forecast
}
$report | ConvertTo-Json -Depth 30 | Set-Content -Encoding UTF8 "$labRoot\verification.json"
$report | Select-Object captured_at,watch_root,plates,auto_shows,revision,balances_match_seed | Format-List
Write-Host 'Report stays in the guest. Photograph results before closing Sandbox; the host share is read-only.'
