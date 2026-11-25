using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Net;
using System.Text;
using System.Text.RegularExpressions;
using System.Windows.Media;
using System.Windows.Media.Imaging;

namespace Tla.Desktop;

internal sealed partial class PhoneBridge
{
    internal sealed record Frame(string Target, string Window, BitmapSource Image);
    internal sealed record Receipt(string State, string Reply);
    private readonly HashSet<IPAddress> paired = new();
    private readonly HashSet<string> connected = new(StringComparer.Ordinal);
    private readonly string adb = FindAdb();

    public async Task Pair(string address, string code)
    {
        var endpoint = Parse(address);
        if (code.Length != 6 || !code.All(char.IsAsciiDigit)) throw new InvalidOperationException("휴대폰에 표시된 6자리 코드를 입력하세요.");
        string reply = await Text(["pair", endpoint.ToString()], code);
        if (!reply.Contains("Successfully paired", StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException("페어링이 완료되지 않았어요. 휴대폰의 주소와 코드를 다시 확인하세요.");
        paired.Add(endpoint.Address);
    }

    public async Task Connect(string address)
    {
        var endpoint = Parse(address);
        string serial = endpoint.ToString();
        if (!paired.Contains(endpoint.Address))
        {
            string discovery = await Text(["mdns", "services"]);
            if (!discovery.Split('\n').Any(line => line.Contains("_adb-tls-connect._tcp", StringComparison.Ordinal)
                    && line.Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries).LastOrDefault() == serial))
                throw new InvalidOperationException("이 주소를 무선 디버깅에서 먼저 페어링해 주세요.");
        }
        string reply = await Text(["connect", serial]);
        if (!reply.Contains($"connected to {serial}", StringComparison.OrdinalIgnoreCase)
                || (await Text(["-s", serial, "get-state"])).Trim() != "device")
            throw new InvalidOperationException("휴대폰에 연결하지 못했어요. 무선 디버깅 기본 화면의 IP와 포트를 확인하세요.");
        connected.Add(serial);
    }

    public async Task<IReadOnlyList<string>> Devices()
    {
        string result = await Text(["devices"]);
        return result.Split('\n').Select(line => line.Trim().Split('\t'))
            .Where(columns => columns.Length == 2 && columns[1] == "device"
                && (columns[0].Contains("._adb-tls-connect._tcp", StringComparison.Ordinal) || connected.Contains(columns[0])))
            .Select(columns => columns[0]).Distinct().ToArray();
    }

    public async Task<string> SendInstruction(string target, string instruction)
    {
        if (!(await Devices()).Contains(target)) throw new InvalidOperationException("휴대폰의 무선 연결을 확인해 주세요.");
        if (instruction.Length is < 1 or > 400 || instruction.Any(char.IsControl))
            throw new InvalidOperationException("400자 이내의 한 줄 지시를 입력하세요.");
        string id = Guid.NewGuid().ToString("N");
        string data = Convert.ToBase64String(Encoding.UTF8.GetBytes(instruction));
        string reply = await Text(["-s", target, "shell", "am", "start", "-W", "-n", "org.aios.mobile/.RemoteCommandActivity",
            "--es", "request_id", id, "--es", "command_b64", data]);
        if (!reply.Contains("Status: ok", StringComparison.Ordinal))
            throw new InvalidOperationException("휴대폰에서 지시를 받지 못했어요. 최신 TLA가 설치되어 있는지 확인하세요.");
        return id;
    }

    public async Task<Receipt?> ReadReceipt(string target, string id)
    {
        string raw = await Text(["-s", target, "shell", "content", "query", "--uri", $"content://org.aios.mobile.remote/{id}"]);
        var fields = ReceiptRow().Match(raw);
        return fields.Success ? new Receipt(fields.Groups[1].Value,
            Encoding.UTF8.GetString(Convert.FromBase64String(fields.Groups[2].Value))) : null;
    }

    public async Task<Frame> Capture(string target)
    {
        string window = await Focus(target);
        byte[] png = await Run(["-s", target, "exec-out", "screencap", "-p"]);
        if (window != await Focus(target)) throw new InvalidOperationException("화면이 전환됐어요. 새로고침해 주세요.");
        int start = png.AsSpan().IndexOf(new byte[] { 137, 80, 78, 71, 13, 10, 26, 10 });
        if (start < 0) throw new InvalidOperationException("휴대폰 화면을 읽지 못했어요.");
        using var stream = new MemoryStream(png, start, png.Length - start, false);
        var source = BitmapFrame.Create(stream, BitmapCreateOptions.None, BitmapCacheOption.OnLoad);
        var pixels = new FormatConvertedBitmap(source, PixelFormats.Bgra32, null, 0);
        pixels.Freeze();
        return new Frame(target, window, pixels);
    }

    public async Task Tap(Frame approved, int x, int y)
    {
        var current = await Capture(approved.Target);
        if (approved.Window != current.Window || approved.Image.PixelWidth != current.Image.PixelWidth
            || approved.Image.PixelHeight != current.Image.PixelHeight || !NearPointMatches(approved.Image, current.Image, x, y))
            throw new InvalidOperationException("승인한 위치의 화면이 바뀌었어요. 새로고침 후 다시 선택하세요.");
        await Run(["-s", approved.Target, "shell", "input", "tap", x.ToString(CultureInfo.InvariantCulture), y.ToString(CultureInfo.InvariantCulture)]);
    }

    private async Task<string> Focus(string target)
    {
        string output = await Text(["-s", target, "shell", "dumpsys", "window", "displays"]);
        var found = FocusedWindow().Matches(output).Select(item => item.Groups[1].Value.Trim()).Distinct().ToArray();
        if (found.Length != 1 || found[0].Contains("NotificationShade", StringComparison.Ordinal)
            || found[0].Contains("Keyguard", StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException("휴대폰 잠금을 풀고 조작할 화면을 열어 주세요.");
        return found[0];
    }

    private static bool NearPointMatches(BitmapSource before, BitmapSource after, int x, int y)
    {
        if (x < 0 || y < 0 || x >= before.PixelWidth || y >= before.PixelHeight) return false;
        int radius = Math.Max(12, Math.Min(before.PixelWidth, before.PixelHeight) / 30);
        var rect = new System.Windows.Int32Rect(Math.Max(0, x - radius), Math.Max(0, y - radius), 1, 1);
        rect.Width = Math.Min(before.PixelWidth, x + radius + 1) - rect.X;
        rect.Height = Math.Min(before.PixelHeight, y + radius + 1) - rect.Y;
        int stride = rect.Width * 4;
        byte[] oldPixels = new byte[stride * rect.Height];
        byte[] newPixels = new byte[oldPixels.Length];
        before.CopyPixels(rect, oldPixels, stride, 0);
        after.CopyPixels(rect, newPixels, stride, 0);
        return oldPixels.AsSpan().SequenceEqual(newPixels);
    }

    private async Task<string> Text(string[] args, string? input = null) => Encoding.UTF8.GetString(await Run(args, input));

    private async Task<byte[]> Run(string[] args, string? input = null)
    {
        var start = new ProcessStartInfo(adb) { UseShellExecute = false, CreateNoWindow = true,
            RedirectStandardOutput = true, RedirectStandardError = true, RedirectStandardInput = input is not null };
        foreach (string arg in args) start.ArgumentList.Add(arg);
        using var process = Process.Start(start) ?? throw new IOException("Android 플랫폼 도구 ADB를 찾을 수 없어요.");
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(12));
        try
        {
            var output = ReadOutput(process.StandardOutput.BaseStream, timeout.Token);
            var errors = process.StandardError.ReadToEndAsync(timeout.Token);
            if (input is not null)
            {
                await process.StandardInput.WriteLineAsync(input.AsMemory(), timeout.Token);
                process.StandardInput.Close();
            }
            await process.WaitForExitAsync(timeout.Token);
            await errors;
            if (process.ExitCode != 0) throw new IOException("휴대폰 연결을 확인하고 다시 시도해 주세요.");
            return await output;
        }
        catch (OperationCanceledException)
        {
            if (!process.HasExited) process.Kill();
            throw new IOException("휴대폰 응답이 늦어요. 연결을 확인해 주세요.");
        }
    }

    private static async Task<byte[]> ReadOutput(Stream stream, CancellationToken token)
    {
        using var output = new MemoryStream();
        var buffer = new byte[8192];
        for (int count; (count = await stream.ReadAsync(buffer, token)) > 0;)
        {
            if (output.Length + count > 32 * 1024 * 1024) throw new IOException("휴대폰 화면이 너무 커요.");
            output.Write(buffer, 0, count);
        }
        return output.ToArray();
    }

    private static IPEndPoint Parse(string text) => IPEndPoint.TryParse(text.Trim(), out var address) && address.Port != 0
        ? address : throw new InvalidOperationException("휴대폰에 표시된 IP:포트 주소를 입력하세요.");

    private static string FindAdb()
    {
        if (Environment.GetEnvironmentVariable("TLA_WINDOWS_ADB") is string configured) return configured;
        for (var root = new DirectoryInfo(AppContext.BaseDirectory); root is not null; root = root.Parent)
        {
            string discovered = Path.Combine(root.FullName, "build", "sdk", "android", "platform-tools", "adb.exe");
            if (File.Exists(discovered)) return discovered;
        }
        return "adb.exe";
    }

    [GeneratedRegex(@"mCurrentFocus=Window\{([^\r\n}]+)\}")]
    private static partial Regex FocusedWindow();

    [GeneratedRegex(@"state=(pending|accepted|cancelled|reply), reply_b64=([A-Za-z0-9+/=]*)")]
    private static partial Regex ReceiptRow();
}
