"""
ResortCom (UVCI) → Airbnb Calendar Sync
"""

import os
import json
import logging
from datetime import datetime, timedelta, date
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from icalendar import Calendar, Event

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

USERNAME = os.environ["RESORTCOM_USERNAME"]
PASSWORD = os.environ["RESORTCOM_PASSWORD"]
OUTPUT_FILE = "calendar.ics"
NEXT_MONTH_CLICKS = 5


def snap(page, filename, msg=""):
    page.screenshot(path=filename, full_page=True)
    log.info(f"📸 {filename} | {page.url} | {msg}")


def dismiss_popups(page):
    """Dismiss any cookie/privacy popups that might block clicks."""
    try:
        accept = page.query_selector("button:has-text('Accept'), button:has-text('accept'), button:has-text('OK')")
        if accept:
            accept.click()
            page.wait_for_timeout(2000)
            log.info("Dismissed cookie popup.")
    except Exception:
        pass


def login(page):
    log.info("--- STEP 1: Login ---")
    page.goto("https://reservation.resortcom.com/index", wait_until="domcontentloaded")
    page.wait_for_timeout(5000)
    snap(page, "01_login_page.png")

    page.fill('input[placeholder="User Name"]', USERNAME)
    page.fill('input[placeholder="Password"]', PASSWORD)
    snap(page, "02_credentials_filled.png")

    page.click('button:has-text("Login")')
    page.wait_for_timeout(8000)
    snap(page, "03_after_login.png")
    log.info(f"After login URL: {page.url}")


def go_to_make_reservation(page):
    log.info("--- STEP 2: Make Reservation ---")
    dismiss_popups(page)
    page.wait_for_timeout(1000)

    page.click("text=MAKE RESERVATION")
    page.wait_for_timeout(8000)
    dismiss_popups(page)
    snap(page, "04_reservation_page.png")


def select_dropdown(page, wrapper_index, option_text, screenshot_prefix):
    """Click a dropdown wrapper, wait for options, click the matching option."""
    log.info(f"Selecting '{option_text}' from dropdown {wrapper_index}...")

    wrappers = page.query_selector_all(".multiselect")
    log.info(f"  Found {len(wrappers)} multiselect wrappers")

    if len(wrappers) <= wrapper_index:
        log.warning(f"  Wrapper index {wrapper_index} not found!")
        return False

    wrappers[wrapper_index].click()
    page.wait_for_timeout(3000)
    snap(page, f"{screenshot_prefix}_open.png", f"Dropdown {wrapper_index} open")

    # Log all visible options
    options = page.query_selector_all(".multiselect__option span, .multiselect__element span")
    log.info(f"  Options visible: {[o.inner_text().strip() for o in options]}")

    # Find and click matching option
    for opt in options:
        text = opt.inner_text().strip()
        if option_text.lower() in text.lower():
            opt.click()
            page.wait_for_timeout(2000)
            snap(page, f"{screenshot_prefix}_selected.png", f"'{option_text}' selected")
            log.info(f"  ✅ Selected: '{text}'")
            return True

    log.warning(f"  ⚠️ Option '{option_text}' not found in dropdown!")
    snap(page, f"{screenshot_prefix}_failed.png", "Option not found")
    return False


def fill_search_form(page):
    log.info("--- STEP 3: Fill search form ---")
    dismiss_popups(page)

    # Select dropdowns in order
    select_dropdown(page, 0, "Cabo San Lucas", "05_dest")
    select_dropdown(page, 1, "Villa Del Arco", "06_resort")
    select_dropdown(page, 2, "One Bedroom", "07_room")

    # Fill in dates
    checkin = (date.today() + timedelta(weeks=3)).strftime("%-m/%-d/%Y")
    checkout = (date.today() + timedelta(weeks=5)).strftime("%-m/%-d/%Y")
    log.info(f"Setting dates: {checkin} → {checkout}")

    # Use the placeholder text to find the right inputs
    checkin_input = page.query_selector('input[placeholder="Check In"]')
    checkout_input = page.query_selector('input[placeholder="Check Out"]')

    if checkin_input:
        checkin_input.click(click_count=3)
        page.wait_for_timeout(500)
        checkin_input.fill(checkin)
        page.wait_for_timeout(500)
        log.info(f"  Set check-in: {checkin}")
    else:
        log.warning("  Check In input not found!")

    if checkout_input:
        checkout_input.click(click_count=3)
        page.wait_for_timeout(500)
        checkout_input.fill(checkout)
        page.wait_for_timeout(500)
        log.info(f"  Set check-out: {checkout}")
    else:
        log.warning("  Check Out input not found!")

    snap(page, "08_form_filled.png", "Form filled")

    # Check if Search button is enabled
    search_btn = page.query_selector("button:has-text('SEARCH'), button:has-text('Search')")
    if search_btn:
        is_disabled = search_btn.get_attribute("disabled")
        log.info(f"  Search button disabled: {is_disabled}")

    log.info("Clicking SEARCH...")
    page.click("button:has-text('SEARCH'), button:has-text('Search')")
    page.wait_for_timeout(10000)
    snap(page, "09_search_results.png", "Search results")


def click_owner_time_calendar(page):
    log.info("--- STEP 4: Click Owner Time calendar icon ---")
    dismiss_popups(page)
    snap(page, "10_before_owner_click.png")

    # Log all buttons
    all_btns = page.query_selector_all("button")
    log.info(f"Buttons on page: {len(all_btns)}")
    for i, btn in enumerate(all_btns):
        log.info(f"  [{i}] text='{btn.inner_text().strip()[:40]}' class='{(btn.get_attribute('class') or '')[:60]}'")

    # Find Owner Time section then get its calendar button
    # Strategy: find the text "Owner Time", then find the nearest button
    owner_section = page.query_selector("text=Owner Time")
    if owner_section:
        log.info("Found 'Owner Time' text on page")
        # Get parent container and find buttons within it
        parent = page.evaluate("""() => {
            const el = Array.from(document.querySelectorAll('*')).find(e => e.innerText && e.innerText.trim() === 'Owner Time');
            if (!el) return null;
            // Walk up to find a container with buttons
            let p = el.parentElement;
            for (let i = 0; i < 5; i++) {
                if (p && p.querySelectorAll('button').length > 0) break;
                p = p ? p.parentElement : null;
            }
            return p ? p.innerHTML : null;
        }""")
        log.info(f"Owner Time parent HTML: {str(parent)[:300]}")

    # Click first calendar icon button
    clicked = False
    for btn in all_btns:
        html = btn.inner_html().lower()
        cls = (btn.get_attribute("class") or "").lower()
        aria = (btn.get_attribute("aria-label") or "").lower()
        if "calendar" in html or "calendar" in cls or "calendar" in aria or "fa-calendar" in html:
            log.info(f"  Clicking calendar button [{all_btns.index(btn)}]: {btn.inner_html()[:80]}")
            btn.click()
            clicked = True
            break

    if not clicked:
        log.warning("No calendar button found! Trying first button...")
        if all_btns:
            all_btns[0].click()

    page.wait_for_timeout(8000)
    snap(page, "11_owner_calendar.png", "After clicking Owner Time calendar")


def parse_calendar_dates(page):
    """Extract available dates — white cells with teal border, no hatching."""
    available = []
    all_tds = page.query_selector_all("td")
    skip_keywords = ["unavailable", "disabled", "empty", "other-month", "blocked", "past"]

    for td in all_tds:
        cls = (td.get_attribute("class") or "").lower()
        data_date = td.get_attribute("data-date") or ""

        if any(kw in cls for kw in skip_keywords):
            continue

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
    log.info("--- STEP 5: Scrape calendar dates ---")
    all_available = []

    for i in range(NEXT_MONTH_CLICKS + 1):
        log.info(f"Calendar view {i+1} of {NEXT_MONTH_CLICKS+1}...")
        snap(page, f"12_calendar_{i+1}.png")

        # Log all td classes to debug date parsing
        all_tds = page.query_selector_all("td")
        log.info(f"  Total td elements: {len(all_tds)}")
        for td in all_tds[:10]:
            log.info(f"    td class='{td.get_attribute('class')}' data-date='{td.get_attribute('data-date')}'")

        dates = parse_calendar_dates(page)
        log.info(f"  → {len(dates)} available dates found")
        all_available.extend(dates)

        if i < NEXT_MONTH_CLICKS:
            next_btn = (
                page.query_selector("text=Next Month") or
                page.query_selector("[aria-label*='next']") or
                page.query_selector(".next-month")
            )
            if next_btn:
                next_btn.click()
                page.wait_for_timeout(4000)
            else:
                log.warning("Next Month button not found — stopping.")
                break

    unique = sorted(set(all_available))
    log.info(f"Total unique available dates: {len(unique)}")
    return unique


def dates_to_ical(available_dates):
    log.info("--- STEP 6: Generate iCal ---")
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
                log.warning("⚠️  No available dates found — check screenshots.")
            else:
                ical_data = dates_to_ical(available_dates)
                with open(OUTPUT_FILE, "wb") as f:
                    f.write(ical_data)
                log.info(f"✅ calendar.ics written with {len(available_dates)} dates.")

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
