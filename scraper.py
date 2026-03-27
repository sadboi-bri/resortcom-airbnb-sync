"""
ResortCom → Airbnb Calendar Sync
Logs into ResortCom, scrapes available dates, generates an iCal file for Airbnb.
"""

import os
import json
import logging
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright
from icalendar import Calendar, Event
import pytz

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

USERNAME = os.environ["RESORTCOM_USERNAME"]
PASSWORD = os.environ["RESORTCOM_PASSWORD"]
OUTPUT_FILE = "calendar.ics"


def login(page):
    log.info("Navigating to ResortCom login...")
    page.goto("https://reservation.resortcom.com/index")
    page.wait_for_load_state("networkidle")

    # Fill in credentials — update selectors if the site uses different field names
    page.fill('input[name="username"], input[type="text"]', USERNAME)
    page.fill('input[name="password"], input[type="password"]', PASSWORD)
    page.click('button[type="submit"], input[type="submit"]')
    page.wait_for_load_state("networkidle")
    log.info("Logged in successfully.")


def scrape_available_dates(page):
    """
    Navigate to the availability/booking calendar on ResortCom and extract open dates.
    NOTE: You may need to update the selectors below to match the actual site structure.
    Run with PWDEBUG=1 locally to inspect the page if dates aren't found.
    """
    log.info("Looking for availability calendar...")

    # Try to navigate to a booking/availability page
    # Update this URL to the correct page after you log in and browse to the calendar
    page.goto("https://reservation.resortcom.com/availability")  # ← update if needed
    page.wait_for_load_state("networkidle")

    available_dates = []

    # Generic approach: look for date elements marked as available
    # Common patterns used by booking calendars:
    date_cells = page.query_selector_all(
        ".available, .open, [data-status='available'], "
        "[class*='available'], [class*='open-date'], "
        "td.day:not(.unavailable):not(.disabled):not(.blocked)"
    )

    for cell in date_cells:
        date_str = (
            cell.get_attribute("data-date")
            or cell.get_attribute("data-day")
            or cell.get_attribute("title")
            or cell.inner_text().strip()
        )
        if date_str:
            try:
                # Try common date formats
                for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%B %d, %Y"):
                    try:
                        dt = datetime.strptime(date_str.strip(), fmt)
                        available_dates.append(dt.date())
                        break
                    except ValueError:
                        continue
            except Exception:
                pass

    log.info(f"Found {len(available_dates)} available dates.")
    return sorted(set(available_dates))


def dates_to_ical(available_dates):
    """Convert a list of available dates into an iCal file that Airbnb can read.
    Airbnb reads iCal as BLOCKED dates, so we invert the logic:
    we block all days that are NOT in available_dates for the next 12 months.
    """
    cal = Calendar()
    cal.add("prodid", "-//ResortCom Airbnb Sync//EN")
    cal.add("version", "2.0")

    tz = pytz.UTC
    today = datetime.now(tz).date()
    end_date = today + timedelta(days=365)

    # Build a set of available dates for fast lookup
    available_set = set(available_dates)

    current = today
    block_start = None

    def add_block(start, end):
        event = Event()
        event.add("summary", "Not Available")
        event.add("dtstart", start)
        event.add("dtend", end + timedelta(days=1))
        event.add("transp", "OPAQUE")
        cal.add_component(event)

    while current <= end_date:
        if current not in available_set:
            if block_start is None:
                block_start = current
        else:
            if block_start is not None:
                add_block(block_start, current - timedelta(days=1))
                block_start = None
        current += timedelta(days=1)

    if block_start is not None:
        add_block(block_start, end_date)

    return cal.to_ical()


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        try:
            login(page)
            available_dates = scrape_available_dates(page)

            if not available_dates:
                log.warning("No available dates found — check your selectors or login.")
            else:
                ical_data = dates_to_ical(available_dates)
                with open(OUTPUT_FILE, "wb") as f:
                    f.write(ical_data)
                log.info(f"Calendar written to {OUTPUT_FILE} with {len(available_dates)} available dates.")

            # Save dates as JSON for debugging
            with open("available_dates.json", "w") as f:
                json.dump([str(d) for d in available_dates], f, indent=2)

        except Exception as e:
            log.error(f"Script failed: {e}")
            raise
        finally:
            browser.close()


if __name__ == "__main__":
    main()
