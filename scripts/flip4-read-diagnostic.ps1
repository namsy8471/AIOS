param(
    [ValidatePattern('^COM[1-9][0-9]*$')][string]$Port,
    [ValidateRange(1, 600)][int]$TimeoutSeconds = 60
)
$ErrorActionPreference = 'Stop'

function ConvertFrom-DiagnosticLine([string]$Line) {
    $prefix = 'AIOS_FLIP4_SNAPSHOT '
    if (-not $Line.StartsWith($prefix, [StringComparison]::Ordinal)) { return }
    try {
        $report = $Line.Substring($prefix.Length) | ConvertFrom-Json -ErrorAction Stop
    } catch {
        # The port may have been opened in the middle of a report.
        return
    }
    if ($report.board.scope -ceq 'cape_flip4_candidate' -and
        $report.modules -is [pscustomobject] -and $report.display -is [pscustomobject] -and
        $report.devices -is [pscustomobject]) {
        return $report
    }
}

$clock = [Diagnostics.Stopwatch]::StartNew()
$deadline = [TimeSpan]::FromSeconds($TimeoutSeconds)
while (-not $Port -and $clock.Elapsed -lt $deadline) {
    $ports = @(Get-PnpDevice -PresentOnly -Class Ports -ErrorAction SilentlyContinue |
        Where-Object InstanceId -Match '^USB\\VID_0525&PID_A4A7(?:\\|&)' |
        ForEach-Object {
            if ($_.FriendlyName -match '\((COM[1-9][0-9]*)\)$') { $Matches[1] }
        } | Sort-Object -Unique)
    if ($ports.Count -gt 1) { throw 'Multiple USB CDC diagnostic ports are present. Select one with -Port.' }
    if ($ports.Count -eq 1) { $Port = $ports[0]; break }
    Start-Sleep -Milliseconds 250
}
if (-not $Port) { throw 'No AIOS USB CDC diagnostic port appeared.' }

$serial = [System.IO.Ports.SerialPort]::new($Port, 115200)
try {
    $serial.Encoding = [Text.Encoding]::UTF8
    $serial.DtrEnable = $true
    $serial.ReadTimeout = 250
    $serial.Open()
    while ($clock.Elapsed -lt $deadline) {
        try {
            $line = $serial.ReadLine()
        } catch [TimeoutException] {
            continue
        }
        $report = ConvertFrom-DiagnosticLine $line
        if ($null -ne $report) {
            $report | ConvertTo-Json -Depth 20
            return
        }
    }
    throw "No complete AIOS Flip4 boot report was received on $Port."
} finally {
    $serial.Dispose()
}
