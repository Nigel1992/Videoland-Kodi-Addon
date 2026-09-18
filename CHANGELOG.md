# Changelog

> **Latest Version:** v1.2.1 (September 18, 2026)

All notable changes to this project are recorded in this file.

## [1.2.1] - 2026-09-18

### Added
- **Live TV ("TV en Gids")**: the six linear Videoland channels (RTL 4, RTL 5, TELEKIDS, RTL 7, RTL 8 and RTL Z) now render as directly playable entries — pressing Enter starts the channel's live stream instantly, no further browsing needed.
- **EPG in every channel**: each channel's description shows the currently airing programme and the one next (`Nu:` and `Vervolgens:`) with their broadcast times, taken from the EPG-grid layout.
- **Widevine live playback**: live DRTM licence tokens are fetched from Videoland's live `upfront-token` endpoint and streams play from the direct bedrrock DASH source. The `hlsfp` HLS assets are FairPlay-encrypted (`skd://`) and unusable in Kodi, so they are never selected.
- **No history for live**: live channels carry no watched status or resume progress, and live playback neither saves progress nor writes anything to Videoland cloud history.
- Legacy Live TV/EPG-grid shortcuts now open the same flat channel zapper instead of the on-site layout page.

### Tests
- 11 regression tests covering channel parsing, current/next EPG selection, live stream resolution, instant playback wiring and the no-history guarantees.

## [1.2.0] - 2026-09-18

### Added
- Fresh Videoland resume prompts with explicit resume, restart and cancel choices.
- Cloud progress saves after seeks, pauses, stops and completion, plus periodic updates. Failed saves persist across Kodi restarts and retry in the background.
- A playback history source setting: Videoland cloud or this Kodi device only. Local mode uses Kodi resume points and watched status, ignores cloud bookmarks and pauses cloud saves and retries.
- Categorized English and Dutch settings with detailed help, optional sync notifications and a cloud sync status screen. Cloud controls depend on the selected history mode.
- Active profile names and a clear explanation when an account has only one profile.
- Fresh Continue Watching browsing and a cloud-backed Remove from Continue Watching context menu.
- Others also watch context menus on films, programmes and episodes, opening Videoland's related titles.

### Fixed
- Resume seeks include the duration required by Kodi to honour the saved position.
- Back, Escape and Cancel dismiss the cloud resume prompt without starting playback or saving zero progress.
- Cloud mode suppresses Kodi-local resume and watched indicators; local mode preserves Kodi's native controls.
- Serialize queued and live cloud saves; removing a title discards matching queued updates and prevents older playback sessions from restoring it.
- Retry temporary 502/503/504 responses and timeouts when removing Continue Watching entries.

## [1.1.0] - 2026-09-16

### Added
- Required dependency on InputStream Helper 0.8.6 or newer for guided InputStream Adaptive and Widevine setup on supported platforms.
- DRM readiness check before requesting short-lived playback credentials, with clean cancellation when setup is declined or unavailable.
- Regression tests covering setup cancellation and successful playback preparation.

### Changed
- Use the InputStream addon selected by InputStream Helper for playback.
- Update installation and upgrade instructions for automatic helper dependency installation.
- Correct playback-quality guidance: available streams and granted licences determine usable resolution; L3 does not imply a universal fixed resolution and L1 alone does not guarantee HD.
- Document the live LibreELEC investigation: tested 720p requests still received SD-only licence metadata, while the 540p control had no missing-key errors. No experimental licence or playback changes are included in this release.

## [1.0.2] - 2026-09-15

### Added
- A quiet loading notice for lists with at least 25 title lookups, explaining that the first load can take a while for many films or series.

### Fixed
- Wire Settings → Cache → Clear Cache to an executable Kodi action, keeping settings open and avoiding an immediate cache refill.
- Genre folders open their complete title list directly, removing the repeated genre submenu for films and series. Genres with multiple rails combine their titles without duplicates.
- Show the first-load notice only once, remembering it across directory visits and Kodi restarts.
- Follow both section and item pagination when browsing genres, collections, seasons and search results. Genre lists no longer stop at 24 titles, and all genre folders are available.
- Preserve section membership and search parameters across pages, discard overlapping items within a section, and report stalled pagination instead of silently showing incomplete results.
- Keep artwork and playback metadata lookups lightweight by fetching additional pages only for directory browsing.
- Retry temporary server errors on cached GET requests, so a brief API failure does not abort a long list halfway through.

## [1.0.1] - 2026-09-15

### Added
- Per-episode details: season folders now show the real episode title and a per-episode synopsis, recovered from each episode's own (cached) video page instead of relying on bare cards that carry neither.
- Dedicated small icons for recurring functions (continue watching, recommendations, preview, new arrivals and popularity lists); catalogue/editorial collections retain neutral icons. Promotional banner metadata takes precedence over wording.
- Shared collection and genre navigation across Series, Programma's, Kids, Home and other catalogue folders, retaining each page's own routes and section labels.
- Matching charcoal/red icons for each movie collection, including Top 10, Genres, recently added, romance, action and award winners.
- Films collections now have their own submenus, including Top 10, recently added and themed lists, preserving titles shared across multiple collections.
- Films now groups the twelve requested movie genre folders under a single Genres submenu.
- Widescreen movie/show artwork as the selected item's background, with dark cinematic menu fanart as a fallback.
- Consistent charcoal/red menu icons, dedicated profile/watchlist icons, and browsing category labels.
- Account settings button to clear saved login information, including legacy credentials, the session, selected profile and cached content.
- Local addon-check script (`scripts/run-addon-check-local.sh`) mirroring the CI addon-check workflow.

### Changed
- Kids menu icon is now a teddy-bear glyph instead of a generic star, matching the flat charcoal/red tile style of the other menu icons.
- Legacy pre-polished icons were removed; the icon set is generated from vector sources via `scripts/build-menu-icons.py`.

### Fixed
- Rotating editorial collections use a neutral collection icon instead of guessing a theme from their names.
- Every folder carries its visible navigation path (categories, genres, shows, seasons, home rails and search), replacing internal SEO names in Kodi's category heading.
- Fetch the title-page Jumbotron hero for movie/show backgrounds instead of reusing catalogue thumbnails; use the same hero throughout season and episode lists.
- The Jumbotron hero no longer shadows the latest episode's real card, so season folders keep every episode (e.g. EWOUT Season 5 Episode 1).
- HTTP 498 (invalid or expired token) now triggers silent re-login using the existing encrypted credentials and retries the action once.
- Navigation and parallel program lookups propagate authentication failures so session renewal can run.
- Session renewal preserves the existing encrypted credential blob instead of rewriting it.

## [1.0.0] - 2026-09-04

First professional release.

### Added
- **Secure Credential Storage**: Email and password are now encrypted with a device-bound key (PBKDF2-HMAC-SHA256 derived AES stream with HMAC authentication) before they are written to disk. Plaintext passwords no longer appear in `settings.xml`.
- **Automatic Re-login**: When a session or JWT expires, the add-on silently re-authenticates from the stored (encrypted) credentials and retries the original request exactly once.
- **Legacy Session Migration**: Existing plaintext sessions are automatically migrated to the encrypted store on first load.
- **Main Menu Icons**: Consistent flat, brand-styled (rounded-square tiles) icons for every main menu entry — Home, Series, Films, Programma's, Kids, Trending, Zoeken, plus Login/Logout/Cache actions.
- **Auth-Error Handling**: Distinct `AuthError` type so expired sessions are detected on HTTP 401/403 and handled gracefully.
- **Add-on renamed to Videoland** across the Kodi UI.

### Updated
- Home screen is grouped into the same titled rails/sections as the official Videoland homepage.
- Films, Series and Programma's listings render as complete flat lists.

### Changed
- Credentials are entered once at login using a masked dialog and are no longer exposed as a settings field.

### Security
- Session tokens (`auth_json`) and credentials (`secret_json`) are stored encrypted on disk.
- Encryption key is device-bound with `0600` permissions, so copied settings cannot be decrypted elsewhere.
- Tokens and email addresses are redacted from Kodi log output.

## [0.3.2] - 2026-09-03

### Fixed
- Regression where Films, Series and Programma's listings showed no items; these now render as flat lists again.

## [0.3.0] - 2026-09-03

### Added
- Home page grouped into rails matching the official Videoland homepage.

## [0.2.0] - 2026-09-02

### Added
- Working main menu populated from Videoland's live navigation (Home, Series, Films, Programma's, Kids, Trending, search).
