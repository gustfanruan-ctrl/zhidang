from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable


class AgentPhase(str, Enum):
    EXTRACTION = "extraction"
    COMPARISON = "comparison"


@dataclass
class AgentResult:
    status: str
    data: Any = None
    mode: str = "llm"
    turns_used: int = 0
    message: str = ""
    final_text: str = ""
    errors: list[str] = field(default_factory=list)


class AgentRunner:
    MAX_ITERATIONS = 8
    TOOL_TIMEOUT_SECONDS = 30
    TOTAL_TIMEOUT_SECONDS = 300

    def __init__(
        self,
        llm_client: Any,
        phase: AgentPhase,
        system_prompt: str,
        tools: list[dict[str, Any]],
        tool_executors: dict[str, Callable],
        model_name: str,
        output_validator: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        final_tool_name: str | None = None,
        progress_callback: Callable[[str], None] | None = None,
        max_iterations: int | None = None,
        tool_timeout_seconds: int | None = None,
        total_timeout_seconds: int | None = None,
        write_tools: set[str] | None = None,
        write_form_configs: dict[str, Any] | None = None,
        write_preview_builder: Callable[[str, dict[str, Any]], str] | None = None,
    ) -> None:
        self.llm_client = llm_client
        self.phase = phase
        self.system_prompt = system_prompt
        self.tools = tools
        self.tool_executors = tool_executors
        self.model_name = model_name
        self.output_validator = output_validator
        self.final_tool_name = final_tool_name
        self.progress_callback = progress_callback
        self.max_iterations = max_iterations or self.MAX_ITERATIONS
        self.tool_timeout_seconds = tool_timeout_seconds or self.TOOL_TIMEOUT_SECONDS
        self.total_timeout_seconds = total_timeout_seconds or self.TOTAL_TIMEOUT_SECONDS
        self.write_tools = write_tools or set()
        self.write_form_configs = write_form_configs or {}
        self.write_preview_builder = write_preview_builder
        self.pending_write: dict[str, Any] | None = None

    def _emit(self, message: str) -> None:
        if self.progress_callback:
            self.progress_callback(message)

    async def run(self, session_id: str, user_message: str | list[dict[str, Any]]) -> AgentResult:
        del session_id
        self.pending_write = None
        content: str | list[dict[str, Any]] = user_message if isinstance(user_message, list) else user_message
        messages: list[dict[str, Any]] = [{"role": "user", "content": content}]
        iterations = 0
        start_time = time.monotonic()

        try:
            while iterations < self.max_iterations:
                self._emit(f"第 {iterations + 1} 轮：请求模型")
                if (time.monotonic() - start_time) > self.total_timeout_seconds:
                    return AgentResult(
                        status="timeout",
                        turns_used=iterations,
                        message=f"Agent 总执行时间超过 {self.total_timeout_seconds}s",
                    )

                create_kwargs: dict[str, Any] = {
                    "model": self.model_name,
                    "max_tokens": 4096,
                    "system": self.system_prompt,
                    "tools": self.tools,
                    "messages": messages,
                }
                if self.final_tool_name:
                    create_kwargs["tool_choice"] = {"type": "tool", "name": self.final_tool_name}

                response = await self.llm_client.messages.create(**create_kwargs)
                self._emit(f"第 {iterations + 1} 轮：模型返回 {response.stop_reason}")

                if response.stop_reason == "end_turn":
                    self._emit("模型已结束输出")
                    return self._handle_end_turn(response, iterations)

                if response.stop_reason == "tool_use":
                    iterations += 1
                    tool_calls = [block for block in response.content if block.type == "tool_use"]
                    self._emit(f"执行工具调用：{', '.join(tc.name for tc in tool_calls)}")
                    tool_results = await asyncio.gather(*(self._safe_execute_tool(tc) for tc in tool_calls))

                    messages.append({"role": "assistant", "content": response.content})
                    messages.append(
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "tool_result",
                                    "tool_use_id": tc.id,
                                    "content": result,
                                }
                                for tc, result in zip(tool_calls, tool_results)
                            ],
                        }
                    )
                    continue

                return AgentResult(
                    status="llm_error",
                    turns_used=iterations,
                    message=f"未识别的 stop_reason: {response.stop_reason}",
                )

            return AgentResult(
                status="max_iterations",
                turns_used=iterations,
                message=f"达到最大迭代次数 {self.max_iterations}",
            )
        except Exception as exc:
            return AgentResult(
                status="llm_error",
                turns_used=iterations,
                message=str(exc),
            )

    def _handle_end_turn(self, response: Any, iterations: int) -> AgentResult:
        final_data = self._extract_output(response)
        final_text = self._extract_text(response)

        if self.output_validator and final_data is not None:
            try:
                validated = self.output_validator(final_data)
                return AgentResult(status="success", data=validated, turns_used=iterations + 1, final_text=final_text, message=final_text)
            except Exception as exc:
                return AgentResult(
                    status="validation_error",
                    data=final_data,
                    turns_used=iterations + 1,
                    final_text=final_text,
                    message=final_text,
                    errors=[str(exc)],
                )

        return AgentResult(status="success", data=final_data, turns_used=iterations + 1, final_text=final_text, message=final_text)

    def _extract_text(self, response: Any) -> str:
        texts: list[str] = []
        for block in response.content:
            if getattr(block, "type", "") == "text":
                text = str(getattr(block, "text", "")).strip()
                if text:
                    texts.append(text)
        return "\n".join(texts).strip()

    async def _validate_write_tool_call(self, tool_name: str, tool_input: dict[str, Any], form_config: dict[str, Any]) -> dict[str, Any]:
        errors: list[str] = []
        if not tool_input.get("company_id"):
            errors.append("缺少 company_id，请先确认客户")
        field_mapping = (form_config or {}).get("field_mapping", {}) or {}
        fields = tool_input.get("fields", {}) or {}
        for field_name in fields:
            if field_name not in field_mapping:
                errors.append(f"字段 '{field_name}' 不在 {tool_input.get('target_form', '目标表单')} 的可用字段中，可用字段：{list(field_mapping.keys())}")
        for field_name in fields:
            mapping = field_mapping.get(field_name, {}) or {}
            if mapping.get("safety") == "forbidden":
                errors.append(f"字段 '{field_name}' 禁止写入")
        for field_name, value in fields.items():
            mapping = field_mapping.get(field_name, {}) or {}
            if mapping.get("safety") == "restricted":
                allowed = mapping.get("allowed_values", []) or []
                if allowed and value not in allowed:
                    errors.append(f"字段 '{field_name}' 的值 '{value}' 不在允许范围内，可选：{allowed}")
        if tool_name in {"update_customer_record", "delete_customer_record"} and not tool_input.get("data_id"):
            errors.append("缺少 data_id，请先调用 query_customer_records 查询目标记录")
        if errors:
            return {"status": "recall", "errors": errors, "hint": "请根据以上错误修正参数后重新调用"}
        return {"status": "ok"}

    def _extract_output(self, response: Any) -> Any:
        for block in reversed(response.content):
            if getattr(block, "type", "") == "tool_use":
                return getattr(block, "input", None)
        for block in response.content:
            if getattr(block, "type", "") == "text":
                text = getattr(block, "text", "")
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    return text
        return None

    async def _safe_execute_tool(self, tool_call: Any) -> str:
        tool_name = tool_call.name
        tool_input = tool_call.input

        try:
            if tool_name in self.write_tools:
                target_form = str(tool_input.get("target_form") or "")
                form_config = self.write_form_configs.get(target_form, {}) or {}
                validation = await self._validate_write_tool_call(tool_name, tool_input, form_config)
                if validation.get("status") == "recall":
                    return json.dumps(validation, ensure_ascii=False)
                self.pending_write = {"tool_name": tool_name, "tool_input": tool_input, "validated": True}
                preview = self.write_preview_builder(tool_name, tool_input) if self.write_preview_builder else "操作已准备好，等待用户确认执行"
                return json.dumps(
                    {
                        "status": "pending_confirmation",
                        "message": "操作已准备好，等待用户确认执行",
                        "preview": preview,
                    },
                    ensure_ascii=False,
                )
            executor = self.tool_executors.get(tool_name)
            if not executor:
                return json.dumps(
                    {
                        "status": "error",
                        "error": "unknown_tool",
                        "message": f"未注册的 Tool: {tool_name}",
                    },
                    ensure_ascii=False,
                )

            result = await asyncio.wait_for(executor(tool_input), timeout=self.tool_timeout_seconds)
            return json.dumps({"status": "success", "data": result}, ensure_ascii=False)
        except asyncio.TimeoutError:
            return json.dumps(
                {
                    "status": "error",
                    "error": "timeout",
                    "message": f"Tool {tool_name} 执行超时（{self.tool_timeout_seconds}s）",
                    "hint": "请稍后重试或缩小输入范围。",
                },
                ensure_ascii=False,
            )
        except Exception as exc:
            return json.dumps(
                {
                    "status": "error",
                    "error": "execution_failed",
                    "message": f"执行 {tool_name} 时出错: {exc}",
                    "hint": "请检查输入参数是否正确。",
                },
                ensure_ascii=False,
            )
