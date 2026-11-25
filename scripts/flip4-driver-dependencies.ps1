param([string]$Adb)
$ErrorActionPreference = 'Stop'
if (-not $Adb) {
    $localAdb = Join-Path $PSScriptRoot '../build/sdk/android/platform-tools/adb.exe'
    $Adb = if (Test-Path -LiteralPath $localAdb) { $localAdb } else { 'adb' }
}

$lines = & $Adb -d shell cat /proc/modules
if ($LASTEXITCODE -ne 0) { throw 'Unable to read loaded modules from the USB device.' }

# /proc/modules lists reverse dependencies in column four.
$loaded = @{}
$dependencies = @{}
foreach ($line in $lines) {
    $fields = $line -split '\s+'
    if ($fields.Count -lt 6 -or $fields[0] -notmatch '^\w+$') {
        throw 'Unexpected format in /proc/modules.'
    }
    $name = $fields[0]
    $loaded[$name] = [int64]$fields[1]
    foreach ($consumer in ($fields[3] -split ',' | Where-Object { $_ -match '^\w+$' })) {
        if (-not $dependencies.ContainsKey($consumer)) {
            $dependencies[$consumer] = [Collections.Generic.List[string]]::new()
        }
        $dependencies[$consumer].Add($name)
    }
}

$report = [ordered]@{}
$displayDrivers = @('msm_drm', 'fst2ca78y_i2c', 'zinitix_ts')
foreach ($module in $displayDrivers) {
    if (-not $loaded.ContainsKey($module)) { throw "Driver module $module is not loaded." }
}
$driverFiles = [ordered]@{
    msm_drm = 'msm_drm.ko'
    fst2ca78y_i2c = 'fst2ca78y_i2c.ko'
    zinitix_ts = 'zinitix_ts.ko'
    i2c_msm_geni = 'i2c-msm-geni.ko'
    ufs_qcom = 'ufs_qcom.ko'
    phy_qcom_ufs_qmp_v4_cape = 'phy-qcom-ufs-qmp-v4-cape.ko'
}
foreach ($module in $driverFiles.Keys) {
    if (-not $loaded.ContainsKey($module)) { continue }
    $seen = [Collections.Generic.HashSet[string]]::new()
    $remaining = [Collections.Generic.Stack[string]]::new()
    $remaining.Push($module)
    while ($remaining.Count) {
        $current = $remaining.Pop()
        foreach ($dependency in $dependencies[$current]) {
            if ($dependency -and $seen.Add($dependency)) { $remaining.Push($dependency) }
        }
    }
    $path = '/vendor_dlkm/lib/modules/' + $driverFiles[$module]
    $fileSize = & $Adb -d shell "if [ -f '$path' ]; then stat -c %s '$path'; fi"
    if ($LASTEXITCODE -ne 0) { throw "Unable to inspect module metadata for $module." }
    $length = ($fileSize -join '').Trim()
    $report[$module] = [ordered]@{
        size_bytes = $loaded[$module]
        direct_module_dependencies = @($dependencies[$module] | Where-Object { $_ } | Sort-Object)
        transitive_module_dependencies = @($seen | Sort-Object)
        vendor_dlkm_file_size_bytes = if ($length -match '^\d+$') { [int64]$length } else { $null }
    }
}
$report | ConvertTo-Json -Depth 4
