#!/usr/bin/env python3
"""Run Case 1 → commit → verify BI state."""
import json, requests, subprocess, sys

SERVER = "http://47.98.102.197:8000"
COMPANY = "798b6f52-2d62-48cf-b40a-dac5d37cc767"
MSG = "新建财务部，黄宇 CFO，纪成、张强、黄先生、曹强、苏女士、陆冠顺都向黄宇汇报"
VERSION = "028bf0a8-9867-47f9-8993-2434dcf8f1a9"

# Login
token = requests.post(f"{SERVER}/api/v1/auth/login",
    json={"username":"admin","password":"Fr521521"}).json()["token"]

# Run e2e client
result = subprocess.run([
    sys.executable, "/mnt/d/智档/backend/tests/e2e_chat_v2_client.py",
    COMPANY, MSG,
    "--server", SERVER,
    "--version", VERSION,
    "--raw-log-dir", "/mnt/d/智档/backend/e2e_output",
    "--ctx-dump-dir", "/mnt/d/智档/backend/e2e_output",
], capture_output=True, text=True, timeout=180, cwd="/mnt/d/智档/backend")

print("=== E2E OUTPUT ===")
print(result.stdout)
if result.returncode != 0:
    print(f"E2E FAILED: {result.stderr}")
    sys.exit(1)

# Extract session_id from output
import re
m = re.search(r"session:\s+(\S+)", result.stdout)
if not m:
    print("NO session_id found")
    sys.exit(1)
sid = m.group(1)
print(f"\n=== COMMITTING session {sid} ===")

# Commit
resp = requests.post(
    f"{SERVER}/api/v1/power-map/{COMPANY}/commit",
    headers={"Authorization": f"Bearer {token}"},
    json={"session_id": sid},
    timeout=30
)
print(f"Commit result: {resp.json()}")

# Verify BI state
import subprocess as sp
sp.run([
    "ssh", "-i", "/opt/data/home/.ssh/id_rsa_sync", "root@47.98.102.197",
    "docker exec zhidang-backend-1 curl -s "
    f"'https://crm.finereporthelp.com/WebReport/decision/url/power_map/getInfo?prj_type=opp&prj_id={COMPANY}&ver_id={VERSION}' "
    "-H 'Cookie: fine_auth_token=eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJHdXN0IiwidGVuYW50SWQiOiJkZWZhdWx0IiwiaXNzIjoiZmFucnVhbiIsImRlc2NyaXB0aW9uIjoiWzVmMjBdWzVjMGZdWzZkMGJdKEd1c3QpIiwiZXhwIjoxNzgwMDE5MTkzLCJpYXQiOjE3Nzk0MTQzOTMsImp0aSI6IlM5bmdqRjczMzJLVmVUY2I5TU9jQVU0MVhWd2J2SExnOGFCdnJ4UUlvSi9MVDdCcyJ9.69FNjQ7Wx38jcPPin1GltgqJNcbgLv8YiV8JFkCwU94'"
    " | python3 -c \"import json,sys;d=json.load(sys.stdin);nodes=d.get('nodes',[]);print(f'BI nodes={len(nodes)}');[print(f'  {n.get(\\\"name\\\")}') for n in nodes[:10]]\""
], timeout=15)
