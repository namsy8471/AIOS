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
import android.os.Bundle;
import android.os.SystemClock;
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

        UiAutomation automation = probe.getUiAutomation(UiAutomation.FLAG_DONT_SUPPRESS_ACCESSIBILITY_SERVICES);
        checkSearchApproval(probe, app, automation, query);
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
