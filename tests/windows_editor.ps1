param([Parameter(Mandatory)][string]$Document, [switch]$Editor)

$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = [Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName PresentationFramework, UIAutomationClient, UIAutomationTypes

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
    [void]$window.ShowDialog()
    exit
}

function Find-Elements($parent, $property, $value, $scope) {
    $condition = [Windows.Automation.PropertyCondition]::new($property, $value)
    $parent.FindAll($scope, $condition)
}

function Get-State {
    $elements = @(Find-Elements ([Windows.Automation.AutomationElement]::RootElement) ([Windows.Automation.AutomationElement]::ProcessIdProperty) $child.Id Children)
    $main = $null
    foreach ($elem in $elements) {
        if ($elem.Current.Name -eq 'AIOS test editor') { $main = $elem }
        $windows = @($elem) + @(Find-Elements $elem ([Windows.Automation.AutomationElement]::ControlTypeProperty) ([Windows.Automation.ControlType]::Window) Descendants)
        foreach ($w in $windows) {
            $pattern = $null
            if ($w.TryGetCurrentPattern([Windows.Automation.WindowPattern]::Pattern, [ref]$pattern) -and $pattern.Current.IsModal -and $w.Current.Name -ne 'AIOS test editor') {
                return @{ State = 'modal' }
            }
        }
    }
    if ($null -eq $main) { return @{ State = 'missing' } }
    return @{ State = 'ready'; Window = $main }
}

function Wait-State($expected) {
    $deadline = [DateTime]::UtcNow.AddSeconds(20)
    do {
        if ($child.HasExited) { throw 'editor exited' }
        $observation = Get-State
        if ($observation.State -eq $expected) { return }
        Start-Sleep -Milliseconds 60
    } while ([DateTime]::UtcNow -lt $deadline)
    throw "Timed out waiting for $expected"
}

function Get-Pattern($window, $name, $pattern) {
    $matchesFound = @(foreach ($candidate in (Find-Elements $window ([Windows.Automation.AutomationElement]::NameProperty) $name Descendants)) {
        $supported = $null
        if ($candidate.TryGetCurrentPattern($pattern, [ref]$supported)) { $supported }
    })
    if ($matchesFound.Count -ne 1) { throw "Missing or ambiguous $name" }
    $matchesFound[0]
}

$child = Start-Process powershell -WindowStyle Hidden -PassThru -ArgumentList "-NoProfile -STA -File `"$PSCommandPath`" -Document `"$Document`" -Editor"
try {
    Wait-State ready
    [Console]::WriteLine('ready')
    while ($null -ne ($line = [Console]::ReadLine())) {
        $observation = Get-State
        if ($observation.State -ne 'ready') { [Console]::WriteLine("blocked-$($observation.State)"); continue }
        $main = $observation.Window
        if ($line.StartsWith('append ')) {
            $value = Get-Pattern $main 'Document' ([Windows.Automation.ValuePattern]::Pattern)
            $value.SetValue($value.Current.Value + "`r`n" + $line.Substring(7))
        } elseif ($line -eq 'save') {
            (Get-Pattern $main 'Save' ([Windows.Automation.InvokePattern]::Pattern)).Invoke()
        } elseif ($line -eq 'inject-modal') {
            (Get-Pattern $main 'Open modal' ([Windows.Automation.InvokePattern]::Pattern)).Invoke()
            Wait-State modal
            [Console]::WriteLine('injected')
            continue
        } else { throw "Unknown command" }
        [Console]::WriteLine('ok')
    }
} finally {
    if (!$child.HasExited) { $child.Kill(); $child.WaitForExit() }
}
