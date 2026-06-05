"""异步效率评审模块。

在 _run_llm_tool_loop 收敛后异步执行，将精简的工具调用 trace 发送给
DeepSeek V4 Pro 做流程效率分析，评审结果落盘供人工每周审核。

入口：async_efficiency_review(trace, cfg) — fire-and-forget，不阻塞主流程。
"""
from __future__ import annotations

import json
import logging
import os
import random
import time
from datetime import date
from typing import Any

from .openai_compatible_agent_client import OpenAICompatibleAgentClient
from ..crypto_utils import decrypt_secret

logger = logging.getLogger("zhidang.review")

REVIEW_OUTPUT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "efficiency_reviews",
)

EFFICIENCY_REVIEW_PROMPT = """你是流程效率分析师。审视下面这段权力地图操作的工具调用序列，
找出冗余、次序不当、可合并的操作。

严格规则：
1. 只分析效率，不分析对错
2. 不建议添加新工具
3. 每个 finding 必须给出 evidence_rounds（涉及的轮次号）
4. 如果 pattern 反复出现，用 suggested_sop 描述 SOP 优化建议——这个字段后续可能直接加进 system prompt
5. 输出必须是合法 JSON，不要任何额外解释文字

输出 JSON schema：
{
  "efficiency_score": 1-10,
  "actual_rounds": <int>,
  "estimated_optimal_rounds": <int>,
  "redundancy_findings": [
    {
      "type": "顺序不当|重复调用|可批量化|可省略",
      "evidence_rounds": [<int>, ...],
      "description": "<具体描述>",
      "suggested_sop": "<一句话 SOP>",
      "expected_savings": {
        "rounds_saved": <int>,
        "applicable_to_rounds": [<int>, ...]
      }
    }
  ],
  "positive_patterns": ["<本次做得好的 1-2 点>"]
}"""


def _is_graph_state_block(text: str) -> bool:
    """判断文本块是否为 power-map 的 graph_state 布局数据块。"""
    markers = ("【角色节点列表】", "【汇报关系列表】", "[角色节点]", "[汇报关系]", "角色节点列表",
               "汇报关系列表", "当前布局数据", "grid items", "container_id",
               "_ToolCallSummary", "【可用工具列表】")
    return any(m in text for m in markers) or text.strip().startswith("layout_summary")


def extract_trace_from_messages(
    accumulated_messages: list[dict[str, Any]],
    session_id: str,
    user_query: str,
    rounds_completed: int,
    exit_reason: str,
    executed: int,
) -> dict[str, Any]:
    """从 accumulated_messages 提取精简 trace。

    精简规则：
    - 跳过 image_url 类型的 content block（截图）
    - 跳过 user message 中的 graph_state text block
    - 工具调用按 assistant(tool_calls) → tool(result) 聚合为 round
    - 每个调用保留: tool_name, args_brief(≤500c), ok, result_brief(≤200c)
    """
    tool_call_sequence: list[dict[str, Any]] = []
    current_round = 0
    pending_tool_names: list[str] = []

    for msg in accumulated_messages:
        role = str(msg.get("role", ""))

        if role == "assistant":
            tool_calls = msg.get("tool_calls") or []
            if not tool_calls:
                continue
            current_round += 1
            pending_tool_names = []
            calls: list[dict[str, Any]] = []
            for tc in tool_calls:
                fn = (tc.get("function") or {}) if isinstance(tc, dict) else {}
                name = str(fn.get("name", ""))
                args_text = str(fn.get("arguments", ""))
                calls.append({
                    "tool_name": name,
                    "args_brief": args_text[:500],
                    "ok": None,
                    "result_brief": "",
                })
                pending_tool_names.append(name)
            tool_call_sequence.append({"round": current_round, "calls_pending": calls, "tool_names_in_order": list(pending_tool_names)})

        elif role == "tool":
            tc_id = str(msg.get("tool_call_id", ""))
            content = str(msg.get("content", ""))
            ok = False
            result_brief = content[:200]
            try:
                parsed = json.loads(content)
                if isinstance(parsed, dict):
                    ok = bool(parsed.get("ok", False))
                    result_brief = json.dumps(parsed, ensure_ascii=False)[:200]
            except (json.JSONDecodeError, TypeError):
                ok = "error" not in content.lower()

            if current_round > 0 and tool_call_sequence:
                last_round = tool_call_sequence[-1]
                pending = last_round.get("calls_pending", [])
                idx = len(pending) - len(last_round.get("tool_names_in_order", []))
                for i, call in enumerate(pending):
                    if call.get("ok") is None:
                        call["ok"] = ok
                        call["result_brief"] = result_brief
                        if last_round.get("tool_names_in_order"):
                            last_round["tool_names_in_order"].pop(0)
                        break

    # 清理中间字段：重命名 calls_pending → calls
    for r in tool_call_sequence:
        pending = r.pop("calls_pending", [])
        r.pop("tool_names_in_order", None)
        r["calls"] = pending

    return {
        "session_id": session_id,
        "user_query": user_query,
        "rounds_completed": rounds_completed,
        "exit_reason": exit_reason,
        "executed_tool_count": executed,
        "tool_call_sequence": tool_call_sequence,
    }


def should_review(rounds_completed: int, exit_reason: str) -> bool:
    """采样策略：判断是否需要触发效率评审。

    - exit_reason == "max_rounds_hit" → 必审（可能有死循环风险）
    - rounds_completed <= 8 → 不审（太简单没价值）
    - rounds_completed >= 25 → 必审（复杂任务）
    - 其他 → 20% 随机采样
    """
    if exit_reason == "max_rounds_hit":
        return True
    if rounds_completed <= 8:
        return False
    if rounds_completed >= 25:
        return True
    return random.random() < 0.2


def _get_review_llm_client(cfg: Any) -> OpenAICompatibleAgentClient:
    """复用现有 LLM 配置构建客户端，model 硬编码为 deepseek-v4-pro。"""
    api_key = decrypt_secret(cfg.llm_api_key_encrypted) or ""
    base_url = (cfg.llm_base_url or "").strip()
    if not api_key:
        raise ValueError("LLM API Key 未配置")
    if not base_url:
        raise ValueError("LLM Base URL 未配置")
    return OpenAICompatibleAgentClient(base_url=base_url, api_key=api_key)


async def async_efficiency_review(trace: dict[str, Any], cfg: Any) -> None:
    """异步评审入口（fire-and-forget）。

    1. 通过 OpenAICompatibleAgentClient 调用 DeepSeek V4 Pro
    2. 解析 JSON 输出（失败时存原始文本，不抛异常）
    3. 落盘到 efficiency_reviews/{YYYY-MM-DD}/{session_id}.review.json
    4. trace 同步落盘到 efficiency_reviews/{YYYY-MM-DD}/{session_id}.trace.json
    """
    session_id = str(trace.get("session_id", "unknown"))
    today = date.today().isoformat()
    out_dir = os.path.join(REVIEW_OUTPUT_DIR, today)
    trace_path = os.path.join(out_dir, f"{session_id}.trace.json")
    review_path = os.path.join(out_dir, f"{session_id}.review.json")

    try:
        os.makedirs(out_dir, exist_ok=True)
    except OSError:
        logger.warning("[DEBUG-J review] failed to create output dir: %s", out_dir)
        return

    # 落盘 trace（无论评审成败都保存）
    try:
        with open(trace_path, "w", encoding="utf-8") as f:
            json.dump(trace, f, ensure_ascii=False, indent=2, default=str)
        _size = os.path.getsize(trace_path)
        logger.info("[DEBUG-J review] trace saved: %s (%d bytes)", trace_path, _size)
    except Exception as exc:
        logger.warning("[DEBUG-J review] failed to write trace: %s", exc)

    # 调用 DeepSeek 评审
    try:
        client = _get_review_llm_client(cfg)
    except Exception as exc:
        logger.warning("[DEBUG-J review] LLM client init failed for session=%s: %s", session_id, exc)
        return

    rounds = trace.get("rounds_completed", "?")
    executed = trace.get("executed_tool_count", "?")
    exit_reason = trace.get("exit_reason", "?")

    messages = [
        {"role": "user", "content": json.dumps(trace, ensure_ascii=False, default=str)},
    ]

    t_start = time.monotonic()
    try:
        resp = await client.messages_create(
            model="deepseek-v4-pro",
            system=EFFICIENCY_REVIEW_PROMPT,
            messages=messages,
            max_tokens=4096,
            temperature=0.2,
        )
        raw_text = ""
        for block in resp.content:
            if getattr(block, "type", "") == "text":
                raw_text += str(getattr(block, "text", ""))
        raw_text = raw_text.strip()

        if not raw_text:
            logger.warning("[DEBUG-J review] empty response for session=%s", session_id)
            return

        # 尝试解析 JSON
        parsed = None
        text = raw_text
        if text.startswith("```"):
            lines = text.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            pass

        elapsed_ms = int((time.monotonic() - t_start) * 1000)
        out = {
            "session_id": session_id,
            "reviewed_at": date.today().isoformat(),
            "model": "deepseek-v4-pro",
            "latency_ms": elapsed_ms,
            "rounds": rounds,
            "executed": executed,
            "exit_reason": exit_reason,
            "parsed": parsed is not None,
        }
        if parsed is not None:
            out["review"] = parsed
            logger.info("[DEBUG-J review] review saved (parsed) for session=%s rounds=%s elapsed=%dms",
                        session_id, rounds, elapsed_ms)
        else:
            out["raw_text"] = raw_text
            logger.info("[DEBUG-J review] review saved (raw) for session=%s rounds=%s elapsed=%dms",
                        session_id, rounds, elapsed_ms)

        with open(review_path, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2, default=str)

    except Exception as exc:
        elapsed_ms = int((time.monotonic() - t_start) * 1000)
        logger.warning("[DEBUG-J review] DeepSeek call failed for session=%s: %s (elapsed=%dms)",
                       session_id, exc, elapsed_ms)
        # 保存失败信息
        try:
            with open(review_path, "w", encoding="utf-8") as f:
                json.dump({
                    "session_id": session_id,
                    "reviewed_at": date.today().isoformat(),
                    "model": "deepseek-v4-pro",
                    "error": str(exc),
                    "latency_ms": elapsed_ms,
                }, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
