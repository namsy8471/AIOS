. (Join-Path $PSScriptRoot 'windows_text.ps1')
if (!('EditorSnapshot' -as [type])) {
    $references = @([Windows.Automation.AutomationElement].Assembly.Location,
                    [Windows.Automation.AutomationPattern].Assembly.Location,
                    [Windows.Rect].Assembly.Location)
    Add-Type -Path (Join-Path $PSScriptRoot 'windows_snapshot.cs') -ReferencedAssemblies $references
}
if ($Toolkit -eq 'winforms') { Initialize-NativeEditorText }


function Invoke-EditorCommand($observation, $toolkitName, $line) {
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
        return (@{state=$observation.State; elements=$nodes} | ConvertTo-Json -Depth 5 -Compress)
    }
    if ($observation.State -ne 'ready') { return "blocked-$($observation.State)" }
    if ($line.StartsWith('append ')) {
        $control = $observation
        $expected = (Read-DocumentValue $control) + "`r`n" + $line.Substring(7)
        if ($toolkitName -eq 'winforms') {
            [NativeEditorText]::Write($control.Handle, $expected)
        } else {
            $control.Text.SetValue($expected)
        }
        [void](Wait-DocumentValue $control $expected)
    } elseif ($line -eq 'save') {
        $observation.Save.Invoke()
    } else { throw "Unknown editor command" }
    return 'ok'
}
