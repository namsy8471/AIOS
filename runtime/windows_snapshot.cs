// One UIA cache request per observation. Native patterns live only for this request.
using System;
using System.Windows.Automation;

public sealed class EditorSnapshot {
    public string State = "missing";
    public int Handle;
    public ValuePattern Text;
    public InvokePattern Save;
    public AutomationElement Window;

    private static void Visit(AutomationElement node, string title, bool native,
                              bool inside, EditorSnapshot result) {
        var info = node.Cached;
        var modal = node.GetCachedPropertyValue(WindowPattern.IsModalProperty, true);
        if (modal is bool && (bool)modal && info.Name != title)
            result.State = "dialog";
        if (inside) {
            if (native && info.NativeWindowHandle != 0 &&
                info.ClassName.IndexOf("EDIT", StringComparison.OrdinalIgnoreCase) >= 0) {
                if (result.Handle != 0) throw new InvalidOperationException("Ambiguous edit control");
                result.Handle = info.NativeWindowHandle;
            }
            if (!native && info.Name == "Document") {
                if (result.Text != null) throw new InvalidOperationException("Ambiguous document");
                result.Text = (ValuePattern)node.GetCachedPattern(ValuePattern.Pattern);
            }
            if (info.Name == "Save") {
                object pattern;
                if (node.TryGetCachedPattern(InvokePattern.Pattern, out pattern)) {
                    if (result.Save != null) throw new InvalidOperationException("Ambiguous save button");
                    result.Save = (InvokePattern)pattern;
                }
            }
        }
        var children = node.CachedChildren;
        if (children != null)
            foreach (AutomationElement child in children) Visit(child, title, native, inside, result);
    }

    public static EditorSnapshot Capture(int pid, string title, bool native) {
        var cache = new CacheRequest();
        cache.TreeScope = TreeScope.Subtree;
        cache.TreeFilter = Automation.RawViewCondition;
        cache.Add(AutomationElement.NameProperty);
        cache.Add(AutomationElement.ClassNameProperty);
        cache.Add(AutomationElement.NativeWindowHandleProperty);
        cache.Add(WindowPattern.IsModalProperty);
        cache.Add(InvokePattern.Pattern);
        if (!native) cache.Add(ValuePattern.Pattern);
        var condition = new PropertyCondition(AutomationElement.ProcessIdProperty, pid);
        var desktop = AutomationElement.RootElement;
        AutomationElementCollection roots;
        using (cache.Activate()) roots = desktop.FindAll(TreeScope.Children, condition);
        var result = new EditorSnapshot();
        int mainCount = 0;
        foreach (AutomationElement root in roots) {
            bool main = root.Cached.Name == title;
            if (main) { mainCount++; result.Window = root; }
            Visit(root, title, native, main, result);
        }
        if (result.State != "dialog" && mainCount == 1 &&
            (native ? result.Handle != 0 : result.Text != null) && result.Save != null)
            result.State = "ready";
        return result;
    }
}
