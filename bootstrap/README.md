# bootstrap

Kener v4 keeps monitors **only as rows in its database**. There is no
`monitors.yaml`, no YAML import, and no bulk-import endpoint — I checked the
whole v4 documentation set and the OpenAPI spec before writing this.

That is a regression from Gatus, where a monitor was a reviewable file and a
`git revert` away from restored. This directory is how that property is kept
anyway:

- **`monitors.json`** — the source of truth. Reviewable, diffable, and the thing
  to change when a monitor changes.
- **`bootstrap.py`** — applies it through the REST API. Stdlib only; there is no
  `jq` and no `pip` on the host this runs on.

## Running it

```bash
export KENER_URL=http://localhost:3002          # 3001 after cutover
export KENER_API_KEY=...                        # Settings → API Keys
python3 bootstrap.py --dry-run                  # show what would change
python3 bootstrap.py
```

The API key needs `monitors.read` and `monitors.write`.

## What it does and does not do

It is **idempotent**: a monitor whose `tag` already exists is `PATCH`ed,
otherwise `POST`ed. Running it twice is safe and is the intended way to apply an
edit to `monitors.json`.

It **never deletes**. Removing a monitor from `monitors.json` does not remove it
from the instance — delete those in the UI, deliberately, because
`DELETE /api/v4/monitors/{tag}` also destroys that monitor's entire history,
its incident and maintenance links, and its alert configuration.

It does **not** assign monitors to a status page. That is a separate concern
(`/api/v4/pages`), and in Kener a monitor is invisible on a page until it is
added to one. Do that once in the UI after the first run.

## Shape notes

`type_data` is written here as a **readable object** so that the `eval` function
bodies are diffable. The API stores it as a JSON string, so `bootstrap.py`
stringifies it on the way out. Do not pre-stringify it in `monitors.json`.

`tag` is the identity key and must be unique across every monitor. Gatus allowed
the same name in two groups — `csnupv` exists in `seed`, `coortex` and
`coortex dev` — so tags here are prefixed with their group.

Changing a `tag` does not rename a monitor; it creates a second one and orphans
the first, along with its history. Treat tags as permanent.

## The eval functions are the point

Every monitor asserts on the response **body**, never on the status code alone.
The reason is in the parent [`README.md`](../README.md): both `seedaps.com` and
`coortex.com` carry wildcard DNS records, so every hostname answers `200`
whether or not it is configured, and `*.coortex.com/health` returns `Healthy`
for a hostname that does not exist.

If you add a monitor for a new tenant, copy an existing `seed` entry and change
only `tag`, `name` and `type_data.url`. Do not simplify the eval to a status
check — that check passes for hostnames that were never configured, which is
exactly the failure this is built to catch.
