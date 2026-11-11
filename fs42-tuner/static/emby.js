// The Emby panel on the Sources page: sign in with Emby Connect, choose servers and libraries (emby.py, /api/emby/*).
// Chosen libraries show up on the Files page under Emby/<server>/<library>, to be put in lists like any media.
(function () {
  "use strict";
  const { el, call, fmtWhen } = W;
  const box = document.getElementById("emby");
  const libs = {};                       // server id -> [{id, name, kind}] once looked up
  let data = null;

  function say(text, kind) {
    const m = document.getElementById("emby-msg");
    if (m) { m.textContent = text || ""; m.className = "msg" + (kind ? " " + kind : ""); }
  }
  const run = (fn) => fn().catch((e) => say(e.message, "err"));

  async function load() {
    data = await call("/api/emby/status");
    render();
  }

  function render() {
    box.replaceChildren(el("h2", { textContent: "Emby servers" }),
      el("p", { className: "dim", textContent: "Sign in with Emby Connect, then tick the servers and libraries to use. Their shows and movies appear on the Files page under Emby/<server>/<library>: put them in lists and on channels like your own media. Nothing is read from a server until a channel plays one of its videos." }),
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
          render();
          say(`Signed in: ${data.servers.length} server(s) on the account.`, "ok");
        });
      });
      box.append(form, el("p", { className: "dim", textContent: "The password is only passed on to Emby Connect; it is never saved." }));
      return;
    }
    const st = data.status || {};
    const c = st.counts || {};
    box.append(el("p", { className: "dim" }, `Signed in as ${data.account}. `,
      st.syncing ? "Reading the servers now…" : st.last ? `Last read ${fmtWhen(st.last * 1000)}: ${c.made || 0} new, ${c.kept || 0} unchanged, ${c.removed || 0} removed.` : "Not read yet."),
      st.error ? el("p", { className: "state err", textContent: st.error }) : "",
      el("div", { className: "row" },
        el("button", { type: "button", className: "btn primary", textContent: "Read the servers now", disabled: !data.edit || st.syncing,
          onclick: () => run(async () => { await call("/api/emby/sync", {}); say("Reading them in the background: new shows appear on the Files page as they are found.", "ok"); setTimeout(() => run(load), 3000); }) }),
        el("button", { type: "button", className: "btn", textContent: "Look for servers again", disabled: !data.edit,
          onclick: () => run(async () => { data = await call("/api/emby/servers", {}); render(); }) }),
        el("button", { type: "button", className: "btn", textContent: "Sign out", disabled: !data.edit,
          onclick: () => run(async () => { data = await call("/api/emby/signout", {}); render(); }) })));
    if (!data.servers.length) box.append(el("p", { className: "dim", textContent: "No servers on this account." }));
    for (const s of data.servers) box.append(server(s));
  }

  function server(s) {
    const c = el("div", { className: "source" + (s.on ? "" : " off") });
    const on = el("input", { type: "checkbox", checked: s.on, disabled: !data.edit || s.gone });
    on.addEventListener("change", () => run(async () => { data = await call("/api/emby/choose", { id: s.id, on: on.checked }); render(); }));
    c.append(el("h2", {}, el("label", {}, on, " ", el("span", { textContent: s.name })),
      el("span", { className: "kind", textContent: s.remote === true ? "over the internet" : s.remote === false ? "on the LAN" : "not reached yet" }),
      s.gone ? el("span", { className: "kind", textContent: "no longer on the account" }) : ""));
    if (s.error) c.append(el("p", { className: "state err", textContent: s.error }));
    const cap = el("input", { type: "number", min: 0, max: 100000, step: 500, value: s.cap_kbps ?? 6000, disabled: !data.edit, className: "num" });
    cap.addEventListener("change", () => run(async () => { data = await call("/api/emby/choose", { id: s.id, cap_kbps: Number(cap.value) }); say("Saved.", "ok"); }));
    c.append(el("p", { className: "dim" }, "Over the internet, ask this server to make ", cap,
      " kbps (0 = the original file; uses the server's CPU). On the LAN the original file is always read."));
    const list = el("div", { className: "row" });
    const pick = el("button", { type: "button", className: "btn", textContent: libs[s.id] ? "Hide libraries" : "Choose libraries" + (s.libraries.length ? ` (${s.libraries.length} chosen)` : ""), disabled: s.gone });
    pick.addEventListener("click", () => run(async () => {
      if (libs[s.id]) { delete libs[s.id]; render(); return; }
      pick.textContent = "Asking the server…";
      libs[s.id] = (await call("/api/emby/libraries", { id: s.id })).libraries;
      render();
    }));
    c.append(el("div", { className: "row" }, pick), list);
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
    if (document.visibilityState === "visible" && !typing && data && data.signed_in) load().catch(() => {});
  }, 15000);
})();
