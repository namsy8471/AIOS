package org.aios.mobile;

import android.accessibilityservice.AccessibilityService.ScreenshotResult;
import android.content.Context;
import android.graphics.Bitmap;
import android.hardware.HardwareBuffer;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.TimeUnit;

final class ScreenVision {
    enum Scene { TITLE, TERMS, OTHER }
    static final String MASTER_DUEL = "jp.konami.masterduel";
    private final Context app;
    private final File runner;

    ScreenVision(Context app) {
        this.app = app;
        runner = new File(app.getApplicationInfo().nativeLibraryDir, "libllama-vision.so");
    }

    static File weights(Context app, boolean projector) {
        return new File(app.getFilesDir(), projector ? "vision-projector.gguf" : "vision-model.gguf");
    }

    boolean installed() { return runner.isFile(); }

    boolean ready() { return installed() && weights(app, false).isFile() && weights(app, true).isFile(); }

    static boolean supports(String packageName, String goal) {
        return MASTER_DUEL.equals(packageName) && (goal.contains("출석") || goal.contains("출첵"));
    }

    static Bitmap copyFrame(ScreenshotResult screenshot) throws IOException {
        try (HardwareBuffer buffer = screenshot.getHardwareBuffer()) {
            Bitmap hardware = Bitmap.wrapHardwareBuffer(buffer, screenshot.getColorSpace());
            if (hardware == null) throw new IOException("화면 이미지를 읽을 수 없어요.");
            try {
                Bitmap copy = hardware.copy(Bitmap.Config.ARGB_8888, false);
                if (copy == null) throw new IOException("화면 이미지를 읽을 수 없어요.");
                return copy;
            } finally {
                hardware.recycle();
            }
        }
    }

    static int[] appearance(Bitmap screen) {
        Bitmap small = Bitmap.createScaledBitmap(screen, 32, 16, true);
        try {
            int[] pixels = new int[512];
            small.getPixels(pixels, 0, 32, 0, 0, 32, 16);
            return pixels;
        } finally {
            if (small != screen) small.recycle();
        }
    }

    static boolean sameAppearance(int[] before, int[] current) {
        int changed = 0;
        for (int i = 0; i < before.length; i++) {
            int a = before[i];
            int b = current[i];
            int delta = Math.abs((a >> 16 & 255) - (b >> 16 & 255))
                + Math.abs((a >> 8 & 255) - (b >> 8 & 255)) + Math.abs((a & 255) - (b & 255));
            if (delta > 80 && ++changed > before.length / 20) return false;
        }
        return true;
    }

    Scene classify(Bitmap screen) throws Exception {
        String prompt = "Classify this screenshot. TITLE means a game title logo with no open dialog. "
            + "TERMS means a dialog about updated terms or agreement. OTHER means neither. Answer only TITLE, TERMS, or OTHER.";
        File image = File.createTempFile("screen-", ".jpg", app.getCacheDir());
        File output = null;
        Process process = null;
        try {
            int width = screen.getWidth();
            int height = screen.getHeight();
            Bitmap crop = Bitmap.createBitmap(screen, width * 17 / 100, height * 14 / 100,
                width * 66 / 100, height * 76 / 100);
            Bitmap input = crop;
            try (FileOutputStream data = new FileOutputStream(image)) {
                float scale = Math.min(1f, 750f / Math.max(crop.getWidth(), crop.getHeight()));
                input = Bitmap.createScaledBitmap(crop, Math.round(crop.getWidth() * scale),
                    Math.round(crop.getHeight() * scale), true);
                if (!input.compress(Bitmap.CompressFormat.JPEG, 90, data)) throw new IOException("화면을 처리할 수 없어요.");
            } finally {
                if (input != crop) input.recycle();
                if (crop != screen) crop.recycle();
            }
            output = File.createTempFile("vision-", ".txt", app.getCacheDir());
            process = new ProcessBuilder(runner.getAbsolutePath(), "-m", weights(app, false).getAbsolutePath(),
                "--mmproj", weights(app, true).getAbsolutePath(), "--image", image.getAbsolutePath(), "-p", prompt,
                "-c", "2048", "-n", "8", "-t", "4", "-ngl", "0", "--image-max-tokens", "96", "--temp", "0",
                "--no-warmup", "--log-verbosity", "1", "--grammar", "root ::= \"TITLE\" | \"TERMS\" | \"OTHER\"")
                .redirectOutput(output).redirectError(new File("/dev/null")).start();
            process.getOutputStream().close();
            if (!process.waitFor(45, TimeUnit.SECONDS) || process.exitValue() != 0) {
                throw new IOException("로컬 비전 모델 실행을 마치지 못했어요.");
            }
            try (InputStream data = new FileInputStream(output)) {
                return Scene.valueOf(new String(MobileEngine.readLimited(data, 128), StandardCharsets.UTF_8).strip());
            }
        } finally {
            if (process != null && process.isAlive()) process.destroyForcibly();
            if (output != null) output.delete();
            image.delete();
        }
    }
}
