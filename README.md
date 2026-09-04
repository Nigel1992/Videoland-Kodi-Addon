<div align="center">

<img src="https://raw.githubusercontent.com/Nigel1992/Videoland-Kodi-Addon/master/icon.png" width="300" alt="Videoland Kodi Addon Logo"/>

# Videoland Kodi Addon

[![GitHub stars](https://img.shields.io/github/stars/Nigel1992/Videoland-Kodi-Addon?style=social)](https://github.com/Nigel1992/Videoland-Kodi-Addon)
[![License: CC BY-NC 4.0](https://img.shields.io/badge/License-CC%20BY--NC%204.0-lightgrey.svg)](LICENSE)

**Latest release:** v1.0.0 — 2026-09-04. See the [Changelog](CHANGELOG.md) or [Releases](https://github.com/Nigel1992/Videoland-Kodi-Addon/releases).

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
- **Main Menu Icons**: Flat, consistent, brand-styled icons for every main menu entry.
- **DRM Support**: Widevine-protected streams via `inputstream.adaptive`.

---

### New in v1.0.0

- Cryptographically stored credentials (device-bound encryption) — passwords never appear in `settings.xml`.
- Automatic, silent re-login and retry when a session or JWT expires.
- Flat professional icon set for all main menu entries, in a consistent brand style.
- Add-on renamed to **Videoland**.
- Home screen rails grouped to match the official Videoland homepage.

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
- [ ] **Improve error messages and user feedback**
- [ ] **Add more debug and diagnostic tools**
- [ ] **Add unit tests for routing, playback metadata, and authentication**
- [ ] **Accessibility improvements for screen readers**

---

## 🤝 Contributing

Pull requests, bug reports, and feature suggestions are welcome. Open an issue or pull request in this repository.

---

## 📄 License

Creative Commons Attribution-NonCommercial 4.0 International. See [LICENSE](LICENSE).

---

## ⚠️ Disclaimer

This project is not affiliated with or endorsed by Videoland. Use at your own risk. For personal, non-commercial use only.
