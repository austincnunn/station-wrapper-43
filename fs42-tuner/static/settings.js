// The Settings page: the compose file's settings that can be changed here (envsettings.py), for this server and for
// each player PC (client mode). Values are only ever put on the page as text.
(function () {
  "use strict";
  const { el, call } = W;
  W.nav("settings");
  const $ = (id) => document.getElementById(id);
  const say = (text, kind) => { $("msg").textContent = text || ""; $("msg").className = "msg" + (kind ? " " + kind : ""); };
  const SOURCE = { saved: "set here", env: "from the compose file", default: "built-in default" };
  const shown = (s, v) => (s.kind === "bool" ? (v === "0" ? "off" : "on") : v === "" || v == null ? "automatic" : v);

  // One setting: empty means "not set here" (the compose file's value, or the default, is used).
  function field(s, edit, note) {
    const id = "f-" + Math.random().toString(36).slice(2);
    const fallback = s.env != null && s.env !== "" ? `compose file: ${shown(s, s.env)}` : `default: ${shown(s, s.default)}`;
    const saved = s.source === "saved" ? s.value : "";
    let input;
    if (s.kind === "bool" || s.kind[0] === "choice") {
      input = el("select", { id, disabled: !edit });
      input.append(el("option", { value: "", textContent: `As the compose file (${fallback.replace(/^.*: /, "")})` }));
      const opts = s.kind === "bool" ? [["1", "On"], ["0", "Off"]] : s.kind[1].filter((c) => c).map((c) => [c, c]);
      for (const [v, t] of opts) input.append(el("option", { value: v, textContent: t }));
      input.value = saved;
    } else {
      input = el("input", { id, type: s.kind[0] === "text" ? "text" : "number", value: saved, placeholder: fallback, disabled: !edit });
      if (s.kind[0] !== "text") Object.assign(input, { min: s.kind[1], max: s.kind[2], step: s.kind[0] === "float" ? "0.05" : "1" });
    }
    input.dataset.key = s.key;
    const hint = `${SOURCE[s.source]}: ${shown(s, s.value)}` + (s.restarts.length ? ` · saving restarts ${s.restarts.join(", ")}` : "") +
      (note ? ` · ${note}` : "") + (s.note ? ` · ${s.note}` : "");
    return el("div", { className: "field" }, el("label", { htmlFor: id, textContent: s.label }), input,
      el("span", { className: "hint", textContent: hint }));
  }

  // The settings in groups, with a Save button that sends every box (empty = clear).
  function form(host, rows, edit, notes, save) {
    let group = null;
    for (const s of rows) {
      if (s.group !== group) host.append(el("h3", { textContent: (group = s.group) }));
      host.append(field(s, edit, notes && notes(s)));
    }
    if (!edit) return;
    const btn = el("button", { type: "button", className: "btn primary", textContent: "Save" });
    btn.addEventListener("click", async () => {
      const values = {};
      for (const i of host.querySelectorAll("[data-key]")) values[i.dataset.key] = i.value.trim();
      btn.disabled = true;
      try {
        render(await save(values));
        say("Saved. What uses it restarts in a few seconds (the dashboard too, for its own settings).", "ok");
      } catch (e) {
        say(e.message, "err");
      } finally {
        btn.disabled = false;
      }
    });
    host.append(el("div", { className: "form-actions" }, btn));
  }

  function render(r) {
    const m = r.machine;
    const yes = (b) => (b ? "set" : "not set");
    $("machine").replaceChildren(el("h2", { textContent: "This machine" }),
      el("table", { className: "chan-table" }, ...[
        ["Role", `${m.role} (FS42_ROLE in the compose file; a player PC runs the client compose file)`],
        ["Time zone", m.tz || "(the container's)"], ["Version", m.version || "?"],
        ["Login", m.login ? "on" : "OFF (DASHBOARD_LOGIN)"], ["Changes from the dashboard", m.edit ? "on" : "OFF (DASHBOARD_EDIT)"],
        ["Secrets (in .env only)", Object.entries(m.secrets).map(([k, v]) => `${k} ${yes(v)}`).join(", ")],
      ].map(([k, v]) => el("tr", {}, el("th", { textContent: k }), el("td", { textContent: v })))));
    if (!r.edit) say("Changing settings is switched off (DASHBOARD_EDIT=0): this page only shows them.");

    const srv = $("server");
    srv.replaceChildren(el("h2", { textContent: "This server" }));
    form(srv, r.settings, r.edit, null, (values) => call("/api/settings", { values }));

    const pl = $("players");
    pl.replaceChildren(el("h2", { textContent: "Players" }));
    if (!r.sync_on) {
      pl.append(el("p", { className: "dim", textContent: "No player PCs: client sync is off (set FS42_SYNC_TOKEN in this server's .env)." }));
      return;
    }
    if (!r.players.length) pl.append(el("p", { className: "dim", textContent: "No player has checked in in the last day." }));
    for (const p of r.players) {
      const box = el("div", { className: "block" }, el("h3", { textContent: `${p.name}${p.gone ? " (not seen for a while)" : ""}` }));
      const applied = p.applied || {};
      const waiting = (s) => (s.source === "saved" && applied[s.key] !== s.value ? "waiting for the player (next sync)" : "");
      form(box, p.settings, r.edit, waiting, (values) => call("/api/settings/player", { name: p.name, values }));
      pl.append(box);
    }
  }

  call("/api/settings").then(render).catch((e) => say(e.message, "err"));
})();
