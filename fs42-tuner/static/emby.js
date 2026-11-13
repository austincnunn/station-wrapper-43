// The Emby and Jellyfin panel on the Sources page: sign in with Emby Connect or add an Emby or Jellyfin server by its address,
// and that is all: an Emby Connect account with several servers is asked which to use, then each server's libraries of shows,
// movies and music videos are chosen and read at once, and each becomes a list ("Server - Library") on the Lists & files page
// (emby.py, /api/emby/*). The ticks are for leaving some out.
(function () {
  "use strict";
  const { el, call, fmtWhen } = W;
  const box = document.getElementById("emby");
  const libs = {};                       // server id -> [{id, name, kind}] once looked up
  let data = null;
  let ask = null;                        // the "which servers?" step: { servers: the account's new ones, want: Set of ticked ids }

  function say(text, kind) {
    const m = document.getElementById("emby-msg");
    if (m) { m.textContent = text || ""; m.className = "msg" + (kind ? " " + kind : ""); }
  }
  const run = (fn) => fn().catch((e) => say(e.message, "err"));

  async function load() {
    data = await call("/api/emby/status");
    render();
  }

  // After a sign-in or a new look at the account: ask which of its new servers to use (one is not a question), then read.
  function offer() {
    const fresh = data.servers.filter((s) => s.auto && !s.on && !s.gone && !s.direct);
    if (fresh.length < 2) return use(fresh.map((s) => s.id));
    ask = { servers: fresh, want: new Set(fresh.map((s) => s.id)) };
    render();
    say(`Signed in: ${fresh.length} new servers on the account. Tick the ones to use.`, "ok");
  }

  async function use(ids) {
    ask = null;
    for (const id of ids) data = await call("/api/emby/choose", { id, on: true });
    const any = data.servers.some((s) => s.on && !s.gone);
    if (any) await call("/api/emby/sync", {}).catch(() => {});     // ponytail: a read already running misses a server switched on just now; it is read at the next one
    await load();
    say(any ? "Reading the servers' libraries now: a list for each appears on the Lists & files page." : "No server is switched on: tick one below to use it.", any ? "ok" : "");
    setTimeout(() => run(load), 3000);
  }

  function asking() {
    const c = el("div", { className: "source" }, el("h2", { textContent: "Which servers do you want to use?" }),
      el("p", { className: "dim", textContent: "Each server you tick is read now, and its libraries of shows, movies and music videos become lists. The first read of a big server far away can take a quarter of an hour. You can switch a server on or off below at any time." }));
    const row = el("div", { className: "row" });
    for (const s of ask.servers) {
      const t = el("input", { type: "checkbox", checked: ask.want.has(s.id) });
      t.addEventListener("change", () => { if (t.checked) ask.want.add(s.id); else ask.want.delete(s.id); });
      row.append(el("label", { className: "kind" }, t, ` ${s.name}`));
    }
    c.append(row, el("div", { className: "row" },
      el("button", { type: "button", className: "btn primary", textContent: "Use these servers", onclick: () => run(() => use([...ask.want])) }),
      el("button", { type: "button", className: "btn", textContent: "None for now", onclick: () => { ask = null; render(); } })));
    return c;
  }

  function render() {
    box.replaceChildren(el("h2", { textContent: "Emby and Jellyfin servers" }),
      el("p", { className: "dim", textContent: "Sign in with Emby Connect and say which of your servers to use, or add an Emby or Jellyfin server by its address. Each server's libraries of shows, movies and music videos are then read, and each becomes a list (“Server - Library”) on the Lists & files page, ready to put on a channel and kept up to date. Untick a server or a library to leave it out. No video is read from a server until a channel plays it." }),
      el("p", { id: "emby-msg", className: "msg", role: "status" }));
    if (!data.signed_in) {
      const name = el("input", { type: "text", autocomplete: "username", placeholder: "Emby Connect name or email", disabled: !data.edit });
      const pw = el("input", { type: "password", autocomplete: "current-password", placeholder: "password", disabled: !data.edit });
      const form = el("form", { className: "row" }, name, pw,
        el("button", { type: "submit", className: "btn primary", textContent: "Sign in", disabled: !data.edit }));
      form.addEventListener("submit", (ev) => {
        ev.preventDefault();
        run(async () => {
          say("Signing in…");
          data = await call("/api/emby/signin", { name: name.value, password: pw.value });
          pw.value = "";
          await offer();
        });
      });
      box.append(form, el("p", { className: "dim", textContent: "The password is only passed on to Emby Connect; it is never saved." }));
    }
    if (ask) box.append(asking());
    box.append(addForm());
    const st = data.status || {};
    const c = st.counts || {};
    box.append(el("p", { className: "dim" }, data.signed_in ? `Signed in to Emby Connect as ${data.account}. ` : "",
      st.syncing ? "Reading the servers now…" : st.last ? `Last read ${fmtWhen(st.last * 1000)}: ${c.made || 0} new, ${c.kept || 0} unchanged, ${c.removed || 0} removed${c.lists ? `, ${c.lists} list(s) made` : ""}.` : "Not read yet."),
      st.error ? el("p", { className: "state err", textContent: st.error }) : "",
      el("div", { className: "row" },
        el("button", { type: "button", className: "btn primary", textContent: "Read the servers now", disabled: !data.edit || st.syncing,
          onclick: () => run(async () => { await call("/api/emby/sync", {}); say("Reading them in the background: new shows appear on the Files page as they are found.", "ok"); setTimeout(() => run(load), 3000); }) }),
        data.signed_in ? el("button", { type: "button", className: "btn", textContent: "Look for Emby servers again", disabled: !data.edit,
          onclick: () => run(async () => { data = await call("/api/emby/servers", {}); await offer(); }) }) : "",
        data.signed_in ? el("button", { type: "button", className: "btn", textContent: "Sign out of Emby Connect", disabled: !data.edit,
          onclick: () => run(async () => { data = await call("/api/emby/signout", {}); render(); }) }) : ""));
    if (!data.servers.length) box.append(el("p", { className: "dim", textContent: "No servers yet." }));
    for (const s of data.servers) box.append(server(s));
  }

  function addForm() {
    const kind = el("select", { disabled: !data.edit, ariaLabel: "Kind of server" },
      el("option", { value: "emby", textContent: "Emby" }), el("option", { value: "jellyfin", textContent: "Jellyfin" }));
    const url = el("input", { type: "text", placeholder: "address, like http://192.168.1.20:8096", disabled: !data.edit });
    const name = el("input", { type: "text", autocomplete: "off", placeholder: "user name on that server", disabled: !data.edit });
    const pw = el("input", { type: "password", autocomplete: "off", placeholder: "password", disabled: !data.edit });
    const form = el("form", { className: "row" }, kind, url, name, pw,
      el("button", { type: "submit", className: "btn", textContent: "Add a server by its address", disabled: !data.edit }));
    form.addEventListener("submit", (ev) => {
      ev.preventDefault();
      run(async () => {
        say(`Signing in to ${kind.value === "jellyfin" ? "Jellyfin" : "Emby"}…`);
        data = await call("/api/emby/add", { kind: kind.value, url: url.value, name: name.value, password: pw.value });
        pw.value = "";
        render();
        say("Added. Reading its libraries now: a list for each appears on the Lists & files page. The password was passed on once and not saved.", "ok");
        setTimeout(() => run(load), 3000);
      });
    });
    return form;
  }

  function server(s) {
    const jf = s.direct;                   // added by its address: its own sign-in, its cap always counts, removable
    const c = el("div", { className: "source" + (s.on ? "" : " off") });
    const on = el("input", { type: "checkbox", checked: s.on, disabled: !data.edit || s.gone });
    on.addEventListener("change", () => run(async () => {
      if (on.checked && s.auto) return use([s.id]);        // never read: switching it on is asking for it
      data = await call("/api/emby/choose", { id: s.id, on: on.checked });
      render();
    }));
    c.append(el("h2", {}, el("label", {}, on, " ", el("span", { textContent: s.name })),
      el("span", { className: "kind", textContent: jf ? (s.kind === "jellyfin" ? "Jellyfin" : "Emby, by address") : s.remote === true ? "over the internet" : s.remote === false ? "on the LAN" : "not reached yet" }),
      s.gone ? el("span", { className: "kind", textContent: "no longer on the account" }) : ""));
    if (s.error) c.append(el("p", { className: "state err", textContent: s.error }));
    const cap = el("input", { type: "number", min: 0, max: 100000, step: 500, value: s.cap_kbps ?? 6000, disabled: !data.edit, className: "num" });
    cap.addEventListener("change", () => run(async () => { data = await call("/api/emby/choose", { id: s.id, cap_kbps: Number(cap.value) }); say("Saved.", "ok"); }));
    c.append(jf
      ? el("p", { className: "dim" }, "Ask this server to make ", cap, " kbps (0 = the original file; anything else uses the server's CPU, for a server far away).")
      : el("p", { className: "dim" }, "Over the internet, ask this server to make ", cap,
        " kbps (0 = the original file; uses the server's CPU). On the LAN the original file is always read."));
    const list = el("div", { className: "row" });
    const pick = el("button", { type: "button", className: "btn", textContent: libs[s.id] ? "Hide libraries" : "Choose libraries" + (s.auto ? " (chosen for you at the first read)" : s.libraries.length ? ` (${s.libraries.length} chosen)` : ""), disabled: s.gone });
    pick.addEventListener("click", () => run(async () => {
      if (libs[s.id]) { delete libs[s.id]; render(); return; }
      pick.textContent = "Asking the server…";
      libs[s.id] = (await call("/api/emby/libraries", { id: s.id })).libraries;
      await load();                        // looking them up is what chooses a new server's libraries
    }));
    c.append(el("div", { className: "row" }, pick, jf ? el("button", { type: "button", className: "btn", textContent: "Remove", disabled: !data.edit,
      onclick: () => run(async () => { data = await call("/api/emby/remove", { id: s.id }); render(); say("Removed. Its videos leave the Files page at the next read.", "ok"); }) }) : ""), list);
    if (libs[s.id]) {
      for (const lib of libs[s.id]) {
        const box2 = el("input", { type: "checkbox", checked: s.libraries.includes(lib.id), disabled: !data.edit });
        box2.addEventListener("change", () => run(async () => {
          const want = libs[s.id].filter((l) => l.id === lib.id ? box2.checked : s.libraries.includes(l.id)).map((l) => l.id);
          data = await call("/api/emby/choose", { id: s.id, libraries: want });
          render();
          say("Saved. Press “Read the servers now” to fetch them.", "ok");
        }));
        list.append(el("label", { className: "kind" }, box2, ` ${lib.name} (${lib.kind})`));
      }
    }
    return c;
  }

  run(load);
  setInterval(() => {
    const typing = document.activeElement && document.activeElement.closest && document.activeElement.closest("#emby");
    if (document.visibilityState === "visible" && !typing && data && (data.signed_in || data.servers.length)) load().catch(() => {});
  }, 15000);
})();
