# Station Wrapper 43: quickstart

1. **Start it.** Download `docker-compose.yml` into an empty folder and run `docker compose up -d` (see `README.md`). Nothing to edit: it makes `data` and `media` folders beside the file and serves port 5004. The first start sets up a Channel Guide on channel 1 and a Test Pattern on channel 2. For a Weather channel as well, put `COMPOSE_PROFILES=weather` in `.env`, run `docker compose up -d` again, and type your ZIP code on the **Settings** page (the **Sources** tab) (United States only; an ordinary PC, not a Raspberry Pi).
   On Linux, the installer does this step for you, and can install Docker, mount a NAS share and keep the server up to date: `curl -fsSL https://raw.githubusercontent.com/austincnunn/station-wrapper-43/main/install.sh | bash` (see [The installer](docs/REFERENCE.md#the-installer)).
2. **Open the dashboard** at `http://<host>:5004`. **Settings → Status** tells you at once if something is wrong.
3. **Put videos in the `media` folder** (or point `FS42_MEDIA_ROOT` at yours in `.env`), then use **Settings → Lists & files** to build lists and the **Stations** page to make a channel with a schedule.
4. **Add it to Jellyfin** (or any IPTV client): one tuner of type HDHomeRun at `<host>:5004`, and one XMLTV guide at `http://<host>:5004/xmltv.xml`. Then run Refresh Guide. (TVHeadend: use `http://<host>:5004/lineup.m3u`.)
5. **Add an antenna tuner, a playlist or a camera** on **Settings → Sources**. They go through this container too, so the client only ever talks to it.
6. **Something wrong?** Open **Settings → Status**, press **Download diagnostics**, and send the file.

Back up the `data` folder; upgrading is `docker compose pull && docker compose up -d`. More detail is in the [reference](docs/REFERENCE.md).
