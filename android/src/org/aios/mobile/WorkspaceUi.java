package org.aios.mobile;

import android.content.Context;
import android.content.res.ColorStateList;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.RippleDrawable;
import android.graphics.drawable.StateListDrawable;
import android.view.Gravity;
import android.view.WindowInsets;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.Spinner;
import android.widget.TextView;

final class WorkspaceUi {
    private static final int BACKGROUND = 0xff11141a;
    private static final int PANEL = 0xff191e26;
    private static final int BORDER = 0xff303a47;
    private static final int TEXT = 0xfff2f5f7;
    private static final int MUTED = 0xffb1bdca;
    private static final int ACCENT = 0xff9ae5cd;
    private static final int INK = 0xff112721;
    private final Context context;

    WorkspaceUi(Context context) { this.context = context; }

    int dp(int value) { return Math.round(value * context.getResources().getDisplayMetrics().density); }

    LinearLayout column() {
        LinearLayout layout = new LinearLayout(context);
        layout.setOrientation(LinearLayout.VERTICAL);
        return layout;
    }

    LinearLayout row() {
        LinearLayout layout = new LinearLayout(context);
        layout.setGravity(Gravity.CENTER_VERTICAL);
        return layout;
    }

    LinearLayout screen() {
        LinearLayout root = column();
        root.setBackgroundColor(BACKGROUND);
        root.setOnApplyWindowInsetsListener((view, insets) -> {
            android.graphics.Insets safe = insets.getInsets(WindowInsets.Type.systemBars() | WindowInsets.Type.ime());
            view.setPadding(safe.left, safe.top, safe.right, safe.bottom);
            return insets;
        });
        return root;
    }

    void pad(LinearLayout layout, int x, int y) {
        layout.setPadding(dp(x), dp(y), dp(x), dp(y));
    }

    LinearLayout card(LinearLayout parent) {
        LinearLayout card = column();
        card.setBackground(shape(PANEL, BORDER, 16));
        pad(card, 16, 12);
        LinearLayout.LayoutParams child = new LinearLayout.LayoutParams(-1, -2);
        child.topMargin = dp(12);
        parent.addView(card, child);
        return card;
    }

    TextView text(String value, int size, boolean muted) {
        TextView view = new TextView(context);
        view.setText(value);
        view.setTextSize(size);
        view.setTextColor(muted ? MUTED : TEXT);
        view.setPadding(0, dp(4), 0, dp(4));
        if (size >= 18) view.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        return view;
    }

    TextView bubble(String value, boolean user) {
        TextView view = text(value, 16, false);
        view.setTextIsSelectable(true);
        if (user) view.setBackground(shape(0xff233a37, 0xff31514a, 16));
        view.setPadding(dp(14), dp(10), dp(14), dp(10));
        return view;
    }

    Button button(String title, Runnable action) {
        Button view = new Button(context);
        view.setText(title);
        view.setTextSize(14);
        view.setAllCaps(false);
        view.setMinHeight(dp(48));
        view.setMinimumHeight(dp(48));
        view.setMinWidth(0);
        view.setPadding(dp(12), 0, dp(12), 0);
        view.setOnClickListener(clicked -> action.run());
        tone(view, false);
        return view;
    }

    void tone(Button button, boolean primary) {
        int fill = primary ? ACCENT : PANEL;
        int foreground = primary ? INK : TEXT;
        button.setTextColor(new ColorStateList(new int[][]{new int[]{-android.R.attr.state_enabled}, new int[]{}},
            new int[]{MUTED, foreground}));
        StateListDrawable surface = new StateListDrawable();
        surface.addState(new int[]{-android.R.attr.state_enabled}, shape(PANEL, BORDER, 12));
        surface.addState(new int[]{}, shape(fill, primary ? fill : BORDER, 12));
        button.setBackground(new RippleDrawable(ColorStateList.valueOf(primary ? 0x33214735 : 0x339ae5cd), surface, null));
    }

    Button composerAction(String glyph, String description, boolean primary, Runnable action) {
        Button button = button(glyph, action);
        button.setContentDescription(description);
        button.setTextSize(22);
        button.setPadding(0, 0, 0, 0);
        int color = primary ? ACCENT : PANEL;
        button.setTextColor(primary ? INK : TEXT);
        StateListDrawable surface = new StateListDrawable();
        surface.addState(new int[]{-android.R.attr.state_enabled}, shape(BORDER, BORDER, 24));
        surface.addState(new int[]{}, shape(color, primary ? color : BORDER, 24));
        button.setBackground(new RippleDrawable(ColorStateList.valueOf(0x339ae5cd), surface, null));
        return button;
    }

    void field(EditText input) {
        input.setBackground(shape(BACKGROUND, BORDER, 12));
        input.setTextColor(TEXT);
        input.setHintTextColor(MUTED);
        input.setTextSize(16);
        input.setMinHeight(dp(52));
        input.setPadding(dp(12), dp(10), dp(12), dp(10));
    }

    void selector(Spinner spinner) { spinner.setMinimumHeight(dp(48)); }

    void paired(LinearLayout row, Button left, Button right) {
        LinearLayout.LayoutParams first = new LinearLayout.LayoutParams(0, -2, 1);
        first.rightMargin = dp(8);
        row.addView(left, first);
        row.addView(right, new LinearLayout.LayoutParams(0, -2, 1));
    }

    private GradientDrawable shape(int fill, int border, int corner) {
        GradientDrawable shape = new GradientDrawable();
        shape.setColor(fill);
        shape.setStroke(dp(1), border);
        shape.setCornerRadius(dp(corner));
        return shape;
    }
}
