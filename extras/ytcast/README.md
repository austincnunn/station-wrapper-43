# ytcast: a YouTube channel you cast to from your phone

YouTube's TV app (`youtube.com/tv`) runs in Firefox on a virtual screen inside a container. ffmpeg captures the picture and sound and sends them to MediaMTX, which serves them as a stream that the wrapper's **Sources** page can add as a channel. Pair your phone once with **Link with TV code**, and casting to it works like casting to a smart TV.

The step-by-step guide is in the wiki: [YouTube Channel](https://github.com/austincnunn/station-wrapper-43/wiki/YouTube-Channel).

| File | What it is |
|---|---|
| `Dockerfile` | Debian + Firefox ESR + Xvfb + PulseAudio + ffmpeg (+ the Intel GPU driver on x86) |
| `run.sh` | Starts everything, sets Firefox's preferences, and runs the capture. Settings come from environment variables (top of the file) |
| `extension/` | A one-rule Firefox extension that tells `youtube.com/tv` it's talking to a TV. From [angeloanan/youtube-tv-browser](https://github.com/angeloanan/youtube-tv-browser) (MIT, `LICENSE`), with its auto-update removed |
| `compose-snippet.yml` | The `mediamtx` and `ytcast` services to paste into your compose file |

Notes:

- It uses about a quarter of a CPU core when idle and around one core while a video plays. Playing also needs about 600–800 MB of RAM. With an Intel GPU (`VAAPI_DEVICE`) the encoding moves off the CPU.
- Google can change `youtube.com/tv` at any time. If the channel suddenly shows YouTube's normal website or an error, that's why.
- Paid movies and other DRM videos won't play. Everything else does.
