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

with sync_playwright() as p:
    b = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-gpu"])
    ctx = b.new_context(viewport={"width": 1920, "height": 1080})
    ctx.add_cookies([{
        "name": "fine_auth_token", "value": token,
        "domain": "crm.finereporthelp.com", "path": "/"
    }])
    page = ctx.new_page()

    page.goto(
        "https://crm.finereporthelp.com/WebReport/power_map/powerMap_v3.13.html?com_id=9321225a-a435-4aa4-a7c7-50a66076fa57",
        wait_until="networkidle", timeout=30000
    )
    page.wait_for_timeout(3000)
    print("Page loaded")

    # Try to zoom to fit via the page's UI
    # First check what zoom controls exist
    btns = page.evaluate("""
        (function() {
            var btns = document.querySelectorAll('button, .btn, [role=\"button\"], span[onclick]');
            var texts = [];
            btns.forEach(function(b) {
                var t = b.textContent.trim();
                if (t && t.length < 20) texts.push(t);
            });
            return JSON.stringify(texts.slice(0, 30));
        })()
    """)
    print("Buttons:", btns)

    # Try finding and clicking a "fit" or zoom button
    # Or: get the SVG bounding box and adjust viewport
    svg_bbox = page.evaluate("""
        (function() {
            var svg = document.querySelector('.x6-graph-svg');
            if (!svg) return JSON.stringify({error: 'no svg'});
            var bbox = svg.getBoundingClientRect();
            var parent = svg.parentElement;
            var pbbox = parent ? parent.getBoundingClientRect() : null;
            return JSON.stringify({
                svg: {w: bbox.width, h: bbox.height, x: bbox.x, y: bbox.y},
                parent: pbbox ? {w: pbbox.width, h: pbbox.height} : null,
                viewBox: svg.getAttribute('viewBox')
            });
        })()
    """)
    print("SVG bbox:", svg_bbox)

    # Also check graph container
    graph_info = page.evaluate("""
        (function() {
            var g = document.querySelector('.x6-graph');
            if (!g) return JSON.stringify({found: false});
            var keys = [];
            for (var k in g) {
                if (g.hasOwnProperty(k) && !k.startsWith('__react') && k.length < 30) {
                    keys.push(k);
                }
            }
            // Try to access graph via jQuery data
            var jqData = typeof $ !== 'undefined' ? 'jq available' : 'no jq';
            if (typeof $ !== 'undefined') {
                try {
                    var data = $(g).data();
                    keys.push('jqDataKeys: ' + Object.keys(data).join(','));
                } catch(e) {}
            }
            return JSON.stringify({found: true, keys: keys.slice(0, 20), jqData: jqData});
        })()
    """)
    print("Graph container:", graph_info)

    # Check if there's a global FR (FineReport) object
    fr_check = page.evaluate("""
        (function() {
            var result = {};
            if (typeof FR !== 'undefined') result.FR = typeof FR;
            if (typeof contentPane !== 'undefined') result.contentPane = typeof contentPane;
            if (typeof _g !== 'undefined') result._g = typeof _g;
            // Try all single-letter globals
            for (var c = 65; c < 91; c++) {
                var name = String.fromCharCode(c);
                if (typeof window[name] !== 'undefined' && window[name] !== null) {
                    var t = typeof window[name];
                    if (t === 'object' || t === 'function') {
                        result[name] = t;
                    }
                }
            }
            return JSON.stringify(result);
        })()
    """)
    print("Globals:", fr_check)

    b.close()
