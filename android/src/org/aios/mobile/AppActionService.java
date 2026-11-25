package org.aios.mobile;

import android.accessibilityservice.AccessibilityService;
import android.accessibilityservice.AccessibilityServiceInfo;
import android.accessibilityservice.GestureDescription;
import android.app.KeyguardManager;
import android.content.Intent;
import android.graphics.Rect;
import android.os.Handler;
import android.os.Looper;
import android.os.PowerManager;
import android.os.SystemClock;
import android.view.accessibility.AccessibilityEvent;
import android.view.accessibility.AccessibilityNodeInfo;
import android.view.accessibility.AccessibilityWindowInfo;

public final class AppActionService extends AccessibilityService {
    private static final long TIMEOUT_MS = 15_000;
    private static volatile AppActionService connected;
    private static volatile String status = "";
    private final Handler main = new Handler(Looper.getMainLooper());
    private final Runnable poll = this::checkScreen;
    private AgentAction pending;
    private long ends;
    private long gestureReadyAt;
    private boolean foundApp;
    private boolean gesturing;

    static boolean available() { return connected != null; }
    static String status() { return status; }

    static boolean begin(AgentAction action) {
        return connected != null && connected.arm(action);
    }

    static void stop(String reason) {
        if (connected != null && connected.pending != null) connected.finishAction(reason);
    }

    @Override protected void onServiceConnected() {
        connected = this;
        setPackageFilter(getPackageName());
    }

    @Override public void onAccessibilityEvent(AccessibilityEvent event) {}

    @Override public void onInterrupt() {
        if (pending != null) finishAction("접근성 작업이 중단됐습니다.");
    }

    @Override public boolean onUnbind(Intent intent) {
        if (connected == this) {
            if (pending != null || gesturing) status = "접근성 서비스 연결이 끝났습니다.";
            connected = null;
        }
        main.removeCallbacksAndMessages(null);
        pending = null;
        return super.onUnbind(intent);
    }

    private boolean arm(AgentAction action) {
        if (pending != null || gesturing || !screenReady()) return false;
        pending = action;
        foundApp = false;
        gestureReadyAt = 0;
        ends = SystemClock.uptimeMillis() + TIMEOUT_MS;
        status = "지정한 화면과 요소를 확인 중입니다.";
        setPackageFilter(action.packageName);
        main.postDelayed(poll, 200);
        return true;
    }

    private boolean screenReady() {
        return getSystemService(PowerManager.class).isInteractive()
            && !getSystemService(KeyguardManager.class).isKeyguardLocked();
    }

    private void setPackageFilter(String packageName) {
        AccessibilityServiceInfo info = getServiceInfo();
        info.packageNames = new String[] {packageName};
        setServiceInfo(info);
    }

    private void finishAction(String message) {
        pending = null;
        status = message;
        main.removeCallbacks(poll);
        setPackageFilter(getPackageName());
    }

    private void checkScreen() {
        AgentAction action = pending;
        if (action == null) return;
        if (!screenReady() || SystemClock.uptimeMillis() >= ends) {
            finishAction("화면이 잠겼거나 제한 시간 안에 지정한 요소를 찾지 못했습니다.");
            return;
        }
        AccessibilityNodeInfo root = getRootInActiveWindow(0);
        if (!action.owns(root)) {
            if (root != null && (foundApp || !getPackageName().equals(String.valueOf(root.getPackageName())))) {
                finishAction("다른 앱이 열려 작업을 중단했습니다.");
            }
            else main.postDelayed(poll, 220);
            return;
        }
        foundApp = true;
        try {
            AccessibilityWindowInfo window = root.getWindow();
            if (window == null || window.getType() != AccessibilityWindowInfo.TYPE_APPLICATION
                    || !window.isActive() || !window.isFocused()) {
                gestureReadyAt = 0;
                main.postDelayed(poll, 220);
                return;
            }
            if (action.kind != AgentAction.Kind.CLICK && gestureReadyAt == 0) {
                gestureReadyAt = SystemClock.uptimeMillis() + 550;
                main.postAtTime(poll, gestureReadyAt);
                return;
            }
            AccessibilityNodeInfo match = action.match(root);
            if (match == null) {
                main.postDelayed(poll, 220);
                return;
            }
            AccessibilityNodeInfo active = getRootInActiveWindow(0);
            if (SystemClock.uptimeMillis() >= ends || !screenReady() || !action.owns(active)
                    || active.getWindowId() != window.getId() || !match.refresh() || !action.matchesLabel(match)
                    || !action.owns(match) || !match.isVisibleToUser() || !match.isEnabled()
                    || match.getWindowId() != window.getId()) {
                throw new IllegalStateException("동작 직전에 화면이 바뀌었습니다.");
            }
            if (action.kind == AgentAction.Kind.CLICK) {
                AccessibilityNodeInfo target = action.clickTarget(match);
                pending = null;
                finishAction(target.performAction(AccessibilityNodeInfo.ACTION_CLICK)
                    ? "누르기 동작을 전달했습니다. 앱에서 결과를 확인해 주세요."
                    : "앱에서 누르기 동작을 받아들이지 않았습니다.");
            } else {
                Rect bounds = new Rect();
                window.getBoundsInScreen(bounds);
                GestureDescription swipe = action.swipe(match, bounds, window.getDisplayId(), getResources().getDisplayMetrics().density);
                pending = null;
                status = "스와이프 동작을 보내는 중입니다.";
                gesturing = dispatchGesture(swipe, new GestureResultCallback() {
                    @Override public void onCompleted(GestureDescription gesture) {
                        gesturing = false;
                        finishAction("스와이프 한 번을 보냈습니다. 앱에서 결과를 확인해 주세요.");
                    }
                    @Override public void onCancelled(GestureDescription gesture) {
                        gesturing = false;
                        finishAction("스와이프가 취소됐습니다.");
                    }
                }, main);
                if (!gesturing) finishAction("스와이프를 시작할 수 없습니다.");
            }
        } catch (RuntimeException error) {
            finishAction(error instanceof IllegalStateException ? error.getMessage() : "동작 도중 화면에 접근할 수 없었습니다.");
        }
    }
}
