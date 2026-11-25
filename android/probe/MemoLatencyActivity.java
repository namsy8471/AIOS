package org.aios.mobile;

import android.app.Activity;
import android.app.AlertDialog;
import android.os.Bundle;
import android.text.Editable;
import android.text.TextWatcher;
import android.view.View;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import java.io.File;
import java.io.IOException;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public final class MemoLatencyActivity extends Activity {
    static final String COMMAND = "메모에 우유 추가";
    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private MobileEngine engine;
    EditText instruction;
    Button preview;
    private Button save;
    private TextView status;
    private TextView memo;
    private TextView inlineText;
    private LinearLayout inline;
    private AlertDialog dialog;
    private String preparedInput;
    private String preparedLine;
    private String memoRevision;
    int variant;
    Sample sample;

    static final class Sample {
        final CountDownLatch frame = new CountDownLatch(1);
        volatile long inputNs;
        long clickNs;
        long readyNs;
        volatile long frameNs;
        volatile Throwable error;
        String revision;
        String line;
    }

    @Override protected void onCreate(Bundle state) {
        super.onCreate(state);
        setShowWhenLocked(true);
        setTurnScreenOn(true);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        engine = new MobileEngine(this, new File(getFilesDir(), "latency-probe"));
        ScrollView page = new ScrollView(this);
        LinearLayout column = new LinearLayout(this);
        column.setOrientation(LinearLayout.VERTICAL);
        int padding = Math.round(20 * getResources().getDisplayMetrics().density);
        column.setPadding(padding, padding, padding, padding);
        page.addView(column);
        setContentView(page);
        text(column, "AIOS");
        instruction = new EditText(this);
        instruction.setShowSoftInputOnFocus(false);
        column.addView(instruction);
        status = text(column, "");
        text(column, "이 휴대폰의 메모");
        memo = text(column, "");
        memo.setMaxLines(3);
        try {
            refreshMemo();
        } catch (Exception error) {
            throw new IllegalStateException(error);
        }
        preview = button(column, "메모 변경 미리 보기", this::previewMemo);
        inline = new LinearLayout(this);
        inline.setOrientation(LinearLayout.VERTICAL);
        text(inline, "메모에 추가할 내용");
        inlineText = text(inline, "");
        LinearLayout actions = new LinearLayout(this);
        inline.addView(actions);
        button(actions, "취소", this::resetPreview);
        save = button(actions, "저장", () -> saveMemo(sample));
        inline.setVisibility(View.GONE);
        column.addView(inline);
        instruction.addTextChangedListener(new TextWatcher() {
            @Override public void beforeTextChanged(CharSequence text, int start, int count, int after) {}
            @Override public void onTextChanged(CharSequence text, int start, int before, int count) {
                preparedInput = text.toString();
                try {
                    preparedLine = MobileEngine.directMemoLine(preparedInput);
                } catch (IOException error) {
                    preparedLine = null;
                }
            }
            @Override public void afterTextChanged(Editable text) {}
        });
    }

    private TextView text(LinearLayout parent, String value) {
        TextView view = new TextView(this);
        view.setText(value);
        parent.addView(view);
        return view;
    }

    private Button button(LinearLayout parent, String value, Runnable action) {
        Button button = new Button(this);
        button.setText(value);
        button.setAllCaps(false);
        button.setOnClickListener(v -> action.run());
        parent.addView(button);
        return button;
    }

    private void refreshMemo() throws Exception {
        String text = engine.memoText();
        memoRevision = MobileEngine.sha(text);
        memo.setText(text);
    }

    private void previewMemo() {
        Sample current = sample;
        if (current == null) return;
        current.clickNs = System.nanoTime();
        String input = instruction.getText().toString();
        int mode = variant;
        String prepared = mode >= 1 && input.equals(preparedInput) ? preparedLine : null;
        String revision = mode >= 2 ? memoRevision : null;
        if (mode >= 3 && prepared != null && revision != null) {
            render(current, mode, revision, prepared);
            return;
        }
        preview.setEnabled(false);
        status.setText("메모 미리 보기 준비 중");
        worker.execute(() -> {
            try {
                String base = revision == null ? MobileEngine.sha(engine.memoText()) : revision;
                String addition = prepared == null ? engine.proposeLine(input, false) : prepared;
                runOnUiThread(() -> {
                    preview.setEnabled(true);
                    render(current, mode, base, addition);
                });
            } catch (Exception error) {
                current.error = error;
                current.frame.countDown();
            }
        });
    }

    private void render(Sample current, int mode, String revision, String line) {
        current.readyNs = System.nanoTime();
        current.revision = revision;
        current.line = line;
        status.setText("미리 보기");
        View frameView;
        if (mode == 4) {
            inlineText.setText(line);
            inline.setVisibility(View.VISIBLE);
            frameView = inline;
        } else {
            dialog = new AlertDialog.Builder(this).setTitle("메모에 추가할 내용").setMessage(line)
                .setNegativeButton("취소", null)
                .setPositiveButton("저장", (d, action) -> saveMemo(current)).create();
            dialog.getWindow().addFlags(WindowManager.LayoutParams.FLAG_HARDWARE_ACCELERATED);
            dialog.show();
            frameView = dialog.getWindow().getDecorView();
        }
        if (frameView.isAttachedToWindow()) {
            watchFrame(frameView, current);
        } else {
            frameView.addOnAttachStateChangeListener(new View.OnAttachStateChangeListener() {
                @Override public void onViewAttachedToWindow(View view) {
                    view.removeOnAttachStateChangeListener(this);
                    watchFrame(view, current);
                }
                @Override public void onViewDetachedFromWindow(View view) {}
            });
        }
    }

    private void watchFrame(View frameView, Sample current) {
        if (!frameView.isHardwareAccelerated()) {
            current.error = new IllegalStateException("Preview window has no hardware renderer");
            current.frame.countDown();
            return;
        }
        frameView.getViewTreeObserver().registerFrameCommitCallback(() -> {
            current.frameNs = System.nanoTime();
            current.frame.countDown();
        });
        frameView.invalidate();
    }

    void resetPreview() {
        if (dialog != null) {
            dialog.dismiss();
            dialog = null;
        }
        inline.setVisibility(View.GONE);
        status.setText("");
    }

    void approveInline() { save.performClick(); }

    private void saveMemo(Sample saved) {
        resetPreview();
        worker.execute(() -> {
            try {
                engine.saveMemo(saved.revision, saved.line);
                runOnUiThread(() -> {
                    try {
                        refreshMemo();
                        status.setText("메모 저장 완료");
                    } catch (Exception error) {
                        saved.error = error;
                    }
                });
            } catch (Exception error) {
                saved.error = error;
            }
        });
    }

    @Override protected void onDestroy() {
        worker.shutdownNow();
        super.onDestroy();
    }
}
