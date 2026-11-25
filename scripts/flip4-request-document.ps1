param(
    [Parameter(Mandatory)][string]$Instruction,
    [ValidatePattern('^COM[1-9][0-9]*$')][string]$Port,
    [ValidateRange(1, 600)][int]$TimeoutSeconds = 180
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'flip4-windows-serial.ps1')

function Invoke-Flip4DocumentRequest($Serial, [string]$Text, [TimeSpan]$Timeout) {
    $clock = [Diagnostics.Stopwatch]::StartNew()
    $retryAt = [TimeSpan]::Zero
    $revision = $null
    while ($clock.Elapsed -lt $Timeout) {
        if (-not $revision -and $clock.Elapsed -ge $retryAt) {
            $Serial.WriteLine('inspect')
            $retryAt = $clock.Elapsed.Add([TimeSpan]::FromSeconds(1))
        }
        try {
            $line = $Serial.ReadLine()
        } catch [TimeoutException] {
            continue
        }
        if (-not $revision) {
            if ($line -cmatch '^AIOS_DOCUMENT revision=([0-9a-f]{64}) bytes=[0-9]+$') {
                $revision = $Matches[1]
                $Serial.WriteLine("model-confirm-append $revision $Text")
            }
            continue
        }
        if ($line -cmatch '^AIOS_SAVED revision=([0-9a-f]{64})$') {
            return [ordered]@{status='saved'; previous_revision=$revision; revision=$Matches[1]}
        }
        if ($line -ceq 'AIOS_REJECT confirmation-canceled') {
            return [ordered]@{status='canceled'; revision=$revision}
        }
        if ($line.StartsWith('AIOS_REJECT ', [StringComparison]::Ordinal)) {
            throw $line
        }
    }
    if ($revision) {
        throw 'The document request was sent but its outcome is unknown. Inspect the current document before retrying.'
    }
    throw 'No AIOS document console replied on the USB port.'
}

if ([string]::IsNullOrWhiteSpace($Instruction) -or $Instruction -match '\p{Cc}|<\|' -or
    [Text.Encoding]::UTF8.GetByteCount($Instruction) -gt 512) {
    throw 'Expected a single nonempty instruction of up to 512 UTF-8 bytes.'
}
$deadline = [TimeSpan]::FromSeconds($TimeoutSeconds)
$clock = [Diagnostics.Stopwatch]::StartNew()
$serial = Open-Flip4Serial $Port $deadline
try {
    Invoke-Flip4DocumentRequest $serial $Instruction ($deadline - $clock.Elapsed) | ConvertTo-Json
} finally {
    $serial.Dispose()
}
