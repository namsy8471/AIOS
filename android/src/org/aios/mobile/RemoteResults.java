package org.aios.mobile;

import android.content.ContentProvider;
import android.content.ContentValues;
import android.database.Cursor;
import android.database.MatrixCursor;
import android.net.Uri;
import android.os.Handler;
import android.os.Looper;
import android.util.Base64;
import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;
import java.util.UUID;
import java.util.function.Consumer;

public final class RemoteResults extends ContentProvider {
    private static final class Entry {
        final String state;
        final String reply;
        final String token;
        final Consumer<Boolean> decision;

        Entry(String state, String reply, String token, Consumer<Boolean> decision) {
            this.state = state;
            this.reply = reply;
            this.token = token;
            this.decision = decision;
        }
    }

    private static final LinkedHashMap<String, Entry> requests = new LinkedHashMap<>();

    static boolean valid(String id) { return id != null && id.matches("[a-f0-9]{32}"); }

    static synchronized boolean begin(String id) {
        if (requests.containsKey(id)) return false;
        if (requests.size() >= 32) requests.remove(requests.keySet().iterator().next());
        requests.put(id, new Entry("pending", "", "", null));
        return true;
    }

    static synchronized void update(String id, String state, String reply) {
        if (requests.containsKey(id)) requests.put(id, new Entry(state, reply, "", null));
    }

    static synchronized void offer(String id, String description, Consumer<Boolean> decision) {
        if (!requests.containsKey(id)) return;
        String token = UUID.randomUUID().toString().replace("-", "");
        requests.put(id, new Entry("proposal", description, token, decision));
    }

    private static synchronized Entry find(String id) { return requests.get(id); }

    private static synchronized Consumer<Boolean> take(String id, String token) {
        Entry item = requests.get(id);
        if (item == null || item.decision == null || !item.token.equals(token)) return null;
        update(id, "accepted", "다음 화면을 확인하고 있어요.");
        return item.decision;
    }

    @Override public boolean onCreate() { return true; }

    @Override public Cursor query(Uri uri, String[] projection, String selection, String[] args, String sort) {
        MatrixCursor cursor = new MatrixCursor(new String[] {"state", "reply_b64", "token"});
        if (uri.getPathSegments().size() == 1 && valid(uri.getLastPathSegment())) {
            Entry item = find(uri.getLastPathSegment());
            if (item != null) {
                String encoded = Base64.encodeToString(item.reply.getBytes(StandardCharsets.UTF_8), Base64.NO_WRAP);
                cursor.addRow(new String[] {item.state, encoded, item.token});
            }
        }
        return cursor;
    }

    @Override public String getType(Uri uri) { return null; }
    @Override public Uri insert(Uri uri, ContentValues values) { throw new UnsupportedOperationException(); }
    @Override public int update(Uri uri, ContentValues values, String selection, String[] args) {
        String id = uri.getLastPathSegment();
        if (uri.getPathSegments().size() != 1 || !valid(id) || values == null) return 0;
        String token = values.getAsString("token");
        String decision = values.getAsString("decision");
        if (!valid(token) || !("approve".equals(decision) || "stop".equals(decision))) return 0;
        Consumer<Boolean> callback = take(id, token);
        if (callback == null) return 0;
        new Handler(Looper.getMainLooper()).post(() -> callback.accept("approve".equals(decision)));
        return 1;
    }
    @Override public int delete(Uri uri, String selection, String[] args) { throw new UnsupportedOperationException(); }
}
