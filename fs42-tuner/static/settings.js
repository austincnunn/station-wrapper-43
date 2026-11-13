// The Settings page: one page with a tab for each group. This file is the page itself (which tab is showing) and
// the General and Players tabs: the compose file's settings that can be changed here (envsettings.py), for this
// server and for each player PC (client mode). The other tabs are in iptv.js + emby.js (Sources), schedule.js,
// files.js (Lists & files), viewers.js and status.js. A tab loads its data the first time it is opened.
(function () {
  "use strict";
  const { call, say } = W;

  // Each tab says what it is for in its own first paragraph (settings.html), so nothing above the tabs changes height.
  const TABS = [
    { id: "general", label: "General" }, { id: "sources", label: "Sources" }, { id: "schedule", label: "Schedule" },
    { id: "files", label: "Lists & files" }, { id: "players", label: "Players" }, { id: "viewers", label: "Viewers" }, { id: "status", label: "Status" },
  ];
  const current = () => {
    const id = location.hash.slice(1);
    return TABS.some((t) => t.id === id) ? id : "general";
  };
  // A tab's timer only looks things up while its tab is the one showing.
  W.onTab = (id) => document.visibilityState === "visible" && current() === id;

  const SOURCE = { saved: "set here", env: "from the compose file", default: "built-in default" };
  // what each secret in .env is for, by its name (pairs, not name: "text", which a secret scanner reads as a password)
  const SECRET_FOR = Object.fromEntries([
    ["DASHBOARD_PASSWORD", "Sets the dashboard's password at first start. Optional: the login page can set it instead."],
    ["MEDIA_SERVER_API_KEY", "Lets the guide ask your Emby or Jellyfin server for titles and pictures."],
    ["FS42_SYNC_TOKEN", "What player PCs sign in with. Made by this server when not set (the Players tab shows it)."],
  ]);
  const WEATHER = "WEATHER_LOCATION";       // the weather channel's place: asked for on the Sources tab, not under Advanced
  const shown = (s, v) => (s.kind === "bool" ? (v === "0" ? "off" : "on") : v === "" || v == null ? "automatic" : v);

  document.addEventListener("alpine:init", () => {
    Alpine.data("settingsPage", () => ({
      tabs: TABS,
      tab: current(),
      seen: {},
      r: null,                    // /api/settings: this machine, this server's settings, the players
      token: "",
      place: "", placeBusy: false,       // the weather channel's place, as typed

      init() {
        this.$watch("r", () => { const w = this.weather; this.place = w && w.source === "saved" ? String(w.value) : ""; });
        this.seen[this.tab] = true;
        window.addEventListener("hashchange", () => {
          this.tab = current();
          this.seen[this.tab] = true;
        });
        call("/api/settings").then((r) => { this.r = r; }).catch((e) => say(e.message, "err"));
      },

      // The secrets in .env: what each is for, and whether it is set (never its value).
      get secretRows() {
        return Object.entries((this.r && this.r.machine.secrets) || {}).map(([name, set]) => ({ name, set: !!set, what: SECRET_FOR[name] || "" }));
      },

      // Every settings form on the page: this server's (General), then one for each player PC (Players).
      get forms() {
        if (!this.r) return [];
        const out = [{ id: "server-", tab: "general", title: "Advanced", advanced: true, rows: this.r.settings.filter((s) => s.key !== WEATHER), applied: null,
          send: (values) => call("/api/settings", { values }) }];
        for (const p of this.r.sync_on ? this.r.players : []) {
          out.push({ id: `player-${p.name}-`, tab: "players", title: `${p.name}${p.gone ? " (not seen for a while)" : ""}`,
            rows: p.settings, applied: p.applied || {}, send: (values) => call("/api/settings/player", { name: p.name, values }) });
        }
        return out;
      },

      // ---- the weather channel's place (a ZIP code, or City, State): one of the compose settings, kept where channels are added
      get weather() { return (this.r && this.r.settings.find((s) => s.key === WEATHER)) || null; },
      get weatherHelp() {
        const w = this.weather;
        if (!w) return "";
        const from = w.source === "env" ? ` Set in the compose file: ${w.value}.` : "";
        return `${w.note}${from} The weather channel itself is switched on with COMPOSE_PROFILES=weather in .env.`;
      },
      async saveWeather() {
        this.placeBusy = true;
        try {
          this.r = await call("/api/settings", { values: { [WEATHER]: this.place.trim() } });
          say(this.place.trim() ? "Saved. The weather channel shows that place within a minute." : "Cleared: the weather channel goes back to the compose file's place, or asks for one.", "ok");
        } catch (e) {
          say(e.message, "err");
        }
        this.placeBusy = false;
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
      // the folded panel's one line: how many of these are set here rather than left to the compose file
      get changed() {
        const n = this.f.rows.filter((s) => s.source === "saved").length;
        return `compose file settings \u00b7 ${n ? `${n} changed here` : "none changed here"}`;
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
