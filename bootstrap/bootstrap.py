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
    """Send type_data as an OBJECT.

    The API stringifies it itself before storing. Sending an already-stringified
    value double-encodes it: the column then parses as a JSON *string* rather
    than an object, every field including `url` reads back empty, and axios
    fails with "Invalid URL" on every check. Measured, not theorised -- it is
    why this function exists at all.
    """
    out = dict(monitor)
    td = out.get("type_data")
    if isinstance(td, str):
        out["type_data"] = json.loads(td)
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

    if DRY:
        print("\nwould assign %d monitors to the home page" % len(tags))
        return 0

    print("\n%d created, %d updated, %d failed, %d total"
          % (created, updated, failed, len(monitors)))

    # A monitor is INVISIBLE on the status page until it is assigned to a page.
    # Creating it is not enough: skip this and the board renders empty while
    # every monitor is happily checking in the background. That is exactly what
    # happened on the first run here, and it is why this step is in the script
    # rather than in a "remember to also..." note.
    #
    # The home page is addressed as `~home` -- its stored path is empty and its
    # public URL is the site root. `monitors` is a plain array of tags, and it
    # REPLACES the assignment rather than adding to it, so monitors.json decides
    # what is on the board and in what order.
    code, body = call("PATCH", "/api/v4/pages/~home", {"monitors": tags})
    if code in (200, 204):
        print("assigned %d monitors to the home page" % len(tags))
    else:
        print("FAILED to assign monitors to the home page: http %s: %s"
              % (code, str(body)[:300]))
        failed += 1

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
