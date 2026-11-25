using System.Collections.ObjectModel;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;

namespace Tla.Desktop;

public partial class MainWindow : Window
{
    private bool busy;
    private bool phoneBusy;
    private readonly PhoneBridge phone = new();
    private readonly ObservableCollection<string> phoneMessages = new();
    private PhoneBridge.Frame? phoneFrame;

    public MainWindow()
    {
        InitializeComponent();
        PhoneConversation.ItemsSource = phoneMessages;
        Loaded += async (_, _) =>
        {
            LoadTargets();
            await WithPhone(RefreshDevices);
        };
    }

    private async void PairPhone(object sender, RoutedEventArgs e) => await WithPhone(async () =>
    {
        string code = PairCode.Password;
        PairCode.Clear();
        await phone.Pair(PairAddress.Text, code);
        await LoadPhones();
        PhoneStatus.Text = "페어링했어요. 목록에서 휴대폰을 선택하거나 무선 디버깅 기본 화면의 주소로 연결하세요.";
    });

    private async void ConnectPhone(object sender, RoutedEventArgs e) => await WithPhone(async () =>
    {
        await phone.Connect(ConnectAddress.Text);
        var devices = await LoadPhones();
        if (devices.Count == 1)
        {
            Phones.SelectedItem = devices[0];
            PhoneStatus.Text = "휴대폰에 보낼 지시를 입력하세요.";
        }
        else PhoneStatus.Text = "연결할 휴대폰을 목록에서 선택하세요.";
    });

    private async void RefreshPhone(object sender, RoutedEventArgs e) => await WithPhone(RefreshDevices);

    private async Task RefreshDevices()
    {
        ClearPhone();
        string? selected = Phones.SelectedItem as string;
        var devices = await LoadPhones();
        if (selected is null && devices.Count == 1) selected = devices[0];
        if (selected is not null && devices.Contains(selected))
        {
            Phones.SelectedItem = selected;
            PhoneStatus.Text = "휴대폰에 보낼 지시를 입력하세요.";
        }
        else PhoneStatus.Text = devices.Count == 0 ? "페어링된 무선 휴대폰을 찾지 못했어요." : "휴대폰을 선택하세요.";
    }

    private async void RefreshPhoneImage(object sender, RoutedEventArgs e)
    {
        if (Phones.SelectedItem is string target) await WithPhone(() => ShowPhone(target));
    }

    private async Task<IReadOnlyList<string>> LoadPhones()
    {
        var devices = await phone.Devices();
        Phones.ItemsSource = devices;
        return devices;
    }

    private void PhoneChanged(object sender, SelectionChangedEventArgs e)
    {
        if (phoneBusy) return;
        ClearPhone();
        if (Phones.SelectedItem is string) PhoneStatus.Text = "휴대폰에 보낼 지시를 입력하세요.";
    }

    private async void SubmitPhone(object sender, RoutedEventArgs e) => await SendToPhone();

    private async void PhoneInstructionKeyDown(object sender, KeyEventArgs e)
    {
        if (e.Key != Key.Enter) return;
        e.Handled = true;
        await SendToPhone();
    }

    private async Task SendToPhone()
    {
        if (phoneBusy || Phones.SelectedItem is not string target) return;
        string request = PhoneInstruction.Text.Trim();
        if (request.Length == 0) return;
        await WithPhone(async () =>
        {
            string id = await phone.SendInstruction(target, request);
            AddPhoneMessage("나 · " + request);
            PhoneInstruction.Clear();
            PhoneStatus.Text = "보냈어요. 휴대폰에서 요청을 승인해 주세요.";
            _ = WatchReceipt(target, id);
        });
    }

    private async Task WatchReceipt(string target, string id)
    {
        DateTime deadline = DateTime.UtcNow.AddMinutes(3);
        bool accepted = false;
        try
        {
            while (DateTime.UtcNow < deadline)
            {
                var receipt = await phone.ReadReceipt(target, id);
                if (receipt?.State is "reply" or "cancelled")
                {
                    AddPhoneMessage("휴대폰 · " + receipt.Reply);
                    return;
                }
                if (!accepted && receipt?.State == "accepted")
                {
                    accepted = true;
                    AddPhoneMessage("휴대폰 · " + receipt.Reply);
                }
                await Task.Delay(1500);
            }
            AddPhoneMessage("휴대폰 · 아직 응답을 확인하지 못했어요.");
        }
        catch (Exception) { AddPhoneMessage("휴대폰 · 응답을 확인하려면 무선 연결을 확인해 주세요."); }
    }

    private void AddPhoneMessage(string message)
    {
        phoneMessages.Add(message);
        PhoneConversation.ScrollIntoView(message);
    }

    private async Task ShowPhone(string target)
    {
        ClearPhone();
        phoneFrame = await phone.Capture(target);
        PhoneImage.Source = phoneFrame.Image;
        PhoneStatus.Text = "휴대폰 화면에서 누를 위치를 선택하세요.";
    }

    private async void TapPhone(object sender, MouseButtonEventArgs e)
    {
        if (phoneBusy || phoneFrame is not { } approved || !Equals(Phones.SelectedItem, approved.Target)) return;
        var point = e.GetPosition(PhoneImage);
        double scale = Math.Min(PhoneImage.ActualWidth / approved.Image.PixelWidth, PhoneImage.ActualHeight / approved.Image.PixelHeight);
        if (scale <= 0) return;
        double x = (point.X - (PhoneImage.ActualWidth - approved.Image.PixelWidth * scale) / 2) / scale;
        double y = (point.Y - (PhoneImage.ActualHeight - approved.Image.PixelHeight * scale) / 2) / scale;
        if (x < 0 || y < 0 || x >= approved.Image.PixelWidth || y >= approved.Image.PixelHeight) return;
        if (MessageBox.Show(this, "표시 중인 휴대폰 화면의 선택한 위치를 누를까요?", "TLA 휴대폰 동작 승인",
                MessageBoxButton.YesNo, MessageBoxImage.Question, MessageBoxResult.No) != MessageBoxResult.Yes) return;
        await WithPhone(async () =>
        {
            ClearPhone();
            await phone.Tap(approved, (int)x, (int)y);
            await Task.Delay(300);
            try { await ShowPhone(approved.Target); }
            catch (Exception) { PhoneStatus.Text = "입력을 보냈어요. 새 화면은 새로고침해 주세요."; }
        });
    }

    private void ClearPhone()
    {
        phoneFrame = null;
        PhoneImage.Source = null;
    }

    private async Task WithPhone(Func<Task> action)
    {
        if (phoneBusy) return;
        phoneBusy = true;
        Phones.IsEnabled = SendPhone.IsEnabled = false;
        PhoneStatus.Text = "휴대폰 응답을 기다리는 중이에요.";
        try { await action(); }
        catch (Exception error) { ClearPhone(); PhoneStatus.Text = error.Message; }
        finally { phoneBusy = false; Phones.IsEnabled = SendPhone.IsEnabled = true; }
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
