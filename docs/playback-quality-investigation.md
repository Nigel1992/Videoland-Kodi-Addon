# Playback quality investigation — 2026-09-15

## Finding

No licence-request integration defect explaining HD failure was identified in this comparison. No working HD playback was established. The initial inspection was followed by controlled live playback tests on the LibreELEC device. Test changes to the installed plugin and playback settings were temporary.

## Evidence

- The tested Kodi device runs InputStream Adaptive 21.5.24.1. Its saved maximum resolution settings allow 1440p; the playback log reports an effective maximum of 1920×1080. Neither is a 540p cap.
- Videoland's software manifest for The Mirror Crack’d (`clip_96513`) offers 224p, 360p, 404p and 540p.
- The hardware manifest adds 720p and 1080p. Those two representations share a different key ID from the SD representations. The HD identifier exactly matches the device's `kNoKey` errors.
- The two playback HAR captures supplied in Downloads (September 3 and September 14) contain Linux Chrome sessions whose fetched manifests top out at 960×540. Both licence responses have `status: OK` and list only an `SD` entry in `supported_tracks`.
- The addon uses the same DRMtoday licence endpoint, upfront-token endpoint structure, customer/platform identifiers, client release, Origin, Referer and token header as the captured web flow. User-Agent strings differ; no evidence from this comparison links that difference to HD entitlement.
- The browser receives a JSON envelope containing a base64 licence. The addon requests `specConform=true` and passes the raw response to the CDM. DRMtoday documents both as supported response modes. This is not evidence of a missing HD-enablement option.

## Limits

An SD-only browser licence response describes that request, not every licence the server might grant. `kNoKey` establishes that a usable key was unavailable to the CDM for that track; it does not by itself establish why. No encrypted licence was decrypted, no content key was extracted, and no captured authentication token or licence challenge was replayed during this investigation.

A reproducible, legitimately working HD session would provide a useful next comparison. Neither L1 support alone nor selecting the first hardware manifest proves HD will work in this addon.

## Live tests

All tests used The Mirror Crack’d and the device's existing Widevine CDM and normal Videoland licence flow. InputStream Adaptive was temporarily configured for a maximum of 720p, and the addon selected the hardware asset for HD tests.

| Test | Selected track | Result |
|---|---|---|
| Existing raw licence response mode | 1280×720 | Repeated `kNoKey` for the HD key ID |
| Browser-style JSON licence response, decoded with `JBlicense` | 1280×720 | Same missing HD key |
| Software stream with browser-style JSON response | 960×540 | Playback timer advanced; no `kNoKey` errors |
| Browser-style response through a temporary localhost diagnostic relay | 1280×720 | HTTP 200, `status: OK`, but `supported_tracks` listed only the SD key; HD still reported `kNoKey` |
| Software control through the same relay | 960×540 | HTTP 200, SD key listed, no `kNoKey` errors |
| Explicit original HD PSSH via `license_data`, with JSON response | 1280×720 | SD-only licence metadata; unknown-KID initialization warnings and `Decrypt Sample returns failure` |

The relay forwarded fresh CDM challenges and unmodified licence responses, retaining only HTTP status and the response's track metadata. It did not save challenges, tokens, licence blobs or decrypted content keys. An initial relay run received HTTP 400 for both HD and SD because Python supplied an unsuitable default Content-Type; that run was invalid as an HD comparison. Explicitly preserving the empty Content-Type restored successful licence responses, including the SD control.

The server-provided Widevine initialization data (PSSH) differs between SD and HD: SD contains the SD key identifier, while 720p/1080p contain the HD identifier. No PSSH was fabricated or edited. Explicitly supplying the original HD PSSH did not produce working video; the legacy override also caused unknown-KID warnings, so this test does not conclusively rule out every initialization-handling issue.

Kodi's reported playback timer advances even during the HD decryption failures. A selected 720p track and advancing timer are therefore insufficient evidence of working HD video.

## Restoration

After testing, the installed plugin was verified byte-for-byte against the original local source. Videoland’s quality preference and InputStream Adaptive’s stream-selection mode and two resolution limits were verified against their saved pre-test values. Temporary runner scripts were removed and the localhost relay was stopped.

## References

- [DRMtoday response modes, documented by castLabs](https://github.com/castlabs/drmtoday-tizen-avplay-demo)
- [InputStream Adaptive licence response configuration](https://github.com/xbmc/inputstream.adaptive/wiki/Integration-DRM-(old))

This report intentionally excludes account identifiers, signed stream URLs, authentication tokens, licence blobs and content keys.
