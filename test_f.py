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

async def fetch_data():
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

async def fetch_html():
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.get("https://crm.finereporthelp.com/WebReport/power_map/powerMap_v3.13.html")
        return r.text

bi_data = asyncio.run(fetch_data())
html = asyncio.run(fetch_html())
print("HTML:", len(html), "bytes")

# Patch the success callback
old = "success: function(result){\n                    var obj = eval('(' + result + ')');\n                    switchVersion(ver_type,obj,self);"
new = "success: function(result){\n                    var obj = window.__GRAPH_DATA__;\n                    switchVersion(ver_type,obj,self);"
html = html.replace(old, new)
print("Patched:", "OK" if old not in html else "FAILED")

bi_str = json.dumps(bi_data, ensure_ascii=False)

with sync_playwright() as p:
    b = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-gpu"])
    ctx = b.new_context(viewport={"width": 1920, "height": 1080})
    ctx.add_cookies([{
        "name": "fine_auth_token", "value": token,
        "domain": "crm.finereporthelp.com", "path": "/"
    }])
    page = ctx.new_page()
    errs = []
    page.on("pageerror", lambda e: errs.append(str(e)[:200]))

    # Inject data before ANY script runs
    page.add_init_script("window.__GRAPH_DATA__ = " + bi_str + ";")

    def handle_route(route):
        url = route.request.url
        # Intercept the HTML page request, not API calls
        if "powerMap_v3.13.html" in url and "getInfo" not in url:
            print("INTERCEPT HTML page, serving patched version")
            route.fulfill(
                status=200,
                headers={"Content-Type": "text/html;charset=UTF-8"},
                body=html
            )
        else:
            route.continue_()

    page.route("**/*", handle_route)

    page.goto(
        "https://crm.finereporthelp.com/WebReport/power_map/powerMap_v3.13.html?com_id=test",
        wait_until="networkidle", timeout=30000
    )
    page.wait_for_timeout(5000)
    print("Page loaded")

    for e in errs:
        print("ERR:", e[:150])

    png = page.screenshot(type="png", full_page=False)
    out = "/app/static/x6_final2.png"
    with open(out, "wb") as f:
        f.write(png)
    print("Screenshot:", out, len(png), "bytes")
    b.close()
