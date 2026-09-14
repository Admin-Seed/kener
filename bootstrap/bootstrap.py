#!/usr/bin/env python3
"""Apply monitors.json, site.json and pages.json to a Kener instance.

Kener v4 has no file-based configuration and no import endpoint: monitors,
pages, categories and every branding value live only as rows in the database.
This script is how that configuration stays reviewable, diffable and rebuildable
from git anyway -- the three JSON files are the source of truth, and running
this makes the instance match them.

Idempotent: monitors and pages are PATCHed if they exist and POSTed if they do
not, and each site key is PATCHed in place. Nothing is ever deleted.

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
    fails with "Invalid URL" on every check. Measured, not theorised.
    """
    out = dict(monitor)
    td = out.get("type_data")
    if isinstance(td, str):
        out["type_data"] = json.loads(td)
    return out


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def apply_site():
    """Push every key in site.json."""
    failed = 0
    for key, value in load(SITE).items():
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
    monitors = load(MONITORS)
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
    return failed


def apply_pages():
    """Create or update every status page, including the home page.

    A monitor is INVISIBLE until it is assigned to a page, so this is not
    optional tidying -- skip it and monitors check happily behind a board that
    shows nothing.

    Membership comes from either `from_category` (derived from monitors.json, so
    a new tenant lands on the right page automatically) or an explicit `tags`
    list where order matters, as it does on the home page. Either way the
    assignment REPLACES rather than appends, so these files decide what is on
    each board.

    This is also how the Gatus groups are reproduced: Kener v4 does not group by
    category on a page -- `category_name` never reaches the rendered page -- so
    a group is a page.
    """
    pages = load(PAGES)
    monitors = load(MONITORS)
    known = set(m["tag"] for m in monitors)

    failed = 0
    for pg in pages:
        if "tags" in pg:
            tags = list(pg["tags"])
            unknown = [t for t in tags if t not in known]
            if unknown:
                print("%-16s FAILED - not in monitors.json: %s"
                      % (pg["page_path"], ", ".join(unknown)))
                failed += 1
                continue
        else:
            tags = [m["tag"] for m in monitors
                    if m["category_name"] == pg["from_category"]]
            if not tags:
                print("%-16s SKIPPED - no monitors in category %r"
                      % (pg["page_path"], pg["from_category"]))
                failed += 1
                continue

        body = dict((k, v) for k, v in pg.items()
                    if k not in ("from_category", "tags"))
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
        print("--- pages ---")
        failed += apply_pages()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
