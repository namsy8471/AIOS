package org.aios.mobile;

import android.app.Activity;
import android.app.Instrumentation;
import android.content.Context;
import android.os.Bundle;
import android.os.SystemClock;
import android.util.Base64;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.Arrays;
import org.json.JSONArray;
import org.json.JSONObject;

public final class MobileProbe extends Instrumentation {
    private String mode;

    @Override public void onCreate(Bundle arguments) {
        super.onCreate(arguments);
        mode = arguments.getString("mode", "");
        start();
    }

    @Override public void onStart() {
        Bundle result = new Bundle();
        try {
            Context app = getTargetContext();
            File probe = new File(app.getFilesDir(), "probe");
            if (!probe.isDirectory() && !probe.mkdirs()) throw new IllegalStateException("Cannot create probe workspace");
            MobileEngine engine = new MobileEngine(app, probe);
            JSONObject report = new JSONObject().put("mode", mode);
            if ("memo-latency".equals(mode)) {
                report = MemoLatencyProbe.run(this, app);
            } else if ("production-memo".equals(mode)) {
                report = ProductionMemoProbe.run(this, app);
            } else if ("agent-actions".equals(mode)) {
                report = AgentActionProbe.run(this, app);
            } else if ("direct".equals(mode)) {
                checkDirectMemo(engine, report);
            } else if ("local".equals(mode) || "large".equals(mode)) {
                long start = SystemClock.elapsedRealtime();
                String original = engine.memoText();
                String revision = MobileEngine.sha(original);
                String line = engine.inferMemoLine("메모에 '우유'를 적어줘.", "large".equals(mode));
                if (!"우유".equals(line) || !engine.memoText().equals(original)) throw new AssertionError("Invalid unsaved proposal");
                long preview = SystemClock.elapsedRealtime();
                engine.saveMemo(revision, line);
                String expected = original + (original.isEmpty() || original.endsWith("\n") ? "" : "\n") + line;
                if (!expected.equals(engine.memoText())) throw new AssertionError("Memo was not saved");
                report.put("preview_ms", preview - start).put("save_ms", SystemClock.elapsedRealtime() - preview)
                    .put("memo", expected).put("revision", MobileEngine.sha(expected));
            } else if ("verify".equals(mode)) {
                report.put("memo", engine.memoText()).put("revision", MobileEngine.sha(engine.memoText()));
            } else if ("pc".equals(mode)) {
                PcPairing pc = new PcPairing(Files.readString(new File(probe, "pairing.json").toPath(), StandardCharsets.UTF_8));
                JSONArray notes = new JSONArray()
                    .put(MobileEngine.source("회의 1.txt", "서윤은 2026-11-27까지 플립4 앱 UI 점검을 완료한다."))
                    .put(MobileEngine.source("회의 2.txt", "지훈은 2026-11-29까지 Windows 문서 초안 기능을 검증한다."))
                    .put(MobileEngine.source("회의 3.txt", "다은은 2026-12-02까지 공동 테스트 결과를 정리한다."));
                String oldDraft = engine.draftText();
                JSONObject reply = engine.requestDraft(pc, "담당자와 기한이 빠지지 않게 회의 보고서 초안을 만들어 줘.", notes, "local");
                if (!oldDraft.equals(engine.draftText())) throw new AssertionError("Draft was saved before review");
                String draft = reply.getString("draft");
                for (String[] expected : new String[][]{{"서윤", "2026-11-27"}, {"지훈", "2026-11-29"}, {"다은", "2026-12-02"}}) {
                    if (draft.lines().noneMatch(line -> line.contains(expected[0]) && line.contains(expected[1]))) {
                        throw new AssertionError("Missing draft deadline for " + expected[0]);
                    }
                }
                engine.saveDraft(draft);
                if (!draft.equals(engine.draftText())) throw new AssertionError("Draft was not saved");
                report.put("reply", reply).put("saved_draft_sha256", MobileEngine.sha(draft));
            } else {
                throw new IllegalArgumentException("Unknown probe mode");
            }
            result.putString("aios_proof", Base64.encodeToString(report.toString().getBytes(StandardCharsets.UTF_8), Base64.NO_WRAP));
            finish(Activity.RESULT_OK, result);
        } catch (Throwable error) {
            result.putString("aios_error", error.toString());
            finish(Activity.RESULT_CANCELED, result);
        }
    }

    private static void checkDirectMemo(MobileEngine engine, JSONObject report) throws Exception {
        for (String[] example : new String[][]{
            {"메모에 우유 추가", "우유"}, {"메모에 '우유'를 적어줘.", "우유"},
            {"메모에 \"저지방 우유 2개\" 추가", "저지방 우유 2개"}
        }) {
            if (!example[1].equals(MobileEngine.directMemoLine(example[0]))) {
                throw new AssertionError("Unrecognized direct memo format");
            }
        }
        for (String example : new String[]{"메모에 우유를 적어줘.", "메모에 우유 추가하지 마",
            "메모에서 우유 삭제", "메모에 우유 추가하고 달걀도 추가", "메모에 ' ' 추가"}) {
            if (MobileEngine.directMemoLine(example) != null) throw new AssertionError("Ambiguous text matched");
        }
        try {
            MobileEngine.directMemoLine("메모에 '우유\n달걀' 추가");
            throw new AssertionError("Multiline input matched");
        } catch (java.io.IOException expected) {
            // The same input validation applies before selecting a preview path.
        }
        String original = engine.memoText();
        long[] times = new long[100];
        String line = "";
        for (int i = 0; i < times.length; i++) {
            long start = SystemClock.elapsedRealtimeNanos();
            String revision = MobileEngine.sha(engine.memoText());
            line = engine.proposeLine("메모에 '우유'를 적어줘.", true);
            times[i] = SystemClock.elapsedRealtimeNanos() - start;
            if (!"우유".equals(line) || !MobileEngine.sha(original).equals(revision)) {
                throw new AssertionError("Invalid direct preview");
            }
        }
        if (!original.equals(engine.memoText())) throw new AssertionError("Preview modified the memo");
        if (!"우유".equals(engine.proposeLine("메모에 우유를 적어줘.", false))) {
            throw new AssertionError("The model fallback did not preserve the memo text");
        }
        long first = times[0];
        Arrays.sort(times);
        report.put("trials", times.length).put("first_us", first / 1000.0)
            .put("median_us", (times[49] + times[50]) / 2000.0).put("p95_us", times[94] / 1000.0);
        String revision = MobileEngine.sha(original);
        engine.saveMemo(revision, line);
        String separator = original.isEmpty() || original.endsWith("\n") ? "" : "\n";
        if (!(original + separator + line).equals(engine.memoText())) throw new AssertionError("Memo was not saved");
        try {
            engine.saveMemo(revision, line);
            throw new AssertionError("Accepted a stale revision");
        } catch (java.io.IOException expected) {
            // Approval remains bound to the previewed revision.
        }
    }
}
