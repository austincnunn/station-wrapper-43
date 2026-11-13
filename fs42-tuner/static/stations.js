// The Stations page: every station as a card (what it plays, whether it is on air, its buttons), with the schedule
// keeper and the caption language folded away above them.
(function () {
  "use strict";
  const { call, fmtWhen, say, run } = W;

  const SHOWN_LISTS = 6;             // a card names this many lists; the rest fold away
  // a build's step (the job's "phase", stationsapi.py), as the card's status line says it
  const DOING = { starting: "starting the build now", linking: "linking the series you picked now", waiting: "waiting for another schedule change to finish",
    catalog: "building the catalog now", days: "adding days to the schedule now" };
  const LANGUAGES = [["en", "English"], ["ja", "Japanese"], ["es", "Spanish"], ["fr", "French"], ["de", "German"], ["it", "Italian"],
    ["pt", "Portuguese"], ["ko", "Korean"], ["zh", "Chinese"], ["ru", "Russian"]];

  document.addEventListener("alpine:init", () => {
    Alpine.data("stationsPage", () => ({
      SHOWN_LISTS,
      stations: [], editable: true, loaded: false,
      jobs: {},                          // station name -> the build this page started and is following
      keeper: { enabled: false, days: 7, options: [3, 7, 14, 30], text: "", cls: "has-text-grey", short: "", bad: false, loaded: false },
      captions: { language: "en", options: LANGUAGES, short: "" },

      init() {
        run(() => this.load());
        // a build started elsewhere, or before this page was reloaded, shows up too: each station carries its job
        setInterval(() => { if (document.visibilityState === "visible") this.load().catch(() => {}); }, 4000);
      },

      async load() {
        const data = await call("/api/stations");
        this.editable = data.edit;
        this.stations = data.stations;
        this.loaded = true;
        this.loadKeeper().catch(() => {});
        if (!this.captions.short) this.loadCaptions().catch(() => {});
      },

      live: (s) => s.type === "guide" || s.type === "web",      // drawn live (the guide) or by a player (pay-per-view): no schedule
      jobFor(s) { return this.jobs[s.name] || s.job || null; },
      busy(s) { return !!this.jobFor(s); },
      // What a build is doing right now, in a few words, or "" when none is running for this station.
      doing(s) {
        const job = this.jobFor(s);
        if (!job || job.state === "done" || job.state === "error") return "";
        if (job.phase === "catalog" && job.refresh) return "looking for new videos now";
        return DOING[job.phase] || "building it now";
      },
      // The card's one line. While a build runs it says so, instead of telling you to start the build that is running.
      status(s) {
        if (s.type === "guide") return ["On air. The guide is drawn live: nothing needs scheduling.", "has-text-success"];
        if (s.type === "web") return ["On air on your players (not in Emby or Jellyfin): a menu, nothing needs scheduling.", "has-text-success"];
        const doing = this.doing(s), now = doing ? ` ${doing[0].toUpperCase()}${doing.slice(1)}.` : "";
        if (!s.scheduled_until) {
          return doing ? [`Off air: ${doing}.`, "has-text-warning"]
            : ["Off air: nothing is scheduled yet. Open Edit and use Save and build to make a schedule.", "has-text-danger"];
        }
        if (!s.on_air) return [`Off air: the schedule ended ${fmtWhen(s.scheduled_until)}.` + (now || " Add days to put it back on."), doing ? "has-text-warning" : "has-text-danger"];
        if (s.low) return [`On air, but the schedule ends ${fmtWhen(s.scheduled_until)}.` + (now || " Add days soon."), "has-text-warning"];
        return [`On air. Scheduled until ${fmtWhen(s.scheduled_until)}.`, "has-text-success"];
      },

      // ---- the schedule keeper
      async loadKeeper() {
        const k = await call("/api/keeper");
        const kp = this.keeper;
        if (!kp.loaded) {                 // the boxes are filled once: a reload every few seconds must not undo what you are choosing
          kp.enabled = k.settings.enabled;
          if (!kp.options.includes(k.settings.days_ahead)) kp.options = [...kp.options, k.settings.days_ahead].sort((a, b) => a - b);
          kp.days = k.settings.days_ahead;
          kp.loaded = true;
        }
        const st = k.status;
        let text, cls = "has-text-grey";
        if (!k.settings.enabled) {
          text = "Off. Stations will go off air when their schedule runs out.";
        } else if (st.error) {
          text = `Could not check the stations: ${st.error}`;
          cls = "has-text-danger";
        } else if (!st.last_pass) {
          text = "On. It checks a little after the dashboard starts, then every 30 minutes.";
        } else {
          text = `On. Last checked ${fmtWhen(st.last_pass)}.`;
          text += st.last_action
            ? " Last topped up: " + st.last_action.added.map((a) => `${a.station} (+${a.days} day${a.days === 1 ? "" : "s"})`).join(", ") + ` at ${fmtWhen(st.last_action.at)}.`
            : " Nothing has needed topping up yet.";
          if (st.more) text += " Still catching up on a long gap.";
          cls = "has-text-success";
        }
        kp.text = text;
        kp.cls = cls;
        // the folded panel's one line; a keeper that is off or failing is worth a look, so it says so in red
        kp.bad = !k.settings.enabled || !!st.error;
        kp.short = st.error ? "could not check the stations" : k.settings.enabled ? `on · ${k.settings.days_ahead} days ahead` : "off: stations go off air when their schedule runs out";
      },
      async saveKeeper(tell) {
        try {
          await call("/api/keeper/settings", { enabled: this.keeper.enabled, days_ahead: Number(this.keeper.days) });
          this.keeper.loaded = false;
          await this.loadKeeper();
          if (tell) say("Saved.", "ok");
          return true;
        } catch (e) {
          say(e.message, "err");
          return false;
        }
      },
      async toggleKeeper() {
        if (await this.saveKeeper(false)) say(this.keeper.enabled ? "Schedules will be kept topped up." : "Switched off: stations will go off air when their schedule runs out.", "ok");
        else this.keeper.enabled = !this.keeper.enabled;
      },

      // ---- the caption language
      async loadCaptions() {
        const c = await call("/api/captions");
        const lang = c.settings.language;
        if (!this.captions.options.some((o) => o[0] === lang)) this.captions.options = [...this.captions.options, [lang, lang]];
        this.captions.language = lang;
        this.captions.short = this.captions.options.find((o) => o[0] === lang)[1];
      },
      saveCaptions() {
        return run(async () => {
          await call("/api/captions/settings", { language: this.captions.language });
          await this.loadCaptions();
          say("Saved. The caption language is used from the next programme.", "ok");
        });
      },

      // ---- builds: the card shows a bar until the job ends
      build(name, days, rebuild, refresh = false, resume = false) {
        return run(async () => this.follow(name, await call("/api/stations/build", { name, days, rebuild, refresh, resume })));
      },
      async follow(name, job) {
        this.jobs[name] = job;
        try {
          const last = await W.followJob(job.id, (j) => { this.jobs[name] = j; });
          say(`${name}: ${last.message}`, last.state === "done" ? "ok" : "err");
        } finally {
          delete this.jobs[name];          // never leave a station looking busy after an error
          await this.load().catch(() => {});
        }
      },
      rebuild(s) {
        return run(async () => {
          if (!await W.confirm(`Rebuild the whole schedule of “${s.name}”? This throws its schedule away and makes a new one from scratch (7 days). The channel keeps playing the old schedule until the new one is ready. To just bring in videos you added, use Update videos instead: it leaves the schedule alone.`, { ok: "Rebuild", danger: true })) return;
          await this.build(s.name, 7, true);
        });
      },
      rename(s) {
        return run(async () => {
          const to = await W.prompt(`New name for “${s.name}”?`, s.name, { ok: "Rename" });
          if (!to || to === s.name) return;
          if (!await W.confirm(`Rename “${s.name}” to “${to}”? FieldStation42 keeps a station's schedule under its name, so the old schedule is cleared and a new catalog and 7 days are built under the new name. It is off air for a moment.`, { ok: "Rename" })) return;
          const out = await call("/api/stations/rename", { name: s.name, to });
          await this.load();
          if (out.job) await this.follow(out.name, out.job);
          else say(`Renamed to “${out.name}”.`, "ok");
        });
      },
      remove(s) {
        return run(async () => {
          if (!await W.confirm(`Delete the station “${s.name}”? Its lists and your media are not touched.`, { ok: "Delete", danger: true })) return;
          await call("/api/stations/delete", { name: s.name });
          await this.load();
          say(`Deleted “${s.name}”.`, "ok");
        });
      },
    }));
  });
})();
