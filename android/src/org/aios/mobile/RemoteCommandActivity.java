package org.aios.mobile;

import android.app.AlertDialog;
import android.os.Bundle;
import android.util.Base64;
import java.nio.charset.StandardCharsets;

public final class RemoteCommandActivity extends MainActivity {
    @Override public void onCreate(Bundle saved) {
        super.onCreate(saved);
        String id = getIntent().getStringExtra("request_id");
        String payload = getIntent().getStringExtra("command_b64");
        if (!RemoteResults.valid(id) || payload == null || payload.length() > 4096) { finish(); return; }
        String command;
        try {
            command = new String(Base64.decode(payload, Base64.DEFAULT), StandardCharsets.UTF_8).strip();
            if (command.isEmpty() || command.length() > 400 || command.chars().anyMatch(Character::isISOControl)) {
                finish(); return;
            }
        } catch (IllegalArgumentException invalid) { finish(); return; }
        if (!RemoteResults.begin(id)) { finish(); return; }
        AlertDialog review = new AlertDialog.Builder(this).setTitle("PC에서 받은 요청")
            .setMessage(command)
            .setNegativeButton("취소", (dialog, which) -> cancel(id))
            .setPositiveButton("진행", (dialog, which) -> executeRemote(id, command))
            .create();
        review.setOnCancelListener(dialog -> cancel(id));
        review.show();
    }

    private void cancel(String id) {
        RemoteResults.update(id, "cancelled", "휴대폰에서 요청을 취소했어요.");
        finish();
    }
}
