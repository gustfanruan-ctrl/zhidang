import sys; sys.path.insert(0, "/app/backend")
from playwright.sync_api import sync_playwright
import json
from app.database import SessionLocal
from app.models import SystemConfig
from app.crypto_utils import decrypt_secret
import httpx, asyncio

db = SessionLocal()
cfg = db.get(SystemConfig, 1)
token = decrypt_secret(cfg.power_map_auth_token_encrypted)
db.close()

async def fetch():
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(
            "https://crm.finereporthelp.com/WebReport/decision/url/power_map/getInfo",
            params={
                "prj_id": "9321225a-a435-4aa4-a7c7-50a66076fa57",
                "prj_type": "company",
                "ver_info": "548f02a7-2a36-4709-b910-eaf717e7cbf7"
            },
            headers={"Authorization": "Bearer " + token}
        )
        return r.json()

bi_data = asyncio.run(fetch())
bi_str = json.dumps(bi_data, ensure_ascii=False)
print("Data:", len(bi_str), "chars, nodes:", len(bi_data.get("node_info",[])))

with sync_playwright() as p:
    b = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-gpu"])
    ctx = b.new_context(viewport={"width": 1920, "height": 1080})

    # Auth cookie
    ctx.add_cookies([{
        "name": "fine_auth_token",
        "value": token,
        "domain": "crm.finereporthelp.com",
        "path": "/"
    }])

    page = ctx.new_page()
    errs = []
    page.on("pageerror", lambda e: errs.append(str(e)[:200]))
    failed = []
    page.on("requestfailed", lambda r: failed.append(r.url[-100:]))

    # NO interception - let page load naturally with auth
    print("Loading page...")
    page.goto(
        "https://crm.finereporthelp.com/WebReport/power_map/powerMap_v3.13.html?com_id=9321225a-a435-4aa4-a7c7-50a66076fa57",
        wait_until="networkidle", timeout=30000
    )
    page.wait_for_timeout(3000)
    print("Page loaded")

    # Check what rendered naturally
    body = page.evaluate("document.body.innerText.substring(0, 300)")
    print("Body:", body[:100])
    print("Failed requests:", len(failed))
    for f in failed[:5]:
        print("  FAILED:", f)

    # Now inject our data via switchVersion (if available)
    # First expose the function if it's in a closure
    exposed = page.evaluate("""
        (function() {
            // Try to expose switchVersion via the page's context
            // The function might be accessible through some global
            var result = {exposed: false, hasGraph: false};
            
            // Check common patterns
            if (typeof switchVersion !== 'undefined') {
                window.__SV__ = switchVersion;
                result.exposed = true;
            }
            if (typeof graph !== 'undefined') {
                result.hasGraph = true;
            }
            return JSON.stringify(result);
        })()
    """)
    print("Exposed:", exposed)

    for e in errs:
        print("ERR:", e[:150])

    png = page.screenshot(type="png", full_page=False)
    with open("/app/static/x6_auth2.png", "wb") as f:
        f.write(png)
    print("Screenshot:", len(png), "bytes")
    b.close()
