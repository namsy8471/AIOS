package org.aios.mobile;

import android.app.Instrumentation;
import android.content.Context;
import android.content.Intent;
import android.os.SystemClock;
import android.view.InputDevice;
import android.view.MotionEvent;
import java.io.File;
import java.io.IOException;
import java.nio.file.Files;
import java.util.Arrays;
import java.util.concurrent.TimeUnit;
import org.json.JSONArray;
import org.json.JSONObject;

final class MemoLatencyProbe {
    private static final int TRIALS = 100;
    private static final int SETUPS = 5;

    static JSONObject run(Instrumentation probe, Context app) throws Exception {
        File workspace = new File(app.getFilesDir(), "latency-probe");
        if (!workspace.isDirectory() && !workspace.mkdirs()) throw new IOException("Cannot create test storage");
        File memo = new File(workspace, "memo.txt");
        String fixture = "속도 시험용 메모 1234567890\n".repeat(40);
        Files.writeString(memo.toPath(), fixture);
        String revision = MobileEngine.sha(fixture);
        Intent target = new Intent(app, MemoLatencyActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        MemoLatencyActivity activity = (MemoLatencyActivity) probe.startActivitySync(target);
        try {
            double[][] input = new double[SETUPS][TRIALS];
            double[][] appWork = new double[SETUPS][TRIALS];
            double[][] rendering = new double[SETUPS][TRIALS];
            for (int cycle = -4; cycle < TRIALS; cycle++) {
                for (int position = 0; position < SETUPS; position++) {
                    int variant = Math.floorMod(cycle + position, SETUPS);
                    MemoLatencyActivity.Sample sample = measure(probe, activity, variant);
                    if (!"우유".equals(sample.line) || !revision.equals(sample.revision)) {
                        throw new AssertionError("Incorrect preview for variant " + variant);
                    }
                    if (cycle >= 0) {
                        input[variant][cycle] = milliseconds(sample.frameNs - sample.inputNs);
                        appWork[variant][cycle] = milliseconds(sample.readyNs - sample.clickNs);
                        rendering[variant][cycle] = milliseconds(sample.frameNs - sample.readyNs);
                    }
                }
            }
            if (!fixture.equals(Files.readString(memo.toPath()))) throw new AssertionError("Preview changed the memo");
            measure(probe, activity, 4);
            probe.runOnMainSync(activity::approveInline);
            MobileEngine engine = new MobileEngine(app, workspace);
            long deadline = SystemClock.uptimeMillis() + 3000;
            while (fixture.equals(engine.memoText()) && SystemClock.uptimeMillis() < deadline) SystemClock.sleep(10);
            if (!(fixture + "우유").equals(engine.memoText())) throw new AssertionError("Approved memo was not saved");
            try {
                engine.saveMemo(revision, "달걀");
                throw new AssertionError("Stale approval saved a second change");
            } catch (IOException expected) {
                if (!(fixture + "우유").equals(engine.memoText())) throw new AssertionError("Stale approval changed the memo");
            }
            JSONObject result = new JSONObject().put("mode", "memo-latency")
                .put("input", "injected touch-up")
                .put("endpoint", "preview frame commit to the swap chain")
                .put("samples_per_setup", TRIALS).put("warmups_per_setup", 4)
                .put("verified_preview_and_approval", true);
            JSONArray rows = new JSONArray();
            JSONArray samples = new JSONArray();
            for (int variant = 0; variant < SETUPS; variant++) {
                JSONArray series = new JSONArray();
                for (double value : input[variant]) series.put(value);
                samples.put(series);
                rows.put(new JSONObject().put("variant", variant)
                    .put("tap_to_frame_ms", statistics(input[variant]))
                    .put("click_to_ready_ms", statistics(appWork[variant]))
                    .put("ready_to_frame_ms", statistics(rendering[variant])));
            }
            result.put("results", rows);
            Files.writeString(new File(workspace, "report.json").toPath(),
                new JSONObject(result.toString()).put("tap_to_frame_samples_ms", samples).toString(2) + "\n");
            return result;
        } finally {
            probe.runOnMainSync(activity::finish);
        }
    }

    private static MemoLatencyActivity.Sample measure(Instrumentation probe, MemoLatencyActivity activity, int variant)
            throws Exception {
        MemoLatencyActivity.Sample sample = new MemoLatencyActivity.Sample();
        int[] coordinates = new int[2];
        probe.runOnMainSync(() -> {
            activity.resetPreview();
            activity.variant = variant;
            activity.sample = sample;
            activity.instruction.setText(MemoLatencyActivity.COMMAND);
        });
        awaitFocus(probe, activity);
        probe.runOnMainSync(() -> {
            activity.preview.getLocationOnScreen(coordinates);
            coordinates[0] += activity.preview.getWidth() / 2;
            coordinates[1] += activity.preview.getHeight() / 2;
        });
        long down = SystemClock.uptimeMillis();
        inject(probe, down, down, MotionEvent.ACTION_DOWN, coordinates);
        long up = SystemClock.uptimeMillis();
        sample.inputNs = System.nanoTime();
        inject(probe, down, up, MotionEvent.ACTION_UP, coordinates);
        if (!sample.frame.await(3, TimeUnit.SECONDS)) {
            throw new AssertionError("No committed preview frame, variant " + variant + ", click " + sample.clickNs);
        }
        if (sample.error != null) throw new AssertionError("Preview failed: " + sample.error, sample.error);
        return sample;
    }

    private static void awaitFocus(Instrumentation probe, MemoLatencyActivity activity) {
        long deadline = SystemClock.uptimeMillis() + 3000;
        boolean[] ready = new boolean[1];
        do {
            probe.runOnMainSync(() -> ready[0] = activity.hasWindowFocus() && activity.preview.isShown()
                && activity.preview.getWidth() > 0);
            if (ready[0]) return;
            SystemClock.sleep(10);
        } while (SystemClock.uptimeMillis() < deadline);
        throw new AssertionError("Test activity did not receive focus");
    }

    private static void inject(Instrumentation probe, long down, long eventTime, int action, int[] point) {
        MotionEvent event = MotionEvent.obtain(down, eventTime, action, point[0], point[1], 0);
        try {
            event.setSource(InputDevice.SOURCE_TOUCHSCREEN);
            probe.sendPointerSync(event);
        } finally {
            event.recycle();
        }
    }

    private static double milliseconds(long nanoseconds) { return nanoseconds / 1_000_000.0; }

    private static JSONObject statistics(double[] samples) throws Exception {
        Arrays.sort(samples);
        return new JSONObject().put("median", (samples[49] + samples[50]) / 2.0)
            .put("p95", samples[94]).put("min", samples[0]).put("max", samples[99])
            .put("within_100ms", Arrays.stream(samples).filter(value -> value <= 100).count());
    }
}
