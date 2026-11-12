# Changelog

All notable changes. Format after [Keep a Changelog](https://keepachangelog.com); versions after [Semantic Versioning](https://semver.org).
Work in progress is kept under *Unreleased* and moves to a version heading when that version is released.

## [Unreleased]

### Added
- **A "Cable box" style for the guide channel.** The look of the FS42 TV apps' channel bar: bevelled grey boxes, the
  programme on now in lavender with blue type, a green clock and time line, monospace type. Pick it under Style on the
  guide's edit page.

### Changed
- **Nothing to set up before the first start.** Download `docker-compose.yml`, run `docker compose up -d`, open the
  dashboard. No `.env`, no `setup-dirs.sh`: config and catalog default to `./data` and media to `./media` beside the compose
  file, and Docker makes the folders. `FS42_LOCAL_ROOT` and `FS42_MEDIA_ROOT` still move them; an existing install keeps its
  paths. The volumes are plain bind mounts now (the old named volumes are unused: `./setup-dirs.sh --migrate` or
  `docker volume rm` clears them). The compose file pulls `ghcr.io/austincnunn/station-wrapper-43:latest`.

### Fixed
- **Players froze at the change from one clip to the next.** Each clip, song or black gap is its own ffmpeg, and
  each one started its timestamps again at 0, so time went backwards at every change; a player reading the channel as one
  long stream (Android TV's Media3, VLC) could freeze there (most often on a music channel, which changes every few
  minutes). Every piece now carries on the channel's clock (`CONTINUOUS_TS`, now on by default; `0` for the old way).
- **No more colour bars and tone.** When a block's videos end a few seconds before its slot (breaks can't be filled to the
  second), the stream showed 15 seconds of colour bars with a tone, and the next programme started late. It is now black and
  silent for exactly the gap. Every other "nothing to play" picture is black and silent too, off-air time uses a black clip
  (`assets/off-air.mp4`), and a client-mode player shows black instead of the "Please Stand By" card.
- **Library card: no false duplicates, no dead links coming back.** The same show filed under two sibling folders of a list
  (two blocks of a block channel) is no longer counted as a duplicate; only copies one list would play twice are. A followed
  folder no longer links in videos that were deleted from the share (the pool keeps their old links), so dead links removed
  before a catalog build stay gone.

### Added
- **Jellyfin servers as a place to get videos from.** The Sources page's Emby panel now also takes a Jellyfin server: type
  its address, a user name and password (passed on once for a token, never saved), tick its libraries, and its shows and
  movies appear on the Files page like an Emby server's (under `Emby/<server>/<library>`). It plays the original file; a
  server far away can be asked for a capped H.264 stream instead. Tried against Jellyfin 12.4.
- **A weather channel with one switch.** `WEATHER_CHANNEL=1` in `.env` starts two small containers (WeatherStar 4000+
  and ws4channels) and adds their stream as a channel (3, or the next free number), on a new install or an old one. Its
  place is one setting on the Settings page (a ZIP code, or City, State; United States); changing it needs no restart.
  Off by default: ws4channels exists for amd64 only, and its hidden browser takes about a CPU core all day.
- **A prompt for AI agents** (`docs/AGENT-PROMPT.md`): paste it into Claude Code or a similar agent after setup and it plans a
  lineup from your library, waits for your yes, then builds the channels through the dashboard.
- **Music channels (like Music Choice).** Lists take songs (mp3, flac, m4a, ogg...) as well as videos, and a song
  plays over a card drawn for it: the album cover, artist, song, album and year, what is up next, and a bar that fills
  as it plays. A **music channel** template on the Stations page; the guide names each song; a player PC streams such a
  station from the server.
- **Settings page.** The compose-file settings people change (the pool sync, the farm, followed folders, the Library
  scan, the schedule keeper's timing, prefetch, the media server) can be changed on a new Settings page; a value set there
  wins over the compose file's, and only the part that uses it is restarted. Each player PC (client mode) gets its screen,
  banner and sync settings from the same page on the server, within a minute. The role, the login switches, paths and
  secrets stay in the compose file; the page shows the role and whether each secret is set.
- **No sync token to think up.** A server with no `FS42_SYNC_TOKEN` makes its own (kept in `config/tuner/sync-token`), so client
  sync is always on behind a token; the Settings page's Players card shows it and copies it for a player's `.env`.

- **Intro cards and folders inside a list on the Stations page.** A video slot can have an intro card (a folder of clips,
  one played as each hour of the slot starts: FieldStation42's `start_bump`), and its lists can be folders inside a list.
  A station with those (made by a script) was read-only on the Stations page; it now opens and saves back unchanged.

- **The guide channel's picture shape and text size.** Standard (4:3) draws the guide in the middle of the picture with black
  bars at the sides, so a 4:3 TV that crops the sides shows it edge to edge; text size runs from Small to Extra large.

- **The guide lists every video of a loop.** A block that plays many videos (a loop station's day, or short videos packed
  into one slot) used to be one long entry named after the station; the guide, the guide channel and Jellyfin/Emby now show each
  video with its own name, times and picture, in the order the block plays them (a shuffled loop stays shuffled).

- **Music video .nfo files.** A Kodi `<musicvideo>` .nfo beside a video names it in the guide by its `<title>`, with its plot,
  year and genres (it is not filed under Movies).

### Removed
- **The TubeArchivist conversion.** The `ta-nfo` service, its panel on the Files page (*YouTube (TubeArchivist)*), the
  `/api/ta/*` calls, the `TA_ENABLED` / `TA_LIBRARY` / `TA_INTERVAL_MINUTES` variables, the `catalog/tanfo` view and its
  playlists, and TA_NFOWriter in the image. YouTube channels downloaded with `.nfo` files (Pinchflat, yt-dlp) still get their
  names, and their yearly seasons can still be chosen by kind. A `ta` key left in `settings.json` is ignored.

## [0.7.0] - 2026-10-11

The first public release.

### Added
- **Captions on the IPTV stream.** A video's captions (a `.srt`/`.vtt`/`.ass` file beside it, or a text track inside it) in the language set on the Stations page (English by default) go out in the stream as a CEA-608 caption track, which players such as VLC and many TVs list under their captions button; a station can turn that off. A block of a station's calendar can instead draw them on the picture (*Draw the captions on the picture while this plays*), always visible, for the shows that need them (a Japanese show, not an English one). Jellyfin's own apps do not list an embedded caption track on live TV, so for Jellyfin use the picture option.
- **Getting started.** A dashboard card that tracks the first steps (media, a list, a station, a build, Jellyfin) and a **Make me a
  channel now** button that makes a working channel from the biggest list or the first series in the media; station **templates**
  (movie channel, one list all day, a cartoon channel, a mainstream channel, a shuffled loop); **Duplicate** a station; a plain-words
  summary under the station form and a warning before leaving with unsaved changes.
- **One browser for choosing what plays.** Lists are folders like any other: browse Lists and Media down to a series, a season,
  a folder, one video or a YouTube playlist, in a slot, a commercials block, a mid card choice, the form's defaults and a repeating
  station. Several sources behind one choice are put together as one (a hidden, kept-up-to-date list).
- **Breaks.** Default commercials and default mid cards are opt in, and a commercials block or cards given to a time of day, a
  video slot or a show opt those hours in; separate start-of-break and end-of-break cards; a calendar **Mid cards** tab; with no
  breaks, time slots are soft (the next video comes from the slot the clock is in). Checked against the real engine
  (`scripts/e2e-breaks.py`).
- **A YouTube channel's kinds.** All standard videos, all shorts or all streams in one choice (followed as new seasons appear);
  playlists are sources like series; the playlists folder comes first, as `_Playlists`.
- **Sources page.** Other HDHomeRun tuners, playlists (with their own guide, `url-tvg`) and cameras, played through the container;
  a tuner can be **guide only**; the old single `passthrough` setting is moved onto the page.
- **Status page and diagnostics.** What is wrong first, each with a button to the page that fixes it; a media speed test; a
  diagnostics download with the recent messages and no passwords; `/lineup.m3u` for TVHeadend.
- **Screenshots and a demo library.** `scripts/fetch-demo-media.py` fetches public-domain demo videos (marked so by the Internet Archive) and `scripts/make-screenshots.py` makes the pictures in `docs/images` from a real container.
- **The guide says as much as a tuner's own.** Synopsis, aired date, kinds, season and episode, a picture per series or movie (the
  poster, the cover embedded in the video, or a frame), the categories Jellyfin sorts by, and a logo for each channel (your own or
  drawn from its name). Off-air time is a gap, not a programme.
- **A test pattern says why**, in its bottom right corner: no file, bad file, no commercial, no bump, queueing, or off air.
- **Short videos share a time slot**, and a station can **leave out** that behaviour.
- **TV guide channel** drawn live, with the show's name and the episode's name apart, scrolling long titles, and music.
- **Security checks in CI:** static analysis, a dependency audit of the pinned `requirements.txt`, a secret scan and a Trivy scan, on
  every push and weekly. `SECURITY.md`, `NOTICE`, and this changelog.

### Changed
- The image installs pinned Python dependencies from `requirements.txt`.
- New installs put the Channel Guide on channel 1 and the Test Pattern on 2 (Jellyfin ignores channel 0).
- A scheduled slot whose lists have no videos yet plays the test pattern instead of failing the build.
- Rebuilds keep the channel on air with the old schedule; a failed build says why and can be resumed.
- Find-everything-first checks on the Stations page are cached and no longer touch every link of a list.

### Fixed
- **A channel on a missing file could not be watched.** A quiet picture (the test pattern shown for a missing or unreadable file) is written in thousands of tiny pieces; the replay a new viewer is given overflowed its queue, so every viewer after the first was dropped at once and saw the stream end. The replay is now handed over in blocks.
- **A channel can't be taken off by an error any more.** Anything that went wrong while a channel was choosing or starting its next piece used to end the channel's thread, and the viewer saw the stream end and reconnect. It is now logged with its traceback, shown on the channel as *CHANNEL ERROR: <what>* for ten seconds, and the channel carries on. `CAPTION_TRACK=0` switches the caption track off for the whole container.
- **A test pattern always says why.** The schedule's own off-air video (an hour no block covers, or a block whose lists have no videos yet) now carries its reason in the corner: *NO VIDEOS IN: <lists>* or *OFF AIR: NOTHING SCHEDULED*. Before, only a block named Offair had one.
- **The antenna's guide asks SiliconDust far less.** Its listings are kept (3 hours, also on disk so a restart does not ask again), a refusal (403, 429 or 503) is backed off for 30 minutes while the last listings keep being served, and it asks 3 channels at a time instead of 8. Before, every guide build and every station build asked for dozens of pages, which could get the address rate limited.
- **Black dashboard picture.** The dashboard thumbnail of a channel that has just started a programme with a black fade-in now looks a few
  seconds further in for a real frame instead of showing black.
- A station built a minute ago missing from the TV guide channel until the guide's next hourly rebuild (it is made again when a build finishes).
- A rebuild no longer stops at a scheduled block whose video left the catalog (`'NoneType' object has no attribute 'path'`).
- The guide channel never loading when a programme was a minute or two long.
- Jellyfin showing a tuner with no channels when `advertise_url` was never set; HEAD requests answered.
- The Sources page showing a source as read in January 1970 (its time was read as milliseconds), and the guide channel failing to draw a programme only a few pixels wide on an older Pillow.
- Elements with the `hidden` attribute staying visible when a class gave them a display.

### Removed
- The DVR recorder and its Newznab indexer (recording is left to Jellyfin's DVR, NextPVR and other dedicated programs).
- The single `passthrough` device's `direct` mode (clients always play through the container).
- Making lists from chosen TubeArchivist playlists on the converter panel (a playlist is chosen where it is used).
