# Extras

Optional scripts that go with the guides in the [wiki](https://github.com/austincnunn/station-wrapper-43/wiki). None of them run inside the container, and the image doesn't need them.

| File | Runs on | What it does | Guide |
|---|---|---|---|
| `remote-player/fs42-feed.sh` | the server | Lets a player PC's SSH key take a snapshot of the schedule and read the data folder, and nothing else | [Syncing a Remote Player](https://github.com/austincnunn/station-wrapper-43/wiki/Syncing-a-Remote-Player) |
| `remote-player/fs42-sync` | the player PC | Copies the server's schedule, station configs and catalog links once an hour, so the player shows the same broadcast | [Syncing a Remote Player](https://github.com/austincnunn/station-wrapper-43/wiki/Syncing-a-Remote-Player) |
| `remote-player/fs42-streams` | the player PC | Turns the server's Sources channels and guide into stations the player can show. Self-check: `fs42-streams --test` | [Syncing a Remote Player](https://github.com/austincnunn/station-wrapper-43/wiki/Syncing-a-Remote-Player) |
| `backup/fs42-backup.sh` | the server | Nightly backup of your configs, schedule and catalog links | [Backups](https://github.com/austincnunn/station-wrapper-43/wiki/Backups) |

Each script has a short settings block at the top. Change those to match your machines before you use it.
