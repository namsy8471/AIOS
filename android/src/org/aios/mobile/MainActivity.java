package org.aios.mobile;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.database.Cursor;
import android.graphics.Insets;
import android.graphics.Rect;
import android.net.Uri;
import android.os.Bundle;
import android.os.SystemClock;
import android.provider.OpenableColumns;
import android.text.InputType;
import android.text.Editable;
import android.text.TextWatcher;
import android.view.View;
import android.view.WindowInsets;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.Spinner;
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

public class MainActivity extends Activity {
    private static final int PICK_MODEL = 1;
    private static final int PICK_NOTES = 2;
    private static final int PICK_PC = 3;
    private static final int PICK_LARGE_MODEL = 4;
    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private final List<Button> controls = new ArrayList<>();
    private LinearLayout content;
    private TextView status;
    private TextView memo;
    private TextView files;
    private TextView draft;
    private EditText instruction;
    private TextView pcStatus;
    private Spinner modelChoice;
    private Spinner pcModelChoice;
    private LinearLayout memoPreview;
    private TextView memoAddition;
    private String memoRevision;
    private MemoProposal pendingMemo;
    private int memoRequest;
    private PcPairing pc;
    private JSONArray selected = new JSONArray();
    private MobileEngine engine;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        engine = createEngine();
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
        instruction = input("예: 메모에 우유 추가", InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_MULTI_LINE);
        instruction.setTag("memo-instruction");
        instruction.addTextChangedListener(new TextWatcher() {
            @Override public void beforeTextChanged(CharSequence text, int start, int count, int after) {}
            @Override public void onTextChanged(CharSequence text, int start, int before, int count) {
                memoRequest++;
                if (pendingMemo != null) status.setText("지시가 바뀌었습니다.");
                clearMemoPreview();
            }
            @Override public void afterTextChanged(Editable text) {}
        });
        status = label(engine.weights(false).isFile() ? "로컬 모델 준비됨" : "로컬 모델을 가져오세요.", 15);
        label("이 휴대폰의 메모", 20);
        memo = label("", 16);
        modelChoice = new Spinner(this);
        ArrayAdapter<String> sizes = new ArrayAdapter<>(this, android.R.layout.simple_spinner_item,
                new String[]{"로컬 경량 모델", "로컬 대형 모델"});
        sizes.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item);
        modelChoice.setAdapter(sizes);
        content.addView(modelChoice);
        button("선택한 로컬 모델 가져오기", () ->
            pick(modelChoice.getSelectedItemPosition() == 1 ? PICK_LARGE_MODEL : PICK_MODEL, "*/*", false));
        button(content, "메모 변경 미리 보기", this::previewMemo).setTag("memo-preview-button");
        buildMemoPreview();
        label("Windows PC에 작업 보내기", 20);
        pcStatus = label("연결한 PC 없음", 15);
        button("PC 페어링 파일 가져오기", () -> pick(PICK_PC, "*/*", false));
        try {
            pc = engine.pairedPc();
            if (pc != null) pcStatus.setText("페어링된 PC · " + pc.endpoint);
        } catch (Exception invalid) {
            pcStatus.setText("PC 페어링 파일을 다시 가져오세요.");
        }
        files = label("선택한 회의 메모 없음", 15);
        button("회의 메모 선택", () -> pick(PICK_NOTES, "text/*", true));
        pcModelChoice = new Spinner(this);
        ArrayAdapter<String> providers = new ArrayAdapter<>(this, android.R.layout.simple_spinner_item,
                new String[]{"Windows 로컬 모델", "ChatGPT 계정", "Claude 계정"});
        providers.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item);
        pcModelChoice.setAdapter(providers);
        content.addView(pcModelChoice);
        button("보낼 내용 확인", this::confirmDraftRequest);
        label("저장한 보고서 초안", 20);
        draft = label("", 16);
        button("저장한 초안을 Google Drive에 보내기", this::confirmDriveUpload);
        refresh();
    }

    MobileEngine createEngine() { return new MobileEngine(this); }

    private int dp(int value) { return Math.round(value * getResources().getDisplayMetrics().density); }

    private TextView label(String text, int size) {
        return label(content, text, size);
    }

    private TextView label(LinearLayout parent, String text, int size) {
        TextView view = new TextView(this);
        view.setText(text);
        view.setTextSize(size);
        view.setPadding(0, dp(7), 0, dp(7));
        parent.addView(view);
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
        button(content, text, action);
    }

    private Button button(LinearLayout parent, String text, Runnable action) {
        Button view = new Button(this);
        view.setAllCaps(false);
        view.setText(text);
        view.setOnClickListener(clicked -> action.run());
        parent.addView(view);
        controls.add(view);
        return view;
    }

    private void buildMemoPreview() {
        memoPreview = new LinearLayout(this);
        memoPreview.setOrientation(LinearLayout.VERTICAL);
        memoPreview.setVisibility(View.GONE);
        label(memoPreview, "메모에 추가할 내용", 18);
        memoAddition = label(memoPreview, "", 16);
        memoAddition.setTag("memo-preview-text");
        LinearLayout actions = new LinearLayout(this);
        button(actions, "취소", () -> {
            clearMemoPreview();
            status.setText("메모 변경 취소");
        }).setTag("memo-preview-cancel");
        button(actions, "저장", this::approveMemo).setTag("memo-preview-save");
        memoPreview.addView(actions);
        content.addView(memoPreview);
    }

    private void refresh() {
        try {
            String text = engine.memoText();
            memoRevision = MobileEngine.sha(text);
            memo.setText(text);
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
        boolean larger = modelChoice.getSelectedItemPosition() == 1;
        long start = SystemClock.elapsedRealtime();
        int request = ++memoRequest;
        clearMemoPreview();
        String direct;
        try {
            direct = MobileEngine.directMemoLine(text);
        } catch (IOException error) {
            status.setText(error.getMessage());
            return;
        }
        if (direct != null && memoRevision != null) {
            showMemoPreview(new MemoProposal(memoRevision, direct), start);
            return;
        }
        run("메모 미리 보기 준비 중", () -> {
            String original = engine.memoText();
            String addition = direct == null ? engine.inferMemoLine(text, larger) : direct;
            return new String[] {original, addition, MobileEngine.sha(original)};
        }, result -> {
            memo.setText(result[0]);
            memoRevision = result[2];
            if (request == memoRequest) showMemoPreview(new MemoProposal(result[2], result[1]), start);
            else status.setText("지시가 바뀌었습니다. 다시 미리 보기를 눌러 주세요.");
        });
    }

    private void showMemoPreview(MemoProposal proposal, long start) {
        pendingMemo = proposal;
        memoAddition.setText(proposal.addition);
        memoPreview.setVisibility(View.VISIBLE);
        status.setText("미리 보기 · " + (SystemClock.elapsedRealtime() - start) + " ms");
        memoPreview.post(() -> {
            if (pendingMemo == proposal) {
                memoPreview.requestRectangleOnScreen(new Rect(0, 0, memoPreview.getWidth(), memoPreview.getHeight()), true);
            }
        });
    }

    private void clearMemoPreview() {
        pendingMemo = null;
        if (memoPreview != null) memoPreview.setVisibility(View.GONE);
    }

    private void approveMemo() {
        MemoProposal proposal = pendingMemo;
        if (proposal == null) return;
        clearMemoPreview();
        memoRevision = null;
        long save = SystemClock.elapsedRealtime();
        run("메모 저장 중", () -> { engine.saveMemo(proposal.revision, proposal.addition); return null; }, ignored -> {
            refresh();
            status.setText("메모 저장 완료 · " + (SystemClock.elapsedRealtime() - save) + " ms");
        });
    }

    private static final class MemoProposal {
        final String revision;
        final String addition;

        MemoProposal(String revision, String addition) {
            this.revision = revision;
            this.addition = addition;
        }
    }

    private void confirmDraftRequest() {
        String task = instruction.getText().toString().trim();
        PcPairing paired = pc;
        JSONArray sources = selected;
        String provider = new String[]{"local", "chatgpt", "claude"}[pcModelChoice.getSelectedItemPosition()];
        String destination;
        switch (provider) {
            case "chatgpt": destination = "Windows PC를 거쳐 OpenAI ChatGPT"; break;
            case "claude": destination = "Windows PC를 거쳐 Anthropic Claude"; break;
            default: destination = "Windows PC 로컬 모델";
        }
        if (sources.length() == 0 || task.isEmpty()) { status.setText("회의 메모와 지시를 입력해 주세요."); return; }
        if (task.getBytes(StandardCharsets.UTF_8).length > 1024) { status.setText("지시는 1024바이트 이내로 입력해 주세요."); return; }
        if (paired == null) { status.setText("먼저 Windows PC를 연결해 주세요."); return; }
        StringBuilder preview = new StringBuilder(task);
        for (int i = 0; i < sources.length(); i++) {
            JSONObject source = sources.optJSONObject(i);
            preview.append("\n\n").append(source.optString("name")).append('\n').append(source.optString("text"));
        }
        new AlertDialog.Builder(this).setTitle(destination + "에 보낼 내용").setMessage(preview)
            .setNegativeButton("취소", null).setPositiveButton("보내기", (dialog, action) -> {
                run("보고서 작성 중 · " + destination, () -> engine.requestDraft(paired, task, sources, provider), this::reviewDraft);
            }).show();
    }

    private void confirmDriveUpload() {
        PcPairing paired = pc;
        String saved = draft.getText().toString();
        if (paired == null) { status.setText("먼저 Windows PC를 연결해 주세요."); return; }
        if (saved.isBlank()) { status.setText("먼저 보고서 초안을 저장해 주세요."); return; }
        new AlertDialog.Builder(this).setTitle("Windows PC를 거쳐 Google Drive에 저장").setMessage(saved)
            .setNegativeButton("취소", null).setPositiveButton("Drive에 저장", (dialog, action) ->
                run("Google Drive에 저장 중", () -> engine.uploadDraft(paired, saved), result ->
                    status.setText("Google Drive 저장 완료 · " + result.optString("name")))).show();
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
        if ((request == PICK_MODEL || request == PICK_LARGE_MODEL) && data.getData() != null) {
            boolean larger = request == PICK_LARGE_MODEL;
            run("로컬 모델 가져오는 중", () -> {
                try (InputStream model = getContentResolver().openInputStream(data.getData())) {
                    if (model == null) throw new IOException("모델을 열 수 없습니다.");
                    engine.importWeights(model, larger);
                }
                return null;
            }, ignored -> status.setText("로컬 모델 준비됨"));
        } else if (request == PICK_PC && data.getData() != null) {
            run("PC 페어링 파일 읽는 중", () -> {
                try (InputStream pairing = getContentResolver().openInputStream(data.getData())) {
                    if (pairing == null) throw new IOException("PC 페어링 파일을 열 수 없습니다.");
                    return engine.importPairing(pairing);
                }
            }, paired -> {
                pc = paired;
                pcStatus.setText("페어링된 PC · " + paired.endpoint);
                status.setText("PC 연결 정보 저장 완료");
            });
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
