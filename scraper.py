"""
ResortCom (UVCI) → Airbnb Calendar Sync
Now with correct Select2 dropdown handling and daterangepicker calendar scraping.
"""

import os
import json
import logging
from datetime import datetime, timedelta, date
from playwright.sync_api import sync_playwright
from icalendar import Calendar, Event

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

USERNAME = os.environ["RESORTCOM_USERNAME"]
PASSWORD = os.environ["RESORTCOM_PASSWORD"]
OUTPUT_FILE = "calendar.ics"
NEXT_MONTH_CLICKS = 10  # Click next enough times to cover 12 months


def snap(page, filename, msg=""):
    page.screenshot(path=filename, full_page=True)
    log.info(f"📸 {filename} | {page.url} | {msg}")


def dismiss_popups(page):
    try:
        accept = page.query_selector("button:has-text('Accept')")
        if accept and accept.is_visible():
            accept.click()
            page.wait_for_timeout(2000)
            log.info("Dismissed cookie popup.")
    except Exception:
        pass


def login(page):
    log.info("--- STEP 1: Login ---")
    page.goto("https://reservation.resortcom.com/index", wait_until="domcontentloaded")
    page.wait_for_timeout(5000)
    page.fill('input[placeholder="User Name"]', USERNAME)
    page.fill('input[placeholder="Password"]', PASSWORD)
    page.click('button:has-text("Login")')
    page.wait_for_timeout(8000)
    log.info(f"After login URL: {page.url}")


def go_to_make_reservation(page):
    log.info("--- STEP 2: Make Reservation ---")
    dismiss_popups(page)
    page.wait_for_timeout(1000)
    page.click("text=MAKE RESERVATION")
    page.wait_for_timeout(8000)
    dismiss_popups(page)
    snap(page, "04_reservation_page.png")


def fill_search_form(page):
    log.info("--- STEP 3: Fill search form using Select2 JS ---")

    # Select2 dropdowns can't be clicked normally — use JavaScript to set values
    # The select IDs are: reco-member-index-search-region, -resort, -unittype

    # Step 1: Select Cabo San Lucas via JS
    log.info("Setting Destination: Cabo San Lucas...")
    page.evaluate("""() => {
        const sel = document.getElementById('reco-member-index-search-region');
        if (!sel) { console.error('Region select not found'); return; }
        // Set the value using Select2's API
        const option = Array.from(sel.options).find(o => o.value === 'Cabo San Lucas');
        if (option) option.selected = true;
        // Trigger Select2 to recognize the change
        const event = new Event('change', { bubbles: true });
        sel.dispatchEvent(event);
        // Also try jQuery trigger if available
        if (window.jQuery) {
            window.jQuery('#reco-member-index-search-region').trigger('change');
        }
    }""")
    page.wait_for_timeout(4000)
    snap(page, "05_dest_selected.png", "After selecting Cabo San Lucas")

    # Step 2: Wait for resorts to load, then select Villa Del Arco
    log.info("Setting Resort: Villa Del Arco...")
    page.wait_for_timeout(3000)  # Wait for resort options to populate

    # Log what resort options are available
    resort_options = page.evaluate("""() => {
        const sel = document.getElementById('reco-member-index-search-resort');
        if (!sel) return 'NOT FOUND';
        return Array.from(sel.options).map(o => ({value: o.value, text: o.text}));
    }""")
    log.info(f"Resort options available: {resort_options}")

    page.evaluate("""() => {
        const sel = document.getElementById('reco-member-index-search-resort');
        if (!sel) return;
        const option = Array.from(sel.options).find(o => 
            o.value.includes('Villa Del Arco') || o.text.includes('Villa Del Arco') ||
            o.value.includes('Villa') || o.text.includes('Villa')
        );
        if (option) {
            option.selected = true;
            sel.dispatchEvent(new Event('change', { bubbles: true }));
            if (window.jQuery) window.jQuery('#reco-member-index-search-resort').trigger('change');
        }
    }""")
    page.wait_for_timeout(4000)
    snap(page, "06_resort_selected.png", "After selecting Villa Del Arco")

    # Step 3: Select One Bedroom
    log.info("Setting Unit Type: One Bedroom...")
    page.wait_for_timeout(2000)

    unit_options = page.evaluate("""() => {
        const sel = document.getElementById('reco-member-index-search-unittype');
        if (!sel) return 'NOT FOUND';
        return Array.from(sel.options).map(o => ({value: o.value, text: o.text}));
    }""")
    log.info(f"Unit type options available: {unit_options}")

    page.evaluate("""() => {
        const sel = document.getElementById('reco-member-index-search-unittype');
        if (!sel) return;
        const option = Array.from(sel.options).find(o => 
            o.text.includes('One Bedroom') || o.value.includes('One Bedroom') ||
            o.text.includes('1 Bedroom') || o.value.includes('1BR')
        );
        if (option) {
            option.selected = true;
            sel.dispatchEvent(new Event('change', { bubbles: true }));
            if (window.jQuery) window.jQuery('#reco-member-index-search-unittype').trigger('change');
        }
    }""")
    page.wait_for_timeout(3000)
    snap(page, "07_unit_selected.png", "After selecting One Bedroom")

    # Step 4: Set dates via the Check In input
    checkin = (date.today() + timedelta(weeks=3)).strftime("%-m/%-d/%Y")
    checkout = (date.today() + timedelta(weeks=5)).strftime("%-m/%-d/%Y")
    log.info(f"Setting dates: {checkin} → {checkout}")

    checkin_input = page.query_selector('input[placeholder="Check In"]')
    checkout_input = page.query_selector('input[placeholder="Check Out"]')

    if checkin_input:
        checkin_input.click(click_count=3)
        page.wait_for_timeout(500)
        checkin_input.fill(checkin)
        page.keyboard.press("Tab")
        page.wait_for_timeout(1000)

    if checkout_input:
        checkout_input.click(click_count=3)
        page.wait_for_timeout(500)
        checkout_input.fill(checkout)
        page.keyboard.press("Tab")
        page.wait_for_timeout(1000)

    snap(page, "08_form_filled.png", "Form filled")

    # Check if search button is enabled
    search_enabled = page.evaluate("""() => {
        const btn = document.querySelector('button[type="submit"]');
        return btn ? !btn.disabled : false;
    }""")
    log.info(f"Search button enabled: {search_enabled}")

    # Click search
    log.info("Clicking SEARCH...")
    page.click('button[type="submit"]')
    page.wait_for_timeout(10000)
    snap(page, "09_search_results.png", "Search results")


def click_owner_time_calendar(page):
    log.info("--- STEP 4: Click Owner Time calendar icon ---")
    snap(page, "10_before_owner.png")

    # Log all buttons
    all_btns = page.query_selector_all("button")
    log.info(f"Buttons on page: {len(all_btns)}")
    for i, btn in enumerate(all_btns):
        log.info(f"  [{i}] text='{btn.inner_text().strip()[:40]}' class='{(btn.get_attribute('class') or '')[:60]}'")

    # Find calendar button near "Owner Time" text
    clicked = False
    for btn in all_btns:
        html = btn.inner_html().lower()
        cls = (btn.get_attribute("class") or "").lower()
        if "calendar" in html or "calendar" in cls or "fa-calendar" in html:
            log.info(f"Clicking calendar button: {btn.inner_html()[:80]}")
            btn.click()
            clicked = True
            break

    if not clicked and len(all_btns) > 0:
        log.warning("No calendar button found by class, clicking first button")
        all_btns[0].click()

    page.wait_for_timeout(8000)
    snap(page, "11_owner_calendar.png", "Owner Time calendar opened")


def scrape_calendar_months(page):
    """
    Scrape available dates from the daterangepicker calendar.
    Available cells have class 'available' but NOT 'off' (off = other month) 
    and NOT 'disabled'.
    The calendar shows month name + year in a select, and day numbers as td text.
    """
    log.info("--- STEP 5: Scrape calendar dates ---")
    all_available = []

    for i in range(NEXT_MONTH_CLICKS + 1):
        log.info(f"Scraping month view {i+1} of {NEXT_MONTH_CLICKS+1}...")
        snap(page, f"12_calendar_{i+1}.png")

        # Get current month and year from the calendar header selects
        month_year = page.evaluate("""() => {
            const monthSel = document.querySelector('.daterangepicker .monthselect');
            const yearSel = document.querySelector('.daterangepicker .yearselect');
            if (!monthSel || !yearSel) return null;
            return {
                month: parseInt(monthSel.value),
                year: parseInt(yearSel.value)
            };
        }""")
        log.info(f"  Calendar showing: {month_year}")

        if not month_year:
            log.warning("  Could not read month/year from calendar")
            break

        month = month_year["month"]
        year = month_year["year"]

        # Get all available day cells (class contains 'available', not 'off', not 'disabled')
        day_cells = page.evaluate("""() => {
            const tds = document.querySelectorAll('.daterangepicker td');
            const results = [];
            for (const td of tds) {
                const cls = td.className;
                const text = td.innerText.trim();
                if (cls.includes('available') && !cls.includes('off') && !cls.includes('disabled') && text) {
                    results.push({ text: text, cls: cls });
                }
            }
            return results;
        }""")

        log.info(f"  Available day cells: {day_cells}")

        for cell in day_cells:
            try:
                day = int(cell["text"])
                d = date(year, month, day)
                all_available.append(d)
            except (ValueError, TypeError):
                pass

        log.info(f"  → {len(day_cells)} available days in {month}/{year}")

        # Click next month arrow
        if i < NEXT_MONTH_CLICKS:
            clicked = page.evaluate("""() => {
                const next = document.querySelector('.daterangepicker th.next.available');
                if (next) { next.click(); return true; }
                return false;
            }""")
            if clicked:
                page.wait_for_timeout(2000)
            else:
                log.warning("  Next month button not found — stopping")
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
            available_dates = scrape_calendar_months(page)

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
