function Open-Flip4Serial([string]$Port, [TimeSpan]$Timeout) {
    $clock = [Diagnostics.Stopwatch]::StartNew()
    while (-not $Port -and $clock.Elapsed -lt $Timeout) {
        $ports = @(Get-PnpDevice -PresentOnly -Class Ports -ErrorAction SilentlyContinue |
            Where-Object InstanceId -Match '^USB\\VID_0525&PID_A4A7(?:\\|&)' |
            ForEach-Object {
                if ($_.FriendlyName -match '\((COM[1-9][0-9]*)\)$') { $Matches[1] }
            } | Sort-Object -Unique)
        if ($ports.Count -gt 1) { throw 'Multiple AIOS USB serial ports are present. Select one with -Port.' }
        if ($ports.Count -eq 1) { $Port = $ports[0]; break }
        Start-Sleep -Milliseconds 250
    }
    if (-not $Port) { throw 'No AIOS USB serial port appeared.' }

    $serial = [System.IO.Ports.SerialPort]::new($Port, 115200)
    try {
        $serial.Encoding = [Text.Encoding]::UTF8
        $serial.DtrEnable = $true
        $serial.ReadTimeout = 250
        $serial.WriteTimeout = 1000
        $serial.Open()
        return $serial
    } catch {
        $serial.Dispose()
        throw
    }
}
