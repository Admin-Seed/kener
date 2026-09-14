# brand

Seed APS marks, carried here so this stack does not depend on the Gatus
repository for its own branding.

| File | Use |
| --- | --- |
| `logo-white.png` | 1081×1080. **In use** — the board runs a dark theme |
| `logo-black.png` | 1081×1081. The light-theme mark, kept for when it is wanted |
| `favicon-32.png`, `favicon-16.png`, `favicon-180.png` | browser tab and touch icon |

## Why both logos, when only one is used

Gatus rendered a theme-aware logo by swapping a CSS background on `:root.dark`.
**Kener has no equivalent** — `site_data.logo` is a single value with no dark
variant. So the board is pinned to the dark theme (`kenerTheme: dark`,
`themeToggle: NO`) and uses the white mark, which is also the shade this board
was originally asked for.

If the light theme is ever wanted, switch `logo` to `logo-black.png` in the same
change as `kenerTheme` — never one without the other, or the mark disappears
into the background.

## How they are referenced

Kener stores uploaded images as **database rows** and serves them from
`/assets/images/[id]`, but v4.1.5 exposes no API for uploading one, so these are
referenced by raw URL from this public repository:

```
https://raw.githubusercontent.com/Admin-Seed/kener/main/brand/logo-white.png
```

That is the same mechanism the Gatus favicon already uses, and it is an external
dependency: if GitHub raw is unreachable the mark fails to load, though the
board itself is unaffected. Uploading them through the admin UI instead would
put them in `kener-postgres-data` and remove that dependency — worth doing if
the images are ever changed by hand.

The sources are the same PNGs supplied for the Gatus board, lifted out of the
base64 data URIs in its `config/01-ui.yaml` rather than re-exported, so they are
byte-identical to what was already approved.
