"""
4-case regression test for _run_llm_tool_loop messages accumulation.
Mocks LLM client, screenshot_fn, and tool executor to verify:
- Case 1: No tool calls → exits immediately
- Case 2: Single tool call → 1 round then done
- Case 3: Multi-round → tools in rounds 1-2, none in round 3
- Case 4: Max rounds exhausted → keeps going until max_rounds

Verification: [loop] log shows messages_count increasing across rounds.
"""
import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

# Add backend to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.services.power_map_service import (
    MergeContext,
    PowerNode,
    HarnessEvent,
    _run_llm_tool_loop,
)


# ── helpers ──────────────────────────────────────────────────

_FAKE_PNG = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
    "+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


class FakeLLMClient:
    """Controllable mock that yields chunks from a pre-built queue per call."""

    def __init__(self, queues: list[list]):
        self._queues = queues
        self.calls = 0
        self.kwargs_history = []

    async def messages_create(self, **kwargs):
        self.kwargs_history.append(kwargs)
        if self.calls >= len(self._queues):
            return SimpleNamespace(content=[])
        chunks = self._queues[self.calls]
        self.calls += 1
        if isinstance(chunks, Exception):
            raise chunks
        text_parts = []
        for chunk in chunks:
            if isinstance(chunk, str):
                text_parts.append(chunk)
            elif isinstance(chunk, dict) and chunk.get("type") == "content":
                text_parts.append(str(chunk.get("text") or ""))
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text="".join(text_parts))]
        )

    async def messages_create_with_history_stream(self, **kwargs):
        self.kwargs_history.append(kwargs)
        if self.calls >= len(self._queues):
            return
        chunks = self._queues[self.calls]
        self.calls += 1
        if isinstance(chunks, Exception):
            raise chunks
        for chunk in chunks:
            yield chunk


async def fake_screenshot_fn(ctx: MergeContext) -> str:
    return _FAKE_PNG


def make_fake_tool_executor(results_by_name: dict[str, dict]):
    """Return an async function that returns the pre-configured result for each tool name."""
    async def _exec(ctx, name, args):
        if name in results_by_name:
            return dict(results_by_name[name])
        return {"ok": False, "error": f"unknown tool: {name}"}
    return _exec


# ── test helpers ─────────────────────────────────────────────

def make_ctx() -> MergeContext:
    ctx = MergeContext()
    ctx.last_screenshot_url = _FAKE_PNG
    n1 = PowerNode(
        id="n1", name="财务部", node_type="dept", x=100, y=100, w=200, h=150
    )
    n2 = PowerNode(
        id="n2", name="张三", node_type="user", x=150, y=300, w=80, h=40,
        parent_dept_id="n1"
    )
    ctx.all_nodes = [n1, n2]
    return ctx


def tool_call_chunks(index: int, id_: str, name: str, args: dict) -> list[dict]:
    """Build a sequence of structured chunks for one tool call."""
    args_json = json.dumps(args)
    chunks = [
        {"type": "tool_call_start", "index": index, "id": id_, "name": name},
    ]
    for i in range(0, len(args_json), 20):
        chunks.append({
            "type": "tool_call_delta",
            "index": index,
            "arguments": args_json[i : i + 20],
        })
    return chunks


# ── cases ────────────────────────────────────────────────────

class TestRunLLMToolLoop:
    """4 regression cases."""

    def _run_loop(
        self,
        *,
        queues,
        tool_results,
        max_rounds=5,
        user_text=None,
        model="gpt-4o",
        return_client=False,
    ) -> list:
        """Run _run_llm_tool_loop with mocks and return all events."""
        ctx = make_ctx()

        mock_cfg = MagicMock()
        mock_cfg.llm_api_key_encrypted = "fake-encrypted-key"
        mock_cfg.llm_base_url = "https://fake.api.com"
        mock_cfg.nl_chat_model = model
        mock_cfg.power_map_llm_model = model
        fake_client = FakeLLMClient(queues)
        tool_names = {"move_user", *tool_results.keys()}

        with (
            patch(
                "app.services.power_map_service.decrypt_secret",
                return_value="fake-api-key",
            ),
            patch(
                "app.services.power_map_service._execute_harness_tool",
                new_callable=AsyncMock,
                side_effect=make_fake_tool_executor(tool_results),
            ),
            patch(
                "app.services.power_map_service._get_llm_client",
                return_value=fake_client,
            ),
        ):
            events = []

            async def _collect():
                async for ev in _run_llm_tool_loop(
                    ctx=ctx,
                    user_text=user_text or "请审视截图，必要时调用布局工具进行美化。",
                    system_prompt="You are a layout assistant.",
                    tools=[
                        {"type": "function", "function": {"name": name, "parameters": {}}}
                        for name in sorted(tool_names)
                    ],
                    cfg=mock_cfg,
                    screenshot_fn=fake_screenshot_fn,
                    max_rounds=max_rounds,
                    session_id="test-session",
                ):
                    events.append(ev)

            asyncio.run(_collect())

        if return_client:
            return events, fake_client
        return events

    # ── test methods ──────────────────────────────────────

    def test_case1_no_tool_calls_exits_immediately(self):
        """LLM returns no tools in round 1 → exits with done."""
        queues = [["截图看起来已经很好了，不需要调整。"]]
        events = self._run_loop(queues=queues, tool_results={})

        rounds = [e for e in events if e.type == "round_start"]
        done = [e for e in events if e.type == "done"]
        tool_calls = [e for e in events if e.type == "tool_call"]

        assert len(rounds) == 1
        assert len(done) == 1
        assert len(tool_calls) == 0
        assert done[0].data.get("error") is None
        print(f"  ✓ case1: {len(rounds)} round, {len(tool_calls)} tools")

    def test_no_tool_but_unfinished_step_does_not_converge_immediately(self):
        """If the model says it is starting another step, no-tool is not convergence."""
        queues = [
            ["Step 2 完成。现在开始 Step 3：调整布局。"],
            ["全部完成。"],
        ]
        events = self._run_loop(queues=queues, tool_results={})

        rounds = [e for e in events if e.type == "round_start"]
        done = [e for e in events if e.type == "done"]

        assert len(rounds) == 2
        assert len(done) == 1
        assert done[0].data.get("error") is None
        print(f"  ok no-tool unfinished: {len(rounds)} rounds")

    def test_no_tool_with_required_edges_does_not_converge_immediately(self):
        queues = [["全部完成。"], ["全部完成。"], ["全部完成。"]]
        events = self._run_loop(
            queues=queues,
            tool_results={},
            user_text="请建立组织架构，并让下属都向负责人汇报。",
            max_rounds=4,
        )

        rounds = [e for e in events if e.type == "round_start"]
        done = [e for e in events if e.type == "done"]

        assert len(rounds) == 3
        assert len(done) == 1
        assert done[0].data.get("error") is None

    def test_case2_single_tool_call_one_round(self):
        """LLM calls 1 tool in round 1, then no tools in round 2 → exits."""
        queues = [
            [
                {"type": "content", "text": "让我调整张三的位置。"},
                *tool_call_chunks(0, "call_1", "move_user", {"node_id": "n2", "direction": "right"}),
            ],
            ["调整完成。"],
        ]
        events = self._run_loop(queues=queues, tool_results={"move_user": {"ok": True}})

        rounds = [e for e in events if e.type == "round_start"]
        tool_calls = [e for e in events if e.type == "tool_call"]
        tool_results_ev = [e for e in events if e.type == "tool_result"]

        assert len(rounds) == 2
        assert len(tool_calls) == 1
        assert len(tool_results_ev) == 1
        print(f"  ✓ case2: {len(rounds)} rounds, {len(tool_calls)} tools")

    def test_case3_multi_round_accumulates_messages(self):
        """LLM calls tools in rounds 1-2, then no tools in round 3."""
        queues = [
            [
                {"type": "content", "text": "先调整张三。"},
                *tool_call_chunks(0, "call_a", "move_user", {"node_id": "n2", "direction": "right"}),
            ],
            [
                {"type": "content", "text": "再微调一下。"},
                *tool_call_chunks(0, "call_b", "move_user", {"node_id": "n2", "direction": "down"}),
            ],
            ["现在看起来很好了。"],
        ]
        events = self._run_loop(queues=queues, tool_results={"move_user": {"ok": True}})

        rounds = [e for e in events if e.type == "round_start"]
        tool_calls = [e for e in events if e.type == "tool_call"]
        done = [e for e in events if e.type == "done"]

        assert len(rounds) == 3
        assert len(tool_calls) == 2
        assert len(done) == 1
        assert done[0].data.get("error") is None
        print(f"  ✓ case3: {len(rounds)} rounds, {len(tool_calls)} tools")

    def test_relayout_compacts_history_before_next_round(self):
        """After relayout, the next LLM call should not carry bulky tool history."""
        huge_relayout_result = {
            "ok": True,
            "direction": "TB",
            "depth_styles_applied": True,
            "nodes": [
                {
                    "id": f"n{i}",
                    "name": f"huge_marker_{i}",
                    "payload": "x" * 1000,
                }
                for i in range(30)
            ],
            "edges": [{"id": f"e{i}", "source_id": "n1", "target_id": "n2"} for i in range(30)],
        }
        queues = [
            [
                {"type": "content", "text": "结构完成，先 relayout。"},
                *tool_call_chunks(0, "call_relayout", "relayout", {"options": {"direction": "TB"}}),
            ],
            ["全部完成。"],
        ]

        _events, fake_client = self._run_loop(
            queues=queues,
            tool_results={"relayout": huge_relayout_result},
            return_client=True,
        )

        assert len(fake_client.kwargs_history) >= 2
        next_round_messages = fake_client.kwargs_history[1]["messages"]
        next_round_payload = json.dumps(next_round_messages, ensure_ascii=False, default=str)

        assert len(next_round_messages) == 1
        assert "relayout 后布局微调阶段" in next_round_payload
        assert "## 当前图结构" in next_round_payload
        assert "data:image/png;base64" in next_round_payload
        assert "huge_marker_" not in next_round_payload
        assert '"role": "tool"' not in next_round_payload

    def test_case4_max_rounds_exhausted(self):
        """LLM keeps calling tools every round until max_rounds=3."""
        queues = [
            [
                {"type": "content", "text": "调整张三。"},
                *tool_call_chunks(0, f"call_{i}", "move_user", {"node_id": "n2", "direction": "right"}),
            ]
            for i in range(3)
        ]
        events = self._run_loop(queues=queues, tool_results={"move_user": {"ok": True}}, max_rounds=3)

        rounds = [e for e in events if e.type == "round_start"]
        tool_calls = [e for e in events if e.type == "tool_call"]
        done = [e for e in events if e.type == "done"]

        assert len(rounds) == 3
        assert len(tool_calls) == 3
        assert len(done) == 1
        print(f"  ✓ case4: {len(rounds)} rounds (max), {len(tool_calls)} tools")

    def test_kimi_auto_plans_once_then_executes_without_raw_user_text(self, monkeypatch):
        monkeypatch.delenv("POWER_MAP_ROLLBACK_PROVIDER", raising=False)
        monkeypatch.setenv("POWER_MAP_LLM_PROFILE", "kimi")
        monkeypatch.setenv("POWER_MAP_KIMI_MODE", "auto")
        raw_user_text = (
            "建一个完整的公司组织架构：总裁办：黄宇任 CEO，苏女士任总裁助理向黄宇汇报。"
            "下设五个部门，部门负责人都向黄宇汇报。"
            "背景说明：这家公司最近在梳理组织治理，希望把会议口述内容整理成权力地图，"
            "其中大量业务背景不需要进入图结构，只保留真实节点、层级和汇报关系。"
        )
        plan_text = (
            "## 目标\n创建组织架构\n"
            "## 应创建的汇报连线\n苏女士 -> 黄宇；部门负责人 -> 黄宇\n"
            "## 完成条件\n节点和汇报连线完成"
        )
        cleaned_text = (
            '{"effective_goal":"创建组织架构","report_edges":[{"source":"苏女士","target":"黄宇"}]}'
        )
        queues = [
            [cleaned_text],
            [plan_text],
            [
                {"type": "content", "text": "执行计划。"},
                *tool_call_chunks(0, "call_1", "move_user", {"node_id": "n2", "direction": "right"}),
            ],
            ["全部完成。"],
        ]

        events, fake_client = self._run_loop(
            queues=queues,
            tool_results={"move_user": {"ok": True}},
            user_text=raw_user_text,
            model="kimi-k2.6",
            return_client=True,
        )

        assert [e.type for e in events if e.type == "done"]
        assert len(fake_client.kwargs_history) >= 3
        cleaning_kwargs = fake_client.kwargs_history[0]
        planning_kwargs = fake_client.kwargs_history[1]
        execution_kwargs = fake_client.kwargs_history[2]
        assert cleaning_kwargs["kimi_thinking"] is False
        assert cleaning_kwargs["max_tokens"] == 1024
        assert "tools" not in cleaning_kwargs
        assert planning_kwargs["kimi_thinking"] is False
        assert "tools" not in planning_kwargs
        assert execution_kwargs["kimi_thinking"] is False
        assert "tools" in execution_kwargs

        planning_payload = json.dumps(
            planning_kwargs["messages"],
            ensure_ascii=False,
            default=str,
        )
        assert "effective_goal" in planning_payload
        assert "创建组织架构" in planning_payload
        assert raw_user_text not in planning_payload

        execution_payload = json.dumps(
            execution_kwargs["messages"],
            ensure_ascii=False,
            default=str,
        )
        assert "## 首轮执行计划" in execution_payload
        assert "苏女士 -> 黄宇" in execution_payload
        assert raw_user_text not in execution_payload

    def test_kimi_auto_valid_radial_intent_uses_fast_path_without_execution_llm(self, monkeypatch):
        monkeypatch.delenv("POWER_MAP_ROLLBACK_PROVIDER", raising=False)
        monkeypatch.setenv("POWER_MAP_LLM_PROFILE", "kimi")
        monkeypatch.setenv("POWER_MAP_KIMI_MODE", "auto")
        monkeypatch.setenv("POWER_MAP_RADIAL_FAST_PATH", "1")
        raw_user_text = "建一个完整组织架构：总裁办黄宇，下设财务部和销售部，负责人都向黄宇汇报。"
        cleaned_text = '{"effective_goal":"创建组织架构"}'
        plan_text = json.dumps(
            {
                "goal": "创建组织架构",
                "departments": [
                    {"name": "总裁办", "parent": ""},
                    {"name": "财务部", "parent": ""},
                    {"name": "销售部", "parent": ""},
                ],
                "people": [
                    {"name": "黄宇", "title": "CEO", "parent": "总裁办"},
                    {"name": "纪成", "title": "财务总监", "parent": "财务部"},
                    {"name": "张强", "title": "销售总监", "parent": "销售部"},
                ],
                "report_edges": [
                    {"source": "纪成", "target": "黄宇"},
                    {"source": "张强", "target": "黄宇"},
                ],
            },
            ensure_ascii=False,
        )

        events, fake_client = self._run_loop(
            queues=[[cleaned_text], [plan_text]],
            tool_results={},
            user_text=raw_user_text,
            model="kimi-k2.6",
            return_client=True,
        )

        done = [e for e in events if e.type == "done"]
        assert len(fake_client.kwargs_history) == 2
        assert done
        assert done[0].data["exit_reason"] == "radial_fast_path"
        assert done[0].data["radial_layout_used"] is True
        assert done[0].data["relayout_called"] is False

    def test_kimi_auto_discards_radial_plan_missing_required_entity(self, monkeypatch):
        monkeypatch.delenv("POWER_MAP_ROLLBACK_PROVIDER", raising=False)
        monkeypatch.setenv("POWER_MAP_LLM_PROFILE", "kimi")
        monkeypatch.setenv("POWER_MAP_KIMI_MODE", "auto")
        monkeypatch.setenv("POWER_MAP_RADIAL_FAST_PATH", "1")
        raw_user_text = (
            "背景说明：" + ("海油工程组织治理材料。" * 80)
            + "关键人员：吕亚平是研发中心领导；你本人是 ITC 副职/技术负责人。"
        )
        cleaned_text = json.dumps(
            {
                "g": "建立海油工程信息化条线",
                "d": [
                    ["海油工程", "", "company"],
                    ["研发中心", "海油工程", "department"],
                    ["ITC", "研发中心", "team"],
                ],
                "p": [
                    ["吕亚平", "研发中心领导", "研发中心"],
                    ["你本人", "ITC 副职/技术负责人", "ITC"],
                ],
                "e": [["你本人", "吕亚平", "reports_to"]],
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        bad_plan_text = json.dumps(
            {
                "goal": "建立海油工程信息化条线",
                "departments": [
                    {"name": "海油工程", "parent": ""},
                    {"name": "研发中心", "parent": "海油工程"},
                    {"name": "ITC", "parent": "研发中心"},
                ],
                "people": [
                    {"name": "吕亚平", "title": "研发中心领导", "parent": "研发中心"},
                ],
                "report_edges": [],
            },
            ensure_ascii=False,
        )

        events, fake_client = self._run_loop(
            queues=[[cleaned_text], [bad_plan_text], ["全部完成。"]],
            tool_results={},
            user_text=raw_user_text,
            model="kimi-k2.6",
            return_client=True,
            max_rounds=3,
        )

        done = [e for e in events if e.type == "done"]
        graph_states = [e for e in events if e.type == "graph_state"]
        assert len(fake_client.kwargs_history) == 2
        assert done
        assert done[0].data["exit_reason"] == "radial_fast_path"
        assert done[0].data["radial_layout_used"] is True
        assert graph_states
        graph_text = json.dumps(graph_states[-1].data, ensure_ascii=False, default=str)
        assert "你本人" in graph_text
        assert "吕亚平" in graph_text

    def test_kimi_planning_failure_falls_back_to_raw_execution(self, monkeypatch):
        monkeypatch.delenv("POWER_MAP_ROLLBACK_PROVIDER", raising=False)
        monkeypatch.setenv("POWER_MAP_LLM_PROFILE", "kimi")
        monkeypatch.setenv("POWER_MAP_KIMI_MODE", "auto")
        raw_user_text = (
            "请建立组织架构，并让下属都向负责人汇报。"
            "背景：这段会议里还有很多客户公司介绍、业务背景、历史沿革和情绪化描述，"
            "这些内容不需要进入图，只需要保留组织节点和真实汇报关系。"
        )
        cleaned_text = '{"effective_goal":"建立组织架构","report_edges":[]}'
        queues = [
            [cleaned_text],
            RuntimeError("planning failed"),
            ["全部完成。"],
            ["全部完成。"],
            ["全部完成。"],
        ]

        _events, fake_client = self._run_loop(
            queues=queues,
            tool_results={},
            user_text=raw_user_text,
            model="kimi-k2.6",
            return_client=True,
            max_rounds=4,
        )

        assert len(fake_client.kwargs_history) >= 3
        assert fake_client.kwargs_history[0]["kimi_thinking"] is False
        assert fake_client.kwargs_history[1]["kimi_thinking"] is False
        assert fake_client.kwargs_history[2]["kimi_thinking"] is False
        execution_payload = json.dumps(
            fake_client.kwargs_history[2]["messages"],
            ensure_ascii=False,
            default=str,
        )
        assert "effective_goal" in execution_payload
        assert "建立组织架构" in execution_payload
        assert raw_user_text not in execution_payload

    def test_kimi_cleaning_failure_falls_back_to_raw_planning(self, monkeypatch):
        monkeypatch.delenv("POWER_MAP_ROLLBACK_PROVIDER", raising=False)
        monkeypatch.setenv("POWER_MAP_LLM_PROFILE", "kimi")
        monkeypatch.setenv("POWER_MAP_KIMI_MODE", "auto")
        raw_user_text = "请建立组织架构，并让下属都向负责人汇报。"
        queues = [
            RuntimeError("cleaning failed"),
            ['{"goal":"建立组织架构","report_edges":[]}'],
            ["全部完成。"],
        ]

        _events, fake_client = self._run_loop(
            queues=queues,
            tool_results={},
            user_text=raw_user_text,
            model="kimi-k2.6",
            return_client=True,
            max_rounds=3,
        )

        assert len(fake_client.kwargs_history) >= 3
        assert fake_client.kwargs_history[0]["kimi_thinking"] is False
        assert fake_client.kwargs_history[1]["kimi_thinking"] is False
        planning_payload = json.dumps(
            fake_client.kwargs_history[1]["messages"],
            ensure_ascii=False,
            default=str,
        )
        assert raw_user_text in planning_payload

    def test_kimi_cleaning_expansion_is_rejected_before_planning(self, monkeypatch):
        monkeypatch.delenv("POWER_MAP_ROLLBACK_PROVIDER", raising=False)
        monkeypatch.setenv("POWER_MAP_LLM_PROFILE", "kimi")
        monkeypatch.setenv("POWER_MAP_KIMI_MODE", "auto")
        raw_user_text = "建组织架构：黄宇 CEO，苏女士向黄宇汇报。"
        expanded_cleaning = (
            '{"effective_goal":"创建一个完整而详细的组织架构图",'
            '"entities":["黄宇","苏女士","总裁办","公司治理背景","业务协同说明"],'
            '"parent_links":[{"child":"苏女士","parent":"总裁办","evidence":"扩写"}],'
            '"report_edges":[{"source":"苏女士","target":"黄宇","relation":"reports_to","evidence":"扩写"}],'
            '"ignored_background_summary":"这段输出比原文更长，应被拒收"}'
        )
        queues = [
            [expanded_cleaning],
            ['{"goal":"创建组织架构","report_edges":[{"source":"苏女士","target":"黄宇"}]}'],
            ["全部完成。"],
        ]

        _events, fake_client = self._run_loop(
            queues=queues,
            tool_results={},
            user_text=raw_user_text,
            model="kimi-k2.6",
            return_client=True,
            max_rounds=3,
        )

        assert len(fake_client.kwargs_history) >= 3
        planning_kwargs = fake_client.kwargs_history[1]
        assert planning_kwargs["kimi_thinking"] is False
        planning_payload = json.dumps(
            planning_kwargs["messages"],
            ensure_ascii=False,
            default=str,
        )
        assert raw_user_text in planning_payload
        assert expanded_cleaning not in planning_payload

    def test_kimi_cleaning_raw_passthrough_is_treated_as_raw(self, monkeypatch):
        monkeypatch.delenv("POWER_MAP_ROLLBACK_PROVIDER", raising=False)
        monkeypatch.setenv("POWER_MAP_LLM_PROFILE", "kimi")
        monkeypatch.setenv("POWER_MAP_KIMI_MODE", "auto")
        raw_user_text = "建组织架构：黄宇 CEO，苏女士向黄宇汇报。"
        queues = [
            [raw_user_text],
            ['{"goal":"创建组织架构","report_edges":[{"source":"苏女士","target":"黄宇"}]}'],
            ["全部完成。"],
        ]

        _events, fake_client = self._run_loop(
            queues=queues,
            tool_results={},
            user_text=raw_user_text,
            model="kimi-k2.6",
            return_client=True,
            max_rounds=3,
        )

        planning_kwargs = fake_client.kwargs_history[1]
        assert planning_kwargs["kimi_thinking"] is False
        planning_payload = json.dumps(
            planning_kwargs["messages"],
            ensure_ascii=False,
            default=str,
        )
        assert raw_user_text in planning_payload

    def test_kimi_cleaning_raw_ok_sentinel_is_treated_as_raw(self, monkeypatch):
        monkeypatch.delenv("POWER_MAP_ROLLBACK_PROVIDER", raising=False)
        monkeypatch.setenv("POWER_MAP_LLM_PROFILE", "kimi")
        monkeypatch.setenv("POWER_MAP_KIMI_MODE", "auto")
        raw_user_text = "建组织架构：黄宇 CEO，苏女士向黄宇汇报。"
        queues = [
            ["__RAW_OK__"],
            ['{"goal":"创建组织架构","report_edges":[{"source":"苏女士","target":"黄宇"}]}'],
            ["全部完成。"],
        ]

        _events, fake_client = self._run_loop(
            queues=queues,
            tool_results={},
            user_text=raw_user_text,
            model="kimi-k2.6",
            return_client=True,
            max_rounds=3,
        )

        planning_kwargs = fake_client.kwargs_history[1]
        planning_payload = json.dumps(
            planning_kwargs["messages"],
            ensure_ascii=False,
            default=str,
        )
        assert raw_user_text in planning_payload
        assert "__RAW_OK__" not in planning_payload


if __name__ == "__main__":
    t = TestRunLLMToolLoop()
    print("=== _run_llm_tool_loop regression tests ===")
    t.test_case1_no_tool_calls_exits_immediately()
    t.test_case2_single_tool_call_one_round()
    t.test_case3_multi_round_accumulates_messages()
    t.test_case4_max_rounds_exhausted()
    print("=== ALL 4 CASES PASSED ===")
