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
import java.util.Locale;
import java.util.Set;
import java.util.function.Consumer;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public final class AgentActivity extends Activity {
    private static final Pattern CHAT_CLICK = Pattern.compile(
        "^(.+?)\\s*에서\\s+(.+?)(?:\\s+버튼)?(?:을|를)?\\s+(?:눌러|클릭)(?:\\s*(?:해\\s*)?(?:줘|주세요))?[.!?]*$");
    private static final Pattern CHAT_OPEN = Pattern.compile(
        "^(.+?)(?:\\s+앱(?:을)?)?\\s+(?:열어|실행)(?:\\s*(?:해\\s*)?(?:줘|주세요))?[.!?]*$");
    private static final Pattern CHAT_TASK = Pattern.compile("^(.+?)\\s*에서\\s+(.+)$");
    private static final Pattern MASTER_DUEL_TASK = Pattern.compile(
        "^((?:유희왕\\s*)?마스터\\s*듀얼)\\s+(?=(?:일일\\s*)?(?:출석|출첵))(.+)$");
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
        apps = spinner(launchableApps(this));
        label("동작", 14);
        actions = spinner(List.of(AgentAction.Kind.values()));
        anchor = input("버튼·카드·화면 문구의 정확한 이름");
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
                .setMessage(choice + "\n\n" + describe(plan) + "\n\n화면 요소는 최대 15초, 승인 버튼은 최대 45초 기다립니다.")
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
        execute(this, plan, status::setText);
    }

    static boolean handleChatApp(Activity activity, String command, Consumer<String> reply) {
        Matcher request = CHAT_CLICK.matcher(command);
        boolean click = request.matches();
        if (!click) {
            request = CHAT_OPEN.matcher(command);
            if (!request.matches()) return false;
        }
        String label = click ? request.group(2).strip() : null;
        if (label != null && label.length() >= 2
                && ((label.startsWith("\"") && label.endsWith("\"")) || (label.startsWith("'") && label.endsWith("'")))) {
            label = label.substring(1, label.length() - 1);
        }
        offerChatApp(activity, request.group(1), label, false, reply);
        return true;
    }

    static void offerChatApp(Activity activity, String name, String actionLabel, boolean modelProposed, Consumer<String> reply) {
        resolveChatApp(activity, name, modelProposed && actionLabel == null, actionLabel == null,
            choice -> runChatApp(activity, choice, actionLabel, reply), reply);
    }

    static boolean handleScreenTask(Activity activity, String command, Consumer<String> reply) {
        Matcher request = CHAT_TASK.matcher(command);
        if (!request.matches()) {
            request = MASTER_DUEL_TASK.matcher(command);
            if (!request.matches()) return false;
        }
        String goal = request.group(2);
        resolveChatApp(activity, request.group(1), false, false, choice -> {
            if (!requireAccessibility(activity, reply)) return;
            boolean visual = ScreenVision.supports(choice.packageName, goal);
            ScreenVision vision = new ScreenVision(activity);
            MobileEngine engine = new MobileEngine(activity);
            boolean larger = !visual && engine.weights(true).isFile();
            if (visual && (!vision.installed() || android.os.Build.VERSION.SDK_INT < 34)) {
                reply.accept("게임 화면을 읽으려면 Android 14 이상과 화면 인식이 포함된 TLA가 필요해요.");
                return;
            }
            if (!(visual ? vision.ready() : engine.weights(larger).isFile())) {
                reply.accept(visual ? "도구 · 설정에서 화면 인식 모델과 이미지 인코더를 가져오면 게임 화면을 볼 수 있어요."
                    : "선택한 로컬 모델을 가져오면 앱 화면에서 다음 동작을 찾을 수 있어요.");
                return;
            }
            Intent launch = activity.getPackageManager().getLaunchIntentForPackage(choice.packageName);
            if (launch == null) {
                reply.accept("선택한 앱을 열 수 없어요.");
                return;
            }
            new AlertDialog.Builder(activity).setTitle("앱 화면 확인")
                .setMessage("‘" + choice.label + "’에서 ‘" + goal + "’에 필요한 버튼을 찾아볼까요?"
                    + (visual ? "\n이 앱의 화면을 캡처해 휴대폰의 로컬 모델로 판독합니다."
                        : larger ? "\n로컬 대형 모델로 화면을 확인합니다." : "\n로컬 경량 모델로 한 단계만 제안합니다."))
                .setNegativeButton("취소", null)
                .setPositiveButton("화면 확인", (dialog, which) -> {
                    if (!AppActionService.inspect(choice.packageName, goal, larger, reply)) {
                        reply.accept("화면 잠금이나 진행 중인 작업 때문에 시작할 수 없어요.");
                    } else if (!open(activity, launch, reply)) {
                        AppActionService.stop("앱을 열지 못했어요.");
                    }
                }).show();
        }, reply);
        return true;
    }

    private static void resolveChatApp(Activity activity, String name, boolean confirmExact, boolean opens,
            Consumer<AppChoice> selected, Consumer<String> reply) {
        try {
            String requestedName = AgentAction.field(name, 128);
            String alias = normalized(requestedName);
            List<AppChoice> matches = new ArrayList<>();
            List<AppChoice> installed = launchableApps(activity);
            for (AppChoice choice : installed) {
                if (normalized(choice.label).equalsIgnoreCase(alias)
                        || (choice.packageName.equals("jp.konami.masterduel")
                            && (alias.equals("마스터듀얼") || alias.equals("유희왕마스터듀얼")))) {
                    matches.add(choice);
                }
            }
            if (matches.size() == 1 && !confirmExact) {
                selected.accept(matches.get(0));
                return;
            }
            if (matches.isEmpty() && alias.length() >= 2) {
                String lower = alias.toLowerCase(Locale.ROOT);
                for (AppChoice choice : installed) {
                    if (normalized(choice.label).toLowerCase(Locale.ROOT).contains(lower)) matches.add(choice);
                }
            }
            if (matches.isEmpty()) {
                reply.accept("‘" + requestedName + "’은 설치된 앱에서 찾지 못했어요. 홈 화면에 표시된 앱 이름이 뭔가요?");
                return;
            }
            AlertDialog.Builder clarify = new AlertDialog.Builder(activity).setTitle("대상 앱 확인")
                .setNegativeButton("취소", null);
            if (matches.size() == 1) {
                AppChoice suggestion = matches.get(0);
                String question = "‘" + suggestion.label + "’ 앱을 말씀하신 건가요?";
                if (opens) question += " 맞으면 이 앱을 열게요.";
                clarify.setMessage(question)
                    .setPositiveButton(opens ? "맞아요, 열기" : "맞아요", (dialog, which) -> selected.accept(suggestion));
            } else {
                clarify.setItems(matches.stream().map(AppChoice::toString).toArray(String[]::new),
                    (dialog, which) -> selected.accept(matches.get(which)));
            }
            clarify.show();
        } catch (IllegalArgumentException error) {
            reply.accept(error.getMessage());
        }
    }

    private static void runChatApp(Activity activity, AppChoice choice, String label, Consumer<String> reply) {
        if (label == null) {
            Intent launch = activity.getPackageManager().getLaunchIntentForPackage(choice.packageName);
            if (launch != null && open(activity, launch, reply)) reply.accept(choice.label + "을 열었어요.");
            else if (launch == null) reply.accept("선택한 앱을 열 수 없습니다.");
            return;
        }
        if (!requireAccessibility(activity, reply)) return;
        try {
            AgentAction action = new AgentAction(choice.packageName, label, AgentAction.Kind.CLICK);
            new AlertDialog.Builder(activity).setTitle("앱 동작 승인")
                .setMessage(choice + "\n\n" + action.label + " 버튼을 한 번 누를까요?")
                .setNegativeButton("취소", (dialog, which) -> reply.accept("앱 작업을 취소했어요."))
                .setPositiveButton("한 번 실행", (dialog, which) -> execute(activity, List.of(action), reply))
                .show();
        } catch (IllegalArgumentException error) {
            reply.accept(error.getMessage());
        }
    }

    private static boolean requireAccessibility(Activity activity, Consumer<String> reply) {
        if (AppActionService.available()) return true;
        new AlertDialog.Builder(activity).setTitle("TLA 앱 작업 접근성 설정")
            .setMessage("다른 앱의 화면에서 작업하려면 Android 접근성 설정에서 TLA 앱 작업을 켜 주세요.")
            .setNegativeButton("취소", null)
            .setPositiveButton("설정 열기", (dialog, which) ->
                open(activity, new Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS), reply)).show();
        return false;
    }

    private static String normalized(String label) { return label.replaceAll("\\s+", ""); }

    private static void execute(Activity activity, List<AgentAction> plan, Consumer<String> reply) {
        Intent launch = activity.getPackageManager().getLaunchIntentForPackage(plan.get(0).packageName);
        if (launch == null) {
            reply.accept("선택한 앱을 열 수 없습니다.");
            return;
        }
        if (!AppActionService.begin(plan)) {
            reply.accept("화면 잠금이나 진행 중인 작업 때문에 시작할 수 없습니다.");
            return;
        }
        if (!open(activity, launch, reply)) AppActionService.stop("선택한 앱을 열지 못해 중단했습니다.");
    }

    private boolean open(Intent intent) {
        return open(this, intent, status::setText);
    }

    private static boolean open(Activity activity, Intent intent, Consumer<String> reply) {
        try {
            activity.startActivity(intent);
            return true;
        } catch (ActivityNotFoundException | SecurityException error) {
            reply.accept("이 작업을 열 수 있는 앱을 찾지 못했습니다.");
            return false;
        }
    }

    private static List<AppChoice> launchableApps(Activity activity) {
        Intent filter = new Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER);
        Set<String> seen = new HashSet<>();
        List<AppChoice> choices = new ArrayList<>();
        for (ResolveInfo info : activity.getPackageManager().queryIntentActivities(filter, 0)) {
            String packageName = info.activityInfo.packageName;
            if (!activity.getPackageName().equals(packageName) && seen.add(packageName)) {
                choices.add(new AppChoice(info.loadLabel(activity.getPackageManager()).toString(), packageName));
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
