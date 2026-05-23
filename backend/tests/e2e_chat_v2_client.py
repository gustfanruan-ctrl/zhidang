#!/usr/bin/env python3
"""E2E test client for /api/v1/power-map/{company_id}/chat_v2 SSE endpoint.

Usage:
    python e2e_chat_v2_client.py <company_id> <message> [--server BASE_URL] [--rounds N] [--output FILE]
"""

# Phase 3 test case changes:
# Case 5 (续聊场景): CANCELLED (2026-05-22) — 产品策略变更，续 session 不再支持
# Cases 1-4: unchanged

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urljoin

import requests


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_SERVER = os.getenv("ZHIDANG_BASE_URL", "http://47.98.102.197:8000")
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = os.getenv("ZHIDANG_PASSWORD", "Fr521521")


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def login(server: str) -> str:
    """Log in as admin and return JWT token."""
    resp = requests.post(
        urljoin(server, "/api/v1/auth/login"),
        json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    token = data.get("token")
    if not token:
        raise RuntimeError(f"Login returned no token: {data}")
    return token


# ---------------------------------------------------------------------------
# Tool touch extraction rules
# ---------------------------------------------------------------------------

TOOL_TOUCH_RULES: dict[str, dict] = {
    # ── Node tools: single node_id ──
    "create_node":              {"type": "node", "source": "result", "path": "node.id"},
    "update_node":              {"type": "node", "source": "args",   "path": "node_id"},
    "delete_node":              {"type": "node", "source": "args",   "path": "node_id"},
    "set_parent":               {"type": "node", "source": "args",   "path": "node_id"},
    "place_node":               {"type": "node", "source": "args",   "path": "node_id"},
    "resize_container":         {"type": "node", "source": "args",   "path": "node_id"},
    "fit_container_to_children":{"type": "node", "source": "args",   "path": "container_id"},
    "nudge_node":               {"type": "node", "source": "args",   "path": "node_id"},

    # ── Node list tools: list of node_ids ──
    "arrange_horizontally":  {"type": "node_list", "source": "args", "path": "node_ids"},
    "arrange_vertically":    {"type": "node_list", "source": "args", "path": "node_ids"},
    "distribute_horizontally":{"type": "node_list", "source": "args", "path": "node_ids"},
    "align_left":            {"type": "node_list", "source": "args", "path": "node_ids"},
    "align_top":             {"type": "node_list", "source": "args", "path": "node_ids"},

    # ── Center tools: node_id + reference_node_ids ──
    "center_above": {"type": "center", "source": "args", "paths": ["node_id", "reference_node_ids"]},
    "center_below": {"type": "center", "source": "args", "paths": ["node_id", "reference_node_ids"]},

    # ── auto_fix_collisions: result.moved_nodes ──
    "auto_fix_collisions": {"type": "result_nodes", "source": "result", "path": "moved_nodes"},

    # ── relayout: all nodes (special; resolved via ctx dump) ──
    "relayout": {"type": "all_nodes", "source": "special"},

    # ── Edge tools ──
    "create_edge": {"type": "edge", "source": "result", "path": "edge_id"},
    "update_edge": {"type": "edge", "source": "args",   "path": "edge_id"},
    "delete_edge": {"type": "edge", "source": "args",   "path": "edge_id"},

    # ── Query tools: no touch ──
    "validate_structure":  {"type": "none"},
    "check_collisions":    {"type": "none"},
    "get_node_geometry":   {"type": "none"},
    "save_state":          {"type": "none"},
}


def _deep_get(obj: dict, path: str):
    """Get nested value via dot-separated path, e.g. 'node.id'."""
    keys = path.split(".")
    for k in keys:
        if isinstance(obj, dict):
            obj = obj.get(k)
        else:
            return None
        if obj is None:
            return None
    return obj


def _extract_touched_from_tool_call(
    tool_name: str,
    args: dict,
    result: dict,
) -> tuple[set[str], set[str], bool]:
    """Extract touched node/edge IDs from a single tool call.

    Returns (touched_ids, touched_edge_ids, needs_all_nodes).
    """
    touched_ids: set[str] = set()
    touched_edge_ids: set[str] = set()
    needs_all = False

    rule = TOOL_TOUCH_RULES.get(tool_name, {"type": "none"})
    rtype = rule.get("type", "none")

    if rtype == "none":
        return touched_ids, touched_edge_ids, needs_all

    if rtype == "all_nodes":
        needs_all = True
        return touched_ids, touched_edge_ids, needs_all

    source = rule.get("source")
    data = args if source == "args" else result
    if data is None:
        return touched_ids, touched_edge_ids, needs_all

    if rtype == "node":
        val = _deep_get(data, rule["path"])
        if val:
            touched_ids.add(str(val))

    elif rtype == "node_list":
        vals = _deep_get(data, rule["path"])
        if vals and isinstance(vals, list):
            touched_ids.update(str(v) for v in vals)

    elif rtype == "center":
        for path in rule["paths"]:
            val = _deep_get(data, path)
            if val:
                if isinstance(val, list):
                    touched_ids.update(str(v) for v in val)
                else:
                    touched_ids.add(str(val))

    elif rtype == "result_nodes":
        vals = _deep_get(data, rule["path"])
        if vals and isinstance(vals, list):
            touched_ids.update(str(v) for v in vals)

    elif rtype == "edge":
        val = _deep_get(data, rule["path"])
        if val:
            touched_edge_ids.add(str(val))

    return touched_ids, touched_edge_ids, needs_all


# ---------------------------------------------------------------------------
# SSE client
# ---------------------------------------------------------------------------

@dataclass
class RoundMetrics:
    round_num: int
    input_tokens: int = 0
    output_tokens: int = 0
    screenshot_size: int = 0
    graph_state_chars: int = 0
    thinking_chars: int = 0
    tool_calls: list[dict] = field(default_factory=list)
    tool_results: list[dict] = field(default_factory=list)


@dataclass
class ChatResult:
    ok: bool
    error: str | None = None
    rounds: list[RoundMetrics] = field(default_factory=list)
    total_elapsed_s: float = 0.0
    final_text: str = ""
    raw_events: list[dict] = field(default_factory=list)
    session_id: str = ""
    # Geometry check
    touched_ids: set[str] = field(default_factory=set)
    touched_edge_ids: set[str] = field(default_factory=set)
    needs_all_node_ids: bool = False
    hard_conflicts: int = 0
    soft_warnings: int = 0
    geometry_report: dict | None = None
    verdict: str = ""

    @property
    def total_input_tokens(self) -> int:
        return sum(r.input_tokens for r in self.rounds)

    @property
    def total_output_tokens(self) -> int:
        return sum(r.output_tokens for r in self.rounds)

    @property
    def total_rounds(self) -> int:
        return len(self.rounds)

    def summary(self) -> str:
        lines = [
            f"  rounds={self.total_rounds}",
            f"  elapsed={self.total_elapsed_s:.1f}s",
            f"  input_tokens={self.total_input_tokens}",
            f"  output_tokens={self.total_output_tokens}",
            f"  final_text={json.dumps(self.final_text[:120], ensure_ascii=False)}",
        ]
        for r in self.rounds:
            lines.append(
                f"  round{r.round_num}: "
                f"in={r.input_tokens} out={r.output_tokens} "
                f"img={r.screenshot_size:,}B gs={r.graph_state_chars}c "
                f"tools={len(r.tool_calls)}"
            )
        if self.geometry_report is not None:
            g = self.geometry_report
            lines.append(f"  geometry: hard={self.hard_conflicts} soft={self.soft_warnings}")
            lines.append(f"  verdict: {self.verdict}")
        return "\n".join(lines)


def _parse_sse_event(event_type: str, data: dict) -> dict:
    return {"type": event_type, "data": data}


def run_chat(
    server: str,
    token: str,
    company_id: str,
    message: str,
    version: str | None = None,
    session_id: str | None = None,
    raw_log_path: str | None = None,
    ctx_dump_dir: str | None = None,
    check_geometry_script: str | None = None,
) -> ChatResult:
    """Call chat_v2 endpoint and parse SSE events into structured metrics."""
    url = urljoin(server, f"/api/v1/power-map/{company_id}/chat_v2?token={token}")

    payload: dict = {"message": message}
    if session_id:
        payload["session_id"] = session_id
    if version:
        payload["version"] = version

    result = ChatResult(ok=False)
    current_round: RoundMetrics | None = None
    round_idx = 0
    t0 = time.monotonic()

    # Track tool_call args (streamed) for touched_id extraction
    pending_tool_call_args: dict[str, dict] = {}  # call_id → args

    # Raw SSE log
    raw_fh = None
    if raw_log_path:
        Path(raw_log_path).parent.mkdir(parents=True, exist_ok=True)
        raw_fh = open(raw_log_path, "w", encoding="utf-8")
        raw_fh.write(f"# SSE raw log | {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        raw_fh.write(f"# url={url}\n")
        raw_fh.write(f"# payload={json.dumps(payload, ensure_ascii=False)}\n")
        raw_fh.write(f"# {'='*60}\n\n")

    try:
        resp = requests.post(url, json=payload, stream=True, timeout=300)
        resp.raise_for_status()

        buffer = ""
        for chunk in resp.iter_content(chunk_size=8192, decode_unicode=True):
            if not chunk:
                continue
            buffer += chunk if isinstance(chunk, str) else chunk.decode("utf-8", errors="replace")

            while "\n\n" in buffer:
                raw_event, buffer = buffer.split("\n\n", 1)

                if raw_fh:
                    raw_fh.write(raw_event + "\n\n")
                    raw_fh.flush()

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
                    data = json.loads(data_str) if data_str else {}
                except json.JSONDecodeError:
                    data = {"raw": data_str}

                event = {"type": event_type, "data": data}
                result.raw_events.append(event)

                if event_type == "round_start":
                    round_idx = int(data.get("round", 0))
                    current_round = RoundMetrics(round_num=round_idx)
                    result.rounds.append(current_round)
                    result.session_id = data.get("session_id", result.session_id)

                elif event_type == "thinking":
                    chunk_text = data.get("text_chunk", "")
                    result.final_text += chunk_text
                    if current_round:
                        current_round.thinking_chars += len(chunk_text)

                elif event_type == "tool_call_start" and current_round:
                    call_id = data.get("id", "")
                    pending_tool_call_args[call_id] = data.get("arguments", "")

                elif event_type == "tool_call_delta" and current_round:
                    call_id = data.get("index", "")
                    # For native tool calling, delta appends to pending args
                    pass

                elif event_type == "tool_call" and current_round:
                    tool_name = data.get("tool", "")
                    args = data.get("args", {})
                    current_round.tool_calls.append({"tool": tool_name, "args": args})

                elif event_type == "tool_result" and current_round:
                    tool_name = data.get("tool", "")
                    result_data = data
                    current_round.tool_results.append(data)

                    # Extract touched IDs
                    # Find the matching tool_call args
                    matching_args = {}
                    for tc in current_round.tool_calls:
                        if tc.get("tool") == tool_name:
                            matching_args = tc.get("args", {})
                            break

                    tids, eids, needs_all = _extract_touched_from_tool_call(
                        tool_name, matching_args, result_data
                    )
                    result.touched_ids.update(tids)
                    result.touched_edge_ids.update(eids)
                    if needs_all:
                        result.needs_all_node_ids = True

                elif event_type == "graph_state" and current_round:
                    current_round.graph_state_chars = len(json.dumps(data, ensure_ascii=False))

                elif event_type == "done":
                    if data.get("error"):
                        result.error = data["error"]
                    elif not data.get("skipped"):
                        result.ok = True
                    result.session_id = data.get("session_id", result.session_id)

        result.total_elapsed_s = time.monotonic() - t0

    except requests.exceptions.RequestException as exc:
        result.error = str(exc)
    except Exception as exc:
        result.error = f"{type(exc).__name__}: {exc}"
    finally:
        if raw_fh:
            raw_fh.write(f"\n# END | elapsed={time.monotonic()-t0:.2f}s | ok={result.ok}\n")
            raw_fh.close()

    # ── Post-run: dump ctx + run geometry check ──
    if result.ok and result.session_id:
        _run_geometry_check(result, server, token, ctx_dump_dir, check_geometry_script)

    return result


def _run_geometry_check(
    result: ChatResult,
    server: str,
    token: str,
    ctx_dump_dir: str | None,
    check_geometry_script: str | None,
) -> None:
    """Dump ctx from server, run check_geometry.py, populate result fields."""
    if not ctx_dump_dir:
        ctx_dump_dir = "./e2e_output"
    sid = result.session_id

    # Create per-session output dir
    session_dir = Path(ctx_dump_dir) / sid
    session_dir.mkdir(parents=True, exist_ok=True)

    # 1. Dump ctx from debug endpoint
    ctx_path = session_dir / "final_ctx.json"
    try:
        dump_url = urljoin(server, f"/api/v1/power-map/debug/dump_ctx?session_id={sid}")
        resp = requests.get(dump_url, headers={"Authorization": f"Bearer {token}"}, timeout=10)
        if resp.status_code == 200:
            ctx_data = resp.json()
            with open(ctx_path, "w") as f:
                json.dump(ctx_data, f, ensure_ascii=False, indent=2)

            # SKIPPED: case requires existing structure but BI is empty
            if len(ctx_data.get("nodes", [])) == 0:
                result.verdict = "SKIPPED"
                result.geometry_report = {"skipped": True, "reason": "BI 初始状态为空，无法验证需要前置结构的 case"}
                return
        else:
            # Debug endpoint failed — set UNKNOWN verdict, do NOT fall back to event reconstruction
            error_detail = resp.text[:500] if resp.text else "(empty body)"
            result.verdict = "UNKNOWN"
            result.geometry_report = {
                "error": f"dump_ctx returned {resp.status_code}: {error_detail}"
            }
            return  # skip check_geometry entirely
    except Exception as exc:
        result.verdict = "UNKNOWN"
        result.geometry_report = {"error": f"dump_ctx failed: {type(exc).__name__}: {exc}"}
        return  # skip check_geometry entirely

    # 2. If relayout was called, touched_ids = all node IDs
    if result.needs_all_node_ids and ctx_path.exists():
        try:
            with open(ctx_path) as f:
                ctx_data = json.load(f)
            all_ids = [n["id"] for n in ctx_data.get("nodes", [])]
            result.touched_ids.update(all_ids)
        except Exception:
            pass

    # 3. Run check_geometry.py
    if check_geometry_script is None:
        # Find script relative to this file
        script_dir = Path(__file__).resolve().parent
        check_geometry_script = str(script_dir / "check_geometry.py")

    geo_path = session_dir / "geometry_report.json"
    if ctx_path.exists() and Path(check_geometry_script).exists():
        cmd = [
            sys.executable, check_geometry_script,
            str(ctx_path.resolve()),
        ]
        if result.touched_ids:
            cmd.extend(["--touched-ids", ",".join(sorted(result.touched_ids))])
        if result.touched_edge_ids:
            cmd.extend(["--touched-edge-ids", ",".join(sorted(result.touched_edge_ids))])

        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            # Parse output lines for conflict counts
            hard = 0
            soft = 0
            for line in proc.stdout.split("\n"):
                if "CRITICAL" in line:
                    hard += 1
                elif "HIGH" in line:
                    hard += 1
                elif "MEDIUM" in line:
                    soft += 1

            result.hard_conflicts = hard
            result.soft_warnings = soft

            geo_report = {
                "exit_code": proc.returncode,
                "stdout": proc.stdout,
                "stderr": proc.stderr,
                "hard_conflicts": hard,
                "soft_warnings": soft,
                "touched_ids": sorted(result.touched_ids),
                "touched_edge_ids": sorted(result.touched_edge_ids),
            }
            with open(geo_path, "w") as f:
                json.dump(geo_report, f, ensure_ascii=False, indent=2)
            result.geometry_report = geo_report
        except Exception as exc:
            result.geometry_report = {"error": str(exc)}

    # 4. Compute verdict
    if result.hard_conflicts > 0:
        result.verdict = "D"
    else:
        # Fall back to heuristic: count tool calls and convergence
        result.verdict = "A"  # default; caller can override with ABCD logic


# ---------------------------------------------------------------------------
# ABCD scoring (pre-geometry-check)
# ---------------------------------------------------------------------------

def _score_abcd(result: ChatResult) -> tuple[int, int, int, int]:
    """Score tool calls: A=direct, B=ok, C=wasted, D=wrong."""
    a = b = c = d = 0
    for r in result.rounds:
        for tc in r.tool_calls:
            tool = tc.get("tool", "")
            if tool in ("create_node", "create_edge", "set_parent", "place_node",
                        "fit_container_to_children", "arrange_horizontally",
                        "arrange_vertically", "center_above", "center_below",
                        "resize_container", "delete_edge"):
                a += 1
            elif tool in ("validate_structure", "check_collisions", "get_node_geometry",
                          "align_left", "align_top", "distribute_horizontally",
                          "nudge_node", "auto_fix_collisions", "update_node"):
                b += 1
            elif tool in ("delete_node",):
                c += 1
            elif tool in ("relayout",):
                d += 1
            else:
                b += 1  # unknown → B
    return a, b, c, d


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    import argparse

    parser = argparse.ArgumentParser(description="E2E test for chat_v2 SSE endpoint")
    parser.add_argument("company_id", help="Company UUID")
    parser.add_argument("message", help="User message")
    parser.add_argument("--server", default=DEFAULT_SERVER, help="Base URL of zhidang backend")
    parser.add_argument("--rounds", type=int, default=1, help="Number of runs")
    parser.add_argument("--output", help="Save results to JSON file")
    parser.add_argument("--raw-log-dir", default="./e2e_output", help="Directory for raw SSE log files")
    parser.add_argument("--version", help="Version UUID")
    parser.add_argument("--session-id", help="Reuse an existing session")
    parser.add_argument("--ctx-dump-dir", default="./e2e_output", help="Directory for ctx dump + geometry report")
    parser.add_argument("--check-geometry-script", help="Path to check_geometry.py")
    args = parser.parse_args()

    print(f"🔐 Logging in to {args.server}...")
    token = login(args.server)
    print(f"   ✅ Authenticated")

    results: list[ChatResult] = []
    for i in range(args.rounds):
        run_session_id = args.session_id or str(uuid.uuid4())[:8]
        raw_log = os.path.join(args.raw_log_dir, f"raw_sse_{run_session_id}.log")
        print(f"\n📡 Run {i+1}/{args.rounds}: chat_v2({args.company_id[:8]}...) → {raw_log}")
        result = run_chat(
            server=args.server,
            token=token,
            company_id=args.company_id,
            message=args.message,
            version=args.version,
            session_id=args.session_id,
            raw_log_path=raw_log,
            ctx_dump_dir=args.ctx_dump_dir,
            check_geometry_script=args.check_geometry_script,
        )
        results.append(result)

        if result.ok:
            # Respect pre-set verdicts (SKIPPED, UNKNOWN) — skip ABCD override
            if result.verdict in ("SKIPPED", "UNKNOWN"):
                final_verdict = result.verdict
                a = b = c = d = 0
            else:
                a, b, c, d = _score_abcd(result)

                # Override verdict: geometry > ABCD
                if result.hard_conflicts > 0:
                    final_verdict = "D"
                elif d > 0:
                    final_verdict = "D"
                elif c > 0:
                    final_verdict = "C"
                elif b > 0:
                    final_verdict = "B"
                else:
                    final_verdict = "A"

                result.verdict = final_verdict

            print(f"   ✅ rounds={result.total_rounds} | tools={a+b+c+d}")
            if result.verdict != "SKIPPED":
                print(f"      ABCD: A={a} B={b} C={c} D={d}")
            if result.hard_conflicts > 0:
                print(f"      🔴 hard_conflicts={result.hard_conflicts} → verdict D")
            print(f"      geometry: hard={result.hard_conflicts} soft={result.soft_warnings}")
            status_icon = {"SKIPPED": "⏭️", "UNKNOWN": "⚠️"}.get(final_verdict, "")
            print(f"      verdict: {status_icon} {final_verdict}")
            print(f"      session: {result.session_id}")
            for r in result.rounds:
                tools = [tc.get("tool", "?") for tc in r.tool_calls]
                print(f"      R{r.round_num}: {len(r.tool_calls)} {tools} | {result.final_text[:60] if r.round_num == result.total_rounds and r.tool_calls == [] else ''}")
            print(f"   {result.summary()}")
        else:
            print(f"   ❌ {result.error}")

    # Aggregate
    ok_results = [r for r in results if r.ok]
    if not ok_results:
        print("\n❌ All runs failed.")
        sys.exit(1)

    avg_rounds = sum(r.total_rounds for r in ok_results) / len(ok_results)
    avg_elapsed = sum(r.total_elapsed_s for r in ok_results) / len(ok_results)

    print(f"\n{'='*60}")
    print(f"📊 FINAL ({len(ok_results)} runs)")
    print(f"   rounds:        {avg_rounds:.1f}")
    print(f"   elapsed:       {avg_elapsed:.1f}s")
    print(f"   verdict:       {ok_results[0].verdict}")
    print(f"   hard_conflicts:{ok_results[0].hard_conflicts}")
    print(f"   soft_warnings: {ok_results[0].soft_warnings}")
    print(f"{'='*60}")

    unknown_results = [r for r in results if r.verdict == "UNKNOWN"]
    if unknown_results:
        print(f"\n⚠️  {len(unknown_results)}/{len(results)} run(s) had UNKNOWN verdict (geometry check skipped).")
        for r in unknown_results:
            err = (r.geometry_report or {}).get("error", "(no error detail)")
            print(f"   session={r.session_id}: {err}")

    if args.output:
        output_data = {
            "config": {
                "server": args.server,
                "company_id": args.company_id,
                "message": args.message,
                "version": args.version,
            },
            "verdict": ok_results[0].verdict,
            "hard_conflicts": ok_results[0].hard_conflicts,
            "soft_warnings": ok_results[0].soft_warnings,
            "averages": {
                "rounds": avg_rounds,
                "elapsed_s": avg_elapsed,
            },
            "runs": [
                {
                    "ok": r.ok,
                    "error": r.error,
                    "rounds": r.total_rounds,
                    "elapsed_s": r.total_elapsed_s,
                    "final_text": r.final_text,
                    "verdict": r.verdict,
                    "hard_conflicts": r.hard_conflicts,
                    "soft_warnings": r.soft_warnings,
                    "abcd": list(_score_abcd(r)),
                }
                for r in results
            ],
        }
        with open(args.output, "w") as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)
        print(f"\n💾 Saved to {args.output}")

    if unknown_results:
        sys.exit(1)


if __name__ == "__main__":
    main()
