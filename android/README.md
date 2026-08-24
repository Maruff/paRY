# paRY for Android

The paRY chat client on a phone: a WebView pointed at a paRY server.

## Status

**Written, never built.** The machine this was authored on has no JDK, no
Gradle and no Android SDK, so nothing here has been compiled, linted or run on
a device. What *has* been checked is everything that can be checked without a
toolchain: every XML file parses, every `@string`/`@color`/`@drawable`/`@xml`/
`@id` reference resolves to something that exists, every `R.*` in the Kotlin
resolves, and the Tamil strings carry the same format arguments as the English
ones. Expect the first `./gradlew assembleDebug` to still find something.

## Why it loads the client instead of bundling it

The APK does not carry a copy of `web/`. Answers come from the server — the
corpus, the index and the compiler all live there — so a bundled client would
gain nothing offline and could drift out of step with the protocol it speaks.
Loading it from the server means the two are always the same version, and there
is exactly one chat window to maintain across web, desktop and Android.

That changes when the Phase A model is small enough to run on the phone: the
assets get bundled and answers become local. The protocol does not change,
which is the reason for settling it before writing any client.

## Build

```bash
cd android
gradle wrapper          # once — the wrapper jar is not committed
./gradlew assembleDebug
```

Or open `android/` in Android Studio, which will offer to do both.

The versions in `gradle/libs.versions.toml` are deliberately conservative
combinations rather than the newest of each, because they could not be resolved
where they were written. Let Android Studio's upgrade assistant move them, and
raise `targetSdk` to whatever Play currently requires before publishing.

## Pointing it at a server

First run asks for an address. On the machine running paRY:

```bash
python -m paRY.serve --host 0.0.0.0
```

- **Emulator** → `http://10.0.2.2:8900` (the default offered), which is the
  emulator's name for the host's loopback
- **Real phone** → the machine's address on the network, `192.168.1.9:8900`

Typing a bare `host:port` is enough; `http://` is assumed, because a paRY
server is normally an internal host reached over plain HTTP. That is also why
`network_security_config.xml` permits cleartext — put the server behind TLS and
that file can be deleted.

The address is saved, and is the only thing this app stores.

## Decisions worth knowing

- **`namespace` is `org.etamil.pary`, `applicationId` is `in.etamil.pary`.**
  The reversed domain would be the natural package, but `in` is a hard keyword
  in Kotlin and a package declaration cannot use one without backticks. The
  applicationId is an identifier string rather than a package, so it keeps the
  real domain.
- **Navigation is confined to the configured server.** Anything else opens in a
  browser rather than inside the app's WebView.
- **`configChanges` includes `uiMode`**, so a system theme flip does not restart
  the activity and throw the conversation away. The trade is that the page's
  colours may lag until it next loads.
- **No `@JavascriptInterface`.** The WebView is given no bridge into the app,
  so there is no surface for a page to reach Android through.
- The one WebView-specific fix already lives in the web client: 
  `scrollIntoView({behavior: "smooth"})` silently does nothing in an embedded
  WebView, which is why the transcript sets `scrollTop` directly.
