// The Viewers tab of the Settings page: the web viewer's accounts (viewers.py, /api/viewers*). Who may log in on the
// viewer's port (VIEWER_PORT), and which channels each one gets.
(function () {
  "use strict";
  const { call, say, run } = W;
  const blank = () => ({ editing: false, name: "", password: "", all: true, channels: [], saving: false });

  document.addEventListener("alpine:init", () => {
    Alpine.data("viewersTab", () => ({
      data: null,                        // { port, edit, users: [{name, channels, summary}], channels: [{number, name}] }
      link: "",                          // the viewer's address, as reached from where this page was
      form: blank(),                     // a new viewer, or (editing) the one whose Edit was pressed

      init() {
        run(() => this.load());
      },
      async load() {
        this.show(await call("/api/viewers"));
      },
      // Each user's line is made here, as text: the page's rows hold data only (Alpine calls a function it finds).
      show(data) {
        const names = Object.fromEntries(data.channels.map((c) => [c.number, c.name]));
        data.users.forEach((u) => {
          u.summary = u.channels === null ? "Every channel"
            : u.channels.length ? u.channels.map((n) => (names[n] ? `${n} ${names[n]}` : n)).join(", ") : "No channels yet";
        });
        this.data = data;
        this.link = data.port ? `${location.protocol}//${location.hostname}:${data.port}/` : "";
      },

      editUser(u) {
        this.form = { ...blank(), editing: true, name: u.name, all: u.channels === null, channels: [...(u.channels || [])] };
        this.$refs.form.scrollIntoView({ behavior: "smooth", block: "nearest" });
      },
      cancel() {
        this.form = blank();
      },
      save() {
        return run(async () => {
          const f = this.form;
          f.saving = true;
          try {
            this.show(await call("/api/viewers/save", { name: f.name, password: f.password || null, channels: f.all ? null : f.channels }));
            this.form = blank();
            say(f.password && f.editing ? "Saved. They are logged out everywhere and log in with the new password." : "Saved.", "ok");
          } finally {
            f.saving = false;
          }
        });
      },
      async remove(u) {
        if (!await W.confirm(`Remove “${u.name}”? They are logged out and can no longer watch.`, { ok: "Remove", danger: true })) return;
        await run(async () => this.show(await call("/api/viewers/remove", { name: u.name })));
        if (this.form.name === u.name) this.form = blank();
      },
    }));
  });
})();
