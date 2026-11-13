// The Lists & files tab of the Settings page: build the lists (tag folders) a station plays from. Names come from
// your disk, so every one is put on the page as text.
(function () {
  "use strict";
  const { call, say, run } = W;

  // one view of the media: the pool of links (or the media folders when there is no pool), with the converted
  // YouTube library showing up inside it as a folder
  const ROOT = "media", LABEL = "Media";
  const REBUILD = "A station that uses this list needs its catalog rebuilt in the schedule console to see the change.";
  const list = (root, path) => call(`/api/files/list?root=${encodeURIComponent(root)}&path=${encodeURIComponent(path)}`);
  const join = (a, b) => (a ? `${a}/${b}` : b);
  const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

  // A YouTube channel keeps its videos in yearly seasons (Season 2026), and some downloaders put its shorts and streams in
  // seasons of their own (Season 12026, Season 22026): choose a kind in one go instead of every season
  const KIND_NAMES = { videos: "standard videos", shorts: "shorts", streams: "streams" };
  const KIND_LABEL = { videos: "Standard videos", shorts: "Shorts", streams: "Streams" };
  const seasonKind = (name) => {
    const m = /^Season (\d{4,5})$/.exec(name.trim());
    if (!m || Number(m[1]) < 1000) return null;
    const n = Number(m[1]);
    return n >= 20000 ? "streams" : n >= 10000 ? "shorts" : "videos";
  };

  document.addEventListener("alpine:init", () => {
    Alpine.data("filesTab", () => ({
      ROOT, LABEL, KIND_NAMES, KIND_LABEL, join,
      edit: true, warning: "",
      // your media (the left pane)
      src: { path: "" }, srcEntries: [], srcTruncated: false, srcLoaded: false, srcPick: [], followOn: true,
      // the lists (the right pane)
      tags: [], tagsLoaded: false, tag: null, tagPath: "", tagEntries: [], tagPick: [],
      follows: [], refs: [], refChoice: "", newName: "",
      counts: {}, counting: false,
      job: null,                         // an "add to a list" that is running, for its progress bar
      inUse: null,                       // sources made for stations, and which stations use them

      init() {
        run(async () => {
          const info = await call("/api/files/info");
          this.edit = info.edit;
          if (!info.edit) this.warning = "Changing lists is switched off on this server (DASHBOARD_EDIT=0). You can still browse.";
          if (!info.tags) this.warning = "There is no catalog/by-genre folder yet. It is created when the container starts.";
          if (info.roots[ROOT]) await this.openSrc("");
          else this.warning = "No media is mounted in the container, so there is nothing to browse.";
          if (info.tags) await this.loadTags(false);
          this.loadSources();
        });
      },

      // ---- small helpers
      crumbs(rootLabel, path) {
        const parts = path ? path.split("/") : [];
        return [{ label: rootLabel, to: "" }, ...parts.map((p, i) => ({ label: p, to: parts.slice(0, i + 1).join("/") }))];
      },
      fmtSize(n) {
        if (n == null) return "";
        const u = ["B", "KB", "MB", "GB", "TB"];
        let i = 0;
        while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
        return `${n >= 10 || i === 0 ? Math.round(n) : n.toFixed(1)} ${u[i]}`;
      },
      selectable: (e) => e.kind === "dir" || !!e.video,      // a show can go in a list (a pool of shows) or be a source of its own

      // ---- your media
      openSrc(path) {
        return run(async () => {
          const data = await list(ROOT, path);
          this.src = { path: data.path };
          this.srcPick = [];
          this.srcEntries = data.entries;
          this.srcTruncated = !!data.truncated;
          this.srcLoaded = true;
        });
      },
      get kinds() {
        if (!this.src.path.includes("/")) return [];
        return ["videos", "shorts", "streams"].filter((k) => this.srcEntries.some((e) => e.kind === "dir" && seasonKind(e.name) === k));
      },
      useKind(k) {
        return run(async () => {
          const out = await call("/api/files/add-show", { path: this.src.path, types: [k] });
          say(`“${out.tag}” is a source now${out.linking ? " (its videos are being linked)" : ""}. Choose it in a station's slot.`, "ok");
          await this.loadSources();
          await this.openSrc(this.src.path);
        });
      },
      // a show can be a source of its own: a station picks it from its Shows menu
      toggleShow(e) {
        return run(async () => {
          const out = await call(e.source ? "/api/files/remove-show" : "/api/files/add-show", e.source ? { tag: e.source } : { path: join(this.src.path, e.name) });
          say(e.source ? `“${e.name}” is no longer a source.` : `“${out.tag}” is now a source: pick it from the Shows menu when you edit a station.`, "ok");
          await this.openSrc(this.src.path);
        });
      },
      get addLabel() {
        if (!this.tag) return "Pick a list to add to";
        return this.srcPick.length ? `Add ${this.srcPick.length} to “${this.tag}”` : `Add to “${this.tag}”`;
      },
      addPicked() {
        return this.addSources(this.srcPick.map((name) => ({ root: ROOT, path: join(this.src.path, name) })));
      },
      // Many channels can be tens of thousands of links: it runs on the server in the background and the bar shows how far it is.
      addSources(sources) {
        return run(async () => {
          let out;
          try {
            const started = await call("/api/files/add", { tag: this.tag, sources, follow: this.followOn, background: true });
            this.job = { message: `Adding to “${started.tag}”… looking through what you picked` };
            for (;;) {
              await W.sleep(800);
              const j = await call(`/api/files/add-status?id=${encodeURIComponent(started.id)}`);
              if (j.state === "running") {
                this.job = { ...j, message: `Adding to “${started.tag}”… ${j.message} (${j.elapsed}s)` };
                continue;
              }
              if (j.state === "error") throw new Error(j.message);
              out = j.result;
              break;
            }
          } finally {
            this.job = null;
          }
          let text = `Added ${plural(out.added, "link")} to “${out.tag}”`;
          if (out.already_there) text += ` (${out.already_there} already there)`;
          if (out.following && out.following.length) text += `. Kept up to date: ${out.following.join(", ")}`;
          text += `. ${REBUILD}`;
          if (out.notes.length) text += ` Skipped: ${out.notes.slice(0, 3).join("; ")}${out.notes.length > 3 ? "; ..." : ""}`;
          this.srcPick = [];
          await this.loadTags(true);
          say(text, out.added || out.already_there ? "ok" : "err");
        });
      },

      // ---- the lists
      // The video counts come from a scan of every list that can take minutes on a big library, so the lists are drawn
      // first and the counts fill in as the scan reports them (the server never makes this page wait for it).
      async loadCounts(tries = 0) {
        try {
          const lib = await call("/library.json");           // the last scheduled scan: opening this page never starts one
          const counts = {};
          for (const t of lib.tags || []) counts[t.tag] = t.videos;
          this.counts = counts;
          this.counting = !!lib.never;                       // no scan has finished yet since the server started
          if (lib.never && tries < 90) setTimeout(() => this.loadCounts(tries + 1), 10000);
        } catch (e) { this.counting = false; }               // counts are a nicety
      },
      countText(name) {
        return this.counts[name] != null ? `${this.counts[name]} videos` : this.counting ? "not counted yet" : "";
      },
      async loadTags(keepOpen) {
        const data = await list("tags", "");
        this.loadCounts();
        this.tags = data.entries.filter((e) => e.kind === "dir");
        this.tagsLoaded = true;
        if (this.tag && !this.tags.some((t) => t.name === this.tag)) this.tag = null;
        else if (this.tag && keepOpen) await this.openTag(this.tag, this.tagPath);
      },
      openTag(tag, path) {
        return run(async () => {
          call(`/api/files/follows?tag=${encodeURIComponent(tag)}`).then((d) => { this.follows = d.follows; }).catch(() => {});
          this.refs = this.tags.map((t) => t.name).filter((n) => n !== tag);
          if (!this.refs.includes(this.refChoice)) this.refChoice = this.refs[0] || "";
          const data = await list("tags", join(tag, path));
          this.tag = tag;
          this.tagPath = path;
          this.tagPick = [];
          this.tagEntries = data.entries;
        });
      },
      followMeta(f) {
        if (f.error) return f.error;
        if (!f.last_checked) return "not checked yet";
        const when = new Date(f.last_checked * 1000).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
        return `checked ${when}${f.last_added ? `, ${f.last_added} new` : ""}`;
      },
      unfollow(f) {
        return run(async () => {
          await call("/api/files/unfollow", { tag: this.tag, root: f.root, path: f.path });
          this.follows = (await call(`/api/files/follows?tag=${encodeURIComponent(this.tag)}`)).follows;
          say(`No longer keeping “${f.path}” up to date. What is already in the list stays.`, "ok");
        });
      },
      addRef() {
        return run(async () => {
          const name = this.refChoice;
          if (!name) return;
          const out = await call("/api/files/add", { tag: this.tag, sources: [{ root: "tags", path: name }], follow: true });
          await this.openTag(this.tag, this.tagPath);
          say(`“${name}” is now inside “${this.tag}” and stays in step with it (${plural(out.added, "link")} added). ${REBUILD}`, "ok");
        });
      },
      createTag() {
        return run(async () => {
          const out = await call("/api/files/create-tag", { name: this.newName });
          this.newName = "";
          this.tag = out.tag;
          this.tagPath = "";
          await this.loadTags(true);
          say(`Created the list “${out.tag}”. Pick videos on the left and add them.`, "ok");
        });
      },
      removePicked() {
        return run(async () => {
          const n = this.tagPick.length;
          if (!await W.confirm(`Remove ${plural(n, "item")} from “${this.tag}”? Only the links go; your media is not touched.`, { ok: "Remove", danger: true })) return;
          const out = await call("/api/files/remove", { tag: this.tag, paths: this.tagPick.map((name) => join(this.tagPath, name)) });
          await this.loadTags(true);
          say(`Removed ${plural(out.removed, "link")}.` +
            (out.refused.length ? ` Left alone, because they are real files: ${out.refused.slice(0, 3).join(", ")}.` : "") +
            ` ${REBUILD}`, out.refused.length ? "err" : "ok");
        });
      },
      renameTag() {
        return run(async () => {
          const to = await W.prompt(`New name for “${this.tag}”? A station that uses the old name must be changed to the new one.`, this.tag, { ok: "Rename" });
          if (!to || to === this.tag) return;
          const out = await call("/api/files/rename-tag", { tag: this.tag, to });
          this.tag = out.tag;
          await this.loadTags(true);
          say(`Renamed to “${out.tag}”. ${out.note}.`, "ok");
        });
      },
      deleteTag() {
        return run(async () => {
          if (!await W.confirm(`Delete the list “${this.tag}”? Only its links are removed; your media is not touched.`, { ok: "Delete", danger: true })) return;
          const out = await call("/api/files/delete-tag", { tag: this.tag });
          this.tag = null;
          await this.loadTags(false);
          say(`Deleted “${out.tag}” (${plural(out.removed, "link")} removed).`, "ok");
        });
      },

      // ---- sources made for stations, and which stations use them
      async loadSources() {
        try { this.inUse = await call("/api/files/sources-in-use"); } catch (e) { this.inUse = null; }
      },
      get idle() { return (this.inUse && this.inUse.empty_unused) || []; },
      get inUseCount() {
        if (!this.inUse) return "";
        const s = this.inUse.sources, idle = this.idle;
        return (s.length ? `(${s.length}, ${s.filter((x) => !x.used_by.length).length} not used` : "(") +
          (idle.length ? `${s.length ? ", " : ""}${plural(idle.length, "empty list")} no station uses` : "") + ")";
      },
      describeSource(s) {
        const what = (s.members || []).map((m) => `${m.path.split("/").pop()}${m.types ? ` (${m.types.join(", ")})` : ""}`).join(", ");
        return `${s.tag} — ${s.kind || "source"}${what && s.kind === "set" ? `: ${what}` : ""} — ` +
          (s.used_by.length ? `used by ${s.used_by.join(", ")}` : "not used by any station");
      },
      removeSource(s) {
        return run(async () => {
          await call("/api/files/remove-show", { tag: s.tag });
          say(`Removed “${s.tag}”.`, "ok");
          await this.loadSources();
          await this.loadTags(true);
        });
      },
      deleteIdle(name) {
        return run(async () => {
          if (!await W.confirm(`Delete the empty list “${name}”? Nothing is in it and no station uses it.`, { ok: "Delete", danger: true })) return;
          await call("/api/files/delete-tag", { tag: name });
          say(`Deleted “${name}”.`, "ok");
          await this.loadSources();
          await this.loadTags(true);
        });
      },
    }));
  });
})();
