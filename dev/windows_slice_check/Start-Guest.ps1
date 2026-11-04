param([Parameter(Mandatory=$true)][string]$SnorcaExe)
$ErrorActionPreference = 'Stop'
# This launcher is for the offline Sandbox guest, not for a working Windows PC.
if ($env:USERNAME -ne 'WDAGUtilityAccount' -or !(Test-Path 'C:\TestInputs\Offline.wsb')) {
    throw 'Run only inside the supplied offline Windows Sandbox.'
}
if (!(Test-Path -LiteralPath $SnorcaExe -PathType Leaf)) { throw 'Snorca executable not found in guest.' }
$labRoot = Join-Path $env:USERPROFILE 'Desktop\TrackerLab'
New-Item -ItemType Directory -Force "$labRoot\temp", "$labRoot\inventory", "$labRoot\snorca-data", "$labRoot\apps" | Out-Null
$utf8 = New-Object System.Text.UTF8Encoding($false)
[IO.File]::WriteAllText("$labRoot\ISOLATED_TRACKER_TEST", "offline-only`n", $utf8)
if (!(Test-Path "$labRoot\inventory\spools_u1.json")) {
    Copy-Item 'C:\TestInputs\inventory.json' "$labRoot\inventory\spools_u1.json"
}
Copy-Item 'C:\TestInputs\cube20.stl' "$labRoot\cube20.stl" -Force
Copy-Item 'C:\TestInputs\SnapmakerSpoolTracker-1.2-beta-Windows.exe' "$labRoot\apps\Tracker.exe" -Force
# Changes apply only to this process and its children in the disposable guest.
$env:TEMP = "$labRoot\temp"
$env:TMP = "$labRoot\temp"
$watchRoot = "$labRoot\temp\snapmaker_orca_model"
Start-Process -FilePath "$labRoot\apps\Tracker.exe" -ArgumentList @('--isolated-root', ('"' + $labRoot + '"'), '--slice-root', ('"' + $watchRoot + '"'))
Start-Process -FilePath $SnorcaExe -ArgumentList @('--datadir', ('"' + "$labRoot\snorca-data" + '"'), ('"' + "$labRoot\cube20.stl" + '"'))
Write-Host 'Select the U1 preset offline, hide Tracker to tray, then press Slice plate. Do not export G-code.'
Write-Host 'Do not run this launcher twice in the same guest; close both test applications first.'
