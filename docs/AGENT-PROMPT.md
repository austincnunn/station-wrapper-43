# Let an AI agent build your channels

Once the server is running, an AI coding agent (Claude Code or similar) can plan a lineup from your library and build it through the dashboard, the same way you would by hand on the Stations and Files pages. Copy the prompt below, fill in the three lines under "My setup", and paste it into the agent.

It tells the agent to look at what you have, propose a lineup and wait for your yes before changing anything. Your videos are never touched: everything it makes is links and settings.

Back up the `data` folder first, and read the plan before you approve it. An agent can misjudge a library just as a person can.

```text
You're helping me build TV channels on my Station Wrapper 43 server (a Docker
container that runs FieldStation42 and adds a web dashboard and an IPTV tuner).
It is already installed and running. I want a lineup of channels that feel like
real TV, made from the videos I already have.

My setup:
- Dashboard address: http://<HOST>:5004
- How you can reach it: <e.g. "you're running on the server itself" / "over SSH as user@host" / "only over HTTP">
- What I'd like: <e.g. "a cartoon channel, a sitcom channel, a movie channel and a sci-fi channel", or "you suggest">

How I want you to work, in this order:

1. Look before you plan. Read the project's docs first: QUICKSTART.md and
   docs/REFERENCE.md at https://github.com/austincnunn/station-wrapper-43
   (the sections on the Stations page, the Files page and breaks matter most).
   Then find out what I actually have: GET /lineup.json for the channels that
   exist, GET /api/system/status for the server's health, and the Files page
   API (under /api/files/) to browse my media folders. Count shows, seasons and
   movies per folder so the plan fits the library.

2. Propose a lineup and stop. Show me a table: channel number, name, what plays
   and when (blocks by time of day), where the videos come from, breaks or no
   breaks. Say what you left out and why (a show with three episodes makes a
   poor channel). Wait for my yes before you create or change anything.

3. Build it through the dashboard's API, the same calls its pages make:
   /api/files/* makes lists (a list is a folder of links to my videos; adding a
   show with "follow" on means new episodes join by themselves),
   /api/stations/save creates or edits a station, /api/stations/build builds
   its catalog and schedule. You don't know the request bodies in advance, so
   learn them rather than guess: read the page scripts the dashboard serves
   (station.js, stations.js, files.js under the site root; the pages are Alpine.js components, so the request bodies are in their call(...) lines) and GET an existing
   station to see the shape. Build one channel fully and check it before doing
   the rest, so a wrong assumption costs one channel and not ten.

4. Check your work. For each channel: it appears in /lineup.json, its schedule
   for today and tomorrow (/api/schedule) has no long gaps or missing files,
   and /api/system/status reports nothing new. Refresh the guide with
   GET /xmltv.xml?refresh. Then tell me plainly what was made, what you could
   not verify, and what I need to do in Jellyfin/Emby/Plex (they usually need a
   guide refresh and sometimes a channel re-map after new channels appear).

Rules that matter here:

- My media is read-only and must stay untouched. Never rename, move, re-encode
  or delete a video. Everything you make is links and settings.
- The management API needs my dashboard login. Don't ask me to paste the
  password into this chat. Ask me to put it in an environment variable (or tell
  me another way you'd prefer), log in with /api/auth/login, keep the session
  cookie in memory only, and log out with /api/auth/logout when you finish.
- Before your first change, ask me to back up the server's data folder (or do
  it yourself if you have shell access: copy data/config somewhere safe). Tell
  me where the copy is.
- Don't delete or renumber channels that already exist unless I ask. The
  Channel Guide and Test Pattern that came with the install can stay.
- Prefer the dashboard's own station form over hand-written FieldStation42
  config files. Only write a config directly for something the form cannot
  express, and tell me when you do, because the Stations page will then show
  that station read-only.
- If something fails twice the same way, stop and show me the error instead of
  trying variations.

Things that are easy to get wrong:

- A "loop" station plays only the videos at the top level of its folder, not
  subfolders. For a channel built from show folders, use a standard station.
- One list per show keeps episodes in order and lets the same show appear on
  more than one channel.
- A list only reaches the air after its station's catalog is built, and a new
  station plays nothing until it has a schedule. Build after you save.
- The server keeps schedules topped up by itself (the schedule keeper), so you
  only need to build the first few days.
- Commercial breaks need a list of short clips to draw from. If I have no such
  folder, make the channels with no breaks and say so, rather than inventing one.
- A music channel (songs over a card) needs the station's media filter set to
  mixed; the "music channel" template does this.
- Channel numbers: keep them in one tidy range and leave gaps for later.

If any part of my setup makes this impossible (you can't reach the dashboard,
the media folder is empty, the login fails), say so right away instead of
working around it.
```

## Notes

- The prompt names the API paths but not their request bodies, on purpose: the agent reads them from the dashboard's own page scripts, so the prompt does not go stale when a form changes.
- The management API is behind the dashboard login ([reference: The login](REFERENCE.md#the-login)). With `DASHBOARD_EDIT=0` it is look-only and the agent cannot build anything.
- Want only one channel, by hand? The **Make me a channel now** button on the dashboard does that in one click.
