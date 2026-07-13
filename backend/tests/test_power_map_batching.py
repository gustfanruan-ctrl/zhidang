import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.power_map_service import (  # noqa: E402
    MergeContext,
    PowerNode,
    _build_batch_execution_nudge,
    _tool_call_signature,
    _tool_set_parent,
    _update_batch_execution_streaks,
)


def test_set_parent_streak_triggers_batch_nudge():
    streaks = {"single_create_node": 0, "single_set_parent": 0, "single_fit_container": 0}

    for _ in range(3):
        streaks = _update_batch_execution_streaks(
            streaks,
            [("set_parent", {"node_id": "n1", "new_parent_id": "p1"})],
        )

    hint = _build_batch_execution_nudge(streaks)

    assert streaks["single_set_parent"] == 3
    assert "set_parent" in hint
    assert "同一轮中发出多个 set_parent" in hint


def test_fit_streak_triggers_layered_fit_nudge():
    streaks = {"single_create_node": 0, "single_set_parent": 0, "single_fit_container": 0}

    for _ in range(2):
        streaks = _update_batch_execution_streaks(
            streaks,
            [("fit_container_to_children", {"container_id": "dept-1"})],
        )

    hint = _build_batch_execution_nudge(streaks)

    assert streaks["single_fit_container"] == 2
    assert "fit_container_to_children" in hint
    assert "同层叶子容器" in hint
    assert "relayout" in hint


def test_create_node_streak_triggers_batch_nudge():
    streaks = {"single_create_node": 0, "single_set_parent": 0, "single_fit_container": 0}

    for _ in range(2):
        streaks = _update_batch_execution_streaks(
            streaks,
            [("create_node", {"type": "department", "name": "设计院", "parent_id": "dept-1"})],
        )

    hint = _build_batch_execution_nudge(streaks)

    assert streaks["single_create_node"] == 2
    assert "create_node" in hint
    assert "同轮批量创建" in hint
    assert "强制" in hint


def test_create_edge_streak_triggers_batch_nudge():
    streaks = {"single_create_edge": 0}

    for _ in range(2):
        streaks = _update_batch_execution_streaks(
            streaks,
            [("create_edge", {"source_id": "u1", "target_id": "u2"})],
        )

    hint = _build_batch_execution_nudge(streaks)

    assert streaks["single_create_edge"] == 2
    assert "create_edge" in hint
    assert "一次性批量发出多个 create_edge" in hint
    assert "不要为层级归属补边" in hint


def test_multi_tool_round_resets_single_tool_streaks():
    streaks = {"single_create_node": 1, "single_set_parent": 2, "single_fit_container": 1}

    streaks = _update_batch_execution_streaks(
        streaks,
        [
            ("set_parent", {"node_id": "n1", "new_parent_id": "p1"}),
            ("set_parent", {"node_id": "n2", "new_parent_id": "p1"}),
        ],
    )

    assert streaks["single_create_node"] == 0
    assert streaks["single_set_parent"] == 0
    assert streaks["single_fit_container"] == 0
    assert _build_batch_execution_nudge(streaks) == ""


def test_move_dept_streak_prefers_relayout_for_from_zero_org_chart():
    streaks = {"single_move_dept": 0}

    for _ in range(3):
        streaks = _update_batch_execution_streaks(
            streaks,
            [("move_dept_with_children", {"dept_id": "d1", "new_x": 100, "new_y": 100})],
        )

    hint = _build_batch_execution_nudge(streaks)

    assert streaks["single_move_dept"] == 3
    assert "move_dept_with_children" in hint
    assert "relayout" in hint


def test_tool_call_signature_is_stable_for_reordered_args():
    left = _tool_call_signature("set_parent", {"new_parent_id": "p1", "node_id": "n1"})
    right = _tool_call_signature("set_parent", {"node_id": "n1", "new_parent_id": "p1"})

    assert left == right


def test_set_parent_returns_noop_when_parent_is_already_set():
    ctx = MergeContext()
    parent = PowerNode(id="p1", name="父部门", node_type="dept")
    child = PowerNode(id="n1", name="子部门", node_type="dept", parent_dept_id="p1")
    ctx.all_nodes = [parent, child]
    ctx.nodes_by_id = {n.id: n for n in ctx.all_nodes}
    ctx.nodes_by_name = {n.name: n for n in ctx.all_nodes}

    result = _tool_set_parent(ctx, "n1", "p1")

    assert result["ok"] is True
    assert result["no_op"] is True
    assert "do not repeat" in result["message"]
