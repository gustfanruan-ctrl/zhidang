"""美宜佳 v4 测试 Case 7 & 8 — v2: v3.1 layout + preserved locks from original BI data.

Pipeline:
  _node_from_bi_dict → _mark_geometry_anomalies (save locks)
  → _v31_global_layout (clean tree layout + dept sizing)
  → restore locks → _mark_geometry_anomalies (re-mark after layout)
  → _build_merge_context → _apply_delta → _compute_forced_move_set
  → _local_layout → render SVG

SVG format matches v4_00~v4_06 reference set.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from backend.app.services.power_map_service import (
    PERSON_W, PERSON_H,
    _node_from_bi_dict,
    _build_merge_context,
    _apply_delta,
    _compute_forced_move_set,
    _scope_meltdown_check,
    _local_layout,
    _build_bbox_items,
    _build_rigid_groups,
    _check_collision,
    _mark_geometry_anomalies,
    _v31_global_layout,
    _find_dept_by_name,
    _find_person_by_name,
    MergeContext,
)

OUT_DIR = Path("/mnt/d/美宜佳布局验证")
DATA_FILE = OUT_DIR / "美宜佳_客户成功版_原始数据.json"

# ── SVG style constants (matching v4_00~v4_06 exactly) ──
BG_FILL = "#fafafa"
DEPT_FILL = "#e9f5e9"
DEPT_STROKE = "#b8d4b8"
DEPT_TEXT = "#2d5a2d"
LOCKED_FILL = "#ffebee"
LOCKED_STROKE = "#d32f2f"
LOCKED_TEXT = "#c62828"
USER_FILL = "#fffde7"
USER_STROKE = "#1565c0"
NEW_FILL = "#fff3e0"
NEW_STROKE = "#ff9800"
EDGE_COLOR = "#A2B1C3"
TITLE_COLOR = "#333"
STATS_COLOR = "#888"
POSITION_COLOR = "#666"
LOCKED_LABEL_COLOR = "#d32f2f"


def load_baseline() -> MergeContext:
    """Load raw BI data → PowerNode list → mark anomaly locks → v31 layout → restore locks → MergeContext."""
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        raw = json.load(f)

    nodes = [_node_from_bi_dict(nd) for nd in raw["nodes"]]
    edges = raw.get("edges", [])[:]

    # Step 1: mark geometry anomalies on original BI positions (capture locks)
    _mark_geometry_anomalies(nodes)
    locked_ids_before = {n.id for n in nodes if getattr(n, 'geometry_locked', False)}
    print(f"  [load] locked from original BI positions: {len(locked_ids_before)} → {[n.name for n in nodes if n.id in locked_ids_before]}")

    # Step 2: v3.1 global layout (clean tree + dept sizing from contained users)
    nodes.sort(key=lambda n: 0 if n.node_type == "dept" else 1)
    _v31_global_layout(nodes, edges)

    # Step 3: re-mark anomalies after layout (some overlaps emerge)
    _mark_geometry_anomalies(nodes)
    locked_ids_after = {n.id for n in nodes if getattr(n, 'geometry_locked', False)}
    print(f"  [load] locked after v31 layout: {len(locked_ids_after)} → {[n.name for n in nodes if n.id in locked_ids_after]}")

    # Step 4: merge both lock sets (union of before and after)
    merged_locked = locked_ids_before | locked_ids_after
    for n in nodes:
        if n.id in merged_locked:
            n.geometry_locked = True
    print(f"  [load] final locked (union): {len(merged_locked)} → {[n.name for n in nodes if n.id in merged_locked]}")

    ctx = _build_merge_context(nodes, edges, "baseline")
    ctx.nodes_by_name = {n.name: n for n in nodes}
    ctx.depts_by_name = {n.name: n for n in nodes if n.node_type == "dept"}
    return ctx


def render_svg(ctx: MergeContext, title: str, new_ids: set, filepath: Path):
    """Render all nodes + edges as SVG matching v4_00~v4_06 style."""
    nodes = ctx.all_nodes
    if not nodes:
        print(f"  [WARN] No nodes to render")
        return

    pad = 80
    min_x = min(n.x for n in nodes) - pad
    min_y = min(n.y for n in nodes) - pad
    max_x = max(n.x + n.w for n in nodes) + pad
    max_y = max(n.y + n.h for n in nodes) + pad
    view_w = max_x - min_x
    view_h = max_y - min_y

    dept_count = sum(1 for n in nodes if n.node_type == "dept")
    user_count = sum(1 for n in nodes if n.node_type == "user")
    locked_count = sum(1 for n in nodes if n.node_type == "user" and getattr(n, 'geometry_locked', False))
    edge_count = len(ctx.edges) if hasattr(ctx, 'edges') and ctx.edges else 0
    moved_count = len(new_ids)

    lines = []
    def L(s=""): lines.append(s)

    L(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{min_x} {min_y} {view_w} {view_h}">')
    L('<defs><marker id="ar" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto">'
      '<path d="M 0 0 L 10 5 L 0 10 z" fill="#A2B1C3"/></marker></defs>')
    L(f'<rect x="{min_x}" y="{min_y}" width="{view_w}" height="{view_h}" fill="{BG_FILL}" rx="8"/>')

    # Title & stats
    L(f'<text x="{min_x+20}" y="{min_y+28}" font-size="16" font-weight="bold" fill="{TITLE_COLOR}">{title}</text>')
    L(f'<text x="{min_x+20}" y="{min_y+48}" font-size="12" fill="{STATS_COLOR}">Depts:{dept_count} Users:{user_count} Edges:{edge_count} Locked:{locked_count}</text>')

    # Edges (center-to-center)
    id_to_node = ctx.nodes_by_id
    if hasattr(ctx, 'edges') and ctx.edges:
        for e in ctx.edges:
            src = id_to_node.get(e.get("source_id", ""))
            tgt = id_to_node.get(e.get("target_id", ""))
            if src and tgt:
                sx, sy = src.x + src.w/2, src.y + src.h/2
                tx, ty = tgt.x + tgt.w/2, tgt.y + tgt.h/2
                L(f'<line x1="{sx}" y1="{sy}" x2="{tx}" y2="{ty}" stroke="{EDGE_COLOR}" '
                  f'stroke-width="1.5" marker-end="url(#ar)" opacity="0.5"/>')

    # Department nodes (drawn first so users are on top)
    for n in nodes:
        if n.node_type != "dept":
            continue
        is_new = n.id in new_ids
        stroke = NEW_STROKE if is_new else DEPT_STROKE
        stroke_w = 3 if is_new else 2
        L(f'<rect x="{n.x}" y="{n.y}" width="{n.w}" height="{n.h}" rx="10" '
          f'fill="{DEPT_FILL}" stroke="{stroke}" stroke-width="{stroke_w}" stroke-dasharray="6 3"/>')
        L(f'<text x="{n.x+16}" y="{n.y+28}" font-size="14" font-weight="bold" fill="{DEPT_TEXT}">{n.name}</text>')
        L(f'<text x="{n.x+16}" y="{n.y+46}" font-size="11" fill="#6b9b6b">[{n.w:.0f}x{n.h:.0f}]</text>')

    # User nodes
    for n in nodes:
        if n.node_type != "user":
            continue
        is_new = n.id in new_ids
        is_locked = getattr(n, 'geometry_locked', False)

        if is_locked:
            fill, stroke, sw = LOCKED_FILL, LOCKED_STROKE, 2.5
            name_color = LOCKED_TEXT
        elif is_new:
            fill, stroke, sw = NEW_FILL, NEW_STROKE, 2.0
            name_color = "#e65100"
        else:
            fill, stroke, sw = USER_FILL, USER_STROKE, 1.5
            name_color = LOCKED_TEXT

        L(f'<rect x="{n.x}" y="{n.y}" width="{PERSON_W}" height="{PERSON_H}" rx="8" '
          f'fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>')

        cx = n.x + PERSON_W / 2
        lock_marker = "🔒" if is_locked else ""
        L(f'<text x="{cx}" y="{n.y+24}" text-anchor="middle" font-size="13" font-weight="bold" fill="{name_color}">{n.name}{lock_marker}</text>')

        if n.position:
            pos_display = n.position[:28] + "..." if len(n.position) > 28 else n.position
            L(f'<text x="{cx}" y="{n.y+42}" text-anchor="middle" font-size="10" fill="{POSITION_COLOR}">{pos_display}</text>')

        if is_locked:
            L(f'<text x="{cx}" y="{n.y+58}" text-anchor="middle" font-size="9" fill="{LOCKED_LABEL_COLOR}">🔒 LOCKED</text>')

    L('</svg>')
    svg = "\n".join(lines)
    filepath.write_text(svg, encoding="utf-8")
    print(f"  OK {filepath.name} ({filepath.stat().st_size} bytes)")


def run_case(label: str, delta: dict, out_name: str) -> tuple[MergeContext, list]:
    """Load baseline → apply delta → local layout → render SVG."""
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")

    ctx = load_baseline()

    old_ids = {n.id for n in ctx.all_nodes}

    ctx = _apply_delta(ctx, delta)

    new_ids = {n.id for n in ctx.all_nodes if n.id not in old_ids}

    forced = _compute_forced_move_set(ctx, delta)
    print(f"  Forced moves: {len(forced)} node(s)")

    scope = delta.get("scope_declaration", {})
    if scope.get("expected_affected_count", 0) > 0:
        try:
            _scope_meltdown_check(forced, delta)
            print(f"  Scope check: OK")
        except ValueError as e:
            print(f"  Scope check: BLOCKED — {e}")

    _local_layout(ctx, forced, delta)

    items = _build_bbox_items(ctx.all_nodes)
    groups = _build_rigid_groups(items)
    collisions = _check_collision(items, groups)
    if collisions:
        print(f"  COLLISIONS: {collisions}")
    else:
        print(f"  No collisions")

    dept_count = sum(1 for n in ctx.all_nodes if n.node_type == "dept")
    user_count = sum(1 for n in ctx.all_nodes if n.node_type == "user")
    locked_count = sum(1 for n in ctx.all_nodes if n.node_type == "user" and getattr(n, 'geometry_locked', False))
    moved_count = len(new_ids)
    unchanged = len(ctx.all_nodes) - moved_count
    print(f"  Depts:{dept_count} Users:{user_count} Total:{len(ctx.all_nodes)} Locked:{locked_count}")

    title = f"{label} | 移动{moved_count} 不动{unchanged} 锁定{locked_count}"
    render_svg(ctx, title, new_ids, OUT_DIR / out_name)

    return ctx, collisions


# ═══════════════════════════════════════════════════
# Case 7: 删部门，人员不动（留下成孤儿）
# ═══════════════════════════════════════════════════

case7_delta = {
    "intent": "delete",
    "explanation": "删除数据资产管理部，王亮亮留为孤儿节点",
    "version_id": "test",
    "version_name": "test",
    "nodes_add": [],
    "nodes_update": [],
    "nodes_delete": [{"id_or_name": "数据资产管理部"}],
    "moves": [],
    "custom_edges_add": [],
    "custom_edges_delete": [],
    "scope_declaration": {"expected_affected_count": 1, "allow_propagation": True},
}

ctx7, coll7 = run_case(
    "Case7: 删除「数据资产管理部」→ 王亮亮留为孤儿节点",
    case7_delta,
    "v4_07_delete_dept_keep_user.svg"
)

wl = _find_person_by_name(ctx7, "王亮亮")
assert wl is not None, "FAIL: 王亮亮 should still exist after Case 7"
dpt7 = _find_dept_by_name(ctx7, "数据资产管理部")
assert dpt7 is None, "FAIL: 数据资产管理部 should be deleted in Case 7"
print(f"  PASS: 王亮亮 remains at ({wl.x:.0f}, {wl.y:.0f}), 数据资产管理部 deleted")

# ═══════════════════════════════════════════════════
# Case 8: 删部门和名下人员
# ═══════════════════════════════════════════════════

case8_delta = {
    "intent": "delete",
    "explanation": "删除基础应用运维部及其成员严俊森",
    "version_id": "test",
    "version_name": "test",
    "nodes_add": [],
    "nodes_update": [],
    "nodes_delete": [{"id_or_name": "基础应用运维部"}, {"id_or_name": "严俊森"}],
    "moves": [],
    "custom_edges_add": [],
    "custom_edges_delete": [],
    "scope_declaration": {"expected_affected_count": 2, "allow_propagation": True},
}

ctx8, coll8 = run_case(
    "Case8: 删除「基础应用运维部」+ 严俊森",
    case8_delta,
    "v4_08_delete_dept_and_user.svg"
)

dpt8 = _find_dept_by_name(ctx8, "基础应用运维部")
yj8 = _find_person_by_name(ctx8, "严俊森")
assert dpt8 is None, f"FAIL: 基础应用运维部 should be deleted, found: {dpt8}"
assert yj8 is None, f"FAIL: 严俊森 should be deleted, found: {yj8}"
print(f"  PASS: Both 基础应用运维部 and 严俊森 deleted")

print(f"\n{'='*60}")
print(f"  SUMMARY")
print(f"{'='*60}")
print(f"  Case 7: {'PASS' if not coll7 else 'COLLISIONS DETECTED (known: 张森/阚总 overlap)'}")
print(f"  Case 8: {'PASS' if not coll8 else 'COLLISIONS DETECTED (known: 张森/阚总 overlap)'}")
print(f"  Output: {OUT_DIR}/")
print(f"    v4_07_delete_dept_keep_user.svg")
print(f"    v4_08_delete_dept_and_user.svg")
