from __future__ import annotations

import argparse
import asyncio
import base64
import json
import mimetypes
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx


DEFAULT_API_BASE = "http://127.0.0.1:8000"


@dataclass
class CapabilityRequestPlan:
    """A dry-run friendly description of one or more Zhidang HTTP calls."""

    capability: str
    action: str
    requests: list[dict[str, Any]]
    write_risk: str = "none"
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability": self.capability,
            "action": self.action,
            "write_risk": self.write_risk,
            "requests": self.requests,
            "notes": self.notes,
        }


def _read_text_file(path: str | None) -> str:
    if not path:
        return ""
    return Path(path).read_text(encoding="utf-8")


def _image_to_data_url(path: str) -> str:
    p = Path(path)
    mime = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
    encoded = base64.b64encode(p.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _display_path(path: str) -> str:
    return str(Path(path))


def _auth_headers(token: str | None) -> dict[str, str]:
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}"}


def _build_merged_record_text(record_details: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for detail in record_details:
        source_type = detail.get("_source_type")
        label = "跟进记录" if source_type == "followup" else "会议转写"
        title = detail.get("title") or detail.get("company_name") or detail.get("id") or "未命名记录"
        raw = str(detail.get("raw_text") or "").strip()
        if raw:
            parts.append(f"--- {label}: {title} ---\n{raw}")
    return "\n\n".join(parts)


def _parse_sse_event_lines(lines: list[str]) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    current_event = "message"
    current_data: list[str] = []

    def flush() -> None:
        nonlocal current_event, current_data
        if not current_data:
            current_event = "message"
            return
        data_text = "\n".join(current_data)
        try:
            data: Any = json.loads(data_text)
        except json.JSONDecodeError:
            data = data_text
        events.append({"event": current_event, "data": data})
        current_event = "message"
        current_data = []

    for line in lines:
        if not line:
            flush()
            continue
        if line.startswith("event:"):
            current_event = line.split(":", 1)[1].strip() or "message"
        elif line.startswith("data:"):
            current_data.append(line.split(":", 1)[1].strip())
    flush()

    session_id = ""
    for event in events:
        data = event.get("data")
        if isinstance(data, dict) and data.get("session_id"):
            session_id = str(data["session_id"])
            break
    return {"events": events, "session_id": session_id}


def build_followup_generate_plan(args: argparse.Namespace) -> CapabilityRequestPlan:
    content_parts = []
    if args.text:
        content_parts.append(args.text)
    file_text = _read_text_file(args.text_file)
    if file_text:
        content_parts.append(file_text)
    images = [_image_to_data_url(path) for path in args.image_file or []]
    content = "\n\n".join(part.strip() for part in content_parts if part.strip())
    if not content and images:
        content = "请根据上传图片内容生成结构化跟进记录。"

    payload = {
        "input_type": "screenshot" if images else "text",
        "content": content,
        "images": images,
        "company_id": args.company_id or "",
        "company_name": args.company_name or "",
    }
    return CapabilityRequestPlan(
        capability="followup",
        action="generate",
        write_risk="none",
        requests=[
            {
                "method": "POST",
                "path": "/api/v1/followup/generate",
                "content_type": "application/json",
                "json": payload,
                "summary": {
                    "company_id": payload["company_id"],
                    "company_name": payload["company_name"],
                    "input_type": payload["input_type"],
                    "content_chars": len(content),
                    "image_count": len(images),
                    "image_files": [_display_path(path) for path in args.image_file or []],
                },
            }
        ],
        notes=["生成跟进记录只生成预览，不写回简道云。写回必须另走 submit/页面确认。"],
    )


def _record_refs(args: argparse.Namespace) -> list[dict[str, str]]:
    refs = [{"source_type": "transcript", "id": rid} for rid in args.transcript_id or []]
    refs.extend({"source_type": "followup", "id": rid} for rid in args.followup_record_id or [])
    return refs


def build_expectation_scene_analyze_plan(args: argparse.Namespace) -> CapabilityRequestPlan:
    upload_files = list(args.upload_file or [])
    refs = _record_refs(args)
    requests: list[dict[str, Any]] = []
    notes: list[str] = []

    if upload_files:
        requests.append(
            {
                "method": "POST",
                "path": "/api/v1/transcript/upload",
                "content_type": "multipart/form-data",
                "form": {
                    "company_name_hint": args.company_name or "",
                    "company_id": args.company_id or "",
                },
                "files": [{"field": "files", "path": _display_path(path)} for path in upload_files],
                "follow_up": "POST /api/v1/transcripts/{transcript_id}/analyze" if args.start_analysis else None,
            }
        )
        notes.append("多文件上传由智档后端合并为一条 Transcript：文本拼接，图片保存为 image segment。")

    if len(refs) == 1 and not upload_files and not args.force_merge:
        ref = refs[0]
        params = {} if ref["source_type"] == "transcript" else {"source_type": "followup"}
        requests.append(
            {
                "method": "POST",
                "path": f"/api/v1/transcripts/{ref['id']}/analyze",
                "content_type": "application/json",
                "params": params,
                "source_record": ref,
            }
        )
    elif refs:
        requests.extend(
            {
                "method": "GET",
                "path": (
                    f"/api/v1/transcripts/{ref['id']}"
                    if ref["source_type"] == "transcript"
                    else f"/api/v1/followup-records/{ref['id']}"
                ),
                "source_record": ref,
            }
            for ref in refs
        )
        requests.append(
            {
                "method": "POST",
                "path": "/api/v1/transcript/upload",
                "content_type": "multipart/form-data",
                "form": {
                    "company_name_hint": args.company_name or "",
                    "company_id": args.company_id or "",
                },
                "generated_file": {
                    "field": "files",
                    "name": args.merged_file_name,
                    "source_records": refs,
                },
                "follow_up": "POST /api/v1/transcripts/{transcript_id}/analyze",
            }
        )
        notes.append("多条已有记录需要先拉详情，按来源边界合并成临时 txt，再上传并启动分析。")

    if not requests:
        raise ValueError("expectation-scene analyze requires --upload-file, --transcript-id, or --followup-record-id")

    return CapabilityRequestPlan(
        capability="expectation_scene",
        action="analyze",
        write_risk="none",
        requests=requests,
        notes=notes or ["分析阶段只生成操作卡片，不写回简道云。写回必须走 operations review/execute。"],
    )


def build_power_map_chat_plan(args: argparse.Namespace) -> CapabilityRequestPlan:
    payload: dict[str, Any] = {"message": args.message, "confirm": False}
    if args.version:
        payload["version"] = args.version
    return CapabilityRequestPlan(
        capability="power_map",
        action="chat",
        write_risk="preview_session",
        requests=[
            {
                "method": "POST",
                "path": f"/api/v1/power-map/{args.company_id}/chat_v2",
                "content_type": "application/json",
                "accept": "text/event-stream",
                "json": payload,
                "summary": {
                    "company_id": args.company_id,
                    "version": args.version or "",
                    "message_chars": len(args.message or ""),
                },
            }
        ],
        notes=[
            "chat_v2 每次创建新会话，不接受旧 session_id。",
            "只有后续显式 commit 且携带 SSE 返回的 session_id 才会写回 Power Map。",
        ],
    )


def build_plan(args: argparse.Namespace) -> CapabilityRequestPlan:
    if args.capability == "followup" and args.followup_action == "generate":
        return build_followup_generate_plan(args)
    if args.capability == "expectation-scene" and args.expectation_action == "analyze":
        return build_expectation_scene_analyze_plan(args)
    if args.capability == "power-map" and args.power_map_action == "chat":
        return build_power_map_chat_plan(args)
    raise ValueError("unsupported capability action")


async def _post_json(api_base: str, token: str | None, request: dict[str, Any]) -> Any:
    async with httpx.AsyncClient(timeout=httpx.Timeout(300.0)) as client:
        resp = await client.post(
            api_base.rstrip("/") + request["path"],
            headers={**_auth_headers(token), "Content-Type": "application/json"},
            params=request.get("params") or None,
            json=request.get("json") or {},
        )
        resp.raise_for_status()
        return resp.json()


async def _upload_files(api_base: str, token: str | None, request: dict[str, Any]) -> Any:
    files = []
    handles = []
    try:
        for item in request.get("files") or []:
            handle = Path(item["path"]).open("rb")
            handles.append(handle)
            files.append((item["field"], (Path(item["path"]).name, handle)))
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0)) as client:
            resp = await client.post(
                api_base.rstrip("/") + request["path"],
                headers=_auth_headers(token),
                data=request.get("form") or {},
                files=files,
            )
            resp.raise_for_status()
            return resp.json()
    finally:
        for handle in handles:
            handle.close()


async def _upload_generated_file(
    api_base: str,
    token: str | None,
    request: dict[str, Any],
    record_details: list[dict[str, Any]],
) -> Any:
    merged_text = _build_merged_record_text(record_details)
    if not merged_text.strip():
        raise ValueError("generated merge upload has no raw_text content")

    generated = request.get("generated_file") or {}
    file_name = str(generated.get("name") or "合并分析.txt")
    files = [(str(generated.get("field") or "files"), (file_name, merged_text.encode("utf-8"), "text/plain"))]
    async with httpx.AsyncClient(timeout=httpx.Timeout(300.0)) as client:
        resp = await client.post(
            api_base.rstrip("/") + request["path"],
            headers=_auth_headers(token),
            data=request.get("form") or {},
            files=files,
        )
        resp.raise_for_status()
        return resp.json()


async def execute_plan(plan: CapabilityRequestPlan, api_base: str, token: str | None) -> dict[str, Any]:
    results = []
    fetched_records: dict[tuple[str, str], dict[str, Any]] = {}
    for req in plan.requests:
        method = req.get("method")
        if method == "GET":
            async with httpx.AsyncClient(timeout=httpx.Timeout(300.0)) as client:
                resp = await client.get(api_base.rstrip("/") + req["path"], headers=_auth_headers(token))
                resp.raise_for_status()
                result = resp.json()
                source_record = req.get("source_record") or {}
                if source_record.get("source_type") and source_record.get("id"):
                    result = {**result, "_source_type": source_record["source_type"], "_source_id": source_record["id"]}
                    fetched_records[(source_record["source_type"], source_record["id"])] = result
                results.append(result)
        elif req.get("content_type") == "multipart/form-data" and req.get("files"):
            result = await _upload_files(api_base, token, req)
            results.append(result)
            if req.get("follow_up") and result.get("transcript_id"):
                follow_req = {
                    "method": "POST",
                    "path": f"/api/v1/transcripts/{result['transcript_id']}/analyze",
                    "content_type": "application/json",
                    "json": {},
                }
                results.append(await _post_json(api_base, token, follow_req))
        elif req.get("content_type") == "multipart/form-data" and req.get("generated_file"):
            generated = req.get("generated_file") or {}
            source_records = generated.get("source_records") or []
            details = [
                fetched_records[(ref["source_type"], ref["id"])]
                for ref in source_records
                if (ref.get("source_type"), ref.get("id")) in fetched_records
            ]
            if len(details) != len(source_records):
                raise ValueError("generated merge upload requires fetched source record details")
            result = await _upload_generated_file(api_base, token, req, details)
            results.append(result)
            if req.get("follow_up") and result.get("transcript_id"):
                follow_req = {
                    "method": "POST",
                    "path": f"/api/v1/transcripts/{result['transcript_id']}/analyze",
                    "content_type": "application/json",
                    "json": {},
                }
                results.append(await _post_json(api_base, token, follow_req))
        elif method == "POST" and req.get("accept") == "text/event-stream":
            raw_lines = []
            async with httpx.AsyncClient(timeout=httpx.Timeout(600.0)) as client:
                async with client.stream(
                    "POST",
                    api_base.rstrip("/") + req["path"],
                    headers={**_auth_headers(token), "Content-Type": "application/json", "Accept": "text/event-stream"},
                    json=req.get("json") or {},
                ) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if line.startswith("event:") or line.startswith("data:"):
                            raw_lines.append(line)
                        elif line == "":
                            raw_lines.append(line)
            results.append({"raw_lines": raw_lines, **_parse_sse_event_lines(raw_lines)})
        elif method == "POST":
            results.append(await _post_json(api_base, token, req))
        else:
            raise ValueError(f"unsupported request: {req}")
    return {"ok": True, "results": results}


def _print_json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Thin CLI wrapper for Zhidang capability HTTP contracts.")
    parser.add_argument("--api-base", default=os.getenv("ZHIDANG_API_BASE", DEFAULT_API_BASE))
    parser.add_argument("--token", default=os.getenv("ZHIDANG_TOKEN", ""))
    parser.add_argument("--execute", action="store_true", help="Actually call Zhidang HTTP APIs. Default is dry-run only.")

    sub = parser.add_subparsers(dest="capability", required=True)

    followup = sub.add_parser("followup")
    followup_sub = followup.add_subparsers(dest="followup_action", required=True)
    followup_gen = followup_sub.add_parser("generate")
    followup_gen.add_argument("--company-id", default="")
    followup_gen.add_argument("--company-name", required=True)
    followup_gen.add_argument("--text", default="")
    followup_gen.add_argument("--text-file")
    followup_gen.add_argument("--image-file", action="append", default=[])

    exp = sub.add_parser("expectation-scene")
    exp_sub = exp.add_subparsers(dest="expectation_action", required=True)
    exp_analyze = exp_sub.add_parser("analyze")
    exp_analyze.add_argument("--company-id", default="")
    exp_analyze.add_argument("--company-name", default="")
    exp_analyze.add_argument("--upload-file", action="append", default=[])
    exp_analyze.add_argument("--transcript-id", action="append", default=[])
    exp_analyze.add_argument("--followup-record-id", action="append", default=[])
    exp_analyze.add_argument("--force-merge", action="store_true")
    exp_analyze.add_argument("--start-analysis", action="store_true", default=True)
    exp_analyze.add_argument("--merged-file-name", default="合并分析.txt")

    power = sub.add_parser("power-map")
    power_sub = power.add_subparsers(dest="power_map_action", required=True)
    power_chat = power_sub.add_parser("chat")
    power_chat.add_argument("--company-id", required=True)
    power_chat.add_argument("--version", default="")
    power_chat.add_argument("--message", required=True)

    return parser


async def async_main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        plan = build_plan(args)
        if not args.execute:
            _print_json({"dry_run": True, **plan.to_dict()})
            return 0
        if not args.token:
            raise ValueError("--execute requires --token or ZHIDANG_TOKEN")
        result = await execute_plan(plan, args.api_base, args.token)
        _print_json({"dry_run": False, "plan": plan.to_dict(), "result": result})
        return 0
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


def main() -> None:
    raise SystemExit(asyncio.run(async_main()))


if __name__ == "__main__":
    main()
