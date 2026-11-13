#!/usr/bin/env bash
# Station Wrapper 43 installer, for a Linux machine (a server, or a player PC in client mode):
#
#   curl -fsSL https://raw.githubusercontent.com/austincnunn/station-wrapper-43/main/install.sh | bash
#
# It asks a few questions, shows what it will do, and then:
#   - installs Docker if it is missing (get.docker.com)
#   - can mount your media share (SMB or NFS) read-only, now and at every boot (/etc/fstab)
#   - downloads the compose file, writes .env beside it, and starts the container
#   - can set a timer that checks for a new version daily or weekly and installs it
# Safe to run again: it keeps a compose file that is already there, .env lines it does not ask about, and a share
# that is already mounted or in /etc/fstab.
#
# Unattended: an answer that is already in the environment is not asked for.
#   FS42_ROLE=server|client          FS42_DIR=<folder for the compose file and data>
#   FS42_EMBY=y|n  FS42_OWN_VIDEOS=y|n   videos from an Emby or Jellyfin server; and videos of your own as well (server)
#   FS42_MEDIA=local|smb|nfs         FS42_MEDIA_ROOT=<videos folder, or where to mount the share> (server only;
#                                    a player always uses /mnt/media)
#   FS42_SHARE=//nas/media or nas:/export     FS42_SHARE_USER= (empty: guest)     FS42_SHARE_PASS=
#   FS42_SERVER=http://<server>:5004  FS42_SYNC_TOKEN=  FS42_SCREEN=hd|crt  FS42_PLAYER_NAME=     (client only)
#   FS42_WEATHER=y|n  WEATHER_LOCATION=<a ZIP code, or City, State>     (server on an ordinary PC only: see below)
#   FS42_AUTO_UPDATE=no|daily|weekly  FS42_GO=y
# Installing from a copy of the project somewhere else:
#   FS42_RAW=<where docker-compose.yml is downloaded from>   FS42_IMAGE=<registry/name of the image, without the tag>
set -euo pipefail

RAW=${FS42_RAW:-https://raw.githubusercontent.com/austincnunn/station-wrapper-43/main}
STOCK_IMAGE=ghcr.io/austincnunn/station-wrapper-43

if [ -t 1 ]; then B=$'\e[1m' G=$'\e[32m' Y=$'\e[33m' R=$'\e[31m' C=$'\e[36m' N=$'\e[0m'; else B="" G="" Y="" R="" C="" N=""; fi
say()  { printf '%s\n' "${C}==>${N} ${B}$*${N}"; }
ok()   { printf '%s\n' "  ${G}✓${N} $*"; }
warn() { printf '%s\n' "  ${Y}!${N} $*" >&2; }
die()  { printf '%s\n' "${R}✗ $*${N}" >&2; exit 1; }

# Under `curl | bash` the script itself is on stdin, so questions are asked on the terminal.
have_tty() { { : < /dev/tty; } 2>/dev/null; }

ask() {            # ask VAR "question" [default] [secret]: an answer already in the environment is kept
  local var=$1 q=$2 def=${3-} ans=""
  [ -z "${!var+x}" ] || return 0
  if have_tty; then
    printf '%s' "${B}?${N} $q${def:+ [$def]}: " > /dev/tty
    if [ "${4-}" = secret ]; then read -rs ans < /dev/tty || true; echo > /dev/tty; else read -r ans < /dev/tty || true; fi
  fi
  printf -v "$var" '%s' "${ans:-$def}"
}

need() {           # ask, until there is an answer
  while :; do
    ask "$@"
    [ -z "${!1}" ] || return 0
    have_tty || die "set $1 (there is no terminal to ask on)"
    unset "$1"
  done
}

choose() {         # choose VAR "question" default option...: ask, until the answer is one of the options
  local var=$1 q=$2 def=$3; shift 3
  while :; do
    ask "$var" "$q ($(IFS=/; echo "$*"))" "$def"
    case " $* " in *" ${!var} "*) return 0 ;; esac
    have_tty || die "$var must be one of: $*"
    warn "one of: $*"; unset "$var"
  done
}

pkg() {            # pkg <Debian/Ubuntu name> <Fedora/Arch name>
  if   command -v apt-get > /dev/null; then $SUDO apt-get update -qq && $SUDO env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "$1" > /dev/null
  elif command -v dnf     > /dev/null; then $SUDO dnf install -y -q "$2"
  elif command -v pacman  > /dev/null; then $SUDO pacman -S --noconfirm --needed "$2"
  else die "install $1 with your package manager, then run this again"; fi
}

# The weather channel is on when .env says so: COMPOSE_PROFILES=weather, or WEATHER_CHANNEL=1 for a compose file from
# before November 2026 (main writes both, so either file works).
WEATHER_ON='^(WEATHER_CHANNEL=1|COMPOSE_PROFILES=(.*,)?weather(,.*)?)$'

# That older compose file switches the two weather containers off with scale 0, and Compose pulls the image of every
# such service anyway (ws4channels is a large amd64-only image). So the services to pull and start are named: all of
# them, less those two while the weather channel is off. With the current file, where they are behind a profile, this
# changes nothing. Run in the install folder, by this script and by the update timer ($Q: --quiet).
UPDATE='set -e
only=""
grep -Eqs "'"$WEATHER_ON"'" .env || only=$(docker compose config --services | grep -vx -e ws4kp -e ws4channels || true)
docker compose pull $Q $only
docker compose up -d $only'

in_fstab() { awk -v m="$1" '$1 !~ /^#/ && $2 == m { f = 1 } END { exit !f }' /etc/fstab; }
has_systemd() { [ -d /run/systemd/system ]; }

smb_cred() { printf '/root/.smb-fs42%s' "${1//[!A-Za-z0-9._-]/-}"; }     # /mnt/media -> /root/.smb-fs42-mnt-media

# .env is read by Docker Compose and by the shell (setup-dirs.sh sources it). Unquoted, Compose expands a $ and cuts
# the value at " #", and the shell splits it at a space. In single quotes both take it as it is, but neither can hold
# an apostrophe the same way, so main refuses one before any work starts.
setenv() {         # setenv KEY VALUE: replaces that line of .env and keeps the rest
  local val=$2
  case $val in *[!A-Za-z0-9_./:@%+,=-]*) val="'$val'" ;; esac
  ( umask 077; { grep -v "^$1=" .env 2> /dev/null || true; printf '%s=%s\n' "$1" "$val"; } > .env.tmp )
  mv .env.tmp .env
}

envget() {         # envget KEY: its value in an install's .env from an earlier run ("" when there is none)
  [ -f "$FS42_DIR/.env" ] || return 0
  sed -n "s/^$1=//p" "$FS42_DIR/.env" | tail -n 1 | sed "s/^'\(.*\)'\$/\1/"
}

add_share() {      # add_share smb|nfs <mount point>: the tools, the password file and the /etc/fstab line
  local kind=$1 mp=$2 src=${FS42_SHARE// /\\040} opts=ro,_netdev,nofail cred
  cred=$(smb_cred "$mp")
  if [ "$kind" = smb ]; then
    command -v mount.cifs > /dev/null || pkg cifs-utils cifs-utils
    if [ -n "$FS42_SHARE_USER" ]; then
      printf 'username=%s\npassword=%s\n' "$FS42_SHARE_USER" "$FS42_SHARE_PASS" |
        $SUDO sh -c 'umask 077; cat > "$1"' _ "$cred"
      opts=$opts,iocharset=utf8,credentials=$cred
    else
      opts=$opts,iocharset=utf8,guest
    fi
    kind=cifs
  else
    command -v mount.nfs > /dev/null || pkg nfs-common nfs-utils
  fi
  $SUDO cp /etc/fstab /etc/fstab.fs42.bak
  printf '%s %s %s %s 0 0\n' "$src" "$mp" "$kind" "$opts" | $SUDO tee -a /etc/fstab > /dev/null
}

mount_share() {    # mount_share <mount point> <"new" when add_share just wrote its fstab line>
  local mp=$1 unit
  $SUDO mkdir -p "$mp"
  if has_systemd; then $SUDO systemctl daemon-reload; fi
  if ! mountpoint -q "$mp" && ! $SUDO mount "$mp"; then
    if [ "${2-}" = new ]; then
      $SUDO cp /etc/fstab.fs42.bak /etc/fstab
      $SUDO rm -f "$(smb_cred "$mp")"
      die "could not mount $FS42_SHARE (the error is above). /etc/fstab is back as it was: check the share's name, the user and the password, and run this again"
    fi
    die "could not mount $mp with the line /etc/fstab already has for it (the error is above)"
  fi
  ok "$mp is mounted (read-only), and will be at every boot"
  # nofail lets the machine boot with the NAS off, but then nothing waits for the share: a container started before it
  # is mounted sees an empty folder until it is restarted. So Docker starts after the mount has been tried.
  if has_systemd; then
    unit=$(systemd-escape -p --suffix=mount "$mp")
    $SUDO mkdir -p /etc/systemd/system/docker.service.d
    printf '[Unit]\nAfter=%s\n' "$unit" | $SUDO tee /etc/systemd/system/docker.service.d/fs42-media.conf > /dev/null
    $SUDO systemctl daemon-reload
  fi
}

install_docker() {
  if ! command -v docker > /dev/null; then
    say "Installing Docker (get.docker.com)"
    curl -fsSL https://get.docker.com | $SUDO sh ||
      die "Docker's installer did not work here: install Docker Engine and its compose plugin yourself, then run this again"
  fi
  if docker info > /dev/null 2>&1; then
    DOCKER="docker" AS=""
  else                                        # not running yet, or this user may not use it
    if has_systemd; then $SUDO systemctl enable --now docker > /dev/null 2>&1 || true; fi
    DOCKER="$SUDO docker" AS=$SUDO
  fi
  $DOCKER info > /dev/null 2>&1 || die "Docker is installed but not running (try: sudo systemctl start docker)"
  $DOCKER compose version > /dev/null 2>&1 || die "this Docker has no 'docker compose': install the docker-compose-plugin package, then run this again"
  ok "$($DOCKER --version)"
  # Rootless Docker is this user's own daemon: root's timer would talk to another one (or none).
  ROOTLESS=""
  if $DOCKER info --format '{{.SecurityOptions}}' 2> /dev/null | grep -q rootless; then ROOTLESS=1; fi
}

auto_update() {    # a systemd timer: pull the newest image, restart only if it changed
  local when bin why
  if ! has_systemd || [ -n "$ROOTLESS" ]; then
    if [ -n "$ROOTLESS" ]; then why="rootless Docker runs as you, and the timer would run as root"; else why="there is no systemd here"; fi
    [ "$FS42_AUTO_UPDATE" = no ] || warn "no update timer: $why. A cron line of your own does the same: cd $DIR && docker compose pull && docker compose up -d"
    return 0
  fi
  if [ "$FS42_AUTO_UPDATE" = no ]; then
    if [ -e /etc/systemd/system/fs42-update.timer ]; then
      $SUDO systemctl disable --now fs42-update.timer > /dev/null 2>&1 || true
      $SUDO rm -f /etc/systemd/system/fs42-update.timer /etc/systemd/system/fs42-update.service /usr/local/sbin/fs42-update
      ok "automatic updates are off"
    fi
    return 0
  fi
  case $FS42_AUTO_UPDATE in daily) when='*-*-* 04:30' ;; *) when='Sun 04:30' ;; esac
  bin=$(command -v docker)
  $SUDO mkdir -p /usr/local/sbin
  $SUDO tee /usr/local/sbin/fs42-update > /dev/null << EOF
#!/bin/sh
# Station Wrapper 43's update, run in the install folder by fs42-update.service (written by install.sh).
PATH=${bin%/*}:\$PATH Q=--quiet
$UPDATE
docker image prune -f --filter "label=org.opencontainers.image.title=Station Wrapper 43"
EOF
  $SUDO chmod 755 /usr/local/sbin/fs42-update
  $SUDO tee /etc/systemd/system/fs42-update.service > /dev/null << EOF
[Unit]
Description=Station Wrapper 43: install the newest version
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory=$DIR
ExecStart=/usr/local/sbin/fs42-update
EOF
  # Persistent: a machine that was off at 04:30 (a player PC) updates when it is next switched on.
  $SUDO tee /etc/systemd/system/fs42-update.timer > /dev/null << EOF
[Unit]
Description=Station Wrapper 43: check for a new version ($FS42_AUTO_UPDATE)

[Timer]
OnCalendar=$when
Persistent=true

[Install]
WantedBy=timers.target
EOF
  $SUDO systemctl daemon-reload
  $SUDO systemctl enable --now fs42-update.timer > /dev/null
  ok "updates install themselves $FS42_AUTO_UPDATE at 04:30 (now: sudo systemctl start fs42-update; off: run this again and answer no)"
}

main() {
  local mp="" share_new="" compose code ip old_root v

  cat << EOF
${C}   ___________
  |  .-----.  |${N}   ${B}Station Wrapper 43${N}${C}
  |  | 4 3 |  o|${N}  your own cable TV network${C}
  |  '-----'  o|
  '-----------'${N}

EOF
  [ "$(uname -s)" = Linux ] || die "this installs on Linux. On a Mac or Windows, use Docker Desktop and the compose file (see the README)"
  if [ "$(id -u)" = 0 ]; then SUDO=""; else command -v sudo > /dev/null || die "run this as root, or install sudo"; SUDO=sudo; fi

  case ${FS42_IMAGE-} in *[!A-Za-z0-9._/:-]*) die "FS42_IMAGE is not an image's name: $FS42_IMAGE" ;; esac

  # ---- the questions --------------------------------------------------------------------------------------------
  choose FS42_ROLE "What is this machine? server = builds the channels, client = a player PC on a TV, playing a server's" server server client
  if [ "$FS42_ROLE" = server ]; then
    ask FS42_DIR "Folder for the compose file and the container's data (a local disk, not a share)" "$HOME/station-wrapper-43"
    # An Emby or Jellyfin server's videos are streamed from it, through placeholders the server makes: nothing to mount.
    choose FS42_EMBY "Do you have an Emby or Jellyfin server whose shows and movies you want on your channels?" n y n
    old_root=$(envget FS42_MEDIA_ROOT)        # an earlier run's answer is the default, so Enter all the way keeps it
    if [ "$FS42_EMBY" = y ]; then
      # Asked for a folder or a share (an unattended run), or has one already: then there are videos of its own.
      [ -z "${FS42_MEDIA-}${FS42_MEDIA_ROOT-}" ] || FS42_OWN_VIDEOS=${FS42_OWN_VIDEOS:-y}
      choose FS42_OWN_VIDEOS "Do you also have videos that are not in Emby or Jellyfin (on this machine, or a NAS share)?" "$([ -n "$old_root" ] && echo y || echo n)" y n
    else
      FS42_OWN_VIDEOS=y
    fi
    if [ "$FS42_OWN_VIDEOS" = n ]; then
      FS42_MEDIA=local FS42_MEDIA_ROOT=""     # no videos of its own: the empty 'media' folder beside the compose file
    else
      choose FS42_MEDIA "Where are your videos? local = on this machine, smb = a Windows or NAS share, nfs = an NFS share" local local smb nfs
      if [ "$FS42_MEDIA" = local ]; then
        ask FS42_MEDIA_ROOT "The folder with your videos$([ -n "$old_root" ] || echo " (empty: a new 'media' folder beside the compose file)")" "$old_root"
        [ -z "$FS42_MEDIA_ROOT" ] || [ -d "$FS42_MEDIA_ROOT" ] || warn "$FS42_MEDIA_ROOT is not there yet"
      else
        need FS42_MEDIA_ROOT "Mount the share at" "${old_root:-/mnt/media}"
        mp=$FS42_MEDIA_ROOT
      fi
    fi
    # The weather channel's hidden browser (ws4channels) is built for amd64 only, so an ARM machine is not asked.
    if grep -Eqs "$WEATHER_ON" "$FS42_DIR/.env"; then
      FS42_WEATHER=n                          # already on: the dashboard's Settings page has its place
    elif case $(uname -m) in x86_64 | amd64) true ;; *) false ;; esac; then
      choose FS42_WEATHER "Add a Weather channel? A WeatherStar 4000 forecast for a place in the United States; it takes about one CPU core and 1 GB of memory all day" n y n
      [ "$FS42_WEATHER" = n ] || need WEATHER_LOCATION "Where? A ZIP code, or City, State"
    else
      [ "${FS42_WEATHER-n}" = n ] || warn "no Weather channel on this machine: it needs an ordinary PC (amd64), and this is $(uname -m)"
      FS42_WEATHER=n
    fi
  else
    ask FS42_DIR "Folder for the compose file and the copied schedule (a local disk, not a share)" "$HOME/fs42-player"
    need FS42_SERVER "The server's address, as http://<server>:5004"
    case $FS42_SERVER in http://* | https://*) ;; *) FS42_SERVER=http://$FS42_SERVER ;; esac
    need FS42_SYNC_TOKEN "The server's sync token (its dashboard: Settings > Players > Show)"
    choose FS42_SCREEN "The screen: hd = 16:9, whole picture; crt = 4:3, widescreen cropped to fill it" hd hd crt
    ask FS42_PLAYER_NAME "A name for this player on the server's Status page" "$(hostname)"
    # The schedule names every video by its path on the server, /mnt/media/...: a player needs the same share there.
    mp=/mnt/media
    if mountpoint -q $mp; then FS42_MEDIA=${FS42_MEDIA:-local}; fi
    choose FS42_MEDIA "The server's media must be at $mp here too. local = it already is (or the server only has Emby or Jellyfin videos), smb / nfs = mount that share there" smb local smb nfs
    [ "$FS42_MEDIA" != local ] || mp=""
  fi
  case $mp in *[[:space:]]*) die "a mount point can't have a space in it: $mp" ;; esac
  if [ -n "$mp" ]; then
    if mountpoint -q "$mp" || in_fstab "$mp"; then
      ok "$mp is already mounted or in /etc/fstab: left as it is"
    elif [ "$FS42_MEDIA" = smb ]; then
      share_new=new
      need FS42_SHARE "The share, as //server/share"
      FS42_SHARE=${FS42_SHARE//\\//}          # \\nas\media, typed the Windows way
      ask FS42_SHARE_USER "Its user name (empty: guest, no password)" ""
      [ -z "$FS42_SHARE_USER" ] || ask FS42_SHARE_PASS "Its password (kept in $(smb_cred "$mp"), which only root can read)" "" secret
    else
      share_new=new
      need FS42_SHARE "The export, as server:/path"
    fi
  fi
  for v in FS42_MEDIA_ROOT FS42_SERVER FS42_SYNC_TOKEN FS42_PLAYER_NAME WEATHER_LOCATION; do
    case ${!v-} in *\'* | *$'\n'*) die "$v can't have an apostrophe or a line break in it: .env can't hold one (for a place, use its ZIP code)" ;; esac
  done
  choose FS42_AUTO_UPDATE "Check for a new version and install it by itself? (a server and its players must run the same version: answer the same on each)" weekly no daily weekly

  echo
  say "About to set up a $FS42_ROLE in $FS42_DIR"
  command -v docker > /dev/null || echo "  - install Docker"
  [ -z "$share_new" ] || echo "  - mount $FS42_SHARE at $mp, read-only, with a line in /etc/fstab"
  echo "  - download the compose file, write .env, start the container"
  [ "${FS42_EMBY-n}" = n ] || echo "  - Emby or Jellyfin: you add the server on the dashboard afterwards (the last lines say where)"
  [ "${FS42_WEATHER-n}" = n ] || echo "  - add a Weather channel for $WEATHER_LOCATION (two more small containers)"
  [ "$FS42_AUTO_UPDATE" = no ] || echo "  - install new versions by itself, $FS42_AUTO_UPDATE"
  ask FS42_GO "Go ahead? (y/n)" y
  case $FS42_GO in y* | Y*) ;; *) die "stopped: nothing was changed" ;; esac

  # ---- the work -------------------------------------------------------------------------------------------------
  install_docker
  if [ -n "$mp" ]; then
    say "The media share"
    [ -z "$share_new" ] || add_share "$FS42_MEDIA" "$mp"
    mount_share "$mp" $share_new
  fi

  say "The container"
  mkdir -p "$FS42_DIR"
  cd "$FS42_DIR"
  DIR=$PWD
  if [ "$FS42_ROLE" = server ]; then
    compose=docker-compose.yml
    [ -z "${FS42_MEDIA_ROOT-}" ] || setenv FS42_MEDIA_ROOT "$FS42_MEDIA_ROOT"
    # "No videos of my own" on a server that had a folder: back to the empty 'media' folder beside the compose file.
    [ "$FS42_OWN_VIDEOS" = y ] || sed -i '/^FS42_MEDIA_ROOT=/d' .env 2> /dev/null || true
    # Beside videos of your own, the Emby folder only shows on the Files page once the pool of links is on.
    [ "$FS42_EMBY$FS42_OWN_VIDEOS" != yy ] || setenv SYNC_ENABLED 1
    [ "$FS42_WEATHER" != y ] || setenv WEATHER_LOCATION "$WEATHER_LOCATION"
    if [ "$FS42_WEATHER" = y ] || grep -Eqs "$WEATHER_ON" .env; then
      # Both of the switch's names, so it is on with either compose file: the current one starts ws4kp and
      # ws4channels for the profile, and the first start then adds the channel.
      v=$(envget COMPOSE_PROFILES)
      case ",$v," in *,weather,*) ;; *) setenv COMPOSE_PROFILES "${v:+$v,}weather" ;; esac
      setenv WEATHER_CHANNEL 1
    fi
  else
    compose=client/docker-compose.client.yml
    setenv FS42_SERVER "$FS42_SERVER"
    setenv FS42_SYNC_TOKEN "$FS42_SYNC_TOKEN"
    setenv FS42_SCREEN "$FS42_SCREEN"
    setenv FS42_PLAYER_NAME "$FS42_PLAYER_NAME"
    code=$(curl -s -o /dev/null -m 10 -w '%{http_code}' -H "Authorization: Bearer $FS42_SYNC_TOKEN" "${FS42_SERVER%/}/sync/state" || true)
    case $code in
      200 | 304) ok "the server answers and takes the token" ;;
      403) warn "the server refused the sync token: put the right one in $DIR/.env, then: docker compose up -d" ;;
      *) warn "no answer from $FS42_SERVER yet (the player keeps trying once it is up)" ;;
    esac
    [ "$(systemctl get-default 2> /dev/null)" != graphical.target ] ||
      warn "this machine starts a desktop, and the player needs the screen to itself: sudo systemctl set-default multi-user.target, then reboot"
  fi
  if [ -e docker-compose.yml ]; then
    ok "kept the docker-compose.yml that is already here"
  else
    curl -fsSL "$RAW/$compose" -o docker-compose.yml || die "could not download $RAW/$compose"
    [ -z "${FS42_IMAGE-}" ] || sed -i "s#$STOCK_IMAGE#$FS42_IMAGE#" docker-compose.yml
  fi
  Q="" $AS sh -c "$UPDATE"
  ok "started"

  auto_update

  echo
  if [ "$FS42_ROLE" = server ]; then
    ip=$(hostname -I 2> /dev/null | awk '{ print $1 }')
    say "Done. The dashboard: http://${ip:-<this machine>}:5004 (the first visit sets its password)"
    if [ "$FS42_EMBY" = y ]; then
      echo "  Next, your Emby or Jellyfin server: http://${ip:-<this machine>}:5004/settings.html#sources (Settings, the Sources tab), under 'Emby and Jellyfin servers'."
      echo "    Sign in with Emby Connect, or add an Emby or Jellyfin server by its address. Choose libraries, then 'Scan the servers now'."
      echo "    Its shows and movies are then on the Lists & files tab of Settings, in the Emby folder."
    fi
    [ "$FS42_WEATHER" = n ] || echo "  Weather comes on air in a minute or two (channel 3, or the next free number). Its place: the Settings page."
  else
    say "Done. The TV should come on within a minute or two; the server's Status page lists this player."
    echo "  It must use the server's time zone (this machine: $(timedatectl show -p Timezone --value 2> /dev/null || cat /etc/timezone 2> /dev/null || echo unknown))."
  fi
  echo "  Settings: $DIR/.env    Logs: cd $DIR && docker compose logs -f"
}

main "$@"   # at the very end, so a download that was cut off runs nothing
