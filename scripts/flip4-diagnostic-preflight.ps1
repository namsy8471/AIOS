param(
    [Parameter(Mandatory)][string]$Bundle,
    [string]$Adb
)
$ErrorActionPreference = 'Stop'
if (-not $Adb) {
    $localAdb = Join-Path $PSScriptRoot '../build/sdk/android/platform-tools/adb.exe'
    $Adb = if (Test-Path -LiteralPath $localAdb) { $localAdb } else { 'adb' }
}

$declared = Get-Content -Raw -LiteralPath (Join-Path $Bundle 'layout.json') | ConvertFrom-Json
$proof = Get-Content -Raw -LiteralPath (Join-Path $Bundle 'qemu-proof.json') | ConvertFrom-Json
$image = Join-Path $Bundle 'aios-flip4-board-probe-unsigned.img'
$result = & python (Join-Path $PSScriptRoot 'inspect-flip4-boot-image.py') $image
if ($LASTEXITCODE -ne 0) { throw 'Unable to inspect the diagnostic boot image.' }
$actual = $result | ConvertFrom-Json

if ($actual.sha256 -cne $declared.sha256 -or $actual.header_version -ne 2 -or $null -ne $actual.avb_footer) {
    throw 'Expected the unchanged, unsigned Android v2 diagnostic image.'
}
if ($proof.scope -cne 'qemu_virt' -or
    $actual.sections.kernel.sha256 -cne $proof.payload.kernel -or
    $actual.sections.ramdisk.sha256 -cne $proof.payload.ramdisk -or
    $proof.driver_without_touch.driver_count -le 0 -or
    $proof.driver_without_touch.records.MODULES.attempted -ne $true -or
    $proof.driver_without_touch.records.MODULES.touch_modules_enabled -ne $false -or
    $proof.driver_without_touch.records.MODULES.exit_code -ne 0) {
    throw 'The diagnostic payload does not match a successful QEMU boot with touchscreen modules disabled.'
}

$device = & (Join-Path $PSScriptRoot 'flip4-inventory.ps1') -Adb $Adb | ConvertFrom-Json
$recoveryLink = $device.android_partition_links.recovery
if ($recoveryLink -cmatch '^/dev/block/([a-z]+[0-9]+)$') {
    $recoveryName = $Matches[1]
} else {
    throw 'The connected device did not report a recovery partition alias.'
}
$partitions = & $Adb -d shell cat /proc/partitions
if ($LASTEXITCODE -ne 0) { throw 'Unable to read partition capacities from the device.' }
$capacity = $null
foreach ($line in $partitions) {
    if ($line -cmatch '^\s*\d+\s+\d+\s+(\d+)\s+([a-z]+[0-9]+)\s*$' -and $Matches[2] -ceq $recoveryName) {
        $capacity = [uint64]$Matches[1] * 1KB
        break
    }
}
if ($null -eq $capacity) { throw 'No capacity was reported for the recovery partition.' }

$boardMatches = $device.'ro.product.model' -ceq 'SM-F721N' -and
    $device.soc.machine -ceq 'CAPE' -and $device.soc.soc_id -ceq '530' -and
    $device.'ro.boot.revision' -ceq '13' -and $device.'ro.boot.dtb_idx' -ceq '0' -and
    $device.'ro.boot.dtbo_idx' -ceq '9'
$lockState = $device.'ro.boot.vbmeta.device_state'
$flashLocked = $device.'ro.boot.flash.locked'
$bootloaderStatus = if ($lockState -ceq 'locked' -and $flashLocked -ceq '1') {
    'locked'
} elseif ($lockState -ceq 'unlocked' -and $flashLocked -ceq '0') {
    'unlocked'
} else {
    'unknown'
}

[ordered]@{
    model = $device.'ro.product.model'
    firmware = $device.'ro.bootloader'
    stock_kernel = $device.kernel_release
    bootloader_status = $bootloaderStatus
    verified_boot = $device.'ro.boot.verifiedbootstate'
    reference_board_identifiers_match = $boardMatches
    recovery_partition = $recoveryLink
    recovery_capacity_bytes = $capacity
    diagnostic_image_bytes = $actual.image_size
    diagnostic_image_sha256 = $actual.sha256
    diagnostic_image_fits = $actual.image_size -le $capacity
    qemu_drivers_loaded_without_touch = $proof.driver_without_touch.driver_count
    physical_boot = 'unverified'
} | ConvertTo-Json
