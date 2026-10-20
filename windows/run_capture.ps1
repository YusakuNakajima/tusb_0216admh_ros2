# Record one capture_session.py run with USBPcapCMD.
#   powershell -ExecutionPolicy Bypass -File run_capture.ps1 -Id 0 -Scenario basic
# Writes tusb_<Scenario>_id<Id>.pcap, calls_<Scenario>_id<Id>.jsonl and run_<Scenario>_id<Id>.log
# next to this script. Needs USBPcap (reboot once after installing it), the
# vendor TUSBADMH.py and capture_session.py in the same folder.
param([int]$Id = 0, [string]$Scenario = 'basic')
$ErrorActionPreference = 'Stop'

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
           ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Start-Process powershell -Verb RunAs -Wait -ArgumentList `
        "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Id $Id -Scenario $Scenario"
    Get-Content (Join-Path $PSScriptRoot "run_${Scenario}_id$Id.log")
    exit
}

Set-Location $PSScriptRoot
Start-Transcript -Path (Join-Path $PSScriptRoot "run_${Scenario}_id$Id.log") -Force | Out-Null
$cmd = 'C:\Program Files\USBPcap\USBPcapCMD.exe'

# Root hub the TUSB device hangs off (device list shows the driver's name).
$iface = $null
foreach ($n in 1..16) {
    $dev = "\\.\USBPcap$n"
    $cfg = & $cmd --extcap-interface $dev --extcap-config 2>$null | Out-String
    if ($cfg -match '\{value=(\d+)\}\{display=\[\d+\] TUSB') { $iface = $dev; $addr = $Matches[1]; break }
}
if (-not $iface) { throw 'TUSB-0216ADMH not found on any USBPcap root hub (reboot after installing USBPcap?)' }
Write-Host "capturing on $iface, device $addr"

$pcap = Join-Path $PSScriptRoot "tusb_${Scenario}_id$Id.pcap"
$log = Join-Path $PSScriptRoot "calls_${Scenario}_id$Id.jsonl"
$cap = Start-Process $cmd -PassThru -WindowStyle Hidden `
    -ArgumentList "-d $iface -o `"$pcap`" --devices $addr --inject-descriptors"
Start-Sleep -Seconds 3
try {
    py -3 capture_session.py --id $Id --log $log --scenario $Scenario
} finally {
    Start-Sleep -Seconds 2
    Stop-Process -Id $cap.Id
}
Write-Host "done: $pcap ($((Get-Item $pcap).Length) bytes), $log"
