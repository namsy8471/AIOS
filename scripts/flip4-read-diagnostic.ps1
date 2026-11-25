param(
    [ValidatePattern('^COM[1-9][0-9]*$')][string]$Port,
    [ValidateRange(1, 600)][int]$TimeoutSeconds = 60
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'flip4-windows-serial.ps1')

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

$deadline = [TimeSpan]::FromSeconds($TimeoutSeconds)
$clock = [Diagnostics.Stopwatch]::StartNew()
$serial = Open-Flip4Serial $Port $deadline
try {
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
    throw "No complete AIOS Flip4 boot report was received on $($serial.PortName)."
} finally {
    $serial.Dispose()
}
