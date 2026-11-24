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
foreach ($module in 'msm_drm', 'fst2ca78y_i2c', 'zinitix_ts') {
    if (-not $loaded.ContainsKey($module)) { throw "Driver module $module is not loaded." }
    $seen = [Collections.Generic.HashSet[string]]::new()
    $remaining = [Collections.Generic.Stack[string]]::new()
    $remaining.Push($module)
    while ($remaining.Count) {
        $current = $remaining.Pop()
        foreach ($dependency in $dependencies[$current]) {
            if ($dependency -and $seen.Add($dependency)) { $remaining.Push($dependency) }
        }
    }
    $report[$module] = [ordered]@{
        size_bytes = $loaded[$module]
        direct_module_dependencies = @($dependencies[$module] | Where-Object { $_ } | Sort-Object)
        transitive_module_dependencies = @($seen | Sort-Object)
    }
}
$report | ConvertTo-Json -Depth 4
