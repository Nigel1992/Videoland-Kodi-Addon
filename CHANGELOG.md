# Changelog

> **Latest Version:** v1.10.8 (November 15, 2026)

All notable changes to this project are recorded in this file.

## [1.10.8] - 2026-11-15

### Opgelost
- **"Nee" bij de vraag start de volgende aflevering niet meer.** De achtergronddienst leest de instelling nu vers bij elke beslissing (hield 'm anders vast zoals bij het opstarten), en "Nee" zet een "stop na deze"-vlag zodat de dienst sowieso niets meer doet.

## [1.10.7] - 2026-11-15

### Opgelost
- **Automatisch doorspelen werkt nu echt.** De volgende aflevering start nu zodra de aflevering als *bekeken* telt (voorbij de drempel), net zoals de Lucent Video-add-on het doet — niet meer alleen bij het "afgelopen"-signaal, dat bij DRM vaak als "gestopt" met een iets verouderde positie binnenkomt.
- Tijdelijke diagnose-meldingen weer verwijderd.

## [1.10.6] - 2026-11-15

### Diagnose
- **Tijdelijke meldingen om "volgende aflevering" te vinden.** Aan het eind tonen "Einde: volgende aflevering zoeken…", en daarna "Volgende aflevering starten…" of "Geen volgende aflevering gevonden". Zo is zichtbaar waar het vastloopt. Worden later weer weggehaald.

## [1.10.5] - 2026-11-15

### Opgelost
- **Dubbele "volgende aflevering"-vraag echt weg.** Het slot stond in de achtergrondtaak en het wissen bij het starten maakte het stuk (een race). Het slot wordt nu meteen in de afspeel-aanroep gezet, zodat een tweede start het al ziet voordat er iets draait. Eén vraag (of melding) per aflevering.

## [1.10.4] - 2026-11-15

### Opgelost
- **De vraag komt nu maar één keer.** Kodi start hetzelfde afspelen soms dubbel, waardoor "Volgende aflevering afspelen?" twee keer verscheen. Er zit nu een slot op: per aflevering één keer.

## [1.10.3] - 2026-11-15

### Opgelost
- **Automatisch doorspelen werkt nu ook bij DRM-afspelen.** Kodi meldt het einde van een beveiligde video (inputstream adaptive) vaak als "gestopt" in plaats van "afgelopen", waardoor de volgende aflevering niet startte. De add-on ziet nu aan de positie (laatste seconden) dat de aflevering klaar is en speelt in de stand "automatisch" de volgende af.

## [1.10.2] - 2026-11-15

### Opgelost
- **Speelt nooit meer dezelfde aflevering opnieuw.** Als de "volgende" aflevering toch de huidige blijkt te zijn, slaat de add-on het over in plaats van opnieuw te starten. Dit verhelpt het opnieuw afspelen van dezelfde aflevering.
- **Je ziet nu waarom er geen popup komt.** In de stand "met vraag" toont de add-on kort op het scherm "Geen volgende aflevering gevonden" als er geen volgende is.
- **Betere timing van de popup.** De aftiteling-markering wordt alleen gebruikt als die in de tweede helft van de aflevering ligt; anders komt de vraag ~45 sec voor het eind.

## [1.10.1] - 2026-11-15

### Opgelost
- **Eigen "volgende aflevering"-popup kwam niet.** De aankondiging liep in een thread die Kodi te vroeg kon afbreken, waardoor de popup-wachter nooit startte. Die draait nu in een blijvende thread, met een logregel (`Next episode: own prompt armed` / `Next episode prompt at ...`) zodat te zien is wanneer hij afgaat.

## [1.10.0] - 2026-11-15

### Gewijzigd
- **Volgende aflevering: nu zonder Up Next te kunnen.** Nieuwe instelling *Volgende aflevering* met vier keuzes: **Up Next-add-on** (zoals voorheen, de bekende kaart), **Door de add-on zelf (met vraag)** — een ingebouwde "Volgende aflevering afspelen?" vlak voor het einde, zonder dat `service.upnext` nodig is, **Door de add-on zelf (automatisch)** — de volgende aflevering begint vanzelf, en **Uit**. Handig als de Up Next-add-on bij jou problemen geeft. De oude losse schakelaars "Up Next" en "Automatisch doorspelen" zijn hierin samengevoegd.

## [1.9.11] - 2026-11-14

### Gewijzigd
- **Net-elders-gekeken titels komen vooraan.** Bij het overnemen van je kijkpositie schrijft Videoland nu ook de tijd mee (`lastplayed`), zodat een aflevering die je zojuist op je telefoon keek vooraan in de skin-rij "Afleveringen die je kijkt" verschijnt (die sorteert op laatst gekeken), en niet ergens in het midden.
- **Geen onnodige verversing meer.** De sync laat het beeld niet meer apart verversen; Kodi werkt de bibliotheekrijen op het hoofdscherm vanzelf bij. Zo springt een lijst waar je op dat moment doorheen bladert niet meer op het verkeerde moment terug.

## [1.9.10] - 2026-11-14

### Toegevoegd
- **Ook tonen wat je op een ander apparaat keek.** Eén keer per uur (en kort na het opstarten) haalt Videoland je kijkpositie uit je "Verder kijken"-rij op en zet die als hervatpunt in de Kodi-bibliotheek. Zo verschijnt een aflevering of film die je op je telefoon, tablet of in de Videoland-app begon ook hier in de rij "Afleveringen die je kijkt" van de skin. Werkt met cloudgeschiedenis; uit te zetten met de nieuwe instelling *Ook tonen wat je op een ander apparaat keek* (standaard aan). Raakt alleen titels die Videoland zelf in je bibliotheek heeft gezet.

## [1.9.9] - 2026-11-14

### Fixed
- **Datum-reparatie draait één keer opnieuw met de melding.** In 1.9.7 draaide de reparatie al stil; hij draait nu nog één keer en toont "Bibliotheekdatums bijgewerkt (N afleveringen)".
## [1.9.8] - 2026-11-14

### Added
- **Melding als de datum-reparatie klaar is.** De eenmalige achtergrondreparatie toont nu "Bibliotheekdatums bijgewerkt (N afleveringen)" zodra hij klaar is, en ververst de huidige lijst.
## [1.9.7] - 2026-11-14

### Changed
- **"Recent toegevoegd" volgt nu de uitzenddatum, met terugwerkende kracht.** De datum van een aflevering volgt nu de uitzenddatum, zodat de nieuwste aflevering bovenaan "recent toegevoegde afleveringen" komt. Een eenmalige achtergrondreparatie zet dit ook recht voor afleveringen die al in je bibliotheek stonden (direct in de Kodi-database).
## [1.9.6] - 2026-11-14

### Fixed
- **Nieuwe afleveringen verschijnen in "recent toegevoegd".** Nieuw toegevoegde afleveringen krijgen nu een `dateadded` op het moment van toevoegen, zodat ze bovenaan komen in "recent toegevoegde afleveringen"-widgets. Bestaande afleveringen houden hun datum.
## [1.9.5] - 2026-11-14

### Fixed
- **Dubbele "verder kijken" definitief weg.** Videoland toont nu helemaal geen eigen hervat-venster meer; het hervatten gaat volledig via Kodi (de "Hervatten?"-vraag van Kodi, of automatisch volgens je Kodi-instelling). Dus nog maar één venster, en je hoeft niets bij te werken. Je plek (ook van Videoland zelf) wordt gewoon toegepast.

### Added
- **Nieuwe afleveringen automatisch in de bibliotheek.** Als een serie die je volgt een nieuwe aflevering krijgt, werkt de addon de bibliotheek bij zodat die aflevering meteen bij de rest komt te staan (Instellingen → Geschiedenis; standaard aan).
## [1.9.4] - 2026-11-14

### Fixed
- **Dubbele "verder kijken" bij afspelen vanuit de Kodi-bibliotheek, nu echt opgelost.** De detectie via Kodi-infolabels werkt niet tijdens het afspelen van een .strm-bestand, dus Videoland stelde z'n eigen vraag toch nog. De .strm-bestanden krijgen nu een merkje (inlib=1) waaraan Videoland betrouwbaar ziet dat het afspelen uit de bibliotheek komt; dan laat Videoland de hervat-vraag volledig aan Kodi over. Let op: draai één keer Bibliotheek > Bibliotheek nu bijwerken, zodat de bestaande .strm-bestanden dit merkje krijgen.
## [1.9.3] - 2026-11-14

### Fixed
- **Nog steeds twee keer "verder kijken".** De vorige poging keek alleen naar bibliotheek-items met een database-id, maar bij afspelen vanuit de Videoland-pagina's zelf heeft Kodi vaak al een eigen hervatpunt (en toont dan z'n eigen "Hervatten?"-venster). Videoland slaat nu z'n eigen vraag over zodra Kodi al een hervatpunt voor het item heeft, zodat je nog maar één keer kiest. Heeft Kodi nog geen hervatpunt (bijv. eerste keer, verder kijken vanaf een ander apparaat), dan toont Videoland zelf de vraag zoals voorheen.
## [1.9.2] - 2026-11-14

### Fixed
- **Twee keer gevraagd om verder te kijken vanuit de bibliotheek.** Bij afspelen vanuit de Kodi-bibliotheek vroeg eerst Kodi "Hervatten?" en daarna Videoland nog een keer. Videoland herkent nu betrouwbaar dat het afspelen uit de bibliotheek komt en laat die vraag aan Kodi over, dus je krijgt nog maar één keuze. Binnen de Videoland-addon zelf blijft Videolands eigen "Verder kijken" gewoon werken.
## [1.9.1] - 2026-11-14

### Added
- **Ondertitels zoeken als de stream er geen heeft**: optioneel opent de addon automatisch de ondertitelzoeker van Kodi, zodat je eigen ondertitel-addon (bijv. OpenSubtitles) er een kan vinden (Instellingen → Afspelen).
## [1.9.0] - 2026-11-14

### Added
- **Hele serie als bekeken markeren**: contextmenu op een serie in je bibliotheek stuurt de afleveringen als bekeken naar Videoland (begrensd voor hele grote series).
- **Melding bij nieuwe afleveringen**: een Kodi-melding als een serie in je kijklijst een nieuwe aflevering krijgt (Instellingen → Geschiedenis).
- **Aanbevolen-widget**: een lijst met Videolands eigen aanbevelingen.
- **Verder kijken (beide diensten)**: een widget die Videolands Verder kijken toont met een snelkoppeling naar die van NLZiet.
- **Instelbaar bekeken-percentage**: kies bij hoeveel procent een video als bekeken naar Videoland gaat (Instellingen → Geschiedenis, standaard 90%). Bij vroegtijdig stoppen boven dat percentage wordt de titel alsnog als bekeken doorgegeven.
## [1.8.0] - 2026-11-14

### Added
- **Binge-modus**: schakelaar "Volgende aflevering automatisch afspelen" (Instellingen → Afspelen). Met Up Next geïnstalleerd: laat dit uit en laat Up Next het doen.
- **Stop na deze aflevering**: zet de automatische volgende aflevering voor die sessie uit.
- **Willekeurige aflevering (shuffle)**: contextmenu op een serie in je bibliotheek.
- **Vaste taal- en ondertitelvoorkeur**: automatische keuze van gesproken taal/ondertitels bij het starten (Instellingen → Afspelen).
- **Kijkgeschiedenis**: lokale lijst van wat je gekeken hebt, in het hoofdmenu en als widget, met wisknop.

### Development
- Deelt de nieuwe `watch_history.py`-module en de taalkeuze in `playback_extras.py` met NLZiet. Extra tests.
## [1.7.0] - 2026-11-14

### Added
- **Watched status back to Videoland**: when you mark something as watched or unwatched in Kodi's own library, Videoland gets the same status (Settings → History → Send watched status to Videoland; needs cloud history). Watching to the end already updated Videoland and still does.
- **Widgets for the home screen**: a new "Widgets" menu that groups Continue watching, My watchlist and the Library as ready-made lists for your skin's home-screen widgets.
- **Search both services**: when NLZiet is installed, a search offers the same search in NLZiet at the top of the results.

### Development
- Shares the new `watch_sync.py` module with NLZiet (watched-status logic), kept identical via `scripts/sync-shared.py`.
- 21 new unit tests (watch_sync, chapter markers).

## [1.6.5] - 2026-11-14

### Fixed
- **No TMDb match for some series** (e.g. Chateau Meiland): when Videoland's page has no plain title the add-on used the page's browser title ("Show - Kijk online bij Videoland"), which never matches TMDb. Site suffixes are now stripped, the title of the card you added is used as a second try, and the Kodi log shows per series which TMDb/TVmaze match was found ("metadata for ...").

### Added
- **Next episode (Up Next)**: with the Up Next add-on installed, the next episode is offered near the end of an episode, also from the Kodi library (Settings → Playback; includes an install button).
- **Skip intro/recap**: when Videoland sends intro or recap times with a video, "Skip the intro?" appears at that moment. Whether it sends them is logged per video ("markers found").

## [1.6.4] - 2026-11-14

### Changed
- Same as 1.6.2: the video quality setting is back (1.6.3 removed it by mistake). "Highest available" uses HD only on Android and otherwise plays the best stream that works.

## [1.6.2] - 2026-11-14

### Fixed
- **"Highest available" quality did not play** on Linux/LibreELEC, Windows and macOS: Videoland only grants its HD key (720p/1080p) to Widevine L1, which Kodi has only on Android, so the HD stream could never be decrypted there (see docs/playback-quality-investigation.md). The setting now uses the HD stream only on Android and otherwise plays the best software stream (up to 540p) and says so once. The setting label and help explain this.

## [1.6.1] - 2026-11-14

### Changed
- **Settings → Library** is now right below Account and split into groups with a heading: Folders, Lists to the library, Automatic updates, Extra metadata and Maintenance.

### Added
- **Profile for the library**: choose whose watchlist goes into the Kodi library (Settings → Library → My watchlist to the library); by default the active profile.

### Development
- Modules shared with the other add-on are listed in `scripts/sync-shared.py` and pinned in `SHARED.lock`; a test fails when one is changed without copying it to the other add-on.

## [1.6.0] - 2026-11-14

### Added
- **Posters and backgrounds: TMDb first** (Settings → Library → Extra metadata, on by default): posters and backgrounds come from TMDb when it has them, with the service's own images as fallback; descriptions stay service-first. Artwork the add-on set earlier in Kodi is replaced when a better image is known (Kodi gets the image url, so the change shows at once); artwork you chose yourself in Kodi is never replaced.
- **Choose the right TMDb title** (Library menu, context menu of a title): pick the matching TMDb series or film by hand, or search with another term, when the automatic match missed it. Titles with a trailing year or "- Seizoen N" now also match automatically.
- **Season posters**: each season gets its own poster from TMDb (`season01-poster.jpg`), also for seasons Kodi already scanned.
- **Logos in the menus**: logos of titles outside the library are looked up on TMDb in the background and appear the next time a list is opened (setting "Show logos in the menus too", needs the TMDb key).
- **One resume question**: playing from Kodi's library no longer asks "Resume?" twice: when Kodi already asked with its own resume point, the add-on does not ask again (cloud progress is still saved).

## [1.5.1] - 2026-11-14

### Added
- **Series and film logos (clearlogo)**: with a TMDb key, every series and film in the library gets its logo (Dutch first, then English, then one without text) as `clearlogo.png` (films: `<name>-clearlogo.png`) and in the `.nfo`. Titles Kodi already scanned get the logo through the artwork repair. Skins that show logos instead of titles (widgets, info screens) now use them; browse lists in the add-on show the logo for titles that are in the library.

## [1.5.0] - 2026-11-14

### Added
- **My watchlist in the Kodi library**: "Add My watchlist to the library now" (Library menu and Settings → Library) puts every series and film from My watchlist in the Kodi library; a bookmarked episode adds its series. With "Keep My watchlist in the library automatically" new watchlist titles are added at every automatic update, and optionally titles that left the watchlist are removed (only those that came from the watchlist).

### Fixed
- **Diagnostics**: a library folder is no longer reported as "not a Kodi source" when Kodi already has titles from it (for example when the parent folder was added as the source); editorial rails on the watchlist page are shown as info instead of a warning.

## [1.4.1] - 2026-11-14

### Fixed
- **My watchlist (Mijn Kijklijst) incomplete or outdated**: the watchlist was served from the browsing cache (30 minutes up to a week, depending on the cache setting), so recently added titles were missing. It is now always loaded fresh from Videoland.
- **Lists of the wrong profile**: the browsing cache was shared by all profiles; each profile now has its own cache folder ("Clear cache" still clears all of them).
- **Progress notices after a restart**: "progress saved/failed" notices were suppressed during the first minute after the device started.

### Added
- **Diagnostics**: per watchlist block, how many titles Videoland reports, how many were loaded and how many are shown, to pin down any remaining gap.

## [1.4.0] - 2026-11-14

### Added
- **Search filters**: a Filter entry on top of search results narrows them by type (series, films, episodes), period and genre (period and genre when Videoland supplies them).
- The diagnostics button moved to Settings → Library.

## [1.3.4] - 2026-11-14

### Fixed
- **Library titles missing from Kodi**: Kodi ignores a scan request while it is still scanning, so titles added in quick succession were written to the library folder but never scanned. Such a request now waits and runs as soon as Kodi's scan is finished, and **Update library now** always lets Kodi scan, so titles that were skipped before get in too.

### Added
- **Diagnostics** (Settings): one screen that checks sign-in, InputStream Adaptive, Widevine, the connection to the service, TMDb and TVmaze, the TMDb key, whether the library folders are Kodi sources, and how many library titles Kodi really has. A privacy-safe report with a log excerpt is saved for bug reports.

## [1.3.3] - 2026-11-14

### Added
- **Sorting**: list pages offer Kodi's sort options (default order, title, year; episode and date inside seasons).
- **Clear error messages**: unexpected problems show one sentence that says what happened (no internet, slow response, session expired, not in your subscription, no longer available, too many requests, service outage); the details go to the Kodi log.
- **GitHub Actions**: tests and an installable zip on every push and pull request; pushing a `v*` tag publishes a release with the zip.

### Fixed
- **TMDb key test**: the button now saves the settings first (Kodi only saves when the settings window closes, so the test used to see an empty key) and says exactly what is wrong: no key saved, key not accepted, or TMDb not reachable. Connections retry with a bundled certificate list on devices without system certificates.
- **Menu icons not changing**: the new icons now live in `resources/icons/tiles/`. Kodi caches images by file name, so with the old names it kept showing the previous icons.

## [1.3.2] - 2026-11-14

### Changed
- **Menu icons**: coloured tiles per menu group (red = browse, plum = your own lists, orange = live tv, grey = account) with white line glyphs, rebuilt by `scripts/build-menu-icons.py`. Live TV has its own broadcast icon.
- **Main menu order**: Videoland's own navigation first, then Continue Watching and Library, then profile, sign out and clear cache at the bottom.
- **Translations**: "Sign in", "Sign out" and "Clear cache" are now translatable instead of fixed Dutch text.

### Fixed
- **Library posters**: series and films now get their poster and background in Kodi's library. The portrait and widescreen images of the card you added are remembered and used when the title page has none, and the images are saved as `poster.jpg`/`fanart.jpg` (films: `<name>-poster.jpg`/`<name>-fanart.jpg`) next to the files, which Kodi always uses.
- **Library posters**: titles Kodi had already scanned without artwork get their poster and background after every library update and every Kodi library scan; artwork you chose in Kodi is never replaced. Settings → Library has a "Repair artwork in the Kodi library" button.

## [1.3.1] - 2026-11-14

### Added
- **Library metadata**: Videoland's own data is always used first; only empty fields are filled in from TMDb (series and films, needs a free TMDb API key) and TVmaze (series, no key needed): description, poster, background, year, genres, rating, network/studio, and per-episode titles, descriptions, images and air dates. Placeholder titles such as "Aflevering 3" are replaced by the real episode title.
- **Library metadata**: `.nfo` files also carry TMDb, TVDB, IMDb and TVmaze ids, so Kodi, skins and Trakt match titles reliably. TVDB is not queried directly (its API needs a paid key); the id comes from TMDb/TVmaze.
- **Settings → Library → Extra metadata**: on/off switch, TMDb API key field and a "Test TMDb key" button.
- Only exact title matches are used (films also need a matching year), answers are cached for 7 days, and an unreachable service is skipped for a few minutes.

## [1.3.0] - 2026-11-14

### Added
- **Kodi library**: series and films get **Add to library** / **Remove from library** in their context menu. The add-on writes `.strm` + `.nfo` files (title, plot, season/episode, poster, fanart and a Videoland id), so titles appear in Kodi's own library and in skin widgets.
- **Automatic updates**: added titles are refreshed in the background (default every 12 hours, never during playback). New episodes are added; titles that left Videoland are removed after three missed updates in a row. Network or login problems never count as missing.
- **Library menu**: a new main menu entry lists everything in the library, with **Update library now** and a remove option per title.
- **Library settings**: folders for series and films (folder browser, smb:// and nfs:// supported), automatic update and interval, and options to scan and clean the Kodi library after a change.

### Changed
- Episode numbers in the library are assigned once and stored, so file names stay the same when episodes come and go. Kodi keeps watched status and resume points.

### Tests
- 9 tests for library export, stable numbering, removal rules, context menus and the silent background update.

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
