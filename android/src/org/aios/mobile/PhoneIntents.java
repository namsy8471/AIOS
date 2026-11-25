package org.aios.mobile;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.net.Uri;
import android.provider.AlarmClock;
import android.provider.MediaStore;
import android.provider.Settings;
import java.util.function.Consumer;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

final class PhoneIntents {
    private static final Pattern OPEN = Pattern.compile(
        "^(화면\\s*설정|디스플레이\\s*설정|와이파이\\s*설정|Wi-Fi\\s*설정|블루투스\\s*설정|카메라)"
        + "(?:를|을)?\\s*(?:열어|켜|실행)(?:\\s*(?:해\\s*)?(?:줘|주세요))?[.!?]*$", Pattern.CASE_INSENSITIVE);
    private static final Pattern TIMER = Pattern.compile(
        "^(?:(\\d{1,4})\\s*분\\s*)?(?:(\\d{1,5})\\s*초\\s*)?타이머(?:를)?\\s*"
        + "(?:(?:맞춰|시작|설정|켜)(?:\\s*(?:해\\s*)?(?:줘|주세요))?)?[.!?]*$");
    private static final Pattern PLAY_COMMAND = Pattern.compile(
        "^(?:구글\\s*)?플레이\\s*스토어(?:\\s*(?:에서|에(?:\\s*들어가서)?))?\\s+(.+?)"
        + "\\s+(?:설치|다운로드(?:\\s*받아)?|찾아|검색)(?:\\s*해)?(?:\\s*(?:줘|주세요))?[.!?]*$");
    private static final Pattern INSTALL = Pattern.compile(
        "^(.+?)\\s+(?:설치|다운로드(?:\\s*받아)?|깔아)(?:\\s*해)?(?:\\s*(?:줘|주세요))?[.!?]*$");

    private PhoneIntents() {}

    static String openAction(String command) {
        Matcher match = OPEN.matcher(command);
        if (!match.matches()) return null;
        String name = match.group(1);
        if (name.startsWith("화면") || name.startsWith("디스플레이")) return Settings.ACTION_DISPLAY_SETTINGS;
        if (name.startsWith("와이파이") || name.regionMatches(true, 0, "Wi-Fi", 0, 5)) return Settings.ACTION_WIFI_SETTINGS;
        if (name.startsWith("블루투스")) return Settings.ACTION_BLUETOOTH_SETTINGS;
        return MediaStore.INTENT_ACTION_STILL_IMAGE_CAMERA;
    }

    static Integer timerSeconds(String command) {
        Matcher match = TIMER.matcher(command);
        if (!match.matches()) return null;
        int minutes = match.group(1) == null ? 0 : Integer.parseInt(match.group(1));
        int seconds = match.group(2) == null ? 0 : Integer.parseInt(match.group(2));
        return minutes * 60 + seconds;
    }

    static Intent timerIntent(int seconds) {
        return new Intent(AlarmClock.ACTION_SET_TIMER)
            .putExtra(AlarmClock.EXTRA_LENGTH, seconds)
            .putExtra(AlarmClock.EXTRA_MESSAGE, "TLA")
            .putExtra(AlarmClock.EXTRA_SKIP_UI, true);
    }

    static String playQuery(String command) {
        Matcher match = PLAY_COMMAND.matcher(command);
        if (match.matches()) return match.group(1).strip();
        match = INSTALL.matcher(command);
        if (!match.matches()) return null;
        String title = match.group(1).strip().replaceFirst("[을를]$", "");
        return isMasterDuel(title) ? title : null;
    }

    static Intent playIntent(String query) {
        String text = AgentAction.field(query, 128);
        Uri.Builder market = new Uri.Builder().scheme("market");
        if (isMasterDuel(text)) market.authority("details").appendQueryParameter("id", "jp.konami.masterduel");
        else market.authority("search").appendQueryParameter("q", text);
        return new Intent(Intent.ACTION_VIEW, market.build()).setPackage("com.android.vending");
    }

    private static boolean isMasterDuel(String title) {
        String alias = title.replaceAll("\\s+", "");
        return alias.equals("마스터듀얼") || alias.equals("유희왕마스터듀얼") || alias.equalsIgnoreCase("MasterDuel");
    }

    static boolean handle(Activity activity, String command, Consumer<String> reply) {
        String app = playQuery(command);
        if (app != null) {
            offerInstall(activity, app, reply);
            return true;
        }
        String action = openAction(command);
        if (action != null) {
            launch(activity, new Intent(action), "요청한 화면을 열었어요.", reply);
            return true;
        }
        Integer seconds = timerSeconds(command);
        if (seconds == null) return false;
        if (seconds < 1 || seconds > 86_400) {
            reply.accept("타이머는 1초부터 24시간까지 지정해 주세요.");
            return true;
        }
        int minutes = seconds / 60;
        String duration = minutes == 0 ? seconds + "초"
            : seconds % 60 == 0 ? minutes + "분" : minutes + "분 " + seconds % 60 + "초";
        new AlertDialog.Builder(activity).setTitle("타이머 시작")
            .setMessage(duration + " 타이머를 시계 앱에 요청할까요?")
            .setNegativeButton("취소", (dialog, which) -> reply.accept("타이머 요청을 취소했어요."))
            .setPositiveButton("시작", (dialog, which) ->
                launch(activity, timerIntent(seconds), "시계 앱에 " + duration + " 타이머를 요청했어요.", reply))
            .show();
        return true;
    }

    static void offerInstall(Activity activity, String app, Consumer<String> reply) {
        try {
            Intent store = playIntent(app);
            boolean listing = "details".equals(store.getData().getAuthority());
            new AlertDialog.Builder(activity).setTitle("Play 스토어 열기")
                .setMessage("Play 스토어에서 ‘" + app + "’의 " + (listing ? "공식 앱 페이지" : "검색 결과") + "를 열까요?")
                .setNegativeButton("취소", (dialog, which) -> reply.accept("Play 스토어 요청을 취소했어요."))
                .setPositiveButton("열기", (dialog, which) ->
                    launch(activity, store, "Play 스토어에 " + app + " 페이지를 열도록 요청했어요.", reply))
                .show();
        } catch (IllegalArgumentException error) {
            reply.accept(error.getMessage());
        }
    }

    private static void launch(Activity activity, Intent intent, String message, Consumer<String> reply) {
        try {
            activity.startActivity(intent);
            reply.accept(message);
        } catch (ActivityNotFoundException | SecurityException error) {
            reply.accept("이 요청을 처리할 앱을 열지 못했어요.");
        }
    }
}
