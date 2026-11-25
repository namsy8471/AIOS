package org.aios.mobile;

import android.accessibilityservice.GestureDescription;
import android.app.Activity;
import android.app.Instrumentation;
import android.app.UiAutomation;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.graphics.PathMeasure;
import android.graphics.Rect;
import android.media.AudioManager;
import android.os.Bundle;
import android.os.SystemClock;
import android.provider.AlarmClock;
import android.provider.Settings;
import android.view.InputDevice;
import android.view.MotionEvent;
import android.view.View;
import android.view.accessibility.AccessibilityNodeInfo;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.function.BooleanSupplier;
import org.json.JSONObject;

public final class AgentActionProbe extends Activity {
    private static final String ATTENDANCE = "일일 출석";
    private static final String CARD = "테스트 카드";
    private final AtomicInteger attendance = new AtomicInteger();
    private final AtomicInteger swipeDirection = new AtomicInteger();
    private Button duplicate;
    private float touchStart;

    @Override protected void onCreate(Bundle state) {
        super.onCreate(state);
        LinearLayout page = new LinearLayout(this);
        page.setOrientation(LinearLayout.VERTICAL);
        Button attend = new Button(this);
        attend.setText(ATTENDANCE);
        attend.setOnClickListener(view -> attendance.incrementAndGet());
        page.addView(attend);
        duplicate = new Button(this);
        duplicate.setText(ATTENDANCE);
        duplicate.setVisibility(View.GONE);
        page.addView(duplicate);
        TextView card = new TextView(this);
        card.setText(CARD);
        card.setTextSize(24);
        card.setOnTouchListener((view, event) -> {
            if (event.getActionMasked() == MotionEvent.ACTION_DOWN) touchStart = event.getX();
            if (event.getActionMasked() == MotionEvent.ACTION_UP) {
                float displacement = event.getX() - touchStart;
                if (Math.abs(displacement) > 32) swipeDirection.set(displacement < 0 ? -1 : 1);
            }
            return true;
        });
        page.addView(card, new LinearLayout.LayoutParams(-1, Math.round(144 * getResources().getDisplayMetrics().density)));
        setContentView(page);
    }

    static JSONObject run(Instrumentation probe, Context app) throws Exception {
        String query = "AIOS & 한국어 # 테스트";
        Intent search = AgentAction.search(query);
        require(Intent.ACTION_VIEW.equals(search.getAction()) && search.hasCategory(Intent.CATEGORY_BROWSABLE)
            && "https".equals(search.getData().getScheme()) && "www.google.com".equals(search.getData().getHost())
            && query.equals(search.getData().getQueryParameter("q")) && search.getData().getFragment() == null,
            "Search intent did not preserve the explicit query");
        expectInvalid(() -> AgentAction.search(" "));
        expectInvalid(() -> new AgentAction(app.getPackageName(), "출석\n확인", AgentAction.Kind.CLICK));
        for (String[] example : new String[][] {
            {"구글에 네이버 검색 해줘", "네이버"},
            {"구글에서 네이버 검색해 줘", "네이버"},
            {"Google 에 네이버 검색 해 주세요.", "네이버"},
            {"오늘 날씨 검색", "오늘 날씨"},
            {"검색 구글에 네이버", "구글에 네이버"},
            {"구글에서의 검색 기록 검색", "구글에서의 검색 기록"}
        }) {
            String parsed = AgentAction.searchQuery(example[0]);
            require(example[1].equals(parsed), "Chat search split failed for " + example[0]);
            require(example[1].equals(AgentAction.search(parsed).getData().getQueryParameter("q")),
                "Chat search sent a different query");
        }

        UiAutomation automation = probe.getUiAutomation(UiAutomation.FLAG_DONT_SUPPRESS_ACCESSIBILITY_SERVICES);
        checkSearchApproval(probe, app, automation, query);
        JSONObject controls = checkChatTools(probe, app, automation);
        AgentActionProbe fixture = (AgentActionProbe) probe.startActivitySync(
            new Intent(app, AgentActionProbe.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
        try {
            String packageName = app.getPackageName();
            AgentAction click = new AgentAction(packageName, ATTENDANCE, AgentAction.Kind.CLICK);
            AccessibilityNodeInfo firstRoot = root(automation, click);
            require(new AgentAction("org.example.other", ATTENDANCE, AgentAction.Kind.CLICK).match(firstRoot) == null,
                "Wrong app was allowed");
            require(new AgentAction(packageName, "출석", AgentAction.Kind.CLICK).match(firstRoot) == null,
                "Partial label was allowed");
            AccessibilityNodeInfo button = click.clickTarget(click.match(firstRoot));
            require(button.performAction(AccessibilityNodeInfo.ACTION_CLICK), "Fixture rejected click");
            await(() -> fixture.attendance.get() == 1, "Fixture received no click");

            probe.runOnMainSync(() -> fixture.duplicate.setVisibility(View.VISIBLE));
            probe.waitForIdleSync();
            await(() -> {
                try {
                    click.match(automation.getRootInActiveWindow());
                    return false;
                } catch (IllegalStateException expected) {
                    return true;
                }
            }, "Duplicate labels did not stop matching");
            probe.runOnMainSync(() -> fixture.duplicate.setVisibility(View.GONE));
            probe.waitForIdleSync();

            boolean service = AppActionService.available();
            for (AgentAction.Kind direction : new AgentAction.Kind[] {AgentAction.Kind.LEFT, AgentAction.Kind.RIGHT}) {
                AgentAction action = new AgentAction(packageName, CARD, direction);
                fixture.swipeDirection.set(0);
                if (service) {
                    arm(probe, action);
                } else {
                    AccessibilityNodeInfo window = root(automation, action);
                    Rect bounds = new Rect();
                    window.getBoundsInScreen(bounds);
                    GestureDescription gesture = action.swipe(action.match(window), bounds, 0,
                        fixture.getResources().getDisplayMetrics().density);
                    inject(automation, gesture.getStroke(0));
                }
                int expected = direction == AgentAction.Kind.LEFT ? -1 : 1;
                await(() -> fixture.swipeDirection.get() == expected, "Fixture received wrong swipe");
                if (service) await(() -> AppActionService.status().contains("한 번을 보냈습니다"), "Service swipe did not finish");
            }
            if (service) {
                arm(probe, click);
                await(() -> fixture.attendance.get() == 2, "Service did not click once");
                SystemClock.sleep(500);
                require(fixture.attendance.get() == 2, "Service repeated click");
                arm(probe, new AgentAction(packageName, "없는 버튼", AgentAction.Kind.CLICK));
                await(() -> AppActionService.status().contains("제한 시간"), "Missing label did not time out", 18_000);
                require(fixture.attendance.get() == 2, "Timed out action clicked a button");
            }
            return new JSONObject().put("mode", "agent-actions").put("search_query_encoding", true).put("search_approval", true)
                .put("chat_search_google_destination", true)
                .put("phone_controls", controls)
                .put("fixture_click", true).put("left_swipe", true).put("right_swipe", true)
                .put("duplicate_blocked", true).put("wrong_app_blocked", true)
                .put("real_accessibility_service", service).put("service_timeout_verified", service);
        } finally {
            probe.runOnMainSync(() -> {
                AppActionService.stop("시험 완료");
                fixture.finish();
            });
        }
    }

    private static JSONObject checkChatTools(Instrumentation probe, Context app, UiAutomation automation) throws Exception {
        require(PhoneControls.parse("설정에서 밝기 올려줘").target(100, 1, 255, 25) == 125, "Brightness increase failed");
        require(PhoneControls.parse("화면 밝기 70%로 설정해 줘").target(100, 1, 255, 25) == 179, "Brightness percentage failed");
        require(PhoneControls.parse("화면 밝기를 더 낮춰 줘!").target(10, 1, 255, 25) == 1, "Brightness minimum failed");
        require(PhoneControls.parse("음량 줄여").target(6, 0, 15, 1) == 5, "Volume decrease failed");
        int seconds = PhoneIntents.timerSeconds("2분 15초 타이머 설정해 줘");
        require(seconds == 135 && PhoneIntents.timerIntent(seconds).getIntExtra(AlarmClock.EXTRA_LENGTH, 0) == 135,
            "Timer length was not preserved");
        require(Settings.ACTION_WIFI_SETTINGS.equals(PhoneIntents.openAction("와이파이 설정 열어줘")),
            "Wi-Fi settings command did not resolve");
        String storeCommand = "구글 플레이 스토어에 들어가서 마스터 듀얼 다운로드 받아줘";
        require("마스터 듀얼".equals(PhoneIntents.playQuery(storeCommand)), "Play request did not preserve the title");
        require("마스터 듀얼".equals(PhoneIntents.playQuery("마스터 듀얼을 설치해 줘")), "Store-free command did not resolve");
        Intent listing = PhoneIntents.playIntent(PhoneIntents.playQuery(storeCommand));
        require("com.android.vending".equals(listing.getPackage())
            && "jp.konami.masterduel".equals(listing.getData().getQueryParameter("id")), "Wrong store listing");
        Activity screen = probe.startActivitySync(new Intent(app, MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
        try {
            View root = screen.getWindow().getDecorView();
            EditText field = root.findViewWithTag("memo-instruction");
            View send = root.findViewWithTag("memo-preview-button");
            sendCommand(probe, field, send, "구글에 네이버 검색 해줘");
            await(() -> {
                AccessibilityNodeInfo active = automation.getRootInActiveWindow();
                return active != null && app.getPackageName().equals(String.valueOf(active.getPackageName()))
                    && active.findAccessibilityNodeInfosByText("네이버").stream()
                        .anyMatch(node -> "Google에 보낼 검색어\n\n네이버".equals(String.valueOf(node.getText())));
            }, "Search approval did not contain only the intended query");
            clickLabel(automation, app.getPackageName(), "취소");

            IntentFilter market = new IntentFilter(Intent.ACTION_VIEW);
            market.addDataScheme("market");
            Instrumentation.ActivityMonitor store = probe.addMonitor(market, new Instrumentation.ActivityResult(0, null), true);
            try {
                sendCommand(probe, field, send, storeCommand);
                root(automation, new AgentAction(app.getPackageName(), "Play 스토어 열기", AgentAction.Kind.WAIT));
                clickLabel(automation, app.getPackageName(), "취소");
                require(store.getHits() == 0, "Cancelled Play request opened another app");
                sendCommand(probe, field, send, storeCommand);
                clickLabel(automation, app.getPackageName(), "열기");
                await(() -> store.getHits() == 1, "Approved Play request did not reach Android");
            } finally {
                probe.removeMonitor(store);
            }
            long plannerMillis = -1;
            if (app.getPackageManager().getLaunchIntentForPackage("com.android.chrome") != null
                    && new MobileEngine(app).weights(false).isFile()) {
                IntentFilter launcherFilter = new IntentFilter(Intent.ACTION_MAIN);
                launcherFilter.addCategory(Intent.CATEGORY_LAUNCHER);
                launcherFilter.addCategory(Intent.CATEGORY_INFO);
                Instrumentation.ActivityMonitor launcher = probe.addMonitor(launcherFilter,
                    new Instrumentation.ActivityResult(0, null), true);
                try {
                    sendCommand(probe, field, send, "Chrom 열어줘");
                    root(automation, new AgentAction(app.getPackageName(), "대상 앱 확인", AgentAction.Kind.WAIT));
                    clickLabel(automation, app.getPackageName(), "취소");
                    require(launcher.getHits() == 0, "Cancelled suggestion launched an app");

                    long start = SystemClock.elapsedRealtime();
                    sendCommand(probe, field, send, "Chrome 좀 띄워 줘");
                    AgentAction confirmation = new AgentAction(app.getPackageName(), "맞아요, 열기", AgentAction.Kind.CLICK);
                    await(() -> confirmation.match(automation.getRootInActiveWindow()) != null,
                        "Local model did not propose opening Chrome", 65_000);
                    plannerMillis = SystemClock.elapsedRealtime() - start;
                    require(launcher.getHits() == 0, "Model proposal launched before approval");
                    clickLabel(automation, app.getPackageName(), confirmation.label);
                    await(() -> launcher.getHits() == 1, "Approved model proposal did not request Chrome");

                    sendCommand(probe, field, send, "게임 출석 좀 챙겨줘");
                    AgentAction question = new AgentAction(app.getPackageName(),
                        "어느 앱에서 할까요? 앱 이름을 포함해서 다시 말씀해 주세요.", AgentAction.Kind.WAIT);
                    await(() -> question.match(automation.getRootInActiveWindow()) != null,
                        "Missing app did not prompt for clarification", 65_000);
                    require(launcher.getHits() == 1, "Missing app caused a launch");
                } finally {
                    probe.removeMonitor(launcher);
                }
            }

            boolean approved = Settings.System.canWrite(app);
            int brightness = Settings.System.getInt(app.getContentResolver(), Settings.System.SCREEN_BRIGHTNESS, 128);
            int beforeMode = Settings.System.getInt(app.getContentResolver(), Settings.System.SCREEN_BRIGHTNESS_MODE,
                Settings.System.SCREEN_BRIGHTNESS_MODE_MANUAL);
            int percent = brightness < 128 ? 70 : 30;
            sendCommand(probe, field, send, "설정에서 밝기 " + percent + "%로 설정해 줘");
            String title = approved ? "화면 밝기 변경" : "화면 밝기 변경 권한";
            root(automation, new AgentAction(app.getPackageName(), title, AgentAction.Kind.CLICK));
            if (approved) {
                try {
                    clickLabel(automation, app.getPackageName(), "적용");
                    await(() -> Settings.System.getInt(app.getContentResolver(), Settings.System.SCREEN_BRIGHTNESS, -1)
                        == Math.round(255 * (percent / 100f)), "Brightness did not change on approval");
                } finally {
                    boolean restored = Settings.System.putInt(app.getContentResolver(), Settings.System.SCREEN_BRIGHTNESS, brightness);
                    boolean modeRestored = Settings.System.putInt(app.getContentResolver(), Settings.System.SCREEN_BRIGHTNESS_MODE, beforeMode);
                    require(restored && modeRestored, "Brightness settings were not restored");
                }
            } else {
                clickLabel(automation, app.getPackageName(), "취소");
            }

            Instrumentation.ActivityMonitor clock = probe.addMonitor(new IntentFilter(AlarmClock.ACTION_SET_TIMER),
                new Instrumentation.ActivityResult(0, null), true);
            try {
                sendCommand(probe, field, send, "5분 타이머 맞춰줘");
                clickLabel(automation, app.getPackageName(), "취소");
                require(clock.getHits() == 0, "Cancelled timer reached the clock");
                sendCommand(probe, field, send, "5분 타이머 맞춰줘");
                clickLabel(automation, app.getPackageName(), "시작");
                await(() -> clock.getHits() == 1, "Approved timer did not reach the clock");
            } finally {
                probe.removeMonitor(clock);
            }
            JSONObject results = new JSONObject().put("brightness_review_or_permission", true)
                .put("brightness_applied_and_restored", approved).put("timer_approval", true)
                .put("play_listing_approval", true)
                .put("model_app_open_confirmation_ms", plannerMillis)
                .put("media_volume_applied_and_restored", false);

            AudioManager audio = app.getSystemService(AudioManager.class);
            int stream = AudioManager.STREAM_MUSIC;
            int previous = audio.getStreamVolume(stream);
            int max = audio.getStreamMaxVolume(stream);
            if (audio.isVolumeFixed() || audio.getStreamMinVolume(stream) == max) return results;
            int target = previous >= max ? previous - 1 : previous + 1;
            try {
                sendCommand(probe, field, send, target < previous ? "미디어 음량 낮춰줘" : "미디어 음량 올려줘");
                root(automation, new AgentAction(app.getPackageName(), "미디어 음량 변경", AgentAction.Kind.CLICK));
                clickLabel(automation, app.getPackageName(), "적용");
                await(() -> audio.getStreamVolume(stream) == target, "Media volume did not change on approval");
            } finally {
                if (audio.getStreamVolume(stream) != previous) audio.setStreamVolume(stream, previous, 0);
            }
            require(audio.getStreamVolume(stream) == previous, "Original volume was not restored");
            return results.put("media_volume_applied_and_restored", true);
        } finally {
            probe.runOnMainSync(screen::finish);
        }
    }

    private static void sendCommand(Instrumentation probe, EditText field, View send, String command) {
        probe.runOnMainSync(() -> {
            field.setText(command);
            send.performClick();
        });
    }

    private static void checkSearchApproval(Instrumentation probe, Context app, UiAutomation automation, String query)
            throws Exception {
        IntentFilter filter = new IntentFilter(Intent.ACTION_VIEW);
        filter.addDataScheme("https");
        filter.addDataAuthority("www.google.com", null);
        filter.addCategory(Intent.CATEGORY_BROWSABLE);
        Instrumentation.ActivityMonitor browser = probe.addMonitor(filter, new Instrumentation.ActivityResult(0, null), true);
        Activity screen = probe.startActivitySync(new Intent(app, AgentActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
        try {
            EditText field = screen.getWindow().getDecorView().findViewWithTag("agent-search-query");
            View review = screen.getWindow().getDecorView().findViewWithTag("agent-search-review");
            probe.runOnMainSync(() -> {
                field.setText(query);
                review.performClick();
            });
            clickLabel(automation, app.getPackageName(), "취소");
            probe.waitForIdleSync();
            require(browser.getHits() == 0, "Cancelling opened the browser");
            probe.runOnMainSync(review::performClick);
            clickLabel(automation, app.getPackageName(), "검색");
            await(() -> browser.getHits() == 1, "Approved search did not request the browser");
        } finally {
            probe.removeMonitor(browser);
            probe.runOnMainSync(screen::finish);
        }
    }


    private static void clickLabel(UiAutomation automation, String packageName, String label) {
        AgentAction action = new AgentAction(packageName, label, AgentAction.Kind.CLICK);
        AccessibilityNodeInfo target = action.clickTarget(action.match(root(automation, action)));
        require(target.performAction(AccessibilityNodeInfo.ACTION_CLICK), "Confirmation button did not click");
    }

    private static void arm(Instrumentation probe, AgentAction action) {
        probe.runOnMainSync(() -> require(AppActionService.begin(action), "Fixture service did not arm"));
    }

    private static AccessibilityNodeInfo root(UiAutomation automation, AgentAction action) {
        AccessibilityNodeInfo[] active = new AccessibilityNodeInfo[1];
        await(() -> {
            active[0] = automation.getRootInActiveWindow();
            return action.owns(active[0]) && action.match(active[0]) != null;
        }, "Test screen did not expose the expected element: " + action.label);
        return active[0];
    }

    private static void inject(UiAutomation automation, GestureDescription.StrokeDescription stroke) {
        PathMeasure path = new PathMeasure(stroke.getPath(), false);
        long down = SystemClock.uptimeMillis();
        float[] xy = new float[2];
        for (int i = 0; i <= 8; i++) {
            path.getPosTan(path.getLength() * i / 8, xy, null);
            int type = i == 0 ? MotionEvent.ACTION_DOWN : i == 8 ? MotionEvent.ACTION_UP : MotionEvent.ACTION_MOVE;
            MotionEvent event = MotionEvent.obtain(down, SystemClock.uptimeMillis(), type, xy[0], xy[1], 0);
            try {
                event.setSource(InputDevice.SOURCE_TOUCHSCREEN);
                require(automation.injectInputEvent(event, true), "Test gesture was not delivered");
            } finally {
                event.recycle();
            }
        }
    }

    private static void expectInvalid(Runnable call) {
        try {
            call.run();
            throw new AssertionError("Invalid action input was accepted");
        } catch (IllegalArgumentException expected) {
            // Invalid input must fail before any intent or gesture is sent.
        }
    }

    private static void await(BooleanSupplier condition, String failure) { await(condition, failure, 5000); }

    private static void await(BooleanSupplier condition, String failure, long timeout) {
        long deadline = SystemClock.uptimeMillis() + timeout;
        do {
            if (condition.getAsBoolean()) return;
            SystemClock.sleep(25);
        } while (SystemClock.uptimeMillis() < deadline);
        throw new AssertionError(failure);
    }

    private static void require(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }
}
