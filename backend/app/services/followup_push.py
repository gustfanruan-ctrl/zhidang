from __future__ import annotations

import hashlib
import json
import time
from typing import Any
from uuid import uuid4

import httpx

DEFAULT_TRAVEL_PUSH_URL = "http://121.199.167.115:2220/dataway/service/success_chuchai"


def get_followup_push_config(field_mappings: dict[str, Any] | None) -> dict[str, Any]:
    root = dict((field_mappings or {}).get("jiandaoyun", {}) or {})
    followup_cfg = dict((root.get("followup_push") or {}))
    enabled = followup_cfg.get("enabled")
    if enabled is None:
        enabled = True
    return {
        "enabled": bool(enabled),
        "url": str(followup_cfg.get("url") or DEFAULT_TRAVEL_PUSH_URL).strip(),
        "secret": str(followup_cfg.get("secret") or "").strip(),
        "timeout_seconds": float(followup_cfg.get("timeout_seconds") or 2.0),
    }


def extract_created_data_id(create_result: dict[str, Any]) -> str:
    candidates = [
        create_result.get("data_id"),
        create_result.get("_id"),
        (create_result.get("data") or {}).get("_id") if isinstance(create_result.get("data"), dict) else "",
        (create_result.get("data") or {}).get("data_id") if isinstance(create_result.get("data"), dict) else "",
    ]
    for candidate in candidates:
        value = str(candidate or "").strip()
        if value:
            return value
    return ""


def build_followup_push_payload(record_data: dict[str, Any], *, op: str = "data_create") -> dict[str, Any]:
    return {
        "op": op,
        "opTime": int(time.time() * 1000),
        "data": record_data,
    }


def build_followup_push_request(
    payload: dict[str, Any],
    *,
    secret: str = "",
) -> tuple[dict[str, Any], dict[str, str], str]:
    timestamp = str(int(time.time()))
    nonce = uuid4().hex[:8]
    body_text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    headers = {
        "Content-Type": "application/json",
        "X-JDY-DeliverId": f"codex-{uuid4().hex}",
    }
    if secret:
        raw = f"{nonce}:{body_text}:{secret}:{timestamp}".encode("utf-8")
        headers["X-JDY-Signature"] = hashlib.sha1(raw).hexdigest()
    params = {"timestamp": timestamp, "nonce": nonce}
    return params, headers, body_text


async def push_followup_to_travel_server(
    *,
    url: str,
    payload: dict[str, Any],
    secret: str = "",
    timeout_seconds: float = 2.0,
) -> dict[str, Any]:
    params, headers, body_text = build_followup_push_request(payload, secret=secret)
    timeout = httpx.Timeout(timeout_seconds)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(url, params=params, headers=headers, content=body_text.encode("utf-8"))
    return {
        "ok": 200 <= response.status_code < 300,
        "status_code": response.status_code,
        "response_text": response.text[:500],
        "deliver_id": headers["X-JDY-DeliverId"],
    }
