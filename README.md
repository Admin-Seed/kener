# kener

Deployment configuration for [Kener](https://github.com/rajnandan1/kener) on
`seed-vm-services-linux-eastus`. **Not a fork** — this repository holds only
the Compose file, the monitor definitions and the backup job (`ops/`).

Deployed with `docker compose` from a clone at `/opt/stacks/kener` on the VM
(see *Changing configuration*). It replaced Gatus (ADR-0007) on 2026-09-14.

| | |
| --- | --- |
| Published | <https://uptime.seedaps.com> — Cloudflare Tunnel → `localhost:3001` |
| VNet | `http://172.17.0.5:3001` |
| Image | `rajnandan1/kener:4.1.11` |

## Kener has no authentication of its own

This is the single most important thing to know before touching the ingress.

Kener's status page is **world-readable to anyone who can reach it**. There is
no whole-site login, no "private mode", and no HTTP basic auth — the entire v4
documentation set contains nothing of the kind. Gatus's basic auth does not
carry over.

The gate is **Cloudflare Access on the published hostname**, and it is not
optional. Adding a tunnel ingress rule without it publishes 46 monitors, their
hostnames and their outage history to the internet.

> For `uptime.seedaps.com` this was later accepted deliberately: ADR-0010 keeps
> the board public (see the header of `compose.yaml`). Putting Cloudflare
> Access in front of the hostname is how that would be undone.

## Three services, and why each is here

| Service | Image | Published | Why |
| --- | --- | --- | --- |
| `kener` | `rajnandan1/kener:4.1.11` | `3001` → `3000` | the application |
| `postgres` | `postgres:16-alpine` | — | dedicated database |
| `redis` | `redis:7-alpine` | — | required; BullMQ queues |

**Redis is not optional.** Kener will not start without `REDIS_URL`. AOF is on.

**PostgreSQL is dedicated, not shared.** Kener's own docs recommend PostgreSQL
for production, and there is **no SQLite → PostgreSQL migration path**, so the
choice is made up front rather than discovered later.

Neither `postgres` nor `redis` publishes a port. Only `kener` does, because
`cloudflared` runs as a systemd service on the VM host rather than as a
container and cannot reach a Docker network by service name.

## Monitors live in the database, not in this repo

Kener v4 has no file-based monitor configuration, no YAML import and no bulk
import endpoint. Monitors are rows, managed through the admin UI or the REST
API. This is a real regression from Gatus, where a monitor was a git commit.

`bootstrap/` is the answer to that. `monitors.json` is the reviewable,
diffable source of truth, and `bootstrap/bootstrap.py` applies it through the
API. See [`bootstrap/README.md`](bootstrap/README.md).

It follows that **the database volume holds configuration, not just history** —
unlike `gatus-data`, which held only graphs. Losing it loses the monitors. That
is why this stack has a backup and Gatus did not.

## Write assertions against the body, not the status code

Every hostname under `seedaps.com` answers `200`, whether or not it exists,
because the zone carries a wildcard record. `*.coortex.com` is a wildcard too,
and its `/health` returns `Healthy` for **any** hostname. A status-code check
would produce 33 green lights that stayed green for a deleted tenant.

So every monitor here asserts on the response body, in its `eval` function:

| Group | Discriminator |
| --- | --- |
| `seed` | body does **not** contain `inexistente` — measured 0/33 real tenants, 4/4 invented controls |
| `coortex`, `coortex dev` | body contains `Seed APS`, checked on `/` and never on `/health` |
| `internal` → portal admin | body contains `Seed Web Admin` |
| `internal` → n8n, signoz | parsed JSON `status == "ok"` |

## Certificates are checked once per certificate

Gatus repeated a certificate condition on 37 endpoints that share **two**
wildcard certificates. Kener has a dedicated `SSL` monitor type, so this is
three monitors instead: the `seedaps.com` wildcard, the `coortex.com` wildcard,
and the Azure SQL gateway on port 1433. One expiry is one alert.

Those use thresholds rather than a flat condition — `DEGRADED` at 168h
remaining, `DOWN` at 24h.

## Changing configuration

| Change | How |
| --- | --- |
| Compose, image pin, ports, `ORIGIN` | PR here, merge, then on the VM: `/opt/stacks/vm-services/deploy.sh /opt/stacks/kener` |
| Backup job (`ops/`) | PR here, merge, then on the VM copy `ops/kener-backup.sh` to `/usr/local/bin/` and the units to `/etc/systemd/system/`, `systemctl daemon-reload` |
| A monitor | edit `bootstrap/monitors.json`, commit, run `bootstrap.py` |
| Incidents, maintenance, pages, users | in the Kener UI — these are not in git |

`ORIGIN` is a literal in `compose.yaml` rather than an environment variable, so
that the value the browser must match is reviewable. It has to be the exact URL
users visit, with no trailing slash — SvelteKit rejects **every form POST,
including login**, with "Cross-site POST form submissions are forbidden" if it
is wrong.

## Two things that will bite

**Do not use the `:alpine` tag.** Upstream's own `docker-compose.yml` comments
*"For Alpine variant use: rajnandan1/kener:alpine"*. That tag was last pushed in
August 2025 and is a v3-era leftover. Use a versioned tag instead.

**Do not add a Docker healthcheck for `kener`.** The official image already
ships one against the plain `/healthcheck`. Never point a restart-on-failure
check at `/healthcheck?strict=1` — that endpoint returns `503` when the database
or Redis is down, and restarting Kener cannot fix either, so it would restart-loop
for the whole outage. `?strict=1` is for alerting, not for restarts.

## Secrets

Nothing secret is in this repository, which is public.

`KENER_SECRET_KEY` and `KENER_DB_PASSWORD` live in the `.env` beside this
Compose file on the VM (`/opt/stacks/kener/.env`, mode 600, ignored by git).
`compose.yaml` refers to them as `${NAME:?…}` and fails loudly rather than
starting with a blank value.

Anyone who can read that file, or run `docker inspect` / `docker compose config`
on the VM, can read them.

## Storage

| Volume | Holds | If lost |
| --- | --- | --- |
| `kener-postgres-data` | monitors, history, incidents, users, uploaded images | **configuration is gone** — restore from backup |
| `kener-redis-data` | BullMQ queue state | rebuilt from the database |

v4 stores uploaded logos and images as database rows; v3's `/uploads/` directory
no longer exists. With PostgreSQL, the database volume is the only thing that
must be backed up.

Backups are a nightly `pg_dump` (custom format) by `ops/kener-backup.sh`, run
by `ops/kener-backup.timer` at 02:30 UTC, into `/var/backups/kener/` on the VM
(root only, 14 kept). **That is the same disk as the database volume**: losing
the disk loses both. An off-VM copy is still pending. Restore is documented in
the `Agent` repository under `docs/runbooks/`.
