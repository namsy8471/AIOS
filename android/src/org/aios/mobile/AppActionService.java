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
import android.graphics.PixelFormat;
import android.view.Gravity;
import android.view.View;
import android.view.WindowManager;
import android.view.accessibility.AccessibilityEvent;
import android.view.accessibility.AccessibilityNodeInfo;
import android.view.accessibility.AccessibilityWindowInfo;
import android.widget.Button;
import android.widget.LinearLayout;
import java.util.List;

public final class AppActionService extends AccessibilityService {
    static final int MAX_STEPS = 8;
    private static final long TIMEOUT_MS = 15_000;
    private static final long APPROVAL_MS = 45_000;
    private static volatile AppActionService connected;
    private static volatile String status = "";
    private final Handler main = new Handler(Looper.getMainLooper());
    private final Runnable poll = this::checkScreen;
    private AgentAction pending;
    private List<AgentAction> sequence = List.of();
    private int stepIndex;
    private long ends;
    private long gestureReadyAt;
    private boolean foundApp;
    private boolean gesturing;
    private long generation;
    private Button stopOverlay;
    private Button continueOverlay;
    private LinearLayout overlay;
    private int approvalWindow = -1;

    static boolean available() { return connected != null; }
    static String status() { return status; }

    static boolean begin(AgentAction action) {
        return begin(List.of(action));
    }

    static boolean begin(List<AgentAction> actions) {
        return connected != null && connected.arm(actions);
    }

    static void stop(String reason) {
        if (connected != null && !connected.sequence.isEmpty()) connected.finishAction(reason);
    }

    @Override protected void onServiceConnected() {
        connected = this;
        setPackageFilter(getPackageName());
    }

    @Override public void onAccessibilityEvent(AccessibilityEvent event) {}

    @Override public void onInterrupt() {
        if (!sequence.isEmpty()) finishAction("접근성 작업이 중단됐습니다.");
    }

    @Override public boolean onUnbind(Intent intent) {
        if (connected == this) {
            if (!sequence.isEmpty() || gesturing) status = "접근성 서비스 연결이 끝났습니다.";
            connected = null;
        }
        main.removeCallbacksAndMessages(null);
        pending = null;
        sequence = List.of();
        gesturing = false;
        generation++;
        removeOverlay();
        return super.onUnbind(intent);
    }

    private boolean arm(List<AgentAction> actions) {
        if (!sequence.isEmpty() || gesturing || !screenReady() || actions.isEmpty() || actions.size() > MAX_STEPS) return false;
        String target = actions.get(0).packageName;
        if (actions.stream().anyMatch(action -> !target.equals(action.packageName))) return false;
        sequence = List.copyOf(actions);
        generation++;
        stepIndex = 0;
        foundApp = false;
        setPackageFilter(target);
        showOverlay();
        queueStep(200);
        return true;
    }

    private void queueStep(long delay) {
        pending = sequence.get(stepIndex);
        approvalWindow = -1;
        if (continueOverlay != null) continueOverlay.setVisibility(View.GONE);
        gestureReadyAt = 0;
        ends = SystemClock.uptimeMillis() + TIMEOUT_MS;
        status = (stepIndex + 1) + "/" + sequence.size() + " 단계의 화면과 요소를 확인 중입니다.";
        if (stopOverlay != null) stopOverlay.setText("TLA  " + (stepIndex + 1) + "/" + sequence.size() + "  중지");
        main.postDelayed(poll, delay);
    }

    private void completedStep(String singleResult) {
        if (sequence.isEmpty()) return;
        if (++stepIndex == sequence.size()) {
            finishAction(sequence.size() == 1 ? singleResult
                : sequence.size() + "단계를 마쳤습니다. 앱에서 결과를 확인해 주세요.");
        } else {
            queueStep(400);
        }
    }

    private void showOverlay() {
        LinearLayout panel = new LinearLayout(this);
        Button button = new Button(this);
        button.setAllCaps(false);
        button.setMinHeight(Math.round(48 * getResources().getDisplayMetrics().density));
        button.setOnClickListener(view -> finishAction("사용자가 중지했습니다. 이미 전달한 동작은 앱에서 확인해 주세요."));
        Button resume = new Button(this);
        resume.setText("확인하고 계속");
        resume.setVisibility(View.GONE);
        resume.setOnClickListener(view -> approveStep());
        panel.addView(button);
        panel.addView(resume);
        WindowManager.LayoutParams params = new WindowManager.LayoutParams(
            WindowManager.LayoutParams.WRAP_CONTENT, WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE | WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL,
            PixelFormat.TRANSLUCENT);
        params.gravity = Gravity.TOP | Gravity.END;
        try {
            getSystemService(WindowManager.class).addView(panel, params);
            overlay = panel;
            stopOverlay = button;
            continueOverlay = resume;
        } catch (WindowManager.BadTokenException | SecurityException error) {
            // Returning to TLA also stops the current sequence.
        }
    }

    private void removeOverlay() {
        if (overlay == null) return;
        LinearLayout old = overlay;
        overlay = null;
        stopOverlay = null;
        continueOverlay = null;
        try {
            getSystemService(WindowManager.class).removeView(old);
        } catch (IllegalArgumentException ignored) {
            // Android may have removed the service window during disconnect.
        }
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
        approvalWindow = -1;
        sequence = List.of();
        status = message;
        main.removeCallbacks(poll);
        removeOverlay();
        setPackageFilter(getPackageName());
    }

    private void approveStep() {
        AgentAction action = pending;
        if (action == null || approvalWindow == -1) return;
        try {
            AccessibilityNodeInfo root = approvalRoot();
            if (SystemClock.uptimeMillis() >= ends || !screenReady() || !action.owns(root)
                    || root.getWindowId() != approvalWindow || action.match(root) == null) {
                finishAction("승인 화면이 바뀌었습니다. 작업을 다시 시작해 주세요.");
                return;
            }
            main.removeCallbacks(poll);
            completedStep("화면을 확인하고 승인했습니다.");
        } catch (RuntimeException error) {
            finishAction("승인할 화면을 다시 확인할 수 없었습니다.");
        }
    }

    private AccessibilityNodeInfo approvalRoot() {
        var displays = getWindowsOnAllDisplays();
        for (int index = 0; index < displays.size(); index++) {
            for (AccessibilityWindowInfo window : displays.valueAt(index)) {
                if (window.getId() == approvalWindow && window.isFocused()) return window.getRoot();
            }
        }
        return null;
    }

    private void checkScreen() {
        AgentAction action = pending;
        if (action == null) return;
        if (approvalWindow != -1 && SystemClock.uptimeMillis() >= ends) {
            finishAction("제한 시간 안에 화면 확인을 승인하지 않았습니다.");
            return;
        }
        if (!screenReady() || SystemClock.uptimeMillis() >= ends) {
            finishAction("화면이 잠겼거나 제한 시간 안에 지정한 요소를 찾지 못했습니다.");
            return;
        }
        AccessibilityNodeInfo root = approvalWindow == -1 ? getRootInActiveWindow(0) : approvalRoot();
        if (approvalWindow != -1 && !action.owns(root)) {
            finishAction("승인 화면이 바뀌었습니다. 작업을 다시 시작해 주세요.");
            return;
        }
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
                    || (approvalWindow == -1 && !window.isActive()) || !window.isFocused()) {
                gestureReadyAt = 0;
                main.postDelayed(poll, 220);
                return;
            }
            if (action.kind.swipe() && gestureReadyAt == 0) {
                gestureReadyAt = SystemClock.uptimeMillis() + 550;
                main.postAtTime(poll, gestureReadyAt);
                return;
            }
            AccessibilityNodeInfo match = action.match(root);
            if (approvalWindow != -1) {
                if (window.getId() != approvalWindow || match == null) {
                    finishAction("승인 화면이 바뀌었습니다. 작업을 다시 시작해 주세요.");
                } else {
                    main.postDelayed(poll, 220);
                }
                return;
            }
            if (match == null) {
                main.postDelayed(poll, 220);
                return;
            }
            AccessibilityNodeInfo active = getRootInActiveWindow(0);
            if (SystemClock.uptimeMillis() >= ends || !screenReady() || !action.owns(active)
                    || active.getWindowId() != window.getId() || !match.refresh() || !action.matchesLabel(match)
                    || !action.owns(match) || !match.isVisibleToUser()
                    || ((action.kind == AgentAction.Kind.CLICK || action.kind.swipe()) && !match.isEnabled())
                    || match.getWindowId() != window.getId()) {
                throw new IllegalStateException("동작 직전에 화면이 바뀌었습니다.");
            }
            if (action.kind == AgentAction.Kind.WAIT) {
                completedStep("지정한 화면 문구를 확인했습니다.");
            } else if (action.kind == AgentAction.Kind.APPROVE) {
                if (continueOverlay == null) {
                    finishAction("화면 위에 승인 버튼을 표시할 수 없어 중단했습니다.");
                    return;
                }
                approvalWindow = window.getId();
                ends = SystemClock.uptimeMillis() + APPROVAL_MS;
                status = "사용자가 화면을 확인하고 승인하기를 기다리고 있습니다.";
                continueOverlay.setVisibility(View.VISIBLE);
                main.postDelayed(poll, 220);
            } else if (action.kind == AgentAction.Kind.CLICK) {
                AccessibilityNodeInfo target = action.clickTarget(match);
                pending = null;
                if (target.performAction(AccessibilityNodeInfo.ACTION_CLICK)) {
                    completedStep("누르기 동작을 전달했습니다. 앱에서 결과를 확인해 주세요.");
                } else {
                    finishAction("앱에서 누르기 동작을 받아들이지 않았습니다.");
                }
            } else {
                Rect bounds = new Rect();
                window.getBoundsInScreen(bounds);
                GestureDescription swipe = action.swipe(match, bounds, window.getDisplayId(), getResources().getDisplayMetrics().density);
                pending = null;
                status = "스와이프 동작을 보내는 중입니다.";
                long dispatched = generation;
                gesturing = dispatchGesture(swipe, new GestureResultCallback() {
                    @Override public void onCompleted(GestureDescription gesture) {
                        if (dispatched != generation) return;
                        gesturing = false;
                        completedStep("스와이프 한 번을 보냈습니다. 앱에서 결과를 확인해 주세요.");
                    }
                    @Override public void onCancelled(GestureDescription gesture) {
                        if (dispatched != generation) return;
                        gesturing = false;
                        if (!sequence.isEmpty()) finishAction("스와이프가 취소됐습니다.");
                    }
                }, main);
                if (!gesturing) finishAction("스와이프를 시작할 수 없습니다.");
            }
        } catch (RuntimeException error) {
            finishAction(error instanceof IllegalStateException ? error.getMessage() : "동작 도중 화면에 접근할 수 없었습니다.");
        }
    }
}
