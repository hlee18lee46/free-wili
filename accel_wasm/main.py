import os, sys, time, json, requests
from typing import Any, Dict, List, Tuple

from dotenv import load_dotenv
from termcolor import cprint

from google import genai
from google.genai import types
from google.genai.types import Content, Part

from playwright.sync_api import sync_playwright, Page, BrowserContext

# ===== Config =====
load_dotenv()
API_KEY = os.getenv("GOOGLE_API_KEY")
if not API_KEY:
    print("ERROR: set GOOGLE_API_KEY in .env"); sys.exit(1)

SCREEN_WIDTH  = int(os.getenv("VIEWPORT_WIDTH", "1440"))
SCREEN_HEIGHT = int(os.getenv("VIEWPORT_HEIGHT", "900"))
MODEL = "gemini-2.5-computer-use-preview-10-2025"

# ===== Helpers =====
def denorm_x(x: int) -> int: return int(max(0, min(999, int(x))) / 1000 * SCREEN_WIDTH)
def denorm_y(y: int) -> int: return int(max(0, min(999, int(y))) / 1000 * SCREEN_HEIGHT)

def ask_confirmation(explanation: str) -> bool:
    cprint("\nSAFETY: confirmation required", "red", attrs=["bold"])
    print(explanation)
    return input("Proceed? [y/N] ").strip().lower() in ("y","yes")

def wait_settle(page: Page, ms: int = 800):
    try: page.wait_for_load_state("domcontentloaded", timeout=5000)
    except: pass
    time.sleep(ms/1000)

# ===== Optional custom function (the model can call this) =====
# We expose a tool the model can invoke to hit your Flask endpoint: /speak-motion?text=...
def speak_motion(text: str) -> Dict[str, Any]:
    url = f"http://localhost:7001/speak-motion"
    try:
        r = requests.get(url, params={"text": text}, timeout=5)
        ok = (r.status_code == 200)
        return {"ok": ok, "status": r.status_code}
    except Exception as e:
        return {"ok": False, "error": str(e)}

# Build a FunctionDeclaration so Gemini can call it:
def build_custom_fns(client: genai.Client) -> List[types.FunctionDeclaration]:
    return [
        types.FunctionDeclaration.from_callable(client=client, callable=speak_motion),
    ]

# ===== Action executor =====
def execute_calls(candidate: types.Candidate, page: Page) -> List[Tuple[str, Dict[str, Any]]]:
    results: List[Tuple[str, Dict[str, Any]]] = []

    def click_at(a): page.mouse.click(denorm_x(a["x"]), denorm_y(a["y"]))
    def hover_at(a): page.mouse.move(denorm_x(a["x"]), denorm_y(a["y"]))
    def type_text_at(a):
        x,y = denorm_x(a["x"]), denorm_y(a["y"])
        text = a.get("text",""); press_enter = bool(a.get("press_enter", True))
        clear = bool(a.get("clear_before_typing", True))
        page.mouse.click(x,y)
        if clear:
            if sys.platform == "darwin": page.keyboard.press("Meta+A")
            else: page.keyboard.press("Control+A")
            page.keyboard.press("Backspace")
        if text: page.keyboard.type(text)
        if press_enter: page.keyboard.press("Enter")
    def key_combination(a):
        keys = str(a.get("keys","")).strip()
        if keys: page.keyboard.press(keys)
    def navigate(a): page.goto(str(a["url"]), wait_until="domcontentloaded")
    def go_back(): page.go_back()
    def go_forward(): page.go_forward()
    def wait_5_seconds(): time.sleep(5)
    def scroll_document(a):
        direction = str(a.get("direction","down")).lower()
        dx=0; dy=800 if direction in ("down","right") else -800
        if direction in ("left","right"): dx,dy = (800 if direction=="right" else -800), 0
        page.mouse.wheel(dx,dy)
    def scroll_at(a):
        page.mouse.move(denorm_x(a["x"]), denorm_y(a["y"]))
        direction = str(a.get("direction","down")).lower()
        mag = int(a.get("magnitude",800))
        dx=0; dy=mag if direction in ("down","right") else -mag
        if direction in ("left","right"): dx,dy = (mag if direction=="right" else -mag), 0
        page.mouse.wheel(dx,dy)
    def drag_and_drop(a):
        x1,y1 = denorm_x(a["x"]), denorm_y(a["y"])
        x2,y2 = denorm_x(a["destination_x"]), denorm_y(a["destination_y"])
        page.mouse.move(x1,y1); page.mouse.down()
        page.mouse.move(x2,y2, steps=20); page.mouse.up()

    for part in candidate.content.parts:
        fc = getattr(part, "function_call", None)
        if not fc: continue
        name, args = fc.name, dict(fc.args or {})
        print(f"→ {name} {json.dumps(args)}")

        # Safety
        extra = {}
        sd = args.get("safety_decision")
        if sd and str(sd.get("decision")) == "require_confirmation":
            if not ask_confirmation(sd.get("explanation","This action needs confirmation.")):
                print("Denied by user; stopping.")
                return results
            extra["safety_acknowledgement"] = "true"

        try:
            # Predefined UI actions
            if   name == "open_web_browser": pass
            elif name == "navigate":         navigate(args)
            elif name == "search":           page.goto("https://www.google.com", wait_until="domcontentloaded")
            elif name == "click_at":         click_at(args)
            elif name == "hover_at":         hover_at(args)
            elif name == "type_text_at":     type_text_at(args)
            elif name == "key_combination":  key_combination(args)
            elif name == "scroll_document":  scroll_document(args)
            elif name == "scroll_at":        scroll_at(args)
            elif name == "drag_and_drop":    drag_and_drop(args)
            elif name == "go_back":          go_back()
            elif name == "go_forward":       go_forward()
            elif name == "wait_5_seconds":   wait_5_seconds()
            # Custom user-defined function
            elif name == "speak_motion":
                # model passes {"text": "..."}; call Python function
                res = speak_motion(args.get("text","Motion detected — theft alert!"))
                extra.update({"custom_result": res})
            else:
                print(f"⚠️  Unimplemented: {name}")

            wait_settle(page)
            results.append((name, extra))
        except Exception as e:
            results.append((name, {"error": str(e), **extra}))
    return results

def to_function_responses(page: Page, results: List[Tuple[str, Dict[str, Any]]]) -> List[types.FunctionResponse]:
    shot = page.screenshot(type="png"); url = page.url
    frs = []
    for name, extra in results:
        payload = {"url": url, **(extra or {})}
        frs.append(types.FunctionResponse(
            name=name,
            response=payload,
            parts=[types.FunctionResponsePart(
                inline_data=types.FunctionResponseBlob(mime_type="image/png", data=shot)
            )]
        ))
    return frs

def run_agent(goal: str, start_url: str, turns: int = 8):
    client = genai.Client(api_key=API_KEY)

    # Tool config: Computer Use + custom functions
    custom_fns = build_custom_fns(client)
    config = types.GenerateContentConfig(
        tools=[
            types.Tool(computer_use=types.ComputerUse(
                environment=types.Environment.ENVIRONMENT_BROWSER,
                # Example: block something
                # excluded_predefined_functions=["drag_and_drop"]
            )),
            types.Tool(function_declarations=custom_fns),
        ],
        thinking_config=types.ThinkingConfig(include_thoughts=True),
    )

    # Browser host
    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=False)
    context = browser.new_context(viewport={"width": SCREEN_WIDTH, "height": SCREEN_HEIGHT})
    page = context.new_page()
    page.goto(start_url, wait_until="domcontentloaded")
    initial_shot = page.screenshot(type="png")

    contents: List[Content] = [Content(role="user", parts=[
        Part(text=goal),
        Part.from_bytes(data=initial_shot, mime_type="image/png"),
    ])]

    try:
        for i in range(turns):
            print(f"\n===== Turn {i+1}/{turns} =====")
            resp = client.models.generate_content(model=MODEL, contents=contents, config=config)
            cand = resp.candidates[0]
            contents.append(cand.content)

            has_fc = any(getattr(p, "function_call", None) for p in cand.content.parts)
            if not has_fc:
                final_text = " ".join([p.text for p in cand.content.parts if getattr(p, "text", None)])
                print("\nAgent finished:", final_text or "(no text)"); break

            results = execute_calls(cand, page)
            if not results:
                print("No actions executed (maybe denied). Stopping."); break

            frs = to_function_responses(page, results)
            contents.append(Content(role="user", parts=[Part(function_response=fr) for fr in frs]))

    finally:
        try: browser.close()
        except: pass
        try: pw.stop()
        except: pass

if __name__ == "__main__":
    goal = "Open http://localhost:7001/ then read the motion status. If motion is detected, call speak_motion with 'Motion detected — theft alert!'"
    start = "http://localhost:7001/"
    if len(sys.argv) > 1: goal = " ".join(sys.argv[1:])
    run_agent(goal, start)
