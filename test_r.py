import sys; sys.path.insert(0, "/app/backend")
from playwright.sync_api import sync_playwright
import json, threading, time
from http.server import HTTPServer, BaseHTTPRequestHandler
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
            params={"prj_id":"9321225a-a435-4aa4-a7c7-50a66076fa57","prj_type":"company","ver_info":"548f02a7-2a36-4709-b910-eaf717e7cbf7"},
            headers={"Authorization":"Bearer "+token})
        return r.json()

bi_data = asyncio.run(fetch())
bi_str = json.dumps(bi_data, ensure_ascii=False)
print("Data:", len(bi_str), "chars")

class DataHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        time.sleep(0.3)
        self.send_response(200)
        self.send_header("Content-Type", "text/html;charset=UTF-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(bi_str.encode("utf-8"))
    def log_message(self, format, *args):
        pass

server = HTTPServer(("127.0.0.1", 9877), DataHandler)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
print("HTTP server on :9877")

with sync_playwright() as p:
    b = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-gpu"])
    ctx = b.new_context(viewport={"width":1920,"height":1080})
    ctx.add_cookies([{"name":"fine_auth_token","value":token,"domain":"crm.finereporthelp.com","path":"/"}])
    page = ctx.new_page()
    errs = []
    page.on("pageerror", lambda e: errs.append(str(e)[:200]))
    
    def handle_route(route):
        if "getInfo" in route.request.url:
            print("REDIRECT getInfo to localhost:9877")
            route.continue_(url="http://127.0.0.1:9877/getInfo")
        else:
            route.continue_()
    
    page.route("**/*", handle_route)
    page.goto(
        "https://crm.finereporthelp.com/WebReport/power_map/powerMap_v3.13.html?com_id=9321225a-a435-4aa4-a7c7-50a66076fa57",
        wait_until="networkidle", timeout=30000
    )
    page.wait_for_timeout(5000)
    print("Page loaded")
    
    for e in errs:
        print("ERR:", e[:150])
    
    png = page.screenshot(type="png", full_page=False)
    with open("/app/static/x6_redirect.png", "wb") as f:
        f.write(png)
    print("Screenshot:", len(png), "bytes")
    b.close()

server.shutdown()
