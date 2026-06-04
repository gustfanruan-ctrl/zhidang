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

with sync_playwright() as p:
    b = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-gpu"])
    ctx = b.new_context(viewport={"width": 1920, "height": 1080})
    page = ctx.new_page()

    msgs = []
    page.on("console", lambda m: msgs.append("[%s] %s" % (m.type, m.text)))

    # Intercept and log what happens
    def handle_route(route):
        if "getInfo" in route.request.url:
            print("INTERCEPT getInfo")
            # Return the EXACT same format as real BI server
            route.fulfill(
                status=200,
                headers={
                    "Content-Type": "text/html;charset=UTF-8",
                    "X-XSS-Protection": "1; mode=block",
                    "Content-Security-Policy": "object-src 'self'",
                    "Cache-Control": "no-cache",
                    "Pragma": "no-cache"
                },
                body=bi_str
            )
        else:
            route.continue_()

    page.route("**/*", handle_route)

    # Before loading page, inject AJAX interceptor
    page.add_init_script("""
        // Override XMLHttpRequest to log responses
        var origOpen = XMLHttpRequest.prototype.open;
        XMLHttpRequest.prototype.open = function(method, url) {
            this._url = url;
            return origOpen.apply(this, arguments);
        };
        var origSend = XMLHttpRequest.prototype.send;
        XMLHttpRequest.prototype.send = function(body) {
            var self = this;
            if (self._url && self._url.indexOf('getInfo') > -1) {
                self.addEventListener('load', function() {
                    console.log('XHR getInfo response type:', typeof self.responseText);
                    console.log('XHR getInfo first 100:', self.responseText.substring(0, 100));
                    try {
                        var parsed = JSON.parse(self.responseText);
                        console.log('XHR getInfo parsed keys:', Object.keys(parsed).join(','));
                    } catch(e) {
                        console.log('XHR getInfo parse error:', e.toString());
                    }
                });
            }
            return origSend.apply(this, arguments);
        };
    """)

    page.goto(
        "https://crm.finereporthelp.com/WebReport/power_map/powerMap_v3.13.html?com_id=test",
        wait_until="domcontentloaded", timeout=20000
    )
    page.wait_for_timeout(8000)

    try:
        nodes = page.evaluate("document.querySelectorAll('.x6-node').length")
        print("X6 nodes:", nodes)
    except:
        print("Node check failed")

    print("--- Console ---")
    for m in msgs:
        if "getInfo" in m.lower() or "xhr" in m.lower() or "err" in m.lower() or "undefined" in m.lower():
            print(m)
    
    png = page.screenshot(type="png", full_page=False)
    with open("/app/static/x6_patched.png", "wb") as f:
        f.write(png)
    print("Screenshot:", len(png), "bytes")
    b.close()
