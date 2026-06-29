import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.openai_compatible_agent_client import OpenAICompatibleAgentClient  # noqa: E402
from app.services.power_map_service import (  # noqa: E402
    _POWER_MAP_CLEAN_RAW_OK,
    _KIMI_PLANNING_SYSTEM_PROMPT,
    _POWER_MAP_SEMANTIC_CLEAN_SYSTEM_PROMPT,
    _build_kimi_execution_seed,
    _kimi_planning_progress_summary,
    _power_map_request_max_tokens,
    _should_attach_screenshot,
    _should_enable_kimi_thinking,
    _validate_power_map_cleaned_text,
)


class FakePostResponse:
    status_code = 200
    text = "{}"

    def json(self):
        return {"choices": [{"message": {"content": "ok"}}]}


class FakeStreamResponse:
    status_code = 200

    def __init__(self, lines):
        self._lines = lines

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def aread(self):
        return b""

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class FakeHttpClient:
    def __init__(self, *, stream_lines=None):
        self.is_closed = False
        self.payloads = []
        self.stream_lines = stream_lines or []

    async def post(self, url, *, headers, json):
        self.payloads.append(json)
        return FakePostResponse()

    def stream(self, method, url, *, headers, json):
        self.payloads.append(json)
        return FakeStreamResponse(self.stream_lines)


def test_kimi_payload_disables_thinking_and_uses_auto_tool_choice(monkeypatch):
    monkeypatch.delenv("POWER_MAP_LLM_PROFILE", raising=False)
    monkeypatch.delenv("POWER_MAP_ROLLBACK_PROVIDER", raising=False)
    fake = FakeHttpClient()
    client = OpenAICompatibleAgentClient(base_url="https://kimi.example/v1", api_key="k")
    client._client = fake

    asyncio.run(
        client.messages_create(
            model="kimi-k2.6",
            system="",
            messages=[{"role": "user", "content": "ping"}],
            tools=[{"name": "create_node", "input_schema": {"type": "object"}}],
            kimi_thinking=False,
        )
    )

    payload = fake.payloads[0]
    assert payload["thinking"] == {"type": "disabled"}
    assert payload["tool_choice"] == "auto"


def test_sonnet_payload_omits_kimi_thinking(monkeypatch):
    monkeypatch.delenv("POWER_MAP_LLM_PROFILE", raising=False)
    monkeypatch.delenv("POWER_MAP_ROLLBACK_PROVIDER", raising=False)
    fake = FakeHttpClient()
    client = OpenAICompatibleAgentClient(base_url="https://gateway.example/v1", api_key="k")
    client._client = fake

    asyncio.run(
        client.messages_create(
            model="claude-sonnet-4-6",
            system="",
            messages=[{"role": "user", "content": "ping"}],
            kimi_thinking=True,
        )
    )

    assert "thinking" not in fake.payloads[0]


def test_rollback_provider_sonnet_disables_kimi_payload_options(monkeypatch):
    monkeypatch.setenv("POWER_MAP_ROLLBACK_PROVIDER", "sonnet")
    fake = FakeHttpClient()
    client = OpenAICompatibleAgentClient(base_url="https://kimi.example/v1", api_key="k")
    client._client = fake

    asyncio.run(
        client.messages_create(
            model="kimi-k2.6",
            system="",
            messages=[{"role": "user", "content": "ping"}],
            kimi_thinking=True,
        )
    )

    assert "thinking" not in fake.payloads[0]


def test_kimi_stream_yields_reasoning_and_usage_chunks(monkeypatch):
    monkeypatch.delenv("POWER_MAP_LLM_PROFILE", raising=False)
    monkeypatch.delenv("POWER_MAP_ROLLBACK_PROVIDER", raising=False)
    lines = [
        "data: " + json.dumps({"choices": [{"delta": {"reasoning_content": "plan"}}]}),
        "data: " + json.dumps({"choices": [{"delta": {"content": "ok"}}]}),
        "data: " + json.dumps({"choices": [{"delta": {}}], "usage": {"prompt_tokens": 10}}),
        "data: [DONE]",
    ]
    fake = FakeHttpClient(stream_lines=lines)
    client = OpenAICompatibleAgentClient(base_url="https://kimi.example/v1", api_key="k")
    client._client = fake

    async def _collect():
        chunks = []
        async for chunk in client.messages_create_with_history_stream(
            model="kimi-k2.6",
            system="",
            messages=[{"role": "user", "content": "ping"}],
            kimi_thinking=True,
        ):
            chunks.append(chunk)
        return chunks

    chunks = asyncio.run(_collect())

    assert fake.payloads[0]["thinking"] == {"type": "enabled"}
    assert {"type": "reasoning", "text": "plan"} in chunks
    assert {"type": "usage", "usage": {"prompt_tokens": 10}} in chunks


def test_kimi_auto_uses_thinking_only_for_planning_phase():
    assert (
        _should_enable_kimi_thinking(
            profile="kimi",
            mode="auto",
            rounds_completed=4,
            batch_execution_streaks={
                "single_create_node": 2,
                "single_set_parent": 0,
                "single_fit_container": 0,
            },
            visual_phase_seen=False,
        )
        is False
    )
    assert (
        _should_enable_kimi_thinking(
            profile="kimi",
            mode="auto",
            rounds_completed=4,
            batch_execution_streaks={},
            visual_phase_seen=False,
            phase="planning",
        )
        is True
    )
    assert (
        _should_enable_kimi_thinking(
            profile="kimi",
            mode="instant",
            rounds_completed=20,
            batch_execution_streaks={},
            visual_phase_seen=True,
        )
        is False
    )
    assert (
        _should_enable_kimi_thinking(
            profile="sonnet",
            mode="thinking",
            rounds_completed=20,
            batch_execution_streaks={},
            visual_phase_seen=True,
        )
        is None
    )


def test_kimi_request_max_tokens_is_capped_for_instant_mode():
    assert _power_map_request_max_tokens(profile="kimi", kimi_thinking=False) == 8192
    assert _power_map_request_max_tokens(profile="kimi", kimi_thinking=True) == 16384
    assert _power_map_request_max_tokens(profile="sonnet", kimi_thinking=None) == 32768


def test_kimi_planning_prompt_separates_hierarchy_from_edges():
    assert "输出格式必须是一个 JSON 对象" in _KIMI_PLANNING_SYSTEM_PROMPT
    assert '"parent_links"' in _KIMI_PLANNING_SYSTEM_PROMPT
    assert '"report_edges"' in _KIMI_PLANNING_SYSTEM_PROMPT
    assert "层级关系、下设、包含、隶属、板块下属单位" in _KIMI_PLANNING_SYSTEM_PROMPT
    assert "不是 create_edge 汇报连线" in _KIMI_PLANNING_SYSTEM_PROMPT
    assert "不要把 parent_links 复制进 report_edges" in _KIMI_PLANNING_SYSTEM_PROMPT
    assert "radial intent" in _KIMI_PLANNING_SYSTEM_PROMPT
    assert "后端 deterministic radial layout" in _KIMI_PLANNING_SYSTEM_PROMPT
    assert "部门初始尺寸预估" in _KIMI_PLANNING_SYSTEM_PROMPT or "部门人数" in _KIMI_PLANNING_SYSTEM_PROMPT
    assert '"tool_batches"' in _KIMI_PLANNING_SYSTEM_PROMPT
    assert "不是复述 SOP" in _KIMI_PLANNING_SYSTEM_PROMPT
    assert "不要输出像素坐标" in _KIMI_PLANNING_SYSTEM_PROMPT
    assert "集团/公司/总部/子公司/事业部/中心/部门/区域/城市组/门店/小组/班组" in _KIMI_PLANNING_SYSTEM_PROMPT
    assert "不能覆盖明确的 parent 层级" in _KIMI_PLANNING_SYSTEM_PROMPT
    assert "不能省略中间层容器" in _KIMI_PLANNING_SYSTEM_PROMPT
    assert "每个 source/target 必须能在 create_people/create_departments 或当前图结构中找到" in _KIMI_PLANNING_SYSTEM_PROMPT
    assert "你本人" in _KIMI_PLANNING_SYSTEM_PROMPT
    assert "部门对部门的 reports_to" in _KIMI_PLANNING_SYSTEM_PROMPT
    assert "平行部门" in _KIMI_PLANNING_SYSTEM_PROMPT
    assert "职位或角色标签" in _KIMI_PLANNING_SYSTEM_PROMPT
    assert "report_edges.reason" in _KIMI_PLANNING_SYSTEM_PROMPT
    assert "信息中心CIO是侯新硕" in _KIMI_PLANNING_SYSTEM_PROMPT
    assert "王忠向刘东汇报" in _KIMI_PLANNING_SYSTEM_PROMPT
    assert "不要输出刘东向侯新硕、吴龙向侯新硕" in _KIMI_PLANNING_SYSTEM_PROMPT


def test_kimi_cleaning_prompt_understands_power_map_model():
    assert "department 是容器节点" in _POWER_MAP_SEMANTIC_CLEAN_SYSTEM_PROMPT
    assert "user 是人员叶子节点" in _POWER_MAP_SEMANTIC_CLEAN_SYSTEM_PROMPT
    assert "CEO/总裁/负责人是人员节点" in _POWER_MAP_SEMANTIC_CLEAN_SYSTEM_PROMPT
    assert '"d"' in _POWER_MAP_SEMANTIC_CLEAN_SYSTEM_PROMPT
    assert '"p"' in _POWER_MAP_SEMANTIC_CLEAN_SYSTEM_PROMPT
    assert '"e"' in _POWER_MAP_SEMANTIC_CLEAN_SYSTEM_PROMPT
    assert _POWER_MAP_CLEAN_RAW_OK in _POWER_MAP_SEMANTIC_CLEAN_SYSTEM_PROMPT
    assert "两个合法输出" in _POWER_MAP_SEMANTIC_CLEAN_SYSTEM_PROMPT
    assert "短输入" in _POWER_MAP_SEMANTIC_CLEAN_SYSTEM_PROMPT
    assert "只输出 __RAW_OK__" in _POWER_MAP_SEMANTIC_CLEAN_SYSTEM_PROMPT
    assert "集团/公司/总部/子公司/事业部/中心/部门/区域/城市组/门店/小组/班组" in _POWER_MAP_SEMANTIC_CLEAN_SYSTEM_PROMPT
    assert "不能因此改变 A 的容器父级" in _POWER_MAP_SEMANTIC_CLEAN_SYSTEM_PROMPT
    assert "JSON 必须极简" in _POWER_MAP_SEMANTIC_CLEAN_SYSTEM_PROMPT
    assert "不要输出 evidence/reason/notes/background/ignored_background_summary" in _POWER_MAP_SEMANTIC_CLEAN_SYSTEM_PROMPT
    assert "d 中每个父容器名必须也在 d 中出现" in _POWER_MAP_SEMANTIC_CLEAN_SYSTEM_PROMPT
    assert "p 中每个人的所属容器必须在 d 中出现" in _POWER_MAP_SEMANTIC_CLEAN_SYSTEM_PROMPT
    assert "e 中每个 source/target 都必须同时出现在 d 或 p" in _POWER_MAP_SEMANTIC_CLEAN_SYSTEM_PROMPT
    assert "必须原样放入 p" in _POWER_MAP_SEMANTIC_CLEAN_SYSTEM_PROMPT
    assert "部门对部门 reports_to" in _POWER_MAP_SEMANTIC_CLEAN_SYSTEM_PROMPT
    assert "max_tokens=1024" not in _POWER_MAP_SEMANTIC_CLEAN_SYSTEM_PROMPT


def test_kimi_cleaning_validator_accepts_only_real_compression():
    raw = "背景说明" * 120 + "组织事实：张三向李四汇报。"
    compressed = '{"effective_goal":"建图","people":[{"name":"张三"},{"name":"李四"}],"report_edges":[{"source":"张三","target":"李四"}]}'

    assert _validate_power_map_cleaned_text(
        raw_text=raw,
        cleaned_text=compressed,
        session_id="test",
    ) == compressed


def test_kimi_cleaning_validator_treats_raw_ok_sentinel_as_no_cleaning():
    assert _validate_power_map_cleaned_text(
        raw_text="建组织架构：张三向李四汇报。",
        cleaned_text=_POWER_MAP_CLEAN_RAW_OK,
        session_id="test",
    ) == ""


def test_kimi_cleaning_validator_rejects_expansion():
    raw = "建组织架构：张三向李四汇报。"
    expanded = '{"effective_goal":"创建一个详细组织架构","background":"这是一段不该出现的扩写说明","people":[{"name":"张三"},{"name":"李四"}]}'

    assert _validate_power_map_cleaned_text(
        raw_text=raw,
        cleaned_text=expanded,
        session_id="test",
    ) == ""


def test_kimi_execution_seed_forbids_hierarchy_edges():
    seed = _build_kimi_execution_seed(
        graph_state_text="## 当前图结构\n节点 (0):",
        plan_text=(
            "## 应建立的层级归属（parent_id / set_parent）\n"
            "集团 -> 子公司\n"
            "## 应创建的汇报/决策连线（create_edge）\n"
            "张三 -> 李四"
        ),
    )
    payload = json.dumps(seed, ensure_ascii=False)

    assert "不要为了组织层级额外创建 create_edge" in payload
    assert "汇报/决策连线（create_edge）" in payload
    assert "按数组批量消耗" in payload
    assert "禁止把数组项逐条拆成多轮" in payload
    assert "edges=0 不能视为完成" in payload
    assert "后端" in payload
    assert "radial layout" in payload
    assert "不要猜坐标" in payload


def test_kimi_planning_progress_summary_is_safe_and_stage_based():
    early = _kimi_planning_progress_summary(2000)
    middle = _kimi_planning_progress_summary(10000)
    outputting = _kimi_planning_progress_summary(18000, plan_chars=512)

    assert "正在识别组织实体" in early
    assert "正在压缩为 JSON 执行清单" in middle
    assert "结构化执行清单正在输出" in outputting
    assert "512" in outputting
    assert "reasoning_content" not in early + middle + outputting


def test_stage_screenshot_policy_only_attaches_for_visual_or_final_rounds():
    assert _should_attach_screenshot(policy="stage", rounds_completed=1, initial=True) is False
    assert (
        _should_attach_screenshot(
            policy="stage",
            rounds_completed=2,
            tool_calls=[("create_node", {})],
        )
        is False
    )
    assert (
        _should_attach_screenshot(
            policy="stage",
            rounds_completed=3,
            tool_calls=[("fit_container_to_children", {})],
        )
        is True
    )
    assert _should_attach_screenshot(policy="stage", rounds_completed=4, final_check=True) is True
    assert _should_attach_screenshot(policy="legacy", rounds_completed=1, initial=True) is True
    assert (
        _should_attach_screenshot(
            policy="stage",
            rounds_completed=2,
            tool_calls=[("create_node", {}) for _ in range(8)],
        )
        is True
    )
