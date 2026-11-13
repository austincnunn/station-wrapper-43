// Shared by every page: the navigation bar, messages (toasts), the confirm / ask dialog, progress bars, and the
// fetch helper. Pages are Alpine.js components styled with Bulma; both are served from /vendor (no CDN).
// Names and titles come from your disk and from FieldStation42, so they are only ever put on a page as text
// (x-text, never x-html).
(function () {
  "use strict";

  const LINKS = [
    ["dashboard", "Dashboard", "/"],
    ["stations", "Stations", "/stations.html"],
    ["watch", "Watch", "/watch.html"],
    ["settings", "Settings", "/settings.html"],
  ];

  async function call(path, body) {
    const opts = body === undefined ? {} : {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    };
    let res, data;
    // The dashboard restarts for a few seconds when a station is added or removed. Looking things up (GET) is
    // safe to repeat, so wait it out instead of showing an error; a change (POST) is never repeated blindly.
    const tries = body === undefined ? 8 : 1;
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
    if (res.status === 401) {                      // not logged in (or the session ended): go and log in, then come back
      location.assign("/login.html?next=" + encodeURIComponent(location.pathname + location.search + location.hash));
      throw new Error("you need to log in");
    }
    if (!res.ok) throw new Error(data.error || `that failed (${res.status})`);
    return data;
  }

  function fmtWhen(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    return d.toLocaleString([], { weekday: "short", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  }
  function fmtTime(iso) {
    return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }
  const hourLabel = (h) => `${String(h % 24).padStart(2, "0")}:00`;
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  // ---- messages. An error stays until it is dismissed or replaced; anything else goes away by itself.
  const toast = {
    items: [],
    seq: 0,
    say(text, kind) {
      this.items = this.items.filter((t) => t.kind !== kind);       // one of each kind: the newest replaces the last
      if (!text) return;
      const id = ++this.seq;
      this.items.push({ id, text: String(text), kind: kind || "" });
      if (kind !== "err") setTimeout(() => this.drop(id), 9000);
    },
    ok(text) { this.say(text, "ok"); },
    err(text) { this.say(text, "err"); },
    info(text) { this.say(text, ""); },
    drop(id) { this.items = this.items.filter((t) => t.id !== id); },
    clear() { this.items = []; },
  };
  const store = (name) => (window.Alpine ? window.Alpine.store(name) : null);
  const say = (text, kind) => { const t = store("toast"); if (t) t.say(text, kind); };
  // Runs something that may fail and shows why. Resolves to undefined when it failed.
  const run = (fn) => Promise.resolve().then(fn).catch((e) => say(e.message, "err"));

  // ---- one dialog for "are you sure?" and "what name?", instead of the browser's own boxes
  const dialog = {
    open: false, text: "", ok: "OK", danger: false, asks: false, value: "", _done: null,
    _show(o) {
      Object.assign(this, { open: true, text: o.text, ok: o.ok || "OK", danger: !!o.danger, asks: !!o.asks, value: o.value || "" });
      return new Promise((r) => { this._done = r; });
    },
    confirm(text, o) { return this._show({ ...(o || {}), text }); },                 // -> true / false
    prompt(text, value, o) { return this._show({ ...(o || {}), text, value, asks: true }); },   // -> the text, or null
    close(yes) {
      this.open = false;
      const done = this._done;
      this._done = null;
      if (done) done(this.asks ? (yes ? this.value.trim() : null) : !!yes);
    },
  };
  const confirmBox = (text, o) => store("dialog").confirm(text, o);
  const promptBox = (text, value, o) => store("dialog").prompt(text, value, o);

  // ---- progress. A job is whatever the server says about something slow: {percent} or {done, total}, a message,
  // maybe a detail line. No number means "working, no count to show" (a moving bar).
  function pct(job) {
    if (!job) return null;
    if (typeof job.percent === "number") return Math.max(0, Math.min(100, job.percent));
    if (job.total > 0 && typeof job.done === "number") return Math.max(0, Math.min(100, Math.round((job.done * 100) / job.total)));
    return null;
  }

  // Follows a station build until it ends. onUpdate(job) runs on every look. Returns the last job seen.
  async function followJob(id, onUpdate) {
    let job = null;
    for (let i = 0; i < 2400; i++) {
      await sleep(1500);
      job = await call(`/api/stations/job?id=${encodeURIComponent(id)}`);
      if (onUpdate) onUpdate(job);
      if (job.state !== "running") break;
    }
    return job;
  }

  // ---- the bar, the messages and the dialog: written once here, because there is no template engine.
  // Static markup only; nothing from the server goes through innerHTML.
  const NAV = `
<nav class="navbar" aria-label="Sections" x-data="shellNav">
  <div class="navbar-brand">
    <a class="navbar-item brand" href="/">Station Wrapper 43</a>
    <button type="button" class="navbar-burger" :class="open && 'is-active'" @click="open = !open" aria-label="Menu" :aria-expanded="open">
      <span aria-hidden="true"></span><span aria-hidden="true"></span><span aria-hidden="true"></span><span aria-hidden="true"></span>
    </button>
  </div>
  <div class="navbar-menu" :class="open && 'is-active'">
    <div class="navbar-start">
      <template x-for="l in links" :key="l[0]">
        <a class="navbar-item" :href="l[2]" x-text="l[1]" :class="l[0] === active && 'is-active'" :aria-current="l[0] === active ? 'page' : null"></a>
      </template>
    </div>
    <div class="navbar-end">
      <a class="navbar-item has-text-warning" href="/login.html" x-show="auth.login && auth.setup_needed" x-cloak>⚠ No password set: set one</a>
      <a class="navbar-item" href="#" x-show="auth.login && !auth.setup_needed && auth.authenticated" x-cloak @click.prevent="logout()">Log out</a>
      <a class="navbar-item" :href="loginHref" x-show="auth.login && !auth.setup_needed && !auth.authenticated" x-cloak>Log in</a>
      <a class="navbar-item adv" :href="consoleHref" target="_blank" rel="noopener"
         title="FieldStation42's own console, for advanced use. No login, so it answers only on the server itself unless FS42_CONSOLE_BIND=0.0.0.0 is set in .env">FS42 console ↗</a>
    </div>
  </div>
</nav>`;
  const OVERLAYS = `
<div class="toasts" x-data role="status" aria-live="polite">
  <template x-for="t in $store.toast.items" :key="t.id">
    <div class="notification" :class="t.kind === 'err' ? 'is-danger' : t.kind === 'ok' ? 'is-primary' : 'is-dark'">
      <button type="button" class="delete" aria-label="Dismiss" @click="$store.toast.drop(t.id)"></button>
      <span x-text="t.text"></span>
    </div>
  </template>
</div>
<div class="modal" x-data :class="$store.dialog.open && 'is-active'" role="dialog" aria-modal="true" aria-labelledby="dialog-text"
     @keydown.escape.window="$store.dialog.open && $store.dialog.close(false)">
  <div class="modal-background" @click="$store.dialog.close(false)"></div>
  <form class="modal-content box" @submit.prevent="$store.dialog.close(true)">
    <p id="dialog-text" class="block" x-text="$store.dialog.text"></p>
    <div class="field" x-show="$store.dialog.asks">
      <input class="input" type="text" aria-labelledby="dialog-text" x-model="$store.dialog.value"
             x-effect="$store.dialog.open && $store.dialog.asks && $nextTick(() => { $el.focus(); $el.select(); })">
    </div>
    <div class="buttons is-right">
      <button type="button" class="button" @click="$store.dialog.close(false)">Cancel</button>
      <button type="submit" class="button" :class="$store.dialog.danger ? 'is-danger' : 'is-primary'" x-text="$store.dialog.ok"
              x-effect="$store.dialog.open && !$store.dialog.asks && $nextTick(() => $el.focus())"></button>
    </div>
  </form>
</div>`;

  const shellEl = document.getElementById("shell");
  if (shellEl) {
    const active = shellEl.dataset.page || "";
    shellEl.innerHTML = (active ? NAV : "") + OVERLAYS;
    shellEl.dataset.active = active;
  }

  document.addEventListener("alpine:init", () => {
    const Alpine = window.Alpine;
    Alpine.store("toast", toast);
    Alpine.store("dialog", dialog);

    Alpine.data("shellNav", () => ({
      open: false,
      links: LINKS,
      active: shellEl ? shellEl.dataset.active : "",
      auth: {},
      consoleHref: `${location.protocol}//${location.hostname}:4242/`,
      loginHref: "/login.html?next=" + encodeURIComponent(location.pathname + location.search),
      async init() {
        try { this.auth = await (await fetch("/api/auth/status")).json(); } catch (e) { /* the bar still works without it */ }
      },
      async logout() {
        await fetch("/api/auth/logout", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
        location.assign("/login.html");
      },
    }));

    // <div x-progress="job"></div>: a bar with the job's message under it; nothing while the job is empty.
    Alpine.directive("progress", (el, { expression }, { evaluateLater, effect }) => {
      const read = evaluateLater(expression);
      const bar = document.createElement("progress");
      bar.className = "progress is-primary is-small";
      bar.max = 100;
      const text = document.createElement("p");
      text.className = "help";
      const detail = document.createElement("p");
      detail.className = "help has-text-grey";
      el.classList.add("job-progress");
      el.setAttribute("role", "status");
      el.append(bar, text, detail);
      effect(() => read((job) => {
        el.hidden = !job;
        if (!job) return;
        const p = pct(job);
        if (p == null) bar.removeAttribute("value"); else bar.value = p;
        bar.setAttribute("aria-label", job.message || "Working");
        text.textContent = (p == null ? "" : `${p}% · `) + (job.message || "Working…");
        detail.textContent = job.detail || "";
        detail.hidden = !job.detail;
      }));
    });
  });

  // One click: a working channel from what there is (the biggest list, or the first series in your media), built
  // for a week. An Alpine component: <div x-data="quickStart" @made="..."> with a button calling go().
  document.addEventListener("alpine:init", () => {
    window.Alpine.data("quickStart", () => ({
      busy: false, note: "", job: null, made: null,
      async go() {
        this.busy = true;
        this.made = null;
        this.note = "Making a channel…";
        try {
          const made = await call("/api/stations/quickstart", {});
          this.note = `Making “${made.name}” (channel ${made.number}) from ${made.describe}, and building a week of it…`;
          this.job = made.job;
          const job = made.job ? await followJob(made.job.id, (j) => { this.job = j; }) : null;
          this.job = null;
          if (job && job.state === "error") throw new Error(job.message);
          this.note = `“${made.name}” is on air as channel ${made.number}.`;
          this.made = made;
          this.$dispatch("made", made);
        } catch (e) {
          this.job = null;
          this.note = e.message;
          this.busy = false;
        }
      },
    }));
  });

  window.W = { call, fmtWhen, fmtTime, hourLabel, sleep, say, run, confirm: confirmBox, prompt: promptBox, pct, followJob };
})();
