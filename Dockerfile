# syntax=docker/dockerfile:1
# ONE image, one container. It runs, under a small supervisor (supervisor/supervisor.py):
#   console   FieldStation42's web console and scheduler (station_42.py), on :4242
#   tuner     the dashboard, player and video streams (fs42-tuner), on :5004
#   sync      keeps the symlink pool current                (SYNC_ENABLED=1)
#
# THREE volumes make it work:
#   /config        all configuration: runtime/ (schedule database), confs/ (stations),
#                  tuner/ (the dashboard's config), groups.toml. LOCAL disk.
#   /app/catalog   everything made of symlinks: by-genre/ (tag folders), media-links/ (a link
#                  for every video). LOCAL disk.
#   /mnt/media     your media, read-only. It may hold several separate shares as subfolders.
#
# FieldStation42 (https://github.com/shane-mason/FieldStation42) as a server is headless: only station_42.py is run.
# field_player.py (the on-screen player) runs only in client mode (FS42_ROLE=client, on a PC plugged into a TV), so mpv,
# a bare X server and Qt WebEngine (for web/pay-per-view stations) are in the image but never started on a server.
# FieldStation42's own guide channel needs tkinter and a screen, so the tuner draws its own (fs42-tuner/guide_channel.py,
# with Pillow). The pip list below is hand-picked from FieldStation42's install/requirements.in rather than installed
# wholesale.
# FieldStation42 itself is fetched from upstream at build time, unmodified: FS42_REF is a branch, a tag or a commit
# (upstream's main by default, so every build has the newest; pin one with --build-arg FS42_REF=<commit>). This stage
# only fetches it: git never reaches the final image. The exact commit is kept in /opt/FS42_REF. Upstream's three sample
# videos (~125 MB) are left out: nothing here plays them.
FROM python:3.11-slim-trixie AS fs42
ARG FS42_REF=main
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates && rm -rf /var/lib/apt/lists/*
RUN git init -q /src \
    && git -C /src remote add origin https://github.com/shane-mason/FieldStation42.git \
    && git -C /src fetch -q --depth 1 origin "$FS42_REF" \
    && git -C /src checkout -q FETCH_HEAD \
    && git -C /src rev-parse HEAD > /FS42_REF \
    && rm -rf /src/.git /src/docs/signoff.mp4 /src/docs/static.mp4 /src/docs/off_air_pattern.mp4 \
    && echo "FieldStation42 $FS42_REF -> $(cat /FS42_REF)"

FROM python:3.11-slim-trixie

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1

# Some Docker hosts hand out an IPv6 address on the bridge network with no actual route;
# apt/pip then try the AAAA record first and stall for ~30s per host. Telling glibc's
# resolver to sort A records first sidesteps that everywhere at once.
RUN echo 'precedence ::ffff:0:0/96 100' >> /etc/gai.conf

# libtk8.6: FieldStation42's console checks a guide station by importing its Tk guide module, so Python's _tkinter
# must load (nothing is ever drawn: no display, no Tk window). Without it the console will not start at all once a
# guide station exists.
# ffmpeg: FieldStation42 shells out to ffprobe, and the tuner encodes streams with it.
# tini: PID 1, so processes that outlive their parent (ffmpeg) are reaped.
# mpv and the Intel video drivers: client mode only (FS42_ROLE=client), where field_player.py plays to the screen with mpv
# drawing straight to it (DRM, no X). The server never starts them. One image for both roles keeps their versions in step.
# A bare X server and the libraries Qt WebEngine needs: client mode too, only while the server has a pay-per-view (web)
# station, which FieldStation42 draws with its browser (PySide6, in requirements.txt); see client/player.sh.
ARG TARGETARCH
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates \
      ffmpeg \
      libtk8.6 \
      tini \
      mpv \
      xserver-xorg-core x11-xserver-utils \
      libxcb-cursor0 libxkbcommon-x11-0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-randr0 libxcb-render-util0 \
      libxcb-shape0 libxcb-xinerama0 libxcb-xkb1 libnss3 libxcomposite1 libxdamage1 libxrandr2 libxtst6 libxkbfile1 \
      libgl1 libegl1 libfontconfig1 libdbus-1-3 libxshmfence1 libgbm1 fonts-dejavu-core \
    && if [ "${TARGETARCH:-amd64}" = amd64 ]; then apt-get install -y --no-install-recommends i965-va-driver intel-media-va-driver; fi \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# FieldStation42, as fetched above.
COPY --from=fs42 /src/ /app/
# FieldStation42 reads runtime/ and confs/ relative to /app. They live in ONE config volume
# (/config), and the entrypoint links /app/runtime and /app/confs into it. The sample confs
# the source ships are dropped so that link can take their place (a volume used to hide them).
# /config and /app/catalog are deliberately NOT created here: when a volume is first used, Docker
# copies the ownership of an existing image folder at the mount path onto the volume's folder on
# the host. That would turn the folders you made as yourself into root's, and the scripts you run
# on the host (init.py, build_channels.py, fs42_link.py) could no longer write to them.
RUN rm -rf /app/confs /app/runtime /app/catalog
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && rm /tmp/requirements.txt

# The tuner. The player script is fetched at build time and checked against a SHA-256, so
# a changed file fails the build. To update: change the version and the hash together.
COPY fs42-tuner/resolver.py fs42-tuner/tuner.py fs42-tuner/guide.py \
     fs42-tuner/upstream.py fs42-tuner/library.py fs42-tuner/stations.py fs42-tuner/files.py fs42-tuner/settings.py fs42-tuner/console_client.py fs42-tuner/stationform.py fs42-tuner/stationsapi.py fs42-tuner/keeper.py fs42-tuner/schedlock.py fs42-tuner/auth.py fs42-tuner/captions.py fs42-tuner/legacy.py fs42-tuner/schedules.py fs42-tuner/prefetch.py fs42-tuner/guide_channel.py fs42-tuner/breaksnap.py fs42-tuner/breakstore.py fs42-tuner/iptv.py fs42-tuner/titles.py fs42-tuner/mediaserver.py fs42-tuner/diag.py fs42-tuner/channel_logo.py fs42-tuner/art.py fs42-tuner/ccinject.py fs42-tuner/syncfeed.py fs42-tuner/ppv.py fs42-tuner/envsettings.py /opt/tuner/
COPY fs42-tuner/static/ /opt/tuner/static/
ADD --checksum=sha256:ceb67d511fae54f442a5b9c03e6b8ea30a89efc9bde7fa3ce0687f05f31e6d6a \
    https://cdn.jsdelivr.net/npm/mpegts.js@1.8.2/dist/mpegts.min.js /opt/tuner/static/mpegts.min.js
COPY fs42-tuner/config.default.json /opt/tuner-config.default.json

# The symlink pool scanner and catalog watcher.
COPY fs42-sync/pool.py fs42-sync/sync.py fs42-tuner/schedlock.py fs42-tuner/console_client.py fs42-tuner/breaksnap.py fs42-tuner/breakstore.py /opt/sync/

# The channel tools (init / build / link) run in here too, so no clone or pip is needed on the host:
#   docker exec <container> fs42-channels build --dry-run
COPY scripts/init.py scripts/build_channels.py scripts/fs42_link.py scripts/firstrun.py scripts/update_catalog.py fs42-tuner/schedlock.py fieldstation42/console_launch.py /opt/wrapper/
COPY fieldstation42/fs42-channels /usr/local/bin/fs42-channels
COPY assets/ /opt/assets/
COPY farm/run.sh /opt/farm/run.sh
COPY supervisor/supervisor.py fs42-tuner/stations.py fs42-tuner/envsettings.py fs42-tuner/settings.py /opt/supervisor/
# Client mode: copies the server's schedule (client.py) and plays it (player.sh, banner.py).
COPY client/client.py client/playerconfs.py client/player.sh client/banner.py fs42-tuner/envsettings.py fs42-tuner/settings.py /opt/client/
COPY fieldstation42/entrypoint.sh /entrypoint.sh
RUN chmod 755 /entrypoint.sh /opt/farm/run.sh /opt/client/player.sh /usr/local/bin/fs42-channels && chmod 644 /opt/tuner/static/mpegts.min.js

ENV FS42_TUNER_CONF=/config/tuner/config.json \
    FS42_IN_CONTAINER=1

# Build information, printed first in the log and kept as image labels. CI passes the real values
# (dev-image.yml, release-image.yml); a plain `docker build` leaves "dev" and "unknown". Last, so a
# new commit rebuilds only this cheap layer. The FieldStation42 commit is the one fetched above.
ARG BUILD_REF=dev
ARG BUILD_SHA=unknown
ARG BUILD_DATE=unknown
COPY --from=fs42 /FS42_REF /opt/FS42_REF
# Our licence travels with the image (FieldStation42's own, MPL-2.0, is /app/LICENSE).
COPY LICENSE /usr/share/doc/station-wrapper-43/LICENSE
ENV FS42_WRAPPER_REF=${BUILD_REF} \
    FS42_WRAPPER_SHA=${BUILD_SHA} \
    FS42_WRAPPER_BUILT=${BUILD_DATE}
LABEL org.opencontainers.image.title="Station Wrapper 43" \
      org.opencontainers.image.version="${BUILD_REF}" \
      org.opencontainers.image.revision="${BUILD_SHA}" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.licenses="PolyForm-Noncommercial-1.0.0 AND MPL-2.0"

# 4242: FieldStation42's console. 5004: the dashboard and player (the port a real
# HDHomeRun serves on, so clients that probe for one find this where they expect it).
EXPOSE 4242 5004
ENTRYPOINT ["/usr/bin/tini", "--", "/entrypoint.sh"]
