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
            params={"prj_id": "9321225a-a435-4aa4-a7c7-50a66076fa57", "prj_type": "company",
                    "ver_info": "548f02a7-2a36-4709-b910-eaf717e7cbf7"},
            headers={"Authorization": "Bearer " + token}
        )
        return r.json()

bi_data = asyncio.run(fetch())
bi_str = json.dumps(bi_data, ensure_ascii=False)
print("JSON:", len(bi_str), "chars")

with sync_playwright() as p:
    b = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-gpu"])
    page = b.new_page()
    result = page.evaluate("""
        (s) => {
            try {
                var obj = eval("(" + s + ")");
                return JSON.stringify({
                    type: typeof obj,
                    keys: Object.keys(obj),
                    node_info: obj.node_info ? obj.node_info.length : 'MISSING',
                    edge_info: obj.edge_info ? obj.edge_info.length : 'MISSING'
                });
            } catch(e) {
                return JSON.stringify({error: e.toString()});
            }
        }
    """, bi_str)
    print("Eval:", result)
    b.close()
