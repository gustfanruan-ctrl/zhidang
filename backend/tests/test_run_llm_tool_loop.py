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

    async def messages_create_with_history_stream(self, **kwargs):
        if self.calls >= len(self._queues):
            return
        chunks = self._queues[self.calls]
        self.calls += 1
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

    def _run_loop(self, *, queues, tool_results, max_rounds=5) -> list:
        """Run _run_llm_tool_loop with mocks and return all events."""
        ctx = make_ctx()

        mock_cfg = MagicMock()
        mock_cfg.llm_api_key_encrypted = "fake-encrypted-key"
        mock_cfg.llm_base_url = "https://fake.api.com"
        mock_cfg.nl_chat_model = "gpt-4o"

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
                return_value=FakeLLMClient(queues),
            ),
        ):
            events = []

            async def _collect():
                async for ev in _run_llm_tool_loop(
                    ctx=ctx,
                    user_text="请审视截图，必要时调用布局工具进行美化。",
                    system_prompt="You are a layout assistant.",
                    tools=[{"type": "function", "function": {"name": "move_user", "parameters": {}}}],
                    cfg=mock_cfg,
                    screenshot_fn=fake_screenshot_fn,
                    max_rounds=max_rounds,
                    session_id="test-session",
                ):
                    events.append(ev)

            asyncio.run(_collect())

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


if __name__ == "__main__":
    t = TestRunLLMToolLoop()
    print("=== _run_llm_tool_loop regression tests ===")
    t.test_case1_no_tool_calls_exits_immediately()
    t.test_case2_single_tool_call_one_round()
    t.test_case3_multi_round_accumulates_messages()
    t.test_case4_max_rounds_exhausted()
    print("=== ALL 4 CASES PASSED ===")
