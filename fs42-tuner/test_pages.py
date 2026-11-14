"""The dashboard's pages (static/): each one loads files that exist, from this server only, and the station
editor's chooser keeps its rows as data.

Run: python3 test_pages.py
"""
import glob
import os
import re
import unittest

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


def read(name):
    with open(os.path.join(STATIC, name), encoding="utf-8") as f:
        return f.read()


class PagesTest(unittest.TestCase):
    def pages(self):
        return sorted(os.path.basename(p) for p in glob.glob(os.path.join(STATIC, "*.html")))

    def test_every_page_loads_only_files_this_server_has(self):
        self.assertIn("settings.html", self.pages())
        for page in self.pages():
            for ref in re.findall(r'(?:src|href)="(/[^"#?]+\.(?:js|css))"', read(page)):
                if ref == "/mpegts.min.js":                      # fetched into the image when it is built (Dockerfile)
                    continue
                self.assertTrue(os.path.isfile(os.path.join(STATIC, ref.lstrip("/"))), f"{page} loads {ref}, which is not there")
            self.assertNotRegex(read(page), r'(?:src|href)="(?:https?:)?//', f"{page} loads something from another server")

    def test_every_page_is_bulma_and_alpine_from_the_vendor_folder(self):
        for page in self.pages():
            html = read(page)
            self.assertRegex(html, r'href="/vendor/bulma-[\d.]+\.min\.css"', page)
            self.assertRegex(html, r'<script defer src="/vendor/alpine-[\d.]+\.min\.js"></script>', page)
            self.assertIn('data-theme="dark"', html, page)

    def test_the_pages_that_became_tabs_are_gone_and_settings_has_their_tabs(self):
        for old in ("iptv.html", "schedule.html", "files.html", "status.html"):
            self.assertNotIn(old, self.pages())
        html, js = read("settings.html"), read("settings.js")
        for tab in ("general", "sources", "schedule", "files", "players", "viewers", "status"):
            self.assertIn(f'id: "{tab}"', js)
        for part in ("sourcesTab", "embyPanel", "scheduleTab", "filesTab", "viewersTab", "statusTab"):
            self.assertIn(f'x-data="{part}"', html)

    def test_the_player_can_say_what_is_playing(self):
        """A lower quality can look the same in a small player: the Stats button shows the decoded size and the rate."""
        html, js = read("watch.html"), read("app.js")
        self.assertIn('<div id="stats" x-show="stats" x-cloak x-text="statsText"></div>', html)      # text, never a function
        self.assertRegex(html, r'<button[^>]*@click="toggleStats\(\)"[^>]*>Stats</button>')
        self.assertIn(":aria-pressed=\"stats ? 'true' : 'false'\"", html)
        for needle in ("mpegts.Events.STATISTICS_INFO", "v.videoWidth", 'recall(STATS_KEY) === "on"'):
            self.assertIn(needle, js)

    def test_the_player_has_the_tv_apps_channel_bar_and_keys_that_reach_it(self):
        html, js, css = read("watch.html"), read("app.js"), read("player.css")
        bar = html[html.index('<div id="banner"'):html.index('<div id="captions"')]
        order = [bar.index(f'x-text="banner.{part}"') for part in ("num", "name", "clock", "title", "until")]
        self.assertEqual(order, sorted(order))                       # number, name, clock; then what is on, until when
        for colour in ("rgb(201, 201, 201)", "rgb(80, 255, 80)", "rgb(180, 176, 242)", "rgb(30, 30, 200)"):
            self.assertIn(colour, css)                               # the Cable box colours of client/banner.py
        # the controls, left to right: channel arrows, the number box, then the volume; Log out names nobody on its face
        controls = html[html.index('class="box controls"'):html.index('aria-label="Channel guide"')]
        marks = [controls.index(m) for m in ('aria-label="Channel up"', 'aria-label="Channel number"', 'id="volume"', '>Log out</button>')]
        self.assertEqual(marks, sorted(marks))
        self.assertNotIn("'Log out ('", html)
        # a control lets go of the keyboard once it is used, and the arrows do not scroll the page
        self.assertIn('@change="setQuality(Number($el.value)); $el.blur()"', html)
        self.assertIn('@change="$el.blur()"', html)
        self.assertIn("this.$refs.entry.blur()", js)
        self.assertIn("e.preventDefault()", js)

    def test_full_screen_keeps_the_controls_and_does_not_depend_on_the_browser_granting_it(self):
        html, js, css = read("watch.html"), read("app.js"), read("player.css")
        stage = html[html.index('id="stage"'):html.index('aria-label="Channel guide"')]
        for inside in ('id="screen"', 'class="box controls"', '@click="toggleFull()"'):
            self.assertIn(inside, stage)                             # what fills the screen holds the picture AND the controls
        self.assertIn(""":class="{ 'is-full': full, 'is-idle': idle }\"""", html)
        self.assertIn("#stage.is-full { position: fixed; inset: 0;", css)       # the window is filled by a style, whatever the browser says
        self.assertIn("requestFullscreen", js)
        self.assertNotIn("enableWorker: true", js)                   # tried: it left the picture a fifth of a second from stalling
        # full, the controls lie over the picture's foot (the same grid cell), so it never changes size as they come and go
        self.assertRegex(css, r"#stage\.is-full #screen \{ grid-area: 1 / 1;")
        self.assertRegex(css, r"#stage\.is-full \.box\.controls \{ grid-area: 1 / 1; align-self: end;")

    def test_the_controls_fade_when_nothing_moves_and_keep_their_room(self):
        html, js, css = read("watch.html"), read("app.js"), read("player.css")
        self.assertIn('<div class="box controls" x-ref="controls">', html)
        self.assertIn("#stage.is-idle .box.controls { opacity: 0; pointer-events: none; }", css)     # faded, not removed: nothing jumps
        self.assertIn("#stage.is-idle #screen { cursor: none; }", css)
        self.assertRegex(js, r'for \(const ev of \["mousemove", "mousedown", "touchstart", "focusin"\]\)')
        self.assertIn('c.matches(":hover")', js)                     # never from under the pointer
        self.assertNotIn(".box.controls { flex: none", css.replace("#stage.is-full .box.controls", ""))   # a stray rule once took the box's margin

    def test_nothing_above_the_settings_tabs_changes_height(self):
        """A title and a per-tab subtitle above the tab bar made it jump from tab to tab: each tab says what it is itself."""
        html = read("settings.html")
        above = html[html.index("<main"):html.index('<div class="tabs')]
        self.assertNotIn("x-text", above)
        self.assertNotRegex(above, r'class="(?:title|subtitle|page-head)')
        self.assertIn('<h1 class="is-sr-only">Settings</h1>', above)              # still a heading for a screen reader

    def test_the_sources_tab_always_shows_its_add_form_last(self):
        html = read("settings.html")
        sources = html[html.index('x-data="sourcesTab"'):html.index('x-data="scheduleTab"')]
        form = sources.index('<form class="box" x-ref="form"')
        self.assertGreater(form, sources.index('x-data="embyPanel"'))
        self.assertNotIn("form.open", html + read("iptv.js"))

    def test_nothing_drawn_by_the_chooser_is_a_function(self):
        """Alpine calls any function an expression evaluates to. A row that carried its own "use" function was chosen
        just by being drawn (x-show="r.use"), which walked the media and made a source of everything in it. Rows and
        chips are data; only openRow / useRow / removeChip act, and only on a click."""
        js = read("station.js")
        self.assertNotRegex(js, r"\b(?:open|use|remove)\s*:\s*(?:async\s*)?\([^)]*\)\s*=>")
        template = js[js.index("const CHOOSER = `"):js.index("`;", js.index("const CHOOSER = `"))]
        for shown in re.findall(r'(?:x-show|x-text|:disabled|:title|:class)="([^"]*)"', template):
            self.assertNotRegex(shown, r"^\s*!?\s*(?:r|c)\.(?:open|use|remove)\s*(?:\|\||&&|$)", shown)
        for click in re.findall(r'@click(?:\.prevent)?="([^"]*)"', template):
            self.assertRegex(click, r"^(?:removeChip\(c\)|toggle\(\)|go\(c\.root, c\.path\)|openRow\(r\)|useRow\(r\))$", click)


if __name__ == "__main__":
    unittest.main()
