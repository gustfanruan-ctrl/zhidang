import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.power_map_service import (  # noqa: E402
    _build_llm_messages,
    _normalize_tool_call_ids,
)


def _multi_tool_history_messages() -> list[dict]:
    return [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "请调整组织架构"},
                {"type": "text", "text": "## 当前图结构\n节点 (2):\n- dept-a"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
            ],
        },
        {
            "role": "assistant",
            "content": "我先批量处理归属关系。",
            "tool_calls": [
                {
                    "id": "toolu_bdrk_old_1",
                    "type": "function",
                    "function": {
                        "name": "set_parent",
                        "arguments": json.dumps({"node_id": "n1", "new_parent_id": "dept-a"}),
                    },
                },
                {
                    "id": "toolu_bdrk_old_2",
                    "type": "function",
                    "function": {
                        "name": "set_parent",
                        "arguments": json.dumps({"node_id": "n2", "new_parent_id": "dept-a"}),
                    },
                },
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "toolu_bdrk_old_1",
            "content": json.dumps({"ok": True, "tool": "set_parent", "node_id": "n1"}),
        },
        {
            "role": "tool",
            "tool_call_id": "toolu_bdrk_old_2",
            "content": json.dumps({"ok": True, "tool": "set_parent", "node_id": "n2"}),
        },
    ]


def _collect_tool_ids(messages: list[dict]) -> tuple[list[str], list[str]]:
    assistant_ids: list[str] = []
    tool_ids: list[str] = []
    for msg in messages:
        if msg.get("role") == "assistant":
            assistant_ids.extend(
                str(tc.get("id") or "")
                for tc in (msg.get("tool_calls") or [])
            )
        elif msg.get("role") == "tool":
            tool_ids.append(str(msg.get("tool_call_id") or ""))
    return assistant_ids, tool_ids


def test_normalize_split_mode_splits_multi_tool_assistant_history():
    normalized = _normalize_tool_call_ids(
        _multi_tool_history_messages(),
        split_multi_tool_calls=True,
    )

    assert [msg["role"] for msg in normalized] == ["user", "assistant", "tool", "assistant", "tool"]
    assert len(normalized[1]["tool_calls"]) == 1
    assert len(normalized[3]["tool_calls"]) == 1

    assistant_ids, tool_ids = _collect_tool_ids(normalized)

    assert len(assistant_ids) == 2
    assert len(set(assistant_ids)) == 2
    assert tool_ids == assistant_ids
    assert all(tc_id.startswith("call_") for tc_id in assistant_ids)
    assert "toolu_bdrk_old" not in json.dumps(normalized, ensure_ascii=False)


def test_normalize_preserve_mode_keeps_multi_tool_assistant_history():
    normalized = _normalize_tool_call_ids(
        _multi_tool_history_messages(),
        split_multi_tool_calls=False,
    )

    assert [msg["role"] for msg in normalized] == ["user", "assistant", "tool", "tool"]
    assert len(normalized[1]["tool_calls"]) == 2

    assistant_ids, tool_ids = _collect_tool_ids(normalized)

    assert len(assistant_ids) == 2
    assert len(set(assistant_ids)) == 2
    assert tool_ids == assistant_ids
    assert all(tc_id.startswith("call_") for tc_id in assistant_ids)
    assert "toolu_bdrk_old" not in json.dumps(normalized, ensure_ascii=False)


def test_build_llm_messages_localizes_tool_ids_in_split_mode():
    normalized = _build_llm_messages(
        _multi_tool_history_messages(),
        current_round=4,
        split_multi_tool_calls=True,
    )

    assert [msg["role"] for msg in normalized] == ["user", "assistant", "tool", "assistant", "tool"]
    assistant_ids, tool_ids = _collect_tool_ids(normalized)

    assert tool_ids == assistant_ids
    assert "toolu_bdrk_old" not in json.dumps(normalized, ensure_ascii=False)
    assert "[graph_state at round 1 - elided, see latest round]" in json.dumps(
        normalized,
        ensure_ascii=False,
    )


def test_build_llm_messages_localizes_tool_ids_in_preserve_mode():
    accumulated = _multi_tool_history_messages() + [
        {
            "role": "user",
            "content": [{"type": "text", "text": "本轮已批量完成 2 个 set_parent，请继续按批量执行。"}],
        }
    ]

    normalized = _build_llm_messages(
        accumulated,
        current_round=4,
        split_multi_tool_calls=False,
    )

    assistant_ids, tool_ids = _collect_tool_ids(normalized)

    assert [msg["role"] for msg in normalized[:4]] == ["user", "assistant", "tool", "tool"]
    assert len(normalized[1]["tool_calls"]) == 2
    assert tool_ids == assistant_ids
    assert "toolu_bdrk_old" not in json.dumps(normalized, ensure_ascii=False)
    assert any(
        "本轮已批量完成 2 个 set_parent" in json.dumps(msg.get("content"), ensure_ascii=False)
        for msg in normalized
        if msg.get("role") == "user"
    )
