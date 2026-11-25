package org.aios.mobile;

import android.content.ContentProvider;
import android.content.ContentValues;
import android.database.Cursor;
import android.database.MatrixCursor;
import android.net.Uri;
import android.util.Base64;
import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;

public final class RemoteResults extends ContentProvider {
    private static final LinkedHashMap<String, String[]> requests = new LinkedHashMap<>();

    static boolean valid(String id) { return id != null && id.matches("[a-f0-9]{32}"); }

    static synchronized boolean begin(String id) {
        if (requests.containsKey(id)) return false;
        if (requests.size() >= 32) requests.remove(requests.keySet().iterator().next());
        requests.put(id, new String[] {"pending", ""});
        return true;
    }

    static synchronized void update(String id, String state, String reply) {
        if (requests.containsKey(id)) requests.put(id, new String[] {state, reply});
    }

    private static synchronized String[] find(String id) { return requests.get(id); }

    @Override public boolean onCreate() { return true; }

    @Override public Cursor query(Uri uri, String[] projection, String selection, String[] args, String sort) {
        MatrixCursor cursor = new MatrixCursor(new String[] {"state", "reply_b64"});
        if (uri.getPathSegments().size() == 1 && valid(uri.getLastPathSegment())) {
            String[] item = find(uri.getLastPathSegment());
            if (item != null) {
                String encoded = Base64.encodeToString(item[1].getBytes(StandardCharsets.UTF_8), Base64.NO_WRAP);
                cursor.addRow(new String[] {item[0], encoded});
            }
        }
        return cursor;
    }

    @Override public String getType(Uri uri) { return null; }
    @Override public Uri insert(Uri uri, ContentValues values) { throw new UnsupportedOperationException(); }
    @Override public int update(Uri uri, ContentValues values, String selection, String[] args) { throw new UnsupportedOperationException(); }
    @Override public int delete(Uri uri, String selection, String[] args) { throw new UnsupportedOperationException(); }
}
