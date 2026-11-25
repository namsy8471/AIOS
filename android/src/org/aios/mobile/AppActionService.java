package org.aios.mobile;

import android.accessibilityservice.AccessibilityService;
import android.accessibilityservice.AccessibilityServiceInfo;
import android.accessibilityservice.GestureDescription;
import android.app.KeyguardManager;
import android.content.Intent;
import android.graphics.Bitmap;
import android.graphics.Path;
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
import android.widget.Toast;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.function.Consumer;

public final class AppActionService extends AccessibilityService {
    static final int MAX_STEPS = 8;
    private static final long TIMEOUT_MS = 15_000;
    private static final long APPROVAL_MS = 45_000;
    private static volatile AppActionService connected;
    private static volatile String status = "";
    private final Handler main = new Handler(Looper.getMainLooper());
    private final Runnable poll = this::checkScreen;
    private final ExecutorService plannerWorker = Executors.newSingleThreadExecutor();
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
    private ScreenTask screenTask;

    private static final class ScreenTask {
        final String packageName;
        final String goal;
        final boolean larger;
        final Consumer<String> reply;
        final boolean visual;
        List<String> labels = List.of();
        int windowId = -1;
        Future<?> inference;
        AgentAction proposed;
        int[] titleFrame;
        boolean visualStarted;
        boolean titleTapped;

        ScreenTask(String packageName, String goal, boolean larger, Consumer<String> reply) {
            this.packageName = packageName;
            this.goal = goal;
            this.larger = larger;
            this.reply = reply;
            visual = ScreenVision.supports(packageName, goal);
        }
    }

    static boolean available() { return connected != null; }
    static String status() { return status; }

    static boolean begin(AgentAction action) {
        return begin(List.of(action));
    }

    static boolean begin(List<AgentAction> actions) {
        return connected != null && connected.arm(actions);
    }

    static boolean inspect(String packageName, String goal, boolean larger, Consumer<String> reply) {
        return connected != null && connected.startInspection(new ScreenTask(packageName, goal, larger, reply));
    }

    static void stop(String reason) {
        if (connected != null && (!connected.sequence.isEmpty() || connected.screenTask != null)) connected.finishAction(reason);
    }

    @Override protected void onServiceConnected() {
        connected = this;
        setPackageFilter(getPackageName());
    }

    @Override public void onAccessibilityEvent(AccessibilityEvent event) {}

    @Override public void onInterrupt() {
        if (!sequence.isEmpty() || screenTask != null) finishAction("접근성 작업이 중단됐습니다.");
    }

    @Override public boolean onUnbind(Intent intent) {
        if (connected == this) {
            if (screenTask != null) finishAction("접근성 서비스 연결이 끝났습니다.");
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

    @Override public void onDestroy() {
        plannerWorker.shutdownNow();
        super.onDestroy();
    }

    private boolean arm(List<AgentAction> actions) {
        if (screenTask != null || !sequence.isEmpty() || gesturing || !screenReady()
                || actions.isEmpty() || actions.size() > MAX_STEPS) return false;
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
        resume.setMaxWidth(getResources().getDisplayMetrics().widthPixels / 2);
        resume.setVisibility(View.GONE);
        resume.setOnClickListener(view -> {
            if (screenTask == null) approveStep();
            else applyScreenProposal();
        });
        panel.addView(button);
        panel.addView(resume);
        WindowManager.LayoutParams params = new WindowManager.LayoutParams(
            WindowManager.LayoutParams.WRAP_CONTENT, WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE | WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL
                | WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON,
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
        ScreenTask finished = screenTask;
        screenTask = null;
        pending = null;
        approvalWindow = -1;
        sequence = List.of();
        status = message;
        main.removeCallbacks(poll);
        removeOverlay();
        setPackageFilter(getPackageName());
        if (finished != null) {
            if (finished.inference != null) finished.inference.cancel(true);
            finished.reply.accept(message);
            Toast.makeText(this, message, Toast.LENGTH_SHORT).show();
        }
    }

    private boolean startInspection(ScreenTask task) {
        if (screenTask != null || !sequence.isEmpty() || gesturing || !screenReady()) return false;
        showOverlay();
        if (stopOverlay == null) return false;
        screenTask = task;
        stopOverlay.setText("TLA 화면 확인 중 · 중지");
        ends = SystemClock.uptimeMillis() + TIMEOUT_MS;
        setPackageFilter(task.packageName);
        main.postDelayed(poll, 650);
        return true;
    }

    private void checkInspection(ScreenTask task) {
        if (!screenReady() || SystemClock.uptimeMillis() >= ends) {
            finishAction("화면이 잠겼거나 화면 작업 시간이 끝났어요.");
            return;
        }
        AccessibilityNodeInfo root = approvalWindow == -1 ? getRootInActiveWindow(0) : approvalRoot();
        if (root != null && task.packageName.equals(String.valueOf(root.getPackageName()))) {
            AccessibilityWindowInfo window = root.getWindow();
            if (window != null && window.getType() == AccessibilityWindowInfo.TYPE_APPLICATION && window.isFocused()) {
                if (task.windowId != -1 && root.getWindowId() != task.windowId) {
                    finishAction("화면이 바뀌어 제안한 동작을 취소했어요.");
                    return;
                }
                if (task.visual && !task.visualStarted && window.isActive()) {
                    if (SystemClock.uptimeMillis() >= ends - TIMEOUT_MS + 3000) startVisualInspection(task, window);
                } else if (!task.visual && task.inference == null && window.isActive()) {
                    List<String> labels = AgentAction.buttonLabels(root, task.packageName);
                    if (!labels.isEmpty()) chooseScreenProposal(task, window.getId(), labels);
                    else if (SystemClock.uptimeMillis() >= ends - TIMEOUT_MS + 3500) {
                        finishAction("이 화면에서 누를 수 있는 버튼 이름을 읽지 못했어요.");
                        return;
                    }
                }
                main.postDelayed(poll, 250);
                return;
            }
        }
        if (task.windowId == -1 && (root == null || getPackageName().equals(String.valueOf(root.getPackageName()))
                || task.packageName.equals(String.valueOf(root.getPackageName())))) {
            main.postDelayed(poll, 250);
        } else {
            finishAction("다른 화면이 열려 작업을 중단했어요.");
        }
    }

    private void startVisualInspection(ScreenTask task, AccessibilityWindowInfo window) {
        task.visualStarted = true;
        task.windowId = window.getId();
        approvalWindow = task.windowId;
        ends = SystemClock.uptimeMillis() + 55_000;
        stopOverlay.setText("TLA 화면 읽는 중 · 중지");
        capture(task, frame -> {
            task.inference = plannerWorker.submit(() -> {
                try {
                    int[] appearance = ScreenVision.appearance(frame);
                    ScreenVision.Scene scene = new ScreenVision(this).classify(frame);
                    main.post(() -> showVisualResult(task, scene, appearance));
                } catch (Exception unavailable) {
                    main.post(() -> {
                        if (screenTask == task) finishAction("로컬 비전 모델이 화면을 읽지 못했어요.");
                    });
                } finally {
                    frame.recycle();
                }
            });
        });
    }

    private void capture(ScreenTask task, Consumer<Bitmap> receive) {
        if (android.os.Build.VERSION.SDK_INT < 34) {
            finishAction("이 Android 버전은 앱 창 캡처를 지원하지 않아요.");
            return;
        }
        takeScreenshotOfWindow(task.windowId, getMainExecutor(), new TakeScreenshotCallback() {
            @Override public void onSuccess(ScreenshotResult screenshot) {
                if (visualWindow(task) == null) {
                    screenshot.getHardwareBuffer().close();
                    if (screenTask == task) finishAction("앱 화면이 바뀌어 판독을 중단했어요.");
                    return;
                }
                try {
                    receive.accept(ScreenVision.copyFrame(screenshot));
                } catch (Exception invalid) {
                    finishAction("앱 창의 화면을 읽지 못했어요.");
                }
            }

            @Override public void onFailure(int error) {
                if (screenTask == task) finishAction(error == ERROR_TAKE_SCREENSHOT_SECURE_WINDOW
                    ? "Android가 이 화면의 캡처를 보호하고 있어요." : "앱 창을 캡처하지 못했어요.");
            }
        });
    }

    private AccessibilityWindowInfo visualWindow(ScreenTask task) {
        if (screenTask != task || !screenReady() || SystemClock.uptimeMillis() >= ends) return null;
        AccessibilityNodeInfo root = approvalRoot();
        if (root == null || root.getWindowId() != task.windowId
                || !task.packageName.equals(String.valueOf(root.getPackageName()))) return null;
        AccessibilityWindowInfo window = root.getWindow();
        return window != null && window.isFocused() && window.getType() == AccessibilityWindowInfo.TYPE_APPLICATION
            ? window : null;
    }

    private void showVisualResult(ScreenTask task, ScreenVision.Scene scene, int[] appearance) {
        if (screenTask != task) return;
        if (visualWindow(task) == null) {
            finishAction("앱 화면이 바뀌어 판독을 중단했어요.");
        } else if (scene == ScreenVision.Scene.TERMS) {
            finishAction("이용약관 확인 화면이에요. 화면에서 직접 확인해 주세요.");
        } else if (scene == ScreenVision.Scene.TITLE && !task.titleTapped) {
            task.titleFrame = appearance;
            ends = SystemClock.uptimeMillis() + APPROVAL_MS;
            stopOverlay.setText("TLA 중지");
            continueOverlay.setText("타이틀 화면 누르기");
            continueOverlay.setVisibility(View.VISIBLE);
        } else {
            finishAction(task.titleTapped ? "타이틀을 한 번 눌렀어요. 다음 화면에서 출석 완료를 확인하지 못했어요."
                : "화면에서 출석으로 이어지는 동작을 확인하지 못했어요.");
        }
    }

    private void applyVisualProposal(ScreenTask task) {
        if (task.titleFrame == null || task.titleTapped) return;
        int[] approvedFrame = task.titleFrame;
        task.titleFrame = null;
        continueOverlay.setVisibility(View.GONE);
        stopOverlay.setText("TLA 화면 다시 확인 중 · 중지");
        capture(task, frame -> {
            try {
                AccessibilityWindowInfo window = visualWindow(task);
                if (window == null || !ScreenVision.sameAppearance(approvedFrame, ScreenVision.appearance(frame))) {
                    finishAction("승인 전 화면이 바뀌어 타이틀을 누르지 않았어요.");
                    return;
                }
                Rect bounds = new Rect();
                window.getBoundsInScreen(bounds);
                if (bounds.width() <= bounds.height() || bounds.width() != frame.getWidth() || bounds.height() != frame.getHeight()) {
                    finishAction("게임 화면의 위치를 확인하지 못했어요.");
                    return;
                }
                sendTitleTap(task, window, bounds);
            } finally {
                frame.recycle();
            }
        });
    }

    private void sendTitleTap(ScreenTask task, AccessibilityWindowInfo window, Rect bounds) {
        task.titleTapped = true;
        Path path = new Path();
        path.moveTo(bounds.exactCenterX(), bounds.top + bounds.height() * 0.73f);
        GestureDescription tap = new GestureDescription.Builder().setDisplayId(window.getDisplayId())
            .addStroke(new GestureDescription.StrokeDescription(path, 0, 80)).build();
        gesturing = dispatchGesture(tap, new GestureResultCallback() {
            @Override public void onCompleted(GestureDescription gesture) {
                gesturing = false;
                if (screenTask != task) return;
                task.visualStarted = false;
                task.windowId = -1;
                approvalWindow = -1;
                ends = SystemClock.uptimeMillis() + TIMEOUT_MS;
            }

            @Override public void onCancelled(GestureDescription gesture) {
                gesturing = false;
                if (screenTask == task) finishAction("타이틀 누르기가 취소됐어요.");
            }
        }, main);
        if (!gesturing) finishAction("타이틀에 누르기 동작을 보낼 수 없었어요.");
    }

    private void chooseScreenProposal(ScreenTask task, int windowId, List<String> labels) {
        task.windowId = windowId;
        task.labels = labels;
        approvalWindow = windowId;
        stopOverlay.setText("TLA 동작 찾는 중 · 중지");
        ends = SystemClock.uptimeMillis() + 65_000;
        task.inference = plannerWorker.submit(() -> {
            try {
                int number = new MobileEngine(this).chooseScreenButton(task.goal, labels, task.larger);
                main.post(() -> showScreenProposal(task, number));
            } catch (Exception error) {
                main.post(() -> {
                    if (screenTask == task) finishAction("로컬 모델이 화면에서 다음 동작을 정하지 못했어요.");
                });
            }
        });
    }

    private void showScreenProposal(ScreenTask task, int number) {
        if (screenTask != task) return;
        if (number == 0) {
            finishAction("이 화면에서 요청에 맞는 버튼을 찾지 못했어요.");
            return;
        }
        task.proposed = new AgentAction(task.packageName, task.labels.get(number - 1), AgentAction.Kind.CLICK);
        if (screenProposalTarget(task) == null) {
            finishAction("버튼이 사라졌거나 같은 이름의 버튼이 여러 개 있어요.");
            return;
        }
        ends = SystemClock.uptimeMillis() + APPROVAL_MS;
        stopOverlay.setText("TLA 중지");
        continueOverlay.setText("‘" + task.proposed.label + "’ 누르기");
        continueOverlay.setAllCaps(false);
        continueOverlay.setVisibility(View.VISIBLE);
    }

    private AccessibilityNodeInfo screenProposalTarget(ScreenTask task) {
        if (!screenReady() || SystemClock.uptimeMillis() >= ends) return null;
        try {
            AccessibilityNodeInfo root = approvalRoot();
            if (!task.proposed.owns(root) || root.getWindowId() != task.windowId) return null;
            if (!AgentAction.buttonLabels(root, task.packageName).equals(task.labels)) return null;
            AccessibilityNodeInfo match = task.proposed.match(root);
            if (match == null || !match.refresh() || !task.proposed.owns(match) || !match.isVisibleToUser()
                    || !task.proposed.matchesLabel(match) || match.getWindowId() != task.windowId) return null;
            return task.proposed.clickTarget(match);
        } catch (RuntimeException error) {
            return null;
        }
    }

    private void applyScreenProposal() {
        ScreenTask task = screenTask;
        if (task.visual) {
            applyVisualProposal(task);
            return;
        }
        if (task.proposed == null) return;
        AccessibilityNodeInfo target = screenProposalTarget(task);
        if (target == null) {
            finishAction("승인 전 화면이 바뀌어 버튼을 누르지 않았어요.");
        } else {
            boolean pressed;
            try { pressed = target.performAction(AccessibilityNodeInfo.ACTION_CLICK); }
            catch (RuntimeException unavailable) { pressed = false; }
            finishAction(pressed ? "‘" + task.proposed.label + "’ 누르기를 전달했어요."
                : "앱에서 누르기 동작을 받지 않았어요.");
        }
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
        if (screenTask != null) {
            try { checkInspection(screenTask); }
            catch (RuntimeException unavailable) { finishAction("앱 화면을 확인할 수 없었어요."); }
            return;
        }
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
