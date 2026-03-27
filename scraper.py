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
NEXT_MONTH_CLICKS = 5  # 6 views x 2 months = 12 months of data

WAIT = 8000   # 8 seconds — generous wait after every page load/click


def wait_and_screenshot(page, filename, msg=""):
    """Wait generously, then take a screenshot for debugging."""
    page.wait_for_timeout(WAIT)
    page.screenshot(path=filename, full_page=True)
    if msg:
        log.info(msg)
    log.info(f"Screenshot saved: {filename} | URL: {page.url}")


def login(page):
    log.info("--- STEP 1: Login ---")
    page.goto("https://reservation.resortcom.com/index", wait_until="domcontentloaded")
    wait_and_screenshot(page, "01_login_page.png", "Login page loaded.")

    page.fill('input[name="username"], input[type="text"]', USERNAME)
    page.fill('input[name="password"], input[type="password"]', PASSWORD)
    page.screenshot(path="02_credentials_filled.png")

    page.click('button[type="submit"], input[type="submit"]')
    wait_and_screenshot(page, "03_after_login.png", "Clicked login button.")


def go_to_make_reservation(page):
    log.info("--- STEP 2: Click Make Reservation ---")
    page.click("text=MAKE RESERVATION")
    wait_and_screenshot(page, "04_make_reservation_page.png", "Make Reservation page loaded.")


def fill_search_form(page):
    log.info("--- STEP 3: Fill search form ---")

    # Clear any pre-selected dropdowns
    try:
        close_buttons = page.query_selector_all(".multiselect__tag-icon")
        for btn in close_buttons:
            btn.click()
            page.wait_for_timeout(500)
    except Exception:
        pass

    # --- Destination: Cabo San Lucas ---
    log.info("Selecting Cabo San Lucas...")
    dest_inputs = page.query_selector_all(".multiselect__input")
    if dest_inputs:
        dest_inputs[0].click()
        page.wait_for_timeout(2000)
        page.screenshot(path="05a_dest_dropdown_open.png")
        page.click("text=Cabo San Lucas")
        page.wait_for_timeout(2000)
        page.screenshot(path="05b_dest_selected.png")

    # --- Resort: Villa Del Arco ---
    log.info("Selecting Villa Del Arco...")
    resort_inputs = page.query_selector_all(".multiselect__input")
    if len(resort_inputs) > 1:
        resort_inputs[1].click()
        page.wait_for_timeout(2000)
        page.screenshot(path="06a_resort_dropdown_open.png")
        page.click("text=Villa Del Arco")
        page.wait_for_timeout(2000)
        page.screenshot(path="06b_resort_selected.png")

    # --- Room type: One Bedroom ---
    log.info("Selecting One Bedroom...")
    room_inputs = page.query_selector_all(".multiselect__input")
    if len(room_inputs) > 2:
        room_inputs[2].click()
        page.wait_for_timeout(2000)
        page.screenshot(path="07a_room_dropdown_open.png")
        page.click("text=One Bedroom")
        page.wait_for_timeout(2000)
        page.screenshot(path="07b_room_selected.png")

    # --- Dates: 3 weeks from now ---
    checkin = (date.today() + timedelta(weeks=3)).strftime("%-m/%-d/%Y")
    checkout = (date.today() + timedelta(weeks=5)).strftime("%-m/%-d/%Y")
    log.info(f"Setting dates: {checkin} → {checkout}")

    date_inputs = page.query_selector_all("input[type='text']")
    for inp in date_inputs:
        placeholder = (inp.get_attribute("placeholder") or "").lower()
        if "check" in placeholder or "date" in placeholder or "from" in placeholder or "start" in placeholder:
            inp.triple_click()
            inp.type(checkin)
            page.wait_for_timeout(500)
            break

    date_inputs2 = page.query_selector_all("input[type='text']")
    for inp in date_inputs2:
        placeholder = (inp.get_attribute("placeholder") or "").lower()
        if "check out" in placeholder or "to" in placeholder or "end" in placeholder or "return" in placeholder:
            inp.triple_click()
            inp.type(checkout)
            page.wait_for_timeout(500)
            break

    page.screenshot(path="08_form_filled.png")

    # --- Click Search ---
    log.info("Clicking SEARCH...")
    page.click("text=SEARCH")
    wait_and_screenshot(page, "09_search_results.png", "Search results loaded.")


def click_owner_time_calendar(page):
    log.info("--- STEP 4: Click Owner Time calendar icon ---")

    # Log all buttons to find the right one
    all_btns = page.query_selector_all("button")
    log.info(f"Buttons on page: {len(all_btns)}")
    for i, btn in enumerate(all_btns):
        log.info(f"  [{i}] text='{btn.inner_text().strip()[:40]}' html='{btn.inner_html()[:60]}'")

    # The Owner Time calendar icon is the FIRST calendar button on the page
    clicked = False
    for btn in all_btns:
        html = btn.inner_html().lower()
        if "calendar" in html or "fa-calendar" in html or "cal" in html:
            log.info(f"Clicking calendar button: {btn.inner_html()[:80]}")
            btn.click()
            clicked = True
            break

    if not clicked:
        # Last resort: click by position — Owner Time calendar icon is button index 0 or 1
        if len(all_btns) > 0:
            log.info("Fallback: clicking first button on page")
            all_btns[0].click()

    wait_and_screenshot(page, "10_owner_calendar.png", "Owner Time calendar opened.")


def parse_calendar_dates(page):
    """Extract available dates from the 2-month calendar view."""
    available = []
    all_tds = page.query_selector_all("td")

    for td in all_tds:
        cls = (td.get_attribute("class") or "").lower()
        data_date = td.get_attribute("data-date") or ""
        text = td.inner_text().strip()

        # Skip unavailable/disabled/empty cells
        skip_keywords = ["unavailable", "disabled", "empty", "other-month", "blocked", "past"]
        if any(kw in cls for kw in skip_keywords):
            continue

        # Must have a date attribute or be a day number
        if data_date:
            for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%m-%d-%Y"):
                try:
                    dt = datetime.strptime(data_date.strip(), fmt)
                    available.append(dt.date())
                    break
                except ValueError:
                    continue

    return available


def scrape_all_available_dates(page):
    log.info("--- STEP 5: Scrape all available dates ---")
    all_available = []

    for i in range(NEXT_MONTH_CLICKS + 1):
        log.info(f"Scraping calendar view {i + 1} of {NEXT_MONTH_CLICKS + 1}...")
        page.screenshot(path=f"11_calendar_view_{i+1}.png", full_page=True)

        dates = parse_calendar_dates(page)
        log.info(f"  → {len(dates)} available dates found in this view.")
        all_available.extend(dates)

        if i < NEXT_MONTH_CLICKS:
            next_btn = (
                page.query_selector("text=Next Month") or
                page.query_selector("[aria-label*='next']") or
                page.query_selector(".next-month") or
                page.query_selector("button[class*='next']")
            )
            if next_btn:
                next_btn.click()
                page.wait_for_timeout(4000)  # Wait for calendar to update
            else:
                log.warning("Next Month button not found — stopping early.")
                break

    unique_dates = sorted(set(all_available))
    log.info(f"Total unique available dates: {len(unique_dates)}")
    return unique_dates


def dates_to_ical(available_dates):
    """
    Airbnb reads iCal as BLOCKED dates.
    So we block every day that is NOT in available_dates for the next 12 months.
    """
    log.info("--- STEP 6: Generating iCal file ---")
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
            go_to_make_reservation(page)
            fill_search_form(page)
            click_owner_time_calendar(page)
            available_dates = scrape_all_available_dates(page)

            if not available_dates:
                log.warning("⚠️  No available dates found — check screenshots in artifacts.")
            else:
                ical_data = dates_to_ical(available_dates)
                with open(OUTPUT_FILE, "wb") as f:
                    f.write(ical_data)
                log.info(f"✅ calendar.ics written with {len(available_dates)} available dates.")

            with open("available_dates.json", "w") as f:
                json.dump([str(d) for d in available_dates], f, indent=2)
            log.info("✅ available_dates.json written.")

        except Exception as e:
            page.screenshot(path="error_state.png", full_page=True)
            log.error(f"Script failed: {e}")
            raise
        finally:
            browser.close()


if __name__ == "__main__":
    main()
