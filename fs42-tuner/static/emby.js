// The Emby and Jellyfin panel on the Sources tab: sign in with Emby Connect or add an Emby or Jellyfin server by its address,
// and that is all: an Emby Connect account with several servers is asked which to use, then each server's libraries of shows,
// movies and music videos are chosen and read at once, and each becomes a list ("Server - Library") on the Lists & files tab
// (emby.py, /api/emby/*). The ticks are for leaving some out.
(function () {
  "use strict";
  const { call, fmtWhen, say, run } = W;

  document.addEventListener("alpine:init", () => {
    Alpine.data("embyPanel", () => ({
      data: null,
      libs: {},                          // server id -> [{id, name, kind}] once looked up
      ask: null,                         // the "which servers?" step: { servers: the account's new ones }
      want: [],                          // ... and the ids ticked in it
      connect: { name: "", password: "" },
      direct: { kind: "emby", url: "", name: "", password: "" },
      busy: "",
      looked: 0,

      init() {
        run(() => this.load());
        setInterval(() => {
          if (!this.data || !W.onTab("sources")) return;
          const a = document.activeElement;
          const typing = a && this.$root.contains(a) && /^(INPUT|SELECT|TEXTAREA)$/.test(a.tagName);
          const every = this.status.syncing ? 3000 : 15000;                 // a read in progress is followed closely
          if (Date.now() - this.looked < every || (typing && !this.status.syncing)) return;
          if (this.status.syncing || this.data.signed_in || this.data.servers.length) this.load().catch(() => {});
        }, 3000);
      },

      async load() {
        this.data = await call("/api/emby/status");
        this.looked = Date.now();
      },

      get status() { return (this.data && this.data.status) || {}; },
      get summary() {
        const st = this.status, c = st.counts || {};
        return (this.data.signed_in ? `Signed in to Emby Connect as ${this.data.account}. ` : "") +
          (st.syncing ? "Reading the servers now…" : st.last ? `Last read ${fmtWhen(st.last * 1000)}: ${c.made || 0} new, ${c.kept || 0} unchanged, ${c.removed || 0} removed${c.lists ? `, ${c.lists} list(s) made` : ""}.` : "Not read yet.");
      },
      // What the bar shows while the servers are read: how many items so far, and of how many when the server said.
      get syncJob() {
        const st = this.status;
        return {
          message: st.library ? `Reading ${st.library}: ${st.read || 0}${st.total ? ` of ${st.total}` : ""} items` : "Reading the servers now…",
          done: st.total ? st.read || 0 : undefined, total: st.total || 0,
        };
      },
      where: (s) => (s.direct ? (s.kind === "jellyfin" ? "Jellyfin" : "Emby, by address")
        : s.remote === true ? "over the internet" : s.remote === false ? "on the LAN" : "not reached yet"),
      libsLabel(s) {
        if (this.libs[s.id]) return "Hide libraries";
        return "Choose libraries" + (s.auto ? " (chosen for you at the first read)" : s.libraries.length ? ` (${s.libraries.length} chosen)` : "");
      },
      tick(id, on) { this.want = on ? [...new Set([...this.want, id])] : this.want.filter((x) => x !== id); },

      // After a sign-in or a new look at the account: ask which of its new servers to use (one is not a question), then read.
      offer() {
        const fresh = this.data.servers.filter((s) => s.auto && !s.on && !s.gone && !s.direct);
        if (fresh.length < 2) return this.use(fresh.map((s) => s.id));
        this.ask = { servers: fresh };
        this.want = fresh.map((s) => s.id);
        say(`Signed in: ${fresh.length} new servers on the account. Tick the ones to use.`, "ok");
      },
      async use(ids) {
        this.ask = null;
        for (const id of ids) this.data = await call("/api/emby/choose", { id, on: true });
        const any = this.data.servers.some((s) => s.on && !s.gone);
        if (any) await call("/api/emby/sync", {}).catch(() => {});     // ponytail: a read already running misses a server switched on just now; it is read at the next one
        await this.load();
        say(any ? "Reading the servers' libraries now: a list for each appears on the Lists & files tab." : "No server is switched on: tick one below to use it.", any ? "ok" : "");
      },

      signin() {
        return run(async () => {
          this.busy = "signin";
          try {
            this.data = await call("/api/emby/signin", { name: this.connect.name, password: this.connect.password });
            this.connect.password = "";
            await this.offer();
          } finally {
            this.busy = "";
          }
        });
      },
      add() {
        return run(async () => {
          this.busy = "add";
          try {
            this.data = await call("/api/emby/add", this.direct);
            this.direct.password = "";
            say("Added. Reading its libraries now: a list for each appears on the Lists & files tab. The password was passed on once and not saved.", "ok");
            await W.sleep(1000);
            await this.load();
          } finally {
            this.busy = "";
          }
        });
      },
      sync() {
        return run(async () => {
          await call("/api/emby/sync", {});
          say("Reading them in the background: new shows appear on the Lists & files tab as they are found.", "ok");
          await W.sleep(1000);
          await this.load();
        });
      },
      lookAgain() { return run(async () => { this.data = await call("/api/emby/servers", {}); await this.offer(); }); },
      signout() { return run(async () => { this.data = await call("/api/emby/signout", {}); }); },

      switchServer(s, on) {
        return run(async () => {
          if (on && s.auto) return this.use([s.id]);        // never read: switching it on is asking for it
          this.data = await call("/api/emby/choose", { id: s.id, on });
        });
      },
      setCap(s, value) {
        return run(async () => { this.data = await call("/api/emby/choose", { id: s.id, cap_kbps: Number(value) }); say("Saved.", "ok"); });
      },
      pickLibraries(s) {
        return run(async () => {
          if (this.libs[s.id]) { delete this.libs[s.id]; return; }
          this.busy = "libs:" + s.id;
          try {
            this.libs[s.id] = (await call("/api/emby/libraries", { id: s.id })).libraries;
            await this.load();                        // looking them up is what chooses a new server's libraries
          } finally {
            this.busy = "";
          }
        });
      },
      chooseLibrary(s, lib, on) {
        return run(async () => {
          const want = this.libs[s.id].filter((l) => (l.id === lib.id ? on : s.libraries.includes(l.id))).map((l) => l.id);
          this.data = await call("/api/emby/choose", { id: s.id, libraries: want });
          say("Saved. Press “Read the servers now” to fetch them.", "ok");
        });
      },
      removeServer(s) {
        return run(async () => {
          if (!await W.confirm(`Remove “${s.name}”? Its videos leave the Lists & files tab at the next read.`, { ok: "Remove", danger: true })) return;
          this.data = await call("/api/emby/remove", { id: s.id });
          say("Removed. Its videos leave the Lists & files tab at the next read.", "ok");
        });
      },
    }));
  });
})();
