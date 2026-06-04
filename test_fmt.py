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

# Test multiple response formats
bi_str = json.dumps(bi_data, ensure_ascii=False)

# Format 1: Wrap in parentheses for eval
eval_str = "(" + bi_str + ")"

# Format 2: JSONP callback
jsonp_str = "callback(" + bi_str + ")"

# Format 3: Raw assignment
raw_str = "window.__INJECTED_DATA__ = " + bi_str + ";"

for label, body in [("eval", eval_str), ("jsonp", jsonp_str), ("raw", raw_str)]:
    print("--- Testing %s (%d chars) ---" % (label, len(body)))
    
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-gpu"])
        ctx = b.new_context(viewport={"width": 1920, "height": 1080})
        page = ctx.new_page()

        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))

        def handle_route(route):
            if "getInfo" in route.request.url:
                print("  INTERCEPT:", route.request.url[-80:])
                route.fulfill(
                    status=200,
                    content_type="text/html;charset=UTF-8",
                    body=body
                )
            else:
                route.continue_()

        page.route("**/*", handle_route)
        page.goto(
            "https://crm.finereporthelp.com/WebReport/power_map/powerMap_v3.13.html?com_id=test",
            wait_until="domcontentloaded", timeout=20000
        )
        page.wait_for_timeout(8000)

        try:
            nodes = page.evaluate("document.querySelectorAll('.x6-node').length")
        except:
            nodes = 0
        print("  Nodes:", nodes, "Errors:", len(errors))
        if errors:
            print("  First error:", errors[0][:100])
        b.close()
