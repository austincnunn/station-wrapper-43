// The Status tab of the Settings page: what is wrong, what to look at, and what is fine (diag.py, /api/system/status).
(function () {
  "use strict";
  const { call, fmtWhen, say, run } = W;

  const MARK = { error: "✖", warn: "▲", ok: "✔" };
  const dur = (s) => (s >= 86400 ? `${Math.floor(s / 86400)}d ${Math.floor((s % 86400) / 3600)}h` : s >= 3600 ? `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m` : `${Math.floor(s / 60)}m`);

  document.addEventListener("alpine:init", () => {
    Alpine.data("statusTab", () => ({
      MARK,
      r: null,
      testing: false, speedText: "", speedBad: false,

      init() {
        run(() => this.load());
        setInterval(() => { if (W.onTab("status")) this.load().catch(() => {}); }, 15000);
      },
      async load() { this.r = await call("/api/system/status"); },

      get stationRows() {
        return this.r.stations.map((s) => [`#${s.number} ${s.name}`, s.type === "guide" ? "guide channel (drawn live)" :
          !s.scheduled_until ? "no schedule" : !s.on_air ? `off air: schedule ended ${fmtWhen(s.scheduled_until)}` :
          `on air, scheduled until ${fmtWhen(s.scheduled_until)}${s.low ? " (running low)" : ""}`]);
      },
      get systemRows() {
        const r = this.r, g = r.guide || {};
        return [
          ["Version", `${r.version.wrapper || "?"} (${(r.version.commit || "?").slice(0, 7)}), built ${r.version.built || "?"}`],
          ["Inside it", `FieldStation42 ${r.version.fieldstation42 || "?"}, ${r.ffmpeg.found ? r.ffmpeg.version : "ffmpeg NOT FOUND"}`],
          ["Running for", dur(r.uptime_seconds)],
          ["Console (:4242)", r.console.reachable ? `reachable, ${r.console.stations} stations` : `NOT reachable: ${r.console.error || ""}`],
          ["Media folder", `${r.media.path}: ${r.media.present ? "has files" : "EMPTY or missing"}`],
          ["Guide", `${g.age_seconds != null ? `built ${g.age_seconds}s ago` : "not built yet"}${g.last_build ? `, last build took ${g.last_build.seconds}s` : ""}; ` +
            Object.entries(g).filter(([k, v]) => v && typeof v === "object" && "channels" in v).map(([k, v]) => `${k}: ${v.channels} ch / ${v.programmes} programmes`).join(", ")],
          ["Sources", r.sources.length ? r.sources.map((s) => `${s.name} (${s.enabled ? s.channels + " ch" : "off"}${s.error ? ", ERROR" : ""})`).join(", ") : "none"],
          ["Streams", `${r.encoders.in_use} of ${r.encoders.max} encoders, ${r.viewers.in_use} of ${r.viewers.max} viewers`],
          ["CPU / memory", `load ${r.cpu.load1} on ${r.cpu.count} cores; ${r.memory ? r.memory.available_mb + " of " + r.memory.total_mb + " MB free" : "?"}`],
          ["Disk free", Object.entries(r.disk).map(([k, d]) => `${k} ${d.free_mb == null ? "?" : d.free_mb + " MB"}`).join(", ")],
        ];
      },
      // player PCs in client mode, and the FS42 TV apps
      get playerRows() {
        return (this.r.players || []).map((p) => (p.kind === "app"
          ? [p.name, `FS42 TV app on ${p.platform}` + (p.watching ? `, watching ${p.channel}` : `, last watched ${p.channel} ${dur(p.age)} ago`) + ` from ${p.addr}`]
          : [p.name, `${p.gone ? "NOT SEEN" : "seen"} ${dur(p.age)} ago from ${p.addr}` +
            (p.channel ? `, on ${p.channel}` : "") + (p.screen ? `, ${p.screen} screen` : "") + (p.mismatch ? ", DIFFERENT VERSION" : "") +
            (p.errors && p.errors.length ? `, ${p.errors.length} problem(s)` : "")]));
      },
      get recent() {
        return this.r.recent_problems.map((x) => `${new Date(x.at * 1000).toLocaleTimeString()}  ${x.line}`).join("\n");
      },

      async speed() {
        this.testing = true;
        this.speedText = "";
        try {
          const r = await call("/api/system/speedtest", {});
          this.speedBad = !!r.error || r.mb_per_s < 20;
          this.speedText = r.error ? r.error : `Read ${r.mb} MB of ${r.file} in ${r.seconds}s: ${r.mb_per_s} MB/s. ` +
            (r.mb_per_s < 20 ? "That is slow: catalog builds and seeking will be slow too (check the share's network and mount options)." : "That is fine.");
        } catch (e) {
          say(e.message, "err");
        }
        this.testing = false;
      },
    }));
  });
})();
