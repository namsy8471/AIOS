using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;

namespace Tla.Desktop;

public partial class MainWindow : Window
{
    private bool busy;

    public MainWindow()
    {
        InitializeComponent();
        Loaded += (_, _) => LoadTargets();
    }

    private void RefreshTargets(object sender, RoutedEventArgs e) { if (!busy) LoadTargets(); }

    private void LoadTargets()
    {
        var selected = Targets.SelectedItem as WindowActions.Target;
        Targets.ItemsSource = WindowActions.ListTargets();
        Targets.SelectedItem = selected;
        if (Targets.SelectedItem is null) Status.Text = "작업할 앱 창을 선택하세요.";
    }

    private async void TargetChanged(object sender, SelectionChangedEventArgs e)
    {
        Controls.ItemsSource = null;
        if (Targets.SelectedItem is WindowActions.Target target)
            await Run(async () => ShowControls(await Task.Run(() => WindowActions.Read(target))));
    }

    private void ShowControls(IReadOnlyList<WindowActions.Control> controls)
    {
        Controls.ItemsSource = controls;
        Status.Text = controls.Count == 0 ? "이 창에서 실행할 수 있는 버튼을 찾지 못했어요." : "이 창에서 실행할 수 있는 버튼";
    }

    private async void ReviewControl(object sender, RoutedEventArgs e)
    {
        if (Targets.SelectedItem is WindowActions.Target target && Controls.SelectedItem is WindowActions.Control control)
            await Run(() => Approve(target, control));
    }

    private async void SubmitInstruction(object sender, RoutedEventArgs e) => await Propose();

    private async void InstructionKeyDown(object sender, KeyEventArgs e)
    {
        if (e.Key != Key.Enter) return;
        e.Handled = true;
        await Propose();
    }

    private async Task Propose()
    {
        if (Targets.SelectedItem is not WindowActions.Target target) return;
        string text = Instruction.Text.Trim();
        if (text.Length == 0) return;
        await Run(async () =>
        {
            var controls = await Task.Run(() => WindowActions.Read(target));
            var choice = await LocalScreenModel.Choose(text, controls);
            if (choice is null) Status.Text = "이 창에서 지시와 일치하는 버튼을 찾지 못했어요.";
            else await Approve(target, choice);
        });
    }

    private async Task Approve(WindowActions.Target target, WindowActions.Control control)
    {
        if (MessageBox.Show(this, $"{target.Title}\n\n‘{control.Name}’ 버튼을 누를까요?", "TLA 동작 승인",
                MessageBoxButton.YesNo, MessageBoxImage.Question, MessageBoxResult.No) != MessageBoxResult.Yes)
        {
            Status.Text = "동작을 취소했어요.";
            return;
        }
        await Task.Run(() => WindowActions.Invoke(target, control));
        Status.Text = $"‘{control.Name}’ 버튼에 누르기 동작을 전달했어요.";
    }

    private async Task Run(Func<Task> action)
    {
        if (busy) return;
        busy = true;
        Targets.IsEnabled = Send.IsEnabled = false;
        Status.Text = "선택한 창을 확인하는 중이에요.";
        try { await action(); }
        catch (Exception error) { Status.Text = error.Message; }
        finally
        {
            busy = false;
            Targets.IsEnabled = Send.IsEnabled = true;
        }
    }
}
