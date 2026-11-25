package org.aios.mobile;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.content.pm.ResolveInfo;
import android.os.Bundle;
import android.provider.Settings;
import android.text.InputType;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.Spinner;
import android.widget.TextView;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.function.Consumer;

public final class AgentActivity extends Activity {
    private WorkspaceUi ui;
    private LinearLayout content;
    private TextView status;
    private EditText query;
    private EditText anchor;
    private Spinner apps;
    private Spinner actions;
    private final List<AgentAction> queued = new ArrayList<>();
    private TextView queueText;

    @Override protected void onCreate(Bundle savedState) {
        super.onCreate(savedState);
        setTitle("웹 검색 · 앱 작업");
        ui = new WorkspaceUi(this);
        LinearLayout root = ui.screen();
        LinearLayout heading = ui.row();
        ui.pad(heading, 18, 8);
        Button back = ui.button("뒤로", this::finish);
        heading.addView(back);
        TextView title = ui.text("웹 검색 · 앱 작업", 20, false);
        LinearLayout.LayoutParams headingTitle = new LinearLayout.LayoutParams(0, -2, 1);
        headingTitle.leftMargin = ui.dp(12);
        heading.addView(title, headingTitle);
        root.addView(heading);

        LinearLayout body = ui.column();
        ui.pad(body, 18, 8);
        ScrollView page = new ScrollView(this);
        page.setFillViewport(true);
        page.setVerticalScrollBarEnabled(false);
        page.addView(body);
        root.addView(page, new LinearLayout.LayoutParams(-1, 0, 1));
        setContentView(root);

        content = ui.card(body);
        label("웹 검색", 20);
        query = input("검색어");
        query.setTag("agent-search-query");
        Button search = button("검색 확인", this::reviewSearch);
        search.setTag("agent-search-review");
        ui.tone(search, true);

        content = ui.card(body);
        label("다른 앱에서 수행", 20);
        label("대상 앱", 14);
        apps = spinner(launchableApps());
        label("동작", 14);
        actions = spinner(List.of(AgentAction.Kind.values()));
        anchor = input("버튼 또는 카드의 정확한 이름");
        ui.tone(button("앱 작업 확인", this::reviewAction), true);
        button("단계 추가", this::addStep);
        button("단계 초기화", () -> {
            queued.clear();
            anchor.setText("");
            queueText.setText("");
        });
        queueText = label("", 14);
        button("TLA 앱 작업 접근성 설정", () -> open(new Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)));
        status = label("", 14);
    }

    @Override protected void onResume() {
        super.onResume();
        AppActionService.stop("TLA로 돌아와 앱 작업을 중단했습니다.");
        String latest = AppActionService.status();
        status.setText(!latest.isEmpty() ? latest
            : AppActionService.available() ? "앱 작업을 승인할 수 있습니다." : "앱 작업에는 접근성 설정이 필요합니다.");
    }

    private void reviewSearch() {
        confirmSearch(this, query.getText().toString(), status::setText);
    }

    static void confirmSearch(Activity activity, String query, Consumer<String> result) {
        try {
            String text = AgentAction.field(query, 256);
            Intent search = AgentAction.search(text);
            new AlertDialog.Builder(activity).setTitle("Google에서 검색")
                .setMessage("Google에 보낼 검색어\n\n" + text)
                .setNegativeButton("취소", (dialog, which) -> result.accept("검색을 취소했어요."))
                .setPositiveButton("검색", (dialog, which) -> {
                    try {
                        activity.startActivity(search);
                        result.accept("브라우저에서 검색을 열었어요.");
                    } catch (ActivityNotFoundException | SecurityException error) {
                        result.accept("검색을 열 수 있는 브라우저를 찾지 못했어요.");
                    }
                }).show();
        } catch (IllegalArgumentException error) {
            result.accept(error.getMessage());
        }
    }

    private void reviewAction() {
        if (!AppActionService.available()) {
            status.setText("접근성 설정에서 TLA 앱 작업을 켜 주세요.");
            return;
        }
        AppChoice choice = (AppChoice) apps.getSelectedItem();
        if (choice == null) {
            status.setText("실행할 앱을 찾지 못했습니다.");
            return;
        }
        try {
            List<AgentAction> steps = new ArrayList<>(queued);
            if (steps.isEmpty() || !anchor.getText().toString().isBlank()) steps.add(selectedAction(choice));
            validateSteps(steps, choice.packageName);
            List<AgentAction> plan = List.copyOf(steps);
            new AlertDialog.Builder(this).setTitle("앱 동작 승인")
                .setMessage(choice + "\n\n" + describe(plan) + "\n\n단계마다 최대 15초 동안 지정한 요소를 기다립니다.")
                .setNegativeButton("취소", null)
                .setPositiveButton(plan.size() == 1 ? "한 번 실행" : "단계 실행", (dialog, which) -> execute(plan)).show();
        } catch (IllegalArgumentException error) {
            status.setText(error.getMessage());
        }
    }

    private AgentAction selectedAction(AppChoice choice) {
        if (choice == null) throw new IllegalArgumentException("실행할 앱을 선택해 주세요.");
        return new AgentAction(choice.packageName, anchor.getText().toString(),
            (AgentAction.Kind) actions.getSelectedItem());
    }

    private void addStep() {
        try {
            AgentAction step = selectedAction((AppChoice) apps.getSelectedItem());
            List<AgentAction> steps = new ArrayList<>(queued);
            steps.add(step);
            validateSteps(steps, step.packageName);
            queued.add(step);
            anchor.setText("");
            queueText.setText(describe(queued));
        } catch (IllegalArgumentException error) {
            status.setText(error.getMessage());
        }
    }

    private static void validateSteps(List<AgentAction> steps, String target) {
        if (steps.size() > AppActionService.MAX_STEPS) {
            throw new IllegalArgumentException("한 번에 최대 " + AppActionService.MAX_STEPS + "단계까지 승인할 수 있습니다.");
        }
        if (steps.stream().anyMatch(step -> !target.equals(step.packageName))) {
            throw new IllegalArgumentException("단계는 같은 앱에서만 실행할 수 있습니다. 앱을 바꾸려면 단계를 초기화해 주세요.");
        }
    }

    private static String describe(List<AgentAction> steps) {
        List<String> lines = new ArrayList<>();
        for (int index = 0; index < steps.size(); index++) {
            AgentAction step = steps.get(index);
            lines.add((index + 1) + ". " + step.kind + " · " + step.label);
        }
        return String.join("\n", lines);
    }

    private void execute(List<AgentAction> plan) {
        Intent launch = getPackageManager().getLaunchIntentForPackage(plan.get(0).packageName);
        if (launch == null) {
            status.setText("선택한 앱을 열 수 없습니다.");
            return;
        }
        if (!AppActionService.begin(plan)) {
            status.setText("화면 잠금이나 진행 중인 작업 때문에 시작할 수 없습니다.");
            return;
        }
        if (!open(launch)) AppActionService.stop("선택한 앱을 열지 못해 중단했습니다.");
    }

    private boolean open(Intent intent) {
        try {
            startActivity(intent);
            return true;
        } catch (ActivityNotFoundException | SecurityException error) {
            status.setText("이 작업을 열 수 있는 앱을 찾지 못했습니다.");
            return false;
        }
    }

    private List<AppChoice> launchableApps() {
        Intent filter = new Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER);
        Set<String> seen = new HashSet<>();
        List<AppChoice> choices = new ArrayList<>();
        for (ResolveInfo info : getPackageManager().queryIntentActivities(filter, 0)) {
            String packageName = info.activityInfo.packageName;
            if (!getPackageName().equals(packageName) && seen.add(packageName)) {
                choices.add(new AppChoice(info.loadLabel(getPackageManager()).toString(), packageName));
            }
        }
        choices.sort(Comparator.comparing(choice -> choice.label, String.CASE_INSENSITIVE_ORDER));
        return choices;
    }

    private TextView label(String text, int size) {
        TextView view = ui.text(text, size, size <= 14);
        content.addView(view);
        return view;
    }

    private EditText input(String hint) {
        EditText view = new EditText(this);
        view.setHint(hint);
        view.setInputType(InputType.TYPE_CLASS_TEXT);
        view.setSingleLine(true);
        ui.field(view);
        content.addView(view);
        return view;
    }

    private Button button(String title, Runnable action) {
        Button view = ui.button(title, action);
        LinearLayout.LayoutParams item = new LinearLayout.LayoutParams(-1, -2);
        item.topMargin = ui.dp(8);
        content.addView(view, item);
        return view;
    }

    private <T> Spinner spinner(List<T> choices) {
        Spinner view = new Spinner(this);
        ArrayAdapter<T> adapter = new ArrayAdapter<>(this, android.R.layout.simple_spinner_item, choices);
        adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item);
        view.setAdapter(adapter);
        ui.selector(view);
        content.addView(view);
        return view;
    }

    private static final class AppChoice {
        final String label;
        final String packageName;
        AppChoice(String label, String packageName) {
            this.label = label;
            this.packageName = packageName;
        }
        @Override public String toString() { return label + " (" + packageName + ")"; }
    }
}
