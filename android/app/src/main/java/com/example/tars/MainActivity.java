package com.example.tars;

import android.Manifest;
import android.app.Activity;
import android.content.pm.PackageManager;
import android.graphics.drawable.ColorDrawable;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.speech.tts.TextToSpeech;
import android.speech.tts.UtteranceProgressListener;
import android.util.Log;
import android.view.Gravity;
import android.view.View;
import android.view.WindowInsets;
import android.view.WindowInsetsController;
import android.webkit.JavascriptInterface;
import android.webkit.PermissionRequest;
import android.webkit.WebChromeClient;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;
import android.widget.TextView;

import com.chaquo.python.PyObject;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;

import java.io.IOException;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.Locale;

public class MainActivity extends Activity {

    private static final int MAX_WAIT_MS = 10_000;
    private static final int POLL_INTERVAL_MS = 200;
    private static final int REQ_RECORD_AUDIO = 1;

    private static volatile boolean serverStarted = false;
    private static volatile int serverPort = 0;
    private static volatile String bootNonce = "";
    private static volatile boolean bootLoaded = false;

    private WebView webView;
    private TextToSpeech tts;
    private boolean ttsReady;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        FrameLayout root = new FrameLayout(this);
        webView = new WebView(this);
        root.addView(webView, new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT));

        TextView loading = new TextView(this);
        loading.setText("TARS d\u00e9marre\u2026");
        loading.setGravity(Gravity.CENTER);
        loading.setId(1);
        root.addView(loading, new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT));

        getWindow().setBackgroundDrawable(new ColorDrawable(0xFFFAFAFA));
        root.setBackgroundColor(0xFFFAFAFA);
        setContentView(root);

        final int basePadLeft = root.getPaddingLeft();
        final int basePadTop = root.getPaddingTop();
        final int basePadRight = root.getPaddingRight();
        final int basePadBottom = root.getPaddingBottom();
        root.setOnApplyWindowInsetsListener((v, insets) -> {
            int left;
            int top;
            int right;
            int bottom;
            if (Build.VERSION.SDK_INT >= 30) {
                android.graphics.Insets bars = insets.getInsets(
                        WindowInsets.Type.systemBars() | WindowInsets.Type.displayCutout());
                left = bars.left;
                top = bars.top;
                right = bars.right;
                bottom = bars.bottom;
            } else {
                left = insets.getSystemWindowInsetLeft();
                top = insets.getSystemWindowInsetTop();
                right = insets.getSystemWindowInsetRight();
                bottom = insets.getSystemWindowInsetBottom();
            }
            v.setPadding(basePadLeft + left, basePadTop + top,
                    basePadRight + right, basePadBottom + bottom);
            return insets;
        });
        root.requestApplyInsets();

        if (Build.VERSION.SDK_INT >= 30) {
            WindowInsetsController controller = getWindow().getInsetsController();
            if (controller != null) {
                int mask = WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS
                        | WindowInsetsController.APPEARANCE_LIGHT_NAVIGATION_BARS;
                controller.setSystemBarsAppearance(mask, mask);
            }
        } else {
            getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR);
        }

        requestAudioPermission();
        configureWebView();
        initTts();

        new Thread(() -> {
            startServer();

            if (serverPort > 0 && waitForServer(MAX_WAIT_MS)) {
                final String url = baseUrl() + (bootLoaded ? "/" : "/?boot=" + Uri.encode(bootNonce));
                bootLoaded = true;
                runOnUiThread(() -> {
                    root.removeView(loading);
                    webView.loadUrl(url);
                });
            } else {
                runOnUiThread(() -> loading.setText("TARS n'a pas r\u00e9pondu. Relance l'application."));
            }
        }).start();
    }

    private synchronized void startServer() {
        if (serverStarted && serverPort > 0) {
            return;
        }
        try {
            if (!Python.isStarted()) {
                Python.start(new AndroidPlatform(getApplicationContext()));
            }
            PyObject tarsMain = Python.getInstance().getModule("tars_main");
            serverPort = tarsMain.callAttr("start").toInt();
            bootNonce = tarsMain.callAttr("get_boot_nonce").toString();
            serverStarted = true;
        } catch (Exception e) {
            Log.e("TARS", "Echec du demarrage du serveur Python", e);
        }
    }

    private static String baseUrl() {
        return "http://127.0.0.1:" + serverPort;
    }

    private void requestAudioPermission() {
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, REQ_RECORD_AUDIO);
        }
    }

    private void configureWebView() {
        if (BuildConfig.DEBUG) {
            WebView.setWebContentsDebuggingEnabled(true);
        }

        WebViewClient client = new WebViewClient();
        webView.setWebViewClient(client);

        webView.setWebChromeClient(new WebChromeClient() {
            @Override
            public void onPermissionRequest(final PermissionRequest request) {
                runOnUiThread(() -> {
                    boolean wantsAudio = false;
                    for (String resource : request.getResources()) {
                        if (PermissionRequest.RESOURCE_AUDIO_CAPTURE.equals(resource)) {
                            wantsAudio = true;
                            break;
                        }
                    }
                    if (wantsAudio) {
                        request.grant(request.getResources());
                    } else {
                        request.deny();
                    }
                });
            }
        });

        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setMediaPlaybackRequiresUserGesture(false);
        settings.setAllowFileAccess(false);
        settings.setJavaScriptCanOpenWindowsAutomatically(false);

        webView.addJavascriptInterface(new NativeTtsBridge(), "NativeTTS");
    }

    private void initTts() {
        releaseTts();
        final TextToSpeech[] holder = new TextToSpeech[1];
        holder[0] = new TextToSpeech(getApplicationContext(), status -> {
            final TextToSpeech engine = holder[0];
            if (status == TextToSpeech.SUCCESS && engine != null) {
                int result = engine.setLanguage(Locale.FRENCH);
                if (result == TextToSpeech.LANG_MISSING_DATA
                        || result == TextToSpeech.LANG_NOT_SUPPORTED) {
                    engine.setLanguage(Locale.getDefault());
                }
                engine.setSpeechRate(0.98f);
                engine.setPitch(1.0f);
                engine.setOnUtteranceProgressListener(new UtteranceProgressListener() {
                    @Override
                    public void onStart(String utteranceId) {
                    }

                    @Override
                    public void onDone(String utteranceId) {
                        notifyTtsDone(utteranceId);
                    }

                    @Override
                    public void onError(String utteranceId) {
                        notifyTtsDone(utteranceId);
                    }

                    @Override
                    public void onError(String utteranceId, int errorCode) {
                        notifyTtsDone(utteranceId);
                    }
                });
                synchronized (MainActivity.this) {
                    tts = engine;
                    ttsReady = true;
                }
            } else {
                Log.e("TARS", "TextToSpeech init echec: " + status);
                if (engine != null) {
                    engine.shutdown();
                    holder[0] = null;
                }
            }
        });
    }

    private synchronized void releaseTts() {
        if (tts != null) {
            try {
                tts.stop();
                tts.shutdown();
            } catch (Exception ignored) {
            }
            tts = null;
        }
        ttsReady = false;
    }

    private void notifyTtsDone(final String utteranceId) {
        if (utteranceId == null) {
            return;
        }
        final String safeId = utteranceId.replace("\\", "\\\\").replace("'", "\\'");
        runOnUiThread(() -> {
            if (webView != null) {
                webView.evaluateJavascript(
                        "window.onNativeTTSDone && window.onNativeTTSDone('" + safeId + "')", null);
            }
        });
    }

    private class NativeTtsBridge {

        @JavascriptInterface
        public void speak(String text, String id) {
            if (text == null || text.isEmpty()) {
                return;
            }
            final String utteranceId = id == null ? "" : id;
            runOnUiThread(() -> {
                final TextToSpeech engine;
                synchronized (MainActivity.this) {
                    engine = tts;
                    if (engine == null || !ttsReady) {
                        notifyTtsDone(utteranceId);
                        return;
                    }
                }
                engine.speak(text, TextToSpeech.QUEUE_ADD, null, utteranceId);
            });
        }

        @JavascriptInterface
        public void setVoice(float pitch, float rate) {
            final float p = Math.max(0.1f, Math.min(2.0f, pitch));
            final float r = Math.max(0.5f, Math.min(2.0f, rate));
            runOnUiThread(() -> {
                final TextToSpeech engine;
                synchronized (MainActivity.this) {
                    engine = tts;
                }
                if (engine != null) {
                    engine.setPitch(p);
                    engine.setSpeechRate(r);
                }
            });
        }

        @JavascriptInterface
        public void stop() {
            runOnUiThread(() -> {
                final TextToSpeech engine;
                synchronized (MainActivity.this) {
                    engine = tts;
                }
                if (engine != null) {
                    engine.stop();
                }
            });
        }
    }

    private boolean waitForServer(int maxWaitMs) {
        long deadline = System.currentTimeMillis() + maxWaitMs;
        while (System.currentTimeMillis() < deadline) {
            try {
                HttpURLConnection conn = (HttpURLConnection) new URL(baseUrl() + "/health").openConnection();
                conn.setConnectTimeout(500);
                conn.setReadTimeout(500);
                int code = conn.getResponseCode();
                conn.disconnect();
                if (code == 200) {
                    return true;
                }
            } catch (IOException ignored) {
            }
            try {
                Thread.sleep(POLL_INTERVAL_MS);
            } catch (InterruptedException e) {
                return false;
            }
        }
        return false;
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        // Rien a relancer : le WebChromeClient accorde l'acces micro quand la page le demande.
    }

    @Override
    public void onBackPressed() {
        if (webView != null && webView.canGoBack()) {
            webView.goBack();
        } else {
            super.onBackPressed();
        }
    }

    @Override
    protected void onDestroy() {
        releaseTts();
        super.onDestroy();
    }
}
