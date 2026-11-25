package org.aios.mobile;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.ActivityNotFoundException;
import android.content.ContentResolver;
import android.content.Intent;
import android.media.AudioManager;
import android.net.Uri;
import android.provider.Settings;
import java.util.function.Consumer;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

final class PhoneControls {
    private static final Pattern COMMAND = Pattern.compile(
        "^(?:설정\\s*에서\\s*)?((?:화면\\s*)?밝기|(?:미디어\\s*)?(?:음량|볼륨|소리))"
        + "(?:를|을)?\\s*(?:(?:좀|조금|더)\\s*)?(?:(\\d{1,3})\\s*(?:%|퍼센트)\\s*(?:로\\s*)?"
        + "(?:설정|맞춰|바꿔)?|(올려|높여|키워|낮춰|내려|줄여|올리기|낮추기))"
        + "(?:\\s*(?:해\\s*)?(?:줘|주세요))?\\s*[.!?]*$");

    private final Activity activity;
    private final Consumer<String> reply;
    private Command waitingForPermission;

    PhoneControls(Activity activity, Consumer<String> reply) {
        this.activity = activity;
        this.reply = reply;
    }

    static Command parse(String text) {
        Matcher match = COMMAND.matcher(text);
        if (!match.matches()) return null;
        boolean brightness = match.group(1).endsWith("밝기");
        if (match.group(2) != null) return new Command(brightness, Integer.parseInt(match.group(2)), 0);
        String direction = match.group(3);
        return new Command(brightness, null,
            direction.startsWith("올") || direction.startsWith("높") || direction.startsWith("키") ? 1 : -1);
    }

    void resume() {
        Command command = waitingForPermission;
        waitingForPermission = null;
        if (command == null) return;
        if (Settings.System.canWrite(activity)) review(command);
        else reply.accept("변경 권한이 없어 화면 밝기를 그대로 두었어요.");
    }

    void review(Command command) {
        if (command.percent != null && command.percent > 100) {
            reply.accept("0%부터 100% 사이로 지정해 주세요.");
            return;
        }
        if (command.brightness && !Settings.System.canWrite(activity)) {
            new AlertDialog.Builder(activity).setTitle("화면 밝기 변경 권한")
                .setMessage("휴대폰 전체의 화면 밝기를 조절하려면 Android 설정에서 TLA의 시스템 설정 변경을 허용해 주세요.")
                .setNegativeButton("취소", null).setPositiveButton("권한 설정", (dialog, action) -> requestPermission(command))
                .show();
            return;
        }
        try {
            if (command.brightness) reviewBrightness(command);
            else reviewVolume(command);
        } catch (SecurityException | Settings.SettingNotFoundException error) {
            reply.accept("현재 휴대폰 설정을 읽지 못했어요.");
        }
    }

    private void requestPermission(Command command) {
        Intent settings = new Intent(Settings.ACTION_MANAGE_WRITE_SETTINGS,
            Uri.fromParts("package", activity.getPackageName(), null));
        try {
            waitingForPermission = command;
            activity.startActivity(settings);
        } catch (ActivityNotFoundException | SecurityException error) {
            waitingForPermission = null;
            reply.accept("Android 권한 설정을 열지 못했어요.");
        }
    }

    private void reviewBrightness(Command command) throws Settings.SettingNotFoundException {
        ContentResolver settings = activity.getContentResolver();
        String brightness = Settings.System.SCREEN_BRIGHTNESS;
        String mode = Settings.System.SCREEN_BRIGHTNESS_MODE;
        int previous = Settings.System.getInt(settings, brightness);
        int beforeMode = Settings.System.getInt(settings, mode, Settings.System.SCREEN_BRIGHTNESS_MODE_MANUAL);
        int target = command.target(previous, 1, 255, 25);
        boolean automatic = beforeMode == Settings.System.SCREEN_BRIGHTNESS_MODE_AUTOMATIC;
        if (!automatic && target == previous) {
            reply.accept("화면 밝기가 이미 요청한 수준이에요.");
            return;
        }
        int percent = Math.round(target * 100f / 255);
        String detail = automatic ? "자동 밝기를 끄고 화면 밝기를 " + percent + "%로 설정할까요?"
            : "화면 밝기를 " + percent + "%로 설정할까요?";
        confirm("화면 밝기 변경", detail, () -> {
            if (!Settings.System.canWrite(activity) || Settings.System.getInt(settings, mode, Settings.System.SCREEN_BRIGHTNESS_MODE_MANUAL) != beforeMode
                    || (!automatic && Settings.System.getInt(settings, brightness, -1) != previous)) {
                reply.accept("밝기 설정이 바뀌었어요. 지시를 다시 보내 주세요.");
                return;
            }
            if (automatic && !Settings.System.putInt(settings, mode, Settings.System.SCREEN_BRIGHTNESS_MODE_MANUAL)) {
                reply.accept("자동 밝기를 변경할 수 없었어요.");
                return;
            }
            boolean written = false;
            try {
                written = Settings.System.putInt(settings, brightness, target);
            } finally {
                if (!written && automatic) Settings.System.putInt(settings, mode, beforeMode);
            }
            int actual = Settings.System.getInt(settings, brightness, -1);
            reply.accept(written && actual == target ? "화면 밝기를 " + percent + "%로 설정했어요."
                : "Android가 요청한 밝기를 적용하지 않았어요.");
        });
    }

    private void reviewVolume(Command command) {
        AudioManager audio = activity.getSystemService(AudioManager.class);
        int stream = AudioManager.STREAM_MUSIC;
        if (audio.isVolumeFixed()) {
            reply.accept("이 기기의 미디어 음량은 고정돼 있어요.");
            return;
        }
        int previous = audio.getStreamVolume(stream);
        int max = audio.getStreamMaxVolume(stream);
        int target = command.target(previous, audio.getStreamMinVolume(stream), max, 1);
        if (target == previous) {
            reply.accept("미디어 음량이 이미 요청한 수준이에요.");
            return;
        }
        confirm("미디어 음량 변경", target + "단계로 설정할까요? (최대 " + max + "단계)", () -> {
            if (audio.getStreamVolume(stream) != previous || audio.getStreamMaxVolume(stream) != max) {
                reply.accept("미디어 음량이 바뀌었어요. 지시를 다시 보내 주세요.");
                return;
            }
            audio.setStreamVolume(stream, target, 0);
            int actual = audio.getStreamVolume(stream);
            reply.accept(actual == target ? "미디어 음량을 " + actual + "단계로 설정했어요."
                : "현재 출력에서는 미디어 음량이 " + actual + "단계로 유지됐어요.");
        });
    }

    private void confirm(String title, String detail, Runnable apply) {
        new AlertDialog.Builder(activity).setTitle(title).setMessage(detail)
            .setNegativeButton("취소", (dialog, action) -> reply.accept("설정 변경을 취소했어요."))
            .setPositiveButton("적용", (dialog, action) -> {
                try {
                    apply.run();
                } catch (SecurityException error) {
                    reply.accept("Android가 설정 변경을 허용하지 않았어요.");
                }
            }).show();
    }

    static final class Command {
        final boolean brightness;
        final Integer percent;
        final int direction;

        Command(boolean brightness, Integer percent, int direction) {
            this.brightness = brightness;
            this.percent = percent;
            this.direction = direction;
        }

        int target(int current, int min, int max, int step) {
            int value = percent == null ? current + step * direction : Math.round(max * (percent / 100f));
            return Math.max(min, Math.min(max, value));
        }
    }
}
