# Changelog

All notable changes. Format after [Keep a Changelog](https://keepachangelog.com); versions after [Semantic Versioning](https://semver.org).
Work in progress is kept under *Unreleased* and moves to a version heading when that version is released.

## [Unreleased]

### Added
- **A web viewer with a login for each viewer.** Switched on on the Players tab of Settings (or `VIEWER_ENABLED=1`), a
  port of its own (5005, or `VIEWER_PORT` / Advanced on the General tab; publish it in the compose file) serves the
  player alone: no dashboard, nothing to change. Each viewer logs in with a name and password and gets only the
  channels you tick for them on the new **Viewers** tab of Settings (or every channel), in the channel list, the guide
  and the streams. Off by default. Port 5004 still plays everything to anyone who reaches it, so give viewers the
  viewer's port only.
- **Emby and Jellyfin: sign in and the lists make themselves.** Signing in with Emby Connect, or adding a server by its
  address, is now the whole setup. An Emby Connect account with more than one server is first asked which of them to
  use. A server you use has its libraries of shows, movies and music videos chosen and read at once, and each library becomes a list on the Lists & files page ("Server - Library"),
  kept up to date as a followed folder. Untick a server or a library to leave it out. A list is made once per library,
  so one you delete stays deleted. Servers you had already set up keep their choices; their chosen libraries get a list
  at the next read.
- **Emby servers by their address.** Beside Emby Connect, the Sources page now adds an Emby server the way it adds a
  Jellyfin one: pick Emby or Jellyfin, type its address, a user name and password (passed on once, never saved). For an
  Emby server that isn't on Connect, or one you'd rather reach on its LAN address. An Emby server that is on your Connect
  account too keeps its one entry, its libraries and its folder, and is reached on the address you gave from then on.
- **An installer.** `curl -fsSL https://raw.githubusercontent.com/austincnunn/station-wrapper-43/main/install.sh | bash`
  sets up a server or a client-mode player PC on a Linux machine: it installs Docker if it is missing, can mount the
  media share (SMB or NFS, read-only, with an `/etc/fstab` line and Docker made to start after it), writes `.env`,
  starts the container, and checks a player's sync token against the server. It asks whether the videos
  come from an Emby or Jellyfin server and, if all of them do, skips the videos folder and the share. On an amd64 server it offers the weather
  channel and asks for the ZIP code (an ARM machine is not asked: the weather containers are amd64 only). It asks whether to install new versions by
  itself (a systemd timer, daily or weekly at 04:30; a machine that was off catches up when switched on). Safe to run
  again; any answer already in the environment is not asked for.
- **A "Cable box" style for the guide channel.** The look of the FS42 TV apps' channel bar: bevelled grey boxes, the
  programme on now in lavender with blue type, a green clock and time line, monospace type. Pick it under Style on the
  guide's edit page. Long names are cut off with … as the apps do, instead of moving along their cell.
- **"Coming up" lines on the guide channel's ticker.** Tick "Add what's coming up later to the messages" on the guide's
  edit page and the ticker adds lines like "Coming up at 9:00 PM: Friends on Channel 117" after your own messages: one
  programme per channel from the guide's listings, half an hour to eight hours ahead, up to eight lines, picked again
  every hour (`wrapper_guide.coming_up` in the station config).
- **The channel bar on player PCs.** A client-mode player now shows the FS42 TV apps' channel bar on every channel
  change, instead of only the number: the channel's number and name and a green clock in bevelled grey boxes, and the
  programme on now (and when it ends) in lavender with blue type, in monospace type, along the bottom of the screen. What
  is on comes from the server's `/channels.json`, as on the dashboard; with the server out of reach the bar still has the
  number and name. It goes after `FS42_BANNER_SECONDS` (8 by default); `FS42_BANNER=off` still turns it off.
- **A quality list on the Watch page.** Low, Medium, Extra Medium and Full: 1000k up to the tuner's own rate (`video.vbitrate`, 4000k unless you changed it;
  the list goes to 5000k). Pick a lower one on a slow connection: the server makes a lower-rate copy of the channel
  (480p at 2000k and under), which takes one more encoder while it is watched. Your choice is remembered.
- **Decoding on the GPU too, to try out.** With a VAAPI encoder (`video.vcodec` `h264_vaapi`), `"hw_decode": true` under
  `video` in the tuner's `config.json` has the GPU decode and scale a programme as well as encode it. Off unless set.
  A programme with burned-in subtitles or a test pattern's text is made as before, and so is one the GPU cannot decode.

### Changed
- **The Watch page plays more smoothly.** When it falls behind it plays a little faster until it has caught up, and
  keeps 3 seconds in hand. It used to jump ahead and keep 1 second, which showed as skips and short freezes, most of
  all in Firefox. The picture is about 2 seconds further behind the channel.
- **The Watch page has the bar at the top**, like every other page (its own "Channels" button is gone: the bar's
  Dashboard link goes to the same place).
- **The Dashboard page puts the channels first.** The channels are at the top with a one-line count ("23 of 23 on air ·
  1 watching"), in smaller tiles of one size. A tile shows what is not ordinary (off air, encoding, watching) instead of
  an "on air" badge on every one, and a file name only during a break. System and Library are folded under the channels
  with one line each ("No problems · up 11h", "31,965 videos in 474 lists"); System opens by itself when something needs
  a look, the Library has a box to find a list, and the browser remembers which you opened. Pictures no longer flash
  to black every ten seconds, the guide channel's tile shows the guide, and a tile for a video from an Emby or Jellyfin
  server shows the server's picture of it instead of a black square.
- **The bar at the top.** A "Log in" link when you are not logged in, a shorter "FS42 console" link, and no "Password"
  link (it is now "Change the password" on the Settings page, under This machine), so the bar fits one row; on a phone
  it is one row to swipe along instead of four.
- **The Stations page is a third of the length.** A card names a station's first six lists and folds the rest ("40
  more lists"); **Edit**, **Watch** (new) and **Schedule** are on the card and the seldom-used buttons (Add 7 days,
  Duplicate, Update videos, Rebuild schedule, Rename, Delete) are under **More**. "Keep schedules going" and "Captions"
  are folded to one line each that says how they are set ("on · 2 days ahead", "English"), red when the keeper is off.
- **Buttons and links look the same on every page.** The Status, Settings and Dashboard pages showed the browser's
  plain grey buttons and purple links. The Save row of a long form (a station, Settings) stays at the bottom of the
  window instead of the bottom of the page.
- **The Sources page is headed "Sources"**, as in the bar (it said "IPTV sources").
- **Nothing to set up before the first start.** Download `docker-compose.yml`, run `docker compose up -d`, open the
  dashboard. No `.env`, no `setup-dirs.sh`: config and catalog default to `./data` and media to `./media` beside the compose
  file, and Docker makes the folders. `FS42_LOCAL_ROOT` and `FS42_MEDIA_ROOT` still move them; an existing install keeps its
  paths. The volumes are plain bind mounts now (the old named volumes are unused: `./setup-dirs.sh --migrate` or
  `docker volume rm` clears them). The compose file pulls `ghcr.io/austincnunn/station-wrapper-43:latest`.

### Fixed
- **A Music Videos library on an Emby or Jellyfin server came up empty.** Its videos are a kind of their own on the
  server, which was not asked for. They are mirrored now, in a folder per artist, and the guide names each by artist
  and song.
- **An install with only Emby or Jellyfin videos can browse them.** With no videos of your own, the Files page showed
  an empty media folder and the `Emby` folder was out of reach. It is now shown whenever there is no media of your own
  for it to hide. (Beside your own media it still needs the pool: `SYNC_ENABLED=1`.)
- **"Getting started" showed on a working setup when you were not logged in.** The page took "log in first" for "no
  stations yet".
- **The Schedule page opened on an error.** It opened on the first station, usually the guide channel, which has no
  schedule ("Nothing is scheduled for this station yet"). A guide or a pay-per-view menu is no longer in its list.
- **The player's banner said a guide's or camera's name twice** ("100 TV Guide TV Guide").
- **The guide channel's dashboard tile could come up empty in the Cable box style.** At the tile's small size a short
  programme's box was narrower than its two bevelled edges, and the picture was not drawn at all.
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
- **A weather channel with one switch.** `COMPOSE_PROFILES=weather` in `.env` starts two small containers (WeatherStar 4000+
  and ws4channels) and adds their stream as a channel (3, or the next free number), on a new install or an old one. Its
  place is one setting on the Settings page (a ZIP code, or City, State; United States); changing it needs no restart.
  Off by default: ws4channels exists for amd64 only, and its hidden browser takes about a CPU core all day.
  (The line was `WEATHER_CHANNEL=1` until 2026-11-13. The two containers moved behind a Compose profile because Compose
  downloaded their images on every install, switched on or not. With the current compose file the old line alone no
  longer starts them: the server's log says so, and the installer adds the new line by itself when run again.)
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
