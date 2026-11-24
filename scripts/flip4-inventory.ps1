param([string]$Adb)
$ErrorActionPreference = 'Stop'
if (-not $Adb) {
    $localAdb = Join-Path $PSScriptRoot '../build/sdk/android/platform-tools/adb.exe'
    $Adb = if (Test-Path -LiteralPath $localAdb) { $localAdb } else { 'adb' }
}

function Get-UsbState {
    $ErrorActionPreference = 'Continue'
    $result = & $Adb -d get-state 2>&1
    if ($LASTEXITCODE -ne 0) { throw "ADB USB connection unavailable. $($result -join ' ')" }
    return ($result -join '').Trim()
}

if ((Get-UsbState) -ne 'device') {
    throw 'ADB requires one authorized Android device connected by USB.'
}

function Read-DeviceValue([string[]]$Arguments) {
    $output = & $Adb -d shell @Arguments
    if ($LASTEXITCODE -ne 0) { throw 'Unable to read an Android device property.' }
    return ($output -join "`n").Trim()
}

$properties = [ordered]@{}
foreach ($key in @('ro.product.model', 'ro.product.device', 'ro.build.display.id',
                   'ro.build.version.release', 'ro.build.version.security_patch',
                   'ro.bootloader', 'ro.product.cpu.abilist', 'ro.boot.flash.locked',
                   'ro.boot.verifiedbootstate', 'ro.boot.vbmeta.device_state')) {
    $properties[$key] = Read-DeviceValue @('getprop', $key)
}
$properties['kernel_release'] = Read-DeviceValue @('uname', '-r')
$board = [ordered]@{}
foreach ($key in @('qcom,board-id', 'qcom,msm-id', 'dtbo-hw_rev', 'dtbo-hw_rev_end')) {
    # Device-tree cells are big-endian. Keep the original byte order for
    # comparison with the overlay, even when the host is little-endian.
    $bytes = & {
        $ErrorActionPreference = 'Continue'
        & $Adb -d shell od -A n -t x1 "/proc/device-tree/$key" 2>$null
    }
    $hex = ($bytes -join '') -replace '\s', ''
    $board[$key] = if ($LASTEXITCODE -eq 0 -and $hex -match '^(?:[a-fA-F0-9]{8})+$') {
        $hex.ToLowerInvariant()
    } else { $null }
}
$properties['device_tree_hex'] = $board
$properties | ConvertTo-Json
