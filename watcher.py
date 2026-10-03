"""Send a Telegram message for each new Summer 2027 software internship on SimplifyJobs."""

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
TERM = "Summer 2027"
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


def notify(token, chat_id, listing):
    company = listing.get("company_name") or "Unknown company"
    title = listing.get("title") or "Software internship"
    time, date = posted_at(listing)
    line = f"{company}: {title}" + (f" @ {time}" if time else "")
    url = html.escape(listing.get("url") or "", quote=True)
    payload = {
        "chat_id": chat_id,
        "text": f'<b>{html.escape(line)}</b>\n{date}\n<a href="{url}">Tap to apply</a>',
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
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        sys.exit("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set")

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
    for listing in new:
        try:
            notify(token, chat_id, listing)
            print(f"Notified: {listing.get('company_name')} | {listing.get('title')}")
        except Exception as e:
            failures += 1
            print(f"Failed to notify for {listing.get('id')}: {e}", file=sys.stderr)
        # Telegram asks bots to stay under about one message per second in a single chat.
        time.sleep(1)

    save_seen(seen | current_ids)
    if failures:
        print(f"{failures} notifications failed", file=sys.stderr)


if __name__ == "__main__":
    main()
