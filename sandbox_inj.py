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

async def fetch_data():
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(
            "https://crm.finereporthelp.com/WebReport/decision/url/power_map/getInfo",
            params={"prj_id":"9321225a-a435-4aa4-a7c7-50a66076fa57","prj_type":"company",
                    "ver_info":"548f02a7-2a36-4709-b910-eaf717e7cbf7"},
            headers={"Authorization":"Bearer "+token})
        return r.json()

async def fetch_html():
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.get("https://crm.finereporthelp.com/WebReport/power_map/powerMap_v3.13.html")
        return r.text

bi_data = asyncio.run(fetch_data())
html = asyncio.run(fetch_html())

# Patch: polling version of success callback
old_cb = "var obj = eval('(' + result + ')');\n                    switchVersion(ver_type,obj,self);"
new_cb = """var obj = window.__GRAPH_DATA__;
                    (function tryRender() {
                        if (typeof graph !== 'undefined' && graph.clearCells) {
                            switchVersion(ver_type, obj, self);
                        } else {
                            setTimeout(tryRender, 200);
                        }
                    })();"""
html = html.replace(old_cb, new_cb)
print("Patched:", "OK" if new_cb in html else "FAILED")
Path("/app/static/pm_sandbox_final.html").write_text(html, encoding="utf-8")

bi_str = json.dumps(bi_data, ensure_ascii=False)

with sync_playwright() as p:
    b = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-gpu"])
    ctx = b.new_context(viewport={"width": 2560, "height": 1440})
    ctx.add_cookies([{"name": "fine_auth_token", "value": token, "domain": "crm.finereporthelp.com", "path": "/"}])
    page = ctx.new_page()
    errs = []
    page.on("pageerror", lambda e: errs.append(str(e)[:200]))

    page.add_init_script("window.__GRAPH_DATA__ = " + bi_str + ";")

    def handle_route(route):
        if "powerMap_v3.13.html" in route.request.url and "getInfo" not in route.request.url:
            route.fulfill(status=200, headers={"Content-Type": "text/html;charset=UTF-8"}, body=html)
        else:
            route.continue_()

    page.route("**/*", handle_route)
    page.goto(
        "https://crm.finereporthelp.com/WebReport/power_map/powerMap_v3.13.html?com_id=test",
        wait_until="networkidle", timeout=30000
    )
    page.wait_for_timeout(8000)  # Wait for polling to succeed

    for e in errs:
        print("ERR:", e[:150])

    # Set viewBox, resize, screenshot SVG
    page.evaluate("""
        (function() {
            var graphs = document.querySelectorAll('.x6-graph');
            var stencil = document.getElementById('stencilContainer');
            for (var i = 0; i < graphs.length; i++) {
                if (stencil && stencil.contains(graphs[i])) continue;
                var svg = graphs[i].querySelector('.x6-graph-svg');
                if (!svg) continue;
                var bbox = svg.getBBox();
                if (bbox.width < 100 || bbox.height < 100) continue;
                var pad = 50;
                var vb = (bbox.x-pad) + ' ' + (bbox.y-pad) + ' ' + (bbox.width+pad*2) + ' ' + (bbox.height+pad*2);
                svg.setAttribute('viewBox', vb);
                var w = bbox.width + pad*2, h = bbox.height + pad*2;
                graphs[i].style.width = w + 'px';
                graphs[i].style.height = h + 'px';
                var el = graphs[i].parentElement;
                for (var j = 0; j < 5 && el && el !== document.body; j++) {
                    el.style.width = w + 'px';
                    el.style.height = h + 'px';
                    el.style.overflow = 'visible';
                    el = el.parentElement;
                }
                break;
            }
        })()
    """)
    page.wait_for_timeout(500)

    svgs = page.query_selector_all(".x6-graph-svg")
    main_svg = None
    max_sz = 0
    for svg in svgs:
        bb = svg.bounding_box()
        if bb and bb["width"] * bb["height"] > max_sz:
            max_sz = bb["width"] * bb["height"]
            main_svg = svg

    if main_svg:
        png = main_svg.screenshot(type="png")
        out = "/app/static/pm_sandbox_injected.png"
        with open(out, "wb") as f:
            f.write(png)
        print("Saved:", out, len(png), "bytes")
    else:
        print("No main SVG found")

    b.close()
