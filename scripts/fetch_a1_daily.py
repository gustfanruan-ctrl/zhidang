#!/usr/bin/env python3
"""Daily fetch from A1 API into transcript DB."""
import json, sys
from datetime import datetime, timezone, timedelta
from uuid import uuid4
import urllib.request

sys.path.insert(0, "/app")
from backend.app.database import SessionLocal
from backend.app.models import Transcript

BASE = "https://crm.finereporthelp.com/WebReport/decision/url/pub/crm/data?id=5074008d30ba433aa54c8ddaee919cec&secret=123"
YESTERDAY = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

db = SessionLocal()
url = f"{BASE}&date={YESTERDAY}"
new = 0
skip = 0

try:
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode())
except Exception as e:
    print(f"[{YESTERDAY}] ERROR fetching A1: {e}")
    db.close()
    sys.exit(1)

for item in data.get("data", []):
    task_uuid = item.get("task_uuid", "")
    if not task_uuid:
        continue
    if db.query(Transcript).filter(Transcript.source_id == task_uuid).first():
        skip += 1
        continue
    raw_text = (item.get("transcript_text") or item.get("summary_text") or "").strip()
    if not raw_text:
        skip += 1
        continue
    t = Transcript(
        id=str(uuid4()),
        source="dingtalk",
        source_id=task_uuid,
        title=item.get("title", "") or "Untitled",
        raw_text=raw_text,
        input_type="text",
        status="parsed",
        sso_user_name=item.get("user_name", ""),
        sso_user_id=item.get("user_username", ""),
        created_at=datetime.now(timezone.utc),
    )
    db.add(t)
    new += 1

db.commit()
db.close()
print(f"[{YESTERDAY}] A1 fetch: {new} new, {skip} skipped")

