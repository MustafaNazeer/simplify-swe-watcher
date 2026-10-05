"""Send a Telegram message for each new or reopened software or data internship on SimplifyJobs."""

import html
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

LISTINGS_URL = (
    "https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships/"
    "dev/.github/scripts/listings.json"
)
CATEGORIES = (
    "Software",
    "Software Engineering",
    "AI/ML/Data",
    "Data Science, AI & Machine Learning",
)
SUMMER_TERM = "Summer 2027"
OFF_SEASONS = ("Fall", "Winter", "Spring")
TIMEZONE = ZoneInfo("America/Chicago")
HERE = os.path.dirname(os.path.abspath(__file__))
SEEN_PATH = os.path.join(HERE, "seen.json")
CLOSED_PATH = os.path.join(HERE, "closed.json")


def fetch_listings():
    req = urllib.request.Request(LISTINGS_URL, headers={"User-Agent": "simplify-swe-watcher"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def off_season_terms(listing):
    return [t for t in listing.get("terms") or [] if t.startswith(OFF_SEASONS)]


def is_graduate_only(listing):
    """Same rule Simplify uses for the graduation cap marker in its README."""
    degrees = [d.lower() for d in listing.get("degrees") or []]
    if any(d in ("master's", "phd", "mba") for d in degrees) and not any(
        d in ("bachelor's", "associate's") for d in degrees
    ):
        return True
    title = (listing.get("title") or "").lower()
    return any(
        term in title
        for term in ("master's", "masters", "master", "mba", "phd", "ph.d", "doctorate", "doctoral")
    )


def in_scope(listing):
    """Category and term match, whether or not the listing is currently open."""
    return (
        listing.get("category") in CATEGORIES
        and listing.get("is_visible") is True
        and not is_graduate_only(listing)
        and (SUMMER_TERM in (listing.get("terms") or []) or bool(off_season_terms(listing)))
    )


def matches(listing):
    return in_scope(listing) and listing.get("active") is True


def posted_at(listing):
    """Return (time, date) strings in US Central, or (None, date) for date only listings.

    Simplify stores date only listings as exactly midnight UTC, so those keep their UTC date
    rather than shifting to the previous evening.
    """
    ts = listing.get("date_posted")
    if not ts:
        return None, "Date unknown"
    if ts % 86400 == 0:
        day = datetime.fromtimestamp(ts, timezone.utc)
        return None, f"{day:%B} {day.day}, {day.year}"
    local = datetime.fromtimestamp(ts, TIMEZONE)
    return local.strftime("%I:%M%p").lstrip("0"), f"{local:%B} {local.day}, {local.year}"


def notify(token, chat_id, listing, reopened=False):
    company = listing.get("company_name") or "Unknown company"
    title = listing.get("title") or "Software internship"
    clock, date = posted_at(listing)
    line = f"{company}: {title}" + (f" @ {clock}" if clock else "")
    tags = (["Reopened"] if reopened else []) + (
        [] if SUMMER_TERM in (listing.get("terms") or []) else off_season_terms(listing)
    )
    if tags:
        date = f"{', '.join(tags)}, posted {date}"
    url = html.escape(listing.get("url") or "", quote=True)
    payload = {
        "chat_id": chat_id,
        "text": f'<b>{html.escape(line)}</b>\n{html.escape(date)}\n<a href="{url}">Tap to apply</a>',
        "parse_mode": "HTML",
        "link_preview_options": {"is_disabled": True},
    }
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        resp.read()


def load_ids(path):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return set(json.load(f))


def save_ids(path, ids):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(sorted(ids), f, indent=0)
        f.write("\n")


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        sys.exit("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set")

    scoped = [l for l in fetch_listings() if in_scope(l)]
    current = [l for l in scoped if l.get("active") is True]
    current_ids = {str(l["id"]) for l in current}
    closed_now = {str(l["id"]) for l in scoped if l.get("active") is not True}
    seen = load_ids(SEEN_PATH)
    closed = load_ids(CLOSED_PATH)

    if seen is None or closed is None:
        # First run, or the first run after closed.json was introduced: record the current
        # state without sending anything, so existing listings do not flood the chat.
        save_ids(SEEN_PATH, (seen or set()) | current_ids)
        save_ids(CLOSED_PATH, closed_now)
        print(f"Seeded {len(current_ids)} open and {len(closed_now)} closed listings, no notifications sent")
        return

    to_send = [
        (l, str(l["id"]) in closed)
        for l in current
        if str(l["id"]) not in seen or str(l["id"]) in closed
    ]
    to_send.sort(key=lambda item: item[0].get("date_posted") or 0)
    reopened_count = sum(1 for _, reopened in to_send if reopened)
    print(
        f"{len(current_ids)} open listings, {len(to_send) - reopened_count} new, "
        f"{reopened_count} reopened"
    )

    failures = 0
    for listing, reopened in to_send:
        try:
            notify(token, chat_id, listing, reopened)
            label = "Notified (reopened)" if reopened else "Notified"
            print(f"{label}: {listing.get('company_name')} | {listing.get('title')}")
        except Exception as e:
            failures += 1
            print(f"Failed to notify for {listing.get('id')}: {e}", file=sys.stderr)
        # Telegram asks bots to stay under about one message per second in a single chat.
        time.sleep(1)

    save_ids(SEEN_PATH, seen | current_ids)
    save_ids(CLOSED_PATH, closed_now)
    if failures:
        print(f"{failures} notifications failed", file=sys.stderr)


if __name__ == "__main__":
    main()
