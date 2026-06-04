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
    ctx.add_cookies([{
        "name": "fine_auth_token", "value": token,
        "domain": "crm.finereporthelp.com", "path": "/"
    }])
    page = ctx.new_page()

    # Load with REAL data - let everything initialize
    page.goto(
        "https://crm.finereporthelp.com/WebReport/power_map/powerMap_v3.13.html?com_id=9321225a-a435-4aa4-a7c7-50a66076fa57",
        wait_until="networkidle", timeout=30000
    )
    page.wait_for_timeout(3000)
    print("Page loaded with real data")

    # Find X6 graph instance through DOM
    x6_info = page.evaluate("""
        (function() {
            var result = {};
            
            // Find X6 container - it has class x6-graph
            var containers = document.querySelectorAll('.x6-graph');
            result.containers = containers.length;
            
            if (containers.length > 0) {
                var c = containers[0];
                // X6 stores graph reference as __x6_instance__ or similar
                var keys = Object.keys(c).filter(function(k) { return !k.startsWith('__react'); });
                result.domKeys = keys.slice(0, 20);
                
                // Try common X6 property names
                for (var prop of ['graph', 'x6', '__x6__', '_x6', 'instance', 'model', 'store']) {
                    if (c[prop] !== undefined) {
                        result['found_' + prop] = typeof c[prop];
                    }
                }
                
                // Check for React fiber (might hold reference)
                var fiberKey = Object.keys(c).find(function(k) { return k.startsWith('__reactFiber'); });
                if (fiberKey) {
                    var fiber = c[fiberKey];
                    result.hasFiber = true;
                    if (fiber && fiber.stateNode) {
                        var snKeys = Object.keys(fiber.stateNode).filter(function(k) { return !k.startsWith('__'); });
                        result.stateNodeKeys = snKeys.slice(0, 20);
                    }
                }
            }
            
            return JSON.stringify(result);
        })()
    """)
    print("X6 info:", x6_info)

    # Also check the x6-graph-svg element
    svg_info = page.evaluate("""
        (function() {
            var svg = document.querySelector('.x6-graph-svg');
            if (!svg) return JSON.stringify({found: false});
            
            var result = {found: true, tag: svg.tagName};
            
            // Check parent for graph ref
            var parent = svg.parentElement;
            if (parent) {
                var pKeys = Object.keys(parent).filter(function(k) { return k.length < 30 && !k.startsWith('on') && !k.startsWith('__react'); });
                result.parentKeys = pKeys.slice(0, 15);
                
                // Look for X6-specific properties
                for (var prop of ['graph', '_x6graph', 'x6graph', 'instance']) {
                    if (parent[prop] !== undefined) {
                        result['p_' + prop] = typeof parent[prop];
                    }
                }
            }
            
            return JSON.stringify(result);
        })()
    """)
    print("SVG info:", svg_info)

    b.close()
