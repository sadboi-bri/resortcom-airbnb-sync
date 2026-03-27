"""
ResortCom (UVCI) → Airbnb Calendar Sync
DEBUG VERSION - dumps full dropdown HTML to understand structure
"""

import os
import json
import logging
from datetime import datetime, timedelta, date
from playwright.sync_api import sync_playwright

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

USERNAME = os.environ["RESORTCOM_USERNAME"]
PASSWORD = os.environ["RESORTCOM_PASSWORD"]


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

    # Dump the FULL HTML of the search form area
    form_html = page.evaluate("""() => {
        // Get the search bar container
        const form = document.querySelector('.multiselect') 
                  || document.querySelector('[class*="search"]')
                  || document.querySelector('[class*="filter"]');
        if (!form) return 'NO FORM FOUND';
        // Walk up to get the full search bar
        let parent = form.parentElement;
        for (let i = 0; i < 3; i++) {
            if (parent && parent.querySelectorAll('.multiselect').length >= 2) break;
            parent = parent ? parent.parentElement : null;
        }
        return parent ? parent.outerHTML : form.outerHTML;
    }""")

    with open("form_html_debug.html", "w") as f:
        f.write(form_html)
    log.info(f"Form HTML saved ({len(form_html)} chars)")
    log.info(f"Form HTML preview: {form_html[:2000]}")

    # Also log every multiselect element's full outer HTML
    multis = page.query_selector_all(".multiselect")
    log.info(f"Found {len(multis)} .multiselect elements")
    for i, m in enumerate(multis):
        html = m.evaluate("e => e.outerHTML")
        log.info(f"  Multiselect [{i}] HTML: {html[:500]}")

    # Try clicking first multiselect and dump what appears
    log.info("Clicking first multiselect...")
    if multis:
        multis[0].click()
        page.wait_for_timeout(3000)
        snap(page, "05_after_first_click.png", "After clicking first dropdown")

        # What appeared after clicking?
        visible_options = page.evaluate("""() => {
            const opts = document.querySelectorAll('.multiselect__option, .multiselect__element, [class*="option"]');
            return Array.from(opts).map(o => ({
                class: o.className,
                text: o.innerText.trim(),
                visible: o.offsetParent !== null
            }));
        }""")
        log.info(f"Options after click: {json.dumps(visible_options[:20], indent=2)}")

        # Also dump full page HTML at this point
        with open("after_click_debug.html", "w") as f:
            f.write(page.content())
        log.info("Full page HTML after click saved to after_click_debug.html")


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})

        try:
            login(page)
            go_to_make_reservation(page)
            log.info("✅ Debug complete — check logs and screenshots.")

        except Exception as e:
            page.screenshot(path="error_state.png", full_page=True)
            log.error(f"Script failed: {e}")
            raise
        finally:
            browser.close()


if __name__ == "__main__":
    main()
