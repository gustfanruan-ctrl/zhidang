from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass
class _TextBlock:
    type: str
    text: str


@dataclass
class _ToolUseBlock:
    type: str
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class OpenAICompatibleResponse:
    stop_reason: str
    content: list[Any]


class OpenAICompatibleAgentClient:
    def __init__(self, *, base_url: str, api_key: str, request_timeout_seconds: int = 120, connect_timeout_seconds: int = 20) -> None:
        base = (base_url or "").rstrip("/")
        if not base:
            raise ValueError("OpenAI-compatible base_url 未配置")
        self.url = f"{base}/chat/completions"
        self.api_key = api_key
        self.timeout = httpx.Timeout(float(request_timeout_seconds), connect=float(connect_timeout_seconds))

    @staticmethod
    def _to_openai_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for tool in tools or []:
            result.append(
                {
                    "type": "function",
                    "function": {
                        "name": str(tool.get("name") or ""),
                        "description": str(tool.get("description") or ""),
                        "parameters": tool.get("input_schema") or {"type": "object", "properties": {}},
                    },
                }
            )
        return result

    @staticmethod
    def _to_openai_tool_choice(tool_choice: Any) -> Any:
        if not isinstance(tool_choice, dict):
            return "auto"
        if tool_choice.get("type") == "tool" and tool_choice.get("name"):
            return {"type": "function", "function": {"name": tool_choice["name"]}}
        return "auto"

    @staticmethod
    def _to_openai_messages(system: str, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = [{"role": "system", "content": system or ""}]
        for msg in messages or []:
            role = str(msg.get("role") or "")
            content = msg.get("content")
            if role == "assistant" and isinstance(content, list):
                text_parts: list[str] = []
                tool_calls: list[dict[str, Any]] = []
                for block in content:
                    if getattr(block, "type", "") == "text":
                        text = str(getattr(block, "text", "")).strip()
                        if text:
                            text_parts.append(text)
                    elif getattr(block, "type", "") == "tool_use":
                        tool_calls.append(
                            {
                                "id": getattr(block, "id", ""),
                                "type": "function",
                                "function": {
                                    "name": getattr(block, "name", ""),
                                    "arguments": json.dumps(getattr(block, "input", {}) or {}, ensure_ascii=False),
                                },
                            }
                        )
                payload: dict[str, Any] = {"role": "assistant", "content": "\n".join(text_parts).strip()}
                if tool_calls:
                    payload["tool_calls"] = tool_calls
                out.append(payload)
                continue

            if role == "user" and isinstance(content, list):
                tool_results = [item for item in content if isinstance(item, dict) and item.get("type") == "tool_result"]
                if tool_results and len(tool_results) == len(content):
                    for item in tool_results:
                        out.append(
                            {
                                "role": "tool",
                                "tool_call_id": str(item.get("tool_use_id") or ""),
                                "content": str(item.get("content") or ""),
                            }
                        )
                    continue

            out.append({"role": role or "user", "content": content if isinstance(content, str) else str(content or "")})
        return out

    @staticmethod
    def _from_openai_message(message: dict[str, Any]) -> OpenAICompatibleResponse:
        content_blocks: list[Any] = []
        text = message.get("content")
        if isinstance(text, str) and text.strip():
            content_blocks.append(_TextBlock(type="text", text=text.strip()))
        tool_calls = message.get("tool_calls") or []
        for call in tool_calls:
            fn = call.get("function") or {}
            args_text = str(fn.get("arguments") or "{}")
            try:
                args = json.loads(args_text)
            except Exception:
                args = {}
            content_blocks.append(
                _ToolUseBlock(
                    type="tool_use",
                    id=str(call.get("id") or ""),
                    name=str(fn.get("name") or ""),
                    input=args if isinstance(args, dict) else {},
                )
            )
        stop_reason = "tool_use" if tool_calls else "end_turn"
        return OpenAICompatibleResponse(stop_reason=stop_reason, content=content_blocks)

    async def messages_create(self, **kwargs: Any) -> OpenAICompatibleResponse:
        payload: dict[str, Any] = {
            "model": kwargs.get("model"),
            "messages": self._to_openai_messages(kwargs.get("system", ""), kwargs.get("messages") or []),
            "max_tokens": int(kwargs.get("max_tokens") or 4096),
            "tools": self._to_openai_tools(kwargs.get("tools") or []),
            "tool_choice": self._to_openai_tool_choice(kwargs.get("tool_choice")),
            "temperature": 0.1,
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(self.url, headers=headers, json=payload)
        if resp.status_code >= 400:
            raise RuntimeError(f"OpenAI-compatible 调用失败: HTTP {resp.status_code} {resp.text[:200]}")
        data = resp.json()
        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError("OpenAI-compatible 返回空 choices")
        message = (choices[0] or {}).get("message") or {}
        return self._from_openai_message(message)

    @property
    def messages(self) -> Any:
        class _MessagesProxy:
            def __init__(self, outer: OpenAICompatibleAgentClient) -> None:
                self._outer = outer

            async def create(self, **kwargs: Any) -> OpenAICompatibleResponse:
                return await self._outer.messages_create(**kwargs)

        return _MessagesProxy(self)
