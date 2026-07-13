from backend.app.services.power_map_service import (
    MergeContext,
    PowerNode,
    _augment_layout_digest,
    _ctx_layout_digest,
    _layout_digest_to_text,
    _tool_check_geometry,
)


def test_layout_digest_reports_visual_parent_and_geometry_problems():
    raw = {
        "ok": True,
        "nodes": [
            {
                "runtime_id": "dept-a",
                "db_id": "dept-a-db",
                "name": "信息中心",
                "type": "dept",
                "box": {"x": 0, "y": 0, "w": 200, "h": 160},
                "visible": True,
            },
            {
                "runtime_id": "dept-b",
                "db_id": "dept-b-db",
                "name": "业务中心",
                "type": "dept",
                "box": {"x": 120, "y": 40, "w": 180, "h": 140},
                "visible": True,
            },
            {
                "runtime_id": "user-a",
                "db_id": "user-a-db",
                "name": "张三",
                "type": "user",
                "box": {"x": 170, "y": 120, "w": 80, "h": 40},
                "parent_runtime_id": "dept-a",
                "parent_db_id": "dept-a-db",
                "parent_name": "信息中心",
                "visible": True,
            },
            {
                "runtime_id": "user-b",
                "db_id": "user-b-db",
                "name": "李四",
                "type": "user",
                "box": {"x": 400, "y": 300, "w": 80, "h": 40},
                "visible": True,
            },
        ],
        "edges": [],
    }

    digest = _augment_layout_digest(raw)

    assert digest["summary"]["node_count"] == 4
    assert digest["summary"]["problem_count"] == 3
    assert any(p["type"] == "dept_partial_overlap" for p in digest["visual_problems"])
    child_problem = next(p for p in digest["visual_problems"] if p["type"] == "child_outside_parent")
    assert child_problem["overflow"] == {"right": 50}
    assert any(p["type"] == "user_without_visual_parent" for p in digest["visual_problems"])
    assert digest["nodes"][0]["children"] == ["张三"]
    assert digest["nodes"][2]["zone_in_parent"]["vertical"] == "bottom"
    assert digest["nodes"][2]["zone_in_parent"]["horizontal"] == "right"

    text = _layout_digest_to_text(digest)
    assert "当前沙箱视觉摘要" in text
    assert "信息中心(dept)" in text
    assert "child_outside_parent" in text


def test_layout_digest_uses_projection_overlap_for_precise_sibling_direction():
    raw = {
        "ok": True,
        "nodes": [
            {
                "runtime_id": "dept-a",
                "db_id": "dept-a-db",
                "name": "信息中心",
                "type": "dept",
                "box": {"x": 0, "y": 0, "w": 120, "h": 100},
                "visible": True,
            },
            {
                "runtime_id": "dept-b",
                "db_id": "dept-b-db",
                "name": "业务中心",
                "type": "dept",
                "box": {"x": 170, "y": 10, "w": 120, "h": 100},
                "visible": True,
            },
            {
                "runtime_id": "dept-c",
                "db_id": "dept-c-db",
                "name": "财务中心",
                "type": "dept",
                "box": {"x": 180, "y": 170, "w": 120, "h": 100},
                "visible": True,
            },
        ],
        "edges": [],
    }

    digest = _augment_layout_digest(raw)
    relations = digest["spatial_relations"]

    right_relation = next(
        r for r in relations
        if r["a"] == "业务中心" and r["b"] == "信息中心"
    )
    assert right_relation["relation"] == "right_of"
    assert right_relation["confidence"] >= 0.8
    assert right_relation["basis"]["orthogonal_overlap_ratio"] >= 0.9

    diagonal_relation = next(
        r for r in relations
        if r["a"] == "财务中心" and r["b"] == "信息中心"
    )
    assert diagonal_relation["relation"] == "lower_right_of"
    assert diagonal_relation["primary_axis"] in {"diagonal", "right_of", "below"}


def test_layout_digest_does_not_compare_parent_and_child_as_siblings():
    raw = {
        "ok": True,
        "nodes": [
            {
                "runtime_id": "dept-a",
                "db_id": "dept-a-db",
                "name": "集团",
                "type": "dept",
                "box": {"x": 0, "y": 0, "w": 500, "h": 400},
                "visible": True,
            },
            {
                "runtime_id": "dept-b",
                "db_id": "dept-b-db",
                "name": "子部门",
                "type": "dept",
                "box": {"x": 40, "y": 30, "w": 180, "h": 120},
                "parent_runtime_id": "dept-a",
                "parent_db_id": "dept-a-db",
                "parent_name": "集团",
                "visible": True,
            },
        ],
        "edges": [],
    }

    digest = _augment_layout_digest(raw)

    assert digest["visual_problems"] == []
    assert digest["spatial_relations"] == []
    assert digest["nodes"][1]["zone_in_parent"]["vertical"] == "top"
    assert digest["nodes"][1]["zone_in_parent"]["horizontal"] == "left"


def test_ctx_layout_digest_fallback_uses_current_merge_context():
    parent = PowerNode(id="dept-a", name="集团", node_type="dept", x=0, y=0, w=500, h=400)
    child = PowerNode(
        id="dept-b",
        name="子部门",
        node_type="dept",
        x=40,
        y=30,
        w=180,
        h=120,
        parent_dept_id="dept-a",
    )
    ctx = MergeContext(
        nodes_by_id={parent.id: parent, child.id: child},
        nodes_by_name={parent.name: parent, child.name: child},
        depts_by_name={parent.name: parent, child.name: child},
        all_nodes=[parent, child],
        edges=[],
    )

    digest = _ctx_layout_digest(ctx)

    assert digest["ok"] is True
    assert digest["summary"]["node_count"] == 2
    assert digest["nodes"][1]["parent_name"] == "集团"
    assert digest["nodes"][1]["zone_in_parent"]["vertical"] == "top"
    assert digest["nodes"][1]["zone_in_parent"]["horizontal"] == "left"


def test_check_geometry_resolves_placeholder_node_ids_by_current_order():
    node = PowerNode(id="real-node-id", name="真实节点", node_type="dept", x=0, y=0, w=300, h=200)
    ctx = MergeContext(
        nodes_by_id={node.id: node},
        nodes_by_name={node.name: node},
        depts_by_name={node.name: node},
        all_nodes=[node],
        edges=[],
    )

    result = _tool_check_geometry(ctx, ["n1", "n2"])

    assert result["ok"] is True
    assert result["action"] == "finalize_if_user_request_satisfied"
    assert result["checked_node_count"] == 1
    assert result["resolved_node_ref_sample"][0] == {
        "input": "n1",
        "id": "real-node-id",
        "name": "真实节点",
        "method": "ordinal",
    }
    assert result["resolved_node_ref_count"] == 2
    assert result["ignored_unknown_node_ids"] == ["n2"]
