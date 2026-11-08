(function () {
  "use strict";

  // The Files page: build the lists (tag folders) a station plays from. Names come from your disk, so every
  // one is put on the page with textContent, never as HTML.

  // one view of the media: the pool of links (or the media folders when there is no pool), with the converted
  // YouTube library showing up inside it as a folder
  const ROOT = "media", LABEL = "Media";
  const $ = (id) => document.getElementById(id);

  const state = {
    edit: true,
    roots: {},
    src: { root: "media", path: "" },
    srcPick: new Set(),
    tag: null,
    tagPath: "",
    tagPick: new Set(),
    counts: {},
  };


  // ---- talking to the server
  async function call(path, body) {
    const opts = body === undefined ? {} : {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    };
    let res, data;
    const tries = body === undefined ? 8 : 1;          // looking things up is safe to repeat through a short restart
    for (let attempt = 1; ; attempt++) {
      try {
        res = await fetch(path, opts);
        data = await res.json();
        break;
      } catch (e) {
        if (attempt >= tries) throw new Error("could not reach the dashboard");
        await new Promise((r) => setTimeout(r, 1500));
      }
    }
    if (res.status === 401) {                      // not logged in (or the session ended): log in, then come back
      location.assign("/login.html?next=" + encodeURIComponent(location.pathname + location.search));
      throw new Error("you need to log in");
    }
    if (!res.ok) throw new Error(data.error || `that failed (${res.status})`);
    return data;
  }
  const list = (root, path) => call(`/api/files/list?root=${encodeURIComponent(root)}&path=${encodeURIComponent(path)}`);

  function say(text, kind) {
    const el = $("msg");
    el.textContent = text || "";
    el.className = "files-msg" + (kind ? " " + kind : "");
    if (text && el.scrollIntoView) el.scrollIntoView({ block: "nearest" });          // the answer is at the top: bring it into view
  }
  async function run(fn) {
    try {
      await fn();
    } catch (e) {
      say(e.message, "err");
    }
  }

  // ---- small helpers
  function el(tag, props, ...kids) {
    const node = document.createElement(tag);
    Object.assign(node, props || {});
    for (const k of kids) node.append(k);
    return node;
  }
  const join = (a, b) => (a ? `${a}/${b}` : b);
  function fmtSize(n) {
    if (n == null) return "";
    const u = ["B", "KB", "MB", "GB", "TB"];
    let i = 0;
    while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
    return `${n >= 10 || i === 0 ? Math.round(n) : n.toFixed(1)} ${u[i]}`;
  }

  function crumbs(nav, rootLabel, path, go) {
    nav.replaceChildren();
    const parts = path ? path.split("/") : [];
    const add = (label, to) => {
      if (nav.childNodes.length) nav.append(el("span", { className: "sep", textContent: "/" }));
      const b = el("button", { type: "button", textContent: label });
      b.addEventListener("click", () => go(to));
      nav.append(b);
    };
    add(rootLabel, "");
    parts.forEach((p, i) => add(p, parts.slice(0, i + 1).join("/")));
  }

  // ---- the sources pane
  async function openSrc(root, path) {
    const data = await list(root, path);
    state.src = { root, path: data.path };
    state.srcPick.clear();
    crumbs($("src-crumbs"), LABEL, data.path, (to) => run(() => openSrc(root, to)));
    const ul = $("src-list");
    ul.replaceChildren();
    if (!data.entries.length) ul.append(el("li", { className: "empty", textContent: "Nothing here." }));
    for (const e of data.entries) ul.append(srcRow(e));
    if (data.truncated) ul.append(el("li", { className: "empty", textContent: "Only the first part of this folder is shown. Open a sub-folder." }));
    drawKinds(data);
    updateButtons();
  }

  // ---- a YouTube channel keeps its videos in yearly seasons (Season 2026), and some downloaders put its shorts and streams in
  // seasons of their own (Season 12026, Season 22026): choose a kind in one go instead of every season
  const KIND_NAMES = { videos: "standard videos", shorts: "shorts", streams: "streams" };
  const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);
  const seasonKind = (name) => {
    const m = /^Season (\d{4,5})$/.exec(name.trim());
    if (!m || Number(m[1]) < 1000) return null;
    const n = Number(m[1]);
    return n >= 20000 ? "streams" : n >= 10000 ? "shorts" : "videos";
  };
  function drawKinds(data) {
    const box = $("src-kinds");
    box.replaceChildren();
    const here = state.src.path;
    const kinds = ["videos", "shorts", "streams"].filter((k) => data.entries.some((e) => e.kind === "dir" && seasonKind(e.name) === k));
    box.hidden = !(here.includes("/") && kinds.length);
    if (box.hidden) return;
    box.append(el("span", { className: "dim", textContent: "This channel, by kind:" }));
    for (const k of kinds) {
      const add = el("button", { type: "button", className: "btn", textContent: "Add all", disabled: !(state.edit && state.tag) });
      add.title = state.tag ? `Every season of ${KIND_NAMES[k]}, kept up to date as new ones appear (if “Keep folders up to date” is ticked)` : "Pick a list first";
      add.dataset.kind = k;
      add.addEventListener("click", () => run(() => addSources([{ root: state.src.root, path: here, types: [k] }])));
      const src = el("button", { type: "button", className: "btn", textContent: "Use as a source", disabled: !state.edit });
      src.title = "A source of its own that a station can play without a list being made first";
      src.addEventListener("click", () => run(async () => {
        const out = await call("/api/files/add-show", { path: here, types: [k] });
        say(`“${out.tag}” is a source now${out.linking ? " (its videos are being linked)" : ""}. Choose it in a station's slot.`, "ok");
        await loadSources().catch(() => {});
        await openSrc(state.src.root, state.src.path);
      }));
      box.append(el("div", { className: "kind-row" }, el("span", { className: "kind-name", textContent: cap(KIND_NAMES[k]) }), add, src));      // one line per kind: its two buttons stay together
    }
  }

  function srcRow(e) {
    const selectable = e.kind === "dir" || e.video;      // a show can go in a list (a pool of shows) or be a source of its own
    const li = el("li", { className: e.kind === "dir" ? "dir" : selectable ? "" : "dim" });
    const box = el("input", { type: "checkbox", disabled: !selectable });
    box.setAttribute("aria-label", `Select ${e.name}`);
    box.addEventListener("change", () => {
      box.checked ? state.srcPick.add(e.name) : state.srcPick.delete(e.name);
      updateButtons();
    });
    const name = el("span", { className: "name" });
    if (e.kind === "dir") {
      const b = el("button", { type: "button", textContent: e.name + "/" });
      b.addEventListener("click", () => run(() => openSrc(state.src.root, join(state.src.path, e.name))));
      name.append(b);
    } else {
      name.textContent = e.label || e.name;   // a movie in its own folder shows as just the movie
      if (e.label) name.title = e.name;
    }
    const meta = e.kind === "dir" ? "" : fmtSize(e.size);
    li.append(box, name, el("span", { className: "meta", textContent: meta }));
    if (e.show) {            // a show can be a source of its own: a station picks it from its Shows menu
      li.append(el("span", { className: "meta", textContent: "show" }));
      const b = el("button", { type: "button", className: "btn", textContent: e.source ? "Stop using as a source" : "Use as a source" });
      b.title = e.source ? "Stations stop being able to pick this show" : "Stations can pick this show directly, apart from your lists. New episodes are added on their own.";
      b.addEventListener("click", () => run(async () => {
        const path = join(state.src.path, e.name);
        const out = await call(e.source ? "/api/files/remove-show" : "/api/files/add-show", e.source ? { tag: e.source } : { path });
        say(e.source ? `“${e.name}” is no longer a source.` : `“${out.tag}” is now a source: pick it from the Shows menu when you edit a station.`, "ok");
        await openSrc(state.src.root, state.src.path);
      }));
      li.append(b);
    }
    li.dataset.name = e.name;
    return li;
  }

  function setAll(ul, pick, on) {
    pick.clear();
    for (const li of ul.children) {
      const box = li.querySelector("input[type=checkbox]");
      if (!box || box.disabled) continue;
      box.checked = on;
      if (on) pick.add(li.dataset.name);
    }
    updateButtons();
  }

  // ---- the lists pane
  // The video counts come from a scan of every list that can take minutes on a big library, so the lists are drawn
  // first and the counts fill in as the scan reports them (the server never makes this page wait for it).
  let countsTimer = null;
  function paintCounts() {
    for (const li of $("tag-list").children) {
      const n = li.dataset.tag != null ? state.counts[li.dataset.tag] : null;
      const c = li.querySelector(".count");
      if (c) c.textContent = n != null ? `${n} videos` : (state.counting ? "not counted yet" : "");
    }
  }
  async function loadCounts(fresh, tries = 0) {
    clearTimeout(countsTimer);
    try {
      const lib = await call("/library.json");           // the last scheduled scan: opening this page never starts one
      state.counts = {};
      for (const t of lib.tags || []) state.counts[t.tag] = t.videos;
      state.counting = !!lib.never;                      // no scan has finished yet since the server started
      state.scanAge = lib.age_seconds;
      paintCounts();
      if (lib.never && tries < 90) countsTimer = setTimeout(() => loadCounts(false, tries + 1).catch(() => {}), 10000);
    } catch (e) { state.counting = false; paintCounts(); }        // counts are a nicety
  }

  async function loadTags(keepOpen, fresh = true) {
    const data = await list("tags", "");
    loadCounts(fresh);
    const ul = $("tag-list");
    ul.replaceChildren();
    const tags = data.entries.filter((e) => e.kind === "dir");
    if (!tags.length) ul.append(el("li", { className: "empty", textContent: "No lists yet. Create one above." }));
    for (const t of tags) {
      const li = el("li");
      li.dataset.tag = t.name;
      li.setAttribute("aria-current", String(t.name === state.tag));
      li.append(el("span", { textContent: t.name }),
        el("span", { className: "count", textContent: state.counts[t.name] != null ? `${state.counts[t.name]} videos` : "" }));
      li.addEventListener("click", () => run(() => openTag(t.name, "")));
      ul.append(li);
    }
    if (state.tag && !tags.some((t) => t.name === state.tag)) {
      state.tag = null;
      $("tag-view").hidden = true;
    } else if (state.tag && keepOpen) {
      await openTag(state.tag, state.tagPath);
    }
    updateButtons();
  }

  async function loadFollows(tag) {
    const data = await call(`/api/files/follows?tag=${encodeURIComponent(tag)}`);
    const ul = $("follow-list");
    ul.replaceChildren();
    $("follows").hidden = !data.follows.length;
    for (const f of data.follows) {
      const li = el("li", { className: f.error ? "dead" : "" });
      li.append(el("span", { className: "name", textContent: f.root === "tags" ? `the list “${f.path}”` : f.path }));
      li.append(el("span", { className: "meta", textContent: f.error ? f.error
        : f.last_checked ? `checked ${fmtWhen(f.last_checked)}${f.last_added ? `, ${f.last_added} new` : ""}` : "not checked yet" }));
      const b = el("button", { type: "button", className: "btn", textContent: "Stop", disabled: !state.edit });
      b.addEventListener("click", () => run(async () => {
        await call("/api/files/unfollow", { tag, root: f.root, path: f.path });
        await loadFollows(tag);
        say(`No longer keeping “${f.path}” up to date. What is already in the list stays.`, "ok");
      }));
      li.append(b);
      ul.append(li);
    }
  }

  async function fillRefs(tag) {
    const all = (await list("tags", "")).entries.filter((e) => e.kind === "dir" && e.name !== tag);
    const sel = $("ref-list");
    sel.replaceChildren(...all.map((e) => el("option", { value: e.name, textContent: e.name })));
    $("ref-row").hidden = !all.length;
  }
  $("ref-btn").addEventListener("click", () => run(async () => {
    const name = $("ref-list").value;
    if (!name) return;
    const out = await call("/api/files/add", { tag: state.tag, sources: [{ root: "tags", path: name }], follow: true });
    await openTag(state.tag, state.tagPath);
    say(`“${name}” is now inside “${state.tag}” and stays in step with it (${out.added} link${out.added === 1 ? "" : "s"} added). ${REBUILD}`, "ok");
  }));

  async function openTag(tag, path) {
    loadFollows(tag).catch(() => {});
    fillRefs(tag).catch(() => {});
    const data = await list("tags", join(tag, path));
    state.tag = tag;
    state.tagPath = path;
    state.tagPick.clear();
    for (const li of $("tag-list").children) {
      li.setAttribute("aria-current", String(li.firstChild && li.firstChild.textContent === tag));
    }
    $("tag-view").hidden = false;
    crumbs($("tag-crumbs"), tag, path, (to) => run(() => openTag(tag, to)));
    const ul = $("tag-contents");
    ul.replaceChildren();
    if (!data.entries.length) ul.append(el("li", { className: "empty", textContent: "This list is empty. Pick videos on the left and add them." }));
    for (const e of data.entries) {
      const li = el("li", { className: e.kind === "dir" ? "dir" : e.link && !e.ok ? "dead" : "" });
      const box = el("input", { type: "checkbox" });
      box.setAttribute("aria-label", `Select ${e.name}`);
      box.addEventListener("change", () => {
        box.checked ? state.tagPick.add(e.name) : state.tagPick.delete(e.name);
        updateButtons();
      });
      const name = el("span", { className: "name" });
      if (e.kind === "dir" && !e.link) {
        const b = el("button", { type: "button", textContent: e.name + "/" });
        b.addEventListener("click", () => run(() => openTag(tag, join(path, e.name))));
        name.append(b);
      } else {
        name.textContent = e.name;
      }
      const meta = e.link ? (e.ok ? "link" : "dead link") : e.kind === "file" ? "real file" : "";
      li.append(box, name, el("span", { className: "meta", textContent: meta }));
      li.dataset.name = e.name;
      ul.append(li);
    }
    updateButtons();
  }

  // ---- buttons
  function updateButtons() {
    const edit = state.edit;
    const add = $("add-btn");
    add.disabled = !(edit && state.tag && state.srcPick.size);
    const n = state.srcPick.size;
    add.textContent = !state.tag ? "Pick a list to add to" : n ? `Add ${n} to “${state.tag}”` : `Add to “${state.tag}”`;
    for (const b of $("src-kinds").querySelectorAll("button[data-kind]")) b.disabled = !(edit && state.tag);       // a channel's kinds of video
    $("remove-btn").disabled = !(edit && state.tag && state.tagPick.size);
    $("rename-btn").disabled = !(edit && state.tag);
    $("delete-btn").disabled = !(edit && state.tag);
    $("new-form").querySelector("button").disabled = !edit;
  }

  $("src-all").addEventListener("click", () => setAll($("src-list"), state.srcPick, true));
  $("src-none").addEventListener("click", () => setAll($("src-list"), state.srcPick, false));
  $("tag-all").addEventListener("click", () => setAll($("tag-contents"), state.tagPick, true));
  $("tag-none").addEventListener("click", () => setAll($("tag-contents"), state.tagPick, false));

  const REBUILD = "A station that uses this list needs its catalog rebuilt in the schedule console to see the change.";

  $("new-form").addEventListener("submit", (ev) => {
    ev.preventDefault();
    run(async () => {
      const name = $("new-name").value;
      const out = await call("/api/files/create-tag", { name });
      $("new-name").value = "";
      state.tag = out.tag;
      state.tagPath = "";
      await loadTags(true);
      say(`Created the list “${out.tag}”. Pick videos on the left and add them.`, "ok");
    });
  });

  $("add-btn").addEventListener("click", () => run(() => addSources(
    [...state.srcPick].map((name) => ({ root: state.src.root, path: join(state.src.path, name) })))));

  async function addSources(sources) {
    // many channels can be tens of thousands of links: it runs on the server in the background and the page shows how far it is
    $("add-btn").disabled = true;
    let out;
    try {
      const started = await call("/api/files/add", { tag: state.tag, sources, follow: $("follow-on").checked, background: true });
      say("Adding… looking through what you picked", "ok");
      for (;;) {
        await new Promise((r) => setTimeout(r, 800));
        const j = await call(`/api/files/add-status?id=${encodeURIComponent(started.id)}`);
        if (j.state === "running") {
          say(`Adding to “${started.tag}”… ${j.message} (${j.elapsed}s)`, "ok");
          continue;
        }
        if (j.state === "error") throw new Error(j.message);
        out = j.result;
        break;
      }
    } finally {
      updateButtons();
    }
    let text = `Added ${out.added} link${out.added === 1 ? "" : "s"} to “${out.tag}”`;
    if (out.already_there) text += ` (${out.already_there} already there)`;
    if (out.following && out.following.length) text += `. Kept up to date: ${out.following.join(", ")}`;
    text += `. ${REBUILD}`;
    if (out.notes.length) text += ` Skipped: ${out.notes.slice(0, 3).join("; ")}${out.notes.length > 3 ? "; ..." : ""}`;
    state.srcPick.clear();
    for (const box of $("src-list").querySelectorAll("input[type=checkbox]")) box.checked = false;
    await loadTags(true);
    say(text, out.added || out.already_there ? "ok" : "err");
  }

  $("remove-btn").addEventListener("click", () => run(async () => {
    const n = state.tagPick.size;
    if (!confirm(`Remove ${n} item${n === 1 ? "" : "s"} from “${state.tag}”? Only the links go; your media is not touched.`)) return;
    const paths = [...state.tagPick].map((name) => join(state.tagPath, name));
    const out = await call("/api/files/remove", { tag: state.tag, paths });
    await loadTags(true);
    say(`Removed ${out.removed} link${out.removed === 1 ? "" : "s"}.` +
      (out.refused.length ? ` Left alone, because they are real files: ${out.refused.slice(0, 3).join(", ")}.` : "") +
      ` ${REBUILD}`, out.refused.length ? "err" : "ok");
  }));

  $("rename-btn").addEventListener("click", () => run(async () => {
    const to = prompt(`New name for “${state.tag}”? A station that uses the old name must be changed to the new one.`, state.tag);
    if (!to || to === state.tag) return;
    const out = await call("/api/files/rename-tag", { tag: state.tag, to });
    state.tag = out.tag;
    await loadTags(true);
    say(`Renamed to “${out.tag}”. ${out.note}.`, "ok");
  }));

  $("delete-btn").addEventListener("click", () => run(async () => {
    if (!confirm(`Delete the list “${state.tag}”? Only its links are removed; your media is not touched.`)) return;
    const out = await call("/api/files/delete-tag", { tag: state.tag });
    state.tag = null;
    $("tag-view").hidden = true;
    await loadTags(false);
    say(`Deleted “${out.tag}” (${out.removed} link${out.removed === 1 ? "" : "s"} removed).`, "ok");
  }));

  function fmtWhen(sec) {
    if (!sec) return "";
    return new Date(sec * 1000).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  }

  // ---- sources made for stations, and which stations use them
  async function loadSources() {
    const card = $("sources-card");
    let data;
    try { data = await call("/api/files/sources-in-use"); } catch (e) { card.hidden = true; return; }
    const idle = data.empty_unused || [];
    card.hidden = !data.sources.length && !idle.length;
    $("sources-count").textContent = (data.sources.length ? `(${data.sources.length}, ${data.sources.filter((s) => !s.used_by.length).length} not used` : "(") +
      (idle.length ? `${data.sources.length ? ", " : ""}${idle.length} empty list${idle.length === 1 ? "" : "s"} no station uses` : "") + ")";
    const box = $("sources-list");
    box.replaceChildren();
    for (const s of data.sources) {
      const row = el("div", { className: "chooser-row" });
      const what = (s.members || []).map((m) => `${m.path.split("/").pop()}${m.types ? ` (${m.types.join(", ")})` : ""}`).join(", ");
      row.append(el("span", { textContent: `${s.tag} — ${s.kind || "source"}${what && s.kind === "set" ? `: ${what}` : ""} — ` +
        (s.used_by.length ? `used by ${s.used_by.join(", ")}` : "not used by any station") }));
      if (!s.used_by.length && state.edit && data.known_stations !== undefined) {
        const b = el("button", { type: "button", className: "btn", textContent: "Remove" });
        b.addEventListener("click", () => run(async () => {
          await call("/api/files/remove-show", { tag: s.tag });
          say(`Removed “${s.tag}”.`, "ok");
          await loadSources();
          await loadTags(true);
        }));
        row.append(b);
      }
      box.append(row);
    }
    if (idle.length) {
      box.append(el("p", { className: "dim", textContent: "Lists with no videos that no station uses (a template makes one for each part of the day):" }));
      for (const name of idle) {
        const row = el("div", { className: "chooser-row" }, el("span", { textContent: name }));
        if (state.edit) {
          const b = el("button", { type: "button", className: "btn", textContent: "Delete" });
          b.addEventListener("click", () => run(async () => {
            if (!confirm(`Delete the empty list “${name}”? Nothing is in it and no station uses it.`)) return;
            await call("/api/files/delete-tag", { tag: name });
            say(`Deleted “${name}”.`, "ok");
            await loadSources();
            await loadTags(true);
          }));
          row.append(b);
        }
        box.append(row);
      }
    }
  }
  $("sources-card").addEventListener("toggle", () => { if ($("sources-card").open) run(loadSources); });

  // ---- start
  run(async () => {
    const info = await call("/api/files/info");
    state.edit = info.edit;
    state.roots = info.roots;
    if (!info.edit) say("Changing lists is switched off on this server (DASHBOARD_EDIT=0). You can still browse.", "err");
    if (!info.tags) say("There is no catalog/by-genre folder yet. It is created when the container starts.", "err");
    if (info.roots[ROOT]) await openSrc(ROOT, "");
    else say("No media is mounted in the container, so there is nothing to browse.", "err");
    if (info.tags) await loadTags(false, false);
    updateButtons();
    loadSources().catch(() => {});
  });
})();
