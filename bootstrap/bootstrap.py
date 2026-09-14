#!/usr/bin/env python3
"""Apply monitors.json to a Kener instance through the v4 REST API.

Kener v4 has no file-based monitor configuration and no import endpoint: monitors
live only as rows in the database. This script is how that configuration stays
reviewable, diffable and rebuildable from git anyway -- monitors.json is the
source of truth, and running this makes the instance match it.

Idempotent: a monitor whose `tag` already exists is PATCHed, otherwise POSTed.
Nothing is ever deleted -- removing a monitor from monitors.json will not remove
it from the instance. Delete those by hand, deliberately.

Usage:
    export KENER_URL=http://localhost:3002
    export KENER_API_KEY=...            # Settings -> API Keys, needs monitors.write
    python3 bootstrap.py [--dry-run]

Stdlib only: there is no jq and no pip on the host this runs on.
"""

import json
import os
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
MONITORS = os.path.join(HERE, "monitors.json")

BASE = os.environ.get("KENER_URL", "").rstrip("/")
KEY = os.environ.get("KENER_API_KEY", "")
DRY = "--dry-run" in sys.argv

if not BASE or not KEY:
    sys.exit("set KENER_URL and KENER_API_KEY")


def call(method, path, payload=None):
    """Return (status, parsed_body_or_text). Does not raise on 4xx/5xx."""
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Authorization", "Bearer " + KEY)
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode("utf-8")
            try:
                return r.status, json.loads(raw)
            except ValueError:
                return r.status, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, raw


def wire(monitor):
    """monitors.json keeps type_data as a readable object so the eval bodies are
    diffable. The API stores it as a JSON string, so stringify on the way out."""
    out = dict(monitor)
    if isinstance(out.get("type_data"), (dict, list)):
        out["type_data"] = json.dumps(out["type_data"])
    return out


def main():
    with open(MONITORS, encoding="utf-8") as fh:
        monitors = json.load(fh)

    tags = [m["tag"] for m in monitors]
    if len(tags) != len(set(tags)):
        sys.exit("monitors.json contains duplicate tags")

    created = updated = failed = 0
    for m in monitors:
        tag = m["tag"]
        status, _ = call("GET", "/api/v4/monitors/" + tag)
        exists = status == 200

        if DRY:
            print("%-28s %s" % (tag, "would update" if exists else "would create"))
            continue

        if exists:
            code, body = call("PATCH", "/api/v4/monitors/" + tag, wire(m))
            ok, verb = code in (200, 204), "updated"
        else:
            code, body = call("POST", "/api/v4/monitors", wire(m))
            ok, verb = code in (200, 201), "created"

        if ok:
            print("%-28s %s" % (tag, verb))
            if verb == "created":
                created += 1
            else:
                updated += 1
        else:
            print("%-28s FAILED http %s: %s" % (tag, code, str(body)[:300]))
            failed += 1

    if not DRY:
        print("\n%d created, %d updated, %d failed, %d total"
              % (created, updated, failed, len(monitors)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
