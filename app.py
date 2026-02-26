import asyncio
import os
import re
from urllib.parse import quote
from flask import Flask, jsonify, request, send_from_directory
from playwright.async_api import async_playwright

# playwright_stealth — אופציונלי
try:
    from playwright_stealth import stealth_async
except ImportError:
    async def stealth_async(page):
        pass

# ── נתיב לתיקיית הפרויקט ─────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, static_folder=BASE_DIR)

@app.route("/")
def index():
    return send_from_directory(BASE_DIR, "index_19.html")

@app.route("/logo.png")
def logo():
    if os.path.exists(os.path.join(BASE_DIR, "logo.png")):
        return send_from_directory(BASE_DIR, "logo.png")
    return "", 404

# ════════════════════════════════════════════════════════════════
#  PLAYWRIGHT AGENT — חילוץ גוש/חלקה מ-GOVMAP
# ════════════════════════════════════════════════════════════════
async def _govmap_agent(city: str, street: str, number: str) -> dict:
    address_q = f"{street} {number}, {city}".strip().strip(",")
    result = {"gush": None, "chelka": None, "address": address_q, "source": None, "error": None}

    async with async_playwright() as pw:
        # ב-Render חייבים headless=True כי אין מסך
        browser = await pw.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
        )
        context = await browser.new_context(
            viewport={"width": 1440, "height": 900},
            locale="he-IL",
            timezone_id="Asia/Jerusalem"
        )
        page = await context.new_page()
        await stealth_async(page)

        try:
            govmap_url = "https://www.govmap.gov.il/?c=210000,610000&z=0"
            await page.goto(govmap_url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(3000)

            # חיפוש שדה כתובת
            search_input = page.locator("input#searchInput, input[placeholder*='חפש']").first
            if await search_input.is_visible():
                await search_input.fill(f"{street} {number}, {city}")
                await page.keyboard.press("Enter")
                await page.wait_for_timeout(4000)

                # שליפת טקסט מהדף
                body_text = await page.inner_text("body")
                current_url = page.url
                html_src = await page.content()

                gush, chelka, source = _extract(body_text, current_url, html_src)
                if gush and chelka:
                    result.update({"gush": gush, "chelka": chelka, "source": source})
                else:
                    result["error"] = "לא נמצאו גוש/חלקה. נסה כתובת מדויקת יותר."
        except Exception as exc:
            result["error"] = f"שגיאה: {str(exc)}"
        finally:
            await browser.close()
    return result

def _extract(body: str, url: str, html: str):
    g = re.search(r'גוש[:\s]+(\d+)', body)
    c = re.search(r'חלק[הא][:\s]+(\d+)', body)
    if g and c: return g.group(1), c.group(1), "text"
    
    g2 = re.search(r'GUSH=(\d+)', url, re.I)
    c2 = re.search(r'HELKA=(\d+)', url, re.I)
    if g2 and c2: return g2.group(1), c2.group(1), "url"
    
    return None, None, None

def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()

@app.route("/api/govmap", methods=["POST"])
def govmap_api():
    data = request.get_json(silent=True) or {}
    city = (data.get("city") or "").strip()
    street = (data.get("street") or "").strip()
    number = (data.get("number") or "").strip()
    if not city and not street:
        return jsonify({"error": "נא לספק עיר ורחוב"}), 400
    result = _run(_govmap_agent(city, street, number))
    return jsonify(result)

# ── נקודת כניסה מותאמת ל-RENDER ──────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
