function Initialize-NativeEditorText {
    if ('NativeEditorText' -as [type]) { return }
    Add-Type -ReferencedAssemblies Accessibility -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using Accessibility;
public static class NativeEditorText {
    [DllImport("oleacc.dll")]
    private static extern int AccessibleObjectFromWindow(IntPtr hwnd, uint objectId,
        ref Guid iid, [MarshalAs(UnmanagedType.Interface)] out IAccessible result);
    private static IAccessible Open(int hwnd) {
        var iid = typeof(IAccessible).GUID;
        IAccessible text;
        Marshal.ThrowExceptionForHR(AccessibleObjectFromWindow(new IntPtr(hwnd), 0xfffffffc, ref iid, out text));
        return text;
    }
    public static string Read(int hwnd) {
        var text = Open(hwnd);
        try { return text.get_accValue(0); }
        finally { Marshal.ReleaseComObject(text); }
    }
    public static void Write(int hwnd, string value) {
        var text = Open(hwnd);
        try {
            text.set_accValue(0, value);
        } finally { Marshal.ReleaseComObject(text); }
    }
}
'@
}

function Read-DocumentValue($control) {
    if ($control.Handle -ne 0) { return [NativeEditorText]::Read($control.Handle) }
    return $control.Text.Current.Value
}

function Wait-DocumentValue($control, [string]$expected) {
    $timer = [Diagnostics.Stopwatch]::StartNew()
    do {
        $text = Read-DocumentValue $control
        if ([string]::Equals($text, $expected, [StringComparison]::Ordinal)) {
            return [Diagnostics.Stopwatch]::GetTimestamp()
        }
        [Threading.Thread]::Sleep(1)
    } while ($timer.Elapsed.TotalSeconds -lt 5)
    throw 'Timed out waiting for the expected accessible document value'
}
