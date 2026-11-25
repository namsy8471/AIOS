using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text;
using System.Windows.Automation;

namespace Tla.Desktop;

internal static class WindowActions
{
    internal sealed record Target(nint Handle, int ProcessId, long Started, string Title);
    internal sealed record Control(string Name, string Id)
    {
        public override string ToString() => Name;
    }

    public static IReadOnlyList<Target> ListTargets()
    {
        var windows = new List<Target>();
        EnumWindows((handle, _) =>
        {
            GetWindowThreadProcessId(handle, out int pid);
            if (pid == Environment.ProcessId || !IsWindowVisible(handle) || GetWindow(handle, 4) != 0) return true;
            var title = new StringBuilder(260);
            if (GetWindowText(handle, title, title.Capacity) == 0) return true;
            long started = StartTime(pid);
            if (started != 0) windows.Add(new Target(handle, pid, started, title.ToString()));
            return true;
        }, 0);
        return windows.OrderBy(item => item.Title, StringComparer.CurrentCultureIgnoreCase).ToArray();
    }

    public static IReadOnlyList<Control> Read(Target target) => Capture(target).Select(item => item.Control).ToArray();

    public static void Invoke(Target target, Control approved)
    {
        var match = Capture(target).SingleOrDefault(item => item.Control == approved);
        if (match.Pattern is null) throw new InvalidOperationException("버튼 이름이나 위치가 바뀌었어요. 다시 확인해 주세요.");
        match.Pattern.Invoke();
    }

    private static List<(Control Control, InvokePattern Pattern)> Capture(Target target)
    {
        GetWindowThreadProcessId(target.Handle, out int pid);
        if (pid != target.ProcessId || StartTime(pid) != target.Started || !IsWindowVisible(target.Handle))
            throw new InvalidOperationException("선택한 창을 다시 열거나 선택해 주세요.");
        var ownedWindows = new List<nint>();
        EnumWindows((handle, _) =>
        {
            if (IsWindowVisible(handle) && GetWindow(handle, 4) == target.Handle) ownedWindows.Add(handle);
            return true;
        }, 0);
        foreach (nint handle in ownedWindows)
        {
            var window = AutomationElement.FromHandle(handle);
            if (window.TryGetCurrentPattern(WindowPattern.Pattern, out object raw) && ((WindowPattern)raw).Current.IsModal)
                throw new InvalidOperationException("선택한 창에서 열린 대화 상자를 먼저 확인해 주세요.");
        }

        var root = AutomationElement.FromHandle(target.Handle);
        var result = new List<(Control Control, InvokePattern Pattern)>();
        var nodes = new Queue<AutomationElement>();
        var tree = TreeWalker.ControlViewWalker;
        nodes.Enqueue(root);
        int remaining = 500;
        while (nodes.TryDequeue(out var node) && remaining-- > 0)
        {
            var info = node.Current;
            if (info.ProcessId != target.ProcessId || info.IsPassword || info.IsOffscreen) continue;
            if (node != root && info.IsEnabled && info.ControlType == ControlType.Button
                && info.Name.Length is > 0 and <= 96 && !info.Name.Any(char.IsControl)
                && node.TryGetCurrentPattern(InvokePattern.Pattern, out object pattern))
            {
                result.Add((new Control(info.Name, string.Join(".", node.GetRuntimeId())), (InvokePattern)pattern));
            }
            for (var child = tree.GetFirstChild(node); child is not null && nodes.Count < remaining;
                 child = tree.GetNextSibling(child)) nodes.Enqueue(child);
        }
        return result.GroupBy(item => item.Control.Name, StringComparer.OrdinalIgnoreCase)
            .Where(group => group.Count() == 1).Select(group => group.Single()).Take(32).ToList();
    }

    private static long StartTime(int pid)
    {
        try
        {
            using var process = Process.GetProcessById(pid);
            return process.StartTime.ToUniversalTime().Ticks;
        }
        catch (ArgumentException) { return 0; }
        catch (InvalidOperationException) { return 0; }
        catch (System.ComponentModel.Win32Exception) { return 0; }
    }

    private delegate bool WindowVisitor(nint handle, nint param);
    [DllImport("user32.dll")] private static extern bool EnumWindows(WindowVisitor callback, nint param);
    [DllImport("user32.dll")] private static extern uint GetWindowThreadProcessId(nint handle, out int pid);
    [DllImport("user32.dll")] private static extern bool IsWindowVisible(nint handle);
    [DllImport("user32.dll")] private static extern nint GetWindow(nint handle, uint command);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern int GetWindowText(nint handle, StringBuilder text, int capacity);
}
