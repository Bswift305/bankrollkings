# Publishing Bankroll Kings to the Google Play Store (Android)

The site is already an installable PWA, so the Android app is a **TWA** (Trusted
Web Activity) — a thin native wrapper that runs the live site full-screen. No
separate codebase, no rewrite. iOS is documented separately (needs a Mac).

## What's already done (in this repo)
- ✅ PWA manifest with PNG icons (`/static/icons/icon-{192,512}.png` + maskable),
  `display: standalone`, name, shortcuts.
- ✅ Service worker registered on all pages (public + authenticated).
- ✅ App icons generated from the BK crowned monogram (`static/brand-bk-mark.png`
  is the reusable source; `static/icons/` holds the sized PNGs).
- ✅ Digital Asset Links endpoint live at `/.well-known/assetlinks.json`
  (route in `app.py`, file at `static/well-known/assetlinks.json`) — **fingerprint
  is a placeholder; fill it in at step 4.**

## One-time prerequisites (yours — needs your identity + payment)
1. **Google Play Console account** — https://play.google.com/console — **$25 one-time**.
2. A **privacy policy URL** (Play requires one). A page on bankrollkings.com is fine.

## Step-by-step

### 1. Generate the Android package (no local Android tooling needed)
Use **PWABuilder** (Microsoft, free): https://www.pwabuilder.com
- Enter `https://bankrollkings.com`, let it analyze the manifest.
- Package For Stores → **Android** → **Google Play**.
- Set **Package ID** to `com.bankrollkings.app` (must match `assetlinks.json`).
- Download the package — it produces an **`.aab`** (upload to Play) and a
  `signing.keystore` + a `assetlinks.json` snippet (with your fingerprint).
- Keep the keystore + passwords SOMEWHERE SAFE — losing it means you can't ship
  updates. (Or use Play App Signing, see step 4.)

*(Alternative: `@bubblewrap/cli` if you prefer a local build with JDK + Android SDK.)*

### 2. Create the app in Play Console
- All apps → Create app → name "Bankroll Kings", type App, Free.
- Complete the required declarations (see step 5).

### 3. Upload the build
- Production (or Internal testing first — recommended) → Create release →
  upload the `.aab` from step 1.

### 4. Wire Digital Asset Links (removes the browser URL bar)
- In Play Console → **App integrity → App signing**, copy the
  **SHA-256 certificate fingerprint**.
- Paste it into `static/well-known/assetlinks.json`, replacing
  `REPLACE_WITH_SHA256_FINGERPRINT_FROM_PLAY_CONSOLE`.
- Deploy (git push → pull on prod → restart) and confirm
  https://bankrollkings.com/.well-known/assetlinks.json shows the real fingerprint.
- Verify with Google's tester:
  https://developers.google.com/digital-asset-links/tools/generator

### 5. Store listing assets + declarations
- **App icon**: 512×512 PNG → use `static/icons/icon-512.png`. ✅ ready.
- **Feature graphic**: 1024×500 PNG (marketing banner) — *needs to be made*.
- **Phone screenshots**: 2–8, min 320px side — capture the live app on a phone
  (dashboard, a prop board, pricing).
- **Short description** (≤80 chars) + **Full description**.
- **Category**: Sports (or Tools). **Content rating** questionnaire.
- **Data safety** form: declare what you collect (account email, payment via
  Stripe, usage). **Privacy policy URL** (required).
- **Target audience**: 18+ (betting-adjacent — keep it adults-only).

### 6. Gambling / betting declaration — READ
Bankroll Kings is sports-betting **analytics**, not a sportsbook (no wagering, no
real-money gaming in-app). In the Play Console content declarations, do **not**
declare it as a real-money gambling app, but **do** set the audience to 18+ and
describe it accurately as analytics/informational. Google is generally permissive
here; just be accurate and don't facilitate placing bets inside the app.

### 7. Submit → review
Google review is typically 1–7 days. Internal-testing track first lets you
install on your own device and confirm assetlinks/full-screen before going to
Production.

## After launch
- App updates: the app loads the live site, so **content/UI updates ship the
  instant you deploy the web app** — no new Play release needed. You only re-submit
  for changes to the native wrapper (package id, icons, permissions).

## iOS (later, needs a Mac)
Same PWABuilder flow → iOS package, but the final build/submit requires Xcode on
macOS + an Apple Developer account ($99/yr), and App Review is stricter (guideline
4.2 "minimum functionality" for web wrappers, and 5.3 gambling scrutiny — adding
native push notifications is the usual mitigation). Tackle once a Mac/cloud-Mac is
available.
