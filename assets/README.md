# Pre-rendered clips

Made once and kept in the repo, so a new install has them without rendering anything (`ffmpeg` with Pillow for the
splash card). The image copies this folder to `/opt/assets/`.

| File | What it is | Used for |
|---|---|---|
| `sw43-splash.mp4` | the Station Wrapper 43 splash card, 5 seconds, 1280x720, silent | the default bump clip (`catalog/by-genre/bump/`) when there are no bump clips or commercials of your own |
| `off-air.mp4` | black and silent, 60 seconds, 1280x720 | the time that no slot is assigned (off air): a station's `off_air_video` |
| `black.png` | black, 1280x720 | a player's stand-by picture (client mode), shown while a channel starts and between programmes |
| `test-pattern.mp4` | colour bars and a quiet 1 kHz tone, 60 seconds, 1280x720 | the Test Pattern station only (stations made before off-air.mp4 had it as their off-air video; saving one on the Stations page moves it on) |

To change one, replace the file and rebuild the image. Keep them small: they are copied into every image.
