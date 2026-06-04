from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger("zhidang.llm")


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
class _ReasoningBlock:
    """携带 reasoning_content，供下一轮透传给 DeepSeek R1 系列模型。"""
    type: str
    reasoning_content: str


@dataclass
class OpenAICompatibleResponse:
    stop_reason: str
    content: list[Any]


class OpenAICompatibleAgentClient:
    MAX_RETRIES = 2
    RETRY_BACKOFF_BASE = 1.5  # seconds

    def __init__(self, *, base_url: str, api_key: str, request_timeout_seconds: int = 7200, connect_timeout_seconds: int = 120) -> None:
        base = (base_url or "").rstrip("/")
        if not base:
            raise ValueError("OpenAI-compatible base_url 未配置")
        self.url = f"{base}/chat/completions"
        self.api_key = api_key
        self.timeout = httpx.Timeout(float(request_timeout_seconds), connect=float(connect_timeout_seconds))
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """获取或创建共享的 httpx 客户端，复用连接池。"""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

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
                reasoning_content: str | None = None
                for block in content:
                    if getattr(block, "type", "") == "__reasoning__":
                        reasoning_content = getattr(block, "reasoning_content", None)
                    elif getattr(block, "type", "") == "text":
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
                if reasoning_content:
                    payload["reasoning_content"] = reasoning_content
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
        reasoning = message.get("reasoning_content")
        if isinstance(reasoning, str) and reasoning:
            content_blocks.append(_ReasoningBlock(type="__reasoning__", reasoning_content=reasoning))
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

    async def messages_create_vision(
        self,
        *,
        model: str,
        system: str,
        content: list[dict[str, Any]],
        max_tokens: int = 4096,
        temperature: float = 0.1,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: Any = None,
    ) -> OpenAICompatibleResponse:
        """Multimodal call: `content` is a list of OpenAI-style content blocks,
        e.g. [{"type": "text", "text": "..."},
              {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}].

        Bypasses the text-only message converter — passes the multimodal user message
        through to the OpenAI-compatible `/chat/completions` endpoint directly.

        Optional `tools`/`tool_choice` enable native function calling. `tools` should
        already be in OpenAI format ({"type": "function", "function": {...}}). The
        returned response will contain `_ToolUseBlock`s for any tool calls.
        """
        if not isinstance(content, list) or not content:
            raise ValueError("messages_create_vision: content 必须是非空 list")

        messages: list[dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": content})

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": int(max_tokens),
            "temperature": float(temperature),
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = self._to_openai_tool_choice(tool_choice) if tool_choice else "auto"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

        client = await self._get_client()
        last_exc: Exception | None = None
        for attempt in range(1 + self.MAX_RETRIES):
            try:
                resp = await client.post(self.url, headers=headers, json=payload)
                if resp.status_code >= 500:
                    raise RuntimeError(f"服务端错误 HTTP {resp.status_code}")
                if resp.status_code >= 400:
                    raise RuntimeError(f"Vision 调用失败: HTTP {resp.status_code} {resp.text[:200]}")
                data = resp.json()
                choices = data.get("choices") or []
                if not choices:
                    raise RuntimeError("Vision 返回空 choices")
                message = (choices[0] or {}).get("message") or {}
                return self._from_openai_message(message)
            except (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError) as exc:
                last_exc = exc
                if attempt < self.MAX_RETRIES:
                    wait = self.RETRY_BACKOFF_BASE * (2 ** attempt)
                    logger.warning("Vision 请求失败 (尝试 %d/%d)，%.1fs 后重试: %s", attempt + 1, 1 + self.MAX_RETRIES, wait, exc)
                    await asyncio.sleep(wait)
                    if self._client and not self._client.is_closed:
                        await self._client.aclose()
                    self._client = None
                    client = await self._get_client()
            except RuntimeError:
                raise
        raise RuntimeError(f"Vision 请求重试 {self.MAX_RETRIES} 次后仍失败: {last_exc}")

    async def messages_create_vision_stream(
        self,
        *,
        model: str,
        system: str,
        content: list[dict[str, Any]],
        max_tokens: int = 2048,
        temperature: float = 0.1,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: Any = None,
    ) -> AsyncGenerator[str | dict[str, Any], None]:
        """Streaming multimodal call.

        Without `tools`: yields each `delta.content` text chunk as a raw `str`
        (legacy behavior).

        With `tools`: yields structured dict chunks instead:
          - {"type": "content", "text": "..."}            text delta
          - {"type": "tool_call_start", "index": int,
             "id": "...", "name": "..."}                  new tool call begins
          - {"type": "tool_call_delta", "index": int,
             "arguments": "..."}                          tool-call argument JSON delta

        SSE protocol: parses `data: {...}` lines from the OpenAI-compatible endpoint with
        `stream: true`. Stops on `data: [DONE]`. Retries pre-connection network errors;
        once the stream has started yielding chunks, network errors propagate.
        """
        if not isinstance(content, list) or not content:
            raise ValueError("messages_create_vision_stream: content 必须是非空 list")

        messages: list[dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": content})

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": int(max_tokens),
            "temperature": float(temperature),
            "stream": True,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = self._to_openai_tool_choice(tool_choice) if tool_choice else "auto"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

        use_structured = bool(tools)
        seen_tool_call_ids: dict[int, str] = {}

        client = await self._get_client()
        last_exc: Exception | None = None
        for attempt in range(1 + self.MAX_RETRIES):
            try:
                async with client.stream("POST", self.url, headers=headers, json=payload) as resp:
                    if resp.status_code >= 500:
                        raise RuntimeError(f"服务端错误 HTTP {resp.status_code}")
                    if resp.status_code >= 400:
                        body = await resp.aread()
                        raise RuntimeError(f"Vision 流式调用失败: HTTP {resp.status_code} {body.decode('utf-8', errors='replace')[:200]}")

                    async for raw_line in resp.aiter_lines():
                        line = raw_line.strip()
                        if not line or not line.startswith("data:"):
                            continue
                        data_str = line[len("data:"):].strip()
                        if data_str == "[DONE]":
                            return
                        try:
                            event = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue
                        choices = event.get("choices") or []
                        if not choices:
                            continue
                        delta = (choices[0] or {}).get("delta") or {}
                        chunk = delta.get("content")

                        if use_structured:
                            if isinstance(chunk, str) and chunk:
                                yield {"type": "content", "text": chunk}
                            tool_call_deltas = delta.get("tool_calls") or []
                            for tcd in tool_call_deltas:
                                if not isinstance(tcd, dict):
                                    continue
                                index = int(tcd.get("index") or 0)
                                fn = tcd.get("function") or {}
                                tc_id = tcd.get("id")
                                fn_name = fn.get("name")
                                # First chunk for this index carries id+name; subsequent only arguments.
                                if index not in seen_tool_call_ids and (tc_id or fn_name):
                                    seen_tool_call_ids[index] = str(tc_id or "")
                                    yield {
                                        "type": "tool_call_start",
                                        "index": index,
                                        "id": str(tc_id or ""),
                                        "name": str(fn_name or ""),
                                    }
                                args_chunk = fn.get("arguments")
                                if isinstance(args_chunk, str) and args_chunk:
                                    yield {
                                        "type": "tool_call_delta",
                                        "index": index,
                                        "arguments": args_chunk,
                                    }
                        else:
                            if isinstance(chunk, str) and chunk:
                                yield chunk
                return
            except (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError) as exc:
                last_exc = exc
                if attempt < self.MAX_RETRIES:
                    wait = self.RETRY_BACKOFF_BASE * (2 ** attempt)
                    logger.warning("Vision 流式请求失败 (尝试 %d/%d)，%.1fs 后重试: %s", attempt + 1, 1 + self.MAX_RETRIES, wait, exc)
                    await asyncio.sleep(wait)
                    if self._client and not self._client.is_closed:
                        await self._client.aclose()
                    self._client = None
                    client = await self._get_client()
            except RuntimeError:
                raise
        raise RuntimeError(f"Vision 流式请求重试 {self.MAX_RETRIES} 次后仍失败: {last_exc}")

    async def messages_create_with_history_stream(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.1,
    ) -> AsyncGenerator[str | dict[str, Any], None]:
        """Streaming call with full message history.

        Same streaming-parse contract as ``messages_create_vision_stream`` —
        without `tools`: yields each `delta.content` text chunk as a raw `str`;
        with `tools`: yields structured dict chunks (content / tool_call_start /
        tool_call_delta).

        Differs only in input shape: caller provides the complete OpenAI-style
        `messages` list (each entry already in the format expected by the
        endpoint — including assistant `tool_calls` and `tool` role results).
        A system message is prepended automatically from `system`.
        """
        if not isinstance(messages, list) or not messages:
            raise ValueError("messages_create_with_history_stream: messages 必须是非空 list")

        full_messages: list[dict[str, Any]] = []
        if system:
            full_messages.append({"role": "system", "content": system})
        full_messages.extend(messages)

        payload: dict[str, Any] = {
            "model": model,
            "messages": full_messages,
            "max_tokens": int(max_tokens),
            "temperature": float(temperature),
            "stream": True,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

        use_structured = bool(tools)
        seen_tool_call_ids: dict[int, str] = {}
        _local_ids: dict[int, str] = {}  # bedrock_idx → call_<uuid16>

        # ── DEBUG: dump request payload metadata ──
        import time as _time, os as _os
        _debug_dir = "/tmp/llm_debug"
        _os.makedirs(_debug_dir, exist_ok=True)
        _ts = _time.strftime("%Y%m%d_%H%M%S")
        _msg_count = len(full_messages)
        _tc_ids = []
        for _m in full_messages:
            for _tc in (_m.get("tool_calls") or []):
                _tc_ids.append(_tc.get("id", "?"))
            if _m.get("role") == "tool":
                _tc_ids.append(f"tool_result:{_m.get('tool_call_id','?')}")
        _dump_path = _os.path.join(_debug_dir, f"req_r{_msg_count}_{_ts}.json")
        with open(_dump_path, "w", encoding="utf-8") as _f:
            json.dump({"model": payload["model"], "messages_count": _msg_count,
                       "tools_count": len(payload.get("tools") or []),
                       "tool_call_ids_in_history": _tc_ids},
                      _f, ensure_ascii=False, indent=2, default=str)
        logger.info("[llm-debug] dumped request to %s (msgs=%d tool_ids=%s)",
                    _dump_path, _msg_count, _tc_ids)

        # ── DEEP DEBUG: dump full messages for Bedrock 400 troubleshooting ──
        try:
            _deep_msgs = []
            for _i, _m in enumerate(full_messages):
                _role = _m.get("role", "?")
                _tcs = [{"id": t.get("id", "?")[:40], "name": (t.get("function") or {}).get("name","?")} for t in (_m.get("tool_calls") or [])]
                _tcid = _m.get("tool_call_id", "")
                _cc = ""
                _c = _m.get("content")
                if isinstance(_c, list):
                    _cc = f"[{len(_c)} blocks: " + ",".join(
                        (b.get("type","?") if isinstance(b,dict) else str(type(b).__name__))
                        for b in _c
                    ) + "]"
                elif isinstance(_c, str):
                    _cc = _c[:120]
                _deep_msgs.append({"idx": _i, "role": _role, "tool_calls": _tcs, "tool_call_id": _tcid, "content_preview": _cc})
            _deep_path = _os.path.join(_debug_dir, f"deep_req_r{_msg_count}_{_ts}.json")
            with open(_deep_path, "w", encoding="utf-8") as _f:
                json.dump(_deep_msgs, _f, ensure_ascii=False, indent=2, default=str)
            logger.info("[llm-deep-debug] dumped %d full messages to %s", len(full_messages), _deep_path)

            # ── RAW PAYLOAD dump: exact JSON bytes httpx will send ──
            try:
                _raw_path = _os.path.join(_debug_dir, f"raw_payload_r{_msg_count}_{_ts}.json")
                with open(_raw_path, "w", encoding="utf-8") as _f:
                    json.dump(payload, _f, ensure_ascii=False, default=str)
                logger.info("[llm-raw-debug] dumped raw payload (%d bytes) to %s",
                            _os.path.getsize(_raw_path), _raw_path)
            except Exception:
                pass
        except Exception:
            pass

        client = await self._get_client()
        last_exc: Exception | None = None
        for attempt in range(1 + self.MAX_RETRIES):
            try:
                async with client.stream("POST", self.url, headers=headers, json=payload) as resp:
                    if resp.status_code >= 500:
                        raise RuntimeError(f"服务端错误 HTTP {resp.status_code}")
                    if resp.status_code >= 400:
                        body = await resp.aread()
                        raise RuntimeError(f"History 流式调用失败: HTTP {resp.status_code} {body.decode('utf-8', errors='replace')[:200]}")


                    async for raw_line in resp.aiter_lines():
                        line = raw_line.strip()
                        if not line or not line.startswith("data:"):
                            continue
                        data_str = line[len("data:"):].strip()
                        if data_str == "[DONE]":
                            return
                        try:
                            event = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue
                        choices = event.get("choices") or []
                        if not choices:
                            continue
                        delta = (choices[0] or {}).get("delta") or {}
                        chunk = delta.get("content")

                        if use_structured:
                            if isinstance(chunk, str) and chunk:
                                yield {"type": "content", "text": chunk}
                            tool_call_deltas = delta.get("tool_calls") or []
                            for tcd in tool_call_deltas:
                                if not isinstance(tcd, dict):
                                    continue
                                index = int(tcd.get("index") or 0)
                                fn = tcd.get("function") or {}
                                tc_id = tcd.get("id")
                                fn_name = fn.get("name")
                                if index not in seen_tool_call_ids and (tc_id or fn_name):
                                    seen_tool_call_ids[index] = str(tc_id or "")
                                    # Localize: replace Bedrock toolu_bdrk_xxx with call_<uuid16>
                                    import uuid as _uuid_mod
                                    local_id = _local_ids.get(index) or "call_" + _uuid_mod.uuid4().hex[:16]
                                    _local_ids[index] = local_id
                                    yield {
                                        "type": "tool_call_start",
                                        "index": index,
                                        "id": local_id,
                                        "name": str(fn_name or ""),
                                    }
                                args_chunk = fn.get("arguments")
                                if isinstance(args_chunk, str) and args_chunk:
                                    yield {
                                        "type": "tool_call_delta",
                                        "index": index,
                                        "arguments": args_chunk,
                                    }
                        else:
                            if isinstance(chunk, str) and chunk:
                                yield chunk
                return
            except (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError) as exc:
                last_exc = exc
                if attempt < self.MAX_RETRIES:
                    wait = self.RETRY_BACKOFF_BASE * (2 ** attempt)
                    logger.warning("History 流式请求失败 (尝试 %d/%d)，%.1fs 后重试: %s", attempt + 1, 1 + self.MAX_RETRIES, wait, exc)
                    await asyncio.sleep(wait)
                    if self._client and not self._client.is_closed:
                        await self._client.aclose()
                    self._client = None
                    client = await self._get_client()
            except RuntimeError:
                raise
        raise RuntimeError(f"History 流式请求重试 {self.MAX_RETRIES} 次后仍失败: {last_exc}")

    async def messages_create(self, **kwargs: Any) -> OpenAICompatibleResponse:
        msgs = self._to_openai_messages(kwargs.get("system", ""), kwargs.get("messages") or [])
        # Ensure at least one user/assistant message — some APIs reject system-only.
        if msgs and msgs[-1]["role"] == "system":
            msgs.append({"role": "user", "content": kwargs.get("system", "")[:2000] or "go"})

        payload: dict[str, Any] = {
            "model": kwargs.get("model"),
            "messages": msgs,
            "max_tokens": int(kwargs.get("max_tokens") or 8192),
            "temperature": kwargs.get("temperature", 0.1),
        }
        tools = self._to_openai_tools(kwargs.get("tools") or [])
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = self._to_openai_tool_choice(kwargs.get("tool_choice"))
        elif kwargs.get("tool_choice") is not None:
            payload["tool_choice"] = self._to_openai_tool_choice(kwargs["tool_choice"])
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

        client = await self._get_client()
        last_exc: Exception | None = None
        for attempt in range(1 + self.MAX_RETRIES):
            try:
                resp = await client.post(self.url, headers=headers, json=payload)
                if resp.status_code >= 500:
                    raise RuntimeError(f"服务端错误 HTTP {resp.status_code}")
                if resp.status_code >= 400:
                    raise RuntimeError(f"OpenAI-compatible 调用失败: HTTP {resp.status_code} {resp.text[:200]}")
                data = resp.json()
                choices = data.get("choices") or []
                if not choices:
                    raise RuntimeError("OpenAI-compatible 返回空 choices")
                message = (choices[0] or {}).get("message") or {}
                return self._from_openai_message(message)
            except (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError) as exc:
                last_exc = exc
                if attempt < self.MAX_RETRIES:
                    wait = self.RETRY_BACKOFF_BASE * (2 ** attempt)
                    logger.warning("LLM 请求失败 (尝试 %d/%d)，%.1fs 后重试: %s", attempt + 1, 1 + self.MAX_RETRIES, wait, exc)
                    await asyncio.sleep(wait)
                    # 重建 client，避免复用已断开的连接
                    if self._client and not self._client.is_closed:
                        await self._client.aclose()
                    self._client = None
                    client = await self._get_client()
            except RuntimeError:
                raise  # 非网络错误，不重试
        raise RuntimeError(f"LLM 请求重试 {self.MAX_RETRIES} 次后仍失败: {last_exc}")

    @property
    def messages(self) -> Any:
        class _MessagesProxy:
            def __init__(self, outer: OpenAICompatibleAgentClient) -> None:
                self._outer = outer

            async def create(self, **kwargs: Any) -> OpenAICompatibleResponse:
                return await self._outer.messages_create(**kwargs)

        return _MessagesProxy(self)
