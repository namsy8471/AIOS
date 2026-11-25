package org.aios.mobile;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.database.Cursor;
import android.graphics.Rect;
import android.net.Uri;
import android.os.Bundle;
import android.os.SystemClock;
import android.provider.OpenableColumns;
import android.text.InputType;
import android.text.Editable;
import android.text.TextWatcher;
import android.view.Gravity;
import android.view.View;
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
import java.util.ArrayDeque;
import java.util.List;
import java.util.concurrent.Callable;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.function.Consumer;
import org.json.JSONArray;
import org.json.JSONObject;

public class MainActivity extends Activity {
    private String remoteRequest;
    private static final java.util.regex.Pattern CAPABILITIES = java.util.regex.Pattern.compile(
        "(?:뭐(?:를)?|뭘|무엇(?:을)?|어떤\\s*일(?:을)?)\\s*(?:해\\s*줄|할)\\s*수|(?:가능한|할\\s*수\\s*있는)\\s*(?:일|기능)|너의?\\s*기능|what can you do",
        java.util.regex.Pattern.CASE_INSENSITIVE);
    private static final int PICK_MODEL = 1;
    private static final int PICK_NOTES = 2;
    private static final int PICK_PC = 3;
    private static final int PICK_LARGE_MODEL = 4;
    private static final int PICK_VISION_MODEL = 5;
    private static final int PICK_VISION_PROJECTOR = 6;
    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private final List<Button> controls = new ArrayList<>();
    private WorkspaceUi ui;
    private PhoneControls phoneControls;
    private ScrollView page;
    private LinearLayout conversation;
    private LinearLayout welcome;
    private final ArrayDeque<View> messages = new ArrayDeque<>();
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
        ui = new WorkspaceUi(this);
        phoneControls = new PhoneControls(this, result -> appendMessage(result, false));
        LinearLayout root = ui.screen();
        LinearLayout heading = ui.row();
        ui.pad(heading, 18, 8);
        LinearLayout brand = ui.column();
        brand.addView(ui.text(getApplicationInfo().loadLabel(getPackageManager()).toString(), 24, false));
        brand.addView(ui.text("Thanks, Local Agent", 12, true));
        heading.addView(brand, new LinearLayout.LayoutParams(0, -2, 1));
        Button workTab = ui.button("대화", () -> {});
        Button settingsTab = ui.button("도구 · 설정", () -> {});
        workTab.setTag("workspace-tab");
        settingsTab.setTag("settings-tab");
        LinearLayout.LayoutParams workTabLayout = new LinearLayout.LayoutParams(-2, -2);
        workTabLayout.rightMargin = ui.dp(6);
        heading.addView(workTab, workTabLayout);
        heading.addView(settingsTab);
        root.addView(heading);

        page = new ScrollView(this);
        page.setFillViewport(true);
        page.setClipToPadding(false);
        page.setVerticalScrollBarEnabled(false);
        LinearLayout body = ui.column();
        ui.pad(body, 18, 8);
        page.addView(body);
        root.addView(page, new LinearLayout.LayoutParams(-1, 0, 1));

        LinearLayout workspace = ui.column();
        LinearLayout settings = ui.column();
        body.addView(workspace);
        body.addView(settings);
        conversation = workspace;
        buildWelcome();
        content = ui.card(settings);
        label("이 휴대폰의 메모", 18);
        memo = label("", 16);
        memo.setHint("저장된 메모가 없습니다.");
        memo.setTextIsSelectable(true);

        content = ui.card(settings);
        label("Windows 협업", 18);
        files = label("선택한 회의 메모 없음", 14);
        button("회의 메모 선택", () -> pick(PICK_NOTES, "text/*", true));
        pcModelChoice = selector("Windows 로컬 모델", "ChatGPT 계정", "Claude 계정");
        button("보낼 내용 확인", this::confirmDraftRequest);
        label("저장한 보고서 초안", 16);
        draft = label("", 15);
        draft.setHint("저장된 보고서가 없습니다.");
        draft.setTextIsSelectable(true);
        button("Google Drive에 보내기", this::confirmDriveUpload);

        content = ui.card(settings);
        label("로컬 모델", 18);
        modelChoice = selector("로컬 경량 모델", "로컬 대형 모델");
        button("선택한 로컬 모델 가져오기", () ->
            pick(modelChoice.getSelectedItemPosition() == 1 ? PICK_LARGE_MODEL : PICK_MODEL, "*/*", false));
        if (new ScreenVision(this).installed()) {
            button("화면 인식 모델 가져오기", () -> pick(PICK_VISION_MODEL, "*/*", false));
            button("이미지 인코더 가져오기", () -> pick(PICK_VISION_PROJECTOR, "*/*", false));
        }
        button("수동 앱 작업", () -> startActivity(new Intent(this, AgentActivity.class)));
        content = ui.card(settings);
        label("PC 연결", 18);
        pcStatus = label("연결한 PC 없음", 14);
        button("PC 페어링 파일 가져오기", () -> pick(PICK_PC, "*/*", false));
        try {
            pc = engine.pairedPc();
            if (pc != null) pcStatus.setText("페어링된 PC · " + pc.endpoint);
        } catch (Exception invalid) {
            pcStatus.setText("PC 페어링 파일을 다시 가져오세요.");
        }

        status = ui.text(engine.weights(false).isFile() ? "로컬 모델 준비됨" : "설정에서 로컬 모델을 가져오세요.", 13, true);
        LinearLayout.LayoutParams statusLayout = new LinearLayout.LayoutParams(-1, -2);
        statusLayout.leftMargin = ui.dp(20);
        statusLayout.rightMargin = ui.dp(20);
        root.addView(status, statusLayout);
        LinearLayout dock = ui.column();
        dock.setPadding(ui.dp(18), 0, ui.dp(18), ui.dp(12));
        content = ui.card(dock);
        LinearLayout composer = content;
        instruction = input("TLA에 지시하기", InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_MULTI_LINE);
        instruction.setBackgroundColor(android.graphics.Color.TRANSPARENT);
        instruction.setMaxLines(3);
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
        LinearLayout actions = ui.row();
        LinearLayout.LayoutParams actionRow = new LinearLayout.LayoutParams(-1, -2);
        actionRow.topMargin = ui.dp(8);
        composer.addView(actions, actionRow);
        Button preview = ui.composerAction("↑", "보내기", true, this::sendCommand);
        preview.setTag("memo-preview-button");
        controls.add(preview);
        actions.addView(new View(this), new LinearLayout.LayoutParams(0, 1, 1));
        actions.addView(preview, new LinearLayout.LayoutParams(ui.dp(48), ui.dp(48)));
        content = conversation;
        buildMemoPreview();
        root.addView(dock);
        workTab.setOnClickListener(view -> {
            workspace.setVisibility(View.VISIBLE);
            settings.setVisibility(View.GONE);
            dock.setVisibility(View.VISIBLE);
            ui.tone(workTab, true);
            ui.tone(settingsTab, false);
            page.scrollTo(0, 0);
        });
        settingsTab.setOnClickListener(view -> {
            settings.setVisibility(View.VISIBLE);
            workspace.setVisibility(View.GONE);
            dock.setVisibility(View.GONE);
            android.view.inputmethod.InputMethodManager keyboard = getSystemService(android.view.inputmethod.InputMethodManager.class);
            keyboard.hideSoftInputFromWindow(instruction.getWindowToken(), 0);
            ui.tone(settingsTab, true);
            ui.tone(workTab, false);
            page.scrollTo(0, 0);
        });
        controls.add(workTab);
        controls.add(settingsTab);
        settings.setVisibility(View.GONE);
        ui.tone(workTab, true);
        setContentView(root);
        refresh();
    }

    MobileEngine createEngine() { return new MobileEngine(this); }

    @Override protected void onResume() {
        super.onResume();
        phoneControls.resume();
    }

    private void buildWelcome() {
        welcome = ui.column();
        ui.pad(welcome, 8, 16);
        welcome.setGravity(Gravity.CENTER);
        TextView title = ui.text("무엇을 할까요?", 30, false);
        title.setGravity(Gravity.CENTER);
        welcome.addView(title);
        Button memoExample = ui.button("메모에 우유 추가", () -> setPrompt("메모에 우유 추가"));
        Button searchExample = ui.button("오늘 날씨 검색", () -> setPrompt("오늘 날씨 검색"));
        LinearLayout examples = ui.row();
        LinearLayout.LayoutParams row = new LinearLayout.LayoutParams(-1, -2);
        row.topMargin = ui.dp(16);
        welcome.addView(examples, row);
        ui.paired(examples, memoExample, searchExample);
        conversation.addView(welcome);
        page.addOnLayoutChangeListener((view, left, top, right, bottom, prevLeft, prevTop, prevRight, prevBottom) -> {
            if (bottom - top != prevBottom - prevTop) {
                welcome.setMinimumHeight(Math.min(ui.dp(420), (bottom - top) * 3 / 4));
            }
        });
    }

    private void setPrompt(String value) {
        instruction.setText(value);
        instruction.setSelection(value.length());
    }

    private void appendMessage(String value, boolean user) {
        if (!user && remoteRequest != null) {
            RemoteResults.update(remoteRequest, "reply", value);
            remoteRequest = null;
        }
        welcome.setVisibility(View.GONE);
        LinearLayout.LayoutParams entry = new LinearLayout.LayoutParams(user ? -2 : -1, -2);
        entry.gravity = user ? Gravity.END : Gravity.START;
        if (user) entry.leftMargin = ui.dp(36);
        entry.topMargin = ui.dp(10);
        TextView bubble = ui.bubble(value, user);
        messages.addLast(bubble);
        conversation.addView(bubble, entry);
        if (messages.size() > 40) conversation.removeView(messages.removeFirst());
        scrollConversation();
    }

    private void scrollConversation() {
        page.post(() -> page.scrollTo(0, page.getChildAt(0).getHeight()));
    }

    private void sendCommand() {
        sendCommand(null);
    }

    final void executeRemote(String id, String command) {
        RemoteResults.update(id, "accepted", "휴대폰에서 요청을 받았어요.");
        setPrompt(command);
        sendCommand(id);
    }

    private void sendCommand(String requestId) {
        String text = instruction.getText().toString().strip();
        if (text.isEmpty()) return;
        if (text.length() > 512) {
            status.setText("지시를 512자 이내로 입력해 주세요.");
            return;
        }
        remoteRequest = requestId;
        clearMemoPreview();
        instruction.setText("");
        appendMessage(text, true);
        getSystemService(android.view.inputmethod.InputMethodManager.class)
            .hideSoftInputFromWindow(instruction.getWindowToken(), 0);
        PhoneControls.Command setting = PhoneControls.parse(text);
        String query = AgentAction.searchQuery(text);
        if (CAPABILITIES.matcher(text).find()) {
            appendMessage("저는 TLA예요. 질문에 답하고, 휴대폰에서 앱을 열거나 Google 검색을 열고, 메모·타이머를 다룰 수 있어요. "
                + "화면에서 읽을 수 있는 버튼은 찾아서 여러 단계로 이어갈 수 있어요. 결제처럼 확인이 필요한 동작은 PC에 알려요. "
                + "예를 들어 ‘구글에서 네이버 검색해줘’나 ‘설정 열어줘’라고 부탁해 보세요.", false);
        } else if (setting != null) {
            phoneControls.review(setting);
        } else if (PhoneIntents.handle(this, text, result -> appendMessage(result, false))) {
            return;
        } else if (query != null) {
            AgentActivity.search(this, query, requestId != null, result -> appendMessage(result, false));
        } else if (text.equals("메모 보기") || text.equals("메모 보여줘")) {
            String stored = memo.getText().toString();
            appendMessage(stored.isEmpty() ? "저장된 메모가 없습니다." : stored, false);
        } else if (text.startsWith("Windows에 ")) {
            confirmDraftRequest(text);
        } else if (text.startsWith("메모에 ")) {
            previewMemo(text);
        } else if (AgentActivity.handleChatApp(this, text, this::replyToAppTask)
                || AgentActivity.handleScreenTask(this, text, requestId, this::replyToAppTask)) {
            return;
        } else {
            planChatCommand(text, requestId);
        }
    }

    private void replyToAppTask(String result) {
        if (!isFinishing() && !isDestroyed()) appendMessage(result, false);
    }

    private void planChatCommand(String text, String requestId) {
        boolean larger = engine.weights(true).isFile();
        if (!engine.weights(larger).isFile()) {
            clarifyChatCommand(text);
            return;
        }
        int keepScreen = android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON;
        if (requestId != null) getWindow().addFlags(keepScreen);
        run("로컬 모델로 이 요청을 처리할 방법을 찾는 중", () -> {
            try { return engine.planCommand(text, larger); }
            catch (Exception invalid) {
                android.util.Log.w("TLAIntent", "Intent inference failed: " + (invalid instanceof IOException
                    ? invalid.getMessage() : invalid.getClass().getSimpleName()));
                return null;
            }
        }, plan -> {
            if (requestId != null) getWindow().clearFlags(keepScreen);
            status.setText("");
            Consumer<String> reply = result -> appendMessage(result, false);
            if (plan == null) {
                reply.accept("로컬 모델 응답을 읽지 못했어요. 다시 보내 주세요.");
                return;
            }
            String app = planArgument(plan, "app", text);
            String label = planArgument(plan, "label", text);
            String answer = plan.opt("text") instanceof String ? plan.optString("text").strip() : "";
            String tool = plan.optString("tool");
            if ("open".equals(tool) && app != null && plan.length() == 2) {
                AgentActivity.offerChatApp(this, app, null, requestId == null, reply);
            } else if ("click".equals(tool) && app != null && label != null && plan.length() == 3) {
                AgentActivity.offerChatApp(this, app, label, true, reply);
            } else if ("install".equals(tool) && app != null && plan.length() == 2) {
                PhoneIntents.offerInstall(this, app, reply);
            } else if ("search".equals(tool) && label != null && plan.length() == 2) {
                AgentActivity.search(this, label, requestId != null, reply);
            } else if ("answer".equals(tool) && !answer.isEmpty() && answer.length() <= 1200 && plan.length() == 2) {
                reply.accept(answer);
            } else if ("screen".equals(tool) && app != null && plan.length() == 2) {
                AgentActivity.offerScreenTask(this, app, text, requestId, reply);
            } else {
                clarifyChatCommand(text);
            }
        });
    }

    private static String planArgument(JSONObject plan, String key, String request) {
        if (!(plan.opt(key) instanceof String)) return null;
        String value = plan.optString(key).strip();
        return !value.isEmpty() && value.length() <= 128 && request.contains(value) ? value : null;
    }

    private void clarifyChatCommand(String text) {
        if (text.contains("출석") || text.contains("눌러")) {
            appendMessage("어느 앱에서 할까요? 앱 이름을 포함해서 다시 말씀해 주세요.", false);
        } else {
            appendMessage("어떤 결과를 원하시나요? 앱 이름이나 하려는 일을 조금 더 알려 주세요.", false);
        }
    }

    private TextView label(String text, int size) {
        return label(content, text, size);
    }

    private TextView label(LinearLayout parent, String text, int size) {
        TextView view = ui.text(text, size, size <= 14);
        parent.addView(view);
        return view;
    }

    private EditText input(String hint, int type) {
        EditText view = new EditText(this);
        view.setHint(hint);
        view.setInputType(type);
        ui.field(view);
        content.addView(view);
        return view;
    }

    private void button(String text, Runnable action) {
        button(content, text, action);
    }

    private Button button(LinearLayout parent, String text, Runnable action) {
        Button view = ui.button(text, action);
        LinearLayout.LayoutParams item = new LinearLayout.LayoutParams(-1, -2);
        item.topMargin = ui.dp(8);
        parent.addView(view, item);
        controls.add(view);
        return view;
    }

    private Spinner selector(String... values) {
        Spinner spinner = new Spinner(this);
        ArrayAdapter<String> adapter = new ArrayAdapter<>(this, android.R.layout.simple_spinner_item, values);
        adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item);
        spinner.setAdapter(adapter);
        ui.selector(spinner);
        content.addView(spinner);
        return spinner;
    }

    private void buildMemoPreview() {
        memoPreview = ui.card(content);
        memoPreview.setVisibility(View.GONE);
        label(memoPreview, "메모에 추가할 내용", 18);
        memoAddition = label(memoPreview, "", 16);
        memoAddition.setTag("memo-preview-text");
        LinearLayout actions = ui.row();
        Button cancel = ui.button("취소", () -> {
            clearMemoPreview();
            status.setText("메모 변경 취소");
            appendMessage("메모 변경을 취소했어요.", false);
        });
        Button save = ui.button("저장", this::approveMemo);
        cancel.setTag("memo-preview-cancel");
        save.setTag("memo-preview-save");
        ui.tone(save, true);
        ui.paired(actions, cancel, save);
        controls.add(cancel);
        controls.add(save);
        memoPreview.addView(actions);
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

    private void previewMemo(String text) {
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
        memoPreview.bringToFront();
        status.setText("미리 보기 · " + (SystemClock.elapsedRealtime() - start) + " ms");
        memoPreview.post(() -> {
            if (pendingMemo == proposal) {
                memoPreview.requestRectangleOnScreen(new Rect(0, 0, memoPreview.getWidth(), memoPreview.getHeight()), true);
            }
        });
        scrollConversation();
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
            appendMessage("메모에 저장했어요.", false);
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
        confirmDraftRequest(instruction.getText().toString().strip());
    }

    private void confirmDraftRequest(String task) {
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
        appendMessage("Windows가 보고서 초안을 만들었어요.", false);
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
        } else if ((request == PICK_VISION_MODEL || request == PICK_VISION_PROJECTOR) && data.getData() != null) {
            run("화면 인식 파일 가져오는 중", () -> {
                try (InputStream model = getContentResolver().openInputStream(data.getData())) {
                    if (model == null) throw new IOException("모델 파일을 열 수 없어요.");
                    MobileEngine.importGguf(model, ScreenVision.weights(this, request == PICK_VISION_PROJECTOR));
                }
                return new ScreenVision(this).ready();
            }, ready -> status.setText(ready ? "화면 인식 모델 준비됨" : "화면 인식 파일 저장됨"));
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
