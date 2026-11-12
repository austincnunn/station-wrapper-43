(function () {
  "use strict";

  const REFRESH_MS = 10 * 1000;
  // Thumbnails are cached in the browser for a minute, matching the server's
  // snapshot reuse, so a refresh doesn't re-request every frame.
  const THUMB_BUCKET_MS = 60 * 1000;

  const statsEl = document.getElementById("stats");
  const channelsEl = document.getElementById("channels");
  const statusEl = document.getElementById("status-line");
  const summaryEl = document.getElementById("summary");
  const sysEl = document.getElementById("sys");
  const sysSummaryEl = document.getElementById("sys-summary");
  let sysWarned = "";

  // An answer that is not 2xx (not logged in, restarting) is an error, never data.
  const get = (path) => fetch(path).then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); });

  // System and Library stay folded away under the channels; the browser remembers which you opened.
  document.querySelectorAll("details.fold").forEach((d) => {
    try { d.open = localStorage.getItem(`fold-${d.id}`) === "1"; } catch (e) { /* not remembered */ }
    d.addEventListener("toggle", () => { try { localStorage.setItem(`fold-${d.id}`, d.open ? "1" : "0"); } catch (e) { /* not remembered */ } });
  });

  function esc(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

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

  function card(label, value, sub, warn) {
    return `<div class="stat${warn ? " warn" : ""}">
      <div class="stat-label">${esc(label)}</div>
      <div class="stat-value">${esc(value)}</div>
      <div class="stat-sub">${esc(sub || "")}</div>
    </div>`;
  }

  function renderStats(sys) {
    const cpuPct = sys.cpu.count ? sys.cpu.load1 / sys.cpu.count : 0;
    const mem = sys.memory;
    const guide = sys.guide || {};
    const guideAge = guide.age_seconds;
    statsEl.innerHTML = [
      card("Channels on air", `${sys.schedule.channels_on_air}`,
           sys.schedule.db_modified ? `schedule written ${sys.schedule.db_modified.replace("T", " ").slice(0, 16)}` : "no schedule db",
           sys.schedule.channels_on_air === 0),
      card("Encoders", `${sys.encoders.in_use} / ${sys.encoders.max}`,
           `${sys.encoders.started_total} started since boot`,
           sys.encoders.in_use >= sys.encoders.max),
      card("Viewers", `${sys.viewers.in_use} / ${sys.viewers.max}`,
           `${sys.viewers.served_total} served, ${sys.viewers.refused_total} refused`,
           sys.viewers.refused_total > 0),
      card("CPU load", sys.cpu.load1.toFixed(2),
           `${sys.cpu.count} cores, 5m ${sys.cpu.load5.toFixed(2)}`,
           cpuPct > 0.9),
      card("Memory", mem ? `${mem.available_mb} MB free` : "unknown",
           mem ? `of ${mem.total_mb} MB` : "", mem && mem.available_mb < 512),
      card("Guide", fmtAge(guideAge),
           guide.fs42 ? `${guide.fs42.channels} channels, ${guide.fs42.programmes} programmes` : "",
           guideAge == null),
      readAheadCard(sys.prefetch),
      card("Uptime", fmtUptime(sys.uptime_seconds), "", false),
    ].join("");
    // The fold's one line: what needs a look, or that nothing does. A new warning opens the fold once.
    const warns = [...statsEl.querySelectorAll(".stat.warn .stat-label")].map((n) => n.textContent).join(", ");
    sysSummaryEl.textContent = warns ? `Check: ${warns}` : `No problems \u00b7 up ${fmtUptime(sys.uptime_seconds)}`;
    sysSummaryEl.classList.toggle("warn", !!warns);
    if (warns && warns !== sysWarned) sysEl.open = true;
    sysWarned = warns;
  }

  // the read-ahead: copies of the next break or episode made before they are due (prefetch.py)
  function readAheadCard(p) {
    if (!p) return "";
    if (!p.enabled) return card("Read-ahead", "off", p.why_not || "", false);
    const shares = Object.entries(p.shares || {}).map(([k, v]) => `${k.split("/").pop()}: ${v.mb_per_s != null ? v.mb_per_s + " MB/s" : "measuring"}, ${v.delay_s != null ? v.delay_s + "s to open" : ""}`).join("; ");
    return card("Read-ahead", `${p.cache.used_mb} / ${p.cache.max_mb} MB`,
                `${p.cache.files} files in ${p.ram ? "RAM" : "disk"}` + (p.copying ? `, copying ${p.copying}` : "") + (shares ? ` · ${shares}` : ""), false);
  }

  function renderChannels(rows) {
    const bucket = Math.floor(Date.now() / THUMB_BUCKET_MS);
    const loaded = new Map([...channelsEl.querySelectorAll(".thumb-img")].map((img) => [img.getAttribute("src"), img]));
    const watching = rows.reduce((sum, r) => sum + (r.viewers || 0), 0);
    summaryEl.textContent = `${rows.filter((r) => r.on_air).length} of ${rows.length} on air` + (watching ? ` \u00b7 ${watching} watching` : "");
    channelsEl.innerHTML = rows.map((r) => {
      const n = esc(r.channel);
      const now = r.now;
      let thumb;
      if (r.on_air && now && (!now.is_stream || now.content_type === "guide")) {   // the guide draws a picture of itself
        thumb = `<img class="thumb-img" alt="" loading="lazy" src="/thumb/${n}.jpg?b=${bucket}">`;
      } else {
        thumb = `<div class="thumb-off">${r.on_air ? "live" : "off air"}</div>`;
      }
      const pct = now && now.duration ? Math.min(100, (now.elapsed / now.duration) * 100) : 0;
      // only what is out of the ordinary gets a badge: every channel is normally on air
      const badges = [
        r.on_air ? "" : '<span class="badge off">off air</span>',
        r.encoding ? '<span class="badge enc">encoding</span>' : "",
        r.viewers ? `<span class="badge view">${r.viewers} watching</span>` : "",
      ].join("");
      let body = '<div class="now dim">Nothing scheduled</div>';
      if (now) {
        // a break names the show it interrupts as the title, so say what is really playing under it
        const filler = !["feature", "guide", "iptv"].includes(now.content_type);
        body = [
          now.title && now.title !== r.station ? `<div class="now" title="${esc(now.file)}">${esc(now.title)}</div>` : "",
          r.external ? `<div class="time">Live from ${esc(r.external.source)}</div>` : "",
          filler ? `<div class="file"><span class="kind">${esc(now.content_type === "bump" ? "mid card" : now.content_type)}</span> ${esc(now.file.replace(/\.\w+$/, ""))}</div>` : "",
          now.duration ? `<div class="bar"><span style="width:${pct.toFixed(1)}%"></span></div>
           <div class="time">${fmtClock(now.elapsed)} / ${fmtClock(now.duration)}</div>` : "",
        ].join("");
      }
      return `<a class="card-chan${r.on_air ? "" : " off"}" href="/watch.html?ch=${n}" title="Watch channel ${n}">
        <div class="thumb">${thumb}</div>
        <div class="meta">
          <div class="head"><span class="num">${n}</span><span class="name">${esc(r.station)}</span>${badges}</div>
          ${body}
        </div>
      </a>`;
    }).join("");

    channelsEl.querySelectorAll(".thumb-img").forEach((img) => {
      const kept = loaded.get(img.getAttribute("src"));
      if (kept) return img.replaceWith(kept);                 // the same frame as last time: keep the picture, no flash to black
      img.addEventListener("error", () => {
        const off = document.createElement("div");
        off.className = "thumb-off";
        off.textContent = "no preview";
        img.replaceWith(off);
      });
    });
  }

  async function refresh() {
    try {
      const [sys, chans] = await Promise.all([get("/system.json"), get("/channels.json")]);
      renderStats(sys);
      renderChannels(chans);
      statusEl.textContent = `Updated ${new Date().toLocaleTimeString()}`;
      statusEl.classList.remove("error");
    } catch (e) {
      statusEl.textContent = "Lost contact with fs42-tuner, retrying";
      statusEl.classList.add("error");
    }
  }

  // Library: the content folder by tag. Read once, then every few minutes, since
  // it only changes when the generator or you add links. Open tags stay open.
  const libEl = document.getElementById("library");
  const libSummaryEl = document.getElementById("lib-summary");
  const libOpen = new Set();

  function renderLibrary(lib) {
    if (!lib.found) {
      libSummaryEl.textContent = "";
      libSummaryEl.classList.remove("warn");
      libEl.innerHTML = `<p class="lib-empty">No content folder at ${esc(lib.root)}. Run the channel generator, or put videos in tag folders there.</p>`;
      return;
    }
    const t = lib.totals;
    const warns = [];
    if (t.dead) warns.push(`${t.dead} dead link${t.dead === 1 ? "" : "s"}`);
    if (t.duplicates) warns.push(`${t.duplicates} duplicate${t.duplicates === 1 ? "" : "s"}`);
    libSummaryEl.textContent = `${t.videos.toLocaleString()} videos in ${lib.tags.length} lists` + (warns.length ? ` \u2014 ${warns.join(", ")}` : "");
    libSummaryEl.classList.toggle("warn", warns.length > 0);
    libEl.innerHTML = lib.tags.map((tag) => {
      const badges = [
        tag.dead ? `<span class="badge warn" title="Links whose file is gone, as seen from this container">${tag.dead} dead</span>` : "",
        tag.duplicates ? `<span class="badge warn" title="The same file linked more than once in this tag; FieldStation42 would schedule it twice">${tag.duplicates} duplicate</span>` : "",
      ].join("");
      const items = tag.sources.map((s) => `<li><span>${esc(s.name)}</span><span>${s.videos}</span></li>`).join("");
      return `<details class="lib-tag" data-tag="${esc(tag.tag)}"${libOpen.has(tag.tag) ? " open" : ""}>
        <summary><span class="lib-name">${esc(tag.tag)}</span><span class="lib-count">${tag.videos} videos</span>${badges}</summary>
        <ul>${items || '<li class="lib-empty">empty</li>'}</ul>
      </details>`;
    }).join("") || '<p class="lib-empty">The content folder is empty.</p>';
    libEl.querySelectorAll("details").forEach((d) => d.addEventListener("toggle", () => {
      if (d.open) libOpen.add(d.dataset.tag); else libOpen.delete(d.dataset.tag);
    }));
    filterLibrary();
  }

  const libFilterEl = document.getElementById("lib-filter");
  function filterLibrary() {
    const q = libFilterEl.value.trim().toLowerCase();
    libEl.querySelectorAll(".lib-tag").forEach((d) => { d.hidden = !!q && !d.dataset.tag.toLowerCase().includes(q); });
  }
  libFilterEl.addEventListener("input", filterLibrary);

  async function loadLibrary(rescan) {
    try {
      const data = await get(rescan ? "/library.json?refresh" : "/library.json");
      if (data.never) {                                       // the server has not finished its first scan yet
        libSummaryEl.textContent = "Waiting for the first scan of your lists…";
        setTimeout(() => loadLibrary(false), 10000);
        return;
      }
      renderLibrary(data);
      if (data.scanning) setTimeout(() => loadLibrary(false), 5000);   // a rescan you asked for is running
    } catch (e) {
      libSummaryEl.textContent = "Library unavailable";
      libSummaryEl.classList.add("warn");
    }
  }
  document.getElementById("lib-rescan").addEventListener("click", () => loadLibrary(true));

  // ---- getting started: what is done and what is next, until the first channel is on air
  const setupEl = document.getElementById("setup");
  async function loadSetup() {
    if (setupEl.dataset.busy === "1") return;               // a channel is being made: leave its progress on screen
    let dismissed = false;
    try { dismissed = localStorage.getItem("setup-dismissed") === "1"; } catch (e) { /* not remembered */ }
    try {
      const [sys, lib, stations] = await Promise.all([
        get("/api/system/status"), get("/library.json"), get("/api/stations"),
      ]);
      const rows = stations.stations || stations.rows || stations || [];
      const list = Array.isArray(rows) ? rows : [];
      const real = list.filter((s) => s.type !== "guide");
      const hasLists = (lib.tags || []).some((t) => t.videos > 0 && !["bump", "commercials"].includes(t.tag));
      const steps = [
        { done: !!(sys.media && sys.media.present), text: "Your media folder has videos in it.", href: "/files.html", go: "Lists & files" },
        { done: hasLists, text: "You have a list with videos in it (or a series, season or folder you can pick directly).", href: "/files.html", go: "Lists & files" },
        { done: real.length > 0, text: "You have a station.", href: "/station.html", go: "New station" },
        { done: real.some((s) => s.on_air), text: "A station is built and on air (Save and build on the station's page).", href: "/stations.html", go: "Stations" },
        { done: null, text: `Add it to Jellyfin or another IPTV app: a tuner of type HDHomeRun at ${location.host} and an XMLTV guide at http://${location.host}/xmltv.xml. The Status page checks everything else.`, href: "/status.html", go: "Status" },
      ];
      const complete = steps.slice(0, 4).every((s) => s.done);
      setupEl.hidden = complete || dismissed;
      if (setupEl.hidden) return;
      const next = steps.findIndex((s) => s.done === false);
      setupEl.replaceChildren();
      const head = document.createElement("div");
      head.className = "view-head";
      head.innerHTML = "<h2>Getting started</h2>";
      const hide = document.createElement("button");
      hide.type = "button";
      hide.className = "btn";
      hide.textContent = "Hide";
      hide.addEventListener("click", () => { try { localStorage.setItem("setup-dismissed", "1"); } catch (e) { /* not remembered */ } setupEl.hidden = true; });
      head.append(hide);
      setupEl.append(head);
      steps.forEach((s, i) => {
        const p = document.createElement("p");
        p.className = "state " + (s.done ? "ok" : i === next ? "" : "dim");
        p.textContent = `${s.done ? "\u2714" : i === next ? "\u25B6" : "\u25CB"} ${s.text} `;
        if (!s.done && (i === next || s.done === null)) {
          const a = document.createElement("a");
          a.className = "btn" + (i === next ? " primary" : "");
          a.href = s.href;
          a.textContent = s.go;
          p.append(a);
        }
        setupEl.append(p);
      });
      if (!steps[2].done) {                                   // no station yet: a way to get one without choosing anything
        const qs = W.quickStart();                          // its "on air: Watch it" message stays until the page is reloaded
        qs.button.addEventListener("click", () => { setupEl.dataset.busy = "1"; });
        const row = document.createElement("p");
        row.append(qs.button, " ", qs.note);
        setupEl.append(row);
      }
    } catch (e) {
      setupEl.hidden = true;
    }
  }
  loadSetup();
  setInterval(loadSetup, 30 * 1000);

  refresh();
  setInterval(refresh, REFRESH_MS);
  loadLibrary(false);
  setInterval(() => loadLibrary(false), 5 * 60 * 1000);
})();
