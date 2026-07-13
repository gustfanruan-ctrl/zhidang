import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.power_map_service import (  # noqa: E402
    PowerNode,
    _apply_power_map_intent_to_context,
    _build_merge_context,
    _parse_power_map_intent,
    _tool_update_node,
)


def test_parse_update_nodes_intent_for_llm_rename_plan():
    plan = {
        "goal": "rename existing department",
        "update_nodes": [
            {
                "ref": "中央IT",
                "name": "【总部】立讯精密工业股份有限公司",
                "reason": "rename existing node",
            }
        ],
        "create_departments": [],
        "create_people": [],
        "parent_links": [],
        "report_edges": [],
    }

    intent = _parse_power_map_intent(json.dumps(plan, ensure_ascii=False))

    assert len(intent.update_nodes) == 1
    assert intent.update_nodes[0].ref == "中央IT"
    assert intent.update_nodes[0].name == "【总部】立讯精密工业股份有限公司"
    assert intent.departments == []


def test_update_node_keeps_name_index_in_sync():
    old_name = "中央IT"
    new_name = "【总部】立讯精密工业股份有限公司"
    ctx = _build_merge_context(
        [PowerNode(id="dept-it", node_type="dept", name=old_name, x=0, y=0, w=210, h=440)],
        [],
        "",
    )

    result = _tool_update_node(ctx, "dept-it", {"name": new_name})

    assert result["ok"] is True
    assert old_name not in ctx.nodes_by_name
    assert ctx.nodes_by_name[new_name] is ctx.all_nodes[0]


def test_backend_applies_llm_update_nodes_without_creating_new_node():
    old_name = "中央IT"
    new_name = "【总部】立讯精密工业股份有限公司"
    ctx = _build_merge_context(
        [PowerNode(id="dept-it", node_type="dept", name=old_name, x=0, y=0, w=210, h=440)],
        [],
        "",
    )
    intent = _parse_power_map_intent(
        json.dumps(
            {
                "goal": "rename existing department",
                "update_nodes": [{"ref": old_name, "name": new_name}],
                "create_departments": [],
                "create_people": [],
                "parent_links": [],
                "report_edges": [],
            },
            ensure_ascii=False,
        )
    )

    result = _apply_power_map_intent_to_context(ctx, intent)

    assert result["ok"] is True
    assert result["updated"] == 1
    assert result["created"] == 0
    assert len(ctx.all_nodes) == 1
    assert ctx.all_nodes[0].name == new_name
