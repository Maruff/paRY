package org.etamil.pary

import android.annotation.SuppressLint
import android.content.Context
import android.content.Intent
import android.content.SharedPreferences
import android.net.Uri
import android.os.Bundle
import android.view.View
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import androidx.activity.OnBackPressedCallback
import androidx.appcompat.app.AppCompatActivity

/**
 * paRY on Android: the web client, loaded from the paRY server it talks to.
 *
 * The client is not bundled into the APK on purpose. Answers come from the
 * server — the corpus, the index and the compiler all live there — so an app
 * carrying its own copy of the client would gain nothing offline and could
 * drift out of step with the protocol it is speaking. Loading it from the
 * server means the client and the server are always the same version, and it
 * means there is exactly one copy of the chat window to maintain across the
 * web, desktop and Android surfaces.
 *
 * When the Phase A model is small enough to run on the phone, that changes:
 * the assets get bundled and the model answers locally. The protocol does not
 * change, which is the point of settling it first.
 */
class MainActivity : AppCompatActivity() {

    private lateinit var webView: WebView
    private lateinit var setupPanel: View
    private lateinit var serverField: EditText
    private lateinit var messageView: TextView

    private var server: String? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        webView = findViewById(R.id.web)
        setupPanel = findViewById(R.id.setup)
        serverField = findViewById(R.id.server)
        messageView = findViewById(R.id.message)

        configureWebView()

        findViewById<Button>(R.id.connect).setOnClickListener {
            connectTo(serverField.text.toString())
        }

        // Back walks the chat's own history before it leaves the app.
        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                if (setupPanel.visibility != View.VISIBLE && webView.canGoBack()) {
                    webView.goBack()
                } else {
                    finish()
                }
            }
        })

        val saved = preferences().getString(KEY_SERVER, null)
        if (saved == null) {
            serverField.setText(DEFAULT_SERVER)
            showSetup(getString(R.string.setup_prompt))
        } else {
            serverField.setText(saved)
            load(saved)
        }
    }

    @SuppressLint("SetJavaScriptEnabled")
    private fun configureWebView() {
        webView.settings.apply {
            // The page being run is paRY's own client, served by the server the
            // user pointed this at. It is a chat window: without JavaScript
            // there is no chat.
            javaScriptEnabled = true
            domStorageEnabled = true
            // Nothing here reads the filesystem, and the page has no reason to.
            allowFileAccess = false
            allowContentAccess = false
        }
        webView.webViewClient = object : WebViewClient() {

            /** Stay on the configured server; send anything else to a browser. */
            override fun shouldOverrideUrlLoading(
                view: WebView,
                request: WebResourceRequest,
            ): Boolean {
                val target = request.url
                if (target.host != null && target.host == Uri.parse(server ?: "").host) {
                    return false
                }
                startActivity(Intent(Intent.ACTION_VIEW, target))
                return true
            }

            override fun onReceivedError(
                view: WebView,
                request: WebResourceRequest,
                error: WebResourceError,
            ) {
                // A failed image is not a failed app; only the page itself
                // going missing is worth interrupting for.
                if (!request.isForMainFrame) return
                showSetup(getString(R.string.unreachable, server ?: "", error.description))
            }
        }
    }

    private fun connectTo(typed: String) {
        val url = normalise(typed)
        if (url == null) {
            messageView.text = getString(R.string.bad_address)
            return
        }
        preferences().edit().putString(KEY_SERVER, url).apply()
        load(url)
    }

    private fun load(url: String) {
        server = url
        setupPanel.visibility = View.GONE
        webView.visibility = View.VISIBLE
        webView.loadUrl(url)
    }

    private fun showSetup(message: String) {
        messageView.text = message
        setupPanel.visibility = View.VISIBLE
        webView.visibility = View.GONE
    }

    private fun preferences(): SharedPreferences =
        getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE)

    private companion object {
        const val PREFERENCES = "paRY"
        const val KEY_SERVER = "server"

        /** The emulator's name for the host machine's loopback. */
        const val DEFAULT_SERVER = "http://10.0.2.2:8900"

        /**
         * What someone types is an address, not a URL: `192.168.1.9:8900`.
         * Assume plain HTTP when no scheme is given, because the server this
         * reaches is usually one on the institution's own network.
         */
        fun normalise(typed: String): String? {
            val trimmed = typed.trim().trimEnd('/')
            if (trimmed.isEmpty()) return null
            val withScheme =
                if (trimmed.startsWith("http://") || trimmed.startsWith("https://")) trimmed
                else "http://$trimmed"
            return if (Uri.parse(withScheme).host.isNullOrEmpty()) null else withScheme
        }
    }
}
