// The Sources tab of the Settings page: other tuners, playlists of channels and single streams (iptv.py,
// /api/iptv/*). The Emby and Jellyfin panel under it is emby.js.
(function () {
  "use strict";
  const { call, fmtWhen, say, run } = W;

  const HINTS = {
    stream: "A camera or one stream: rtsp://, http://, rtmp://, udp:// or srt://. A password in the address is kept private and never shown again.",
    m3u: "The address of the playlist (an .m3u or .m3u8 file). Its channels are read now and again every few hours.",
    hdhomerun: "The tuner's address, such as http://192.168.1.20. Its channels keep their own numbers.",
  };
  const PLACEHOLDERS = { stream: "rtsp://user:password@192.168.1.60:554/stream1", m3u: "http://example.com/channels.m3u", hdhomerun: "http://192.168.1.20" };
  const KINDS = { stream: "stream", m3u: "playlist", hdhomerun: "tuner" };
  const MODES = { convert: "converted for browsers", relay: "passed on as it is", guide: "guide only (not played here)" };

  document.addEventListener("alpine:init", () => {
    Alpine.data("sourcesTab", () => ({
      HINTS, KINDS, MODES,
      sources: [], edit: true, legacy: null, clashes: [], loaded: false,
      open: [],                         // ids of the sources whose channel table is open
      reading: null,                    // id of the source whose channels are being read again
      // the form at the bottom of the tab: a new source, or (editing: its id) the one whose Edit was pressed
      form: { editing: null, title: "", type: "stream", name: "", url: "", mode: "convert", base: "", result: "", saving: false, testing: false },

      init() {
        run(() => this.load());
        setInterval(() => {
          const a = document.activeElement;
          const typing = a && this.$root.contains(a) && /^(INPUT|SELECT|TEXTAREA)$/.test(a.tagName);
          if (W.onTab("sources") && !typing) this.load().catch(() => {});       // never while something is being typed
        }, 30000);
      },

      async load() {
        const data = await call("/api/iptv/sources");
        this.sources = data.sources;
        this.edit = data.edit;
        this.legacy = data.legacy || null;
        this.clashes = data.clashes || [];
        this.loaded = true;
      },

      get urlPlaceholder() { return PLACEHOLDERS[this.form.type]; },
      chOn: (ch) => !(ch.override && ch.override.enabled === false),
      stateText(s) {
        if (s.error) return `Could not read it: ${s.error}`;
        if (!s.enabled) return "Switched off: its channels are not on air.";
        if (s.mode === "guide") return `Guide only: its ${s.channels.length} channels' listings are in our guide; they are not in the lineup, so Jellyfin plays them from the tuner itself.`;
        const on = s.channels.filter(this.chOn).length;
        return `${on} of ${s.channels.length} channel${s.channels.length === 1 ? "" : "s"} on air` +
          (s.refreshed ? `, read ${fmtWhen(new Date(s.refreshed * 1000).toISOString())}` : "") + ".";
      },
      noteOpen(id, open) {
        this.open = open ? [...new Set([...this.open, id])] : this.open.filter((x) => x !== id);
      },

      toggle(s) {
        return run(async () => {
          await call("/api/iptv/save", { id: s.id, name: s.name, enabled: !s.enabled });
          await this.load();
        });
      },
      refresh(s) {
        return run(async () => {
          this.reading = s.id;
          try {
            await call("/api/iptv/refresh", { id: s.id });
            await this.load();
            say(`Read ${s.name}.`, "ok");
          } finally {
            this.reading = null;
          }
        });
      },
      remove(s) {
        return run(async () => {
          if (!await W.confirm(`Remove “${s.name}”? Its channels leave the lineup, the guide and the player.`, { ok: "Remove", danger: true })) return;
          await call("/api/iptv/delete", { id: s.id });
          await this.load();
        });
      },
      saveChannel(s, ch, fields) {
        return run(async () => {
          await call("/api/iptv/channel", { id: s.id, key: ch.key, ...fields });
          await this.load();
        });
      },
      importLegacy() {
        return run(async () => {
          await call("/api/iptv/import-legacy", {});
          say("Moved. Restart the container once so the old setting is gone for good.", "ok");
          await this.load();
        });
      },

      // ---- the form
      blank() {
        Object.assign(this.form, { editing: null, title: "", type: "stream", name: "", url: "", mode: "convert", base: "", result: "" });
      },
      editSource(s) {
        Object.assign(this.form, {
          editing: s.id, title: s.name, type: s.type,              // what kind of source it is can't change: make a new one
          name: s.name, url: s.url, mode: s.mode, base: s.base ? s.base : "", result: "",
        });
        this.$nextTick(() => {
          this.$refs.form.scrollIntoView({ block: "start", behavior: "smooth" });
          this.$refs.name.focus({ preventScroll: true });
        });
      },
      typeChanged() {
        if (this.form.type !== "hdhomerun" && this.form.mode === "guide") this.form.mode = "convert";
      },
      test() {
        return run(async () => {
          if (this.form.type !== "stream") {
            this.form.result = "A playlist or tuner is checked when it is saved: its channels are read then.";
            return;
          }
          this.form.testing = true;
          this.form.result = "Looking at it for a few seconds…";
          try {
            const r = await call("/api/iptv/test", { url: this.form.url.trim() });
            this.form.result = r.ok ? `It works: ${[r.video, r.audio].filter(Boolean).join(", ") || "a stream"}.` : `It did not answer: ${r.error}`;
          } catch (e) {
            this.form.result = "";
            throw e;
          } finally {
            this.form.testing = false;
          }
        });
      },
      save() {
        return run(async () => {
          const f = this.form;
          f.saving = true;
          f.result = "Saving…";
          try {
            const body = { name: f.name, url: f.url, mode: f.mode, base: f.base === "" || f.base == null ? null : Number(f.base) };
            if (f.editing) body.id = f.editing; else body.type = f.type;
            await call("/api/iptv/save", body);
            this.blank();
            await this.load();
            say("Saved. Its channels are in the lineup, the guide and the player.", "ok");
          } finally {
            f.saving = false;
            if (f.result === "Saving…") f.result = "";
          }
        });
      },
    }));
  });
})();
