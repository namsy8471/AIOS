package org.aios.mobile;

import android.content.Context;
import android.os.SystemClock;
import android.util.AtomicFile;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileNotFoundException;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.UUID;
import java.util.concurrent.TimeUnit;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

final class MobileEngine {
    static final int MAX_SOURCE_BYTES = 8192;
    private final File storage;
    private final File weights;
    private final File nativeModelRunner;
    private final AtomicFile memo;
    private final AtomicFile draft;

    MobileEngine(Context context) {
        this(context, context.getFilesDir());
    }

    MobileEngine(Context context, File storage) {
        this.storage = storage;
        weights = new File(context.getFilesDir(), "model.gguf");
        nativeModelRunner = new File(context.getApplicationInfo().nativeLibraryDir, "libllama-runner.so");
        memo = new AtomicFile(new File(storage, "memo.txt"));
        draft = new AtomicFile(new File(storage, "draft.md"));
    }

    File weights() { return weights; }

    String memoText() throws IOException { return readText(memo); }

    String draftText() throws IOException { return readText(draft); }

    private static String readText(AtomicFile file) throws IOException {
        try {
            return new String(file.readFully(), StandardCharsets.UTF_8);
        } catch (FileNotFoundException missing) {
            if (file.getBaseFile().exists()) throw missing;
            return "";
        }
    }

    static String sha(String text) throws Exception {
        byte[] digest = MessageDigest.getInstance("SHA-256").digest(text.getBytes(StandardCharsets.UTF_8));
        StringBuilder hex = new StringBuilder(64);
        for (byte b : digest) hex.append(Character.forDigit((b >>> 4) & 15, 16)).append(Character.forDigit(b & 15, 16));
        return hex.toString();
    }

    private static void writeText(AtomicFile target, String text) throws IOException {
        FileOutputStream stream = target.startWrite();
        try {
            stream.write(text.getBytes(StandardCharsets.UTF_8));
            target.finishWrite(stream);
        } catch (IOException failure) {
            target.failWrite(stream);
            throw failure;
        }
        if (!readText(target).equals(text)) throw new IOException("저장한 내용을 확인할 수 없습니다.");
    }

    void saveMemo(String revision, String addition) throws Exception {
        String original = memoText();
        if (!sha(original).equals(revision)) throw new IOException("메모가 바뀌었습니다. 새로 제안해 주세요.");
        String newline = original.isEmpty() || original.endsWith("\n") ? "" : "\n";
        if (original.length() > 65536) throw new IOException("메모가 너무 큽니다.");
        writeText(memo, original + newline + addition);
    }

    void saveDraft(String text) throws IOException { writeText(draft, text); }

    static byte[] readLimited(InputStream input, int max) throws IOException {
        ByteArrayOutputStream content = new ByteArrayOutputStream();
        byte[] chunk = new byte[4096];
        for (int read; (read = input.read(chunk)) != -1;) {
            if (content.size() + read > max) throw new IOException("파일 또는 응답이 너무 큽니다.");
            content.write(chunk, 0, read);
        }
        return content.toByteArray();
    }

    void importWeights(InputStream input) throws IOException {
        AtomicFile model = new AtomicFile(weights());
        FileOutputStream output = model.startWrite();
        try {
            byte[] magic = new byte[4];
            int offset = 0;
            while (offset < magic.length) {
                int read = input.read(magic, offset, magic.length - offset);
                if (read < 0) throw new IOException("GGUF 모델 파일을 선택해 주세요.");
                offset += read;
            }
            if (!"GGUF".equals(new String(magic, StandardCharsets.US_ASCII))) throw new IOException("GGUF 모델 파일을 선택해 주세요.");
            output.write(magic);
            byte[] chunk = new byte[65536];
            long total = magic.length;
            for (int read; (read = input.read(chunk)) != -1;) {
                total += read;
                if (total > 1024L * 1024 * 1024) throw new IOException("모델 크기 한도는 1 GiB입니다.");
                output.write(chunk, 0, read);
            }
            model.finishWrite(output);
        } catch (IOException failure) {
            model.failWrite(output);
            throw failure;
        }
    }

    String proposeLine(String instruction) throws Exception {
        if (!weights().isFile()) throw new IOException("먼저 로컬 GGUF 모델을 가져오세요.");
        if (instruction.isBlank() || instruction.getBytes(StandardCharsets.UTF_8).length > 512
                || instruction.contains("<|") || instruction.chars().anyMatch(Character::isISOControl)) {
            throw new IOException("512바이트 이내의 한 줄 지시를 입력해 주세요.");
        }
        String system = "Extract the exact text to append from the Korean memo request. "
            + "Return one JSON object with tool append_line and line. No markdown. "
            + "Example: 메모에 사과를 적어줘 -> {\"tool\":\"append_line\",\"line\":\"사과\"}";
        String prompt = "<|im_start|>system\n" + system + "<|im_end|>\n<|im_start|>user\n"
            + instruction + "<|im_end|>\n<|im_start|>assistant\n";
        File output = File.createTempFile("model-", ".text", storage);
        Process process = null;
        try {
            process = new ProcessBuilder(nativeModelRunner.getAbsolutePath(), "-m", weights().getAbsolutePath(),
                "-ngl", "0", "-n", "64", prompt).redirectOutput(output).redirectError(new File("/dev/null")).start();
            process.getOutputStream().close();
            if (!process.waitFor(60, TimeUnit.SECONDS)) throw new IOException("로컬 모델 실행 시간이 초과됐습니다.");
            if (process.exitValue() != 0) {
                throw new IOException("로컬 모델 실행에 실패했습니다 (" + process.exitValue() + ").");
            }
            String generated;
            try (InputStream input = new java.io.FileInputStream(output)) {
                generated = new String(readLimited(input, 8192), StandardCharsets.UTF_8);
            }
            if (generated.startsWith(prompt)) generated = generated.substring(prompt.length());
            JSONObject proposed = new JSONObject(generated.trim());
            String line = proposed.getString("line");
            if (proposed.length() != 2 || !"append_line".equals(proposed.getString("tool")) || line.isBlank()
                    || line.chars().anyMatch(Character::isISOControl) || !instruction.contains(line)) {
                throw new IOException("안전한 메모 변경안을 만들지 못했습니다.");
            }
            return line;
        } finally {
            if (process != null && process.isAlive()) process.destroyForcibly();
            output.delete();
        }
    }

    static JSONObject source(String name, String text) throws Exception {
        return new JSONObject().put("name", name).put("text", text).put("sha256", sha(text));
    }

    JSONObject requestDraft(String token, String instruction, JSONArray sources) throws Exception {
        if (!token.matches("[0-9a-f]{64}")) throw new IOException("PC 연결 토큰을 확인해 주세요.");
        String id = UUID.randomUUID().toString();
        byte[] request = new JSONObject().put("id", id).put("task", "meeting_draft")
                .put("instruction", instruction).put("sources", sources).toString().getBytes(StandardCharsets.UTF_8);
        long start = SystemClock.elapsedRealtime();
        HttpURLConnection connection = (HttpURLConnection) new URL("http://127.0.0.1:18120/v1/jobs").openConnection();
        try {
            connection.setInstanceFollowRedirects(false);
            connection.setRequestMethod("POST");
            connection.setDoOutput(true);
            connection.setConnectTimeout(4000);
            connection.setReadTimeout(130000);
            connection.setRequestProperty("Authorization", "Bearer " + token);
            connection.setRequestProperty("Content-Type", "application/json; charset=utf-8");
            connection.setFixedLengthStreamingMode(request.length);
            try (OutputStream output = connection.getOutputStream()) { output.write(request); }
            if (connection.getResponseCode() != 200) throw new IOException("PC 작업 실패 (HTTP " + connection.getResponseCode() + ")");
            try (InputStream input = connection.getInputStream()) {
                JSONObject result = new JSONObject(new String(readLimited(input, 65536), StandardCharsets.UTF_8));
                if (!id.equals(result.getString("id")) || result.getString("draft").isBlank()) throw new JSONException("PC 결과가 요청과 일치하지 않습니다.");
                JSONArray hashes = result.getJSONArray("source_hashes");
                if (hashes.length() != sources.length()) throw new JSONException("PC 문서 목록이 일치하지 않습니다.");
                for (int i = 0; i < hashes.length(); i++) {
                    if (!hashes.getString(i).equals(sources.getJSONObject(i).getString("sha256"))) throw new JSONException("PC 문서 해시가 일치하지 않습니다.");
                }
                return result.put("round_trip_ms", SystemClock.elapsedRealtime() - start);
            }
        } finally {
            connection.disconnect();
        }
    }
}
