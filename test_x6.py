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
print("Data:", len(bi_str), "chars")

with sync_playwright() as p:
    b = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-gpu"])
    ctx = b.new_context(viewport={"width": 1920, "height": 1080})
    page = ctx.new_page()

    console_msgs = []
    page.on("console", lambda msg: console_msgs.append("[%s] %s" % (msg.type, msg.text)))
    page.on("pageerror", lambda err: console_msgs.append("[ERR] " + str(err)))

    # Navigate to blank page first, then set content manually
    # OR: intercept and provide proper data
    
    # Strategy: intercept ALL getInfo calls and return raw text/html
    def handle_route(route):
        if "getInfo" in route.request.url:
            print("INTERCEPT getInfo:", route.request.url.split("?")[-1][:60])
            route.fulfill(
                status=200,
                headers={"Content-Type": "text/html;charset=UTF-8"},
                body=bi_str
            )
        else:
            route.continue_()

    page.route("**/*", handle_route)
    
    # Navigate
    page.goto(
        "https://crm.finereporthelp.com/WebReport/power_map/powerMap_v3.13.html?com_id=test",
        wait_until="domcontentloaded", timeout=20000
    )
    
    # Wait for graph to potentially render
    print("Waiting for X6...")
    try:
        page.wait_for_selector(".x6-node", timeout=15000)
        node_count = page.evaluate("document.querySelectorAll('.x6-node').length")
        print("X6 nodes appeared:", node_count)
    except:
        print("No X6 nodes found")
    
    # Print console
    print("--- Console (%d) ---" % len(console_msgs))
    for m in console_msgs[-15:]:
        print(m)
    
    # Screenshot
    png = page.screenshot(type="png", full_page=False)
    out = "/app/static/x6_final.png"
    with open(out, "wb") as f:
        f.write(png)
    print("Saved:", out, len(png), "bytes")
    b.close()
