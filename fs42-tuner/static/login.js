// The login page: log in, set the first password, or change it. It stands alone (no bar, no common.js): it is the one
// page everyone can open.
(function () {
  "use strict";
  const params = new URLSearchParams(location.search);

  // Only ever go back to a page on this server. A tab of the Settings page (#schedule) survives the redirect here
  // as this page's own #, so it is put back on.
  function nextUrl() {
    const n = params.get("next") || "/";
    const ok = /^\/(?![\/\\])[^\s]*$/.test(n) && !n.startsWith("/login");
    return ok ? n + (n.includes("#") ? "" : location.hash) : "/";
  }

  async function post(path, body) {
    let res, data;
    try {
      res = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      data = await res.json();
    } catch (e) {
      throw new Error("could not reach the dashboard");
    }
    if (!res.ok) throw new Error(data.error || `that failed (${res.status})`);
    return data;
  }

  document.addEventListener("alpine:init", () => {
    Alpine.data("loginPage", () => ({
      mode: "",                  // login | setup | change | off
      msg: "", kind: "", busy: false,
      pw: "", pw2: "", old: "",
      viewer: false, user: "",   // the web viewer's port (viewers.py): the same page, with a name as well

      init() {
        this.run(async () => {
          const st = await (await fetch("/api/auth/status")).json();
          this.viewer = !!st.viewer;
          if (!st.login) this.mode = "off";
          else if (st.setup_needed) this.mode = "setup";
          else if (st.authenticated && params.get("change")) this.mode = "change";
          else if (st.authenticated) return location.replace(nextUrl());
          else this.mode = "login";
          this.$nextTick(() => { const el = this.$refs[this.viewer ? "user" : this.mode]; if (el) el.focus(); });
        });
      },
      async run(fn) {
        this.busy = true;
        this.msg = "";
        try {
          await fn();
        } catch (e) {
          this.msg = e.message;
          this.kind = "err";
        }
        this.busy = false;
      },
      login() {
        return this.run(async () => {
          await post("/api/auth/login", this.viewer ? { user: this.user, password: this.pw } : { password: this.pw });
          location.assign(nextUrl());
        });
      },
      setup() {
        return this.run(async () => {
          if (this.pw !== this.pw2) throw new Error("the two passwords are not the same");
          await post("/api/auth/setup", { password: this.pw });
          location.assign(nextUrl());
        });
      },
      change() {
        return this.run(async () => {
          if (this.pw !== this.pw2) throw new Error("the two new passwords are not the same");
          await post("/api/auth/password", { current: this.old, new: this.pw });
          this.old = this.pw = this.pw2 = "";
          this.msg = "Password changed. Everyone else has been logged out.";
          this.kind = "ok";
        });
      },
    }));
  });
})();
