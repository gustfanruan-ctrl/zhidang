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
print("Data nodes:", len(bi_data.get("node_info", [])))

with sync_playwright() as p:
    b = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-gpu"])
    ctx = b.new_context(viewport={"width": 1920, "height": 1080})
    page = ctx.new_page()

    msgs = []
    page.on("console", lambda m: msgs.append("[%s] %s" % (m.type, m.text)))
    page.on("pageerror", lambda e: msgs.append("[ERR] " + str(e)))

    page.goto(
        "https://crm.finereporthelp.com/WebReport/power_map/powerMap_v3.13.html?com_id=test",
        wait_until="domcontentloaded", timeout=20000
    )
    page.wait_for_timeout(3000)
    print("Page loaded")

    # Pass data as argument (safe, no string injection)
    result = page.evaluate("""
        (data) => {
            try {
                var self = {};
                window.switchVersion=switchVersion; switchVersion('company', data, self);
                return JSON.stringify({ok: true, nodes: document.querySelectorAll('.x6-node').length});
            } catch(e) {
                return JSON.stringify({error: e.toString()});
            }
        }
    """, bi_data)
    print("Inject result:", result)

    page.wait_for_timeout(3000)
    try:
        n = page.evaluate("() => document.querySelectorAll('.x6-node').length")
        print("X6 nodes:", n)
    except Exception as e:
        print("Count error:", e)

    png = page.screenshot(type="png", full_page=False)
    out = "/app/static/x6_inject3.png"
    with open(out, "wb") as f:
        f.write(png)
    print("Saved:", len(png), "bytes")

    for m in msgs[-10:]:
        print(m)
    b.close()
