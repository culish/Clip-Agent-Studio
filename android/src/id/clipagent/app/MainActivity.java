package id.clipagent.app;

import android.Manifest;
import android.app.Activity;
import android.app.DownloadManager;
import android.content.ActivityNotFoundException;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.content.res.Configuration;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.view.View;
import android.view.ViewGroup;
import android.webkit.CookieManager;
import android.webkit.DownloadListener;
import android.webkit.JavascriptInterface;
import android.webkit.URLUtil;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;
import android.widget.Toast;

import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Clip Agent untuk Android: remote untuk Clip Agent yang berjalan di laptop (Wi-Fi yang sama).
 * - Menampilkan web app Clip Agent dari laptop di WebView.
 * - Menerima link yang dibagikan dari YouTube (Bagikan -> Clip Agent).
 * - Menyimpan klip ke folder Download/ClipAgent lewat DownloadManager.
 * - Memasangkan HP lewat tautan clipagent://pair?server=...&code=... (dari QR di laptop).
 */
public class MainActivity extends Activity {
    static final String VERSION = "1.0";
    private static final String PREFS = "clipagent";
    private static final String CONNECT_PAGE = "file:///android_asset/connect.html";
    private static final int REQ_STORAGE = 7;
    private static final int DEFAULT_PORT = 8765;
    private static final Pattern URL_RE = Pattern.compile("https?://[^\\s\"'<>]+");
    private static final Pattern FILENAME_RE = Pattern.compile("filename\\*?=(?:UTF-8'')?\"?([^\";]+)\"?",
            Pattern.CASE_INSENSITIVE);

    private WebView web;
    private FrameLayout root;
    private SharedPreferences prefs;
    private String pendingSource;
    private View customView;
    private WebChromeClient.CustomViewCallback customCallback;
    private String[] pendingDownload;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        prefs = getSharedPreferences(PREFS, MODE_PRIVATE);
        root = new FrameLayout(this);
        web = new WebView(this);
        root.addView(web, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        setContentView(root);

        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setMediaPlaybackRequiresUserGesture(true);
        s.setUserAgentString(s.getUserAgentString() + " ClipAgentApp/" + VERSION);
        CookieManager.getInstance().setAcceptCookie(true);

        web.setWebViewClient(new Client());
        web.setWebChromeClient(new Chrome());
        web.setDownloadListener(new DownloadListener() {
            @Override
            public void onDownloadStart(String url, String userAgent, String disposition, String mime, long length) {
                onDownload(url, disposition, mime);
            }
        });
        web.addJavascriptInterface(new Bridge(), "ClipAgentApp");
        handleIntent(getIntent());
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        handleIntent(intent);
    }

    // ------------------------------------------------------------------ navigasi
    private void handleIntent(Intent intent) {
        if (intent != null) {
            String action = intent.getAction();
            if (Intent.ACTION_SEND.equals(action)) {
                String text = intent.getStringExtra(Intent.EXTRA_TEXT);
                String url = findUrl(text);
                if (url != null) {
                    pendingSource = url;
                } else if (text != null) {
                    toast("Tidak ada link di teks yang dibagikan.");
                }
            } else if (Intent.ACTION_VIEW.equals(action) && intent.getData() != null
                    && "clipagent".equals(intent.getData().getScheme())) {
                Uri d = intent.getData();
                String server = normalizeServer(d.getQueryParameter("server"));
                String code = d.getQueryParameter("code");
                if (server != null && code != null && !code.trim().isEmpty()) {
                    saveServer(server, code.trim());
                    toast("Terhubung ke " + display(server));
                }
            }
        }
        route();
    }

    /** Buka web app di laptop (lewat /connect agar cookie akses selalu segar). */
    private void route() {
        String server = prefs.getString("server", null);
        String code = prefs.getString("code", null);
        if (server == null || code == null) {
            showConnect(null);
            return;
        }
        String next = "/";
        if (pendingSource != null) {
            next = "/#studio?source=" + Uri.encode(pendingSource);
            pendingSource = null;
        }
        web.loadUrl(server + "/connect?code=" + Uri.encode(code) + "&next=" + Uri.encode(next));
    }

    private void showConnect(String error) {
        StringBuilder url = new StringBuilder(CONNECT_PAGE)
                .append("?server=").append(Uri.encode(display(prefs.getString("server", ""))))
                .append("&code=").append(Uri.encode(prefs.getString("code", "")));
        if (error != null) url.append("&error=").append(Uri.encode(error));
        if (pendingSource != null) url.append("&pending=1");
        web.loadUrl(url.toString());
    }

    private void saveServer(String server, String code) {
        prefs.edit().putString("server", server).putString("code", code).apply();
    }

    private boolean handleNav(Uri u) {
        String scheme = u.getScheme();
        if (scheme == null || "file".equals(scheme) || "about".equals(scheme)) return false;
        if ("clipagent".equals(scheme)) {
            handleIntent(new Intent(Intent.ACTION_VIEW, u));
            return true;
        }
        if ("intent".equals(scheme)) {
            try {
                Intent i = Intent.parseUri(u.toString(), Intent.URI_INTENT_SCHEME);
                Uri data = i.getData();
                if (data != null && "clipagent".equals(data.getScheme())) {
                    handleIntent(new Intent(Intent.ACTION_VIEW, data));
                }
            } catch (Exception ignored) {
                // tautan intent tidak valid: abaikan
            }
            return true;
        }
        String server = prefs.getString("server", "");
        if (("http".equals(scheme) || "https".equals(scheme)) && !server.isEmpty()) {
            Uri su = Uri.parse(server);
            if (su.getHost() != null && su.getHost().equalsIgnoreCase(u.getHost()) && portOf(su) == portOf(u)) {
                return false;   // halaman Clip Agent: tetap di aplikasi
            }
        }
        try {
            startActivity(new Intent(Intent.ACTION_VIEW, u));   // YouTube, berita, dll.
        } catch (ActivityNotFoundException e) {
            toast("Tidak ada aplikasi untuk membuka tautan ini.");
        }
        return true;
    }

    class Client extends WebViewClient {
        @Override
        public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
            return handleNav(request.getUrl());
        }

        @Override
        public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
            if (request.isForMainFrame() && !"file".equals(request.getUrl().getScheme())) {
                showConnect("Laptop tidak bisa dihubungi (" + error.getDescription() + "). Pastikan Clip Agent "
                        + "berjalan, Akses dari HP aktif, dan HP memakai Wi-Fi yang sama dengan laptop.");
            }
        }
    }

    // ------------------------------------------------------------------ jembatan JavaScript
    class Bridge {
        @JavascriptInterface
        public void connect(final String server, final String code) {
            runOnUiThread(new Runnable() {
                @Override
                public void run() {
                    String current = web.getUrl();
                    if (current == null || !current.startsWith("file:///android_asset/")) return;
                    String norm = normalizeServer(server);
                    if (norm == null || code == null || code.trim().isEmpty()) {
                        showConnect("Isi alamat laptop dan kode akses.");
                        return;
                    }
                    saveServer(norm, code.trim());
                    route();
                }
            });
        }

        @JavascriptInterface
        public void changeServer() {
            runOnUiThread(new Runnable() {
                @Override
                public void run() {
                    showConnect(null);
                }
            });
        }

        @JavascriptInterface
        public void retry() {
            runOnUiThread(new Runnable() {
                @Override
                public void run() {
                    route();
                }
            });
        }

        @JavascriptInterface
        public String version() {
            return VERSION;
        }
    }

    // ------------------------------------------------------------------ unduhan
    private void onDownload(String url, String disposition, String mime) {
        String name = fileName(url, disposition, mime);
        if (Build.VERSION.SDK_INT < 29
                && checkSelfPermission(Manifest.permission.WRITE_EXTERNAL_STORAGE) != PackageManager.PERMISSION_GRANTED) {
            pendingDownload = new String[]{url, name, mime};
            requestPermissions(new String[]{Manifest.permission.WRITE_EXTERNAL_STORAGE}, REQ_STORAGE);
            return;
        }
        startDownload(url, name, mime);
    }

    private void startDownload(String url, String name, String mime) {
        try {
            DownloadManager.Request r = new DownloadManager.Request(Uri.parse(url));
            String cookie = CookieManager.getInstance().getCookie(url);
            if (cookie != null) r.addRequestHeader("Cookie", cookie);
            r.addRequestHeader("User-Agent", web.getSettings().getUserAgentString());
            r.setTitle(name);
            r.setDescription("Clip Agent");
            if (mime != null && !mime.isEmpty()) r.setMimeType(mime.split(";")[0].trim());
            r.setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED);
            r.setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, "ClipAgent/" + name);
            DownloadManager dm = (DownloadManager) getSystemService(Context.DOWNLOAD_SERVICE);
            dm.enqueue(r);
            toast("Mengunduh " + name + " ke Download/ClipAgent");
        } catch (Exception e) {
            toast("Gagal mengunduh: " + e.getMessage());
        }
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] results) {
        super.onRequestPermissionsResult(requestCode, permissions, results);
        if (requestCode == REQ_STORAGE && pendingDownload != null) {
            if (results.length > 0 && results[0] == PackageManager.PERMISSION_GRANTED) {
                startDownload(pendingDownload[0], pendingDownload[1], pendingDownload[2]);
            } else {
                toast("Izin penyimpanan dibutuhkan untuk menyimpan klip.");
            }
            pendingDownload = null;
        }
    }

    // ------------------------------------------------------------------ video layar penuh
    class Chrome extends WebChromeClient {
        @Override
        public void onShowCustomView(View view, CustomViewCallback callback) {
            if (customView != null) {
                callback.onCustomViewHidden();
                return;
            }
            customView = view;
            customCallback = callback;
            root.addView(view, new FrameLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
            web.setVisibility(View.GONE);
            getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_FULLSCREEN
                    | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION | View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY);
        }

        @Override
        public void onHideCustomView() {
            exitFullscreen();
        }
    }

    private void exitFullscreen() {
        if (customView == null) return;
        root.removeView(customView);
        customView = null;
        web.setVisibility(View.VISIBLE);
        if (customCallback != null) customCallback.onCustomViewHidden();
        customCallback = null;
        boolean night = (getResources().getConfiguration().uiMode & Configuration.UI_MODE_NIGHT_MASK)
                == Configuration.UI_MODE_NIGHT_YES;
        getWindow().getDecorView().setSystemUiVisibility(night ? 0 : View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR);
    }

    // ------------------------------------------------------------------ siklus hidup
    @Override
    public void onBackPressed() {
        if (customView != null) {
            exitFullscreen();
        } else if (web.canGoBack()) {
            web.goBack();
        } else {
            super.onBackPressed();
        }
    }

    @Override
    protected void onPause() {
        super.onPause();
        web.onPause();
        CookieManager.getInstance().flush();
    }

    @Override
    protected void onResume() {
        super.onResume();
        web.onResume();
    }

    @Override
    protected void onDestroy() {
        if (web != null) {
            root.removeView(web);
            web.destroy();
        }
        super.onDestroy();
    }

    // ------------------------------------------------------------------ utilitas
    static String findUrl(String text) {
        if (text == null) return null;
        Matcher m = URL_RE.matcher(text);
        String first = null;
        while (m.find()) {
            String u = m.group();
            if (u.contains("youtu")) return u;
            if (first == null) first = u;
        }
        return first;
    }

    static String normalizeServer(String s) {
        if (s == null) return null;
        s = s.trim();
        if (s.isEmpty()) return null;
        if (!s.startsWith("http://") && !s.startsWith("https://")) s = "http://" + s;
        Uri u = Uri.parse(s);
        String host = u.getHost();
        if (host == null || host.isEmpty()) return null;
        int port = u.getPort();
        if (port == -1) port = "https".equals(u.getScheme()) ? 443 : DEFAULT_PORT;
        return u.getScheme() + "://" + host + ":" + port;
    }

    static String display(String server) {
        if (server == null) return "";
        return server.replaceFirst("^https?://", "");
    }

    private static int portOf(Uri u) {
        if (u.getPort() != -1) return u.getPort();
        return "https".equals(u.getScheme()) ? 443 : 80;
    }

    private static String fileName(String url, String disposition, String mime) {
        if (disposition != null) {
            Matcher m = FILENAME_RE.matcher(disposition);
            if (m.find()) {
                String n = Uri.decode(m.group(1)).replaceAll("[\\\\/:*?\"<>|]", "_").trim();
                if (!n.isEmpty()) return n;
            }
        }
        return URLUtil.guessFileName(url, disposition, mime);
    }

    private void toast(String msg) {
        Toast.makeText(this, msg, Toast.LENGTH_LONG).show();
    }
}
