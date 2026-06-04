import sys; sys.path.insert(0, "/app/backend")
import asyncio, json, base64
from pathlib import Path
from app.database import SessionLocal
from app.models import SystemConfig
from app.crypto_utils import decrypt_secret
import httpx

async def main():
    db = SessionLocal()
    cfg = db.get(SystemConfig, 1)
    token = decrypt_secret(cfg.power_map_auth_token_encrypted)
    db.close()
    
    prj_id = "9321225a-a435-4aa4-a7c7-50a66076fa57"
    ver_info = "548f02a7-2a36-4709-b910-eaf717e7cbf7"
    
    url = "https://crm.finereporthelp.com/WebReport/decision/url/power_map/getInfo"
    headers = {"Authorization": "Bearer " + token}
    params = {"prj_id": prj_id, "prj_type": "opp", "ver_info": ver_info}
    
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, params=params, headers=headers)
        data = resp.json()
    
    nodes = []
    for raw in data.get("node_info", []):
        nt = raw.get("node_type", "user")
        if nt == "person":
            nt = "user"
        elif nt == "department":
            nt = "dept"
        
        w = float(raw.get("node_width", 0)) or (160 if nt == "user" else 500)
        h = float(raw.get("node_height", 0)) or (60 if nt == "user" else 200)
        
        nodes.append({
            "id": str(raw.get("id", "")),
            "name": str(raw.get("name", "")),
            "node_type": nt,
            "position": str(raw.get("position", "")),
            "tagA": str(raw.get("tagA", "")),
            "parent_dept_id": str(raw.get("node_parent_dept", "")),
            "pid": str(raw.get("pid", "")),
            "node_manager": str(raw.get("node_manager", "0")),
            "width": int(w),
            "height": int(h),
        })
    
    edges = []
    for e in data.get("edge_info", []):
        edges.append({
            "source": str(e.get("source_id", "")),
            "target": str(e.get("target_id", "")),
            "type": str(e.get("edge_type", "reports_to")),
        })
    
    graph_data = {"nodes": nodes, "edges": edges}
    dept_count = sum(1 for n in nodes if n["node_type"] == "dept")
    user_count = sum(1 for n in nodes if n["node_type"] == "user")
    print("Nodes: %d (users=%d, depts=%d)" % (len(nodes), user_count, dept_count))
    print("Edges: %d" % len(edges))
    
    graph_json = json.dumps(graph_data, ensure_ascii=False)
    
    # Inject into sandbox
    template = Path("/app/static/pm_sandbox.html").read_text(encoding="utf-8")
    html = template.replace(
        "window.__GRAPH_DATA__",
        "window.__GRAPH_DATA__ = " + graph_json + ";\n//"
    )
    preview_path = Path("/app/static/_pm_preview_test2.html")
    preview_path.write_text(html, encoding="utf-8")
    print("HTML: %d bytes" % len(html))
    
    # Render screenshot
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-gpu"])
        page = await browser.new_page()
        await page.goto("file://" + str(preview_path), wait_until="load", timeout=15000)
        # Check if data was loaded
        has_data = await page.evaluate("window.__GRAPH_DATA__ !== undefined")
        print("Graph data loaded:", has_data)
        
        try:
            await page.wait_for_function("window.__LAYOUT_DONE__ === true", timeout=10000)
            print("Layout done!")
        except Exception as e:
            print("Layout timeout:", str(e)[:80])
            # Check for JS errors
            errors = await page.evaluate("""() => {
                var errs = window.__JS_ERRORS__ || [];
                return errs.join(' | ');
            }""")
            print("JS errors:", errors if errors else "none")
            
            # Get page content snapshot
            body = await page.evaluate("document.body.innerHTML.substring(0, 500)")
            print("Body:", body)
        
        png_bytes = await page.screenshot(type="png", full_page=True)
        await browser.close()
    
    out_path = Path("/app/static/meiyijia_preview2.png")
    out_path.write_bytes(png_bytes)
    print("Screenshot: %s (%d bytes)" % (out_path, len(png_bytes)))

asyncio.run(main())
