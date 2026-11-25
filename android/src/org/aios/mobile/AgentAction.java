package org.aios.mobile;

import android.content.Intent;
import android.graphics.Path;
import android.graphics.Rect;
import android.net.Uri;
import android.view.accessibility.AccessibilityNodeInfo;
import android.accessibilityservice.GestureDescription;
import java.util.ArrayDeque;

final class AgentAction {
    enum Kind {
        CLICK("버튼 누르기"), LEFT("왼쪽으로 스와이프"), RIGHT("오른쪽으로 스와이프");

        final String label;
        Kind(String label) { this.label = label; }
        @Override public String toString() { return label; }
    }

    static final int MAX_NODES = 2000;
    final String packageName;
    final String label;
    final Kind kind;

    AgentAction(String packageName, String label, Kind kind) {
        this.packageName = packageName;
        this.label = field(label, 96);
        this.kind = kind;
    }

    static String field(String value, int limit) {
        String clean = value.strip();
        if (clean.isEmpty() || clean.length() > limit || clean.chars().anyMatch(Character::isISOControl)) {
            throw new IllegalArgumentException("한 줄에 1~" + limit + "자 이내로 입력해 주세요.");
        }
        return clean;
    }

    static Intent search(String query) {
        Uri url = new Uri.Builder().scheme("https").authority("www.google.com")
            .path("/search").appendQueryParameter("q", field(query, 256)).build();
        return new Intent(Intent.ACTION_VIEW, url).addCategory(Intent.CATEGORY_BROWSABLE);
    }

    boolean owns(AccessibilityNodeInfo node) {
        return node != null && packageName.contentEquals(node.getPackageName() == null ? "" : node.getPackageName());
    }

    boolean matchesLabel(AccessibilityNodeInfo node) {
        return label.contentEquals(node.getText() == null ? "" : node.getText())
            || label.contentEquals(node.getContentDescription() == null ? "" : node.getContentDescription());
    }

    AccessibilityNodeInfo match(AccessibilityNodeInfo root) {
        if (!owns(root)) return null;
        ArrayDeque<AccessibilityNodeInfo> stack = new ArrayDeque<>();
        stack.push(root);
        AccessibilityNodeInfo match = null;
        int visited = 0;
        while (!stack.isEmpty()) {
            AccessibilityNodeInfo node = stack.pop();
            if (++visited > MAX_NODES) throw new IllegalStateException("화면 요소가 너무 많습니다.");
            if (!owns(node) || !node.isVisibleToUser()) continue;
            if (matchesLabel(node)) {
                if (match != null) throw new IllegalStateException("같은 이름의 요소가 여러 개 있습니다.");
                match = node;
            }
            if (node.getChildCount() > MAX_NODES - visited - stack.size()) {
                throw new IllegalStateException("화면 요소가 너무 많습니다.");
            }
            for (int index = node.getChildCount() - 1; index >= 0; index--) {
                AccessibilityNodeInfo child = node.getChild(index, 0);
                if (child != null) stack.push(child);
            }
        }
        return match;
    }

    AccessibilityNodeInfo clickTarget(AccessibilityNodeInfo node) {
        if (node.isClickable() && node.isEnabled()) return node;
        AccessibilityNodeInfo parent = node.getParent(0);
        if (owns(parent) && parent.getWindowId() == node.getWindowId()
                && parent.isVisibleToUser() && parent.isEnabled() && parent.isClickable()) return parent;
        throw new IllegalStateException("이 요소는 접근성으로 누를 수 없습니다.");
    }

    GestureDescription swipe(AccessibilityNodeInfo node, Rect window, int displayId, float density) {
        Rect area = new Rect();
        node.getBoundsInScreen(area);
        if (!area.intersect(window) || area.width() < 96 * density || area.height() < 48 * density) {
            throw new IllegalStateException("스와이프할 수 있는 카드 영역을 확인하지 못했습니다.");
        }
        float left = area.left + area.width() * 0.2f;
        float right = area.right - area.width() * 0.2f;
        Path path = new Path();
        path.moveTo(kind == Kind.LEFT ? right : left, area.exactCenterY());
        path.lineTo(kind == Kind.LEFT ? left : right, area.exactCenterY());
        return new GestureDescription.Builder().setDisplayId(displayId)
            .addStroke(new GestureDescription.StrokeDescription(path, 0, 250)).build();
    }
}
