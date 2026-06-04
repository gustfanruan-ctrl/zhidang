import sys; sys.path.insert(0, "/app/backend")
from playwright.sync_api import sync_playwright
import json
from pathlib import Path
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
print("Nodes:", len(bi_data.get("node_info", [])), "Edges:", len(bi_data.get("edge_info", [])))

# Cache the patched HTML (only need to do once)
html_path = Path("/app/static/pm_patched.html")
if not html_path.exists():
    async def fetch_html():
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.get("https://crm.finereporthelp.com/WebReport/power_map/powerMap_v3.13.html")
            return r.text
    html = asyncio.run(fetch_html())
    old = "success: function(result){\n                    var obj = eval('(' + result + ')');\n                    switchVersion(ver_type,obj,self);"
    new = "success: function(result){\n                    var obj = window.__GRAPH_DATA__;\n                    switchVersion(ver_type,obj,self);"
    html = html.replace(old, new)
    html_path.write_text(html, encoding="utf-8")
    print("Patched HTML saved")
else:
    print("Using cached patched HTML")

bi_str = json.dumps(bi_data, ensure_ascii=False)

with sync_playwright() as p:
    b = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-gpu"])
    ctx = b.new_context(viewport={"width": 1920, "height": 1080})
    ctx.add_cookies([{
        "name": "fine_auth_token", "value": token,
        "domain": "crm.finereporthelp.com", "path": "/"
    }])
    page = ctx.new_page()
    
    page.add_init_script("window.__GRAPH_DATA__ = " + bi_str + ";")

    def handle_route(route):
        if "powerMap_v3.13.html" in route.request.url and "getInfo" not in route.request.url:
            route.fulfill(status=200, headers={"Content-Type": "text/html;charset=UTF-8"}, body=html_path.read_text())
        else:
            route.continue_()

    page.route("**/*", handle_route)
    page.goto("https://crm.finereporthelp.com/WebReport/power_map/powerMap_v3.13.html?com_id=test",
              wait_until="networkidle", timeout=30000)
    page.wait_for_timeout(5000)

    # Verify nodes rendered
    try:
        n = page.evaluate("document.querySelectorAll('.x6-node').length")
        print("X6 nodes:", n)
    except:
        print("Could not count nodes")

    png = page.screenshot(type="png", full_page=False)
    out = "/app/static/pm_sandbox_demo.png"
    with open(out, "wb") as f:
        f.write(png)
    print("Screenshot:", out, len(png), "bytes")
    b.close()
