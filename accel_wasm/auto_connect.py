# auto_connect.py
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError
import time
import os
import sys

DASHBOARD_URL = os.environ.get("WILI_URL", "http://localhost:7001/")
# Use a persistent Chrome profile so WebSerial permission is remembered
USER_DATA_DIR = os.environ.get("PLAYWRIGHT_CHROME_PROFILE", "/tmp/playwright-chrome")
CHROME_PATH = os.environ.get(
    "CHROME_PATH",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
)

def log(msg):
    print(f"[auto] {msg}", flush=True)

def wait_for_text(page, selector, substr, timeout_ms=4000):
    """Wait until element contains target substring."""
    deadline = time.time() + (timeout_ms/1000)
    while time.time() < deadline:
        try:
            txt = page.inner_text(selector)
            if substr.lower() in (txt or "").lower():
                return True
        except Exception:
            pass
        time.sleep(0.2)
    return False

def auto_connect():
    with sync_playwright() as pw:
        # Prefer channel="chrome" if available; otherwise use executable_path
        try:
            browser = pw.chromium.launch_persistent_context(
                user_data_dir=USER_DATA_DIR,
                channel="chrome",
                headless=False,
                args=[
                    "--use-fake-ui-for-media-stream",  # harmless; keeps prompts minimal
                ],
            )
        except Exception:
            # Fallback to explicit Chrome path
            browser = pw.chromium.launch_persistent_context(
                user_data_dir=USER_DATA_DIR,
                headless=False,
                executable_path=CHROME_PATH,
            )

        try:
            page = browser.new_page()
            page.goto(DASHBOARD_URL, wait_until="domcontentloaded")
            log("Opened dashboard ✅")

            # Click Connect Device
            page.wait_for_selector("#connectBtn", timeout=6000)
            page.click("#connectBtn")
            log("Clicked Connect Device 🚀")

            # If this is the first run, a system WebSerial chooser appears.
            # You must select your device manually ONCE.
            # After you’ve approved it once, Chrome will remember for this profile
            # and the next runs won’t show the dialog.

            # Wait a bit and check status line
            time.sleep(1.0)
            status = page.inner_text("#status")
            log(f"Status now: {status}")

            # Try to detect "Connected"
            if not wait_for_text(page, "#status", "Connected", timeout_ms=8000):
                log("Did not detect 'Connected' yet — if this is your first run, approve the Serial chooser.")
                # Give you a moment to click the chooser manually
                try:
                    page.wait_for_timeout(8000)
                except PWTimeoutError:
                    pass

            # Optional: set g_range to 16384 (±2g)
            try:
                page.select_option("#grange", "16384")
                log("Set g_range to 16384 (±2g)")
            except Exception:
                log("Could not set g_range (dropdown not found). Skipping.")

            # Read key UI fields
            try:
                status = page.inner_text("#status")
                motion = page.inner_text("#motionStatus")
                kv_ema = page.inner_text("#kvEMA")
                kv_mag = page.inner_text("#kvMag")
                kv_xyz = page.inner_text("#kvXYZ")
            except Exception:
                status = motion = kv_ema = kv_mag = kv_xyz = "(unavailable)"

            print("\n=== LIVE READOUT ===")
            print(f"Status     : {status}")
            print(f"Motion     : {motion}")
            print(f"EMA (m/s²) : {kv_ema}")
            print(f"|a|  (m/s²): {kv_mag}")
            print(f"X/Y/Z (m/s²): {kv_xyz}")
            print("====================\n")

            # Keep window open a moment so you can see it
            page.wait_for_timeout(2000)

        finally:
            # Close the entire persistent context (Chrome instance)
            browser.close()

if __name__ == "__main__":
    try:
        auto_connect()
    except KeyboardInterrupt:
        sys.exit(130)
