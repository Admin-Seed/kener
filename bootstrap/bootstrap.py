#!/usr/bin/env python3
"""Apply monitors.json and site.json to a Kener instance through the v4 REST API.

Kener v4 has no file-based configuration and no import endpoint: monitors,
categories and every branding value live only as rows in the database. This
script is how that configuration stays reviewable, diffable and rebuildable from
git anyway -- the two JSON files are the source of truth, and running this makes
the instance match them.

Idempotent: a monitor whose `tag` already exists is PATCHed, otherwise POSTed,
and each site key is PATCHed in place. Nothing is ever deleted.

Usage:
    export KENER_URL=https://uptime.seedaps.com     # or http://localhost:3001
    export KENER_API_KEY=...                        # Settings -> API Keys
    python3 bootstrap.py [--dry-run] [--site-only] [--monitors-only]

Stdlib only: there is no jq and no pip on the host this runs on.
"""

import json
import os
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
MONITORS = os.path.join(HERE, "monitors.json")
SITE = os.path.join(HERE, "site.json")
PAGES = os.path.join(HERE, "pages.json")

BASE = os.environ.get("KENER_URL", "").rstrip("/")
KEY = os.environ.get("KENER_API_KEY", "")
DRY = "--dry-run" in sys.argv
SITE_ONLY = "--site-only" in sys.argv
MONITORS_ONLY = "--monitors-only" in sys.argv

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


def apply_site():
    """Push every key in site.json.

    `categories` is the one that matters most: a monitor's `category_name` only
    becomes a heading on the board if a category of that name is declared here.
    Set the monitors without the categories and they all pile into one flat
    list, which is what happened before this file existed.
    """
    with open(SITE, encoding="utf-8") as fh:
        site = json.load(fh)

    failed = 0
    for key, value in site.items():
        if DRY:
            print("%-16s would set" % key)
            continue
        code, body = call("PATCH", "/api/v4/site/" + key, {"value": value})
        if code in (200, 204):
            print("%-16s set" % key)
        else:
            print("%-16s FAILED http %s: %s" % (key, code, str(body)[:200]))
            failed += 1
    return failed


def apply_monitors():
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
        return failed

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

    return failed


def apply_pages():
    """Create or update one status page per group.

    This is how the Gatus groups are reproduced. Kener v4 does **not** group
    monitors by category on a page -- `category_name` is set on every monitor
    and the `categories` site key is populated, but neither reaches the rendered
    page; they are v3 leftovers. Groups in v4 are separate pages, linked from
    the nav.

    Membership is derived from `category_name` in monitors.json rather than
    listed here, so a new tenant lands on the right page by virtue of its
    category and the two files cannot drift apart.
    """
    with open(PAGES, encoding="utf-8") as fh:
        pages = json.load(fh)
    with open(MONITORS, encoding="utf-8") as fh:
        monitors = json.load(fh)

    failed = 0
    for pg in pages:
        tags = [m["tag"] for m in monitors
                if m["category_name"] == pg["from_category"]]
        if not tags:
            print("%-16s SKIPPED - no monitors in category %r"
                  % (pg["page_path"], pg["from_category"]))
            failed += 1
            continue

        body = dict((k, v) for k, v in pg.items() if k != "from_category")
        body["monitors"] = tags

        if DRY:
            print("%-16s would hold %d monitors" % (pg["page_path"], len(tags)))
            continue

        code, _ = call("GET", "/api/v4/pages/" + pg["page_path"])
        if code == 200:
            code, resp = call("PATCH", "/api/v4/pages/" + pg["page_path"], body)
            verb, okcodes = "updated", (200, 204)
        else:
            code, resp = call("POST", "/api/v4/pages", body)
            verb, okcodes = "created", (200, 201)

        if code in okcodes:
            print("%-16s %-8s %d monitors" % (pg["page_path"], verb, len(tags)))
        else:
            print("%-16s FAILED http %s: %s"
                  % (pg["page_path"], code, str(resp)[:200]))
            failed += 1
    return failed


def main():
    failed = 0
    if not MONITORS_ONLY:
        print("--- site configuration ---")
        failed += apply_site()
        print()
    if not SITE_ONLY:
        print("--- monitors ---")
        failed += apply_monitors()
        print()
        print("--- group pages ---")
        failed += apply_pages()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
