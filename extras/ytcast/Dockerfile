# ytcast: YouTube's TV app (youtube.com/tv) in Firefox on a virtual screen, captured by
# ffmpeg and published to a MediaMTX server (RTSP). Pair a phone with "Link with TV code"
# and cast to it like a smart TV.
FROM debian:trixie-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
      firefox-esr xvfb x11-utils xdotool pulseaudio pulseaudio-utils ffmpeg zip \
      fonts-noto-core fonts-noto-color-emoji ca-certificates procps \
    # Intel GPU encoding (VAAPI_DEVICE in run.sh). The driver only exists for x86, so skip it elsewhere.
    && if [ "$(dpkg --print-architecture)" = amd64 ]; then \
         apt-get install -y --no-install-recommends intel-media-va-driver vainfo; fi \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -m -u 1000 tv

# TV user-agent extension (from github.com/angeloanan/youtube-tv-browser, MIT; see extension/LICENSE)
COPY extension /opt/ext
RUN cd /opt/ext && zip -q /opt/youtube-tv.xpi manifest.json user-agent.json

# No USER line: run.sh starts as root, fixes /profile's owner, then drops to user tv.
COPY run.sh /run.sh
ENTRYPOINT ["/run.sh"]
