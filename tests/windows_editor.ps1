param([Parameter(Mandatory)][string]$Document,
      [ValidateSet('wpf','winforms')][string]$Toolkit = 'wpf', [switch]$Editor)

$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = [Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName PresentationFramework, UIAutomationClient, UIAutomationTypes

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
                return @{ State = 'dialog' }
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
    $roots = @(Find-Elements ([Windows.Automation.AutomationElement]::RootElement) ([Windows.Automation.AutomationElement]::ProcessIdProperty) $child.Id Children)
    $names = @($roots | ForEach-Object { $_.Current.Name }) -join ', '
    throw "Timed out waiting for $expected, last state $($observation.State), windows [$names]"
}

function Get-Pattern($window, $name, $pattern) {
    $matchesFound = @(foreach ($candidate in (Find-Elements $window ([Windows.Automation.AutomationElement]::NameProperty) $name Descendants)) {
        $supported = $null
        if ($candidate.TryGetCurrentPattern($pattern, [ref]$supported)) { $supported }
    })
    if ($matchesFound.Count -ne 1) { throw "Missing or ambiguous $name" }
    $matchesFound[0]
}

if ($Toolkit -eq 'winforms') {
    Add-Type -ReferencedAssemblies Accessibility -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using Accessibility;
public static class NativeEditorText {
    [DllImport("oleacc.dll")]
    private static extern int AccessibleObjectFromWindow(IntPtr hwnd, uint objectId,
        ref Guid iid, [MarshalAs(UnmanagedType.Interface)] out IAccessible result);
    public static void Append(int hwnd, string line) {
        var iid = typeof(IAccessible).GUID;
        IAccessible text;
        Marshal.ThrowExceptionForHR(AccessibleObjectFromWindow(new IntPtr(hwnd), 0xfffffffc, ref iid, out text));
        try {
            text.set_accValue(0, text.get_accValue(0) + "\r\n" + line);
        } finally { Marshal.ReleaseComObject(text); }
    }
}
'@
}

$child = Start-Process powershell -WindowStyle Hidden -PassThru -ArgumentList "-NoProfile -STA -File `"$PSCommandPath`" -Document `"$Document`" -Toolkit $Toolkit -Editor"
try {
    Wait-State ready
    [Console]::WriteLine('ready')
    while ($null -ne ($line = [Console]::ReadLine())) {
        $observation = Get-State
        if ($observation.State -ne 'ready') { [Console]::WriteLine("blocked-$($observation.State)"); continue }
        $main = $observation.Window
        if ($line.StartsWith('append ')) {
            if ($Toolkit -eq 'winforms') {
                $all = $main.FindAll([Windows.Automation.TreeScope]::Descendants, [Windows.Automation.Condition]::TrueCondition)
                $fields = @($all | Where-Object { $_.Current.ClassName -match 'EDIT' -and $_.Current.NativeWindowHandle -ne 0 })
                if ($fields.Count -ne 1) {
                    $tree = @($all | ForEach-Object { "$($_.Current.Name) [$($_.Current.ClassName)]" }) -join ', '
                    throw "Missing or ambiguous native edit control: $tree"
                }
                [NativeEditorText]::Append($fields[0].Current.NativeWindowHandle, $line.Substring(7))
            } else {
                $value = Get-Pattern $main 'Document' ([Windows.Automation.ValuePattern]::Pattern)
                $value.SetValue($value.Current.Value + "`r`n" + $line.Substring(7))
            }
        } elseif ($line -eq 'save') {
            (Get-Pattern $main 'Save' ([Windows.Automation.InvokePattern]::Pattern)).Invoke()
        } elseif ($line -eq 'inject-modal') {
            (Get-Pattern $main 'Open modal' ([Windows.Automation.InvokePattern]::Pattern)).Invoke()
            Wait-State dialog
            [Console]::WriteLine('injected')
            continue
        } else { throw "Unknown command" }
        [Console]::WriteLine('ok')
    }
} finally {
    if (!$child.HasExited) { $child.Kill(); $child.WaitForExit() }
}
