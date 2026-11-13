"""The web viewer: the player for people watching in a browser, in a container of its own.

This is the one part meant to be reached from outside the house (behind a reverse proxy that does HTTPS), so it is
kept away from everything else: it has no media, no schedule and no settings, only the folder of viewer accounts
(viewers.py). Each viewer logs in and gets the player page, and what that page reads is fetched from the server
(FS42_SERVER, the dashboard's port, which stays private) and cut down to that viewer's channels. A stream is passed
on chunk by chunk. Anything not listed in Handler is a 404.

  FS42_SERVER             the server's dashboard port                     http://station-wrapper-43:5004
  VIEWER_DIR              the accounts folder (the server's config/viewers)  /viewers
  VIEWER_PORT             the port inside the container                    5005
  VIEWER_TRUSTED_PROXIES  addresses or networks of your reverse proxy, comma separated: its X-Forwarded-For is
                          believed, so wrong passwords are counted for each visitor and not for the proxy
  VIEWER_MAX_STREAMS      streams one viewer may have open at once         3

Run: python3 viewer.py (the compose file's `viewer` service does).
"""
import http.client
import http.cookies
import ipaddress
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import auth as authmod
import guide
import viewers

SERVER = (os.environ.get("FS42_SERVER") or "http://station-wrapper-43:5004").rstrip("/")
DIR = os.environ.get("VIEWER_DIR") or "/viewers"
PORT = int(os.environ.get("VIEWER_PORT") or 5005)
MAX_STREAMS = int(os.environ.get("VIEWER_MAX_STREAMS") or 3)
MAX_CONNECTIONS = 200               # open at once, from everybody: more are closed as they arrive
IDLE_SECONDS = float(os.environ.get("VIEWER_IDLE_SECONDS") or 30)       # a connection that says or takes nothing for this long is dropped
RECHECK_SECONDS = float(os.environ.get("VIEWER_RECHECK_SECONDS") or 15)  # how often an open stream asks whether its viewer may still watch
TRUSTED = [ipaddress.ip_network(n.strip(), strict=False) for n in os.environ.get("VIEWER_TRUSTED_PROXIES", "").split(",") if n.strip()]
USERS = viewers.Viewers(os.path.join(DIR, "viewers.json"))
COOKIE = "sw43_viewer"

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
STATIC_TYPES = {".html": "text/html; charset=utf-8", ".js": "application/javascript", ".css": "text/css"}
OPEN = {"/login.html", "/login.js", "/app.css"}                              # the login page and what it loads
FILES = {"/app.js", "/common.js", "/player.css", "/mpegts.min.js"}           # what the player page loads
CHANNEL = re.compile(r"[A-Za-z0-9.\-]{1,16}")
CAPTIONS = re.compile(r"[A-Za-z0-9.\-]{1,16}(\.json|/[A-Za-z0-9]{1,64}/[A-Za-z0-9_.\-]{1,64}\.vtt)")
OFF_PAGE = b"<!doctype html><title>Switched off</title><p>The web viewer is switched off.</p>"

STREAMS, STREAMS_LOCK = {}, threading.Lock()         # viewer -> streams open now
CACHE, CACHE_LOCK = {}, threading.Lock()             # path -> (fetched at, body)


class Upstream(Exception):
    """The server did not give us what was asked for. `code` is what the viewer is told."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


def ask(path, keep=0):
    """What the server answers for `path` (one of ours, never a viewer's own text), kept for `keep` seconds."""
    with CACHE_LOCK:
        hit = CACHE.get(path)
        if hit and time.time() - hit[0] < keep:
            return hit[1]
    try:
        with urllib.request.urlopen(SERVER + path, timeout=20) as r:  # nosec B310 - our own server, from the compose file
            body = r.read()
    except urllib.error.HTTPError as e:
        raise Upstream(e.code if e.code in (404, 503) else 502) from None
    except OSError:
        raise Upstream(502) from None
    if keep:
        with CACHE_LOCK:
            CACHE[path] = (time.time(), body)
    return body


def trusted(address):
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return any(ip in net for net in TRUSTED)


def static(path):
    """(body, type) of a file under static/, or None. The caller has already checked the path is one we serve."""
    full = os.path.normpath(os.path.join(STATIC_DIR, path.lstrip("/")))
    if os.path.commonpath([full, STATIC_DIR]) != STATIC_DIR or not os.path.isfile(full):
        return None
    with open(full, "rb") as f:
        return f.read(), STATIC_TYPES.get(os.path.splitext(full)[1], "application/octet-stream")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    timeout = IDLE_SECONDS
    server_version, sys_version = "sw43-viewer", ""
    # no do_HEAD: nothing here needs it, and http.server answers 501 for a method it has no handler for

    def log_message(self, *a):
        pass

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        super().end_headers()

    def _bytes(self, body, ctype, code=200, headers=(), cache="no-store"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200, headers=()):
        self._bytes(json.dumps(obj).encode(), "application/json", code, headers)

    def _error(self, code, text=""):
        self._json({"error": text or self.responses.get(code, ("error",))[0]}, code)

    def _token(self):
        jar = http.cookies.SimpleCookie()
        try:
            jar.load(self.headers.get("Cookie", ""))
        except http.cookies.CookieError:
            return None
        return jar[COOKIE].value if COOKIE in jar else None

    def _cookie(self, value, max_age):
        flags = f"{COOKIE}={value}; Path=/; HttpOnly; SameSite=Strict; Max-Age={max_age}"
        if self.headers.get("X-Forwarded-Proto", "") == "https":
            flags += "; Secure"
        return ("Set-Cookie", flags)

    def _who(self):
        """The visitor's address, for counting wrong passwords: the last hop in X-Forwarded-For that is not one of
        our own proxies, when the request came through one. A header from anyone else is not believed."""
        peer = self.client_address[0]
        if not trusted(peer):
            return peer
        for hop in reversed([h.strip() for h in self.headers.get("X-Forwarded-For", "").split(",") if h.strip()]):
            if not trusted(hop):
                try:
                    return str(ipaddress.ip_address(hop))
                except ValueError:
                    break
        return peer

    def do_GET(self):
        u = urlparse(self.path)
        p = u.path
        if not USERS.is_on():                         # the switch on the dashboard's Players tab
            return self._bytes(OFF_PAGE, "text/html; charset=utf-8", 503)
        name = USERS.user(self._token())
        if p == "/api/auth/status":                   # in the dashboard's own words, so its login page works here too
            return self._json({"login": True, "viewer": True, "has_password": True, "setup_needed": False,
                               "authenticated": bool(name), "user": name})
        if p in OPEN or p.startswith("/vendor/"):
            got = static(p)
            return self._bytes(*got, cache="no-cache") if got else self._error(404)
        if name is None:
            if p not in ("/", "/watch.html"):
                return self._json({"error": "log in first", "login": "/login.html"}, 401)
            return self._bytes(b"", "text/plain", 302, [("Location", "/login.html")])
        only = USERS.channels(name)                   # None: every channel

        try:
            if p in ("/", "/watch.html"):             # the same page, told who is watching and without the dashboard's bar
                page = static("/watch.html")[0].replace(b'data-page="watch"', f'data-page="" data-viewer="{name}"'.encode())
                return self._bytes(page, "text/html; charset=utf-8", cache="no-cache")
            if p in FILES:
                got = static(p)
                return self._bytes(*got, cache="no-cache") if got else self._error(404)
            if p == "/lineup.json":                   # number and name only: the addresses in it are the server's private ones
                rows = [{"GuideNumber": r["GuideNumber"], "GuideName": r.get("GuideName")} for r in json.loads(ask(p, keep=15))]
                return self._json([r for r in rows if only is None or str(r["GuideNumber"]) in only])
            if p == "/xmltv.xml":
                body = ask(p, keep=60)
                if only is not None:
                    body = guide.only_channels(body, only)
                return self._bytes(re.sub(rb"<icon\b[^>]*/>", b"", body), "application/xml")     # pictures are at private addresses too
            if p == "/system.json":                   # the quality list's top rate, and nothing about the machine
                return self._json({"video_kbps": json.loads(ask(p, keep=60)).get("video_kbps")})
            if p.startswith("/captions/") and CAPTIONS.fullmatch(p[len("/captions/"):]):
                rest = p[len("/captions/"):]
                num = rest.split("/")[0]
                if only is not None and (num[:-5] if num.endswith(".json") else num) not in only:
                    return self._error(403, "that channel is not one of yours")
                return self._bytes(ask(p), "application/json" if rest.endswith(".json") else "text/vtt; charset=utf-8")
            if p.startswith("/auto/v") and CHANNEL.fullmatch(p[len("/auto/v"):]):
                num = p[len("/auto/v"):]
                if only is not None and num not in only:
                    return self._error(403, "that channel is not one of yours")
                return self._stream(name, num, parse_qs(u.query).get("kbps", [""])[0])
        except Upstream as e:
            return self._error(e.code, "the TV server did not answer" if e.code == 502 else "")
        except ValueError:                            # the server answered, but not with what this page reads
            return self._error(502, "the TV server did not answer")
        self._error(404)

    def _stream(self, name, num, kbps):
        """Pass a channel on from the server, for as long as this viewer may watch it and keeps reading."""
        with STREAMS_LOCK:
            if STREAMS.get(name, 0) >= MAX_STREAMS:
                return self._error(429, "too many streams are open for you: close one and try again")
            STREAMS[name] = STREAMS.get(name, 0) + 1
        self.close_connection = True
        try:
            url = f"{SERVER}/auto/v{num}" + (f"?kbps={int(kbps)}" if kbps.isdigit() else "")
            req = urllib.request.Request(url, headers={"User-Agent": f"sw43-web-viewer ({name})"})
            try:
                up = urllib.request.urlopen(req, timeout=20)  # nosec B310 - our own server, from the compose file
            except urllib.error.HTTPError as e:           # no such channel, or every tuner is in use
                return self._error(e.code if e.code in (404, 503) else 502)
            except OSError:
                return self._error(502, "the TV server did not answer")
            with up:
                self.send_response(200)
                self.send_header("Content-Type", "video/mp2t")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Connection", "close")
                self.end_headers()
                token, check = self._token(), time.time() + RECHECK_SECONDS
                while True:
                    chunk = up.read1(65536)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    if time.time() > check:               # logged out, removed, the channel taken away or the viewer switched off
                        only, check = USERS.channels(name), time.time() + RECHECK_SECONDS
                        if not USERS.is_on() or USERS.user(token) != name or (only is not None and num not in only):
                            break
        except (OSError, http.client.HTTPException):      # the viewer left, stopped reading, or the server's side broke
            pass
        finally:
            with STREAMS_LOCK:
                STREAMS[name] -= 1

    def do_POST(self):
        p = urlparse(self.path).path
        self.close_connection = True                      # a body we refuse is not read
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = -1
        if p not in ("/api/auth/login", "/api/auth/logout") or not USERS.is_on():
            return self._error(404 if USERS.is_on() else 503)
        # JSON only: a page on another site can send a form to here, but not this (the browser asks first)
        if "application/json" not in self.headers.get("Content-Type", "") or not 0 <= length <= 10_000:
            return self._error(415 if 0 <= length <= 10_000 else 413)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            body = None
        if not isinstance(body, dict):
            return self._error(400, "that is not valid JSON")
        self.close_connection = False
        if p.endswith("/logout"):
            try:
                USERS.revoke(self._token())               # dead everywhere, not only cleared in this browser
            except OSError:
                pass
            return self._json({"ok": True}, headers=[self._cookie("", 0)])
        try:
            token = USERS.login(body.get("user"), body.get("password"), self._who())
        except authmod.AuthError as e:
            return self._error(401, str(e))
        self._json({"ok": True}, headers=[self._cookie(token, authmod.SESSION_SECONDS)])


class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 64
    slots = threading.BoundedSemaphore(MAX_CONNECTIONS)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):        # full: this one is closed at once, the others carry on
            return self.shutdown_request(request)
        super().process_request(request, client_address)

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()

    def handle_error(self, request, client_address):      # a visitor who hung up or timed out is not news
        pass


def drop_root():
    """Started as root (the compose file gives it nothing but the right to do this): become whoever owns the accounts
    folder, which is who the dashboard writes its files as. A folder root owns leaves us root, with no capabilities."""
    if os.geteuid() == 0:
        st = os.stat(DIR)
        if st.st_uid:
            os.setgroups([])
            os.setgid(st.st_gid)
            os.setuid(st.st_uid)


def heartbeat():
    while True:
        try:
            USERS.beat()
        except OSError as e:
            print(f"! could not write to {DIR}: {e.strerror}", flush=True)
        time.sleep(30)


if __name__ == "__main__":
    drop_root()
    threading.Thread(target=heartbeat, daemon=True, name="heartbeat").start()
    print(f"Station Wrapper 43 web viewer on :{PORT}, for {SERVER} ({len(USERS.list())} viewers, "
          f"{'on' if USERS.is_on() else 'switched off'}; proxies believed: {', '.join(map(str, TRUSTED)) or 'none'})", flush=True)
    Server(("0.0.0.0", PORT), Handler).serve_forever()  # nosec B104 - a server in a container: every address is the point
