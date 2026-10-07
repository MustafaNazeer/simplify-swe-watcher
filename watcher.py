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
README_URL = "https://github.com/SimplifyJobs/Summer2027-Internships"
SUMMARY_MAX_LINES = 40
# Telegram rejects messages whose visible text (links not counted) is over 4096 characters;
# leave room for the closing line.
SUMMARY_MAX_CHARS = 3800
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


def short_date(listing):
    """Posted date like "Aug 3", with the year added when it is not the current year."""
    ts = listing.get("date_posted")
    if not ts:
        return "date unknown"
    day = datetime.fromtimestamp(ts, timezone.utc if ts % 86400 == 0 else TIMEZONE)
    text = f"{day:%b} {day.day}"
    return text if day.year == datetime.now(TIMEZONE).year else f"{text}, {day.year}"


def listing_terms(listing):
    return [] if SUMMER_TERM in (listing.get("terms") or []) else off_season_terms(listing)


def send_message(token, chat_id, text):
    payload = {
        "chat_id": chat_id,
        "text": text,
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


def notify(token, chat_id, listing):
    company = listing.get("company_name") or "Unknown company"
    title = listing.get("title") or "Software internship"
    clock, date = posted_at(listing)
    line = f"{company}: {title}" + (f" @ {clock}" if clock else "")
    terms = listing_terms(listing)
    if terms:
        date = f"{', '.join(terms)}, posted {date}"
    url = html.escape(listing.get("url") or "", quote=True)
    send_message(
        token,
        chat_id,
        f'<b>{html.escape(line)}</b>\n{html.escape(date)}\n<a href="{url}">Tap to apply</a>',
    )


def reopened_summary(listings):
    """One message for a batch of reopened listings, newest first, trimmed to fit Telegram."""
    listings = sorted(listings, key=lambda l: l.get("date_posted") or 0, reverse=True)
    header = f"Reopened: {len(listings)} listing{'s' if len(listings) != 1 else ''}"
    lines = [f"<b>{header}</b>"]
    length = len(header)
    shown = 0
    for listing in listings[:SUMMARY_MAX_LINES]:
        company = listing.get("company_name") or "Unknown company"
        title = listing.get("title") or "Software internship"
        details = ", ".join([short_date(listing)] + listing_terms(listing))
        url = html.escape(listing.get("url") or "", quote=True)
        visible = f"{company}: {title} ({details})"
        if length + len(visible) + 1 > SUMMARY_MAX_CHARS:
            break
        lines.append(f'<a href="{url}">{html.escape(f"{company}: {title}")}</a> ({html.escape(details)})')
        length += len(visible) + 1
        shown += 1
    if shown < len(listings):
        lines.append(f'...and {len(listings) - shown} more on <a href="{README_URL}">Simplify\'s list</a>')
    return "\n".join(lines)


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

    reopened = [l for l in current if str(l["id"]) in closed]
    new = [l for l in current if str(l["id"]) not in seen and str(l["id"]) not in closed]
    new.sort(key=lambda l: l.get("date_posted") or 0)
    print(f"{len(current_ids)} open listings, {len(new)} new, {len(reopened)} reopened")

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

    if reopened:
        try:
            send_message(token, chat_id, reopened_summary(reopened))
            for listing in reopened:
                print(f"Notified (reopened): {listing.get('company_name')} | {listing.get('title')}")
        except Exception as e:
            failures += 1
            print(f"Failed to send the reopened summary: {e}", file=sys.stderr)

    save_ids(SEEN_PATH, seen | current_ids)
    save_ids(CLOSED_PATH, closed_now)
    if failures:
        print(f"{failures} notifications failed", file=sys.stderr)


if __name__ == "__main__":
    main()
