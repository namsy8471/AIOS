package org.aios.mobile;

import android.app.Instrumentation;
import android.content.Context;
import android.content.Intent;
import android.os.Bundle;
import android.os.SystemClock;
import android.view.MotionEvent;
import android.view.View;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.EditText;
import android.widget.TextView;

import java.io.File;
import java.nio.file.Files;
import java.util.Arrays;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.function.BooleanSupplier;
import org.json.JSONObject;

/** Uses the shipping activity and engine with a synthetic memo in isolated storage. */
public final class ProductionMemoProbe extends MainActivity {
    private static final String COMMAND = "메모에 우유 추가";

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        setShowWhenLocked(true);
        setTurnScreenOn(true);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
    }

    @Override MobileEngine createEngine() {
        return new MobileEngine(this, storage(this));
    }

    private static File storage(Context context) {
        return new File(context.getFilesDir(), "production-memo-probe");
    }

    static JSONObject run(Instrumentation probe, Context context) throws Exception {
        File directory = storage(context);
        Files.createDirectories(directory.toPath());
        File memo = new File(directory, "memo.txt");
        String fixture = "저장 동작 시험";
        Files.writeString(memo.toPath(), fixture);
        Intent intent = new Intent(context, ProductionMemoProbe.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        ProductionMemoProbe screen = (ProductionMemoProbe) probe.startActivitySync(intent);
        try {
            View root = screen.getWindow().getDecorView();
            EditText input = root.findViewWithTag("memo-instruction");
            Button preview = root.findViewWithTag("memo-preview-button");
            View cancel = root.findViewWithTag("memo-preview-cancel");
            View save = root.findViewWithTag("memo-preview-save");
            TextView result = root.findViewWithTag("memo-preview-text");
            await(probe, screen::hasWindowFocus);

            double[] samples = new double[100];
            for (int sample = -4; sample < samples.length; sample++) {
                probe.runOnMainSync(() -> {
                    input.setText(COMMAND);
                    if (cancel.isShown()) cancel.performClick();
                });
                int[] point = new int[2];
                CountDownLatch committed = new CountDownLatch(1);
                long[] frame = new long[1];
                probe.runOnMainSync(() -> {
                    preview.getLocationOnScreen(point);
                    point[0] += preview.getWidth() / 2;
                    point[1] += preview.getHeight() / 2;
                    preview.setOnTouchListener((view, event) -> {
                        if (event.getActionMasked() == MotionEvent.ACTION_UP) {
                            root.getViewTreeObserver().registerFrameCommitCallback(() -> {
                                if (result.isShown() && "우유".contentEquals(result.getText())) {
                                    frame[0] = System.nanoTime();
                                    committed.countDown();
                                }
                            });
                        }
                        return false;
                    });
                });
                long down = SystemClock.uptimeMillis();
                MemoLatencyProbe.inject(probe, down, down, MotionEvent.ACTION_DOWN, point);
                long started = System.nanoTime();
                MemoLatencyProbe.inject(probe, down, SystemClock.uptimeMillis(), MotionEvent.ACTION_UP, point);
                if (!committed.await(3, TimeUnit.SECONDS)) throw new AssertionError("Shipping preview did not commit");
                if (sample >= 0) samples[sample] = (frame[0] - started) / 1_000_000.0;
            }
            probe.runOnMainSync(() -> {
                preview.setOnTouchListener(null);
                cancel.performClick();
                check(!result.isShown(), "Cancel left a preview");
            });
            check(fixture.equals(Files.readString(memo.toPath())), "Preview or cancel saved the memo");

            probe.runOnMainSync(() -> {
                preview.performClick();
                input.setText("메모에 달걀 추가");
                check(!result.isShown(), "Editing left an old preview");
            });
            probe.runOnMainSync(() -> {
                input.setText("메모에 우유를 적어줘.");
                preview.performClick();
            });
            await(probe, result::isShown);
            probe.runOnMainSync(() -> check("우유".contentEquals(result.getText()), "Model fallback proposal changed"));
            probe.runOnMainSync(() -> {
                input.setText("메모에 우유를 적어줘.");
                preview.performClick();
                input.setText(COMMAND);
            });
            await(probe, preview::isEnabled);
            probe.runOnMainSync(() -> check(!result.isShown(), "Late model reply replaced an edited instruction"));

            probe.runOnMainSync(preview::performClick);
            Files.writeString(memo.toPath(), "다른 버전");
            probe.runOnMainSync(save::performClick);
            await(probe, preview::isEnabled);
            check("다른 버전".equals(Files.readString(memo.toPath())), "Stale approval modified the memo");

            probe.runOnMainSync(preview::performClick);
            await(probe, save::isShown);
            probe.runOnMainSync(save::performClick);
            await(probe, preview::isEnabled);
            check("다른 버전\n우유".equals(Files.readString(memo.toPath())), "Retry did not save the approved memo");

            Arrays.sort(samples);
            long within = Arrays.stream(samples).filter(value -> value <= 100).count();
            check(within >= 95, "Shipping preview exceeded the 100 ms p95 target");
            return new JSONObject().put("mode", "production-memo")
                .put("samples", samples.length).put("within_100ms", within)
                .put("p50_ms", (samples[49] + samples[50]) / 2)
                .put("p95_ms", samples[94]).put("max_ms", samples[99])
                .put("cancel_preserved", true).put("stale_preview_discarded", true)
                .put("stale_save_rejected", true).put("retry_saved", true).put("model_fallback_verified", true);
        } finally {
            probe.runOnMainSync(screen::finish);
        }
    }

    private static void await(Instrumentation probe, BooleanSupplier predicate) {
        long deadline = SystemClock.uptimeMillis() + 15_000;
        boolean[] ready = {false};
        do {
            probe.runOnMainSync(() -> ready[0] = predicate.getAsBoolean());
            if (ready[0]) return;
            SystemClock.sleep(10);
        } while (SystemClock.uptimeMillis() < deadline);
        throw new AssertionError("Expected shipping screen state not reached");
    }

    private static void check(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }
}
