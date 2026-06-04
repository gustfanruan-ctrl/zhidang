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
    page.on("console", lambda m: msgs.append(m.text))
    page.on("pageerror", lambda e: msgs.append("PAGE_ERR: " + str(e)))

    # More aggressive interception - patch $.ajax BEFORE page loads
    page.add_init_script("""
        // Capture original $.ajax
        Object.defineProperty(window, '$', {
            get: function() { return window.__jQuery__; },
            set: function(val) {
                window.__jQuery__ = val;
                if (val && val.ajax) {
                    var origAjax = val.ajax;
                    val.ajax = function(options) {
                        if (options.url && options.url.indexOf('getInfo') > -1) {
                            var origSuccess = options.success;
                            options.success = function(result, status, xhr) {
                                console.log('AJAX getInfo success called!');
                                console.log('Result type:', typeof result);
                                console.log('Result length:', typeof result === 'string' ? result.length : 'N/A');
                                console.log('First 50:', typeof result === 'string' ? result.substring(0, 50) : JSON.stringify(result).substring(0, 50));
                                if (origSuccess) return origSuccess.apply(this, arguments);
                            };
                            var origError = options.error;
                            options.error = function(xhr, status, err) {
                                console.log('AJAX getInfo ERROR:', status, err);
                                if (origError) return origError.apply(this, arguments);
                            };
                        }
                        return origAjax.call(val, options);
                    };
                    console.log('$.ajax patched for getInfo interception');
                }
            },
            configurable: true
        });
    """)

    def handle_route(route):
        if "getInfo" in route.request.url:
            print("ROUTE INTERCEPT getInfo")
            route.fulfill(
                status=200,
                headers={"Content-Type": "text/html;charset=UTF-8"},
                body=bi_str
            )
        else:
            route.continue_()

    page.route("**/*", handle_route)

    page.goto(
        "https://crm.finereporthelp.com/WebReport/power_map/powerMap_v3.13.html?com_id=test",
        wait_until="domcontentloaded", timeout=20000
    )
    page.wait_for_timeout(10000)

    try:
        nodes = page.evaluate("document.querySelectorAll('.x6-node').length")
        print("X6 nodes:", nodes)
    except:
        print("Node check failed")

    print("--- All console ---")
    for m in msgs:
        print(m[:200])

    png = page.screenshot(type="png", full_page=False)
    with open("/app/static/x6_p2.png", "wb") as f:
        f.write(png)
    print("Screenshot:", len(png), "bytes")
    b.close()
