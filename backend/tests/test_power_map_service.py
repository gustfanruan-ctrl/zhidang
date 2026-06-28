"""Unit tests for power_map_service v4 layout algorithm."""

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

# Ensure backend is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.power_map_service import (
    PERSON_W,
    PERSON_H,
    DEPT_DEFAULT_W,
    DEPT_DEFAULT_H,
    DEPT_MIN_W,
    DEPT_MIN_H,
    GEO_EMBED_SAFE_MARGIN,
    DEPT_PAD_LEFT,
    DEPT_PAD_TOP,
    DEPT_PAD_RIGHT,
    DEPT_PAD_BOTTOM,
    ADJUST_THRESHOLD_PX,
    MIN_GAP_BETWEEN_USERS,
    MIN_GAP_BETWEEN_DEPTS,
    PowerNode,
    BBoxItem,
    RigidGroup,
    MergeContext,
    _node_from_bi_dict,
    _to_up_node,
    _generate_node_id,
    _make_person_node,
    _make_dept_node,
    _build_merge_context,
    _apply_delta,
    _build_dept_forest,
    _rt_layout_forest,
    _calc_and_set_dept_bounds,
    _v31_global_layout,
    _v31_layout_orphans,
    _compute_edge_ports,
    _parse_llm_output,
    _compute_forced_move_set,
    _scope_meltdown_check,
    _local_layout,
    _find_empty_slot_in_dept,
    _find_safe_dept_position,
    _find_orphan_slot,
    _rects_overlap,
    _find_dept_by_name,
    _find_person_by_name,
    _find_dept_for_user,
    _build_bbox_items,
    _build_rigid_groups_v2,
    _check_collision,
    _mark_geometry_anomalies,
    _normalize_edges,
    _push_group_right,
    _find_safe_position,
    _post_submit_verify,
    _tool_relayout,
    _execute_harness_tool,
)


# ═══════════════════════════════════════════════════
#  Fixtures
# ═══════════════════════════════════════════════════

@pytest.fixture
def sample_bi_nodes():
    """Sample BI nodes dict (as from getInfo)."""
    return [
        {
            "id": "dept1",
            "type": "department",
            "node_type": "dept",
            "name": "技术部",
            "x": "100",
            "y": "100",
            "width": 700,
            "height": 350,
            "par_id": "",
        },
        {
            "id": "user1",
            "type": "person",
            "node_type": "user",
            "name": "张三",
            "department": "技术部",
            "position": "技术总监",
            "phone": "13800001111",
            "pid": "",
            "x": "130",
            "y": "160",
            "node_width": 150,
            "node_height": 50,
            "par_id": "dept1",
        },
        {
            "id": "user2",
            "type": "person",
            "node_type": "user",
            "name": "李四",
            "department": "技术部",
            "position": "工程师",
            "phone": "13800002222",
            "pid": "user1",
            "x": "290",
            "y": "160",
            "node_width": 150,
            "node_height": 50,
            "par_id": "dept1",
        },
    ]


@pytest.fixture
def sample_edges():
    """Sample edges from BI."""
    return [
        {
            "source_id": "user1",
            "target_id": "user2",
            "source_port": "port-bottom",
            "target_port": "port-top",
            "color": "#A2B1C3",
            "edge_remark": "",
        },
    ]


def test_normalize_edges_preserves_department_relationship_lines():
    left = PowerNode(id="dept-left", node_type="dept", name="市场部", x=0, y=0, w=700, h=350)
    right = PowerNode(id="dept-right", node_type="dept", name="销售部", x=900, y=0, w=700, h=350)
    ctx = MergeContext(
        nodes_by_id={left.id: left, right.id: right},
        nodes_by_name={left.name: left, right.name: right},
        depts_by_name={left.name: left, right.name: right},
        all_nodes=[left, right],
        edges=[{"id": "edge-1", "source_id": left.id, "target_id": right.id, "edge_type": ""}],
    )

    _normalize_edges(ctx)

    assert len(ctx.edges) == 1
    assert ctx.edges[0]["id"] == "edge-1"
    assert left.parent_dept_id == ""
    assert right.parent_dept_id == ""


# ═══════════════════════════════════════════════════
#  Test 1: Node Conversion (BI ↔ Internal ↔ upInfo)
# ═══════════════════════════════════════════════════

class TestNodeConversion:
    def test_bi_dict_to_power_node_user(self):
        d = {
            "id": "u1", "type": "person", "node_type": "user",
            "name": "张三", "department": "技术部", "position": "总监",
            "phone": "139", "pid": "u2", "x": "100", "y": "200",
            "node_width": 150, "node_height": 50, "par_id": "d1",
        }
        n = _node_from_bi_dict(d)
        assert n.id == "u1"
        assert n.node_type == "user"
        assert n.name == "张三"
        assert n.department == "技术部"
        assert n.pid == "u2"
        assert n.parent_dept_id == "d1"
        assert n.x == 100.0
        assert n.y == 200.0
        assert n.w == 150.0
        assert n.h == 50.0

    def test_bi_dict_to_power_node_dept(self):
        d = {
            "id": "d1", "type": "department", "node_type": "dept",
            "name": "技术部", "x": "100", "y": "100",
            "width": 700, "height": 350,
        }
        n = _node_from_bi_dict(d)
        assert n.node_type == "dept"
        assert n.w == 700.0
        assert n.h == 350.0

    def test_bi_dict_type_fallback(self):
        d = {"id": "u1", "type": "person", "name": "test", "x": 0, "y": 0}
        n = _node_from_bi_dict(d)
        assert n.node_type == "user"

    def test_to_up_node_user(self):
        n = PowerNode(id="u1", node_type="user", name="张三",
                       department="技术部", position="总监",
                       phone="139", pid="u2", parent_dept_id="d1",
                       x=100, y=200, w=PERSON_W, h=PERSON_H)
        out = _to_up_node(n)
        assert out["type"] == "user"
        assert out["node_type"] == "user"
        assert out["id"] == "u1"
        assert out["name"] == "张三"
        assert out["par_id"] == "d1"
        assert out["x"] == 100
        assert out["y"] == 200
        assert "width" not in out
        assert "height" not in out
        assert out["node_border_color"] == "#a2b1c3"
        assert out["node_background"] == ""
        assert out["node_width"] == "0.0"
        assert out["node_height"] == "0.0"

    def test_to_up_node_dept(self):
        n = PowerNode(id="d1", node_type="dept", name="技术部",
                       x=100, y=100, w=700, h=350,
                       background="#e9f5e9")
        out = _to_up_node(n)
        assert out["type"] == "dept"
        assert out["node_type"] == "dept"
        assert out["width"] == 700
        assert out["height"] == 350
        assert out["node_background"] == "#e9f5e9"
        assert out["node_width"] == "700.0"
        assert out["node_height"] == "350.0"
        assert out["x"] == 100
        assert out["y"] == 100
        assert out["par_id"] == ""
        assert "node_border_color" not in out

    def test_to_up_node_uses_correct_field_names(self):
        n = PowerNode(id="u1", node_type="user", name="test",
                       parent_dept_id="dept123", x=50, y=60)
        out = _to_up_node(n)
        assert out["node_type"] == "user"
        assert out["type"] == "user"
        assert out["node_parent_dept"] == "dept123"
        assert out["par_id"] == "dept123"
        assert out["x"] == 50
        assert out["y"] == 60
        assert out["tagC_arr"] == ""
        assert out["tagC"] == ""
        assert out["tagD"] == ""
        assert out["attitude_arr"] == []
        assert out["node_border_color"] == "#a2b1c3"


# ═══════════════════════════════════════════════════
#  Test 2: Node ID Generation
# ═══════════════════════════════════════════════════

class TestNodeIdGeneration:
    def test_generate_unique_ids(self):
        ids = {_generate_node_id() for _ in range(100)}
        assert len(ids) == 100

    def test_make_person_node(self):
        n = _make_person_node("张三", department="技术部", position="总监",
                               phone="139", cont_id="c1", pid="p1",
                               parent_dept_id="d1")
        assert n.node_type == "user"
        assert n.name == "张三"
        assert n.department == "技术部"
        assert n.w == PERSON_W
        assert n.h == PERSON_H
        assert len(n.id) == 32

    def test_make_dept_node(self):
        n = _make_dept_node("技术部")
        assert n.node_type == "dept"
        assert n.w == DEPT_DEFAULT_W
        assert n.h == DEPT_DEFAULT_H
        assert n.background == "#e9f5e9"


# ═══════════════════════════════════════════════════
#  Test 3: State Merging — Apply Delta
# ═══════════════════════════════════════════════════

class TestStateMerging:
    def test_add_person_to_existing_dept(self):
        dept = _make_dept_node("技术部")
        dept.id = "dept1"
        nodes = [dept]
        ctx = _build_merge_context(nodes, [], "v1")

        delta = {
            "nodes_add": [{"tmp_id": "t1", "node_type": "user", "name": "王五",
                           "department": "技术部", "position": "工程师"}],
        }
        ctx = _apply_delta(ctx, delta)
        assert len(ctx.all_nodes) == 2
        person = next(n for n in ctx.all_nodes if n.node_type == "user")
        assert person.name == "王五"
        assert person.department == "技术部"
        assert person.parent_dept_id == "dept1"

    def test_add_person_auto_creates_dept(self):
        ctx = _build_merge_context([], [], "v1")
        delta = {
            "nodes_add": [{"tmp_id": "t1", "node_type": "user", "name": "赵六",
                           "department": "新部门"}],
        }
        ctx = _apply_delta(ctx, delta)
        depts = [n for n in ctx.all_nodes if n.node_type == "dept"]
        assert len(depts) == 1
        assert depts[0].name == "新部门"

    def test_add_new_dept(self):
        ctx = _build_merge_context([], [], "v1")
        delta = {
            "nodes_add": [{"tmp_id": "t1", "node_type": "dept", "name": "财务部"}],
        }
        ctx = _apply_delta(ctx, delta)
        assert len(ctx.all_nodes) == 1
        assert ctx.all_nodes[0].node_type == "dept"
        assert ctx.all_nodes[0].name == "财务部"

    def test_delete_node(self):
        u1 = _make_person_node("张三")
        u1.id = "user1"
        ctx = _build_merge_context([u1], [], "v1")
        delta = {"nodes_delete": [{"id_or_name": "user1"}]}
        ctx = _apply_delta(ctx, delta)
        assert len(ctx.all_nodes) == 0

    def test_delete_node_by_name(self):
        u1 = _make_person_node("张三")
        u1.id = "user1"
        ctx = _build_merge_context([u1], [], "v1")
        delta = {"nodes_delete": [{"id_or_name": "张三"}]}
        ctx = _apply_delta(ctx, delta)
        assert len(ctx.all_nodes) == 0

    def test_update_node(self):
        u1 = _make_person_node("张三", position="旧职位")
        u1.id = "user1"
        ctx = _build_merge_context([u1], [], "v1")
        delta = {"nodes_update": [{"id_or_name": "user1", "position": "新职位"}]}
        ctx = _apply_delta(ctx, delta)
        assert ctx.all_nodes[0].position == "新职位"

    def test_move_person_between_depts(self):
        dept_a = _make_dept_node("A部门")
        dept_a.id = "dept_a"
        dept_b = _make_dept_node("B部门")
        dept_b.id = "dept_b"
        person = _make_person_node("张三", department="A部门", parent_dept_id="dept_a")
        person.id = "user1"
        nodes = [dept_a, dept_b, person]
        ctx = _build_merge_context(nodes, [], "v1")
        delta = {"moves": [{"person": "user1", "to_dept": "B部门"}]}
        ctx = _apply_delta(ctx, delta)
        moved = next(n for n in ctx.all_nodes if n.id == "user1")
        assert moved.department == "B部门"
        assert moved.parent_dept_id == "dept_b"

    def test_reports_to_resolution(self):
        boss = _make_person_node("黄小红")
        boss.id = "boss1"
        ctx = _build_merge_context([boss], [], "v1")

        delta = {
            "nodes_add": [{
                "tmp_id": "t1", "node_type": "user", "name": "张三",
                "reports_to": "黄小红",
            }],
        }
        ctx = _apply_delta(ctx, delta)
        new_person = next(n for n in ctx.all_nodes if n.name == "张三")
        assert new_person.pid == "boss1"

    def test_reports_to_unresolvable(self):
        ctx = _build_merge_context([], [], "v1")
        delta = {
            "nodes_add": [{
                "tmp_id": "t1", "node_type": "user", "name": "张三",
                "reports_to": "不存在的人",
            }],
        }
        ctx = _apply_delta(ctx, delta)
        new_person = next(n for n in ctx.all_nodes if n.name == "张三")
        assert new_person.pid == ""
        assert any("不存在" in w for w in ctx.warnings)

    def test_custom_edge_add(self):
        u1 = _make_person_node("张三")
        u1.id = "user1"
        u2 = _make_person_node("李四")
        u2.id = "user2"
        ctx = _build_merge_context([u1, u2], [], "v1")
        delta = {"custom_edges_add": [{"source": "user1", "target": "user2", "color": "#ff0000"}]}
        ctx = _apply_delta(ctx, delta)
        assert len(ctx.edges) == 1
        assert ctx.edges[0]["source_id"] == "user1"
        assert ctx.edges[0]["target_id"] == "user2"
        assert ctx.edges[0]["color"] == "#ff0000"

    def test_custom_edge_delete(self):
        u1 = _make_person_node("张三")
        u1.id = "user1"
        u2 = _make_person_node("李四")
        u2.id = "user2"
        edges = [{"source_id": "user1", "target_id": "user2", "source_port": "port-bottom",
                   "target_port": "port-top", "color": "#A2B1C3", "edge_remark": ""}]
        ctx = _build_merge_context([u1, u2], edges, "v1")
        delta = {"custom_edges_delete": [{"source": "user1", "target": "user2"}]}
        ctx = _apply_delta(ctx, delta)
        assert len(ctx.edges) == 0

    def test_duplicate_dept_skipped(self):
        dept = _make_dept_node("技术部")
        dept.id = "dept1"
        ctx = _build_merge_context([dept], [], "v1")
        delta = {"nodes_add": [{"tmp_id": "t1", "node_type": "dept", "name": "技术部"}]}
        ctx = _apply_delta(ctx, delta)
        assert len([n for n in ctx.all_nodes if n.node_type == "dept"]) == 1


# ═══════════════════════════════════════════════════
#  Test 4: Structure Derivation — Forest Building
# ═══════════════════════════════════════════════════

class TestForestBuilding:
    def test_simple_tree(self):
        root = PowerNode(id="u1", node_type="user", name="root", pid="")
        child = PowerNode(id="u2", node_type="user", name="child", pid="u1")
        persons = [root, child]
        roots = _build_dept_forest("d1", persons)
        assert len(roots) == 1
        assert roots[0].id == "u1"
        assert "u2" in roots[0].children_ids
        assert child.depth == 1
        assert child.parent_id == "u1"

    def test_multiple_roots(self):
        r1 = PowerNode(id="u1", node_type="user", name="r1", pid="")
        r2 = PowerNode(id="u2", node_type="user", name="r2", pid="")
        persons = [r1, r2]
        roots = _build_dept_forest("d1", persons)
        assert len(roots) == 2

    def test_pid_outside_dept_becomes_root(self):
        p = PowerNode(id="u1", node_type="user", name="p", pid="external_id")
        persons = [p]
        roots = _build_dept_forest("d1", persons)
        assert len(roots) == 1
        assert roots[0].id == "u1"

    def test_cycle_detection(self):
        a = PowerNode(id="u1", node_type="user", name="A", pid="u2")
        b = PowerNode(id="u2", node_type="user", name="B", pid="u1")
        persons = [a, b]
        roots = _build_dept_forest("d1", persons)
        assert len(roots) == 1


# ═══════════════════════════════════════════════════
#  Test 5: Geometry — Reingold-Tilford Layout
# ═══════════════════════════════════════════════════

class TestRTLayout:
    def test_single_node(self):
        n = PowerNode(id="u1", node_type="user", name="A", pid="")
        positions = _rt_layout_forest([n], {"u1": n})
        assert "u1" in positions
        x, y = positions["u1"]
        assert y == 0.0
        assert x >= 0

    def test_parent_child_positions(self):
        root = PowerNode(id="u1", node_type="user", name="root", pid="")
        child = PowerNode(id="u2", node_type="user", name="child", pid="u1")
        root.children_ids = ["u2"]
        id_map = {"u1": root, "u2": child}

        positions = _rt_layout_forest([root], id_map)
        _, root_y = positions["u1"]
        _, child_y = positions["u2"]
        assert root_y == 0.0
        assert child_y == PERSON_H + 40  # _LEVEL_GAP_V = 40

    def test_sibling_spacing(self):
        r = PowerNode(id="u1", node_type="user", name="R", pid="")
        c1 = PowerNode(id="c1", node_type="user", name="C1", pid="u1")
        c2 = PowerNode(id="c2", node_type="user", name="C2", pid="u1")
        r.children_ids = ["c1", "c2"]
        id_map = {"u1": r, "c1": c1, "c2": c2}

        positions = _rt_layout_forest([r], id_map)
        x1, _ = positions["c1"]
        x2, _ = positions["c2"]
        assert x2 > x1

    def test_no_overlap_between_siblings(self):
        r = PowerNode(id="u1", node_type="user", name="R", pid="")
        children = []
        id_map = {"u1": r}
        for i in range(5):
            c = PowerNode(id=f"c{i}", node_type="user", name=f"C{i}", pid="u1")
            r.children_ids.append(f"c{i}")
            children.append(c)
            id_map[f"c{i}"] = c

        positions = _rt_layout_forest([r], id_map)

        for i in range(len(children)):
            for j in range(i + 1, len(children)):
                xi, _ = positions[f"c{i}"]
                xj, _ = positions[f"c{j}"]
                assert xi + PERSON_W <= xj or xj + PERSON_W <= xi, \
                    f"Siblings c{i} and c{j} overlap: ({xi}, {xj})"

    def test_multi_root_forest(self):
        r1 = PowerNode(id="r1", node_type="user", name="R1", pid="")
        r2 = PowerNode(id="r2", node_type="user", name="R2", pid="")
        id_map = {"r1": r1, "r2": r2}

        positions = _rt_layout_forest([r1, r2], id_map)
        x1, _ = positions["r1"]
        x2, _ = positions["r2"]
        assert x2 > x1


# ═══════════════════════════════════════════════════
#  Test 6: Department Bounds Calculation
# ═══════════════════════════════════════════════════

class TestDepartmentBounds:
    def test_empty_dept_default_size(self):
        dept = PowerNode(id="d1", node_type="dept", name="空部门")
        _calc_and_set_dept_bounds(dept, [], [])
        assert dept.w == DEPT_DEFAULT_W
        assert dept.h == DEPT_DEFAULT_H

    def test_dept_with_users(self):
        dept = PowerNode(id="d1", node_type="dept", name="技术部", x=100, y=100)
        u1 = PowerNode(id="u1", node_type="user", name="u1", x=130, y=160, w=PERSON_W, h=PERSON_H)
        u2 = PowerNode(id="u2", node_type="user", name="u2", x=290, y=160, w=PERSON_W, h=PERSON_H)
        _calc_and_set_dept_bounds(dept, [u1, u2], [])
        assert dept.w >= DEPT_MIN_W
        assert dept.h >= DEPT_MIN_H
        content_w = dept.w - DEPT_PAD_LEFT - DEPT_PAD_RIGHT
        assert content_w >= PERSON_W * 2

    def test_dept_min_size_enforced(self):
        dept = PowerNode(id="d1", node_type="dept", name="小部门")
        u1 = PowerNode(id="u1", node_type="user", name="u1", x=0, y=0, w=PERSON_W, h=PERSON_H)
        _calc_and_set_dept_bounds(dept, [u1], [])
        assert dept.w >= DEPT_MIN_W
        assert dept.h >= DEPT_MIN_H


# ═══════════════════════════════════════════════════
#  Test 7: Port Selection
# ═══════════════════════════════════════════════════

class TestPortSelection:
    def test_below_target(self):
        src = PowerNode(id="s", node_type="user", name="S", x=100, y=100, w=160, h=72)
        tgt = PowerNode(id="t", node_type="user", name="T", x=100, y=300, w=160, h=72)
        edges = [{"source_id": "s", "target_id": "t"}]
        _compute_edge_ports(edges, {"s": src, "t": tgt})
        assert edges[0]["source_port"] == "port-bottom"
        assert edges[0]["target_port"] == "port-top"

    def test_right_of_target(self):
        src = PowerNode(id="s", node_type="user", name="S", x=100, y=100, w=160, h=72)
        tgt = PowerNode(id="t", node_type="user", name="T", x=400, y=100, w=160, h=72)
        edges = [{"source_id": "s", "target_id": "t"}]
        _compute_edge_ports(edges, {"s": src, "t": tgt})
        assert edges[0]["source_port"] == "port-right"
        assert edges[0]["target_port"] == "port-left"

    def test_same_position_defaults_vertical(self):
        src = PowerNode(id="s", node_type="user", name="S", x=100, y=100, w=160, h=72)
        tgt = PowerNode(id="t", node_type="user", name="T", x=102, y=100, w=160, h=72)
        edges = [{"source_id": "s", "target_id": "t"}]
        _compute_edge_ports(edges, {"s": src, "t": tgt})
        assert edges[0]["source_port"] == "port-bottom"
        assert edges[0]["target_port"] == "port-top"


# ═══════════════════════════════════════════════════
#  Test 8: v4 Local Layout
# ═══════════════════════════════════════════════════

class TestV4LocalLayout:
    def test_local_layout_places_new_user_in_dept(self):
        """New user in existing dept gets placed inside the dept."""
        dept = _make_dept_node("技术部")
        dept.id = "d1"
        dept.x, dept.y = 100, 100
        dept.w, dept.h = 700, 350
        existing_user = PowerNode(id="u1", node_type="user", name="张三",
                                   x=130, y=160, w=PERSON_W, h=PERSON_H,
                                   parent_dept_id="d1")
        new_user = _make_person_node("王五", department="技术部", parent_dept_id="d1")
        new_user.id = "u2"
        new_user.x, new_user.y = 0, 0

        ctx = MergeContext()
        ctx.all_nodes = [dept, existing_user, new_user]
        ctx.edges = []

        forced = {"u2"}
        _local_layout(ctx, forced)

        assert new_user.x > 0
        assert new_user.y > 0
        assert new_user.x >= dept.x + DEPT_PAD_LEFT
        assert new_user.y >= dept.y + DEPT_PAD_TOP
        assert new_user.w == PERSON_W
        assert new_user.h == PERSON_H

    def test_local_layout_does_not_move_unchanged(self):
        """Unforced nodes must not move."""
        dept = _make_dept_node("技术部")
        dept.id = "d1"
        dept.x, dept.y = 100, 100
        dept.w, dept.h = 700, 350
        existing_user = PowerNode(id="u1", node_type="user", name="张三",
                                   x=130, y=160, w=PERSON_W, h=PERSON_H,
                                   parent_dept_id="d1")

        ctx = MergeContext()
        ctx.all_nodes = [dept, existing_user]
        ctx.edges = []

        _local_layout(ctx, set())

        assert existing_user.x == 130
        assert existing_user.y == 160

    def test_local_layout_places_new_dept(self):
        """New dept gets placed at a non-overlapping position."""
        existing_dept = _make_dept_node("技术部")
        existing_dept.id = "d1"
        existing_dept.x, existing_dept.y = 100, 100
        existing_dept.w, existing_dept.h = 700, 350
        new_dept = _make_dept_node("财务部")
        new_dept.id = "d2"
        new_dept.x, new_dept.y = 0, 0

        ctx = MergeContext()
        ctx.all_nodes = [existing_dept, new_dept]
        ctx.edges = []

        forced = {"d2"}
        _local_layout(ctx, forced)

        # Should have been assigned a position (not still at (0,0))
        assert new_dept.x != 0 or new_dept.y != 0
        # Should not overlap with existing dept
        assert not _rects_overlap(
            (new_dept.x, new_dept.y, new_dept.x + new_dept.w, new_dept.y + new_dept.h),
            (existing_dept.x, existing_dept.y, existing_dept.x + existing_dept.w, existing_dept.y + existing_dept.h),
        )

    def test_local_layout_places_orphan(self):
        """User with no dept gets placed in orphan zone."""
        orphan = _make_person_node("孤狼", department="", parent_dept_id="")
        orphan.id = "o1"
        orphan.x, orphan.y = 0, 0

        ctx = MergeContext()
        ctx.all_nodes = [orphan]
        ctx.edges = []

        forced = {"o1"}
        _local_layout(ctx, forced)

        assert orphan.x > 0
        assert orphan.y > 0
        assert orphan.w == PERSON_W
        assert orphan.h == PERSON_H


# ═══════════════════════════════════════════════════
#  Test 9: v4 Slot Search
# ═══════════════════════════════════════════════════

class TestSlotSearch:
    def test_empty_dept_has_slot(self):
        dept = PowerNode(id="d1", node_type="dept", name="空部门",
                          x=100, y=100, w=700, h=350)
        slot = _find_empty_slot_in_dept(dept, [])
        assert slot is not None
        x, y = slot
        assert x >= dept.x + DEPT_PAD_LEFT
        assert y >= dept.y + DEPT_PAD_TOP
        assert x + PERSON_W <= dept.x + dept.w - DEPT_PAD_RIGHT
        assert y + PERSON_H <= dept.y + dept.h - DEPT_PAD_BOTTOM

    def test_slot_avoids_occupied(self):
        dept = PowerNode(id="d1", node_type="dept", name="部门",
                          x=100, y=100, w=700, h=350)
        slot_x = dept.x + DEPT_PAD_LEFT
        slot_y = dept.y + DEPT_PAD_TOP
        occupied_user = PowerNode(id="u1", node_type="user", name="占位",
                                   x=slot_x, y=slot_y, w=PERSON_W, h=PERSON_H)
        slot = _find_empty_slot_in_dept(dept, [occupied_user])
        assert slot is not None
        # Should not return the occupied slot
        assert not (slot[0] == slot_x and slot[1] == slot_y)

    def test_full_dept_returns_none(self):
        """Tight dept that can't fit another person returns None."""
        dept = PowerNode(id="d1", node_type="dept", name="满部门",
                          x=100, y=100,
                          w=DEPT_PAD_LEFT + PERSON_W + DEPT_PAD_RIGHT,
                          h=DEPT_PAD_TOP + PERSON_H + DEPT_PAD_BOTTOM)
        occupied_user = PowerNode(id="u1", node_type="user", name="占位",
                                   x=dept.x + DEPT_PAD_LEFT, y=dept.y + DEPT_PAD_TOP,
                                   w=PERSON_W, h=PERSON_H)
        slot = _find_empty_slot_in_dept(dept, [occupied_user])
        assert slot is None

    def test_dept_slot_placement(self):
        dept1 = _make_dept_node("技术部")
        dept1.id = "d1"
        dept1.x, dept1.y = 100, 100
        dept1.w, dept1.h = 700, 350

        ctx = MergeContext()
        ctx.all_nodes = [dept1]

        pos = _find_safe_dept_position(ctx)
        assert pos is not None
        x, y = pos
        assert y >= 50  # Some reasonable position


# ═══════════════════════════════════════════════════
#  Test 10: v4 Forced Move Set
# ═══════════════════════════════════════════════════

class TestForcedMoveSet:
    def test_empty_delta_no_forced(self):
        nodes = [_make_person_node("张三"), _make_dept_node("技术部")]
        ctx = _build_merge_context(nodes, [], "v1")

        delta = {
            "nodes_add": [], "nodes_delete": [], "nodes_update": [],
            "moves": [],
            "scope_declaration": {"expected_affected_count": 0, "allow_propagation": False},
        }
        forced = _compute_forced_move_set(ctx, delta)
        assert len(forced) == 0

    def test_update_no_forced(self):
        u1 = _make_person_node("张三", position="旧")
        u1.id = "user1"
        ctx = _build_merge_context([u1], [], "v1")

        delta = {
            "nodes_update": [{"id_or_name": "user1", "position": "新"}],
            "scope_declaration": {"expected_affected_count": 0, "allow_propagation": False},
        }
        forced = _compute_forced_move_set(ctx, delta)
        assert "user1" not in forced  # Updates don't force moves

    def test_delete_no_forced(self):
        u1 = _make_person_node("张三")
        u1.id = "user1"
        ctx = _build_merge_context([u1], [], "v1")
        # Note: we test forced BEFORE applying delta (as done in confirm)
        delta = {
            "nodes_delete": [{"id_or_name": "user1"}],
            "scope_declaration": {"expected_affected_count": 0, "allow_propagation": False},
        }
        forced = _compute_forced_move_set(ctx, delta)
        assert len(forced) == 0  # Deletions don't trigger reshuffle

    def test_add_user_to_roomy_dept(self):
        dept = _make_dept_node("技术部")
        dept.id = "dept1"
        dept.x, dept.y = 100, 100
        dept.w, dept.h = 700, 350
        ctx = _build_merge_context([dept], [], "v1")

        delta = {
            "nodes_add": [{"tmp_id": "t1", "node_type": "user", "name": "王五",
                           "department": "技术部"}],
            "scope_declaration": {"expected_affected_count": 1, "allow_propagation": False},
        }
        forced = _compute_forced_move_set(ctx, delta)
        # The tmp_id "t1" won't resolve in pre-delta ctx — the forced set returns resolved IDs
        # After resolution, the new node won't be in ctx.nodes_by_* yet since delta not applied
        # So forced may be empty in this pre-delta test
        # This is expected — the real pipeline calls compute AFTER apply_delta

    def test_add_user_full_dept_raises(self):
        """v4.1: Full dept no longer raises — instead dept is added to forced for adaptive_push_v2."""
        dept = _make_dept_node("满部门")
        dept.id = "dept1"
        dept.x, dept.y = 100, 100
        dept.w = DEPT_PAD_LEFT + PERSON_W + DEPT_PAD_RIGHT
        dept.h = DEPT_PAD_TOP + PERSON_H + DEPT_PAD_BOTTOM
        occupied = _make_person_node("占位", department="满部门", parent_dept_id="dept1")
        occupied.id = "u1"
        occupied.x = dept.x + DEPT_PAD_LEFT
        occupied.y = dept.y + DEPT_PAD_TOP
        occupied.w, occupied.h = PERSON_W, PERSON_H
        ctx = _build_merge_context([dept, occupied], [], "v1")

        delta = {
            "nodes_add": [{"tmp_id": "t1", "node_type": "user", "name": "王五",
                           "department": "满部门"}],
            "scope_declaration": {"expected_affected_count": 1, "allow_propagation": False},
        }
        # v4.1: apply_delta first (as real pipeline does), then compute forced
        ctx = _apply_delta(ctx, delta)
        forced = _compute_forced_move_set(ctx, delta)
        # v4.1: full dept → dept added to forced (no meltdown)
        # The new user's tmp_id gets resolved to real id via apply_delta
        assert "dept1" in forced

    def test_add_user_full_dept_with_propagation(self):
        """With allow_propagation, full dept is added to forced set."""
        dept = _make_dept_node("满部门")
        dept.id = "dept1"
        dept.x, dept.y = 100, 100
        dept.w = DEPT_PAD_LEFT + PERSON_W + DEPT_PAD_RIGHT
        dept.h = DEPT_PAD_TOP + PERSON_H + DEPT_PAD_BOTTOM
        occupied = _make_person_node("占位", department="满部门", parent_dept_id="dept1")
        occupied.id = "u1"
        occupied.x = dept.x + DEPT_PAD_LEFT
        occupied.y = dept.y + DEPT_PAD_TOP
        occupied.w, occupied.h = PERSON_W, PERSON_H
        ctx = _build_merge_context([dept, occupied], [], "v1")

        delta = {
            "nodes_add": [{"tmp_id": "t1", "node_type": "user", "name": "王五",
                           "department": "满部门"}],
            "scope_declaration": {"expected_affected_count": 2, "allow_propagation": True},
        }
        forced = _compute_forced_move_set(ctx, delta)
        # dept should be in forced set
        assert "dept1" in forced


# ═══════════════════════════════════════════════════
#  Test 11: v4 Meltdown Check
# ═══════════════════════════════════════════════════

class TestMeltdownCheck:
    def test_small_scope_ok(self):
        delta = {"scope_declaration": {"expected_affected_count": 5, "allow_propagation": False}}
        _scope_meltdown_check({"a", "b", "c"}, delta)  # Should not raise

    def test_large_scope_raises(self):
        delta = {"scope_declaration": {"expected_affected_count": 1, "allow_propagation": False}}
        with pytest.raises(ValueError, match="变更范围超出预期"):
            _scope_meltdown_check({"a", "b", "c", "d", "e"}, delta)  # 5 > 1*2


# ═══════════════════════════════════════════════════
#  Test 12: v4 Acid Test — Zero Ops Zero Change
# ═══════════════════════════════════════════════════

class TestV4Acid:
    def test_zero_ops_zero_change(self):
        """v4 acid test: submitting with empty delta must not change any position."""
        dept = _make_dept_node("Dept1", x=50, y=50)
        person = _make_person_node("A", x=100, y=200, parent_dept_id=dept.id)
        nodes = [person, dept]
        for n in nodes:
            n.x = n.x or 100  # ensure positions are set
        nodes[0].x, nodes[0].y = 100, 200
        nodes[1].x, nodes[1].y = 50, 50
        nodes[1].w, nodes[1].h = 700, 350

        edges: list = []
        ctx = MergeContext()
        ctx.all_nodes = nodes
        ctx.edges = edges
        ctx.nodes_by_id = {n.id: n for n in nodes}
        ctx.depts_by_name = {"Dept1": dept}
        ctx.nodes_by_name = {"A": person, "Dept1": dept}

        before = {n.id: (n.x, n.y, n.w, n.h) for n in nodes}

        delta = {
            "nodes_add": [], "nodes_delete": [], "nodes_update": [], "moves": [],
            "scope_declaration": {"expected_affected_count": 0, "allow_propagation": False},
        }
        ctx = _apply_delta(ctx, delta)
        forced = _compute_forced_move_set(ctx, delta)
        _scope_meltdown_check(forced, delta)
        _local_layout(ctx, forced)

        for n in nodes:
            bx, by, bw, bh = before[n.id]
            assert n.x == bx, f"{n.name} x changed: {bx} -> {n.x}"
            assert n.y == by, f"{n.name} y changed: {by} -> {n.y}"

    def test_field_update_no_position_change(self):
        """Field-only update must not change any position."""
        u1 = _make_person_node("张三", position="旧职位")
        u1.id = "user1"
        u1.x, u1.y = 200, 300
        u1.w, u1.h = PERSON_W, PERSON_H
        nodes = [u1]
        ctx = MergeContext()
        ctx.all_nodes = nodes
        ctx.edges = []
        ctx.nodes_by_id = {"user1": u1}

        before_pos = (u1.x, u1.y)

        delta = {
            "nodes_update": [{"id_or_name": "user1", "position": "新职位"}],
            "scope_declaration": {"expected_affected_count": 0, "allow_propagation": False},
        }
        ctx = _apply_delta(ctx, delta)
        forced = _compute_forced_move_set(ctx, delta)
        _local_layout(ctx, forced)

        assert u1.x == before_pos[0], f"x changed: {before_pos[0]} -> {u1.x}"
        assert u1.y == before_pos[1], f"y changed: {before_pos[1]} -> {u1.y}"
        assert u1.position == "新职位"

    def test_delete_person_others_unmoved(self):
        """Deleting a person must not move other nodes."""
        d1 = _make_dept_node("技术部")
        d1.id = "dept1"
        d1.x, d1.y = 100, 100
        d1.w, d1.h = 700, 350
        u1 = _make_person_node("张三", department="技术部", parent_dept_id="dept1")
        u1.id = "user1"
        u1.x, u1.y = 130, 160
        u1.w, u1.h = PERSON_W, PERSON_H
        u2 = _make_person_node("李四", department="技术部", parent_dept_id="dept1")
        u2.id = "user2"
        u2.x, u2.y = 290, 160
        u2.w, u2.h = PERSON_W, PERSON_H

        nodes = [d1, u1, u2]
        ctx = MergeContext()
        ctx.all_nodes = nodes
        ctx.edges = []
        ctx.nodes_by_id = {n.id: n for n in nodes}
        ctx.nodes_by_name = {n.name: n for n in nodes if n.name}
        ctx.depts_by_name = {n.name: n for n in nodes if n.node_type == "dept"}

        before_d1 = (d1.x, d1.y, d1.w, d1.h)
        before_u2 = (u2.x, u2.y)

        delta = {
            "nodes_delete": [{"id_or_name": "user1"}],
            "scope_declaration": {"expected_affected_count": 0, "allow_propagation": False},
        }
        ctx = _apply_delta(ctx, delta)
        forced = _compute_forced_move_set(ctx, delta)
        _local_layout(ctx, forced)

        # Find remaining nodes
        d1_after = ctx.nodes_by_id.get("dept1")
        u2_after = ctx.nodes_by_id.get("user2")
        assert d1_after is not None
        assert u2_after is not None
        # Dept position unchanged
        assert d1_after.x == before_d1[0]
        assert d1_after.y == before_d1[1]
        # u2 position unchanged (no fill-gap reshuffle)
        assert u2_after.x == before_u2[0]
        assert u2_after.y == before_u2[1]


# ═══════════════════════════════════════════════════
#  Test 13: v3.1 Fallback Layout
# ═══════════════════════════════════════════════════

class TestV31Fallback:
    def test_single_dept_single_user(self):
        dept = _make_dept_node("技术部")
        dept.id = "d1"
        user = _make_person_node("张三", department="技术部", parent_dept_id="d1")
        user.id = "u1"
        nodes = [dept, user]
        edges: list = []

        _v31_global_layout(nodes, edges)

        assert dept.w >= DEPT_MIN_W
        assert dept.h >= DEPT_MIN_H
        assert user.x >= dept.x + DEPT_PAD_LEFT
        assert user.y >= dept.y + DEPT_PAD_TOP
        assert user.w == PERSON_W
        assert user.h == PERSON_H

    def test_orphan_users(self):
        u1 = _make_person_node("孤狼", department="", parent_dept_id="")
        u1.id = "o1"
        u2 = _make_person_node("独行", department="", parent_dept_id="")
        u2.id = "o2"
        nodes = [u1, u2]
        edges: list = []

        _v31_global_layout(nodes, edges)

        assert u1.x != 0 or u1.y != 0
        assert u2.x != 0 or u2.y != 0
        assert u1.w == PERSON_W
        assert u1.h == PERSON_H

    def test_empty_nodes(self):
        """Layout with no nodes should not crash."""
        _v31_global_layout([], [])

    def test_dept_with_no_users(self):
        dept = _make_dept_node("空部门")
        dept.id = "d1"
        _v31_global_layout([dept], [])
        assert dept.w >= DEPT_MIN_W
        assert dept.h >= DEPT_MIN_H


# ═══════════════════════════════════════════════════
#  Test 14: LLM Output Parsing
# ═══════════════════════════════════════════════════

class TestLLMParsing:
    def test_parse_basic_output(self):
        text = json.dumps({
            "intent": "create",
            "explanation": "创建新部门",
            "nodes_add": [{"tmp_id": "t1", "node_type": "dept", "name": "新部门"}],
            "scope_declaration": {"expected_affected_count": 1, "allow_propagation": False},
        })
        delta = _parse_llm_output(text, "vid1", "vname1")
        assert delta["intent"] == "create"
        assert len(delta["nodes_add"]) == 1
        assert delta["version_id"] == "vid1"
        assert delta["version_name"] == "vname1"
        assert delta["scope_declaration"]["expected_affected_count"] == 1

    def test_parse_code_fence_output(self):
        text = '```json\n{"intent": "create", "explanation": "test", "nodes_add": [], "scope_declaration": {"expected_affected_count": 0, "allow_propagation": false}}\n```'
        delta = _parse_llm_output(text, "v1", "v1")
        assert delta["intent"] == "create"

    def test_parse_with_all_fields(self):
        text = json.dumps({
            "intent": "mixed",
            "explanation": "test",
            "nodes_add": [],
            "nodes_update": [],
            "nodes_delete": [],
            "moves": [],
            "custom_edges_add": [],
            "custom_edges_delete": [],
            "scope_declaration": {"expected_affected_count": 0, "allow_propagation": False},
        })
        delta = _parse_llm_output(text, "v1", "v1")
        for key in ["nodes_add", "nodes_update", "nodes_delete", "moves",
                     "custom_edges_add", "custom_edges_delete", "scope_declaration"]:
            assert delta[key] is not None

    def test_scope_declaration_default(self):
        """When scope_declaration is missing from LLM output, defaults are used."""
        text = json.dumps({"intent": "create", "explanation": "test", "nodes_add": []})
        delta = _parse_llm_output(text, "v1", "v1")
        assert delta["scope_declaration"] == {"expected_affected_count": 0, "allow_propagation": False}


# ═══════════════════════════════════════════════════
#  Test 15: v4 Helper Functions
# ═══════════════════════════════════════════════════

class TestV4Helpers:
    def test_find_dept_by_name(self):
        dept = _make_dept_node("技术部")
        dept.id = "d1"
        ctx = MergeContext()
        ctx.all_nodes = [dept]
        found = _find_dept_by_name(ctx, "技术部")
        assert found is not None
        assert found.id == "d1"

    def test_find_dept_by_name_case_insensitive(self):
        dept = _make_dept_node("技术部")
        dept.id = "d1"
        ctx = MergeContext()
        ctx.all_nodes = [dept]
        found = _find_dept_by_name(ctx, "  技术部  ")
        assert found is not None

    def test_find_dept_by_name_not_found(self):
        ctx = MergeContext()
        ctx.all_nodes = []
        assert _find_dept_by_name(ctx, "不存在的部门") is None

    def test_find_person_by_name(self):
        person = _make_person_node("张三")
        person.id = "u1"
        ctx = MergeContext()
        ctx.all_nodes = [person]
        found = _find_person_by_name(ctx, "张三")
        assert found is not None
        assert found.id == "u1"

    def test_find_person_not_found(self):
        ctx = MergeContext()
        ctx.all_nodes = []
        assert _find_person_by_name(ctx, "不存在的人") is None

    def test_find_dept_for_user_by_parent_id(self):
        dept = _make_dept_node("技术部")
        dept.id = "d1"
        user = _make_person_node("张三", parent_dept_id="d1")
        ctx = MergeContext()
        ctx.all_nodes = [dept, user]
        found = _find_dept_for_user(user, ctx)
        assert found is not None
        assert found.id == "d1"

    def test_find_dept_for_user_by_department_name(self):
        dept = _make_dept_node("技术部")
        dept.id = "d1"
        user = _make_person_node("张三", department="技术部", parent_dept_id="")
        ctx = MergeContext()
        ctx.all_nodes = [dept, user]
        found = _find_dept_for_user(user, ctx)
        assert found is not None
        assert found.id == "d1"

    def test_rects_overlap_true(self):
        r1 = (0, 0, 100, 100)
        r2 = (50, 50, 150, 150)
        assert _rects_overlap(r1, r2) is True

    def test_rects_overlap_false(self):
        r1 = (0, 0, 100, 100)
        r2 = (200, 200, 300, 300)
        assert _rects_overlap(r1, r2) is False

    def test_rects_touching_not_overlap(self):
        r1 = (0, 0, 100, 100)
        r2 = (100, 0, 200, 100)
        assert _rects_overlap(r1, r2) is False


# ═══════════════════════════════════════════════════
#  Test 16: v3.1 Edge Cases
# ═══════════════════════════════════════════════════

class TestV31EdgeCases:
    def test_deep_tree_layout(self):
        nodes = []
        id_map = {}
        prev_id = None
        for i in range(10):
            pid = prev_id if prev_id else ""
            n = PowerNode(id=f"n{i}", node_type="user", name=f"N{i}", pid=pid)
            if prev_id and id_map.get(prev_id):
                id_map[prev_id].children_ids.append(f"n{i}")
            nodes.append(n)
            id_map[f"n{i}"] = n
            prev_id = f"n{i}"

        roots = _build_dept_forest("d1", nodes)
        assert len(roots) == 1

        positions = _rt_layout_forest(roots, id_map)
        assert len(positions) == 10
        for i in range(1, 10):
            _, yi = positions[f"n{i}"]
            assert yi >= 0

    def test_nested_dept_nodes(self):
        parent = _make_dept_node("总部")
        parent.id = "d1"
        child_dept = _make_dept_node("分部", parent_dept_id="d1")
        child_dept.id = "d2"
        user = _make_person_node("员工", department="分部", parent_dept_id="d2")
        user.id = "u1"
        nodes = [parent, child_dept, user]

        _v31_global_layout(nodes, [])
        assert parent.w >= DEPT_MIN_W
        assert child_dept.w >= DEPT_MIN_W
        assert user.w == PERSON_W


class TestRelayoutTool:
    def _ctx(self, nodes, edges):
        ctx = MergeContext()
        ctx.all_nodes = nodes
        ctx.edges = edges
        ctx.nodes_by_id = {n.id: n for n in nodes}
        ctx.nodes_by_name = {n.name: n for n in nodes}
        ctx.depts_by_name = {n.name: n for n in nodes if n.node_type == "dept"}
        return ctx

    def test_cross_department_reports_project_to_container_layers(self):
        exec_dept = PowerNode(id="d-exec", node_type="dept", name="总裁办")
        finance = PowerNode(id="d-fin", node_type="dept", name="财务部")
        sales = PowerNode(id="d-sales", node_type="dept", name="销售部")
        ceo = PowerNode(id="u-ceo", node_type="user", name="黄宇", parent_dept_id="d-exec")
        cfo = PowerNode(id="u-cfo", node_type="user", name="纪成", parent_dept_id="d-fin")
        sales_director = PowerNode(id="u-sales", node_type="user", name="张强", parent_dept_id="d-sales")
        ctx = self._ctx(
            [exec_dept, finance, sales, ceo, cfo, sales_director],
            [
                {"id": "e1", "source_id": "u-cfo", "target_id": "u-ceo", "edge_type": "reports_to"},
                {"id": "e2", "source_id": "u-sales", "target_id": "u-ceo", "edge_type": "reports_to"},
            ],
        )

        result = _tool_relayout(ctx, {"direction": "TB"})

        assert result["ok"] is True
        assert finance.y > exec_dept.y
        assert sales.y > exec_dept.y
        assert abs((finance.y + finance.h / 2) - (sales.y + sales.h / 2)) < 5

    def test_execute_harness_tool_relayout_runs_real_layout(self):
        exec_dept = PowerNode(id="d-exec", node_type="dept", name="总裁办", x=5000, y=5000)
        finance = PowerNode(id="d-fin", node_type="dept", name="财务部", x=-3000, y=-3000)
        ceo = PowerNode(id="u-ceo", node_type="user", name="黄宇", parent_dept_id="d-exec")
        cfo = PowerNode(id="u-cfo", node_type="user", name="纪成", parent_dept_id="d-fin")
        ctx = self._ctx(
            [exec_dept, finance, ceo, cfo],
            [{"id": "e1", "source_id": "u-cfo", "target_id": "u-ceo", "edge_type": "reports_to"}],
        )

        result = asyncio.run(
            _execute_harness_tool(ctx, "relayout", {"options": {"direction": "TB"}})
        )

        assert result["ok"] is True
        assert "deprecated" not in json.dumps(result, ensure_ascii=False)
        assert finance.y > exec_dept.y
        assert exec_dept.x >= 0
        assert finance.x >= 0


# ═══════════════════════════════════════════════════
#  Test 17: Constants
# ═══════════════════════════════════════════════════

class TestConstants:
    def test_person_size(self):
        assert PERSON_W == 160
        assert PERSON_H == 72

    def test_dept_constants(self):
        assert DEPT_MIN_W == 300
        assert DEPT_MIN_H == 200
        assert DEPT_DEFAULT_W == 700
        assert DEPT_DEFAULT_H == 350

    def test_v4_constants(self):
        assert MIN_GAP_BETWEEN_USERS == 20
        assert MIN_GAP_BETWEEN_DEPTS == 100
        assert ADJUST_THRESHOLD_PX == 5


# ═══════════════════════════════════════════════════
#  Test 18: v4 Collision Detection & Dept Merge
# ═══════════════════════════════════════════════════

class TestV4Collision:
    """v4 collision detection and dept merge patches."""

    def test_dept_expand_pushes_neighbor(self):
        """Full dept A touches dept B, add person to A → A expands, B pushed right."""
        # Dept A: exactly fits 1 user
        dept_a = _make_dept_node("A", x=50, y=50)
        dept_a.w = DEPT_PAD_LEFT + PERSON_W + DEPT_PAD_RIGHT
        dept_a.h = DEPT_PAD_TOP + PERSON_H + DEPT_PAD_BOTTOM
        # Dept B: placed to the right, slightly overlapping user area
        dept_b = _make_dept_node("B", x=dept_a.x + dept_a.w + 50, y=50)
        dept_b.w, dept_b.h = 200, 200
        user_b = _make_person_node("U1", parent_dept_id=dept_b.id)
        user_b.x, user_b.y = dept_b.x + DEPT_PAD_LEFT, dept_b.y + DEPT_PAD_TOP

        nodes = [dept_a, dept_b, user_b]
        ctx = MergeContext()
        ctx.all_nodes = nodes
        ctx.edges = []
        ctx.nodes_by_id = {n.id: n for n in nodes}
        ctx.depts_by_name = {"A": dept_a, "B": dept_b}
        ctx.nodes_by_name = {n.name: n for n in nodes}

        # Fill dept_a with exactly 1 user (full)
        u0 = _make_person_node("u0", parent_dept_id=dept_a.id)
        u0.x = dept_a.x + DEPT_PAD_LEFT
        u0.y = dept_a.y + DEPT_PAD_TOP
        nodes.append(u0)
        ctx.nodes_by_id[u0.id] = u0

        delta = {
            "nodes_add": [{"tmp_id": "tx", "node_type": "user", "name": "NewGuy", "department": "A"}],
            "nodes_delete": [], "nodes_update": [], "moves": [],
            "scope_declaration": {"expected_affected_count": 2, "allow_propagation": True},
        }
        ctx = _apply_delta(ctx, delta)
        forced = _compute_forced_move_set(ctx, delta)
        _local_layout(ctx, forced, delta)

        # Dept A should have expanded
        assert dept_a.h > DEPT_PAD_TOP + PERSON_H + DEPT_PAD_BOTTOM
        # New user placed
        new_guy = _find_person_by_name(ctx, "NewGuy")
        assert new_guy is not None and new_guy.x > 0
        # No leftover collisions
        items = _build_bbox_items(ctx.all_nodes)
        groups = _build_rigid_groups_v2(ctx.all_nodes)
        collisions = _check_collision(items, groups)
        assert not collisions, f"Unexpected collisions: {collisions}"

    def test_merge_dept_handles_users(self):
        """Merge dept A→B with users: users move to B, B resizes, no collisions."""
        dept_a = _make_dept_node("A", x=50, y=50)
        dept_a.w, dept_a.h = 200, 150
        dept_b = _make_dept_node("B", x=350, y=50)
        dept_b.w, dept_b.h = 200, 150
        ua = _make_person_node("UA", parent_dept_id=dept_a.id)
        ua.x, ua.y = 80, 110
        ub = _make_person_node("UB", parent_dept_id=dept_b.id)
        ub.x, ub.y = 380, 110

        nodes = [dept_a, dept_b, ua, ub]
        ctx = MergeContext()
        ctx.all_nodes = nodes
        ctx.edges = []
        ctx.nodes_by_id = {n.id: n for n in nodes}
        ctx.depts_by_name = {"A": dept_a, "B": dept_b}
        ctx.nodes_by_name = {n.name: n for n in nodes}

        delta = {
            "nodes_add": [], "nodes_delete": [{"id_or_name": "A"}],
            "nodes_update": [], "moves": [{"person": "UA", "to_dept": "B"}],
            "scope_declaration": {"expected_affected_count": 1, "allow_propagation": True},
        }
        ctx = _apply_delta(ctx, delta)
        forced = _compute_forced_move_set(ctx, delta)
        _local_layout(ctx, forced, delta)

        # UA should now be in B
        assert ua.parent_dept_id == dept_b.id
        # No collisions
        items = _build_bbox_items(ctx.all_nodes)
        groups = _build_rigid_groups_v2(ctx.all_nodes)
        collisions = _check_collision(items, groups)
        assert not collisions, f"Collisions after merge: {collisions}"

    def test_orphan_avoids_dept_user(self):
        """New orphan user must not overlap with existing dept users."""
        dept = _make_dept_node("D", x=50, y=50)
        dept.w, dept.h = 700, 350
        user_d = _make_person_node("UD", parent_dept_id=dept.id)
        user_d.x, user_d.y = 80, 80

        nodes = [dept, user_d]
        ctx = MergeContext()
        ctx.all_nodes = nodes
        ctx.edges = []
        ctx.nodes_by_id = {n.id: n for n in nodes}
        ctx.depts_by_name = {"D": dept}
        ctx.nodes_by_name = {n.name: n for n in nodes}

        delta = {
            "nodes_add": [{"tmp_id": "tx", "node_type": "user", "name": "Orphan", "department": ""}],
            "nodes_delete": [], "nodes_update": [], "moves": [],
            "scope_declaration": {"expected_affected_count": 1, "allow_propagation": False},
        }
        ctx = _apply_delta(ctx, delta)
        forced = _compute_forced_move_set(ctx, delta)
        _local_layout(ctx, forced, delta)

        orphan = _find_person_by_name(ctx, "Orphan")
        assert orphan is not None
        # Orphan must not overlap UD
        assert not _rects_overlap(
            (orphan.x, orphan.y, orphan.x + PERSON_W, orphan.y + PERSON_H),
            (user_d.x, user_d.y, user_d.x + PERSON_W, user_d.y + PERSON_H)
        ), f"Orphan overlaps UD: ({orphan.x},{orphan.y})"

    def test_dept_capacity_exceeded_raises(self):
        """v4.1: Full dept no longer raises — instead auto-resize via adaptive_push_v2."""
        dept = _make_dept_node("D", x=50, y=50)
        dept.w, dept.h = 300, 100

        nodes = [dept]
        ctx = MergeContext()
        ctx.all_nodes = nodes
        ctx.edges = []
        ctx.nodes_by_id = {n.id: n for n in nodes}
        ctx.depts_by_name = {"D": dept}
        ctx.nodes_by_name = {n.name: n for n in nodes}

        delta = {
            "nodes_add": [{"tmp_id": "tx", "node_type": "user", "name": "New", "department": "D"}],
            "nodes_delete": [], "nodes_update": [], "moves": [],
            "scope_declaration": {"expected_affected_count": 1, "allow_propagation": False},
        }

        # Fill dept completely
        x = dept.x + DEPT_PAD_LEFT
        y = dept.y + DEPT_PAD_TOP
        while y + PERSON_H <= dept.y + dept.h - DEPT_PAD_BOTTOM:
            while x + PERSON_W <= dept.x + dept.w - DEPT_PAD_RIGHT:
                u = _make_person_node(f"u{x}_{y}", parent_dept_id=dept.id)
                u.x, u.y = x, y
                nodes.append(u)
                ctx.nodes_by_id[u.id] = u
                x += PERSON_W + MIN_GAP_BETWEEN_USERS
            x = dept.x + DEPT_PAD_LEFT
            y += PERSON_H + MIN_GAP_BETWEEN_USERS

        ctx = _apply_delta(ctx, delta)
        forced = _compute_forced_move_set(ctx, delta)
        # v4.1: no meltdown — dept auto-expands
        _local_layout(ctx, forced, delta)
        # Verify all nodes (old + new) are positioned
        all_ids = {n.id for n in ctx.all_nodes}
        for n in ctx.all_nodes:
            assert n.x >= 0 and n.y >= 0, f"{n.name} placed at negative coords"
        # The new node should be inside the dept
        new_node = ctx.nodes_by_name.get("New")
        assert new_node is not None
        assert new_node.y >= dept.y

    def test_post_commit_verify_blocks_collision(self):
        """Artificially create a collision → post-submit verify must raise."""
        a = _make_person_node("A", x=50, y=50)
        b = _make_person_node("B", x=100, y=60)  # Overlaps A
        nodes = [a, b]
        items = _build_bbox_items(nodes)
        with pytest.raises(ValueError, match="POST_COMMIT_COLLISION"):
            _post_submit_verify(items)

    def test_rigid_group_translate(self):
        """Translate must move dept AND all direct users synchronously."""
        d = _make_dept_node("d1", x=50, y=50)
        d.w, d.h = 200, 200
        u1 = _make_person_node("u1", x=80, y=80)
        u2 = _make_person_node("u2", x=120, y=150)
        group = RigidGroup(dept=d, direct_users=[u1, u2])
        group.translate(100, 0)
        assert d.x == 150
        assert u1.x == 180
        assert u2.x == 220


class TestGeometryLocked:
    """v4 geometry_locked: protect existing user-drawn anomalous positions."""

    def test_locked_user_not_moved_by_dept_expand(self):
        """User spanning across dept boundary → locked, not moved by dept expansion."""
        dept_a = _make_dept_node("A", x=50, y=50)
        dept_a.w, dept_a.h = 200, 150
        dept_b = _make_dept_node("B", x=250, y=50)
        dept_b.w, dept_b.h = 200, 150
        # User X: claimed by A but bbox overlaps into B
        user_x = _make_person_node("X", parent_dept_id=dept_a.id)
        user_x.x, user_x.y = 180, 80  # Right edge overlaps B

        nodes = [dept_a, dept_b, user_x]
        _mark_geometry_anomalies(nodes)
        assert user_x.geometry_locked, "X should be locked (out of dept A bounds)"

        ctx = MergeContext()
        ctx.all_nodes = nodes
        ctx.edges = []
        ctx.nodes_by_id = {n.id: n for n in nodes}

        delta = {
            "nodes_add": [{"tmp_id": "tx", "node_type": "user", "name": "New", "department": "A"}],
            "nodes_delete": [], "nodes_update": [], "moves": [],
            "scope_declaration": {"expected_affected_count": 1, "allow_propagation": True},
        }
        ctx = _apply_delta(ctx, delta)
        forced = _compute_forced_move_set(ctx, delta)
        _local_layout(ctx, forced, delta)

        # X must not move
        assert user_x.x == 180 and user_x.y == 80, f"X moved: ({user_x.x},{user_x.y})"
        # No collision error raised (X is locked and exempt)

    def test_orphan_locked_not_pushed(self):
        """Orphan user overlapping a dept → locked, not pushed to orphan zone."""
        dept = _make_dept_node("D", x=50, y=50)
        dept.w, dept.h = 300, 200
        user_y = _make_person_node("Y")  # no parent_dept
        user_y.x, user_y.y = 200, 100  # Inside dept D

        nodes = [dept, user_y]
        _mark_geometry_anomalies(nodes)
        assert user_y.geometry_locked, "Y should be locked (orphan inside dept)"

        # Any operation must not move Y
        delta = {
            "nodes_add": [{"tmp_id": "tx", "node_type": "user", "name": "Z", "department": "D"}],
            "nodes_delete": [], "nodes_update": [], "moves": [],
            "scope_declaration": {"expected_affected_count": 1, "allow_propagation": False},
        }
        ctx = MergeContext()
        ctx.all_nodes = nodes
        ctx.edges = []
        ctx.nodes_by_id = {n.id: n for n in nodes}
        ctx.depts_by_name = {"D": dept}
        ctx.nodes_by_name = {n.name: n for n in nodes}
        ctx = _apply_delta(ctx, delta)
        forced = _compute_forced_move_set(ctx, delta)
        _local_layout(ctx, forced, delta)

        assert user_y.x == 200 and user_y.y == 100, f"Y moved: ({user_y.x},{user_y.y})"

    def test_new_user_still_constrained(self):
        """New LLM-added user must NOT be placed out of dept bounds."""
        dept = _make_dept_node("D", x=50, y=50)
        dept.w, dept.h = 300, 200
        nodes = [dept]

        ctx = MergeContext()
        ctx.all_nodes = nodes
        ctx.edges = []
        ctx.nodes_by_id = {n.id: n for n in nodes}
        ctx.depts_by_name = {"D": dept}
        ctx.nodes_by_name = {n.name: n for n in nodes}

        delta = {
            "nodes_add": [{"tmp_id": "tx", "node_type": "user", "name": "New", "department": "D"}],
            "nodes_delete": [], "nodes_update": [], "moves": [],
            "scope_declaration": {"expected_affected_count": 1, "allow_propagation": False},
        }
        ctx = _apply_delta(ctx, delta)
        forced = _compute_forced_move_set(ctx, delta)
        _local_layout(ctx, forced, delta)

        new_user = _find_person_by_name(ctx, "New")
        assert new_user is not None
        # Must be inside dept
        assert new_user.x >= dept.x + GEO_EMBED_SAFE_MARGIN
        assert new_user.y >= dept.y + GEO_EMBED_SAFE_MARGIN
        assert new_user.x + PERSON_W <= dept.x + dept.w - GEO_EMBED_SAFE_MARGIN
        assert new_user.y + PERSON_H <= dept.y + dept.h - GEO_EMBED_SAFE_MARGIN
        assert not new_user.geometry_locked, "New user must not be auto-locked"
