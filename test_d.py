import sys; sys.path.insert(0, "/app/backend")
from playwright.sync_api import sync_playwright
import json, time
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
print("Data:", len(bi_str), "chars")

with sync_playwright() as p:
    b = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-gpu"])
    ctx = b.new_context(viewport={"width": 1920, "height": 1080})

    ctx.add_cookies([{
        "name": "fine_auth_token",
        "value": token,
        "domain": "crm.finereporthelp.com",
        "path": "/"
    }])

    page = ctx.new_page()
    errs = []
    page.on("pageerror", lambda e: errs.append(str(e)[:200]))

    # DELAYED interception - wait 3 seconds before fulfilling
    getinfo_intercepted = [False]

    def handle_route(route):
        if "getInfo" in route.request.url:
            if not getinfo_intercepted[0]:
                getinfo_intercepted[0] = True
                print("INTERCEPT getInfo - delaying 3s...")
                # Let page initialize first, then fulfill
                def fulfill():
                    print("Fulfilling getInfo now")
                    route.fulfill(
                        status=200,
                        headers={"Content-Type": "text/html;charset=UTF-8"},
                        body=bi_str
                    )
                # Use asyncio in sync context
                import asyncio as aio
                loop = aio.new_event_loop()
                loop.call_later(3, fulfill)
                # But we can't use asyncio in sync playwright... 
                # Alternative: use threading timer
                import threading
                threading.Timer(3.0, fulfill).start()
            else:
                route.continue_()
        else:
            route.continue_()

    page.route("**/*", handle_route)

    print("Loading page...")
    page.goto(
        "https://crm.finereporthelp.com/WebReport/power_map/powerMap_v3.13.html?com_id=test",
        wait_until="domcontentloaded", timeout=20000
    )
    print("Page loaded, waiting for delayed fulfillment...")
    page.wait_for_timeout(10000)

    for e in errs:
        print("ERR:", e[:150])

    png = page.screenshot(type="png", full_page=False)
    with open("/app/static/x6_delayed.png", "wb") as f:
        f.write(png)
    print("Screenshot:", len(png), "bytes")
    b.close()
