<div align="center">

<img src="https://raw.githubusercontent.com/Nigel1992/Videoland-Kodi-Addon/master/icon.png" width="300" alt="Videoland Kodi Addon Logo"/>

# Videoland Kodi Addon

[![GitHub stars](https://img.shields.io/github/stars/Nigel1992/Videoland-Kodi-Addon?style=social)](https://github.com/Nigel1992/Videoland-Kodi-Addon)
[![License: CC BY-NC 4.0](https://img.shields.io/badge/License-CC%20BY--NC%204.0-lightgrey.svg)](LICENSE)

**Latest version:** v1.2.1 — 2026-09-18. See the [Changelog](CHANGELOG.md) or [Releases](https://github.com/Nigel1992/Videoland-Kodi-Addon/releases).

<sub>Unofficial Videoland Kodi Addon - Watch movies, series, programs, and more from Videoland directly in Kodi using your own subscription.</sub>

</div>

---

> ⚠️ **Warning:** This add-on is under constant development. Some features may be broken or incomplete. Please see the To-Do section below for known issues and planned improvements. Use at your own risk and check back for frequent updates!

---

## ✨ Features

- **Home Screen Rails**: The home page mirrors the official Videoland app, grouping content into the same titled rails/sections for a native feel.
- **Live TV (TV en Gids)**: Browse the six linear channels (RTL 4, RTL 5, TELEKIDS, RTL 7, RTL 8, RTL Z) and start live playback with a single click. Each channel's description shows the currently airing programme and the one next with broadcast times. Live streams carry no watched status, resume progress or cloud history.
- **Series**: Browse and play series with full season/episode navigation.
- **Movies**: Discover and watch movies from the Videoland catalog.
- **Programma's**: Browse programs and catch-up content.
- **Kids**: Dedicated kids content section.
- **Trending**: See what's trending right now.
- **Search**: Find series, movies, and programs by title.
- **Watchlist (Mijn Kijklijst)**: Access your saved content.
- **Cloud Playback Progress**: Resume from Videoland and save Kodi progress to the same profile after seeking, pausing or stopping, and periodically during playback. Failed saves are retained on this device and retried while Kodi is running, including after a restart. Turning off progress saving pauses retries; signing out removes pending saves. **Settings → Playback history → Cloud progress status** shows the last successful save, pending updates and any save error for the active profile. Sync notifications are optional and off by default. In cloud mode, browse items hide Kodi-local progress and watched markers; the resume popup uses fresh cloud progress.
- **Active Profile and Continue Watching**: The main menu shows the active profile name and offers **Refresh Continue Watching**, which fetches the current list directly from Videoland without using the browsing cache. On supported Continue Watching cards, use the context menu → **Remove from Continue Watching** to remove the title from the selected cloud profile. Older pending saves for that title are discarded; explicitly playing it again can add it back.
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
- **Guided DRM Setup**: InputStream Helper checks InputStream Adaptive and Widevine before playback and guides installation or enabling on supported platforms.

---

## 📺 Playback Quality & DRM (important)

Playback quality depends on the available streams, the licence granted for the device/session, and Kodi's playback capabilities. Widevine L3 does not itself specify a fixed 540p or 720p limit, and L1 alone does not guarantee HD in this addon.

**What we have verified:** For *The Mirror Crack’d*, Videoland's software DRM manifest tops out at **960×540**. Its hardware DRM manifest additionally offers **1280×720** and **1920×1080**, using a separate key ID. That HD key ID matches the `kNoKey` errors observed on the tested LibreELEC device. Two captured Linux Chrome sessions also received manifests capped at 540p, with successful DRMtoday responses listing only an SD track. These observations do not establish a universal limit for every title or device.

**About the quality setting:** The add-on offers a *Preferred quality* setting:

- **Software L3 (default)** — prefers the asset marked `software` by Videoland, falling back to the first DASH asset if absent.
- **Best available (DASH)** — uses the first DASH asset returned by Videoland. It does not sort assets by resolution or guarantee that the selected tracks can be decrypted.

See [the playback investigation](docs/playback-quality-investigation.md) for the evidence and its limits.

This add-on does **not** bypass DRM or subscription checks; it simply plays the streams your device is entitled to.

---

### New in v1.2.1

- **Live TV channels, instantly playable** — TV en Gids shows the six linear Videoland channels (RTL 4, RTL 5, TELEKIDS, RTL 7, RTL 8, RTL Z) as a flat zapper; pressing Enter starts the live stream right away.
- **EPG in each channel** — the description shows the currently airing programme (`Nu:`) and the one next (`Vervolgens:`) with their broadcast times.
- **Widevine live streams** — live playback uses Videoland's direct DRMtoday DASH source with fresh licence tokens; the FairPlay-only HLS variants are never used.
- **No history for live** — live channels are never marked watched, get no resume progress, and live playback does not touch Videoland cloud history.

### New in v1.2.0

- Choose Videoland cloud history or local Kodi resume points and watched status.
- Resume reliably, sync progress with optional notifications, and retry failed saves in the background.
- Refresh or remove titles from cloud Continue Watching, and see the active profile.
- Right-click a title for **Others also watch / Anderen kijken ook** recommendations.
- Clear English and Dutch settings explain which history and sync options are active.

### New in v1.1.0

- **Guided Widevine setup** through InputStream Helper 0.8.6 or newer, installed as a required dependency.
- Playback checks DRM readiness before requesting short-lived playback credentials; cancelling setup stops playback cleanly.
- Updated playback-quality documentation based on browser captures and live LibreELEC tests. This release does not add HD support to the tested L3 setup.

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

1. Download **`plugin.video.videoland.nl-1.2.1.zip`** from [GitHub Releases](https://github.com/Nigel1992/Videoland-Kodi-Addon/releases/latest). Choose the addon ZIP asset, not GitHub’s automatically generated source archives.
2. In Kodi, go to **Add-ons > Install from zip file** and select the downloaded zip.
3. Open the add-on and use **Aanmelden** to authenticate with Videoland the first time.
4. Start a video and follow InputStream Helper's prompts to install or enable InputStream Adaptive and set up Widevine on supported platforms. Kodi installs InputStream Helper as an add-on dependency. If you cancel setup, playback stops; start the video again when you are ready to finish setup.

To upgrade, install the new ZIP over the existing addon. Saved login, profiles and settings are retained. Keep Kodi’s official addon repository enabled so Kodi can install InputStream Helper.

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

### Playback history source

Settings → Playback history → Save and resume using selects Videoland cloud (default) or This Kodi device only. Cloud mode uses Videoland resume prompts and hides Kodi resume/watched marks; saving to Videoland is a separate switch. Local mode leaves resume and watched status to Kodi, ignores cloud bookmarks and their duration, hides cloud Continue Watching, and pauses cloud writes/retries. Kodi's normal resume thresholds and watched rules apply. Local history is tied to the Kodi profile and shared between Videoland profiles on the device. Switching sources does not migrate or erase history. Pending cloud saves may resume after switching back with cloud saving enabled.

Right-click a film, programme or episode and choose **Others also watch / Anderen kijken ook** to browse Videoland’s related titles. This works with either playback history source.
