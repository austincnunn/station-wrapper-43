# Vendored front-end libraries

The dashboard's pages are [Alpine.js](https://alpinejs.dev) components styled with [Bulma](https://bulma.io). Both are
kept here and served by the tuner itself, so the dashboard works on a network with no internet: nothing is fetched from
a CDN, and there is no build step. The version is in each file's name, so the server can tell browsers to keep them
(`Cache-Control: immutable`).

| File | Version | From (npm package, file) | Licence | sha256 |
|---|---|---|---|---|
| `bulma-1.0.4.min.css` | 1.0.4 | `bulma`, `css/bulma.min.css` | MIT (`LICENSE-bulma.txt`) | `67fa26df1ca9e95d8f2adc7c04fa1b15fa3d24257470ebc10cc68b9aab914bee` |
| `alpine-3.17.5.min.js` | 3.17.5 | `alpinejs`, `dist/cdn.min.js` | MIT (`LICENSE-alpine.txt`) | `b4036e9e9ac22fa6f6ae1ba292e015e1f3e9c85d0d79e73e4c8eb9bb139b522e` |

To update one: `npm pack <package>@<version>`, copy the file out of the tarball under its new name, change this table,
and change the two `<link>`/`<script>` lines in every page of `../` (`grep -l vendor/ ../*.html`), `scripts/smoke-image.sh`
and `fs42-tuner/test_auth_http.py`.
