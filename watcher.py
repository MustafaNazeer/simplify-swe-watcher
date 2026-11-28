"""Send a Telegram message for each new or reopened software or data internship on SimplifyJobs."""

import html
import json
import os
import re
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
JOB_PAGE_URL = "https://simplify.jobs/p/{}"
# Listings whose pay is listed must reach this, in USD per year, at PAY_PERCENTILE of the way
# from the bottom of their range to the top. Listings with no pay listed are still sent.
MIN_YEARLY_PAY = 80_000
PAY_PERCENTILE = 0.4
HOURS_PER_YEAR = 2080
# Simplify uses salary_period 1 for hourly. When the period is missing, an amount above this
# is taken to be yearly and anything at or below it hourly.
YEARLY_AMOUNT_FLOOR = 1000
# Approximate rates to USD, only used to compare against MIN_YEARLY_PAY. Pay in any other
# currency counts as not listed.
USD_RATES = {"USD": 1.0, "CAD": 0.72, "GBP": 1.33, "EUR": 1.15}
HERE = os.path.dirname(os.path.abspath(__file__))
SEEN_PATH = os.path.join(HERE, "seen.json")
CLOSED_PATH = os.path.join(HERE, "closed.json")


def fetch_listings():
    req = urllib.request.Request(LISTINGS_URL, headers={"User-Agent": "simplify-swe-watcher"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def fetch_pay(listing):
    """Yearly USD (low, high, currency) from the listing's Simplify page, or None if not listed."""
    req = urllib.request.Request(
        JOB_PAGE_URL.format(listing["id"]), headers={"User-Agent": "Mozilla/5.0"}
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            page = resp.read().decode("utf-8", errors="replace")
        match = re.search(
            r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', page, re.S
        )
        job = json.loads(match.group(1))["props"]["pageProps"]["jobPosting"]
    except Exception as e:
        print(f"Could not read pay for {listing.get('id')}: {e}", file=sys.stderr)
        return None
    low, high = job.get("min_salary"), job.get("max_salary")
    currency = job.get("currency_type") or "USD"
    if (low is None and high is None) or currency not in USD_RATES:
        return None
    low, high = float(low if low is not None else high), float(high if high is not None else low)
    hourly = job.get("salary_period") == 1 or (
        job.get("salary_period") is None and high <= YEARLY_AMOUNT_FLOOR
    )
    scale = (HOURS_PER_YEAR if hourly else 1) * USD_RATES[currency]
    return low * scale, high * scale, currency


def pay_ok(pay):
    if pay is None:
        return True
    low, high, _ = pay
    return low + PAY_PERCENTILE * (high - low) >= MIN_YEARLY_PAY


def pay_text(pay):
    """Like "~$56K to $104K/yr", with the original currency noted when it was converted."""
    if pay is None:
        return "Pay not listed"
    low, high, currency = pay
    low_k, high_k = round(low / 1000), round(high / 1000)
    text = f"~${low_k}K/yr" if low_k == high_k else f"~${low_k}K to ${high_k}K/yr"
    return text if currency == "USD" else f"{text} (from {currency})"


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
    """Return (time, date) in US Central, like ("2:14PM", "November 27th"), or (None, date) for
    date only listings. The year is added when it is not the current year.

    Simplify stores date only listings as exactly midnight UTC, so those keep their UTC date
    rather than shifting to the previous evening.
    """
    ts = listing.get("date_posted")
    if not ts:
        return None, "date unknown"
    date_only = ts % 86400 == 0
    day = datetime.fromtimestamp(ts, timezone.utc if date_only else TIMEZONE)
    suffix = "th" if 11 <= day.day <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(day.day % 10, "th")
    date = f"{day:%B} {day.day}{suffix}"
    if day.year != datetime.now(TIMEZONE).year:
        date += f", {day.year}"
    return (None if date_only else day.strftime("%I:%M%p").lstrip("0")), date


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


def notify(token, chat_id, listing, pay):
    """One line: the company linked to the posting and the time posted, the pay, the date."""
    company = listing.get("company_name") or "Unknown company"
    clock, date = posted_at(listing)
    url = html.escape(listing.get("url") or "", quote=True)
    at = f" @ {clock}" if clock else ""
    send_message(
        token,
        chat_id,
        f'<b><a href="{url}">{html.escape(company)}</a>{html.escape(at)}</b>'
        f" | {html.escape(pay_text(pay))} | {html.escape(date)}",
    )


def reopened_summary(listings, pays):
    """One message for a batch of reopened listings, newest first, trimmed to fit Telegram."""
    listings = sorted(listings, key=lambda l: l.get("date_posted") or 0, reverse=True)
    header = f"Reopened: {len(listings)} listing{'s' if len(listings) != 1 else ''}"
    lines = [f"<b>{header}</b>"]
    length = len(header)
    shown = 0
    for listing in listings[:SUMMARY_MAX_LINES]:
        company = listing.get("company_name") or "Unknown company"
        clock, date = posted_at(listing)
        details = f" @ {clock} | " if clock else " | "
        details += f"{pay_text(pays[str(listing['id'])])} | {date}"
        url = html.escape(listing.get("url") or "", quote=True)
        if length + len(company + details) + 1 > SUMMARY_MAX_CHARS:
            break
        lines.append(f'<a href="{url}">{html.escape(company)}</a>{html.escape(details)}')
        length += len(company + details) + 1
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

    # Pay is only on each listing's own page, so it is fetched just for listings about to be
    # sent. Listings below the pay bar are still recorded as seen so they are not fetched again.
    pays = {}
    for listing in new + reopened:
        pays[str(listing["id"])] = fetch_pay(listing)
        time.sleep(0.5)
    low_pay = [l for l in new + reopened if not pay_ok(pays[str(l["id"])])]
    for listing in low_pay:
        print(f"Skipped for pay ({pay_text(pays[str(listing['id'])])}): "
              f"{listing.get('company_name')} | {listing.get('title')}")
    new = [l for l in new if pay_ok(pays[str(l["id"])])]
    reopened = [l for l in reopened if pay_ok(pays[str(l["id"])])]
    print(f"{len(current_ids)} open listings, {len(new)} new, {len(reopened)} reopened, "
          f"{len(low_pay)} below the pay bar")

    failures = 0
    for listing in new:
        try:
            notify(token, chat_id, listing, pays[str(listing["id"])])
            print(f"Notified: {listing.get('company_name')} | {listing.get('title')}")
        except Exception as e:
            failures += 1
            print(f"Failed to notify for {listing.get('id')}: {e}", file=sys.stderr)
        # Telegram asks bots to stay under about one message per second in a single chat.
        time.sleep(1)

    if reopened:
        try:
            send_message(token, chat_id, reopened_summary(reopened, pays))
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
