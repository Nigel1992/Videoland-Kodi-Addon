# Changelog

> **Latest Version:** v1.0.0 (September 4, 2026)

All notable changes to this project are recorded in this file.

## [Unreleased]

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
