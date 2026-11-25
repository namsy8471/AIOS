package org.aios.mobile;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.database.Cursor;
import android.graphics.Insets;
import android.net.Uri;
import android.os.Bundle;
import android.os.SystemClock;
import android.provider.OpenableColumns;
import android.text.InputType;
import android.view.WindowInsets;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import java.io.IOException;
import java.io.InputStream;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.Callable;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.function.Consumer;
import org.json.JSONArray;
import org.json.JSONObject;

public final class MainActivity extends Activity {
    private static final int PICK_MODEL = 1;
    private static final int PICK_NOTES = 2;
    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private final List<Button> controls = new ArrayList<>();
    private LinearLayout content;
    private TextView status;
    private TextView memo;
    private TextView files;
    private TextView draft;
    private EditText instruction;
    private EditText token;
    private JSONArray selected = new JSONArray();
    private MobileEngine engine;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        engine = new MobileEngine(this);
        ScrollView page = new ScrollView(this);
        content = new LinearLayout(this);
        content.setOrientation(LinearLayout.VERTICAL);
        page.addView(content);
        page.setOnApplyWindowInsetsListener((view, window) -> {
            Insets safe = window.getInsets(WindowInsets.Type.systemBars());
            view.setPadding(safe.left + dp(20), safe.top + dp(12), safe.right + dp(20), safe.bottom + dp(16));
            return window;
        });
        setContentView(page);

        label("AIOS", 28);
        instruction = input("예: 메모에 우유를 적어 줘.", InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_MULTI_LINE);
        status = label(engine.weights().isFile() ? "로컬 모델 준비됨" : "로컬 모델을 가져오세요.", 15);
        label("이 휴대폰의 메모", 20);
        memo = label("", 16);
        button("로컬 모델 가져오기", () -> pick(PICK_MODEL, "*/*", false));
        button("메모 변경 미리 보기", this::previewMemo);
        label("Windows PC에 작업 보내기", 20);
        token = input("PC 연결 토큰", InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
        token.setText(getPreferences(MODE_PRIVATE).getString("usb_token", ""));
        files = label("선택한 회의 메모 없음", 15);
        button("회의 메모 선택", () -> pick(PICK_NOTES, "text/*", true));
        button("보낼 내용 확인", this::confirmDraftRequest);
        label("저장한 보고서 초안", 20);
        draft = label("", 16);
        refresh();
    }

    private int dp(int value) { return Math.round(value * getResources().getDisplayMetrics().density); }

    private TextView label(String text, int size) {
        TextView view = new TextView(this);
        view.setText(text);
        view.setTextSize(size);
        view.setPadding(0, dp(7), 0, dp(7));
        content.addView(view);
        return view;
    }

    private EditText input(String hint, int type) {
        EditText view = new EditText(this);
        view.setHint(hint);
        view.setInputType(type);
        content.addView(view);
        return view;
    }

    private void button(String text, Runnable action) {
        Button view = new Button(this);
        view.setAllCaps(false);
        view.setText(text);
        view.setOnClickListener(clicked -> action.run());
        content.addView(view);
        controls.add(view);
    }

    private void refresh() {
        try {
            memo.setText(engine.memoText());
            draft.setText(engine.draftText());
        } catch (IOException error) {
            status.setText("저장된 문서를 읽을 수 없습니다.");
        }
    }

    private <T> void run(String progress, Callable<T> task, Consumer<T> complete) {
        controls.forEach(button -> button.setEnabled(false));
        status.setText(progress);
        worker.execute(() -> {
            try {
                T result = task.call();
                runOnUiThread(() -> {
                    if (isFinishing() || isDestroyed()) return;
                    controls.forEach(button -> button.setEnabled(true));
                    complete.accept(result);
                });
            } catch (Exception error) {
                runOnUiThread(() -> {
                    if (isFinishing() || isDestroyed()) return;
                    controls.forEach(button -> button.setEnabled(true));
                    status.setText(error.getLocalizedMessage() == null ? "작업을 끝내지 못했습니다." : error.getLocalizedMessage());
                });
            }
        });
    }

    private void previewMemo() {
        String text = instruction.getText().toString();
        long start = SystemClock.elapsedRealtime();
        run("휴대폰에서 추론 중", () -> new String[] {MobileEngine.sha(engine.memoText()), engine.proposeLine(text)}, proposal -> {
            status.setText("미리 보기 · " + (SystemClock.elapsedRealtime() - start) + " ms");
            new AlertDialog.Builder(this).setTitle("메모에 추가할 내용").setMessage(proposal[1])
                .setNegativeButton("취소", null).setPositiveButton("저장", (dialog, action) -> {
                    long save = SystemClock.elapsedRealtime();
                    run("메모 저장 중", () -> { engine.saveMemo(proposal[0], proposal[1]); return null; }, ignored -> {
                        refresh();
                        status.setText("메모 저장 완료 · " + (SystemClock.elapsedRealtime() - save) + " ms");
                    });
                }).show();
        });
    }

    private void confirmDraftRequest() {
        String task = instruction.getText().toString().trim();
        String pairing = token.getText().toString().trim();
        JSONArray sources = selected;
        if (sources.length() == 0 || task.isEmpty()) { status.setText("회의 메모와 지시를 입력해 주세요."); return; }
        if (task.getBytes(StandardCharsets.UTF_8).length > 1024) { status.setText("지시는 1024바이트 이내로 입력해 주세요."); return; }
        if (!pairing.matches("[0-9a-f]{64}")) { status.setText("PC 연결 토큰을 확인해 주세요."); return; }
        StringBuilder preview = new StringBuilder(task);
        for (int i = 0; i < sources.length(); i++) {
            JSONObject source = sources.optJSONObject(i);
            preview.append("\n\n").append(source.optString("name")).append('\n').append(source.optString("text"));
        }
        new AlertDialog.Builder(this).setTitle("Windows 작업자에게 보낼 내용").setMessage(preview)
            .setNegativeButton("취소", null).setPositiveButton("보내기", (dialog, action) -> {
                getPreferences(MODE_PRIVATE).edit().putString("usb_token", pairing).apply();
                run("Windows에서 보고서 작성 중", () -> engine.requestDraft(pairing, task, sources), this::reviewDraft);
            }).show();
    }

    private void reviewDraft(JSONObject result) {
        String text = result.optString("draft");
        status.setText("PC 왕복 " + result.optLong("round_trip_ms") + " ms · 추론 " + result.optLong("inference_ms") + " ms");
        new AlertDialog.Builder(this).setTitle("Windows가 만든 보고서 초안").setMessage(text)
            .setNegativeButton("취소", null).setPositiveButton("저장", (dialog, action) ->
                run("초안 저장 중", () -> { engine.saveDraft(text); return null; }, ignored -> {
                    refresh();
                    status.setText("초안 저장 완료");
                })).show();
    }

    private void pick(int request, String type, boolean multiple) {
        Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType(type);
        intent.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, multiple);
        startActivityForResult(intent, request);
    }

    @Override protected void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request, result, data);
        if (result != RESULT_OK || data == null) return;
        if (request == PICK_MODEL && data.getData() != null) {
            run("로컬 모델 가져오는 중", () -> {
                try (InputStream model = getContentResolver().openInputStream(data.getData())) {
                    if (model == null) throw new IOException("모델을 열 수 없습니다.");
                    engine.importWeights(model);
                }
                return null;
            }, ignored -> status.setText("로컬 모델 준비됨"));
        } else if (request == PICK_NOTES) {
            List<Uri> uris = new ArrayList<>();
            if (data.getClipData() == null) {
                if (data.getData() != null) uris.add(data.getData());
            } else {
                for (int i = 0; i < data.getClipData().getItemCount(); i++) uris.add(data.getClipData().getItemAt(i).getUri());
            }
            if (uris.isEmpty() || uris.size() > 3) { status.setText("메모를 한 개에서 세 개까지 선택해 주세요."); return; }
            run("메모 읽는 중", () -> {
                JSONArray notes = new JSONArray();
                for (Uri uri : uris) notes.put(readNote(uri));
                return notes;
            }, notes -> {
                selected = notes;
                List<String> names = new ArrayList<>();
                for (int i = 0; i < notes.length(); i++) names.add(notes.optJSONObject(i).optString("name"));
                files.setText(String.join("\n", names));
                status.setText("회의 메모 " + names.size() + "개 선택됨");
            });
        }
    }

    private JSONObject readNote(Uri uri) throws Exception {
        String name = "회의 메모";
        try (Cursor columns = getContentResolver().query(uri, new String[]{OpenableColumns.DISPLAY_NAME}, null, null, null)) {
            if (columns != null && columns.moveToFirst() && columns.getString(0) != null) name = columns.getString(0);
        }
        try (InputStream input = getContentResolver().openInputStream(uri)) {
            if (input == null) throw new IOException("메모를 열 수 없습니다.");
            byte[] bytes = MobileEngine.readLimited(input, MobileEngine.MAX_SOURCE_BYTES);
            String text = StandardCharsets.UTF_8.newDecoder().decode(ByteBuffer.wrap(bytes)).toString();
            if (text.isBlank()) throw new IOException("빈 메모는 보낼 수 없습니다.");
            return MobileEngine.source(name, text);
        }
    }

    @Override protected void onDestroy() {
        worker.shutdownNow();
        super.onDestroy();
    }
}
