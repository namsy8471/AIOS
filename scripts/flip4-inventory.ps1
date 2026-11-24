param([string]$Adb = 'adb')
$ErrorActionPreference = 'Stop'
# ADB selects its single connected device and reports an error for ambiguity.
function Read-DeviceValue([string[]]$Arguments) {
    $output = & $Adb shell @Arguments
    if ($LASTEXITCODE -ne 0) { throw 'Unable to read an Android device property.' }
    return ($output -join "`n").Trim()
}

$properties = [ordered]@{}
foreach ($key in @('ro.product.model', 'ro.product.device', 'ro.build.display.id',
                   'ro.build.version.release', 'ro.bootloader', 'ro.product.cpu.abilist')) {
    $properties[$key] = Read-DeviceValue @('getprop', $key)
}
$properties['kernel_release'] = Read-DeviceValue @('uname', '-r')
$board = [ordered]@{}
foreach ($key in @('qcom,board-id', 'qcom,msm-id', 'dtbo-hw_rev', 'dtbo-hw_rev_end')) {
    # Device-tree cells are big-endian. Keep the original byte order for
    # comparison with the overlay, even when the host is little-endian.
    $bytes = & $Adb shell od -A n -t x1 "/proc/device-tree/$key" 2>$null
    $hex = ($bytes -join '') -replace '\s', ''
    $board[$key] = if ($LASTEXITCODE -eq 0 -and $hex -match '^(?:[a-fA-F0-9]{8})+$') {
        $hex.ToLowerInvariant()
    } else { $null }
}
$properties['device_tree_hex'] = $board
$properties | ConvertTo-Json
