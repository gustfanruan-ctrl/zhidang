"""Compare customer cache IDs with followup record IDs to find matching fields."""
import json, sys
sys.path.insert(0, "/app")
from backend.app.database import SessionLocal
from backend.app.models import FollowupRecord
from sqlalchemy import select
import urllib.request

# Get token
from backend.app.auth import create_jwt
token = create_jwt({'source': 'superadmin', 'username': 'admin'})

# Get customers from API
req = urllib.request.Request(
    "http://localhost:8000/api/v1/customers/list?limit=50",
    headers={"Authorization": f"Bearer {token}"}
)
with urllib.request.urlopen(req) as resp:
    customers = json.loads(resp.read())["customers"]

customer_ids = {c['company_id'] for c in customers}
print(f"Customer cache: {len(customer_ids)} IDs (sample: {list(customer_ids)[:3]})")

# Search followup records
db = SessionLocal()
rows = db.execute(select(FollowupRecord).limit(200)).scalars().all()

matches_comid = 0
matches_genjin = 0
matches_task_id = 0
matches_any = 0

for r in rows:
    raw = r.raw_record or {}
    cid = None

    # comid as string
    comid = raw.get('comid', '')
    if comid and comid in customer_ids:
        cid = comid
        matches_comid += 1

    # genjin subform
    genjin = raw.get('genjin', [])
    if isinstance(genjin, list):
        for g in genjin:
            if isinstance(g, dict):
                gid = g.get('genjin_id', {})
                if isinstance(gid, dict) and gid.get('id', '') in customer_ids:
                    cid = gid['id']
                    matches_genjin += 1
                    break

    # task_id
    task_id = raw.get('task_id', '')
    if task_id and task_id in customer_ids:
        cid = task_id
        matches_task_id += 1

    if cid:
        matches_any += 1

print(f"Out of {len(rows)} followup records:")
print(f"  Match by comid: {matches_comid}")
print(f"  Match by genjin_id: {matches_genjin}")
print(f"  Match by task_id: {matches_task_id}")
print(f"  Any match: {matches_any}")

# Show ID formats
print(f"\nCustomer ID format: {list(customer_ids)[:3]}")
print(f"Followup comid format: {rows[0].raw_record.get('comid','?') if rows else '?'}")
db.close()
