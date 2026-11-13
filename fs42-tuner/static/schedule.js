// The Schedule tab of the Settings page: what a station plays on a day, block by block, and the files inside a block.
// /settings.html?name=<station>#schedule opens on that station.
(function () {
  "use strict";
  const { call, fmtWhen, fmtTime, say, run } = W;

  const TYPE = { feature: "program", commercial: "commercial", bump: "mid card", stream: "stream" };
  const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

  document.addEventListener("alpine:init", () => {
    Alpine.data("scheduleTab", () => ({
      TYPE,
      stations: [], edit: true, busy: false,
      name: "", date: iso(new Date()),
      note: "", noteClass: "", blocks: [], truncated: false, empty: "",
      job: null,                        // the build that "Add 7 days" started, for its progress bar

      init() {
        run(async () => {
          const data = await call("/api/stations");
          this.edit = data.edit;
          this.stations = data.stations.filter((s) => s.type !== "guide" && s.type !== "web");
          if (!this.stations.length) {
            this.empty = "There are no stations yet. Make one on the Stations page.";
            return;
          }
          const wanted = new URLSearchParams(location.search).get("name");
          this.name = wanted && this.stations.some((s) => s.name === wanted) ? wanted : this.stations[0].name;
          await this.load();
        });
      },

      pick() {
        history.replaceState(null, "", `?name=${encodeURIComponent(this.name)}${location.hash}`);
        return this.load();
      },
      shift(days) {
        const d = new Date(this.date + "T00:00:00");
        d.setDate(d.getDate() + days);
        this.date = iso(d);
        return this.load();
      },
      today() {
        this.date = iso(new Date());
        return this.load();
      },

      load() {
        return run(async () => {
          if (!this.name) return;
          const s = await call(`/api/schedule?name=${encodeURIComponent(this.name)}&date=${encodeURIComponent(this.date)}`);
          let cls = "";
          if (!s.scheduled_until) {
            this.note = "Nothing is scheduled for this station yet. Build it from the Stations page.";
            cls = "has-text-danger";
          } else if (!s.on_air) {
            this.note = `Off air: the schedule ended ${fmtWhen(s.scheduled_until)}.`;
            cls = "has-text-danger";
          } else if (s.low) {
            this.note = `Scheduled until ${fmtWhen(s.scheduled_until)}: that is less than a day away, so add days soon.`;
            cls = "has-text-warning";
          } else {
            this.note = `Scheduled until ${fmtWhen(s.scheduled_until)}.`;
          }
          if (s.notes && s.notes.length) {                    // hours that play the test pattern because their lists are empty
            this.note += " " + s.notes.join(" ");
            cls = cls || "has-text-warning";
          }
          this.noteClass = cls || "has-text-grey";
          this.blocks = s.blocks.map((b) => ({ ...b, open: false, loaded: false, entries: [], total: 0 }));
          this.truncated = !!s.truncated;
          this.empty = s.blocks.length ? "" : s.beyond ? "That is further ahead than the schedule is shown." : "Nothing is scheduled on this day.";
        });
      },

      when(b) {
        const hours = (new Date(b.end) - new Date(b.start)) / 3600000;
        return hours >= 23 ? "All day (repeats)" : `${fmtTime(b.start)} – ${fmtTime(b.end)}`;
      },
      flip(b) {
        b.open = !b.open;
        if (b.open && !b.loaded) return this.more(b);
      },
      // the files inside one block, a page at a time: a looping station's day holds thousands of repeats
      more(b) {
        return run(async () => {
          const data = await call(`/api/schedule/block?name=${encodeURIComponent(this.name)}&start=${encodeURIComponent(b.start)}&offset=${b.entries.length}&limit=200`);
          b.entries.push(...data.entries);
          b.total = data.total;
          b.loaded = true;
        });
      },
      // FieldStation42's own title for the file when its catalog has one; the file name goes beside it, dimmer
      hasTitle: (e) => !!e.title && e.title !== e.file.replace(/\.[^.]+$/, ""),
      shownTitle(e) { return this.hasTitle(e) ? e.title : e.file; },
      fmtLen(sec) {
        sec = Math.round(sec);
        const m = Math.floor(sec / 60), s = sec % 60;
        return m ? `${m}m ${String(s).padStart(2, "0")}s` : `${s}s`;
      },

      extend() {
        return run(async () => {
          this.busy = true;
          try {
            this.job = await call("/api/stations/build", { name: this.name, days: 7, rebuild: false });
            const job = await W.followJob(this.job.id, (j) => { this.job = j; });
            say(job.message, job.state === "error" ? "err" : "ok");
          } finally {
            this.busy = false;
            this.job = null;
          }
          await this.load();
        });
      },
    }));
  });
})();
