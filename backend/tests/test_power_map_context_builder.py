from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tests.power_map_context_builder as builder_mod
from tests.power_map_context_builder import PowerMapContextBuilder, build_pyramid_text


def _sample_graph() -> dict:
    return {
        "ok": True,
        "nodes": [
            {
                "id": "dept-1",
                "type": "department",
                "name": "总裁办",
                "parent_id": "",
                "role": "",
                "position": "",
                "children_ids": ["person-1", "person-2"],
                "incoming_edges": [],
                "outgoing_edges": [],
                "x": 0,
                "y": 0,
                "w": 400,
                "h": 240,
                "depth": 0,
            },
            {
                "id": "person-1",
                "type": "person",
                "name": "黄宇",
                "parent_id": "dept-1",
                "role": "A",
                "position": "CEO",
                "children_ids": [],
                "incoming_edges": [],
                "outgoing_edges": [],
                "x": 80,
                "y": 40,
                "w": 160,
                "h": 72,
                "depth": 1,
            },
            {
                "id": "person-2",
                "type": "person",
                "name": "苏女士",
                "parent_id": "dept-1",
                "role": "",
                "position": "总裁助理",
                "children_ids": [],
                "incoming_edges": [],
                "outgoing_edges": [],
                "x": 80,
                "y": 140,
                "w": 160,
                "h": 72,
                "depth": 1,
            },
        ],
        "edges": [
            {
                "id": "edge-1",
                "source_id": "person-2",
                "target_id": "person-1",
                "edge_type": "reports_to",
                "remark": "",
            }
        ],
    }


def test_build_pyramid_text_contains_all_layers():
    graph = _sample_graph()
    text = build_pyramid_text(
        graph,
        previous_graph=None,
        focus_ids=["dept-1", "person-1", "person-2"],
        touched_ids=set(),
        touched_edge_ids=set(),
        history=[],
        current_round=type("RoundStub", (), {"steps": [], "round_no": 1})(),
        max_json_nodes=10,
    )

    assert "LAYER 1: 摘要" in text
    assert "LAYER 2: 拓扑视图" in text
    assert "LAYER 3: 详细数据" in text
    assert "LAYER 4: 派生分析" in text
    assert "LAYER 5: 操作历史" in text
    assert "graph TD" in text
    assert '"all_node_count": 3' in text


def test_context_builder_records_recent_tool_history(monkeypatch):
    builder = PowerMapContextBuilder(focus_limit=3, max_json_nodes=5)
    graph1 = _sample_graph()
    graph2 = _sample_graph()
    graph2["nodes"].append(
        {
            "id": "dept-2",
            "type": "department",
            "name": "销售部",
            "parent_id": "",
            "role": "",
            "position": "",
            "children_ids": [],
            "incoming_edges": [],
            "outgoing_edges": [],
            "x": 500,
            "y": 0,
            "w": 320,
            "h": 200,
            "depth": 0,
        }
    )

    state = {"value": graph1}

    def fake_get_graph_state(_ctx):
        return state["value"]

    monkeypatch.setattr(builder_mod, "_get_graph_state", fake_get_graph_state)

    builder.begin_round(1)
    first = builder.build(object())
    assert "本轮变化：" in first

    state["value"] = graph2
    builder.begin_round(2)
    builder.record_tool_call("create_node", {"name": "销售部", "parent_id": ""})
    builder.record_tool_result("create_node", {"ok": True, "node_id": "dept-2", "name": "销售部"})
    second = builder.build(object())

    assert "新增 1 节点" in second
    assert "create_node" in second
    assert "销售部" in second
