# Brand Asset Map

Last updated: `2026-06-22`

## Brand hierarchy

Bankroll Kings should use three distinct asset roles:

1. `Master brand / marketing image`
2. `Site header / wordmark`
3. `Small icon / favicon / PWA icon`

These assets should look related, but they should not all try to do the same job.

---

## 1. Master brand / marketing image

Primary asset:
- `static/brand-bk-lion.png`
- `static/brand-bk-lion.webp`

Role:
- Play Store feature graphic source
- social preview image
- marketing banners
- splash / hero brand storytelling

Reason:
- the lion is the emotional centerpiece of the brand
- this asset is too detailed for favicon or tiny header usage

---

## 2. Site header

The top bar is assembled from two pieces, NOT a single baked image:
- icon: `static/brand-bk-mark.webp` (the BRK symbol)
- name: the word "BANKROLL KINGS" as live, bold, solid-white CSS text

Reason:
- a stacked crown+BRK+BANKROLL KINGS lockup renders the name at ~8px in a nav
  bar — illegible. Live text stays crisp and readable at every size, scales on
  mobile, and can be restyled without re-exporting art.
- the full wordmark lockup (`static/brand-bk-logo.*`) is reserved for the
  Organization schema logo and general lockup/marketing use, NOT the nav bar.

---

## 3. Small icon / favicon / PWA icon

Primary asset source:
- `static/brand-bk-mark.png`
- `static/brand-bk-mark.webp`

Generated outputs:
- `static/favicon.png`
- `static/icons/icon-180.png`
- `static/icons/icon-192.png`
- `static/icons/icon-512.png`
- `static/icons/icon-1024.png`
- `static/icons/icon-maskable-192.png`
- `static/icons/icon-maskable-512.png`

Role:
- browser favicon
- Chrome shortcut / installed PWA icon
- Android app icon base
- Apple touch icon

Reason:
- the simplified crowned BRK mark stays recognizable at small size
- full lion art should not be used for tiny icon surfaces

---

## Current surface mapping

### Authenticated site shell
- header: `static/brand-bk-mark.webp` (BRK icon) + live white "BANKROLL KINGS" text

### Public site shell
- header: `static/brand-bk-mark.webp` (BRK icon) + live white "BANKROLL KINGS" text

### Search / favicon / installed app icon
- favicon: `static/favicon.png`
- manifest icons: `static/icons/*`

### Social preview
- `og:image`: `static/brand-bk-lion.png`
- `twitter:image`: `static/brand-bk-lion.png`

### Structured organization logo
- schema logo: `static/brand-bk-logo.png`

Reason:
- social cards should sell the brand
- search / schema should stay cleaner and more logo-like

---

## Guardrails

- Do not use the full lion image as the favicon.
- Do not use the `.com` logo variant as the main site header.
- Do not mix unrelated icon styles back into the shell without replacing the whole icon family intentionally.
- If the logo changes again, regenerate `favicon.png` and every file under `static/icons/` from `brand-bk-mark.png`.

---

## If the brand evolves later

If a new lion or wordmark is approved:

1. replace the source asset
2. export PNG + WebP versions into `static/`
3. regenerate favicon and manifest icons from the simplified mark
4. bump cache strings in:
   - `templates/bk_base.html`
   - `templates/public_base.html`
   - `static/service-worker.js`
