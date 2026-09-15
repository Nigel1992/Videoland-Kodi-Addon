<div align="center">

<img src="https://raw.githubusercontent.com/Nigel1992/Videoland-Kodi-Addon/master/icon.png" width="300" alt="Videoland Kodi Addon Logo"/>

# Videoland Kodi Addon

[![GitHub stars](https://img.shields.io/github/stars/Nigel1992/Videoland-Kodi-Addon?style=social)](https://github.com/Nigel1992/Videoland-Kodi-Addon)
[![License: CC BY-NC 4.0](https://img.shields.io/badge/License-CC%20BY--NC%204.0-lightgrey.svg)](LICENSE)

**Latest version:** v1.0.2 — 2026-09-15. See the [Changelog](CHANGELOG.md) or [Releases](https://github.com/Nigel1992/Videoland-Kodi-Addon/releases).

<sub>Unofficial Videoland Kodi Addon - Watch movies, series, programs, and more from Videoland directly in Kodi using your own subscription.</sub>

</div>

---

> ⚠️ **Warning:** This add-on is under constant development. Some features may be broken or incomplete. Please see the To-Do section below for known issues and planned improvements. Use at your own risk and check back for frequent updates!

---

## ✨ Features

- **Home Screen Rails**: The home page mirrors the official Videoland app, grouping content into the same titled rails/sections for a native feel.
- **Series**: Browse and play series with full season/episode navigation.
- **Movies**: Discover and watch movies from the Videoland catalog.
- **Programma's**: Browse programs and catch-up content.
- **Kids**: Dedicated kids content section.
- **Trending**: See what's trending right now.
- **Search**: Find series, movies, and programs by title.
- **Watchlist (Mijn Kijklijst)**: Access your saved content.
- **Profile Management**: Switch between user profiles from the Kodi UI.
- **Secure Credential Storage**: Email and password are encrypted with a device-bound key before they ever reach disk; sessions are stored encrypted and **auto-relogin** refreshes expired sessions silently.
- **Dialog-Based Login**: Credentials are entered once at login and never shown again in the add-on settings.
- **Main Menu Icons**: Flat, consistent, brand-styled icons for every main menu entry — including a teddy-bear Kids icon and dedicated profile/watchlist icons.
- **Collection & Genre Menus**: Series, Programma's, Kids, Home and catalogue folders share a consistent collection/genre submenu layout while keeping each page's own routes and section labels.
- **Per-Episode Details**: Episode lists show the real episode title and a per-episode synopsis, recovered from each episode's own page instead of relying on bare cards.
- **Hero Backgrounds**: Widescreen movie/show artwork from the title-page hero is used as the selected item's background throughout season and episode lists.
- **Category Breadcrumbs**: Every folder shows its readable navigation path (categories, genres, shows, seasons, home rails, search) instead of internal SEO names.
- **Account Tools**: An in-settings button clears saved credentials, session, selected profile and cached content; signing out and switching profiles are one click away.
- **Expired-Session Resilience**: Stale sessions (including Videoland's HTTP 498 token response) trigger a silent re-login and single retry.
- **DRM Support**: Widevine-protected DASH streams via `inputstream.adaptive`.

---

## 📺 Playback Quality & DRM (important)

Stream resolution is determined by your device's **Widevine security level** — the add-on cannot increase it beyond what the DRM grants to the device.

| Device type | Widevine level | Typical Videoland quality |
|---|---|---|
| **L1 (hardware-backed)** — certified Android TV boxes, NVIDIA Shield, Amazon Fire TV, many Chromebooks, select Android phones | L1 | **Up to Full HD / HDR** where the service provides it |
| **L3 (software)** — e.g. **Raspberry Pi 5**, many LibreELEC/PC/software-CDM setups | L3 | **540p (SD)** — Videoland only issues SD keys to software-only security |

**Why 540p?** Videoland's DRM (Widevine via DRMtoday) refuses to emit HD/UHD content keys to devices running a **software (L3)** Widevine security level. On such devices — including most Raspberry Pi and general-purpose LibreELEC hardware — playback is capped at **540p**. This is a provider-side DRM restriction, not something the add-on can bypass.

**About the quality setting:** The add-on offers a *Preferred quality* setting:
- **Software L3 (default)** — reliably decodes on devices like the Pi 5 (`CDM "kNoKey"` failures on the L1 rendition are avoided).
- **Best available (DASH)** — selects the highest stream reported, but the resolution is **still bounded by the Widevine security level**. On an **L1** device this is where you get Full HD/HDR; on an L3 device you'll still see 540p.

> 💡 **Tip:** For Full HD/HDR, use a Kodi device with **L1 (hardware-backed) Widevine** and set *Preferred quality* to **Best available (DASH)**.

This add-on does **not** bypass DRM or subscription checks; it simply plays the streams your device is entitled to.

---

### New in v1.0.2

- Complete genre, collection, episode and search lists: all pages are loaded, including previously hidden genre folders and titles beyond the first 24.

### New in v1.0.1

- **Correct episode titles & descriptions** — every episode in a season folder shows its real name and synopsis (previously cards had none).
- **Kids icon** — the Kids main-menu tile is now a teddy-bear glyph instead of a generic star.
- **Collection/genre submenus** shared across Series, Programma's, Kids, Home and catalogue folders, preserving each page's own routes.
- **Films** collections get their own submenus (Top 10, recently added, themed lists) plus a single **Genres** submenu.
- **Dedicated icons** for recurring functions (continue watching, recommendations, preview, new arrivals, popularity lists) and a neutral icon for editorial collections.
- **Widescreen hero artwork** as the selected item's background throughout season and episode lists.
- **Readable navigation breadcrumbs** instead of internal SEO names in Kodi's category heading.
- **Account settings button** to clear saved credentials, session, profile and cache; support for the HTTP 498 stale-token response with automatic re-login.

See the [Changelog](CHANGELOG.md) for the full list of changes.

---

## 🖼️ Screenshots

Coming soon...
<p align="center">
  <img src="docs/screenshot_main.png" width="400" alt="Main Menu"/>
  <img src="docs/screenshot_series.png" width="400" alt="Series View"/>
</p>

---

## 🚀 Installation

1. Download the latest release from [GitHub Releases](https://github.com/Nigel1992/Videoland-Kodi-Addon/releases).
2. In Kodi, go to **Add-ons > Install from zip file** and select the downloaded zip.
3. Open the add-on and use **Aanmelden** to authenticate with Videoland the first time.
4. Install `inputstream.adaptive` for DRM playback.

### Local Addon Check (Filtered Source)

To run addon-check locally without scanning local environment/cache folders, use:

```bash
scripts/run-addon-check-local.sh
```

Run a specific branch only:

```bash
scripts/run-addon-check-local.sh --branch omega
```

---

## 🛣️ Roadmap / Coming Soon

- **Live TV support**.
- **Playback history and resume**.
- **Enhanced search**: filter by genre, year, release date, and more.
- **Better artwork and fanart for all content**.
- **Automated Testing**: expanded CI/CD pipeline for code quality and automated releases.
- **UI Polish**: enhanced skins integration, custom info dialogs, and animations.

---

## 📝 To-Do

- [X] **Group Home page into rails matching the official app**
- [X] **Flat listings for Films, Series and Programma's**
- [X] **Secure (encrypted) credential storage and auto-relogin**
- [X] **Professional icon set for the main menu**
- [X] **Per-episode titles and descriptions in season folders**
- [X] **Automated unit tests for routing, layout parsing and authentication**
- [ ] **Improve error messages and user feedback**
- [ ] **Add more debug and diagnostic tools**
- [ ] **Accessibility improvements for screen readers**

## 💖 Support the Project

All donations go towards your chosen charity. You can pick any charity you'd like, and 5% is retained due to Ko-Fi fees. As a thank you, your name will be listed as a supporter/donor in a GitHub project. Feel free to email me at thedjskywalker@gmail.com for proof! :)

[![Ko-Fi](https://img.shields.io/badge/Ko--Fi-Support%20me-FF5E5B?style=for-the-badge&logo=ko-fi&logoColor=white)](https://ko-fi.com/nigel1992)
[![PayPal](https://img.shields.io/badge/PayPal-Donate-00457C?style=for-the-badge&logo=paypal&logoColor=white)](https://www.paypal.com/donate/?hosted_button_id=KYV9ARF99ZSCE)

---

## 🤝 Contributing

Pull requests, bug reports, and feature suggestions are welcome. Open an issue or pull request in this repository.

---

## 📄 License

Creative Commons Attribution-NonCommercial 4.0 International. See [LICENSE](LICENSE).

---

## ⚠️ Disclaimer

This project is not affiliated with or endorsed by Videoland. Use at your own risk. For personal, non-commercial use only.
