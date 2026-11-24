# Attach to one operator-selected editor and leave its lifetime under operator control.
param([Parameter(Mandatory)][int]$ProcessId,
      [Parameter(Mandatory)][string]$Title,
      [Parameter(Mandatory)][ValidateSet('wpf','winforms')][string]$Toolkit)

$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = [Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName PresentationFramework, UIAutomationClient, UIAutomationTypes
. (Join-Path $PSScriptRoot 'windows_adapter.ps1')
$target = Get-Process -Id $ProcessId
try {
    $null = $target.Handle
    $initial = [EditorSnapshot]::Capture($ProcessId, $Title, ($Toolkit -eq 'winforms'))
    if ($target.HasExited -or $initial.State -ne 'ready') { throw 'Selected editor is unavailable' }
    [Console]::WriteLine('ready')
    while ($null -ne ($line = [Console]::ReadLine())) {
        if ($target.HasExited) { throw 'Selected editor closed' }
        $view = [EditorSnapshot]::Capture($ProcessId, $Title, ($Toolkit -eq 'winforms'))
        [Console]::WriteLine((Invoke-EditorCommand $view $Toolkit $line))
    }
} finally {
    $target.Dispose()
}
