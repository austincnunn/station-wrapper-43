// The station editor: what a station is, and for a scheduled one the week it plays (default, seasons, special days),
// drawn on the calendar (calendar.js keeps the dragging; this file keeps everything around it).
// Two Alpine components: stationPage (the whole form) and chooser (pick lists, series, seasons, folders or videos).
(function () {
  "use strict";
  const { call, say, run } = W;

  const params = new URLSearchParams(location.search);
  const original = params.get("name");          // null: a new station
  const copyOf = params.get("copy");            // a new station that starts as a copy of this one

  // "bump" holds the interstitial clips and "commercials" the ad breaks: neither is something to schedule as a program
  const NOT_PROGRAMS = new Set(["bump", "commercials"]);
  const DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"];
  const WEEKEND = ["saturday", "sunday"];
  const SEASONS = ["spring", "summer", "fall", "winter"];
  const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
  const NTHS = [[1, "1st"], [2, "2nd"], [3, "3rd"], [4, "4th"], [5, "5th"], [-1, "last"]];
  const cap = (d) => d[0].toUpperCase() + d.slice(1);
  const clone = (x) => JSON.parse(JSON.stringify(x));
  const pad = (n) => String(n).padStart(2, "0");
  const md = (s) => s.split("-").map(Number);
  const emptyDay = () => ({ videos: [], commercials: [], cards: [] });
  const nearest = (options, v) => options.reduce((a, b) => (Math.abs(b - v) < Math.abs(a - v) ? b : a));
  const weekColumns = () => DAYS.map((d) => ({ key: d, label: cap(d).slice(0, 3) }));
  const newDefinition = () => ({
    default: Object.fromEntries(DAYS.map((d) => [d, { videos: [{ from: 0, to: 24, lists: [] }], commercials: [], cards: [] }])),
    seasons: { dates: { spring: "03-01", summer: "06-01", fall: "09-01", winter: "12-01" }, spring: null, summer: null, fall: null, winter: null },
    events: [],
  });

  // ---- start from a template: the slot length and a week laid out for a kind of channel (the lists are yours to choose)
  const TEMPLATES = [
    { id: "", label: "A blank week" },
    { id: "movies", label: "A movie channel: one list all day, 5 minute slots", increment: 5, hint: "A movie is rounded up to the next 5 minutes, not the next half hour.",
      week: () => [[0, 24, "movies"]] },
    { id: "allday", label: "One list, all day, in 30 minute slots", increment: 30, week: () => [[0, 24, "everything"]] },
    { id: "cartoons", prefix: "Cartoons", label: "A cartoon channel (like Cartoon Network): young kids early, teens mid-day, adult cartoons after 10 pm", increment: 30,
      week: (d) => (WEEKEND.includes(d)
        ? [[0, 6, "adult cartoons"], [6, 12, "young kids"], [12, 20, "teens"], [20, 22, "family"], [22, 24, "adult cartoons"]]
        : [[0, 6, "adult cartoons"], [6, 11, "young kids"], [11, 17, "teens"], [17, 22, "family"], [22, 24, "adult cartoons"]]) },
    { id: "mainstream", prefix: "Mainstream", label: "A mainstream channel: a full week with a morning show, mid-day talk, a cartoon block, prime time and late night", increment: 30,
      week: (d) => (WEEKEND.includes(d)
        ? [[0, 7, "overnight"], [7, 12, "weekend cartoons"], [12, 19, "movies and sports"], [19, 23, "prime time"], [23, 24, "late night"]]
        : [[0, 5, "overnight"], [5, 9, "morning show"], [9, 11, "daytime"], [11, 14, "mid-day talk shows"], [14, 15.5, "afternoon"],
           [15.5, 17.5, "cartoon block"], [17.5, 19, "early evening"], [19, 23, "prime time"], [23, 24, "late night"]]) },
    { id: "music", label: "A music channel (like Music Choice): one list of songs all day, shuffled", increment: 30,
      hint: "Put music (mp3, flac, m4a…) in the list, a whole artist or album folder at a time: each song plays over a card with its cover, its name, its album and what is up next.",
      week: () => [[0, 24, "music"]] },
    { id: "loop", label: "A loop: one list repeating all day (shuffled)", loop: true },
  ];
  const clockText = (h) => `${String(Math.floor(h)).padStart(2, "0")}:${h % 1 ? "30" : "00"}`;
  function layoutText(t) {
    const line = (d) => t.week(d).map(([a, b, what]) => `${clockText(a)}–${clockText(b)} ${what}`).join(", ");
    return t.week("monday").length > 1 ? `Weekdays: ${line("monday")}. Weekends: ${line("saturday")}.` : "";
  }

  // ---- the chooser's helpers
  const TYPE_NAMES = { videos: "All standard videos", shorts: "All shorts", streams: "All streams" };
  const seasonKind = (name) => {
    const m = /^Season (\d{4,5})$/.exec(name.trim());
    if (!m) return null;
    const n = Number(m[1]);
    return n >= 20000 ? "streams" : n >= 10000 ? "shorts" : "videos";
  };
  const memberText = (m) => `${m.path.split("/").pop()}${m.types ? ` (${m.types.join(", ")})` : m.root === "tags" ? " (list)" : ""}`;
  // a folder inside a list ("Night Shift/After Dark/Futurama") reads as its own name, with where it is
  const listText = (n) => (n.includes("/") ? `${n.split("/").pop()} (in ${n.split("/").slice(0, -1).join(" / ")})` : n);
  const sameMember = (a, b) => a.root === b.root && a.path === b.path && JSON.stringify(a.types || null) === JSON.stringify(b.types || null);
  const mediaList = (() => {
    const cache = new Map();
    return (path) => {
      if (!cache.has(path)) cache.set(path, call(`/api/files/list?root=media&path=${encodeURIComponent(path)}`).catch((e) => { cache.delete(path); throw e; }));
      return cache.get(path);
    };
  })();

  // The chooser's markup, written once: it is used for every field that picks what plays.
  // IMPORTANT: Alpine calls any function an expression evaluates to. So nothing shown here is a function: a row or a
  // chip is plain data that says what a click would do, and only a click (openRow, useRow, removeChip) does it. A row
  // that held its own "use" function was once called just by being drawn, which chose every video it showed.
  const CHOOSER = `
<div class="tags">
  <template x-for="c in chips" :key="c.text">
    <span class="tag is-rounded is-medium"><span x-text="c.text"></span><button type="button" class="delete is-small" x-show="c.removable" :aria-label="'Remove ' + c.text" @click="removeChip(c)"></button></span>
  </template>
  <span class="has-text-grey" x-show="cfg.combine && value && linking.includes(value)">linking its videos…</span>
  <span class="has-text-grey" x-show="!chips.length" x-text="cfg.none || (many ? 'Nothing chosen yet.' : 'Nothing chosen.')"></span>
</div>
<div class="buttons"><button type="button" class="button is-small" :aria-expanded="open" @click="toggle()" x-text="many ? 'Add…' : 'Change…'"></button></div>
<div class="chooser-panel" x-show="open">
  <nav class="breadcrumb is-small" aria-label="Where you are"><ul>
    <template x-for="c in crumbs" :key="c.root + '/' + c.path"><li><a href="#" @click.prevent="go(c.root, c.path)" x-text="c.text"></a></li></template>
  </ul></nav>
  <ul class="rows scroll">
    <template x-for="(r, i) in rows" :key="i">
      <li>
        <a href="#" class="name" x-show="r.open !== null" @click.prevent="openRow(r)" x-text="r.text"></a>
        <span class="name" x-show="r.open === null" x-text="r.text"></span>
        <button type="button" class="button is-small" x-show="r.use !== null || r.why !== ''" :disabled="r.use === null || !edit" :title="r.why" @click="useRow(r)" x-text="many ? 'Add' : 'Use'"></button>
      </li>
    </template>
    <li class="has-text-grey" x-show="empty" x-text="empty"></li>
  </ul>
  <p class="help" role="status" x-text="note"></p>
</div>`;

  let cal = null;                // the calendar on screen (calendar.js). Kept out of Alpine: it is an engine, not data.

  document.addEventListener("alpine:init", () => {
    // ---- the chooser: lists are folders like any other. Open "Lists" or "Media", go down into series, seasons, folders and
    // lists, and use any of them, one video, a YouTube playlist, or all of a channel's shorts, streams or standard videos.
    // Lists are for files you want to reuse; anything from the media (or a video inside a list) becomes a source of its own the
    // first time it is chosen, so nothing needs a list made first. A field that takes one list (a mid card, a commercial)
    // can still have several: they are put together as one source ("combine").
    // cfg: { get(), set(value), multi, combine, folders, none, pool }
    //   multi: the value is a list of names. combine: one name, made of several members. folders: the choice is a folder
    //   of the Lists, at any depth, used as it is (an intro card's folder): no Media, no videos.
    //   pool: which of the page's lists to offer ("lists" or "playable").
    Alpine.data("chooser", (cfg) => ({
      cfg,
      open: false, loc: { root: "", path: "" }, rows: [], crumbs: [], empty: "", note: "",

      init() {
        this.$el.classList.add("chooser");
        this.$el.innerHTML = CHOOSER;
        // Alpine has already walked past this element by now, and inside a x-for or x-if it is not watching for new
        // children either, so they are handed to it here (one that it did pick up is left alone: it marks what it has done).
        const host = this.$el;
        queueMicrotask(() => { for (const child of [...host.children]) Alpine.initTree(child); });
      },
      get value() { return this.cfg.get(); },
      get many() { return !!(this.cfg.multi || this.cfg.combine); },
      kindOf(n) {
        if (this.shows.includes(n)) return (this.showKinds[n] || "series") + (this.linking.includes(n) ? ", linking…" : "");
        return n.includes("/") ? "folder" : "list";
      },
      current() {                       // what a combined value is made of
        const v = this.value;
        return this.cfg.combine && v ? this.members[v] || [{ root: "tags", path: v }] : [];
      },
      get chips() {
        const c = this.cfg, v = this.value;
        if (c.combine) return this.current().map((m) => ({ text: memberText(m), removable: true, member: m }));
        const names = c.multi ? v : v ? [v] : [];
        return names.map((n) => ({ text: c.folders ? listText(n) : `${listText(n)} (${this.kindOf(n)})`, removable: !!(c.multi || c.none), name: n }));
      },
      removeChip(chip) {
        const c = this.cfg;
        if (!chip.removable) return;
        if (c.combine) return this.setMembers(this.current().filter((x) => !sameMember(x, chip.member)));
        c.set(c.multi ? this.value.filter((s) => s !== chip.name) : "");
      },
      // A row of the browser is data: text, where opening it goes (open: {root, path} or null), what using it chooses
      // (use: {list} | {folder} | {source: body for /api/files/add-show} or null), and why it can't be used (why).
      openRow(r) { if (r.open) return this.go(r.open.root, r.open.path); },
      useRow(r) {
        const u = r.use;
        if (!u || !this.edit) return;
        if (u.list !== undefined) return this.chooseList(u.list);
        if (u.folder !== undefined) return this.pickFolder(u.folder);
        return this.useSource(u.source);
      },

      fail(e) {
        this.note = String(e.message || e);           // where you are looking: a message at the top may be off screen
        say(this.note, "err");
      },
      noteSource(out) {                 // something from the media just became a source: the page knows it from now on
        if (!this.shows.includes(out.tag)) this.shows.push(out.tag);
        this.showKinds[out.tag] = out.kind || "series";
        if (out.linking) this.trackLinking(out.tag);
      },
      async setMembers(members) {
        if (!members.length) return this.cfg.set("");
        if (members.length === 1 && members[0].root === "tags") return this.cfg.set(members[0].path);
        this.note = "Adding…";
        try {
          const out = await call("/api/files/add-show", members.length === 1 ? { path: members[0].path, types: members[0].types } : { members });
          this.noteSource(out);
          this.members[out.tag] = members;
          this.note = "";
          this.cfg.set(out.tag);
        } catch (e) {
          this.fail(e);
        }
      },
      addMember(m) { return this.setMembers([...this.current().filter((x) => !sameMember(x, m)), m]); },
      chooseList(name) {
        const c = this.cfg;
        if (c.combine) return this.addMember({ root: "tags", path: name });
        c.set(c.multi ? [...this.value.filter((n) => n !== name), name] : name);
        if (!c.multi) this.open = false;
      },
      async useSource(body) {                                       // body: {path, types?} or {list_path}
        this.note = "Adding…";
        try {
          if (this.cfg.combine) {
            let path = body.path;
            if (body.list_path) path = (await call(`/api/files/media-path?list_path=${encodeURIComponent(body.list_path)}`)).path;
            this.note = "";
            return this.addMember({ root: "media", path, ...(body.types ? { types: body.types } : {}) });
          }
          const out = await call("/api/files/add-show", body);               // it becomes a source the first time it is chosen
          this.noteSource(out);
          this.note = "";
          this.chooseList(out.tag);
        } catch (e) {
          this.fail(e);
        }
      },
      pickFolder(path) {
        this.cfg.set(path);
        this.open = false;
      },

      toggle() {
        this.open = !this.open;
        if (this.open) this.draw();
      },
      go(root, path) {
        this.loc = { root, path };
        return this.draw();
      },
      async draw() {
        const loc = this.loc, c = this.cfg, rows = [];
        const row = (text, open, use, why) => rows.push({ text, open: open || null, use: use || null, why: why || "" });
        const parts = loc.path ? loc.path.split("/") : [];
        this.crumbs = [{ text: "Browse", root: "", path: "" },
          ...(loc.root ? [{ text: loc.root === "lists" ? "Lists" : "Media", root: loc.root, path: "" }] : []),
          ...parts.map((p, i) => ({ text: p, root: loc.root, path: parts.slice(0, i + 1).join("/") }))];
        this.empty = "";
        if (!loc.root) {
          row("Lists (files you re-use)", { root: "lists", path: "" });
          if (!c.folders) row("Media (series, seasons, folders, videos, playlists)", { root: "media", path: "" });
          this.rows = rows;
          return;
        }
        let entries = [];
        try {
          if (loc.root === "lists" && !loc.path) entries = this[c.pool || "lists"].map((n) => ({ name: n, kind: "dir", list: true }));
          else if (loc.root === "lists") entries = (await call(`/api/files/list?root=tags&path=${encodeURIComponent(loc.path)}`)).entries;
          else entries = (await mediaList(loc.path)).entries;
        } catch (e) {
          this.rows = [];
          this.empty = String(e.message || e);
          return;
        }
        if (loc !== this.loc) return;                                      // somewhere else was opened while this was being read
        const here = (n) => (loc.path ? `${loc.path}/${n}` : n);
        if (c.folders) {
          if (loc.path) row("This folder", null, { folder: loc.path });
          const dirs = entries.filter((e) => e.kind === "dir");
          if (!dirs.length) this.empty = "No folders in here.";
          for (const e of dirs) row(e.name, { root: "lists", path: here(e.name) }, { folder: here(e.name) });
          this.rows = rows;
          return;
        }
        if (loc.root === "lists" && loc.path && !loc.path.includes("/")) row("This whole list", null, { list: loc.path });
        if (loc.root === "media" && loc.path.includes("/")) {
          // a YouTube channel keeps shorts, streams and standard videos in seasons of their own: choose a kind in one go
          const kinds = [...new Set(entries.filter((e) => e.kind === "dir").map((e) => seasonKind(e.name)).filter(Boolean))];
          if (kinds.length && entries.some((e) => /^Season \d{4,5}$/.test(e.name) && Number(e.name.split(" ")[1]) >= 1000)) {
            for (const k of ["videos", "shorts", "streams"].filter((x) => kinds.includes(x))) {
              row(`${TYPE_NAMES[k]} (every season, kept up to date)`, null, { source: { path: loc.path, types: [k] } });
            }
          }
        }
        if (!entries.length) this.empty = "Nothing here.";
        for (const e of entries) {
          const isDir = e.kind === "dir";
          const text = e.label || e.name;
          if (!isDir && !e.video && e.kind !== "playlist") continue;          // videos and playlists are choosable
          if (loc.root === "lists" && !loc.path) {
            row(e.name, { root: "lists", path: e.name }, { list: e.name });
          } else if (loc.root === "lists") {
            row(text, isDir ? { root: "lists", path: here(e.name) } : null, e.kind === "playlist" ? null : { source: { list_path: here(e.name) } });
          } else {
            const top = !loc.path;                                           // a whole top folder of the media is not one choice
            const holder = isDir && (top || text === "_Playlists");           // nor is the folder the playlists are kept in
            row(e.kind === "playlist" ? `${text} (YouTube playlist)` : text,
              isDir ? { root: "media", path: here(e.name) } : null,
              holder ? null : { source: { path: here(e.name) } },
              holder ? (text === "_Playlists" ? "Open it and choose a playlist" : "Open it and choose a series, a season, or a video inside") : "");
          }
        }
        this.rows = rows;
      },
    }));

    // ---- the page
    Alpine.data("stationPage", () => ({
      DAYS, SEASONS, MONTHS, NTHS, TEMPLATES, cap, md, original,
      SCHEDULE_TABS: [["default", "Default"], ...SEASONS.map((s) => [s, cap(s)]), ["special", "Special days"]],
      LAYERS: [["videos", "Videos"], ["commercials", "Commercials"], ["cards", "Mid cards"]],
      consoleHref: `${location.protocol}//${location.hostname}:4242/static/stations.html`,

      title: original || (copyOf ? "New station (a copy)" : "New station"),
      loaded: false, locked: "", edit: true, dirty: false, watching: false,
      showTemplates: false, template: "", templateHint: "Fills in the slot length and the week for you. Everything can still be changed, and nothing is saved until you press Save.",
      form: {
        name: "", number: "", logo: "", captrack: true, kind: "standard",
        increment: 30, breaks: "end", snap: false, pack: true, cards: false, bump: "", bumpEnd: "", com: false, comlist: "",
        looplist: "", shuffle: false, episodes: true,
        guide: { title: "Channel Guide", hours: 3, theme: "modern-blue", aspect: "16:9", text_size: "normal", scroll_speed: 1, messages: "", coming_up: false, music: "" },
        ppv: { folder: "", theme: "modern", seconds: 10 },
      },
      schedule: null,            // the definition being edited (see schedules.py): default, seasons, events
      tab: "default",            // "default", a season, or "special"
      layer: "videos",           // "videos", "commercials" or "cards"
      eventId: null,             // the special day being edited
      lastLists: [],             // what the last slot drawn played, to start the next one the same
      lastAds: "",
      lists: [],                 // names of the lists (tag folders)
      playable: [],              // the ones a station can play as programs
      shows: [],                 // shows already used as sources (made into hidden lists)
      showKinds: {},             // list name -> series / season / episode / folder
      members: {},               // what each source list is made of (from /api/files/shows), for the choosers
      linking: [],               // sources picked a moment ago whose videos are still being linked in
      pendingLists: [],          // lists a template named, made when the station is saved (they may stay empty for now)
      mediaDirs: [],             // suggestions for the music and movie folders: the folders inside your media
      hasView: false, columns: [], sel: null, problem: "",
      preview: [], previewError: "", summary: "",
      saving: "", job: null,

      init() {
        window.addEventListener("beforeunload", (e) => { if (this.dirty) { e.preventDefault(); e.returnValue = ""; } });
        // anything you change makes the page "not saved", and the summary and the next 14 days are worked out again
        this.$watch("form", () => this.touched());
        this.$watch("schedule", () => { this.touched(); this.schedulePreview(); });
        run(() => this.start());
      },

      async start() {
        const [tags, lib, shows] = await Promise.all([call("/api/files/list?root=tags&path="), call("/api/stations"),
          call("/api/files/shows").catch(() => ({ shows: [] }))]);
        this.shows = shows.shows || [];
        this.showKinds = shows.kinds || {};
        this.members = shows.members || {};
        call("/api/files/list?root=media&path=").then((m) => { this.mediaDirs = m.entries.filter((e) => e.kind === "dir").map((e) => e.name); }).catch(() => {});
        this.edit = lib.edit;
        call("/api/titles").then((n) => { this.form.episodes = n.settings.episode_names; }).catch(() => {});
        this.lists = tags.entries.filter((e) => e.kind === "dir").map((e) => e.name);
        this.playable = this.lists.filter((n) => !NOT_PROGRAMS.has(n));
        if (original) {
          const got = await call(`/api/stations/get?name=${encodeURIComponent(original)}`);
          if (!got.form) {
            this.locked = got.why || "uses settings this form can't hold";
            return;
          }
          this.apply(got.form);
        } else if (copyOf) {
          const got = await call(`/api/stations/get?name=${encodeURIComponent(copyOf)}`);
          if (!got.form) throw new Error(`“${copyOf}” can't be copied here: ${got.why || "it uses settings this form can't hold"}.`);
          this.apply({ ...got.form, name: `${copyOf} copy`, number: null });
        } else {
          const bump = this.lists.includes("bump") ? "bump" : this.lists[0];
          this.apply({ name: "", number: null, kind: "standard", schedule: null, increment: 30, breaks: "end", bump, commercials: "", midcards: false });
          this.showTemplates = true;                  // a new station can start from a template
        }
        this.loaded = true;
        await this.$nextTick();
        this.redraw();                                // the calendar needs its box on screen
        await this.$nextTick();
        this.dirty = false;
        this.watching = true;
        if (!original) { this.$refs.name.focus(); if (copyOf) this.$refs.name.select(); }
      },

      // ---- what saving and building would do, in words, and a warning before leaving with changes that were not saved
      touched() {
        if (this.watching) this.dirty = true;
        clearTimeout(this._summary);
        this._summary = setTimeout(() => { this.summarise().catch(() => {}); }, 300);
      },
      get live() { return this.form.kind === "guide" || this.form.kind === "ppv"; },     // drawn live, or by each player: nothing to build
      async summarise() {
        if (this.live) { this.summary = ""; return; }
        if (!this._counts) {
          try {
            const lib = await (await fetch("/library.json")).json();
            this._counts = lib.never ? {} : Object.fromEntries((lib.tags || []).map((t) => [t.tag, t.videos]));
          } catch (e) { this._counts = {}; }
        }
        const counts = this._counts;
        let names = [];
        if (this.form.kind === "loop") names = [this.form.looplist];
        else if (this.schedule) {
          const weeks = [this.schedule.default, ...Object.values(this.schedule.seasons).filter((x) => x && x.monday)];
          for (const w of weeks) for (const d of DAYS) for (const b of w[d].videos) names.push(...b.lists);
          for (const ev of this.schedule.events) {
            const ds = ev.mode === "same" ? [ev.schedule] : DAYS.map((d) => ev.schedule[d]);
            for (const d of ds) for (const b of d.videos) names.push(...b.lists);
          }
        }
        names = [...new Set(names.filter(Boolean))];
        if (!names.length) { this.summary = "Nothing is chosen to play yet: click a slot on the calendar and choose a list, a series, a season or a video."; return; }
        const fresh = names.filter((n) => this.pendingLists.includes(n));
        const parts = names.filter((n) => !this.pendingLists.includes(n)).map((n) => (n in counts ? `${n} (${counts[n]} video${counts[n] === 1 ? "" : "s"})`
          : this.lists.includes(n) ? `${n} (a list)` : `${n} (a source)`));
        if (fresh.length) parts.push(`${fresh.length} new list${fresh.length === 1 ? "" : "s"} named for the parts of the day (made when you save, empty until you put videos in)`);
        const empty = names.filter((n) => counts[n] === 0);
        const breaks = this.form.com ? "Breaks use the default commercials" : "No breaks except in hours where you chose commercials";
        this.summary = `Plays from ${parts.join(", ")}. ${breaks}.` + (empty.length ? ` ${empty.join(", ")} ${empty.length === 1 ? "has" : "have"} no videos yet, so ${empty.length === 1 ? "it" : "they"} will play nothing.` : "");
      },

      // ---- the form, to and from what the server keeps
      apply(form) {
        const f = this.form;
        f.looplist = form.kind === "loop" ? form.loop.list : this.playable[0] || "";
        f.name = form.name;
        f.number = form.number == null ? "" : form.number;
        f.logo = form.logo || "";
        f.captrack = form.caption_track !== false;
        f.kind = form.kind;
        if (form.kind === "standard") {
          this.schedule = form.schedule ? clone(form.schedule) : newDefinition();
          this.tab = "default";
          this.eventId = null;
          const first = this.schedule.default.monday.videos[0];
          this.lastLists = first ? [...first.lists] : [];
          f.increment = Number(form.increment);
          f.breaks = form.breaks || "end";
          f.snap = !!form.snap;
          f.pack = form.pack !== false;
          f.bump = form.bump || "";
          f.bumpEnd = form.bump_end || form.bump || "";
          f.com = !!form.commercials;
          f.cards = form.midcards !== false;
          f.comlist = form.commercials || (this.lists.includes("commercials") ? "commercials" : this.lists[0] || "");
        } else if (form.kind === "guide") {
          const g = form.guide;
          Object.assign(f.guide, { title: g.title, theme: g.theme || "modern-blue", aspect: g.aspect || "16:9", text_size: g.text_size || "normal",
            hours: Number(g.hours), scroll_speed: nearest([0.6, 1, 1.8], g.scroll_speed), messages: g.messages.join("\n"), coming_up: !!g.coming_up, music: g.music });
        } else if (form.kind === "ppv") {
          Object.assign(f.ppv, { folder: form.ppv.folder, theme: form.ppv.theme || "modern", seconds: nearest([5, 10, 15, 30], form.ppv.seconds) });
        } else {
          f.shuffle = form.loop.shuffle;
        }
        if (this.loaded) this.$nextTick(() => this.redraw());
      },
      collect() {
        const f = this.form;
        const form = { name: f.name, number: f.number === "" || f.number == null ? null : Number(f.number), kind: f.kind, logo: f.logo.trim(), caption_track: f.captrack };
        if (f.kind === "standard") {
          Object.assign(form, { schedule: clone(this.schedule), increment: Number(f.increment), breaks: f.breaks, snap: f.snap, pack: f.pack,
            bump: f.bump, bump_end: f.bumpEnd, midcards: f.cards, commercials: f.com ? f.comlist : "" });
        } else if (f.kind === "guide") {
          const g = f.guide;
          form.guide = { title: g.title, hours: Number(g.hours), theme: g.theme, scroll_speed: Number(g.scroll_speed), aspect: g.aspect, text_size: g.text_size,
            messages: g.messages.split("\n").map((m) => m.trim()).filter(Boolean), music: g.music.trim(), coming_up: g.coming_up };
        } else if (f.kind === "ppv") {
          form.ppv = { folder: f.ppv.folder.trim(), theme: f.ppv.theme, seconds: Number(f.ppv.seconds) };
        } else {
          form.loop = { list: f.looplist, shuffle: f.shuffle };
        }
        return form;
      },
      applyTemplate(id) {
        const t = TEMPLATES.find((x) => x.id === id);
        if (!t || !t.id) return;
        const lists = this.playable;
        const name = this.form.name, number = this.form.number === "" ? null : Number(this.form.number);
        const bump = this.lists.includes("bump") ? "bump" : this.lists[0];
        if (t.loop) {
          this.apply({ name, number, kind: "loop", loop: { list: lists[0] || "", shuffle: true } });
        } else {
          const defn = newDefinition();
          // A template with a name for each part of the day (kids, mainstream) uses a list of its own for each, made when the
          // station is saved (a list may be empty at first: it is there to be filled), so the week has its shape and its names.
          // A template without one starts every part with your own lists in turn; click a slot to choose what really plays.
          const roles = [...new Set(DAYS.flatMap((d) => t.week(d).map((b) => b[2])))];
          const listFor = (role) => {
            if (t.prefix) {
              const made = `${t.prefix} - ${cap(role)}`;
              if (!this.lists.includes(made) && !this.pendingLists.includes(made)) this.pendingLists.push(made);
              return made;
            }
            return lists.length ? lists[roles.indexOf(role) % lists.length] : "";
          };
          for (const d of DAYS) defn.default[d].videos = t.week(d).map(([from, to, role]) => ({ from, to, lists: listFor(role) ? [listFor(role)] : [] }));
          this.apply({ name, number, kind: "standard", schedule: defn, increment: t.increment, breaks: "end", bump, commercials: "", midcards: false });
        }
        this.templateHint = [t.hint, t.week ? layoutText(t) : "",
          t.prefix ? `Each part of the day has a list of its own (“${t.prefix} - …”), made when you save, which can be empty for now: put videos in it on the Lists & files tab of Settings, or click a slot to choose something else.`
            : lists.length ? "The parts of the day start with your lists in turn; click a slot to choose what really plays."
            : "You have no lists yet: make one on the Lists & files tab of Settings, or click a slot to pick a series or folder directly."].filter(Boolean).join(" ");
      },

      // ---- the week (or single day) the calendar is showing, and what is true of it
      get ev() { return (this.schedule && this.schedule.events.find((e) => e.id === this.eventId)) || null; },
      view() {
        const s = this.schedule;
        if (!s || this.form.kind !== "standard") return null;
        if (this.tab === "default") return { columns: weekColumns(), day: (k) => s.default[k], full: false };
        if (SEASONS.includes(this.tab)) {
          const w = s.seasons[this.tab];
          return w ? { columns: weekColumns(), day: (k) => w[k], full: false } : null;
        }
        const ev = this.ev;
        if (!ev) return null;
        if (ev.mode === "same") return { columns: [{ key: "every", label: "Every day" }], day: () => ev.schedule, full: ev.replace };
        return { columns: weekColumns(), day: (k) => ev.schedule[k], full: ev.replace };
      },
      // A fresh calendar for each view, so no selection is left over from another tab.
      redraw() {
        const v = this.view();
        this.hasView = !!v;
        this.columns = v ? v.columns : [];
        if (!v) {
          cal = null;
          this.sel = null;
          this.problem = "";
          return;
        }
        cal = Calendar.create({
          host: this.$refs.calendar,
          columns: v.columns,
          getDay: (k) => this.view().day(k),
          layer: () => this.layer,
          full: () => this.view().full,
          // a slot drawn on a day that is already filled starts with no list (so it shows, and you choose); on a day with
          // gaps it starts like the last one you made. A cards or commercials block starts with nothing chosen.
          defaults: () => (this.layer === "videos" ? { lists: this.view().full ? [] : [...this.lastLists] }
            : this.layer === "cards" ? { start: "", end: "" } : { list: "" }),
          onChange: () => this.calendarChanged(),
          onSelect: () => this.calendarChanged(),
        });
        cal.render();
      },
      calendarChanged() {
        if (!cal) return;
        this.sel = cal.selected();
        const v = this.view();
        let text = "";
        for (const c of v ? v.columns : []) {
          const p = CalendarOps.problem(v.day(c.key).videos, v.full, true);
          if (p) { text = `${c.key === "every" ? "" : cap(c.key) + ": "}${p}.`; break; }
        }
        this.problem = text;
      },
      get layerNote() {
        if (this.layer === "videos") return "Times snap to half hours. A slot that starts or ends at half past can hold only one list.";
        if (this.layer === "cards") {
          return "Mid cards for a time period, by the hour: the list played at the start of a break and the one at its end (they can be the same). A video slot with cards of its own (choose it on the Videos tab) uses those; hours you leave empty use the station's own two lists (below)" +
            (this.form.cards ? "." : ", which are switched off: those hours have no cards, and a block you draw here turns cards on for its hours.");
        }
        return "Commercials are chosen by the hour, for the hours that have videos. Hours you leave empty use the station's own commercial list (below)" +
          (this.form.com ? "." : ", which is switched off: those hours have no breaks, and a block you draw here turns commercials on for its hours.");
      },

      // ---- the selected slot
      get blk() { return this.sel ? this.sel.block : {}; },
      get slotKey() { return this.sel ? `${this.tab}|${this.eventId}|${this.layer}|${this.sel.key}|${this.sel.i}` : ""; },
      get slotTitle() {
        const s = this.sel;
        return s ? `${CalendarOps.clock(s.block.from)} – ${CalendarOps.clock(s.block.to)}` + (s.key === "every" ? "" : `, ${cap(s.key)}`) : "";
      },
      setSlotLists(lists) {
        this.lastLists = lists;
        cal.update((x) => { x.lists = lists; });
      },
      setSlotIntro(v) { cal.update((x) => { if (v) x.intro = v; else delete x.intro; }); },
      setSlotCard(key, v) {
        cal.update((x) => {
          x[key] = v;
          if (!x.start && !x.end) { delete x.start; delete x.end; }
          else { x.start = x.start || x.end; x.end = x.end || x.start; }       // one chosen: the other is the same
        });
      },
      setSlotBurn(on) { cal.update((x) => { if (on) x.burn = true; else delete x.burn; }); },
      setLayerCard(key, v) { cal.update((x) => { x[key] = v; if (!x.end) x.end = x.start; }); },
      setAds(v) {
        this.lastAds = v;
        cal.update((x) => { x.list = v; });
      },
      removeSlot() { cal.removeSelected(); },
      copySlot() {
        cal.copySelected();
        say("Copied. Press Ctrl+V with the pointer where it should go.", "");
      },
      pasteOn(which) {
        const s = cal.selected();
        if (!s) return;
        const want = { weekdays: (k) => !WEEKEND.includes(k), weekend: (k) => WEEKEND.includes(k), all: () => true }[which];
        const keys = this.columns.map((c) => c.key).filter((k) => k !== s.key && want(k));
        if (keys.length) cal.pasteBlockOn(keys, clone(s.block));
      },

      // ---- seasons
      inheritSeason(same) {
        this.schedule.seasons[this.tab] = same ? null : clone(this.schedule.default);
        this.$nextTick(() => this.redraw());
      },
      setSeasonStart(m, d) {
        this.schedule.seasons.dates[this.tab] = `${pad(m)}-${pad(Math.min(d, new Date(2001, m, 0).getDate()))}`;
      },
      seasonRange(s) {
        const dates = this.schedule.seasons.dates;
        const order = [...SEASONS].sort((a, b) => dates[a].localeCompare(dates[b]));
        const [m, d] = md(dates[order[(order.indexOf(s) + 1) % 4]]);
        const end = new Date(2001, m - 1, d - 1);
        return `${MONTHS[end.getMonth()]} ${end.getDate()}`;
      },

      // ---- special days
      whenText(ev) {
        const w = ev.when;
        if (w.type === "nth") {
          return `${["", "1st", "2nd", "3rd", "4th", "5th"][w.nth] || "last"} ${cap(w.weekday)} of ${MONTHS[w.month - 1]}` + (w.days > 1 ? `, ${w.days} days` : "") + ", every year";
        }
        const [sm, sd] = md(w.start), [em, ed] = md(w.end);
        const span = w.start === w.end ? `${MONTHS[sm - 1]} ${sd}` : `${MONTHS[sm - 1]} ${sd} – ${MONTHS[em - 1]} ${ed}`;
        return span + (w.year ? `, ${w.year}` : ", every year");
      },
      addEvent() {
        const now = new Date();
        const day = `${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
        const ev = { id: Math.random().toString(16).slice(2, 10), name: "New special day", when: { type: "range", start: day, end: day, year: now.getFullYear() }, replace: false, mode: "same", schedule: emptyDay() };
        this.schedule.events.push(ev);
        this.eventId = ev.id;
        this.$nextTick(() => this.redraw());
      },
      async deleteEvent(ev) {
        if (!await W.confirm(`Delete “${ev.name}”?`, { ok: "Delete", danger: true })) return;
        this.schedule.events = this.schedule.events.filter((x) => x.id !== ev.id);
        if (this.eventId === ev.id) this.eventId = null;
        this.$nextTick(() => this.redraw());
      },
      setWhenType(type) {
        const now = new Date(), day = `${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
        this.ev.when = type === "nth" ? { type: "nth", month: 11, weekday: "thursday", nth: 4, days: 1 } : { type: "range", start: day, end: day, year: now.getFullYear() };
      },
      setEvDate(which, m, d) {
        const w = this.ev.when;
        w[which] = `${pad(m)}-${pad(Math.max(1, Math.min(31, d || 1)))}`;
        if (which === "start" && w.year && w.end < w.start) w.end = w.start;
      },
      async setEvMode(mode) {
        const ev = this.ev;
        if (mode === ev.mode) return;
        if (mode === "weekday") {
          ev.schedule = Object.fromEntries(DAYS.map((d) => [d, clone(ev.schedule)]));
        } else {
          const differ = DAYS.some((d) => JSON.stringify(ev.schedule[d]) !== JSON.stringify(ev.schedule.monday));
          if (differ && !await W.confirm("Use Monday's lineup for every day? The other days' lineups will be lost.", { ok: "Use Monday's", danger: true })) {
            this.$refs.evmode.value = ev.mode;
            return;
          }
          ev.schedule = clone(ev.schedule.monday);
        }
        ev.mode = mode;
        this.$nextTick(() => this.redraw());
      },
      setEvReplace(on) {
        const ev = this.ev;
        ev.replace = on;
        if (on) this.fillGaps(ev);
        this.$nextTick(() => this.redraw());
      },
      // a replaced day must be filled: give the empty stretches the first list so nothing is left bare
      fillGaps(ev) {
        const days = ev.mode === "same" ? [ev.schedule] : DAYS.map((d) => ev.schedule[d]);
        for (const day of days) {
          let blocks = clone(day.videos);
          if (!blocks.length) {
            blocks = [{ from: 0, to: 24, lists: [...this.lastLists] }];
          } else {
            blocks.sort((a, b) => a.from - b.from);
            const out = [];
            let mark = 0;
            for (const b of blocks) {
              if (b.from > mark) out.push({ from: mark, to: b.from, lists: [...blocks[0].lists] });
              out.push(b);
              mark = b.to;
            }
            if (mark < 24) out.push({ from: mark, to: 24, lists: [...blocks[blocks.length - 1].lists] });
            blocks = CalendarOps.tidy(out);
          }
          day.videos = blocks;
        }
      },

      // ---- which layer wins each of the next days, for the draft being edited
      schedulePreview() {
        clearTimeout(this._preview);
        this._preview = setTimeout(async () => {
          if (!this.schedule) return;
          try {
            this.preview = (await call("/api/stations/schedule-preview", { schedule: clone(this.schedule) })).days;
            this.previewError = "";
          } catch (e) {
            this.preview = [];
            this.previewError = e.message;
          }
        }, 500);
      },
      previewLabel(d) {
        const what = d.layer === "event" ? d.name + (d.replace ? "" : " (some slots)") : d.layer === "season" ? cap(d.name) : d.name === "default" ? "Default" : `${cap(d.name)} (default)`;
        return `${cap(d.weekday).slice(0, 3)} ${new Date(d.date + "T00:00:00").getDate()} · ${what}`;
      },

      // a big series on a slow share takes a while to link: the page carries on, and says so until it is done
      trackLinking(tag) {
        if (!this.linking.includes(tag)) this.linking.push(tag);
        if (this._linkTimer) return;
        this._linkTimer = setInterval(async () => {
          const got = await call("/api/files/shows").catch(() => null);
          if (!got) return;
          this.linking = got.linking || [];
          this.members = got.members || this.members;
          if (!this.linking.length) { clearInterval(this._linkTimer); this._linkTimer = null; }
        }, 2000);
      },

      // ---- saving
      async save() {
        const form = this.collect();
        if (this.pendingLists.length) {                        // the lists a template named are made now, if the station uses them
          const used = new Set((JSON.stringify(form).match(/"[^"]+"/g) || []).map((s) => JSON.parse(s)));
          for (const name of [...this.pendingLists]) {
            if (!used.has(name)) continue;
            try { await call("/api/files/create-tag", { name }); } catch (e) { if (!/already/i.test(e.message)) throw e; }
            if (!this.lists.includes(name)) this.lists.push(name);
            if (!this.playable.includes(name)) this.playable.push(name);
            this.pendingLists = this.pendingLists.filter((n) => n !== name);
          }
        }
        const out = await call("/api/stations/save", { original, form });
        if (form.kind === "guide") await call("/api/titles/settings", { episode_names: this.form.episodes });      // the episode names setting lives on this page
        await this.$nextTick();
        this.dirty = false;
        return out;
      },
      async during(what, fn) {
        this.saving = what;
        try {
          await fn();
        } catch (e) {
          say(e.message, "err");
        } finally {
          this.saving = "";
          this.job = null;
        }
      },
      saveOnly() {
        return this.during("save", async () => {
          const out = await this.save();
          say(`Saved “${out.name}”.` + (out.warnings.length ? " Note: " + out.warnings.join("; ") + "." : "") +
            " Use Save and build when you want the changes to take effect.", out.warnings.length ? "err" : "ok");
          if (!original) setTimeout(() => location.replace(`/station.html?name=${encodeURIComponent(out.name)}`), out.warnings.length ? 4000 : 1200);
        });
      },
      saveApply() {
        return this.during("apply", async () => {
          const out = await this.save();
          const r = await call("/api/stations/guide-apply", {});
          say(`Saved “${out.name}”. ` + (r.restarted ? "The guide restarted with your changes." : "Nobody is watching it, so it will start with your changes."), "ok");
          if (!original) setTimeout(() => location.replace(`/station.html?name=${encodeURIComponent(out.name)}`), 1200);
        });
      },
      saveBuild() {
        return this.during("build", async () => {
          const out = await this.save();
          this.job = await call("/api/stations/build", { name: out.name, days: 7, rebuild: true });
          const j = await W.followJob(this.job.id, (job) => { this.job = job; });
          if (j.state !== "done") throw new Error(j.message);
          say(`“${out.name}” is built and scheduled. Opening its schedule…`, "ok");
          setTimeout(() => location.assign(`/settings.html?name=${encodeURIComponent(out.name)}#schedule`), 1200);
        });
      },
    }));
  });
})();
