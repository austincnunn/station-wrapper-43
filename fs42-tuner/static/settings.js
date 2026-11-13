// The Settings page: one page with a tab for each group. This file is the page itself (which tab is showing) and
// the General and Players tabs: the compose file's settings that can be changed here (envsettings.py), for this
// server and for each player PC (client mode). The other tabs are in iptv.js + emby.js (Sources), schedule.js,
// files.js (Lists & files) and status.js. A tab loads its data the first time it is opened.
(function () {
  "use strict";
  const { call, say } = W;

  const TABS = [
    { id: "general", label: "General", about: "Settings from the compose file, changed here." },
    { id: "sources", label: "Sources", about: "Other tuners, playlists of channels, single streams such as cameras, and Emby or Jellyfin servers. Their channels get numbers of their own and join the lineup, the guide, the player and the dashboard." },
    { id: "schedule", label: "Schedule", about: "What each station plays, day by day." },
    { id: "files", label: "Lists & files", about: "Build the lists a station plays from. Nothing is copied: a list holds links, so a video can be in as many lists as you like and your media is never touched." },
    { id: "players", label: "Players", about: "Player PCs in client mode: connect one, and change its settings from here." },
    { id: "status", label: "Status", about: "What is wrong, what to look at, and what is fine. The diagnostics file holds all of this plus the last messages the container printed, with passwords left out: send it when asking for help." },
  ];
  const current = () => {
    const id = location.hash.slice(1);
    return TABS.some((t) => t.id === id) ? id : "general";
  };
  // A tab's timer only looks things up while its tab is the one showing.
  W.onTab = (id) => document.visibilityState === "visible" && current() === id;

  const SOURCE = { saved: "set here", env: "from the compose file", default: "built-in default" };
  const shown = (s, v) => (s.kind === "bool" ? (v === "0" ? "off" : "on") : v === "" || v == null ? "automatic" : v);

  document.addEventListener("alpine:init", () => {
    Alpine.data("settingsPage", () => ({
      tabs: TABS,
      tab: current(),
      seen: {},
      r: null,                    // /api/settings: this machine, this server's settings, the players
      token: "",

      init() {
        this.seen[this.tab] = true;
        window.addEventListener("hashchange", () => {
          this.tab = current();
          this.seen[this.tab] = true;
        });
        call("/api/settings").then((r) => { this.r = r; }).catch((e) => say(e.message, "err"));
      },

      get secrets() {
        return Object.entries(this.r.machine.secrets).map(([k, v]) => `${k} ${v ? "set" : "not set"}`).join(", ");
      },

      // Every settings form on the page: this server's (General), then one for each player PC (Players).
      get forms() {
        if (!this.r) return [];
        const out = [{ id: "server-", tab: "general", title: "This server", rows: this.r.settings, applied: null,
          send: (values) => call("/api/settings", { values }) }];
        for (const p of this.r.sync_on ? this.r.players : []) {
          out.push({ id: `player-${p.name}-`, tab: "players", title: `${p.name}${p.gone ? " (not seen for a while)" : ""}`,
            rows: p.settings, applied: p.applied || {}, send: (values) => call("/api/settings/player", { name: p.name, values }) });
        }
        return out;
      },

      // The sync token a player puts in its .env (FS42_SYNC_TOKEN): fetched only when asked for, then shown and copied.
      async showToken() {
        try {
          this.token = `FS42_SYNC_TOKEN=${(await call("/api/settings/sync-token")).token}`;
          await this.$nextTick();
          this.$refs.token.select();
          // the clipboard API needs https; over plain http the old copy command still works on the selected text
          const copied = navigator.clipboard ? await navigator.clipboard.writeText(this.token).then(() => true, () => false)
            : document.execCommand("copy");
          say(copied ? "Copied: paste it into the player's .env." : "It is selected: press Ctrl+C (⌘C on a Mac) to copy it.", copied ? "ok" : "");
        } catch (e) {
          say(e.message, "err");
        }
      },
    }));

    // One form of settings (f, from the page's forms). Every box is sent on Save; an empty one means "not set here"
    // (the compose file's value, or the default, is used).
    Alpine.data("settingsForm", () => ({
      values: {},
      busy: false,

      init() {
        this.fill();
        this.$watch("f.rows", () => this.fill());
      },
      fill() {
        const values = {};
        for (const s of this.f.rows) values[s.key] = s.source === "saved" ? String(s.value) : "";
        this.values = values;
      },
      get groups() {
        const out = [];
        for (const s of this.f.rows) {
          if (!out.length || out[out.length - 1].name !== s.group) out.push({ name: s.group, rows: [] });
          out[out.length - 1].rows.push(s);
        }
        return out;
      },
      isSelect: (s) => s.kind === "bool" || s.kind[0] === "choice",
      options: (s) => (s.kind === "bool" ? [["1", "On"], ["0", "Off"]] : s.kind[1].filter((c) => c).map((c) => [c, c])),
      fallback: (s) => (s.env != null && s.env !== "" ? `compose file: ${shown(s, s.env)}` : `default: ${shown(s, s.default)}`),
      hint(s) {
        const waiting = this.f.applied && s.source === "saved" && this.f.applied[s.key] !== s.value ? "waiting for the player (next sync)" : "";
        return `${SOURCE[s.source]}: ${shown(s, s.value)}` + (s.restarts.length ? ` · saving restarts ${s.restarts.join(", ")}` : "") +
          (waiting ? ` · ${waiting}` : "") + (s.note ? ` · ${s.note}` : "");
      },
      async save() {
        const values = {};
        for (const [k, v] of Object.entries(this.values)) values[k] = String(v ?? "").trim();
        this.busy = true;
        try {
          this.r = await this.f.send(values);
          say("Saved. What uses it restarts in a few seconds (the dashboard too, for its own settings).", "ok");
        } catch (e) {
          say(e.message, "err");
        } finally {
          this.busy = false;
        }
      },
    }));
  });
})();
