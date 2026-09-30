"""Send an ntfy push for each new Summer 2027 software internship on SimplifyJobs."""

import base64
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

LISTINGS_URL = (
    "https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships/"
    "dev/.github/scripts/listings.json"
)
CATEGORIES = ("Software", "Software Engineering")
TERM = "Summer 2027"
MAX_NOTIFICATIONS = 20
TIMEZONE = ZoneInfo("America/Chicago")
SEEN_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seen.json")


def fetch_listings():
    req = urllib.request.Request(LISTINGS_URL, headers={"User-Agent": "simplify-swe-watcher"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def matches(listing):
    return (
        listing.get("category") in CATEGORIES
        and TERM in (listing.get("terms") or [])
        and listing.get("active") is True
        and listing.get("is_visible") is True
    )


def header_value(text):
    """ntfy accepts RFC 2047 encoded words for non ASCII header values."""
    try:
        text.encode("ascii")
        return text
    except UnicodeEncodeError:
        return "=?UTF-8?B?" + base64.b64encode(text.encode("utf-8")).decode("ascii") + "?="


def posted_time(listing):
    ts = listing.get("date_posted")
    if not ts:
        return "unknown time"
    return datetime.fromtimestamp(ts, TIMEZONE).strftime("%I:%M%p").lstrip("0")


def notify(topic, listing):
    company = listing.get("company_name") or "Unknown company"
    title = listing.get("title") or "Software internship"
    url = urllib.parse.quote(listing.get("url") or "", safe=":/?#[]@!$&'()*+,;=%~")
    req = urllib.request.Request(
        f"https://ntfy.sh/{topic}",
        data=b"Tap to apply",
        method="POST",
        headers={
            "Title": header_value(f"{company}: {title} @ {posted_time(listing)}"),
            "Click": url,
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        resp.read()


def load_seen():
    if not os.path.exists(SEEN_PATH):
        return None
    with open(SEEN_PATH, encoding="utf-8") as f:
        return set(json.load(f))


def save_seen(ids):
    with open(SEEN_PATH, "w", encoding="utf-8") as f:
        json.dump(sorted(ids), f, indent=0)
        f.write("\n")


def main():
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if not topic:
        sys.exit("NTFY_TOPIC is not set")

    current = [l for l in fetch_listings() if matches(l)]
    current_ids = {str(l["id"]) for l in current}
    seen = load_seen()

    if seen is None:
        save_seen(current_ids)
        print(f"Seeded seen.json with {len(current_ids)} listings, no notifications sent")
        return

    new = [l for l in current if str(l["id"]) not in seen]
    new.sort(key=lambda l: l.get("date_posted") or 0)
    print(f"{len(current_ids)} matching listings, {len(new)} new")

    failures = 0
    for listing in new[:MAX_NOTIFICATIONS]:
        try:
            notify(topic, listing)
            print(f"Notified: {listing.get('company_name')} | {listing.get('title')}")
        except Exception as e:
            failures += 1
            print(f"Failed to notify for {listing.get('id')}: {e}", file=sys.stderr)
    if len(new) > MAX_NOTIFICATIONS:
        print(f"Skipped {len(new) - MAX_NOTIFICATIONS} over the per run cap")

    save_seen(seen | current_ids)
    if failures:
        print(f"{failures} notifications failed", file=sys.stderr)


if __name__ == "__main__":
    main()
