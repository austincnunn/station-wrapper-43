// The Dashboard: every channel and what it is playing, the system at a glance, and the library by list.
// It reads /channels.json, /system.json and /library.json, which need no login.
(function () {
  "use strict";

  const REFRESH_MS = 10 * 1000;
  // Thumbnails are cached in the browser for a minute, matching the server's
  // snapshot reuse, so a refresh doesn't re-request every frame.
  const THUMB_BUCKET_MS = 60 * 1000;

  // An answer that is not 2xx (not logged in, restarting) is an error, never data.
  const get = (path) => fetch(path).then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); });
  const recall = (key) => { try { return localStorage.getItem(key); } catch (e) { return null; } };
  const keep = (key, value) => { try { localStorage.setItem(key, value); } catch (e) { /* not remembered */ } };

  function fmtUptime(sec) {
    const d = Math.floor(sec / 86400);
    const h = Math.floor((sec % 86400) / 3600);
    const m = Math.floor((sec % 3600) / 60);
    return d ? `${d}d ${h}h` : h ? `${h}h ${m}m` : `${m}m`;
  }
  function fmtClock(sec) {
    sec = Math.max(0, Math.round(sec));
    const h = Math.floor(sec / 3600);
    const m = Math.floor((sec % 3600) / 60);
    const s = String(sec % 60).padStart(2, "0");
    return h ? `${h}:${String(m).padStart(2, "0")}:${s}` : `${m}:${s}`;
  }
  function fmtAge(sec) {
    if (sec == null) return "never";
    if (sec < 90) return `${sec}s ago`;
    return `${Math.round(sec / 60)}m ago`;
  }

  // the read-ahead: copies of the next break or episode made before they are due (prefetch.py)
  function readAhead(p) {
    if (!p) return null;
    if (!p.enabled) return { label: "Read-ahead", value: "off", sub: p.why_not || "", warn: false };
    const shares = Object.entries(p.shares || {}).map(([k, v]) => `${k.split("/").pop()}: ${v.mb_per_s != null ? v.mb_per_s + " MB/s" : "measuring"}, ${v.delay_s != null ? v.delay_s + "s to open" : ""}`).join("; ");
    return { label: "Read-ahead", value: `${p.cache.used_mb} / ${p.cache.max_mb} MB`,
      sub: `${p.cache.files} files in ${p.ram ? "RAM" : "disk"}` + (p.copying ? `, copying ${p.copying}` : "") + (shares ? ` · ${shares}` : ""), warn: false };
  }

  function statTiles(sys) {
    const cpuPct = sys.cpu.count ? sys.cpu.load1 / sys.cpu.count : 0;
    const mem = sys.memory;
    const guide = sys.guide || {};
    return [
      { label: "Channels on air", value: `${sys.schedule.channels_on_air}`,
        sub: sys.schedule.db_modified ? `schedule written ${sys.schedule.db_modified.replace("T", " ").slice(0, 16)}` : "no schedule db",
        warn: sys.schedule.channels_on_air === 0 },
      { label: "Encoders", value: `${sys.encoders.in_use} / ${sys.encoders.max}`, sub: `${sys.encoders.started_total} started since boot`,
        warn: sys.encoders.in_use >= sys.encoders.max },
      { label: "Viewers", value: `${sys.viewers.in_use} / ${sys.viewers.max}`, sub: `${sys.viewers.served_total} served, ${sys.viewers.refused_total} refused`,
        warn: sys.viewers.refused_total > 0 },
      { label: "CPU load", value: sys.cpu.load1.toFixed(2), sub: `${sys.cpu.count} cores, 5m ${sys.cpu.load5.toFixed(2)}`, warn: cpuPct > 0.9 },
      { label: "Memory", value: mem ? `${mem.available_mb} MB free` : "unknown", sub: mem ? `of ${mem.total_mb} MB` : "", warn: !!mem && mem.available_mb < 512 },
      { label: "Guide", value: fmtAge(guide.age_seconds), sub: guide.fs42 ? `${guide.fs42.channels} channels, ${guide.fs42.programmes} programmes` : "",
        warn: guide.age_seconds == null },
      readAhead(sys.prefetch),
      { label: "Uptime", value: fmtUptime(sys.uptime_seconds), sub: "", warn: false },
    ].filter(Boolean);
  }

  document.addEventListener("alpine:init", () => {
    Alpine.data("dashboardPage", () => ({
      fmtClock,
      channels: [], summary: "", bucket: 0, noThumb: {},
      stats: [], sysSummary: "", sysWarns: "",
      statusLine: "", lost: false,
      lib: null, libSummary: "", libWarn: false, libFilter: "", libOpen: [], scanning: false,
      setup: { show: false, steps: [], next: -1, noStation: false }, setupBusy: false,

      init() {
        // System and Library stay folded away under the channels; the browser remembers which you opened.
        for (const id of ["sys", "lib"]) this.$refs[id].open = recall(`fold-${id}`) === "1";
        this.refresh();
        setInterval(() => this.refresh(), REFRESH_MS);
        // Library: the content folder by list. Read once, then every few minutes, since
        // it only changes when the generator or you add links. Open lists stay open.
        this.loadLibrary(false);
        setInterval(() => { if (!this.scanning) this.loadLibrary(false); }, 5 * 60 * 1000);
        this.loadSetup();
        setInterval(() => this.loadSetup(), 30 * 1000);
      },
      remember(id, open) { keep(`fold-${id}`, open ? "1" : "0"); },

      async refresh() {
        try {
          const [sys, chans] = await Promise.all([get("/system.json"), get("/channels.json")]);
          this.stats = statTiles(sys);
          // The fold's one line: what needs a look, or that nothing does. A new warning opens the fold once.
          const warns = this.stats.filter((s) => s.warn).map((s) => s.label).join(", ");
          this.sysSummary = warns ? `Check: ${warns}` : `No problems · up ${fmtUptime(sys.uptime_seconds)}`;
          if (warns && warns !== this.sysWarns) this.$refs.sys.open = true;
          this.sysWarns = warns;
          this.bucket = Math.floor(Date.now() / THUMB_BUCKET_MS);
          this.channels = chans;
          const watching = chans.reduce((sum, r) => sum + (r.viewers || 0), 0);
          this.summary = `${chans.filter((r) => r.on_air).length} of ${chans.length} on air` + (watching ? ` · ${watching} watching` : "");
          this.statusLine = `Updated ${new Date().toLocaleTimeString()}`;
          this.lost = false;
        } catch (e) {
          this.statusLine = "Lost contact with fs42-tuner, retrying";
          this.lost = true;
        }
      },
      // the guide draws a picture of itself; a stream has no frame to show. A frame that failed is not asked for again this minute.
      hasThumb(r) {
        return !!(r.on_air && r.now && (!r.now.is_stream || r.now.content_type === "guide")) && this.noThumb[r.channel] !== this.bucket;
      },
      thumbText(r) {
        if (this.noThumb[r.channel] === this.bucket) return "no preview";
        return r.on_air ? "live" : "off air";
      },
      filler: (now) => !["feature", "guide", "iptv"].includes(now.content_type),

      // ---- library
      async loadLibrary(rescan) {
        try {
          const data = rescan ? await W.call("/library.json?refresh") : await get("/library.json");
          this.scanning = !!data.scanning;
          if (data.never) {                                       // the server has not finished its first scan yet
            this.lib = { ...data, scanning: true };
            this.libSummary = "Waiting for the first scan of your lists…";
            setTimeout(() => this.loadLibrary(false), 5000);
            return;
          }
          this.lib = data;
          this.libWarn = false;
          if (data.found) {
            const t = data.totals, warns = [];
            if (t.dead) warns.push(`${t.dead} dead link${t.dead === 1 ? "" : "s"}`);
            if (t.duplicates) warns.push(`${t.duplicates} duplicate${t.duplicates === 1 ? "" : "s"}`);
            this.libSummary = `${t.videos.toLocaleString()} videos in ${data.tags.length} lists` + (warns.length ? ` — ${warns.join(", ")}` : "");
            this.libWarn = warns.length > 0;
          } else {
            this.libSummary = "";
          }
          if (data.scanning) setTimeout(() => this.loadLibrary(false), 2000);   // a rescan you asked for is running: follow it
        } catch (e) {
          this.scanning = false;
          this.libSummary = "Library unavailable";
          this.libWarn = true;
        }
      },
      // The bar while the lists are scanned: how many lists are done, and which one is being read.
      get scanJob() {
        const l = this.lib;
        if (!l || !(l.scanning || this.scanning)) return null;
        const s = l.scan || {};
        return { message: s.total ? `Scanning your lists: ${s.done} of ${s.total}${s.tag ? ` (${s.tag})` : ""}` : "Scanning your lists…", done: s.total ? s.done : undefined, total: s.total || 0 };
      },
      get shownTags() {
        const q = this.libFilter.trim().toLowerCase();
        const tags = (this.lib && this.lib.found && this.lib.tags) || [];
        return q ? tags.filter((t) => t.tag.toLowerCase().includes(q)) : tags;
      },
      noteOpen(tag, open) {
        this.libOpen = open ? [...new Set([...this.libOpen, tag])] : this.libOpen.filter((t) => t !== tag);
      },

      // ---- getting started: what is done and what is next, until the first channel is on air
      hideSetup() {
        keep("setup-dismissed", "1");
        this.setup.show = false;
      },
      async loadSetup() {
        if (this.setupBusy) return;                             // a channel is being made: leave its progress on screen
        const dismissed = recall("setup-dismissed") === "1";
        try {
          const auth = await get("/api/auth/status");           // logged out, the steps can't be worked out: ask for nothing
          if (auth.login && !auth.authenticated) { this.setup.show = false; return; }
          const [sys, lib, stations] = await Promise.all([get("/api/system/status"), get("/library.json"), get("/api/stations")]);
          const rows = stations.stations || stations.rows || stations || [];
          const real = (Array.isArray(rows) ? rows : []).filter((s) => s.type !== "guide");
          const hasLists = (lib.tags || []).some((t) => t.videos > 0 && !["bump", "commercials"].includes(t.tag));
          const steps = [
            { done: !!(sys.media && sys.media.present), text: "Your media folder has videos in it.", href: "/settings.html#files", go: "Lists & files" },
            { done: hasLists, text: "You have a list with videos in it (or a series, season or folder you can pick directly).", href: "/settings.html#files", go: "Lists & files" },
            { done: real.length > 0, text: "You have a station.", href: "/station.html", go: "New station" },
            { done: real.some((s) => s.on_air), text: "A station is built and on air (Save and build on the station's page).", href: "/stations.html", go: "Stations" },
            { done: null, text: `Add it to Jellyfin or another IPTV app: a tuner of type HDHomeRun at ${location.host} and an XMLTV guide at http://${location.host}/xmltv.xml. The Status tab of Settings checks everything else.`, href: "/settings.html#status", go: "Status" },
          ];
          const complete = steps.slice(0, 4).every((s) => s.done);
          this.setup = { show: !(complete || dismissed), steps, next: steps.findIndex((s) => s.done === false), noStation: !steps[2].done };
        } catch (e) {
          this.setup.show = false;                              // not logged in, or restarting: say nothing
        }
      },
    }));
  });
})();
