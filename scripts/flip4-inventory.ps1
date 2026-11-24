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
$properties | ConvertTo-Json
