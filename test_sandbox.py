import sys; sys.path.insert(0, "/app/backend")
import asyncio, json, base64
from pathlib import Path
from app.database import SessionLocal
from app.models import SystemConfig
from app.crypto_utils import decrypt_secret

async def main():
    db = SessionLocal()
    cfg = db.get(SystemConfig, 1)
    token = decrypt_secret(cfg.power_map_auth_token_encrypted) if cfg.power_map_auth_token_encrypted else ""
    db.close()
    
    import httpx
    prj_id = "9321225a-a435-4aa4-a7c7-50a66076fa57"
    ver_info = "548f02a7-2a36-4709-b910-eaf717e7cbf7"
    
    url = "https://crm.finereporthelp.com/WebReport/decision/url/power_map/getInfo"
    headers = {"Authorization": "Bearer " + token}
    params = {"prj_id": prj_id, "prj_type": "opp", "ver_info": ver_info}
    
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, params=params, headers=headers)
        data = resp.json()
    
    print("Status:", resp.status_code)
    
    meta = data.get("data", data)
    company_name = meta.get("company_name", "unknown")
    print("Company:", company_name)
    
    # Get contact_info which has nodes (persons + departments)
    contact_info = meta.get("contact_info", [])
    print("Contact info entries:", len(contact_info))
    
    # Separate nodes by type
    nodes = []
    for entry in contact_info:
        ntype_raw = entry.get("node_type", entry.get("type", ""))
        # Map BI types
        if ntype_raw == "person":
            ntype = "user"
        elif ntype_raw == "department":
            ntype = "dept"
        else:
            # Check if it has children/dept properties
            if entry.get("par_id") or entry.get("node_parent_dept"):
                ntype = "user"
            else:
                ntype = "dept"
        
        nodes.append({
            "id": str(entry.get("id", "")),
            "name": str(entry.get("name", "")),
            "node_type": ntype,
            "position": str(entry.get("position", "")),
            "tagA": str(entry.get("tagA", "")),
            "parent_dept_id": str(entry.get("par_id") or entry.get("node_parent_dept", "")),
            "pid": str(entry.get("pid", "")),
            "node_manager": str(entry.get("node_manager", "0")),
            "width": 160 if ntype == "user" else 500,
            "height": 60 if ntype == "user" else 200,
        })
    
    # Get edges
    raw_edges = meta.get("custom_edges", meta.get("edges", []))
    edges = []
    for e in raw_edges:
        edges.append({
            "source": str(e.get("source_id") or e.get("source", "")),
            "target": str(e.get("target_id") or e.get("target", "")),
            "type": str(e.get("type", "reports_to")),
        })
    
    graph_data = {"nodes": nodes, "edges": edges}
    print("Nodes:", len(nodes), "Edges:", len(edges))
    print("Users:", sum(1 for n in nodes if n["node_type"] == "user"))
    print("Depts:", sum(1 for n in nodes if n["node_type"] == "dept"))
    
    # Show node names
    for n in nodes:
        dept = " [" + n["parent_dept_id"][:8] + "]" if n["parent_dept_id"] else ""
        print("  " + n["node_type"] + ": " + n["name"] + dept)
    
    graph_json = json.dumps(graph_data, ensure_ascii=False)
    
    # Inject into sandbox
    template = Path("/app/static/pm_sandbox.html").read_text(encoding="utf-8")
    html = template.replace(
        "window.__GRAPH_DATA__",
        "window.__GRAPH_DATA__ = " + graph_json + ";\n//"
    )
    preview_path = Path("/app/static/_pm_preview_test.html")
    preview_path.write_text(html, encoding="utf-8")
    print("\nHTML written:", preview_path, len(html), "bytes")
    
    # Render screenshot
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-gpu"])
        page = await browser.new_page()
        await page.goto("file://" + str(preview_path), wait_until="load", timeout=15000)
        await page.wait_for_function("window.__LAYOUT_DONE__ === true", timeout=15000)
        png_bytes = await page.screenshot(type="png", full_page=True)
        await browser.close()
    
    out_path = Path("/app/static/meiyijia_preview.png")
    out_path.write_bytes(png_bytes)
    print("Screenshot:", out_path, len(png_bytes), "bytes")

asyncio.run(main())
