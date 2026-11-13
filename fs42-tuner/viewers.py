"""Viewer accounts for the web viewer: the player in a container of its own (viewer.py), where each person logs in
and sees only the channels picked for them.

Kept apart from the dashboard's one password (auth.py), whose file handling, slow hash and guess limit are reused.
One folder (config/viewers) is shared by the two containers, and each writes a file of its own in it, so neither
ever overwrites the other's change:
  viewers.json   the dashboard's: for each user the salted hash of the password and the channel numbers (null =
                 every channel), the signing secret, and the on/off switch
  sessions.json  the viewer's: sessions that were logged out
  alive          the viewer's: touched every half minute, so the dashboard can say whether it is running
A session is signed with the secret AND that user's hash, so a new password or a removed user ends that user's
sessions, and nobody else's.

The dashboard's own port stays open for watching, so these accounts only limit people who can reach the viewer and
not the dashboard.
"""
import hashlib
import hmac
import os
import re
import secrets

import auth as authmod
from auth import AuthError

NAME = re.compile(r"[a-z0-9_-]{1,32}")       # lower case only: a phone's keyboard capitalises the first letter


def _name(name):
    return name.strip().lower() if isinstance(name, str) else ""


class Viewers(authmod.Auth):
    def __init__(self, path, **kw):
        super().__init__(path, **kw)
        folder = os.path.dirname(path)
        self._sessions = authmod.Auth(os.path.join(folder, "sessions.json"))      # only its _load / _save: a second JSON file
        self._alive = os.path.join(folder, "alive")

    # ---- the switch on the dashboard's Players tab, and whether the viewer's container is there to obey it
    def is_on(self):
        return self._load().get("on", True) is not False

    def switch(self, on):
        data = self._load()
        data["on"] = bool(on)
        self._save(data)

    def beat(self):
        """The viewer says it is running."""
        with open(self._alive, "a"):
            pass
        os.utime(self._alive, (self.clock(), self.clock()))

    def running(self):
        try:
            return self.clock() - os.path.getmtime(self._alive) < 90
        except OSError:
            return False

    def _users(self):
        users = self._load().get("users")
        return users if isinstance(users, dict) else {}

    def list(self):
        """Every user and their channels (None = all). Never the hashes."""
        return [{"name": n, "channels": u.get("channels")} for n, u in sorted(self._users().items())]

    def channels(self, name):
        """The set of channel numbers this user may watch, or None for every channel."""
        only = (self._users().get(name) or {}).get("channels")
        return None if only is None else set(only)

    def save(self, name, password=None, channels=None):
        """Add a user or change one. No password keeps the one they have; channels None means every channel."""
        name = _name(name)
        if not NAME.fullmatch(name):
            raise AuthError("a user name is 1 to 32 letters, digits, - or _")
        if channels is not None and not (isinstance(channels, list) and len(channels) <= 5000
                                         and all(isinstance(c, str) and 0 < len(c) <= 16 for c in channels)):
            raise AuthError("the channels must be a list of channel numbers")
        data = self._load()
        users = self._users()
        user = dict(users.get(name) or {})
        if password:
            self.check_new(password)
            salt = secrets.token_bytes(16)
            user["hash"] = f"pbkdf2_sha256${authmod.ITERATIONS}${salt.hex()}${authmod._hash(password, salt).hex()}"
        elif "hash" not in user:
            raise AuthError("a new user needs a password")
        user["channels"] = None if channels is None else sorted(set(channels))
        users[name] = user
        data["users"] = users
        data.setdefault("secret", secrets.token_hex(32))
        self._save(data)

    def remove(self, name):
        data = self._load()
        users = self._users()
        if users.pop(_name(name), None) is None:
            raise AuthError("there is no such user")
        data["users"] = users
        self._save(data)

    def verify(self, name, password):
        if not isinstance(password, str) or len(password) > authmod.MAX_LENGTH:
            return False
        try:
            _, iterations, salt, digest = self._users()[_name(name)]["hash"].split("$")
            want = bytes.fromhex(digest)
            got = authmod._hash(password, bytes.fromhex(salt), int(iterations))
        except (KeyError, TypeError, ValueError, AttributeError):
            authmod._hash(password, b"\0" * 16)      # spend the same time, so an unknown user is not a tell
            return False
        return hmac.compare_digest(got, want)

    # ---- sessions: expiry.nonce.name.signature
    def _sig(self, payload, name):
        data = self._load()
        user = self._users().get(name)
        if not user or not user.get("hash") or not data.get("secret"):
            return None
        return hmac.new((data["secret"] + user["hash"]).encode(), payload.encode(), hashlib.sha256).hexdigest()

    def make_session(self, name):
        payload = f"{int(self.clock()) + authmod.SESSION_SECONDS}.{secrets.token_hex(8)}.{name}"
        return f"{payload}.{self._sig(payload, name)}"

    def _parse(self, token):
        """(expiry, nonce, name) of a token that is correctly signed, not expired, and whose user still exists."""
        try:
            expiry, nonce, name, sig = token.split(".")
            want = self._sig(f"{expiry}.{nonce}.{name}", name)
            if want is None or int(expiry) <= self.clock():
                return None
        except (ValueError, AttributeError):
            return None
        return (int(expiry), nonce, name) if hmac.compare_digest(sig.encode(), want.encode()) else None

    def user(self, token):
        """Whose session this is, or None."""
        parsed = self._parse(token)
        return parsed[2] if parsed and parsed[1] not in self._sessions._load() else None

    def revoke(self, token):
        """Log a session out for good. Kept in sessions.json until the session would have expired anyway."""
        parsed = self._parse(token)
        if parsed:
            now = self.clock()
            gone = {n: e for n, e in self._sessions._load().items() if isinstance(e, int) and e > now}
            gone[parsed[1]] = parsed[0]
            self._sessions._save(gone)

    def login(self, name, password, who="?"):
        """A session token for the right name and password. AuthError otherwise, or when too many were tried."""
        wait = self.blocked_for(who)
        if wait:
            raise AuthError(f"too many wrong passwords: wait {wait} seconds and try again")
        if not self.verify(name, password):
            self.failed(who)
            raise AuthError("that name or password is not right")
        self.succeeded(who)
        return self.make_session(_name(name))
