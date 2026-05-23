#!/usr/bin/env python3
"""Post-deployment verification: module checks + endpoint checks.

Usage:
    python3 scripts/verify_deploy.py [--server URL] [--token TOKEN]
    Default server: http://localhost:8000
    Default token: auto-login as admin

Verifies:
    Module checks: key functions/classes exist via import + hasattr
    Endpoint checks: each endpoint returns route-specific error, not FastAPI default 404

Exit 0 on all pass, exit 1 on any failure.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

DEFAULT_SERVER = os.getenv("ZHIDANG_BASE_URL", "http://localhost:8000")
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = os.getenv("ZHIDANG_PASSWORD", "Fr521521")

_failures: list[str] = []


# ── helpers ──────────────────────────────────────────────────────────

def _http(method: str, url: str, headers: dict | None = None,
          body: dict | None = None, timeout: int = 10) -> tuple[int, str, str]:
    """Make HTTP request, return (status, body, content_type)."""
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace"), \
                   resp.headers.get("Content-Type", "")
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")
        return exc.code, body_text, exc.headers.get("Content-Type", "")
    except urllib.error.URLError as exc:
        return 0, "", ""


def _login(server: str) -> str:
    status, body, _ = _http("POST", f"{server}/api/v1/auth/login",
                            {"Content-Type": "application/json"},
                            {"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})
    if status != 200:
        raise RuntimeError(f"Login failed: HTTP {status}: {body[:200]}")
    token = json.loads(body).get("token", "")
    if not token:
        raise RuntimeError(f"Login returned no token: {body[:200]}")
    return token


def check(name: str, ok: bool, detail: str = "") -> bool:
    status = "✅ PASS" if ok else "❌ FAIL"
    msg = f"  {status}  {name}"
    if detail and not ok:
        msg += f"\n         {detail}"
    print(msg)
    if not ok:
        _failures.append(name)
    return ok


# ── Module checks (run inside container via docker exec) ─────────────

MODULE_CHECKS = [
    # (import_path, attr_name, description)
    ("app.services.openai_compatible_agent_client",
     "OpenAICompatibleAgentClient.messages_create_with_history_stream",
     "OpenAICompatibleAgentClient has messages_create_with_history_stream"),
    ("app.services.power_map_service",
     "chat_power_map_v2",
     "power_map_service has chat_power_map_v2"),
    ("app.services.power_map_service",
     "commit_power_map_session",
     "power_map_service has commit_power_map_session"),
    ("app.services.power_map_service",
     "discard_power_map_session",
     "power_map_service has discard_power_map_session"),
    ("app.services.power_map_service",
     "_build_graph_state_text",
     "power_map_service has _build_graph_state_text"),
    ("app.services.sandbox_infra",
     "verify_manifest",
     "sandbox_infra has verify_manifest"),
]


def run_module_checks(container: str = "zhidang-backend-1") -> bool:
    """Run import+hasattr checks. Uses direct import if inside container, docker exec otherwise."""
    print("\n── Module checks ──")

    # Detect if we're inside the container
    try:
        result = subprocess.run(
            ["docker", "exec", "-w", "/app/backend", container,
             "python3", "-c", "print('ok')"],
            capture_output=True, text=True, timeout=5,
        )
        use_docker = result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        use_docker = False

    if use_docker:
        # Run inside container via docker exec
        check_script = _build_module_check_script()
        result = subprocess.run(
            ["docker", "exec", "-w", "/app/backend", container,
             "python3", "-c", check_script],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            check("module_checks: container exec", False,
                  f"exit={result.returncode} stderr={result.stderr[:200]}")
            return False
        raw_output = result.stdout
    else:
        # Direct import (already inside container or running locally)
        sys.path.insert(0, "/app/backend")
        results = []
        for import_path, attr_name, desc in MODULE_CHECKS:
            if "." in attr_name:
                class_name, _, attr_name_only = attr_name.partition(".")
            else:
                class_name = None
                attr_name_only = attr_name
            try:
                mod = __import__(import_path, fromlist=["_"])
                if class_name:
                    obj = getattr(mod, class_name, None)
                    if obj is None:
                        results.append({"desc": desc, "ok": False, "detail": f"class {class_name} not found"})
                    else:
                        results.append({"desc": desc, "ok": hasattr(obj, attr_name_only)})
                else:
                    results.append({"desc": desc, "ok": hasattr(mod, attr_name_only)})
            except Exception as e:
                results.append({"desc": desc, "ok": False, "detail": str(e)})
        raw_output = json.dumps(results)

    try:
        results = json.loads(raw_output)
    except json.JSONDecodeError:
        check("module_checks: parse output", False,
              f"raw_output={raw_output[:200]}")
        return False

    all_ok = True
    for item in results:
        ok = check(item["desc"], item["ok"], item.get("detail", ""))
        if not ok:
            all_ok = False
    return all_ok


def _build_module_check_script() -> str:
    lines = [
        "import json, sys; sys.path.insert(0, '/app/backend')",
        "results = []",
    ]
    for import_path, attr_name, desc in MODULE_CHECKS:
        if "." in attr_name:
            class_name, _, attr_name_only = attr_name.partition(".")
        else:
            class_name = None
            attr_name_only = attr_name

        lines.append(f"""
try:
    import {import_path} as _m
""")
        if class_name:
            lines.append(f"""    obj = getattr(_m, {json.dumps(class_name)}, None)
    if obj is None:
        results.append({{"desc": {json.dumps(desc)}, "ok": False, "detail": "class {class_name} not found"}})
    elif hasattr(obj, {json.dumps(attr_name_only)}):
        results.append({{"desc": {json.dumps(desc)}, "ok": True}})
    else:
        results.append({{"desc": {json.dumps(desc)}, "ok": False, "detail": "missing attribute {attr_name_only}"}})
except Exception as e:
    results.append({{"desc": {json.dumps(desc)}, "ok": False, "detail": str(e)}})
""")
        else:
            lines.append(f"""    if hasattr(_m, {json.dumps(attr_name_only)}):
        results.append({{"desc": {json.dumps(desc)}, "ok": True}})
    else:
        results.append({{"desc": {json.dumps(desc)}, "ok": False, "detail": "missing attribute {attr_name_only}"}})
except Exception as e:
    results.append({{"desc": {json.dumps(desc)}, "ok": False, "detail": str(e)}})
""")
    lines.append("print(json.dumps(results))")
    return "\n".join(lines)


# ── Endpoint checks ──────────────────────────────────────────────────

ENDPOINT_CHECKS = [
    # (method, path, body_dict, expected_statuses, expected_in_body, description)
    ("POST", "/api/v1/power-map/test_company/chat_v2",
     {"message": "test", "session_id": "rejected_verify"}, (400,), "session_id",
     "chat_v2: endpoint exists (400=session_id rejected)"),
    ("POST", "/api/v1/power-map/test_company/commit",
     {"session_id": "nonexistent_verify"}, (200,), "session",
     "commit: endpoint exists (session_not_found expected)"),
    ("POST", "/api/v1/power-map/test_company/discard",
     {"session_id": "nonexistent_verify"}, (200,), "ok",
     "discard: endpoint exists"),
    ("GET", "/api/v1/power-map/debug/dump_ctx?session_id=nonexistent_verify",
     None, (404,), "session",
     "dump_ctx: endpoint exists (404=session not found)"),
]


def run_endpoint_checks(server: str, token: str) -> bool:
    print("\n── Endpoint checks ──")
    headers = {"Authorization": f"Bearer {token}",
               "Content-Type": "application/json"}
    all_ok = True

    for method, path, body, expected_codes, expected_word, desc in ENDPOINT_CHECKS:
        url = f"{server}{path}"
        try:
            status, body_text, ct = _http(method, url, headers, body)
            body_lower = body_text.lower()
            status_ok = status in expected_codes
            word_ok = expected_word.lower() in body_lower

            if status_ok and word_ok:
                check(desc, True)
            elif status_ok:
                check(desc, False,
                      f"HTTP {status} but body missing '{expected_word}': {body_text[:200]}")
                all_ok = False
            else:
                check(desc, False,
                      f"HTTP {status} (expected {'/'.join(str(c) for c in expected_codes)}): {body_text[:200]}")
                all_ok = False
        except Exception as exc:
            check(desc, False, f"Connection failed: {exc}")
            all_ok = False

    return all_ok


# ── Main ─────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Post-deployment verification")
    parser.add_argument("--server", default=DEFAULT_SERVER)
    parser.add_argument("--token", help="Admin JWT (auto-login if omitted)")
    parser.add_argument("--container", default="zhidang-backend-1",
                        help="Docker container name for module checks")
    parser.add_argument("--skip-modules", action="store_true",
                        help="Skip module-level checks")
    args = parser.parse_args()

    server = args.server.rstrip("/")
    print(f"🔍 Verifying on {server}\n")

    # 1. Auth
    try:
        token = args.token or _login(server)
        check("auth: login", True)
    except Exception as exc:
        check("auth: login", False, str(exc))
        print("\n❌ Cannot proceed without auth.")
        sys.exit(1)

    # 2. Module checks
    if not args.skip_modules:
        run_module_checks(args.container)
    else:
        print("\n── Module checks ── (skipped)")

    # 3. Endpoint checks
    run_endpoint_checks(server, token)

    # Summary
    print(f"\n{'='*50}")
    if _failures:
        print(f"❌ {len(_failures)} check(s) FAILED:")
        for f in _failures:
            print(f"   - {f}")
        sys.exit(1)
    else:
        print("✅ All checks passed.")
        sys.exit(0)


if __name__ == "__main__":
    main()
