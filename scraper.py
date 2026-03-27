"""
ResortCom (UVCI) → Airbnb Calendar Sync
Logs in, navigates to Owner Time calendar, scrapes available dates across 12 months,
then generates an iCal file for Airbnb to consume.
"""

import os
import json
import logging
from datetime import datetime, timedelta, date
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from icalendar import Calendar, Event
import pytz

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

USERNAME = os.environ["RESORTCOM_USERNAME"]
PASSWORD = os.environ["RESORTCOM_PASSWORD"]
OUTPUT_FILE = "calendar.ics"

# How many times to click "Next Month" to cover ~12 months (2 months shown at a time)
NEXT_MONTH_CLICKS = 5


def login(page):
    log.info("Navigating to ResortCom login...")
    page.goto("https://reservation.resortcom.com/index", wait_until="networkidle")
    page.fill('input[name="username"], input[type="text"]', USERNAME)
    page.fill('input[name="password"], input[type="password"]', PASSWORD)
    page.click('button[type="submit"], input[type="submit"]')
    page.wait_for_load_state("networkidle", timeout=30000)
    log.info(f"Logged in. Current URL: {page.url}")


def go_to_reservation_search(page):
    log.info("Clicking Make Reservation...")
    page.click("text=MAKE RESERVATION")
    page.wait_for_load_state("networkidle", timeout=30000)

    log.info("Selecting Cabo San Lucas...")
    # Clear existing selections and pick Cabo San Lucas
    try:
        # Close any pre-selected items first (the X buttons)
        close_buttons = page.query_selector_all(".multiselect__tag-icon, [class*='tag'] span, .tag-close")
        for btn in close_buttons:
            btn.click()
        page.wait_for_timeout(500)
    except Exception:
        pass

    # Select destination: Cabo San Lucas
    page.click("[placeholder*='destination'], [placeholder*='Destination'], .multiselect__input, input[placeholder*='Select']")
    page.wait_for_timeout(500)
    page.click("text=Cabo San Lucas")
    page.wait_for_timeout(500)

    log.info("Selecting Villa Del Arco...")
    # Select resort: Villa Del Arco - click the second dropdown
    resort_inputs = page.query_selector_all(".multiselect__input, input[placeholder*='Select']")
    if len(resort_inputs) > 1:
        resort_inputs[1].click()
    page.wait_for_timeout(500)
    page.click("text=Villa Del Arco")
    page.wait_for_timeout(500)

    log.info("Selecting One Bedroom...")
    # Select room type: One Bedroom
    room_inputs = page.query_selector_all(".multiselect__input, input[placeholder*='Select']")
    if len(room_inputs) > 2:
        room_inputs[2].click()
    page.wait_for_timeout(500)
    page.click("text=One Bedroom")
    page.wait_for_timeout(500)

    # Set check-in date to ~3 weeks from today
    checkin = (date.today() + timedelta(weeks=3)).strftime("%-m/%-d/%Y")
    checkout = (date.today() + timedelta(weeks=5)).strftime("%-m/%-d/%Y")

    log.info(f"Setting dates: {checkin} to {checkout}")
    date_inputs = page.query_selector_all("input[type='text'][class*='date'], input[placeholder*='date'], input[placeholder*='Date']")
    if len(date_inputs) >= 2:
        date_inputs[0].triple_click()
        date_inputs[0].type(checkin)
        date_inputs[1].triple_click()
        date_inputs[1].type(checkout)
    
    page.wait_for_timeout(500)
    log.info("Clicking Search...")
    page.click("text=SEARCH")
    page.wait_for_load_state("networkidle", timeout=30000)


def click_owner_time_calendar(page):
    log.info("Looking for Owner Time calendar icon...")
    page.wait_for_timeout(2000)

    # Find the Owner Time section and click its calendar icon
    # The calendar icons are next to each booking type
    owner_section = page.query_selector("text=Owner Time")
    if owner_section:
        # Get the parent container and find the calendar button within it
        parent = owner_section.evaluate_handle("el => el.closest('.row, .section, div[class*=\"time\"], div[class*=\"owner\"]') || el.parentElement.parentElement")
        cal_btn = page.query_selector_all("button[class*='calendar'], .calendar-icon, button svg, [class*='btn-calendar']")
        if cal_btn:
            cal_btn[0].click()
        else:
            # Fallback: find all calendar-like buttons and click the first one (Owner Time)
            all_btns = page.query_selector_all("button")
            for btn in all_btns:
                inner = btn.inner_html()
                if "calendar" in inner.lower() or "📅" in inner:
                    btn.click()
                    break
    
    page.wait_for_load_state("networkidle", timeout=15000)
    page.wait_for_timeout(2000)
    log.info("Owner Time calendar should now be visible.")


def parse_calendar_dates(page):
    """
    Parse available dates (white boxes with teal border) from the 2-month calendar view.
    Available dates have no hatching and have a border — we identify them by class.
    """
    available = []

    # Get all day cells
    # Available = not unavailable, not empty
    # The calendar renders months with day numbers inside td or div elements
    # We look for cells that are "available" (white/teal border) vs "unavailable" (hatched)
    
    # Try multiple selector strategies
    selectors = [
        "td.available:not(.unavailable)",
        "td[class*='available']:not([class*='unavailable'])",
        ".calendar-day.available",
        "td:not(.unavailable):not(.disabled):not(.empty) > div[data-date]",
        "[data-date]:not(.unavailable)",
    ]

    cells = []
    for sel in selectors:
        cells = page.query_selector_all(sel)
        if cells:
            log.info(f"Found {len(cells)} cells with selector: {sel}")
            break

    if not cells:
        # Fallback: dump all td elements and their classes for debugging
        all_tds = page.query_selector_all("td")
        log.info(f"No cells found with specific selectors. Total td elements: {len(all_tds)}")
        for td in all_tds[:20]:
            log.info(f"  td class='{td.get_attribute('class')}' data-date='{td.get_attribute('data-date')}' text='{td.inner_text().strip()}'")

    for cell in cells:
        date_str = (
            cell.get_attribute("data-date") or
            cell.get_attribute("data-day") or
            cell.get_attribute("title")
        )
        if not date_str:
            # Try child elements
            child = cell.query_selector("[data-date]")
            if child:
                date_str = child.get_attribute("data-date")

        if date_str:
            for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%m-%d-%Y"):
                try:
                    dt = datetime.strptime(date_str.strip(), fmt)
                    available.append(dt.date())
                    break
                except ValueError:
                    continue

    return available


def scrape_all_available_dates(page):
    all_available = []

    # Scrape current 2-month view, then advance month by month
    for i in range(NEXT_MONTH_CLICKS + 1):
        log.info(f"Scraping calendar view {i + 1} of {NEXT_MONTH_CLICKS + 1}...")
        page.screenshot(path=f"calendar_view_{i}.png")
        
        dates = parse_calendar_dates(page)
        log.info(f"  Found {len(dates)} available dates in this view.")
        all_available.extend(dates)

        if i < NEXT_MONTH_CLICKS:
            try:
                next_btn = page.query_selector("text=Next Month, [aria-label*='next'], .next-month, button[class*='next']")
                if next_btn:
                    next_btn.click()
                    page.wait_for_timeout(2000)
                else:
                    log.warning("Could not find Next Month button.")
                    break
            except PlaywrightTimeout:
                log.warning("Timeout clicking Next Month.")
                break

    unique_dates = sorted(set(all_available))
    log.info(f"Total unique available dates found: {len(unique_dates)}")
    return unique_dates


def dates_to_ical(available_dates):
    """
    Airbnb iCal import treats events as BLOCKED dates.
    So we block everything EXCEPT the available dates.
    """
    cal = Calendar()
    cal.add("prodid", "-//ResortCom UVCI Airbnb Sync//EN")
    cal.add("version", "2.0")

    today = date.today()
    end_date = today + timedelta(days=365)
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
        page = browser.new_page(viewport={"width": 1280, "height": 900})

        try:
            login(page)
            go_to_reservation_search(page)
            click_owner_time_calendar(page)
            available_dates = scrape_all_available_dates(page)

            if not available_dates:
                log.warning("No available dates found — check screenshots in artifacts.")
            else:
                ical_data = dates_to_ical(available_dates)
                with open(OUTPUT_FILE, "wb") as f:
                    f.write(ical_data)
                log.info(f"✅ calendar.ics written with {len(available_dates)} available dates.")

            with open("available_dates.json", "w") as f:
                json.dump([str(d) for d in available_dates], f, indent=2)

        except Exception as e:
            page.screenshot(path="error_state.png")
            log.error(f"Script failed: {e}")
            raise
        finally:
            browser.close()


if __name__ == "__main__":
    main()
