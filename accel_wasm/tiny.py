import os, time
from google import genai
from google.genai import types
from google.genai.types import Content, Part
from playwright.sync_api import sync_playwright
from dotenv import load_dotenv; load_dotenv()

API_KEY = os.getenv("GOOGLE_API_KEY")
MODEL = "gemini-2.5-computer-use-preview-10-2025"

W, H = 1024, 640  # small viewport = fewer image tokens

def dx(x): return int(max(0, min(999, int(x))) / 1000 * W)
def dy(y): return int(max(0, min(999, int(y))) / 1000 * H)

def exec_calls(candidate, page):
    """Execute only the essentials: navigate, click_at, type_text_at, scroll_document."""
    fr = []
    for p in candidate.content.parts:
        fc = getattr(p, "function_call", None)
        if not fc: continue
        name, a = fc.name, dict(fc.args or {})
        # (Optional) honor require_confirmation if present
        sd = a.get("safety_decision")
        extra = {}
        if sd and sd.get("decision") == "require_confirmation":
            # Minimal HITL: skip if not explicitly allowed by user
            print("Safety requires confirmation:", sd.get("explanation", ""))
            return fr  # stop here in minimal demo

        try:
            if   name == "navigate":
                page.goto(str(a["url"]), wait_until="domcontentloaded")
            elif name == "click_at":
                page.mouse.click(dx(a["x"]), dy(a["y"]))
            elif name == "type_text_at":
                x, y = dx(a["x"]), dy(a["y"])
                page.mouse.click(x, y)
                if a.get("clear_before_typing", True):
                    page.keyboard.press("Meta+A"); page.keyboard.press("Backspace")
                t = a.get("text", "")
                if t: page.keyboard.type(t)
                if a.get("press_enter", True): page.keyboard.press("Enter")
            elif name == "scroll_document":
                direction = str(a.get("direction","down")).lower()
                page.mouse.wheel(0, 600 if direction == "down" else -600)
            # wait briefly for UI to settle
            try: page.wait_for_load_state("domcontentloaded", timeout=3000)
            except: pass
            time.sleep(0.4)
        finally:
            shot = page.screenshot(type="png")  # required each step
            fr.append(types.FunctionResponse(
                name=name,
                response={"url": page.url},
                parts=[types.FunctionResponsePart(
                    inline_data=types.FunctionResponseBlob(
                        mime_type="image/png", data=shot))]
            ))
    return fr

def run(goal, start_url):
    client = genai.Client(api_key=API_KEY)

    cfg = types.GenerateContentConfig(
        tools=[types.Tool(computer_use=types.ComputerUse(
            environment=types.Environment.ENVIRONMENT_BROWSER
        ))]
        # no thinking_config → fewer tokens
    )

    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=False)
    ctx = browser.new_context(viewport={"width": W, "height": H})
    page = ctx.new_page(); page.goto(start_url, wait_until="domcontentloaded")
    init_shot = page.screenshot(type="png")

    contents = [Content(role="user", parts=[
        Part(text=goal),                         # keep prompt SHORT
        Part.from_bytes(data=init_shot, mime_type="image/png"),
    ])]

    try:
        for _ in range(3):                      # tiny turn budget
            resp = client.models.generate_content(model=MODEL, contents=contents, config=cfg)
            cand = resp.candidates[0]
            contents.append(cand.content)

            # stop if no function calls (final text)
            if not any(getattr(p, "function_call", None) for p in cand.content.parts):
                break

            frs = exec_calls(cand, page)
            if not frs: break                   # minimal: abort on safety or none
            contents.append(Content(role="user", parts=[Part(function_response=f) for f in frs]))
    finally:
        browser.close(); pw.stop()

if __name__ == "__main__":
    # Example: open your dashboard and search the page (adjust goal as needed)
    run("Open http://localhost:7001/ and click Connect Device.", "http://localhost:7001/")
