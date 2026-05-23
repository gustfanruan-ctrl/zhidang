#!/usr/bin/env python3
"""E2E test client with per-round sandbox screenshot capture.

Usage:
    python3 e2e_with_screenshots.py <company_id> <message> [--output-dir DIR]
"""
from __future__ import annotations
import json, os, sys, time, uuid, base64, asyncio
from pathlib import Path
from urllib.parse import urljoin
import requests

SERVER = os.getenv("ZHIDANG_BASE_URL", "http://47.98.102.197:8000")
SANDBOX_BASE = os.getenv("SANDBOX_BASE_URL", SERVER)
TOKEN = None
OUTPUT_DIR = "./e2e_output"
COMPANY_ID = ""
MESSAGE = ""

def login():
    global TOKEN
    resp = requests.post(
        urljoin(SERVER, "/api/v1/auth/login"),
        json={"username": "admin", "password": os.getenv("ZHIDANG_PASSWORD", "Fr521521")},
        timeout=10,
    )
    resp.raise_for_status()
    TOKEN = resp.json()["token"]

def capture_sandbox(session_id: str, round_num: int) -> str:
    """Use requests to get sandbox page, but we need browser for screenshots.
    Instead, call a server-side endpoint to capture and return base64.
    Actually — just use Playwright if available, or skip."""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            page = browser.new_page(viewport={"width": 1920, "height": 1080})
            page.set_extra_http_headers({"X-Sandbox-Session": session_id})
            url = f"{SANDBOX_BASE}/sandbox/render?session_id={session_id}"
            page.goto(url, wait_until="networkidle", timeout=15000)
            page.wait_for_timeout(2000)
            png = page.locator("#graphContainer .x6-graph-svg").first.screenshot(type="png")
            browser.close()
            return base64.b64encode(png).decode("ascii")
    except Exception as exc:
        print(f"  [screenshot failed: {exc}]")
        return ""

def run():
    url = urljoin(SERVER, f"/api/v1/power-map/{COMPANY_ID}/chat_v2?token={TOKEN}")
    payload = {"message": MESSAGE}
    
    raw_log = os.path.join(OUTPUT_DIR, f"raw_sse_{uuid.uuid4().hex[:8]}.log")
    Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
    
    rounds = 0
    current_round = 0
    thinking = {}
    tool_calls = {}
    session_id = ""
    abcd = {"A": 0, "B": 0, "C": 0, "D": 0}
    last_screenshot_round = 0
    t0 = time.monotonic()
    
    with open(raw_log, "w") as fh:
        fh.write(f"# SSE raw log | {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        fh.write(f"# url={url}\n# payload={json.dumps(payload, ensure_ascii=False)}\n# {'='*60}\n\n")
        
        resp = requests.post(url, json=payload, stream=True, timeout=300)
        resp.raise_for_status()
        
        buffer = ""
        for chunk in resp.iter_content(chunk_size=8192, decode_unicode=True):
            if not chunk:
                continue
            buffer += chunk if isinstance(chunk, str) else chunk.decode("utf-8", errors="replace")
            
            while "\n\n" in buffer:
                raw_event, buffer = buffer.split("\n\n", 1)
                fh.write(raw_event + "\n\n")
                fh.flush()
                
                lines = raw_event.strip().split("\n")
                event_type = ""
                data_str = ""
                for line in lines:
                    if line.startswith("event: "):
                        event_type = line[7:]
                    elif line.startswith("data: "):
                        data_str = line[6:]
                
                if not event_type:
                    continue
                try:
                    data = json.loads(data_str)
                except:
                    continue
                
                if event_type == "round_start":
                    current_round = data.get("round", 0)
                    rounds = max(rounds, current_round)
                    session_id = data.get("session_id", session_id)
                    thinking[current_round] = ""
                    tool_calls[current_round] = []
                    
                    # Capture screenshot at round boundary (except R1 start)
                    if current_round > 1 and session_id:
                        png_b64 = capture_sandbox(session_id, current_round)
                        if png_b64:
                            png_path = os.path.join(OUTPUT_DIR, f"case_round_{current_round}.png")
                            with open(png_path, "wb") as pf:
                                pf.write(base64.b64decode(png_b64))
                            print(f"  📸 R{current_round} screenshot → {png_path} ({len(png_b64)} chars)")
                            last_screenshot_round = current_round
                
                elif event_type == "thinking":
                    if current_round:
                        thinking[current_round] = thinking.get(current_round, "") + data.get("text_chunk", "")
                
                elif event_type == "tool_call":
                    tool = data.get("tool", "")
                    args = data.get("args", {})
                    if current_round:
                        tool_calls[current_round].append({"tool": tool, "args": args})
                    
                    # ABCD
                    if tool in ("create_node", "delete_node", "create_edge", "delete_edge",
                               "set_parent", "update_node", "update_edge"):
                        abcd["A"] += 1
                    elif tool in ("place_node", "nudge_node", "resize_container", "fit_container_to_children"):
                        abcd["B"] += 1
                    elif tool in ("arrange_horizontally", "arrange_vertically", "center_above",
                                "center_below", "align_left", "align_top", "distribute_horizontally", "relayout"):
                        abcd["C"] += 1
                    elif tool in ("check_collisions", "auto_fix_collisions", "validate_structure", "get_node_geometry"):
                        abcd["D"] += 1
        
        # Final screenshot
        if session_id:
            png_b64 = capture_sandbox(session_id, -1)
            if png_b64:
                png_path = os.path.join(OUTPUT_DIR, f"case_round_FINAL.png")
                with open(png_path, "wb") as pf:
                    pf.write(base64.b64decode(png_b64))
                print(f"  📸 FINAL screenshot → {png_path}")
    
    elapsed = time.monotonic() - t0
    total_tools = sum(len(v) for v in tool_calls.values())
    
    print(f"\n{'='*60}")
    print(f"Case: {MESSAGE[:50]}")
    print(f"Rounds: {rounds}")
    print(f"Tools: {total_tools}")
    print(f"ABCD: A={abcd['A']} B={abcd['B']} C={abcd['C']} D={abcd['D']}")
    print(f"Elapsed: {elapsed:.1f}s")
    print(f"Session: {session_id}")
    print(f"SSE log: {raw_log}")
    
    for r in range(1, rounds + 1):
        t = thinking.get(r, "")[:200]
        tc = tool_calls.get(r, [])
        tools_str = ", ".join(tc2["tool"] for tc2 in tc)
        print(f"  R{r}: {len(tc)} calls [{tools_str}] | think: {t[:120]}")
    
    # Also capture a direct screenshot of the page content
    if session_id:
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
                page = browser.new_page(viewport={"width": 1920, "height": 1080})
                page.set_extra_http_headers({"X-Sandbox-Session": session_id})
                page.goto(f"{SANDBOX_BASE}/sandbox/render?session_id={session_id}", wait_until="networkidle", timeout=15000)
                page.wait_for_timeout(3000)
                # Full page screenshot
                png_path = os.path.join(OUTPUT_DIR, "case_fullpage.png")
                page.screenshot(path=png_path, full_page=True)
                print(f"  📸 Full page → {png_path}")
                # Check node count
                count = page.evaluate("document.querySelectorAll('g.x6-node').length")
                print(f"  x6-node count: {count}")
                browser.close()
        except Exception as exc:
            print(f"  Full page screenshot failed: {exc}")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python3 e2e_with_screenshots.py <company_id> <message> [--output-dir DIR]")
        sys.exit(1)
    
    COMPANY_ID = sys.argv[1]
    MESSAGE = sys.argv[2]
    
    for i, arg in enumerate(sys.argv):
        if arg == "--output-dir" and i + 1 < len(sys.argv):
            OUTPUT_DIR = sys.argv[i + 1]
    
    print(f"Server: {SERVER}")
    print(f"Company: {COMPANY_ID}")
    print(f"Message: {MESSAGE}")
    print(f"Output: {OUTPUT_DIR}")
    print()
    
    login()
    run()
