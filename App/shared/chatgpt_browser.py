"""Drives the real chatgpt.com web UI (not the API) with Playwright, reusing
the shop's own ChatGPT Plus account -- for the volume where paying per image
via the OpenAI API (image_enhancer.py) would cost far more per month than
the flat Plus subscription. Deliberately uses the machine's real installed
Edge (channel="msedge") instead of downloading a separate Chromium: a real,
already-trusted browser install is less likely to look like a bot than a
fresh headless Chromium fingerprint, and skips an extra ~150MB download.

Logging in happens once, manually, in a real visible window (login() below)
-- this code never sees or stores the account's password. Playwright's
persistent context then keeps that session (cookies/local storage) on disk
under paths.CHATGPT_BROWSER_PROFILE_DIR, the same way a real browser profile
would, so later calls reuse it without asking to log in again.
"""
from playwright.sync_api import sync_playwright

import paths

CHATGPT_URL = "https://chatgpt.com/"


def login_interactive() -> None:
    """Opens a real, visible Edge window on chatgpt.com for the user to log
    into by hand. Blocks until they close that window themselves."""
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            paths.CHATGPT_BROWSER_PROFILE_DIR, channel="msedge", headless=False,
            viewport={"width": 1280, "height": 900},
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(CHATGPT_URL)
        # Blocks until the user closes the window (or the whole context) --
        # there's no reliable "logged in" DOM signal to poll for that isn't
        # sensitive to the page's own redesigns, and closing the window is a
        # clear, unambiguous "I'm done" signal from the person doing it.
        page.wait_for_event("close", timeout=0)
        context.close()
