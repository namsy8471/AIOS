param([Parameter(Mandatory)][string]$Document,
      [ValidateSet('wpf','winforms')][string]$Toolkit = 'wpf', [switch]$Editor,
      [switch]$Clock, [string]$LatencyReport)

$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = [Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName PresentationFramework, UIAutomationClient, UIAutomationTypes

function Start-EditorClock {
    $script:sequence = 0
    $script:changes = [Collections.Generic.List[string]]::new()
    $script:nextChange = [Threading.EventWaitHandle]::new(
        $false, [Threading.EventResetMode]::AutoReset, "Local\AIOS-clock-$PID")
    $body.Add_TextChanged({
        $changed = [Diagnostics.Stopwatch]::GetTimestamp()
        $script:changes.Add("$($body.Text)`t$changed")
        if ($script:changes.Count -eq 100) {
            [IO.File]::WriteAllLines("$Document.clock.tmp", [string[]]$script:changes)
            [IO.File]::Move("$Document.clock.tmp", "$Document.clock")
        }
    })
    if ($Toolkit -eq 'wpf') {
        $script:clockTimer = [Windows.Threading.DispatcherTimer]::new()
        $script:clockTimer.Interval = [TimeSpan]::FromMilliseconds(10)
    } else {
        $script:clockTimer = [Windows.Forms.Timer]::new()
        $script:clockTimer.Interval = 10
    }
    $script:clockTimer.Add_Tick({
        if ($script:nextChange.WaitOne(0)) {
            $script:sequence++
            $body.Text = "$([char]0xAD00)$([char]0xCE21) $script:sequence"
        }
    })
    $script:clockTimer.Start()
}

if ($Editor -and $Toolkit -eq 'winforms') {
    Add-Type -AssemblyName System.Windows.Forms
    $form = [Windows.Forms.Form]::new()
    $form.Text = 'AIOS test editor'
    $form.AccessibleName = 'AIOS test editor'
    $body = [Windows.Forms.TextBox]::new()
    $body.Multiline = $true
    $body.Name = 'documentBody'
    $body.AccessibleName = 'Document'
    $body.Text = [IO.File]::ReadAllText($Document)
    $save = [Windows.Forms.Button]::new()
    $save.Text = 'Save'
    $save.Add_Click({
        [IO.File]::WriteAllText($Document, $body.Text.Replace("`r`n", "`n"), [Text.UTF8Encoding]::new($false))
    })
    $inject = [Windows.Forms.Button]::new()
    $inject.Text = 'Open modal'
    $inject.Add_Click({
        $dialog = [Windows.Forms.Form]::new()
        $dialog.Text = 'Save document'
        try { [void]$dialog.ShowDialog($form) } finally { $dialog.Dispose() }
    })
    $layout = [Windows.Forms.FlowLayoutPanel]::new()
    $layout.Dock = 'Fill'
    foreach ($item in $body, $save, $inject) { $layout.Controls.Add($item) }
    $form.Controls.Add($layout)
    if ($Clock) { Start-EditorClock }
    $form.Show()
    $form.Activate()
    [Windows.Forms.Application]::Run($form)
    exit
}

if ($Editor) {
    $window = [Windows.Window]::new()
    $window.Title = 'AIOS test editor'
    $body = [Windows.Controls.TextBox]::new()
    $body.AcceptsReturn = $true
    $body.Text = [IO.File]::ReadAllText($Document)
    [Windows.Automation.AutomationProperties]::SetName($body, 'Document')
    $save = [Windows.Controls.Button]::new()
    $save.Content = 'Save'
    $save.Add_Click({
        [IO.File]::WriteAllText($Document, $body.Text.Replace("`r`n", "`n"), [Text.UTF8Encoding]::new($false))
    })
    $inject = [Windows.Controls.Button]::new()
    $inject.Content = 'Open modal'
    $inject.Add_Click({
        $dialog = [Windows.Window]::new()
        $dialog.Title = 'Save document'
        $dialog.Owner = $window
        [void]$dialog.ShowDialog()
    })
    $panel = [Windows.Controls.StackPanel]::new()
    foreach ($item in $body, $save, $inject) { [void]$panel.Children.Add($item) }
    $window.Content = $panel
    if ($Clock) { Start-EditorClock }
    [void]$window.ShowDialog()
    exit
}

$runtime = Join-Path $PSScriptRoot '../runtime'
. (Join-Path $runtime 'windows_text.ps1')
if (!('EditorSnapshot' -as [type])) {
    $references = @([Windows.Automation.AutomationElement].Assembly.Location,
                    [Windows.Automation.AutomationPattern].Assembly.Location,
                    [Windows.Rect].Assembly.Location)
    Add-Type -Path (Join-Path $runtime 'windows_snapshot.cs') -ReferencedAssemblies $references
}
if ($Toolkit -eq 'winforms') { Initialize-NativeEditorText }

function Get-State {
    [EditorSnapshot]::Capture($child.Id, 'AIOS test editor', ($Toolkit -eq 'winforms'))
}

function Wait-State($expected) {
    $deadline = [DateTime]::UtcNow.AddSeconds(20)
    do {
        if ($child.HasExited) { throw 'editor exited' }
        $observation = Get-State
        if ($observation.State -eq $expected) { return }
        Start-Sleep -Milliseconds 60
    } while ([DateTime]::UtcNow -lt $deadline)
    throw "Timed out waiting for $expected, last state $($observation.State)"
}

$clockOption = if ($LatencyReport) { '-Clock' } else { '' }

$child = Start-Process powershell -WindowStyle Hidden -PassThru -ArgumentList "-NoProfile -STA -File `"$PSCommandPath`" -Document `"$Document`" -Toolkit $Toolkit -Editor $clockOption"
try {
    Wait-State ready
    if ($LatencyReport) {
        $control = Get-State
        $trigger = [Threading.EventWaitHandle]::OpenExisting("Local\AIOS-clock-$($child.Id)")
        $observed = try {
            foreach ($index in 1..100) {
                [void]$trigger.Set()
                Wait-DocumentValue $control "$([char]0xAD00)$([char]0xCE21) $index"
            }
        } finally { $trigger.Dispose() }
        $limit = [Diagnostics.Stopwatch]::StartNew()
        while (!(Test-Path -LiteralPath "$Document.clock") -and $limit.Elapsed.TotalSeconds -lt 5) {
            [Threading.Thread]::Sleep(5)
        }
        $records = [IO.File]::ReadAllLines("$Document.clock")
        if ($records.Count -ne $observed.Count) { throw 'Unpaired observations' }
        $frequency = [Diagnostics.Stopwatch]::Frequency
        $samples = for ($i = 0; $i -lt $observed.Count; $i++) {
            $value, $stamp = $records[$i] -split "`t", 2
            if ($value -cne "$([char]0xAD00)$([char]0xCE21) $($i + 1)") { throw 'Source value mismatch' }
            $changed = [long]$stamp
            $elapsed = $observed[$i] - $changed
            if ($elapsed -lt 0) { throw 'Observation preceded its source' }
            [ordered]@{ index = $i + 1; changed_ticks = $changed; observed_ticks = $observed[$i];
                latency_ms = $elapsed * 1000.0 / $frequency }
        }
        $times = @($samples | ForEach-Object { $_.latency_ms } | Sort-Object)
        $report = [ordered]@{ toolkit = $Toolkit; frequency = $frequency; count = $samples.Count;
            p95_ms = $times[94]; max_ms = $times[-1]; samples = $samples }
        [IO.File]::WriteAllText($LatencyReport, ($report | ConvertTo-Json -Depth 4))
        return
    }
    [Console]::WriteLine('ready')
    while ($null -ne ($line = [Console]::ReadLine())) {
        $observation = Get-State
        if ($line -eq 'observe') {
            $nodes = @()
            if ($observation.State -eq 'ready') {
                $control = $observation
                $nodes = @(
                    @{element_id='body'; name='Document'; role='textbox'; actions=@('append');
                      value=(Read-DocumentValue $control).Replace("`r`n", "`n")}
                    @{element_id='save'; name='Save'; role='button'; actions=@('invoke')}
                )
            }
            [Console]::WriteLine((@{state=$observation.State; elements=$nodes} | ConvertTo-Json -Depth 5 -Compress))
            continue
        }
        if ($observation.State -ne 'ready') { [Console]::WriteLine("blocked-$($observation.State)"); continue }
        if ($line.StartsWith('append ')) {
            $control = $observation
            $expected = (Read-DocumentValue $control) + "`r`n" + $line.Substring(7)
            if ($Toolkit -eq 'winforms') {
                [NativeEditorText]::Write($control.Handle, $expected)
            } else {
                $control.Text.SetValue($expected)
            }
            [void](Wait-DocumentValue $control $expected)
        } elseif ($line -eq 'save') {
            $observation.Save.Invoke()
        } elseif ($line -eq 'inject-modal') {
            $observation.OpenModal.Invoke()
            Wait-State dialog
            [Console]::WriteLine('injected')
            continue
        } else { throw "Unknown command" }
        [Console]::WriteLine('ok')
    }
} finally {
    if (!$child.HasExited) { $child.Kill(); $child.WaitForExit() }
}
