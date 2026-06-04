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

    page.goto(
        "https://crm.finereporthelp.com/WebReport/power_map/powerMap_v3.13.html?com_id=test",
        wait_until="domcontentloaded", timeout=20000
    )
    page.wait_for_timeout(3000)
    print("Page loaded")

    # List all global properties that aren't standard browser ones
    globals_list = page.evaluate("""
        () => {
            var std = ['window','document','location','navigator','screen','history',
                       'localStorage','sessionStorage','console','fetch','alert',
                       'setTimeout','setInterval','clearTimeout','clearInterval',
                       'Promise','Map','Set','WeakMap','WeakSet','Symbol','Proxy',
                       'Reflect','JSON','Math','Date','RegExp','Error','Array',
                       'Object','String','Number','Boolean','Function','parseInt',
                       'parseFloat','isNaN','isFinite','decodeURI','encodeURI',
                       'decodeURIComponent','encodeURIComponent','escape','unescape',
                       'eval','undefined','NaN','Infinity','Intl','Atomics',
                       'SharedArrayBuffer','DataView','ArrayBuffer','Float32Array',
                       'Float64Array','Int8Array','Int16Array','Int32Array',
                       'Uint8Array','Uint8ClampedArray','Uint16Array','Uint32Array',
                       'BigInt','BigInt64Array','BigUint64Array','WebAssembly',
                       'queueMicrotask','requestAnimationFrame','cancelAnimationFrame',
                       'requestIdleCallback','cancelIdleCallback','btoa','atob',
                       'performance','crypto','indexedDB','webkit','chrome',
                       'CSS','CSSConditionRule','CSSFontFaceRule','CSSImportRule',
                       'jQuery','$','__core-js_shared__','core','FR'];
            var keys = Object.getOwnPropertyNames(window).filter(function(k) {
                return std.indexOf(k) === -1 && typeof window[k] !== 'undefined';
            });
            return JSON.stringify(keys.slice(0, 50));
        }
    """)
    print("Custom globals:", globals_list)

    # Check for graph, drawNode, switchVersion
    for name in ["graph", "drawNode", "switchVersion", "createEdge", "node_map", "edge_map", "nodes", "edges", "serverName", "com_id"]:
        try:
            t = page.evaluate("typeof %s" % name)
            print("  typeof %s = %s" % (name, t))
        except:
            print("  %s = ERROR" % name)

    b.close()
