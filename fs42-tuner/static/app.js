// The Watch page: the web player. An Alpine component holds what the controls show (channel, volume, quality, captions,
// the guide); the playback itself is mpegts.js, driven from here. It needs no login.
(function () {
  "use strict";

  const LAST_CHANNEL_KEY = "fs42.lastChannel";
  const VOLUME_KEY = "fs42.volume";
  const QUALITY_KEY = "fs42.quality";
  const STATS_KEY = "fs42.stats";               // "on" while the Stats readout is showing
  const CC_PREF_KEY = "fs42.captions";          // "off" or a language code ("" for a track with none)
  const CC_NUDGE_KEY = "fs42.captionsNudge";    // seconds: how far behind the clock the picture runs for this viewer
  const GUIDE_REFRESH_MS = 5 * 60 * 1000;
  const BANNER_REFRESH_MS = 15 * 1000;
  const HIDE_MS = 4000;                         // the controls fade this long after the pointer last moved
  const BANNER_SHOW_MS = 8000;                  // as long as the TV apps and a player PC show theirs
  const RETRY_MS = 3000;
  // The picture stopping without any error (a gap in the stream the player cannot get past) used to need a page
  // refresh. If a playing picture has not moved for STALL_MS, tune the channel again.
  const STALL_MS = 8000;

  const recall = (key) => { try { return localStorage.getItem(key); } catch (e) { return null; } };
  const keep = (key, value) => { try { localStorage.setItem(key, value); } catch (e) { /* private mode etc.: not remembered */ } };
  const sortKey = (num) => { const f = parseFloat(num); return Number.isNaN(f) ? Infinity : f; };

  function parseVtt(text) {
    const secs = (s) => { const p = s.replace(",", ".").split(":").map(Number); return p.length === 3 ? p[0] * 3600 + p[1] * 60 + p[2] : p[0] * 60 + p[1]; };
    const cues = [];
    for (const block of text.replace(/\r/g, "").split(/\n\n+/)) {
      const lines = block.split("\n");
      const i = lines.findIndex((l) => l.includes("-->"));
      if (i < 0) continue;
      const m = lines[i].match(/([\d:.,]+)\s*-->\s*([\d:.,]+)/);
      if (!m) continue;
      const body = lines.slice(i + 1).join("\n").replace(/<[^>]+>/g, "").replace(/\{\\[^}]*\}/g, "").replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&nbsp;/g, " ").trim();
      if (body) cues.push({ from: secs(m[1]), to: secs(m[2]), text: body });
    }
    return cues.sort((a, b) => a.from - b.from);
  }

  function parseXmltvDate(s) {
    // "YYYYMMDDHHMMSS [+-ZZZZ]" -- local-offset for fs42 blocks, +0000 for
    // anything sourced from SiliconDust. Both forms carry an explicit offset.
    const m = /^(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})\s*([+-]\d{4})?$/.exec((s || "").trim());
    if (!m) return null;
    const [, Y, Mo, D, H, Mi, S, off] = m;
    let ms = Date.UTC(+Y, +Mo - 1, +D, +H, +Mi, +S);
    if (off) {
      const sign = off[0] === "-" ? -1 : 1;
      ms -= sign * (+off.slice(1, 3) * 60 + +off.slice(3, 5)) * 60000;
    }
    return new Date(ms);
  }

  // Kept out of Alpine: the player, the guide's thousands of programmes and the caption cues are working data, not what is shown.
  let player = null;
  let speedKB = 0;        // how fast the stream is arriving, as the player last reported it (KiB a second)
  let programmes = {};   // number -> [{start, stop, title}] sorted by start
  let cues = [];
  let retryTimer = null, bannerTimer = null, toastTimer = null, idleTimer = null;
  const ccState = { eid: null, skew: 0, pos: 0, at: 0, token: 0, inBreak: false, segEnd: 0, polling: false, chosen: false };
  const stall = { last: -1, since: Date.now(), tries: 0 };

  const nowPlaying = (num) => { const now = new Date(); return (programmes[num] || []).find((p) => p.start <= now && now < p.stop) || null; };
  const upNext = (num) => { const now = new Date(); return (programmes[num] || []).find((p) => p.start > now) || null; };

  document.addEventListener("alpine:init", () => {
    Alpine.data("watchPage", () => ({
      unsupported: false,
      viewer: (document.getElementById("shell") || { dataset: {} }).dataset.viewer || "",   // who is logged in, on the web viewer's port
      channels: [],              // [{number, name}] sorted by channel number
      guide: [],                 // the same, with what is on now and next
      current: null,             // the channel tuned, as a string
      entry: "", guideOpen: false,
      banner: { show: false, num: "", name: "", clock: "", title: "", until: "" },
      toast: "",
      volume: 100, silent: true, volumeIcon: "\u{1F507}",
      kbps: 0, qualities: [{ kbps: 0, name: "Full" }], qualityTitle: "Picture quality: pick a lower one on a slow connection",
      topKbps: 4000,             // the tuner's own rate: what Full is
      stats: recall(STATS_KEY) === "on", statsText: "",
      full: false,               // the player (picture and controls) is filling the window, and the screen where the browser lets it
      idle: false,               // nothing has moved for a while: the controls are faded out
      cc: { tracks: [], track: -1, nudge: 2 },
      ccLines: [],

      async init() {
        const video = this.$refs.video;
        this.cc.nudge = Number(recall(CC_NUDGE_KEY) ?? 2) || 0;
        this.kbps = Number(recall(QUALITY_KEY)) || 0;
        const saved = recall(VOLUME_KEY);                          // the saved volume is ready for the first unmute
        if (saved !== null && Number(saved) >= 0 && Number(saved) <= 1) video.volume = Number(saved);
        this.showVolume();
        this.loadQuality();
        document.addEventListener("keydown", (e) => this.key(e));
        for (const ev of ["mousemove", "mousedown", "touchstart", "focusin"]) document.addEventListener(ev, () => this.wake(), { passive: true });
        this.wake();
        document.addEventListener("fullscreenchange", () => { if (!document.fullscreenElement) this.full = false; });    // Esc left the full screen

        if (!window.mpegts || !mpegts.isSupported()) { this.unsupported = true; return; }
        try {
          await this.loadLineup();
          await this.loadGuide();
        } catch (e) {
          this.say("Could not load channel list");
          return;
        }
        this.drawGuide();
        let start = new URLSearchParams(location.search).get("ch") || recall(LAST_CHANNEL_KEY);
        if (!start || !this.channels.some((c) => c.number === start)) start = this.channels.length ? this.channels[0].number : null;
        if (start) this.tune(start);

        setInterval(() => this.refreshGuide(), GUIDE_REFRESH_MS);
        setInterval(() => this.updateBanner(false), BANNER_REFRESH_MS);
        setInterval(() => this.watchdog(), 2000);
        setInterval(() => this.ccTick(), 200);
        setInterval(() => this.ccPollOnce(), 5000);
        setInterval(() => this.statsTick(), 1000);
      },

      async logout() {
        await fetch("/api/auth/logout", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" }).catch(() => {});
        location.assign("/login.html");
      },

      say(msg) {
        this.toast = msg;
        clearTimeout(toastTimer);
        toastTimer = setTimeout(() => { this.toast = ""; }, 4000);
      },

      // ---- the lineup and the guide
      async loadLineup() {
        const res = await fetch("/lineup.json");
        if (res.status === 401 && this.viewer) location.assign("/login.html");      // the session ended
        if (!res.ok) throw new Error(`lineup.json: ${res.status}`);
        this.channels = (await res.json())
          .map((r) => ({ number: String(r.GuideNumber), name: r.GuideName || String(r.GuideNumber) }))
          .sort((a, b) => sortKey(a.number) - sortKey(b.number));
      },
      async loadGuide() {
        const res = await fetch("/xmltv.xml");
        if (!res.ok) throw new Error(`xmltv.xml: ${res.status}`);
        const doc = new DOMParser().parseFromString(await res.text(), "application/xml");
        // Every <channel> carries its tuner channel number as a second
        // display-name (see guide.py) specifically so a consumer that only knows
        // the number, like this page, can key off it without touching ids.
        const idToNumber = {};
        doc.querySelectorAll("channel").forEach((ch) => {
          const id = ch.getAttribute("id");
          const num = Array.from(ch.querySelectorAll("display-name")).map((n) => n.textContent.trim()).find((n) => /^[0-9.]+$/.test(n));
          if (id && num) idToNumber[id] = num;
        });
        const byNumber = {};
        doc.querySelectorAll("programme").forEach((pr) => {
          const num = idToNumber[pr.getAttribute("channel")];
          const start = parseXmltvDate(pr.getAttribute("start")), stop = parseXmltvDate(pr.getAttribute("stop"));
          if (!num || !start || !stop) return;
          const titleEl = pr.querySelector("title");
          (byNumber[num] = byNumber[num] || []).push({ start, stop, title: titleEl ? titleEl.textContent : "" });
        });
        Object.values(byNumber).forEach((list) => list.sort((a, b) => a.start - b.start));
        programmes = byNumber;
      },
      drawGuide() {
        this.guide = this.channels.map((c) => {
          const now = nowPlaying(c.number), next = upNext(c.number);
          return { ...c, now: now ? now.title : "", next: next ? next.title : "" };
        });
      },
      async refreshGuide() {
        try {
          await this.loadGuide();
          this.drawGuide();
          this.updateBanner(false);
        } catch (e) {
          this.say("Guide unavailable");
        }
      },
      updateBanner(showAndFade) {
        const chan = this.channels.find((c) => c.number === this.current);
        if (!chan) return;
        const np = nowPlaying(chan.number);
        const hm = (d) => d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
        Object.assign(this.banner, { num: chan.number, name: chan.name, clock: hm(new Date()),
          title: np ? np.title : chan.name, until: np ? `until ${hm(np.stop)}` : "" });       // nothing in the guide (a camera): its name
        if (showAndFade) {
          this.banner.show = true;
          clearTimeout(bannerTimer);
          bannerTimer = setTimeout(() => { this.banner.show = false; }, BANNER_SHOW_MS);
        }
      },

      // ---- playback
      destroyPlayer() {
        clearTimeout(retryTimer);
        if (!player) return;
        try {
          player.pause();
          player.unload();
          player.detachMediaElement();
          player.destroy();
        } catch (e) {
          // best-effort teardown -- a half-torn-down player is still better
          // than leaking the old one into the next tune()
        }
        player = null;
      },
      tune(num) {
        if (!this.channels.some((c) => c.number === num)) {
          this.say(`No channel ${num}`);
          return;
        }
        this.current = num;
        keep(LAST_CHANNEL_KEY, num);
        this.entry = "";
        this.destroyPlayer();
        const again = (why) => {
          this.say(why);
          clearTimeout(retryTimer);
          retryTimer = setTimeout(() => { if (this.current === num) this.tune(num); }, RETRY_MS);
        };

        player = mpegts.createPlayer(
          { type: "mpegts", isLive: true, url: `/auto/v${encodeURIComponent(num)}` + (this.kbps ? `?kbps=${this.kbps}` : "") },
          {
            // The browser keeps half a minute of what was already played, not three: nothing here rewinds. (enableWorker was
            // tried with it and left out: the picture then ran a fifth of a second from the end of what had arrived, not two.)
            autoCleanupMaxBackwardDuration: 30,
            autoCleanupMinBackwardDuration: 15,
            enableStashBuffer: false,
            // Falling behind is made up by playing a little faster, not by jumping ahead. A jump is a visible skip and left
            // 1 s in hand, so the next hiccup froze the picture (worst in Firefox); the tuner's 3 s replay for a new viewer
            // sat right on the old 3 s limit. The jump is kept for a long way behind (a tab left in the background).
            liveSync: true,
            liveSyncMaxLatency: 5.0,
            liveSyncTargetLatency: 3.0,
            liveSyncPlaybackRate: 1.1,
            liveBufferLatencyChasing: true,
            liveBufferLatencyMaxLatency: 15.0,
            liveBufferLatencyMinRemain: 3.0,
          }
        );
        player.attachMediaElement(this.$refs.video);
        speedKB = 0;
        if (mpegts.Events.STATISTICS_INFO) player.on(mpegts.Events.STATISTICS_INFO, (s) => { speedKB = s.speed || 0; });
        player.on(mpegts.Events.ERROR, () => again("Stream error — retrying…"));
        // the server closing the stream (a viewer too slow to keep up is dropped) is not an error to the player: it just
        // stops, and the picture freezes. Treat the end of a live stream as a reason to reconnect.
        if (mpegts.Events.LOADING_COMPLETE) player.on(mpegts.Events.LOADING_COMPLETE, () => again("Stream ended — reconnecting…"));
        stall.since = Date.now();                        // a fresh player gets time to start before the watchdog looks
        stall.last = -1;
        player.load();
        player.play().catch(() => {
          // Autoplay-with-sound can be refused before the mute button is
          // touched; the element is already muted by default so this is rare.
        });

        this.updateBanner(true);
        this.drawGuide();
        this.ccReset();
      },
      watchdog() {
        const video = this.$refs.video;
        if (!this.current || !player || document.hidden) { stall.since = Date.now(); return; }
        if (video.paused) {                              // autoplay was refused: ask again rather than reconnect forever
          video.play().catch(() => {});
          stall.since = Date.now();
          return;
        }
        if (video.currentTime !== stall.last) {          // it moved
          stall.last = video.currentTime;
          stall.since = Date.now();
          stall.tries = 0;
          return;
        }
        if (Date.now() - stall.since > STALL_MS) {
          stall.tries += 1;
          this.say(stall.tries > 1 ? "Still no picture — trying again…" : "The picture stopped — reconnecting…");
          stall.since = Date.now() + Math.min(stall.tries, 4) * 2000;   // each failed try waits a little longer
          this.tune(this.current);
        }
      },
      channelStep(dir) {
        if (!this.channels.length) return;
        let idx = this.channels.findIndex((c) => c.number === this.current);
        if (idx === -1) idx = 0;
        this.tune(this.channels[(idx + dir + this.channels.length) % this.channels.length].number);
      },
      enter() {
        const v = this.entry.trim();
        this.$refs.entry.blur();                         // so the arrow keys are the channel keys again
        if (v) this.tune(v);
      },

      // ---- quality: a lower-rate copy of the channel (/auto/v<n>?kbps=N) for a slow connection. 1000k to 5000k, never over
      // what the tuner itself makes (video.vbitrate): the top of the list is the channel as it is. Remembered.
      async loadQuality() {
        let top = 4000;
        try { top = (await (await fetch("/system.json")).json()).video_kbps || top; } catch (e) { /* the default list */ }
        this.topKbps = top;
        if (this.kbps >= top) this.kbps = 0;
        const names = { 1000: "Low", 2000: "Medium", 3000: "Extra Medium", 4000: "High" };     // High: only under a 5000k tuner
        const rates = [1000, 2000, 3000, 4000, 5000].filter((r) => r < top);
        if (!rates.includes(this.kbps)) this.kbps = 0;
        this.qualities = [...rates.map((r) => ({ kbps: r, name: names[r] })), { kbps: 0, name: "Full" }];
        this.qualityTitle = "Picture quality: " + rates.map((r) => `${names[r]} ${r}k`).concat(`Full ${top}k`).join(", ");
      },
      setQuality(kbps) {
        this.kbps = kbps;
        keep(QUALITY_KEY, String(kbps));
        if (this.current != null) this.tune(this.current);
      },

      // ---- the controls fade when nothing has moved for HIDE_MS, and come back with the mouse, a touch or the Tab key.
      // The channel and volume keys do not bring them back: the channel bar already says what changed.
      wake() {
        if (this.idle) this.idle = false;
        clearTimeout(idleTimer);
        idleTimer = setTimeout(() => this.rest(), HIDE_MS);
      },
      rest() {
        const c = this.$refs.controls, a = document.activeElement;
        // not from under the pointer, nor while a number is being typed or the quality list is open, nor with the guide open
        const busy = c.matches(":hover") || (a && c.contains(a) && /^(INPUT|SELECT)$/.test(a.tagName)) || this.guideOpen || this.unsupported;
        if (busy) this.wake();
        else this.idle = true;
      },

      // ---- full screen: the picture AND the controls under it, so the channel can still be changed there. The player
      // always fills the browser's window (a style); the whole screen is asked for on top of that, and a browser that
      // refuses or never answers (an embedded one) just leaves it at the window.
      toggleFull() {
        this.full = !this.full;
        const stage = this.$refs.stage;
        if (this.full && stage.requestFullscreen) Promise.resolve(stage.requestFullscreen()).catch(() => {});
        else if (!this.full && document.fullscreenElement) document.exitFullscreen();
      },

      // ---- what is playing (the Stats button): the picture's size as it was decoded, how fast the stream is arriving, and
      // the quality asked for. A lower quality can look the same in a small player, so this is how to tell that it took.
      toggleStats() {
        this.stats = !this.stats;
        keep(STATS_KEY, this.stats ? "on" : "off");
        this.statsTick();
      },
      statsTick() {
        if (!this.stats) return;
        const v = this.$refs.video, q = this.qualities.find((x) => x.kbps === this.kbps);
        const size = v.videoWidth ? `${v.videoWidth}×${v.videoHeight}` : "no picture yet";
        const rate = speedKB ? `${(speedKB * 8.192 / 1000).toFixed(1)} Mbps arriving` : "";     // the player counts in KiB a second
        this.statsText = [size, rate, `${q ? q.name : "Full"}: ${this.kbps || this.topKbps}k video`].filter(Boolean).join(" · ");
      },

      // ---- volume: a slider, a mute button, and the arrow keys. The picture starts muted (browsers refuse sound
      // until you do something), then the first touch of any of these brings it up at the volume you left it at.
      showVolume() {
        const video = this.$refs.video;
        this.silent = video.muted || video.volume === 0;
        this.volumeIcon = this.silent ? "\u{1F507}" : video.volume < 0.34 ? "\u{1F508}" : video.volume < 0.67 ? "\u{1F509}" : "\u{1F50A}";    // low, medium, loud: one icon each
        this.volume = Math.round((video.muted ? 0 : video.volume) * 100);
      },
      setVolume(v, remember = true) {
        const video = this.$refs.video;
        video.volume = Math.min(1, Math.max(0, v));
        video.muted = video.volume === 0;
        if (remember) keep(VOLUME_KEY, String(video.volume));
        this.showVolume();
      },
      toggleMute() {
        const video = this.$refs.video;
        if (video.muted || video.volume === 0) {
          if (video.volume === 0) video.volume = 0.5;       // it was turned all the way down: bring it back to something
          video.muted = false;
        } else {
          video.muted = true;
        }
        this.showVolume();
      },
      key(e) {
        const video = this.$refs.video;
        if (e.target === this.$refs.entry || e.target === this.$refs.volume) return;       // the slider has its own arrow keys
        if (e.target && /^(INPUT|SELECT|TEXTAREA)$/.test(e.target.tagName)) return;
        const arrows = {
          ArrowUp: () => this.channelStep(1), ArrowDown: () => this.channelStep(-1),
          ArrowRight: () => this.setVolume((video.muted ? 0 : video.volume) + 0.05),
          ArrowLeft: () => this.setVolume((video.muted ? 0 : video.volume) - 0.05),
        };
        if (arrows[e.key] && !e.ctrlKey && !e.metaKey && !e.altKey) {
          e.preventDefault();                            // the keys are the remote: the page does not scroll under them
          arrows[e.key]();
        } else if ((e.key === "m" || e.key === "M") && !e.ctrlKey && !e.metaKey) this.toggleMute();
        else if ((e.key === "f" || e.key === "F") && !e.ctrlKey && !e.metaKey) this.toggleFull();
        else if (e.key === "Escape" && this.full) this.toggleFull();
        else if ((e.key === "c" || e.key === "C") && !e.ctrlKey && !e.metaKey && this.cc.tracks.length) this.ccNext();
      },

      // ---- captions
      // The server says which file a channel is airing and where in it the channel is now, and hands over that file's
      // captions as WebVTT. The page works out which line belongs on screen from the clock, so nothing is added to the
      // stream itself (it is not selectable in other players: see the README). Off by default; the choice of language is
      // remembered, so captions stay on from one episode to the next.
      ccPref() {      // ?cc=on (or a language code, or off) in the address overrides what was remembered
        const asked = new URLSearchParams(location.search).get("cc");
        if (asked !== null && !ccState.chosen) return asked === "on" ? "" : asked || "off";
        return recall(CC_PREF_KEY) || "off";
      },
      ccShow() {
        let lines = [];
        if (this.cc.track >= 0 && cues.length && !ccState.inBreak) {
          const t = ccState.pos + (Date.now() / 1000 + ccState.skew - ccState.at) - this.cc.nudge;      // where in the file the picture is now
          lines = cues.filter((c) => t >= c.from && t < c.to).map((c) => c.text);
        }
        if (lines.join("\n") !== this.ccLines.join("\n")) this.ccLines = lines;
      },
      async ccLoad(trackIndex, token) {
        const t = this.cc.tracks[trackIndex];
        cues = [];
        if (!t) return;
        try {
          const res = await fetch(`/captions/${encodeURIComponent(this.current)}/${ccState.eid}/${encodeURIComponent(t.id)}.vtt`);
          if (!res.ok) return;
          const got = parseVtt(await res.text());
          if (token === ccState.token) cues = got;
        } catch (e) { /* captions are a nicety: the picture carries on */ }
      },
      async ccSelect(index) {          // -1 is off
        ccState.chosen = true;         // from now on the button decides, not the address
        this.cc.track = index;
        keep(CC_PREF_KEY, index < 0 ? "off" : this.cc.tracks[index].lang);
        const token = ++ccState.token;
        this.ccShow();
        if (index >= 0) { await this.ccLoad(index, token); this.ccShow(); }
      },
      ccNext() { return this.ccSelect(this.cc.track + 1 >= this.cc.tracks.length ? -1 : this.cc.track + 1); },
      nudge(d) {
        this.cc.nudge = Math.round((this.cc.nudge + d) * 10) / 10;
        keep(CC_NUDGE_KEY, String(this.cc.nudge));
        this.ccShow();
      },
      async ccPollOnce() {
        if (!this.current) return;
        const num = this.current;
        let info;
        try { info = await (await fetch(`/captions/${encodeURIComponent(num)}.json`)).json(); } catch (e) { return; }
        if (num !== this.current) return;
        const s = ccState;
        s.skew = (info.now || Date.now() / 1000) - Date.now() / 1000;
        s.pos = info.pos || 0;
        s.at = info.now || Date.now() / 1000;
        s.segEnd = (info.now || 0) + (info.remaining || 0);          // when this piece ends: look again just after
        s.inBreak = info.kind === "bump" || info.kind === "commercial";
        if (s.inBreak) { this.ccShow(); return; }                    // a break has no captions of its own: keep the show's choice, show nothing
        if (info.eid !== s.eid) {              // a different file is on: look again at what it has
          s.eid = info.eid;
          this.cc.track = -1;
          this.cc.tracks = info.tracks || [];
          cues = [];
          const token = ++s.token;
          const pref = this.ccPref();
          let track = pref === "off" ? -1 : this.cc.tracks.findIndex((t) => t.lang === pref);
          if (pref !== "off" && track < 0 && this.cc.tracks.length) track = 0;      // another language than before: better than none
          this.cc.track = track;
          this.ccShow();
          if (track >= 0) { await this.ccLoad(track, token); this.ccShow(); }
        }
      },
      ccReset() {                      // a new channel: forget the old file
        ccState.eid = null;
        ccState.token++;
        cues = [];
        this.cc.track = -1;
        this.cc.tracks = [];
        this.ccShow();
        this.ccPollOnce();
      },
      ccTick() {
        if (document.hidden) return;                     // nobody is looking: the next poll catches up
        this.ccShow();
        // the piece on air has ended (the picture runs a little behind the clock): look at what is on now, don't wait for the next poll
        const s = ccState;
        if (s.segEnd && !s.polling && Date.now() / 1000 + s.skew - this.cc.nudge > s.segEnd + 0.3) {
          s.polling = true;
          s.segEnd = 0;
          this.ccPollOnce().finally(() => { s.polling = false; });
        }
      },
    }));
  });
})();
