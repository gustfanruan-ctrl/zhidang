from __future__ import annotations

import base64
import functools
import json
import logging
import math
import os
import re
import time
import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy.orm import Session

from ..crypto_utils import decrypt_secret
from ..models import SystemConfig
from .cas_auth import CasAuthError, cas_auth_service
from .openai_compatible_agent_client import OpenAICompatibleAgentClient

try:
    from backend.tests.check_geometry import check_geometry_from_nodes  # type: ignore
except ImportError:
    try:
        from tests.check_geometry import check_geometry_from_nodes  # type: ignore
    except ImportError:
        check_geometry_from_nodes = None  # type: ignore

logger = logging.getLogger("zhidang.power_map")

# ═══════════════════════════════════════════════════════════
#  Layout Constants (v4 — minimum intrusion)
# ═══════════════════════════════════════════════════════════

PERSON_W = 160
PERSON_H = 72
DEPT_MIN_W = 300
DEPT_MIN_H = 200
DEPT_DEFAULT_W = 700
DEPT_DEFAULT_H = 350

# Safety margins (only for new node placement)
MIN_GAP_BETWEEN_USERS = 20       # intra-dept user spacing
MIN_GAP_BETWEEN_DEPTS = 100      # inter-dept spacing
GEO_EMBED_SAFE_MARGIN = 10       # user bbox distance from dept inner wall
DEPT_PAD_LEFT = 30
DEPT_PAD_RIGHT = 30
DEPT_PAD_TOP = 60
DEPT_PAD_BOTTOM = 30

# Slot search
SLOT_SEARCH_STEP = 10            # scan step size for empty slot detection
FALLBACK_NEW_DEPT_OFFSET = 200   # fallback position offset for new dept

# Change detection
ADJUST_THRESHOLD_PX = 5          # unchanged threshold

# v4.1 ripple warning thresholds
RIPPLE_WARN_THRESHOLD = {
    "moved_groups_count": 3,
    "max_displacement_px": 500,
    "ripple_radius_depts": 5,
    "indirectly_moved_users": 15,
}

_TYPE_TO_BI = {"user": "person", "dept": "department"}
_TYPE_FROM_BI = {"person": "user", "department": "dept"}

# ═══════════════════════════════════════════════════════════
#  Session store (in-memory, TTL'd)
# ═══════════════════════════════════════════════════════════
# session_id → MergeContext.  Sessions accumulate user-driven changes in
# memory until the user explicitly calls save_state (which then writes
# back to BI and clears the session).  Sessions expire after 30 minutes
# of inactivity.
_SESSION_STORE: "dict[str, MergeContext]" = {}
_SESSION_LAST_ACCESS: dict[str, float] = {}
_SESSION_TTL = 1800  # seconds


def _cleanup_expired_sessions() -> None:
    now = time.time()
    expired = [
        sid for sid, ts in _SESSION_LAST_ACCESS.items()
        if now - ts > _SESSION_TTL
    ]
    for sid in expired:
        _SESSION_STORE.pop(sid, None)
        _SESSION_LAST_ACCESS.pop(sid, None)


def _touch_session(session_id: str) -> None:
    _SESSION_LAST_ACCESS[session_id] = time.time()


def _new_session_id() -> str:
    return uuid.uuid4().hex


def _get_session(session_id: str) -> "MergeContext | None":
    if not session_id:
        return None
    _cleanup_expired_sessions()
    ctx = _SESSION_STORE.get(session_id)
    if ctx is not None:
        _touch_session(session_id)
    return ctx


def _store_session(session_id: str, ctx: "MergeContext") -> None:
    _SESSION_STORE[session_id] = ctx
    _touch_session(session_id)


def _drop_session(session_id: str) -> None:
    _SESSION_STORE.pop(session_id, None)
    _SESSION_LAST_ACCESS.pop(session_id, None)

# v3.1 legacy constants (still used by _v31_global_layout fallback)
_SIBLING_GAP_H = 30
_SUBTREE_GAP_H = 50
_LEVEL_GAP_V = 40
_DEPT_GAP_H = 200
_DEPT_GAP_V = 200
_CANVAS_MAX_X = 2800
_CANVAS_ORIGIN_X = 0
_CANVAS_ORIGIN_Y = 0
_ORPHAN_GRID_GAP = 20
_PORT_THRESHOLD = 50

_DEFAULT_NODE_FIELDS: dict[str, Any] = {
    "information": "",
    "school": "",
    "hobby": "",
    "tagA": "",
    "tagB": "",
    "tagC": "",
    "tagC_arr": "",
    "tagD": "",
    "tagD_label": "",
    "tagD_level": "",
    "tagD_other_name": "",
    "tagD_other_abbr": "",
    "if_highLight": "1",
    "node_manager": "0",
    "node_reach": "0",
    "attitude_arr": [],
    "pid": "",
    "cont_id": "",
    "jdy_id": "",
    "par_id": "",
    "node_background": "",
    "node_border_color": "",
    "node_expect": "",
}


# ═══════════════════════════════════════════════════════════
#  Internal Node Representation
# ═══════════════════════════════════════════════════════════

@dataclass
class PowerNode:
    """Internal node representation for layout algorithm."""
    id: str
    node_type: str  # "user" or "dept"
    name: str
    # Structural sub-type for the new structure-first toolset.
    # For node_type="dept": one of "system" | "org" | "department" | ""
    # For node_type="user": always "" (persons need no further subtype)
    subtype: str = ""
    # Person role tag for the structure-first toolset: "A" | "D" | "I" | "S"
    # ("Accountable" / "Driver" / "Informed" / "Support"). Empty for non-persons.
    role: str = ""
    pid: str = ""                       # reports-to parent node id
    department: str = ""                # dept name (user nodes)
    parent_dept_id: str = ""            # par_id — owning dept node id
    position: str = ""
    phone: str = ""
    cont_id: str = ""
    tagA: str = ""
    tagB: str = ""
    tagC_arr: str = ""
    tagD_label: str = ""
    tagD_level: str = ""
    tagD_other_name: str = ""
    tagD_other_abbr: str = ""
    information: str = ""
    school: str = ""
    hobby: str = ""
    if_highLight: str = "1"
    node_manager: str = "0"
    node_reach: str = "0"
    attitude_arr: list = field(default_factory=list)
    jdy_id: str = ""
    background: str = ""
    node_border_color: str = ""
    node_expect: str = ""
    # Geometry
    x: float = 0
    y: float = 0
    w: float = 0
    h: float = 0
    # Layout state
    depth: int = 0
    children_ids: list[str] = field(default_factory=list)
    geometry_locked: bool = False  # user-drawn cross-boundary node — permanent freeze
    is_cross_dept: bool = False       # user spans ≥2 depts (≥30% overlap each)
    parent_id: str = ""                 # resolved layout parent (may differ from pid)
    # BI writeback isolation: stores original BI par_id, while parent_dept_id
    # may be overwritten in memory by _resolve_parent_dept.
    _parent_dept_original: str = ""
    # Temporary
    _tmp_id: str = ""


@dataclass
class BBoxItem:
    """Unified bounding box for collision detection."""
    id: str
    item_type: str  # "user" | "dept"
    x: float
    y: float
    w: float
    h: float
    parent_dept_id: str | None = None  # user only
    children_ids: list[str] = field(default_factory=list)  # dept only


@dataclass
class RigidGroup:
    """递归嵌套的刚性部门组。顶级组作平级推挤单位，嵌套子部门在父内部参与碰撞检测。"""
    dept: PowerNode
    direct_users: list[PowerNode] = field(default_factory=list)   # 直属 user
    nested_children: list["RigidGroup"] = field(default_factory=list)  # 嵌套子部门

    def bbox(self) -> tuple[float, float, float, float]:
        """整组外接矩形 = dept bbox 与所有递归内容的并集"""
        x1, y1 = self.dept.x, self.dept.y
        x2 = self.dept.x + self.dept.w
        y2 = self.dept.y + self.dept.h
        for u in self.direct_users:
            x1 = min(x1, u.x)
            y1 = min(y1, u.y)
            x2 = max(x2, u.x + PERSON_W)
            y2 = max(y2, u.y + PERSON_H)
        for child in self.nested_children:
            cx1, cy1, cx2, cy2 = child.bbox()
            x1 = min(x1, cx1)
            y1 = min(y1, cy1)
            x2 = max(x2, cx2)
            y2 = max(y2, cy2)
        return (x1, y1, x2, y2)

    def contains(self, inner_bbox: tuple[float, float, float, float], with_padding: bool = True) -> bool:
        """检查 inner_bbox 是否完全落在本组的 dept bbox 内"""
        margin = GEO_EMBED_SAFE_MARGIN if with_padding else 0
        ix1, iy1, ix2, iy2 = inner_bbox
        dx1 = self.dept.x - margin
        dy1 = self.dept.y - margin
        dx2 = self.dept.x + self.dept.w + margin
        dy2 = self.dept.y + self.dept.h + margin
        return ix1 >= dx1 and iy1 >= dy1 and ix2 <= dx2 and iy2 <= dy2

    def translate(self, dx: float, dy: float) -> None:
        """整组平移：dept + 所有直属 user + 所有嵌套子部门递归平移"""
        self.dept.x += dx
        self.dept.y += dy
        for u in self.direct_users:
            u.x += dx
            u.y += dy
        for child in self.nested_children:
            child.translate(dx, dy)

    def expand(self, target_bbox: tuple[float, float, float, float]) -> None:
        """部门扩展：扩展 dept 尺寸以包含 target_bbox，内部节点位置不变"""
        _, _, tx2, ty2 = target_bbox
        new_right = max(self.dept.x + self.dept.w, tx2 + DEPT_PAD_RIGHT)
        new_bottom = max(self.dept.y + self.dept.h, ty2 + DEPT_PAD_BOTTOM)
        self.dept.w = new_right - self.dept.x
        self.dept.h = new_bottom - self.dept.y


@dataclass
class ExpansionRecord:
    dept_id: str
    old_w: float
    old_h: float
    new_w: float
    new_h: float
    reason: str


@dataclass
class TranslationRecord:
    dept_id: str
    dx: float
    dy: float
    affected_user_ids: list[str] = field(default_factory=list)
    reason: str = ""


class RippleReport:
    """涟漪规模报告 — 记录 adaptive_push_v2 的所有副作用"""

    def __init__(self):
        self.expanded_depts: list[ExpansionRecord] = []
        self.moved_groups: list[TranslationRecord] = []
        self.max_displacement_px: float = 0.0
        self.ripple_radius_depts: int = 0
        self.indirectly_moved_users: int = 0
        self.ripple_chain: list[dict] = []

    def add_expansion(self, dept_id: str, old_w: float, old_h: float, new_w: float, new_h: float, reason: str):
        self.expanded_depts.append(ExpansionRecord(dept_id, old_w, old_h, new_w, new_h, reason))
        self.ripple_chain.append({
            "action": "expand", "dept_id": dept_id,
            "detail": {"old": [old_w, old_h], "new": [new_w, new_h]},
            "reason": reason,
        })

    def add_translation(self, dept_id: str, dx: float, dy: float, affected_user_ids: list[str], reason: str):
        self.moved_groups.append(TranslationRecord(dept_id, dx, dy, affected_user_ids, reason))
        self.max_displacement_px = max(self.max_displacement_px, abs(dx) + abs(dy))
        self.indirectly_moved_users += len(affected_user_ids)
        self.ripple_chain.append({
            "action": "translate", "dept_id": dept_id,
            "detail": {"dx": dx, "dy": dy},
            "reason": reason,
        })

    def finalize(self, all_groups: list["RigidGroup"]):
        self.ripple_radius_depts = len(
            set(r.dept_id for r in self.expanded_depts) | set(r.dept_id for r in self.moved_groups)
        )

    def to_dict(self) -> dict:
        return {
            "expanded_depts": [
                {"dept_id": r.dept_id, "old_size": [r.old_w, r.old_h], "new_size": [r.new_w, r.new_h], "reason": r.reason}
                for r in self.expanded_depts
            ],
            "moved_groups": [
                {"dept_id": r.dept_id, "dx": r.dx, "dy": r.dy, "affected_user_ids": r.affected_user_ids, "reason": r.reason}
                for r in self.moved_groups
            ],
            "max_displacement_px": self.max_displacement_px,
            "ripple_radius_depts": self.ripple_radius_depts,
            "indirectly_moved_users": self.indirectly_moved_users,
            "ripple_chain": self.ripple_chain,
        }


def _safe_pos_float(raw: Any, default: float) -> float:
    """Parse to float; return default if None/empty/non-positive/unparseable.

    Defends against BI emitting "0"/0/None for width/height — `or` chains treat
    these as truthy/falsy inconsistently and can produce w=h=0 user nodes.
    """
    if raw is None or raw == "":
        return float(default)
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return float(default)
    return v if v > 0 else float(default)


def _node_from_bi_dict(d: dict[str, Any]) -> PowerNode:
    """Convert a BI getInfo node dict to PowerNode."""
    raw_type = d.get("node_type") or d.get("type", "")
    internal_type = _TYPE_FROM_BI.get(raw_type, raw_type)
    _default_w = PERSON_W if internal_type != "dept" else DEPT_DEFAULT_W
    _default_h = PERSON_H if internal_type != "dept" else DEPT_DEFAULT_H
    _raw_w = d.get("width") if d.get("width") not in (None, "") else d.get("node_width")
    _raw_h = d.get("height") if d.get("height") not in (None, "") else d.get("node_height")
    _final_w = _safe_pos_float(_raw_w, _default_w)
    _final_h = _safe_pos_float(_raw_h, _default_h)
    return PowerNode(
        id=str(d.get("id", "")),
        node_type=internal_type,
        name=str(d.get("name", "")),
        pid=str(d.get("pid", "")),
        department=str(d.get("department", "")),
        parent_dept_id=str(d.get("par_id") or d.get("node_parent_dept") or d.get("parent_dept_id", "")),
        _parent_dept_original=str(d.get("par_id", "")),  # raw BI value for writeback isolation
        position=str(d.get("position", "")),
        phone=str(d.get("phone", "")),
        cont_id=str(d.get("cont_id", "")),
        tagA=str(d.get("tagA", "")),
        tagB=str(d.get("tagB", "")),
        tagC_arr=str(d.get("tagC_arr", "")),
        tagD_label=str(d.get("tagD_label", "")),
        tagD_level=str(d.get("tagD_level", "")),
        tagD_other_name=str(d.get("tagD_other_name", "")),
        tagD_other_abbr=str(d.get("tagD_other_abbr", "")),
        information=str(d.get("information", "")),
        school=str(d.get("school", "")),
        hobby=str(d.get("hobby", "")),
        if_highLight=str(d.get("if_highLight", "1")),
        node_manager=str(d.get("node_manager", "0")),
        node_reach=str(d.get("node_reach", "0")),
        attitude_arr=list(d.get("attitude_arr", []) or []),
        jdy_id=str(d.get("jdy_id", "")),
        background=str(d.get("node_background", "")),
        node_border_color=str(d.get("node_border_color", "")),
        node_expect=str(d.get("node_expect", "")),
        x=float(d.get("x", 0)),
        y=float(d.get("y", 0)),
        w=_final_w,
        h=_final_h,
    )


def _power_node_to_bi_info_dict(node: PowerNode) -> dict[str, Any]:
    """Reverse of _node_from_bi_dict — PowerNode → BI getInfo node_info dict."""
    bi_type = node.node_type  # getInfo format uses "user"/"dept", NOT "person"/"department"
    if node.node_type == "user":
        width = PERSON_W
        height = PERSON_H
    else:
        width = node.w if node.w > 0 else DEPT_DEFAULT_W
        height = node.h if node.h > 0 else DEPT_DEFAULT_H
    parent_dept = node._parent_dept_original or node.parent_dept_id or ""
    return {
        "id": node.id,
        "node_type": bi_type,
        "name": node.name,
        "pid": node.pid,
        "department": node.department,
        "par_id": node.parent_dept_id,
        "node_parent_dept": parent_dept,
        "position": node.position,
        "phone": node.phone,
        "cont_id": node.cont_id,
        "tagA": node.tagA,
        "tagB": node.tagB,
        "tagC": node.tagC_arr,
        "tagC_arr": node.tagC_arr,
        "tagD": node.tagD_label,
        "tagD_label": node.tagD_label,
        "tagD_level": node.tagD_level,
        "tagD_other_name": node.tagD_other_name,
        "tagD_other_abbr": node.tagD_other_abbr,
        "information": node.information,
        "school": node.school,
        "hobby": node.hobby,
        "if_highLight": node.if_highLight,
        "node_manager": node.node_manager,
        "node_reach": node.node_reach,
        "attitude_arr": list(node.attitude_arr or []),
        "jdy_id": node.jdy_id,
        "node_background": node.background,
        "node_border_color": node.node_border_color,
        "node_expect": node.node_expect,
        "x": str(int(node.x)),
        "y": str(int(node.y)),
        "width": str(int(width)),
        "height": str(int(height)),
        "node_width": str(int(width)),
        "node_height": str(int(height)),
    }


def _compute_par_id(node: PowerNode) -> str:
    """Return node.parent_dept_id only if user is geometrically inside that dept.

    BI HAR 标准：par_id 只对真正嵌入部门的 user 填写，不是所有有逻辑归属的都填。
    """
    if node.node_type != "user" or not node.parent_dept_id:
        return ""
    return node.parent_dept_id


CROSS_DEPT_THRESHOLD = 0.30  # user-dept overlap ratio to count as "spanning"


def _resolve_parent_dept(
    user: PowerNode,
    dept_nodes: list[PowerNode],
) -> str:
    """Three-layer fallback to resolve a user's owning dept ID.

    Sets user.is_cross_dept = True if user geometrically spans ≥2 depts
    (each ≥ CROSS_DEPT_THRESHOLD overlap ratio).  Step A/B match keeps
    parent_dept_id but still checks cross-dept; Step C assigns only if
    fully_contained in exactly 1 dept, otherwise leaves parent empty.

    Returns the resolved dept ID (str), or empty string if none found.
    Never writes back to BI — result is only for in-memory layout use.
    """
    if user.node_type != "user":
        return ""

    raw_pdept = user.parent_dept_id
    user_bbox = (user.x, user.y, user.x + PERSON_W, user.y + PERSON_H)
    user_area = PERSON_W * PERSON_H

    # ── Pre-compute overlap ratios for all depts ──
    overlap_info: list[dict] = []
    for d in dept_nodes:
        d_bbox = (d.x, d.y, d.x + d.w, d.y + d.h)
        area = _rects_overlap_area(user_bbox, d_bbox)
        ratio = area / user_area
        fully_contained = _rects_contain(d_bbox, user_bbox, margin=0)
        overlap_info.append({
            "dept": d,
            "area": area,
            "ratio": ratio,
            "fully_contained": fully_contained,
        })

    # Count depts with overlap ≥ threshold
    high_depts = [oi for oi in overlap_info if oi["ratio"] >= CROSS_DEPT_THRESHOLD]
    user.is_cross_dept = len(high_depts) >= 2
    if user.is_cross_dept:
        logger.info("[PARENT_FALLBACK] %s → cross_dept: spans %d depts (≥%.0f%%): %s",
                    user.name, len(high_depts), CROSS_DEPT_THRESHOLD * 100,
                    [(oi["dept"].name, f"{oi['ratio']:.1%}") for oi in high_depts])

    resolved_id = ""
    layer = "?"

    # ── Layer A: par_id UUID ──
    if raw_pdept:
        match_a = next((d for d in dept_nodes if d.id == raw_pdept), None)
        if match_a:
            resolved_id = match_a.id
            layer = "A(UUID)"

    # ── Layer B: name match (only if A didn't match) ──
    if not resolved_id and raw_pdept:
        name_matches = [d for d in dept_nodes if d.name.strip() == raw_pdept.strip()]
        if len(name_matches) == 1:
            resolved_id = name_matches[0].id
            layer = "B(name)"
        elif len(name_matches) > 1:
            logger.warning("[PARENT_FALLBACK] %s → Layer B [NAME_AMBIGUOUS] raw_pdept=%r matched %d depts: %s",
                           user.name, raw_pdept, len(name_matches),
                           [d.name for d in name_matches])

    # ── Layer C: geometric containment ──
    if not resolved_id:
        fully_contained_by = [oi for oi in overlap_info if oi["fully_contained"]]
        if user.is_cross_dept:
            # Spans multiple depts but not fully contained in any single one
            # → leave parent_dept_id empty, is_cross_dept already True
            layer = "C(cross)"
            logger.info("[PARENT_FALLBACK] %s → Layer C(cross): no single fully_contained, cross_dept=True",
                        user.name)
        elif len(fully_contained_by) == 1:
            resolved_id = fully_contained_by[0]["dept"].id
            layer = "C(contained)"
            logger.info("[PARENT_FALLBACK] %s → Layer C(contained) dept=%s",
                        user.name, fully_contained_by[0]["dept"].name)
        elif len(fully_contained_by) > 1:
            # Fully contained in multiple depts (nested depts) — pick largest overlap
            best = max(fully_contained_by, key=lambda oi: oi["area"])
            resolved_id = best["dept"].id
            layer = "C(nested)"
            logger.info("[PARENT_FALLBACK] %s → Layer C(nested) dept=%s (of %d containers)",
                        user.name, best["dept"].name, len(fully_contained_by))
        elif high_depts:
            # Not fully contained, but one dept has significant overlap
            best = max(high_depts, key=lambda oi: oi["ratio"])
            resolved_id = best["dept"].id
            layer = "C(partial)"
            logger.info("[PARENT_FALLBACK] %s → Layer C(partial) dept=%s ratio=%.1f%%",
                        user.name, best["dept"].name, best["ratio"] * 100)
        else:
            layer = "C(none)"
            logger.debug("[PARENT_FALLBACK] %s → Layer C(none): no dept match", user.name)

    if resolved_id:
        dept_name = next((d.name for d in dept_nodes if d.id == resolved_id), "?")
        cross_mark = " [CROSS_DEPT]" if user.is_cross_dept else ""
        logger.info("[PARENT_FALLBACK] %s → %s dept=%s%s",
                    user.name, layer, dept_name, cross_mark)

    return resolved_id


def _to_up_node(node: PowerNode) -> dict[str, Any]:
    """Convert PowerNode to upInfo JSON dict — exact format matching BI HAR."""
    is_dept = node.node_type == "dept"

    obj: dict[str, Any] = {
        "id": node.id,
        "pid": node.pid or "",
        "cont_id": node.cont_id or "",
        "tagA": node.tagA or "",
        "tagB": node.tagB or "",
        "x": int(node.x),
        "y": int(node.y),
        "name": node.name,
        "phone": node.phone or "",
        "position": node.position or "",
        "department": node.department or "",
        "information": node.information or "",
        "school": node.school or "",
        "hobby": node.hobby or "",
        "if_highLight": node.if_highLight or "1",
        "node_manager": node.node_manager or "0",
        "node_reach": node.node_reach or "0",
        "tagD_other_abbr": node.tagD_other_abbr or "",
        "tagD_other_name": node.tagD_other_name or "",
        "node_type": node.node_type,
        "node_width": f"{node.w:.1f}" if is_dept else "0.0",
        "node_height": f"{node.h:.1f}" if is_dept else "0.0",
        "node_parent_dept": node._parent_dept_original or "",
        "node_background": (node.background or "#e9f5e9") if is_dept else "",
        "tagC": "",
        "tagC_arr": node.tagC_arr or "",
        "tagD": "",
        "tagD_label": node.tagD_label or "",
        "tagD_level": node.tagD_level or "",
        "attitude_arr": node.attitude_arr or [],
        "type": node.node_type,
        "jdy_id": node.jdy_id or "",
    }

    if is_dept:
        obj["width"] = int(node.w)
        obj["height"] = int(node.h)
        obj["par_id"] = ""
    else:
        obj["node_border_color"] = node.node_border_color or "#a2b1c3"
        obj["par_id"] = node._parent_dept_original

    return obj


def _generate_node_id() -> str:
    """Generate a unique node ID using UUID."""
    return uuid.uuid4().hex


def _make_person_node(
    name: str,
    department: str = "",
    position: str = "",
    phone: str = "00000000000",
    cont_id: str = "",
    pid: str = "",
    parent_dept_id: str = "",
    **kwargs: Any,
) -> PowerNode:
    """Create a person node with default values."""
    node = PowerNode(
        id=_generate_node_id(),
        node_type="user",
        name=name,
        department=department,
        position=position,
        phone=phone,
        cont_id=cont_id,
        pid=pid,
        parent_dept_id=parent_dept_id,
        w=PERSON_W,
        h=PERSON_H,
    )
    for k, v in kwargs.items():
        if hasattr(node, k):
            setattr(node, k, v)
    return node


def _make_dept_node(name: str, x: float = 0, y: float = 0, parent_dept_id: str = "", **kwargs: Any) -> PowerNode:
    """Create a department node with default values."""
    node = PowerNode(
        id=_generate_node_id(),
        node_type="dept",
        name=name,
        parent_dept_id=parent_dept_id,
        x=x,
        y=y,
        w=DEPT_DEFAULT_W,
        h=DEPT_DEFAULT_H,
        background="#e9f5e9",
    )
    for k, v in kwargs.items():
        if hasattr(node, k):
            setattr(node, k, v)
    return node


# ═══════════════════════════════════════════════════════════
#  Layer 0: LLM Semantic Prompt & Parsing
# ═══════════════════════════════════════════════════════════

POWER_MAP_SYSTEM_PROMPT = """你是一个权力地图结构分析助手。根据用户的自然语言指令和当前画布数据，输出结构化的变更方案（JSON）。

## 核心规则

1. **只输出结构变更，不输出坐标**：你只负责语义分析。坐标由后端布局引擎处理。
2. **隶属走 department 字段**：人员归属部门通过 department 字段表达（部门名），不是 edge。
3. **汇报走 reports_to 字段**：人员之间的汇报关系通过 reports_to 字段表达（引用 tmp_id 或姓名）。
4. **忽略 BI 的 pid 字段**：BI 数据中的 pid 语义模糊。汇报关系只看 reports_to。

## JSON 输出格式

输出纯 JSON（不要 markdown 代码块），结构如下：

{{
  "intent": "create_dept",
  "explanation": "新建财务部，CFO黄宇，6名下属向其汇报",
  "version_id": "{version_id}",
  "version_name": "{version_name}",
  "nodes_add": [
    {{
      "tmp_id": "dept_财务部",
      "node_type": "dept",
      "name": "财务部"
    }},
    {{
      "tmp_id": "person_黄宇",
      "node_type": "user",
      "name": "黄宇",
      "department": "财务部",
      "position": "CFO"
    }},
    {{
      "tmp_id": "person_纪成",
      "node_type": "user",
      "name": "纪成",
      "department": "财务部",
      "reports_to": "person_黄宇"
    }}
  ],
  "nodes_update": [],
  "nodes_delete": [],
  "moves": [],
  "custom_edges_add": [],
  "custom_edges_delete": [],
  "scope_declaration": {{"expected_affected_count": 8, "allow_propagation": false}}
}}

## 字段说明

- **nodes_add 每个节点必填**：tmp_id（唯一临时ID）、node_type（"dept"或"user"）、name
- **person 节点**：department（部门名）、position（职位）、reports_to（上级的 tmp_id 或姓名）
- **dept 节点**：parent_dept（父部门名，顶级留空""）
- **custom_edges_add**：额外边。格式 {{"source": "tmp_id或姓名", "target": "tmp_id或姓名", "edge_type": "reports_to"}}
  - person 之间的汇报关系优先用 reports_to 字段
  - custom_edges_add 仅用于已有节点之间的新建边
- **nodes_update**：修改已有节点。格式 {{"id_or_name": "张三", "position": "新职位"}}
- **moves**：人员跨部门调动。格式 {{"person": "姓名", "to_dept": "目标部门名"}}

## 当前数据

版本：{version_name} ({version_id})
公司：{company_name}

当前节点：
{current_nodes}

当前边：
{current_edges}

可用联系人（CRM 数据）：
{available_contacts}

## 用户指令

{user_message}

## 注意事项

- 部门 type 用 "dept"，人员 type 用 "user"
- person 的 department 写部门名称，不是 id
- reports_to 用 tmp_id（新建节点之间）或已有节点姓名
- 不要输出 markdown 代码块标记，只输出纯 JSON
- 空数组写 []，不要省略
"""



def _parse_llm_output(text: str, version_id: str, version_name: str) -> dict[str, Any]:
    """Parse LLM JSON output into a SemanticDelta dict."""
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    parsed = json.loads(text)

    delta: dict[str, Any] = {
        "intent": parsed.get("intent", "mixed"),
        "explanation": parsed.get("explanation", ""),
        "version_id": parsed.get("version_id", version_id),
        "version_name": parsed.get("version_name", version_name),
        "nodes_add": parsed.get("nodes_add", []),
        "nodes_update": parsed.get("nodes_update", []),
        "nodes_delete": parsed.get("nodes_delete", []),
        "moves": parsed.get("moves", []),
        "custom_edges_add": parsed.get("custom_edges_add", []),
        "custom_edges_delete": parsed.get("custom_edges_delete", []),
        "scope_declaration": parsed.get("scope_declaration", {"expected_affected_count": 0, "allow_propagation": False}),
    }
    return delta


# ═══════════════════════════════════════════════════════════
#  Layer 1: State Merging
# ═══════════════════════════════════════════════════════════

@dataclass
class MergeContext:
    """Working state during state merging."""
    nodes_by_id: dict[str, PowerNode] = field(default_factory=dict)
    nodes_by_name: dict[str, PowerNode] = field(default_factory=dict)
    depts_by_name: dict[str, PowerNode] = field(default_factory=dict)
    all_nodes: list[PowerNode] = field(default_factory=list)
    edges: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    tmp_map: dict[str, str] = field(default_factory=dict)  # tmp_id → real_id
    # ── Structure-first toolset (v6) state ──
    # Persisted layout preferences the Agent records via add_layout_constraint.
    # Each entry: {"id": str, "type": "same_rank"|"horizontal_order", "nodes": [...]}.
    layout_constraints: list[dict[str, Any]] = field(default_factory=list)
    # Harness session context (set by _execute_harness*; consumed by render_screenshot).
    harness_prj_id: str = ""
    harness_cookies: dict[str, str] | None = None
    harness_headers: dict[str, str] | None = None
    last_screenshot_url: str = ""
    # auto_fix_collisions call counter (spec caps at 2 per session).
    auto_fix_calls: int = 0
    # Repeated-failed-call detection: deque of (tool_name, frozenset(args items)) keys.
    # Used by _execute_harness_tool to short-circuit when the LLM keeps retrying
    # the same failing call with identical arguments.
    _recent_tool_calls: list = field(default_factory=list)  # max 5 entries, manual ring
    # Persistence context — populated by the harness so save_state can
    # write back without re-fetching everything.
    harness_cfg: Any | None = None
    harness_current_user: dict[str, Any] | None = None
    harness_version_id: str = ""
    harness_session_id: str = ""
    # BI version pass-through — populated when a specific version UUID
    # was requested upstream so sandbox getInfo and save_state can use
    # the actual version instead of falling back to "main".
    bi_version: str | None = None
    bi_prj_type: str = "company"
    bi_ver_info: str | None = None
    # CRM contact roster (from BI getInfo step1 contact_info). Used at
    # commit time to back-fill cont_id / phone / position / department on
    # LLM-created user nodes by exact name match — transparent to the LLM.
    upinfo_users: list = field(default_factory=list)


def _build_merge_context(
    current_nodes: list[PowerNode],
    current_edges: list[dict[str, Any]],
    version_id: str,
    bi_version: str | None = None,
    bi_prj_type: str = "company",
    bi_ver_info: str | None = None,
) -> MergeContext:
    """Build indices from current BI state (v4 — no snapshot/user_adjusted)."""
    ctx = MergeContext()
    ctx.all_nodes = list(current_nodes)
    ctx.edges = [dict(e) for e in current_edges]

    for n in ctx.all_nodes:
        ctx.nodes_by_id[n.id] = n
        if n.name:
            if n.name in ctx.nodes_by_name:
                # Duplicate name — keep first, warn
                if n.node_type == ctx.nodes_by_name[n.name].node_type:
                    ctx.warnings.append(f"重名节点: {n.name}")
            else:
                ctx.nodes_by_name[n.name] = n
        if n.node_type == "dept" and n.name:
            ctx.depts_by_name[n.name] = n

    ctx.bi_version = bi_version
    ctx.bi_prj_type = bi_prj_type
    ctx.bi_ver_info = bi_ver_info

    # Sanity: zero-dimension nodes get defaults (BI data truthy-fallback defense)
    _W_DEFAULTS = {"user": PERSON_W, "dept": DEPT_DEFAULT_W}
    _H_DEFAULTS = {"user": PERSON_H, "dept": DEPT_DEFAULT_H}
    _fixed_count = 0
    for n in ctx.all_nodes:
        if not n.w or n.w <= 0:
            n.w = float(_W_DEFAULTS.get(n.node_type, PERSON_W))
            _fixed_count += 1
        if not n.h or n.h <= 0:
            n.h = float(_H_DEFAULTS.get(n.node_type, PERSON_H))
    if _fixed_count > 0:
        logger.warning(f"[DEBUG-J wh_sanity] fixed {_fixed_count} nodes with zero dimensions")

    return ctx


def _resolve_tmp_id(tmp_id: str, tmp_map: dict[str, str]) -> str:
    """Resolve a tmp_id or name to a real node id."""
    if tmp_id in tmp_map:
        return tmp_map[tmp_id]
    return ""


def _apply_delta(
    ctx: MergeContext,
    delta: dict[str, Any],
) -> MergeContext:
    """Apply semantic delta to the in-memory graph. Order: delete → update → move → add."""

    # ── 1. Delete nodes (v4 zero-ripple principle: no re-layout, no reorder, no resize) ──
    delete_keys: set[str] = set()
    cascade_ids: set[str] = set()  # dept ids to cascade-delete users from
    for item in delta.get("nodes_delete", []):
        if isinstance(item, dict):
            key = str(item.get("id_or_name", ""))
            if key:
                delete_keys.add(key)
            if item.get("cascade"):
                node = ctx.nodes_by_id.get(key) or ctx.nodes_by_name.get(key)
                if node and node.node_type == "dept":
                    cascade_ids.add(node.id)
        elif isinstance(item, str):
            delete_keys.add(item)

    delete_ids: set[str] = set()
    for key in delete_keys:
        node = ctx.nodes_by_id.get(key) or ctx.nodes_by_name.get(key)
        if node:
            delete_ids.add(node.id)

    # Cascade: if dept deleted with cascade=true, also delete its users
    if cascade_ids:
        for n in ctx.all_nodes:
            if n.node_type == "user" and n.parent_dept_id in cascade_ids:
                delete_ids.add(n.id)

    if delete_ids:
        # ── Zero-ripple: clear references, remove nodes+edges, NO re-layout ──
        # Clear pid references for children of deleted nodes
        for n in ctx.all_nodes:
            if n.pid in delete_ids:
                n.pid = ""
        # Clear par_id references (cascade=false: user stays, parent cleared)
        for n in ctx.all_nodes:
            if n.parent_dept_id in delete_ids:
                n.parent_dept_id = ""
        # Remove nodes (positions of remaining nodes unchanged)
        ctx.all_nodes = [n for n in ctx.all_nodes if n.id not in delete_ids]
        # Remove edges involving deleted nodes
        ctx.edges = [
            e for e in ctx.edges
            if str(e.get("source_id", "")) not in delete_ids
            and str(e.get("target_id", "")) not in delete_ids
        ]
        # Rebuild indices (no position changes)
        ctx.nodes_by_id = {n.id: n for n in ctx.all_nodes}
        ctx.nodes_by_name = {}
        ctx.depts_by_name = {}
        for n in ctx.all_nodes:
            if n.name and n.name not in ctx.nodes_by_name:
                ctx.nodes_by_name[n.name] = n
            if n.node_type == "dept" and n.name:
                ctx.depts_by_name[n.name] = n

    # ── 2. Update nodes ──
    for item in delta.get("nodes_update", []):
        if not isinstance(item, dict):
            continue
        key = str(item.get("id_or_name", ""))
        node = ctx.nodes_by_id.get(key) or ctx.nodes_by_name.get(key)
        if not node:
            ctx.warnings.append(f"更新失败: 找不到节点 '{key}'")
            continue
        updatable = ["name", "position", "phone", "department", "tagA", "tagB",
                      "information", "school", "hobby", "node_manager", "node_reach",
                      "if_highLight", "tagC_arr", "tagD_label", "tagD_level",
                      "tagD_other_name", "tagD_other_abbr", "background",
                      "node_border_color", "node_expect", "cont_id", "jdy_id"]
        for k, v in item.items():
            if k in updatable and hasattr(node, k):
                setattr(node, k, v)

    # ── 3. Move persons between departments ──
    for item in delta.get("moves", []):
        if not isinstance(item, dict):
            continue
        person_key = str(item.get("person", ""))
        to_dept = str(item.get("to_dept", ""))
        if not person_key or not to_dept:
            continue
        node = ctx.nodes_by_id.get(person_key) or ctx.nodes_by_name.get(person_key)
        if not node or node.node_type != "user":
            ctx.warnings.append(f"移动失败: 找不到人员 '{person_key}'")
            continue
        node.department = to_dept
        # Resolve parent_dept_id
        dept = ctx.depts_by_name.get(to_dept)
        if dept:
            node.parent_dept_id = dept.id
        else:
            node.parent_dept_id = ""

    # ── 4. Add nodes ──
    tmp_map: dict[str, str] = {}  # tmp_id → real_id

    for item in delta.get("nodes_add", []):
        if not isinstance(item, dict):
            continue
        node_type = str(item.get("node_type", "user"))
        name = str(item.get("name", "")).strip()
        if not name:
            continue

        # Check for duplicate name
        if node_type == "dept":
            existing = ctx.depts_by_name.get(name)
            if existing:
                ctx.warnings.append(f"部门 '{name}' 已存在，跳过新增")
                tmp_map[item.get("tmp_id", "")] = existing.id
                continue

        new_id = _generate_node_id()
        tmp_id = str(item.get("tmp_id", ""))
        if tmp_id:
            tmp_map[tmp_id] = new_id

        dept_name = str(item.get("department", ""))
        reports_to = str(item.get("reports_to", ""))

        if node_type == "dept":
            parent_dept_name = str(item.get("parent_dept", ""))
            parent_dept_id = ""
            if parent_dept_name:
                pdept = ctx.depts_by_name.get(parent_dept_name)
                if pdept:
                    parent_dept_id = pdept.id
            node = _make_dept_node(
                name=name,
                parent_dept_id=parent_dept_id,
            )
            node.background = str(item.get("background_color", "#e9f5e9"))
        else:
            # Resolve parent_dept_id from department name
            parent_dept_id = ""
            if dept_name:
                dept = ctx.depts_by_name.get(dept_name)
                if dept:
                    parent_dept_id = dept.id
                else:
                    # Auto-create department
                    new_dept = _make_dept_node(name=dept_name)
                    ctx.all_nodes.append(new_dept)
                    ctx.nodes_by_id[new_dept.id] = new_dept
                    ctx.depts_by_name[dept_name] = new_dept
                    if new_dept.name not in ctx.nodes_by_name:
                        ctx.nodes_by_name[new_dept.name] = new_dept
                    parent_dept_id = new_dept.id
                    ctx.warnings.append(f"自动创建部门 '{dept_name}'")

            node = _make_person_node(
                name=name,
                department=dept_name,
                position=str(item.get("position", "")),
                phone=str(item.get("phone", "00000000000")),
                cont_id=str(item.get("cont_id", "")),
                parent_dept_id=parent_dept_id,
            )

        # Copy extra fields from LLM
        for k in ["tagA", "tagB", "information", "school", "hobby",
                   "tagC_arr", "tagD_label", "tagD_level",
                   "tagD_other_name", "tagD_other_abbr",
                   "node_manager", "node_reach", "if_highLight",
                   "jdy_id", "node_border_color", "node_expect"]:
            if k in item:
                setattr(node, k, item[k])

        node.id = new_id
        ctx.all_nodes.append(node)
        ctx.nodes_by_id[new_id] = node
        if name not in ctx.nodes_by_name:
            ctx.nodes_by_name[name] = node
        if node_type == "dept":
            ctx.depts_by_name[name] = node

    # Second pass: resolve reports_to → pid using tmp_map
    for item in delta.get("nodes_add", []):
        if not isinstance(item, dict):
            continue
        tmp_id = str(item.get("tmp_id", ""))
        real_id = tmp_map.get(tmp_id, "")
        if not real_id:
            continue
        node = ctx.nodes_by_id.get(real_id)
        if not node or node.node_type != "user":
            continue

        reports_to = str(item.get("reports_to", ""))
        if reports_to:
            # Try tmp_map first, then name lookup
            resolved = tmp_map.get(reports_to, "")
            if not resolved:
                target = ctx.nodes_by_name.get(reports_to)
                if target:
                    resolved = target.id
            if resolved:
                node.pid = resolved
            else:
                ctx.warnings.append(f"reports_to '{reports_to}' 无法解析，'{node.name}' 设为根节点")

    # ── 5. Custom edges ──
    for item in delta.get("custom_edges_delete", []):
        if not isinstance(item, dict):
            continue
        src = str(item.get("source", ""))
        tgt = str(item.get("target", ""))
        src_real = tmp_map.get(src, src)
        tgt_real = tmp_map.get(tgt, tgt)
        src_node = ctx.nodes_by_id.get(src_real) or ctx.nodes_by_name.get(src_real) \
                   or ctx.nodes_by_id.get(src) or ctx.nodes_by_name.get(src)
        tgt_node = ctx.nodes_by_id.get(tgt_real) or ctx.nodes_by_name.get(tgt_real) \
                   or ctx.nodes_by_id.get(tgt) or ctx.nodes_by_name.get(tgt)
        if src_node and tgt_node:
            ctx.edges = [
                e for e in ctx.edges
                if not (str(e.get("source_id", "")) == src_node.id and
                        str(e.get("target_id", "")) == tgt_node.id)
            ]

    for item in delta.get("custom_edges_add", []):
        if not isinstance(item, dict):
            continue
        src = str(item.get("source", ""))
        tgt = str(item.get("target", ""))
        src_real = tmp_map.get(src, src)
        tgt_real = tmp_map.get(tgt, tgt)
        src_node = ctx.nodes_by_id.get(src_real) or ctx.nodes_by_name.get(src_real) \
                   or ctx.nodes_by_id.get(src) or ctx.nodes_by_name.get(src)
        tgt_node = ctx.nodes_by_id.get(tgt_real) or ctx.nodes_by_name.get(tgt_real) \
                   or ctx.nodes_by_id.get(tgt) or ctx.nodes_by_name.get(tgt)
        if not src_node or not tgt_node:
            ctx.warnings.append(f"连线失败: 找不到节点 '{src}' 或 '{tgt}'")
            continue
        # Check duplicate
        dup = any(
            str(e.get("source_id", "")) == src_node.id and
            str(e.get("target_id", "")) == tgt_node.id
            for e in ctx.edges
        )
        if dup:
            continue
        ctx.edges.append({
            "source_id": src_node.id,
            "target_id": tgt_node.id,
            "source_port": "port-bottom",
            "target_port": "port-top",
            "color": str(item.get("color", "#A2B1C3")),
            "edge_remark": str(item.get("remark", "")),
        })

    ctx.tmp_map = tmp_map
    return ctx


# ═══════════════════════════════════════════════════════════
#  Layer 2: Change Impact Analysis (v4 core)
# ═══════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════


def _mark_geometry_anomalies(nodes: list[PowerNode]) -> None:
    """Mark existing user nodes with anomalous positions as geometry_locked.

    Rules:
    1. User has parent_dept but bbox not fully inside that dept → locked
    2. User has no parent_dept but overlaps any dept → locked

    Before locking, runs _resolve_parent_dept to fill missing parent_dept_id
    via three-layer fallback (par_id UUID → name match → geometry).  Only
    users that still lack a valid parent after fallback can be locked by Rule 2.
    """
    dept_nodes = [n for n in nodes if n.node_type == "dept"]

    # ── Pre-pass: resolve missing parent_dept_id ──
    for u in nodes:
        if u.node_type != "user":
            continue
        # Only run fallback if parent_dept_id is missing or looks like a name (not UUID)
        raw = u.parent_dept_id
        is_uuid = (len(raw) >= 32 and raw.replace("-", "").isalnum()
                   if raw else False)
        if not raw or not is_uuid:
            resolved = _resolve_parent_dept(u, dept_nodes)
            if resolved:
                u.parent_dept_id = resolved

    # ── Original Rule 1 + Rule 2 + Rule 3 (cross_dept) ──
    for u in nodes:
        if u.node_type != "user":
            continue

        # Rule 3: cross-dept user — always lock (semantic: spans ≥2 depts)
        if getattr(u, 'is_cross_dept', False):
            u.geometry_locked = True
            logger.info("geometry_locked: user %s is cross_dept (spans ≥2 depts)", u.name)
            continue  # skip Rule 1/2 — already locked

        # Rule 1: user in dept but out of bounds
        if u.parent_dept_id:
            claimed_dept = next((d for d in dept_nodes if d.id == u.parent_dept_id), None)
            if claimed_dept:
                if not (
                    u.x >= claimed_dept.x - GEO_EMBED_SAFE_MARGIN and
                    u.y >= claimed_dept.y - GEO_EMBED_SAFE_MARGIN and
                    u.x + PERSON_W <= claimed_dept.x + claimed_dept.w + GEO_EMBED_SAFE_MARGIN and
                    u.y + PERSON_H <= claimed_dept.y + claimed_dept.h + GEO_EMBED_SAFE_MARGIN
                ):
                    u.geometry_locked = True
                    logger.info("geometry_locked: user %s outside claimed dept %s", u.name, claimed_dept.name)

        # Rule 2: no parent_dept but overlaps a dept
        if not u.parent_dept_id and not u.geometry_locked:
            for d in dept_nodes:
                if _rects_overlap(
                    (u.x, u.y, u.x + PERSON_W, u.y + PERSON_H),
                    (d.x - GEO_EMBED_SAFE_MARGIN,
                     d.y - GEO_EMBED_SAFE_MARGIN,
                     d.x + d.w + GEO_EMBED_SAFE_MARGIN,
                     d.y + d.h + GEO_EMBED_SAFE_MARGIN)
                ):
                    u.geometry_locked = True
                    logger.info("geometry_locked: orphan user %s overlaps dept %s", u.name, d.name)
                    break


def _build_bbox_items(nodes: list[PowerNode]) -> list[BBoxItem]:
    """Build unified BBoxItem list from all nodes."""
    items: list[BBoxItem] = []
    for n in nodes:
        w = n.w if n.node_type == "dept" else PERSON_W
        h = n.h if n.node_type == "dept" else PERSON_H
        item = BBoxItem(
            id=n.id,
            item_type=n.node_type,
            x=n.x,
            y=n.y,
            w=w,
            h=h,
            parent_dept_id=n.parent_dept_id if n.node_type == "user" else None,
        )
        items.append(item)
    return items


def _build_rigid_groups_v2(nodes: list[PowerNode]) -> list[RigidGroup]:
    """v4.1: Build nested RigidGroup forest from all nodes."""
    dept_nodes = [n for n in nodes if n.node_type == "dept"]
    user_nodes = [n for n in nodes if n.node_type == "user"]

    # Build flat groups
    groups: dict[str, RigidGroup] = {}
    for d in dept_nodes:
        groups[d.id] = RigidGroup(dept=d)

    # Detect nesting: if dept_A bbox contains dept_B bbox, B is nested in A
    for da in dept_nodes:
        for db in dept_nodes:
            if da.id == db.id:
                continue
            a_bbox = (da.x, da.y, da.x + da.w, da.y + da.h)
            b_bbox = (db.x, db.y, db.x + db.w, db.y + db.h)
            if _rects_contain(a_bbox, b_bbox, GEO_EMBED_SAFE_MARGIN):
                # db is nested inside da
                groups[da.id].nested_children.append(groups[db.id])

    # Assign users to deepest containing group
    for u in user_nodes:
        # Skip locked users
        if u.geometry_locked:
            continue
        best_depth = -1
        best_id = None
        for d in dept_nodes:
            d_bbox = (d.x, d.y, d.x + d.w, d.y + d.h)
            u_bbox = (u.x, u.y, u.x + PERSON_W, u.y + PERSON_H)
            if _rects_contain(d_bbox, u_bbox, GEO_EMBED_SAFE_MARGIN):
                depth = _count_nesting_depth(groups[d.id])
                if depth > best_depth:
                    best_depth = depth
                    best_id = d.id
        if best_id:
            groups[best_id].direct_users.append(u)

    # Return top-level groups only (no parent)
    all_dept_ids = {d.id for d in dept_nodes}
    child_ids: set[str] = set()
    for g in groups.values():
        for nc in g.nested_children:
            child_ids.add(nc.dept.id)
    top_ids = all_dept_ids - child_ids
    return [groups[tid] for tid in top_ids]


def _rects_contain(outer: tuple, inner: tuple, margin: float = 0) -> bool:
    """Check if outer bbox fully contains inner bbox (with optional margin)."""
    ox1, oy1, ox2, oy2 = outer
    ix1, iy1, ix2, iy2 = inner
    return (ix1 >= ox1 - margin and iy1 >= oy1 - margin and
            ix2 <= ox2 + margin and iy2 <= oy2 + margin)


def _count_nesting_depth(group: RigidGroup) -> int:
    """Count how many levels of nesting this group has."""
    if not group.nested_children:
        return 1
    return 1 + max(_count_nesting_depth(c) for c in group.nested_children)


def _check_collision(
    items: list[BBoxItem],
    groups: list[RigidGroup],
    locked_ids: set[str] | None = None,
) -> list[tuple[str, str, str]]:
    """Check all-pairs collision. Skips geometry_locked nodes."""
    locked_ids = locked_ids or set()
    conflicts: list[tuple[str, str, str]] = []

    for i in range(len(items)):
        a = items[i]
        if a.id in locked_ids:
            continue
        for j in range(i + 1, len(items)):
            b = items[j]
            if b.id in locked_ids:
                continue
            if not _rects_overlap((a.x, a.y, a.x + a.w, a.y + a.h),
                                  (b.x, b.y, b.x + b.w, b.y + b.h)):
                continue

            # user–user
            if a.item_type == "user" and b.item_type == "user":
                conflicts.append((a.id, b.id, "user–user overlap"))
            # dept–dept
            elif a.item_type == "dept" and b.item_type == "dept":
                conflicts.append((a.id, b.id, "dept–dept overlap"))
            # user–dept
            elif a.item_type == "user" and b.item_type == "dept":
                if a.parent_dept_id != b.id:
                    conflicts.append((a.id, b.id, f"user outside dept {b.id}"))
            elif b.item_type == "user" and a.item_type == "dept":
                if b.parent_dept_id != a.id:
                    conflicts.append((b.id, a.id, f"user outside dept {a.id}"))

    # Check inter-group spacing
    for i in range(len(groups)):
        for j in range(i + 1, len(groups)):
            ga = groups[i]
            gb = groups[j]
            ax1, ay1, ax2, ay2 = ga.bbox()
            bx1, by1, bx2, by2 = gb.bbox()
            gap_x = max(0, bx1 - ax2) if bx1 > ax2 else max(0, ax1 - bx2)
            gap_y = max(0, by1 - ay2) if by1 > ay2 else max(0, ay1 - by2)
            if gap_x < MIN_GAP_BETWEEN_DEPTS and gap_y < MIN_GAP_BETWEEN_DEPTS and (gap_x == 0 or gap_y == 0):
                if ax1 < bx2 and ax2 > bx1 and ay1 < by2 and ay2 > by1:
                    conflicts.append((ga.dept.id, gb.dept.id, "dept groups too close (overlap)"))

    return conflicts


def _push_group_right(group: RigidGroup, amount: float) -> None:
    """Push a group to the right by amount px."""
    group.translate(amount, 0)


# ═══════════════════════════════════════════════════════════
#  v4.1 adaptive_push_v2 — 自适应推挤算法
# ═══════════════════════════════════════════════════════════

def adaptive_push_v2(
    target_node: PowerNode,
    all_top_groups: list[RigidGroup],
    ripple_report: RippleReport | None = None,
) -> RippleReport:
    """v4.1: 自适应推挤。遇到空间冲突时自动扩展容器 + 平移邻居。"""
    if ripple_report is None:
        ripple_report = RippleReport()

    # Step 1: 定位 target 所属的最深层 RigidGroup
    host_group = _find_deepest_host_group(target_node, all_top_groups)

    # Step 2: 嵌套链向上传播（容器扩展）
    if host_group:
        _propagate_expansion_upward(
            (target_node.x, target_node.y, target_node.x + PERSON_W, target_node.y + PERSON_H),
            host_group, ripple_report
        )

    # Step 3: 找到 host 所属的顶级祖先
    top_group = host_group
    if top_group:
        top_group = _find_top_level_ancestor(host_group, all_top_groups)

    # Step 4: 平级链向外传播（推挤邻居）
    if top_group:
        _propagate_translation_sideways(top_group, all_top_groups, ripple_report)

    ripple_report.finalize(all_top_groups)
    return ripple_report


def _find_deepest_host_group(node: PowerNode, all_groups: list[RigidGroup]) -> RigidGroup | None:
    """Find the deepest RigidGroup whose dept contains this node."""
    u_bbox = (node.x, node.y, node.x + PERSON_W, node.y + PERSON_H)
    best_group = None
    best_depth = -1
    def _search(groups: list[RigidGroup], depth: int):
        nonlocal best_group, best_depth
        for g in groups:
            if g.contains(u_bbox, with_padding=True):
                if depth > best_depth:
                    best_depth = depth
                    best_group = g
                _search(g.nested_children, depth + 1)
    _search(all_groups, 1)
    return best_group


def _find_top_level_ancestor(group: RigidGroup, all_top_groups: list[RigidGroup]) -> RigidGroup:
    """Find the top-level RigidGroup that contains this group (or itself if already top)."""
    if group in all_top_groups:
        return group
    for top in all_top_groups:
        result = _find_in_tree(group.dept.id, top)
        if result == top:
            return top
    return group  # fallback


def _find_in_tree(dept_id: str, current: RigidGroup) -> RigidGroup | None:
    if current.dept.id == dept_id:
        return current
    for child in current.nested_children:
        result = _find_in_tree(dept_id, child)
        if result:
            return current
    return None


def _propagate_expansion_upward(
    inner_bbox: tuple[float, float, float, float],
    current_group: RigidGroup,
    ripple_report: RippleReport,
) -> None:
    """从 current_group 开始向上沿嵌套链传播扩展."""
    while current_group is not None:
        if current_group.contains(inner_bbox, with_padding=True):
            break  # 容得下
        old_w, old_h = current_group.dept.w, current_group.dept.h
        current_group.expand(inner_bbox)
        ripple_report.add_expansion(
            dept_id=current_group.dept.id,
            old_w=old_w, old_h=old_h,
            new_w=current_group.dept.w, new_h=current_group.dept.h,
            reason="嵌套内容越界"
        )
        inner_bbox = current_group.bbox()
        # Walk up: find parent in the tree
        current_group = None  # FIX: we don't have parent pointers; for now, single-level
        # In Phase 3 integration, we'll pass parent lookup


def _propagate_translation_sideways(
    top_group: RigidGroup,
    all_top_groups: list[RigidGroup],
    ripple_report: RippleReport,
) -> None:
    """顶级组与平级邻居的碰撞推挤，递归收敛."""
    queue: list[RigidGroup] = [top_group]
    processed: set[str] = set()

    while queue:
        current = queue.pop(0)
        if current.dept.id in processed:
            continue
        processed.add(current.dept.id)

        cb = current.bbox()
        for other in all_top_groups:
            if other.dept.id in processed:
                continue
            if other.dept.id == current.dept.id:
                continue
            ob = other.bbox()
            if not _rects_overlap((cb[0], cb[1], cb[2], cb[3]),
                                   (ob[0], ob[1], ob[2], ob[3])):
                continue

            # 计算推挤向量
            dx_right = cb[2] + MIN_GAP_BETWEEN_DEPTS - ob[0]
            dy_down = cb[3] + MIN_GAP_BETWEEN_DEPTS - ob[1]

            if dx_right > 0 and dx_right <= dy_down:
                dx, dy = dx_right, 0.0
            elif dy_down > 0:
                dx, dy = 0.0, dy_down
            else:
                continue

            affected_ids = [u.id for u in other.direct_users]
            for child in other.nested_children:
                _collect_user_ids(child, affected_ids)

            other.translate(dx, dy)
            ripple_report.add_translation(
                dept_id=other.dept.id,
                dx=dx, dy=dy,
                affected_user_ids=affected_ids,
                reason=f"被 {current.dept.name} 推挤"
            )
            queue.append(other)


def _collect_user_ids(group: RigidGroup, ids: list[str]):
    for u in group.direct_users:
        ids.append(u.id)
    for child in group.nested_children:
        _collect_user_ids(child, ids)


def _calc_push_vector(pusher: RigidGroup, pushee: RigidGroup) -> tuple[float, float]:
    """计算最小推挤向量，方向限定右或下."""
    pb = pusher.bbox()
    qb = pushee.bbox()
    dx = pb[2] + MIN_GAP_BETWEEN_DEPTS - qb[0]
    dy = pb[3] + MIN_GAP_BETWEEN_DEPTS - qb[1]
    if dx <= 0 and dy <= 0:
        return (0.0, 0.0)
    if dx > 0 and dx <= dy:
        return (dx, 0.0)
    elif dy > 0:
        return (0.0, dy)
    return (0.0, 0.0)


def _check_ripple_threshold(ripple_report: RippleReport, delta: dict[str, Any]) -> None:
    """检查涟漪规模是否超出阈值。超出且未声明 allow_large_ripple → 返回 NeedsConfirmation."""
    allow_large = delta.get("scope_declaration", {}).get("allow_large_ripple", False)
    if allow_large:
        return  # 用户已确认，跳过检查

    warnings = []
    moved_count = len(ripple_report.moved_groups)
    if moved_count > RIPPLE_WARN_THRESHOLD["moved_groups_count"]:
        warnings.append(f"平移 {moved_count} 个部门组(阈值 {RIPPLE_WARN_THRESHOLD['moved_groups_count']})")
    if ripple_report.max_displacement_px > RIPPLE_WARN_THRESHOLD["max_displacement_px"]:
        warnings.append(f"最大位移 {ripple_report.max_displacement_px:.0f}px(阈值 {RIPPLE_WARN_THRESHOLD['max_displacement_px']})")
    if ripple_report.ripple_radius_depts > RIPPLE_WARN_THRESHOLD["ripple_radius_depts"]:
        warnings.append(f"涉及 {ripple_report.ripple_radius_depts} 个部门(阈值 {RIPPLE_WARN_THRESHOLD['ripple_radius_depts']})")
    if ripple_report.indirectly_moved_users > RIPPLE_WARN_THRESHOLD["indirectly_moved_users"]:
        warnings.append(f"间接移动 {ripple_report.indirectly_moved_users} 人(阈值 {RIPPLE_WARN_THRESHOLD['indirectly_moved_users']})")

    if warnings:
        raise ValueError(
            f"涟漪规模超出阈值: {'; '.join(warnings)}。"
            f"请在 scope_declaration 中设置 allow_large_ripple=true 确认执行。"
        )


def _find_safe_position(
    items: list[BBoxItem],
    groups: list[RigidGroup],
    w: float,
    h: float,
    start_x: float,
    start_y: float,
    exclude_id: str | None = None,
) -> tuple[float, float] | None:
    """Search for a non-colliding position starting from (start_x, start_y)."""
    candidates = [
        (start_x, start_y),
        (start_x + w + 20, start_y),
        (start_x, start_y + h + 20),
        (start_x + w + 20, start_y + h + 20),
        (start_x - w - 20, start_y),
        (start_x, start_y - h - 20),
    ]
    for cx, cy in candidates:
        test_bbox = (cx, cy, cx + w, cy + h)
        ok = True
        for it in items:
            if exclude_id and it.id == exclude_id:
                continue
            ib = (it.x, it.y, it.x + it.w, it.y + it.h)
            if _rects_overlap(test_bbox, ib):
                ok = False
                break
        if ok:
            return (cx, cy)
    return None


def _compute_forced_move_set(
    ctx: MergeContext,
    delta: dict[str, Any],
) -> set[str]:
    """Identify nodes that MUST move due to the delta.

    Rules:
    - nodes_add (user):  only the new node (if fits in dept) + dept resize if needed
    - nodes_add (dept):  only the new dept node
    - nodes_delete:      NO nodes move (deletions don't trigger reshuffle)
    - nodes_update:      NO nodes move (field-only changes)
    - moves:             only the moved person
    - relations:         NO nodes move (edge-only changes)
    """
    forced: set[str] = set()

    # ── New users ──
    for item in delta.get("nodes_add", []):
        if not isinstance(item, dict):
            continue
        nt = item.get("node_type", "")
        if nt == "user" or nt == "person":
            # The new node itself
            tmp_id = item.get("tmp_id", "")
            if tmp_id:
                forced.add(tmp_id)
            # Check if target dept has room
            dept_name = item.get("department", "")
            target_dept = _find_dept_by_name(ctx, dept_name)
            if target_dept:
                users_in_dept = [n for n in ctx.all_nodes if n.node_type == "user" and n.parent_dept_id == target_dept.id]
                slot = _find_empty_slot_in_dept(target_dept, users_in_dept)
                if slot is None:
                    # v4.1: 部门空间不足 → 不熔断，将部门加入 forced 由 layout 阶段调用 adaptive_push_v2
                    forced.add(target_dept.id)
        elif nt == "dept" or nt == "department":
            tmp_id = item.get("tmp_id", "")
            if tmp_id:
                forced.add(tmp_id)

    # ── Moves (cross-dept) ──
    for move in delta.get("moves", []):
        person_name = move.get("person", "")
        person = _find_person_by_name(ctx, person_name)
        if person:
            forced.add(person.id)
            to_dept_name = move.get("to_dept", "")
            to_dept = _find_dept_by_name(ctx, to_dept_name)
            if to_dept:
                users_in_dept = [n for n in ctx.all_nodes if n.node_type == "user" and n.parent_dept_id == to_dept.id]
                existing = [u for u in users_in_dept if u.id != person.id]
                slot = _find_empty_slot_in_dept(to_dept, existing)
                if slot is None and delta.get("scope_declaration", {}).get("allow_propagation"):
                    forced.add(to_dept.id)

    # ── Resolve tmp_ids in forced set to real node IDs ──
    resolved: set[str] = set()
    for fid in forced:
        node = ctx.nodes_by_name.get(fid) or ctx.nodes_by_id.get(fid)
        if not node:
            real_id = ctx.tmp_map.get(fid)
            if real_id:
                node = ctx.nodes_by_id.get(real_id)
        if node:
            resolved.add(node.id)

    # ── Also include new nodes whose tmp_id was empty (LLM doesn't always fill it) ──
    for item in delta.get("nodes_add", []):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if name and not item.get("tmp_id", ""):
            node = ctx.nodes_by_name.get(name)
            if node and node.x == 0 and node.y == 0:
                resolved.add(node.id)

    return resolved


def _scope_meltdown_check(forced: set[str], delta: dict[str, Any]) -> None:
    """Raise error if forced moves exceed declared scope."""
    scope = delta.get("scope_declaration", {})
    expected = scope.get("expected_affected_count", len(forced) + 10)
    allow_propagation = scope.get("allow_propagation", False)

    # When LLM declares expected_affected_count == 0 it means "I don't know" —
    # skip the meltdown check rather than reject any non-zero forced move.
    if expected == 0:
        return

    if len(forced) > expected * 2:
        raise ValueError(
            f"变更范围超出预期：预计 {expected} 节点，实际需移动 {len(forced)} 节点。"
            f"请确认操作或设置 allow_propagation=true 并重新估算 expected_affected_count。"
        )


# ═══════════════════════════════════════════════════════════
#  Layer 3: Local Layout (v4 — slot search, not global relayout)
# ═══════════════════════════════════════════════════════════

def _local_layout(ctx: MergeContext, forced: set[str], delta: dict[str, Any] | None = None) -> None:
    # v4 zero-ripple: forced empty (pure delete/update) → collision check only.
    # Never calls dept-tree reorder, auto-resize, inter-dept layout, or orphan compactify.
    id_to_node = {n.id: n for n in ctx.all_nodes}
    allow_propagation = (delta or {}).get("scope_declaration", {}).get("allow_propagation", False)

    # Build collision sets
    items = _build_bbox_items(ctx.all_nodes)
    groups = _build_rigid_groups_v2(ctx.all_nodes)
    locked_ids = {n.id for n in ctx.all_nodes if n.geometry_locked}

    # ── Place new depts ──
    for nid in list(forced):
        node = id_to_node.get(nid)
        if not node or node.node_type != "dept":
            continue
        if node.x == 0 and node.y == 0:  # New dept, needs position
            pos = _find_safe_position(items, groups, DEPT_DEFAULT_W, DEPT_DEFAULT_H, 50, 50, exclude_id=node.id)
            if pos:
                node.x, node.y = pos
            else:
                # Fallback: bottom-right corner
                all_depts = [n for n in ctx.all_nodes if n.node_type == "dept" and n.id != node.id]
                if all_depts:
                    max_x = max(d.x + d.w for d in all_depts)
                    max_y = max(d.y + d.h for d in all_depts)
                    node.x = max_x + FALLBACK_NEW_DEPT_OFFSET
                    node.y = max_y + FALLBACK_NEW_DEPT_OFFSET
                else:
                    node.x, node.y = 50, 50
            node.w, node.h = DEPT_DEFAULT_W, DEPT_DEFAULT_H

    # ── Place new users ──
    # Sort: nodes without pid (leaders) first, then subordinates.
    # This ensures superiors have their final position before subordinates reference them.
    _forced_users = [
        (nid, id_to_node[nid]) for nid in forced
        if id_to_node.get(nid) and id_to_node[nid].node_type == "user"
    ]
    _forced_users.sort(key=lambda x: 0 if not x[1].pid else 1)
    for nid, node in _forced_users:
        if node.x == 0 and node.y == 0:
            # ── Tree placement: if reports_to is set, place relative to superior ──
            superior = None
            if node.pid:
                superior = id_to_node.get(node.pid)
            _diag_sup_id = superior.id if superior else "None"
            _diag_existing = len([
                n for n in ctx.all_nodes
                if n.node_type == "user" and n.pid == _diag_sup_id
            ]) if superior else 0
            logger.info(
                "[DIAG] _local_layout user: %s pid=%s superior=%s has_superior=%s existing_subs=%d",
                node.name,
                node.pid[-8:] if node.pid else "",
                superior.name if superior else "None",
                bool(superior),
                _diag_existing,
            )
            if superior:
                # Resolve parent_dept_id from superior if not already set
                if not node.parent_dept_id and superior.parent_dept_id:
                    node.parent_dept_id = superior.parent_dept_id
                    node.department = superior.department

                # Get existing direct subordinates of this superior
                existing_subs = [
                    n for n in ctx.all_nodes
                    if n.node_type == "user" and n.pid == superior.id and n.id != node.id
                    and not (n.x == 0 and n.y == 0)   # exclude unplaced nodes
                ]

                if not existing_subs:
                    # No existing subordinates: place directly below superior
                    target_x = superior.x
                    target_y = superior.y + PERSON_H + _LEVEL_GAP_V
                else:
                    # Has existing subordinates: append to the right of rightmost
                    rightmost = max(existing_subs, key=lambda u: u.x)
                    target_x = rightmost.x + PERSON_W + _SIBLING_GAP_H
                    target_y = rightmost.y  # same row

                # Collision check at target position (skip self and parent dept)
                target_bbox = (target_x, target_y, target_x + PERSON_W, target_y + PERSON_H)
                parent_dept_id = node.parent_dept_id or superior.parent_dept_id
                conflict = False
                for n in ctx.all_nodes:
                    if n.id == node.id:
                        continue
                    if n.id == parent_dept_id:  # user inside its own dept is expected
                        continue
                    nw = n.w if n.node_type == "dept" else PERSON_W
                    nh = n.h if n.node_type == "dept" else PERSON_H
                    nb = (n.x, n.y, n.x + nw, n.y + nh)
                    if _rects_overlap(target_bbox, nb):
                        conflict = True
                        break

                # ── CAPACITY_DIAG: 容量判定诊断 ──
                _dept_check = _find_dept_for_user(node, ctx)
                if _dept_check:
                    dept_bbox = (_dept_check.x, _dept_check.y, _dept_check.w, _dept_check.h)
                    dept_inner_bottom = _dept_check.y + _dept_check.h - DEPT_PAD_BOTTOM
                    diag_lines = [
                        f"[CAPACITY_DIAG] dept={_dept_check.name}",
                        f"  dept_bbox = ({_dept_check.x}, {_dept_check.y}, {_dept_check.w}, {_dept_check.h})",
                        f"  dept_inner_bottom = {dept_inner_bottom}",
                        f"  existing_users ({len(existing_subs)}):",
                    ]
                    for uu in existing_subs:
                        ub = (uu.x, uu.y, uu.x + PERSON_W, uu.y + PERSON_H)
                        diag_lines.append(f"    {uu.name}: bbox=({ub[0]},{ub[1]},{ub[2]},{ub[3]}), bottom={ub[3]}")
                    diag_lines.extend([
                        f"  superior={superior.name}: bbox=({superior.x},{superior.y},{superior.x+PERSON_W},{superior.y+PERSON_H})",
                        f"  new_user {node.name}:",
                        f"    target_position = ({target_x}, {target_y})",
                        f"    bbox = ({target_x}, {target_y}, {target_x+PERSON_W}, {target_y+PERSON_H})",
                        f"    top = {target_y}",
                        f"    bottom = {target_y+PERSON_H}",
                        f"  containment_check:",
                        f"    top_inside = target_y >= {_dept_check.y}+DEPT_PAD_TOP? → {target_y >= _dept_check.y + DEPT_PAD_TOP}",
                        f"    bottom_inside = bottom <= {dept_inner_bottom}? → {target_y+PERSON_H <= dept_inner_bottom}",
                        f"    left_inside = target_x >= {_dept_check.x}+DEPT_PAD_LEFT? → {target_x >= _dept_check.x + DEPT_PAD_LEFT}",
                        f"    right_inside = right <= {_dept_check.x+_dept_check.w-DEPT_PAD_RIGHT}? → {target_x+PERSON_W <= _dept_check.x + _dept_check.w - DEPT_PAD_RIGHT}",
                        f"    fully_fits = {target_x >= _dept_check.x + DEPT_PAD_LEFT and target_y >= _dept_check.y + DEPT_PAD_TOP and target_x+PERSON_W <= _dept_check.x + _dept_check.w - DEPT_PAD_RIGHT and target_y+PERSON_H <= dept_inner_bottom}",
                    ])
                    logger.info("\\n".join(diag_lines))

                # ── Place user at target (unified: always check dept bounds) ──
                node.x, node.y = target_x, target_y
                node.w, node.h = PERSON_W, PERSON_H
                logger.info(
                    "[DIAG] _local_layout placed (superior path): %s → (%.0f, %.0f)",
                    node.name, target_x, target_y,
                )

                # Always check dept capacity regardless of conflict
                dept = _find_dept_for_user(node, ctx)
                if dept:
                    user_bbox = (target_x, target_y, target_x + PERSON_W, target_y + PERSON_H)
                    if not _fits_in_dept(user_bbox, dept):
                        old_w, old_h = dept.w, dept.h
                        _expand_dept_for_user(user_bbox, dept)
                        logger.info(
                            "[CAPACITY_FIX] dept=%s resized: w %d→%d, h %d→%d, "
                            "reason=%s, conflict=%s",
                            dept.name, old_w, dept.w, old_h, dept.h,
                            "overflow" if conflict else "no-conflict-overflow",
                            conflict,
                        )

                continue

            dept = _find_dept_for_user(node, ctx)
            if dept:
                users_in = [n for n in ctx.all_nodes if n.node_type == "user" and n.parent_dept_id == dept.id and n.id != node.id]
                slot = _find_empty_slot_in_dept(dept, users_in)
                if slot:
                    node.x, node.y = slot
                else:
                    # v4.1: 部门不足 → 始终自动扩展，不熔断
                    dept.h += PERSON_H + MIN_GAP_BETWEEN_USERS
                    node.x = dept.x + DEPT_PAD_LEFT
                    node.y = dept.y + dept.h - PERSON_H - DEPT_PAD_BOTTOM
                    # Rebuild and re-check collisions via adaptive_push_v2
                    items = _build_bbox_items(ctx.all_nodes)
                    groups = _build_rigid_groups_v2(ctx.all_nodes)
                    collisions = _check_collision(items, groups, locked_ids)
                    if collisions:
                        for c in collisions:
                            conflict_groups = [g for g in groups if g.dept.id in (c[0], c[1])]
                            for g in conflict_groups:
                                if g.dept.id != dept.id:
                                    _push_group_right(g, MIN_GAP_BETWEEN_DEPTS)
            else:
                # Orphan: find safe position
                pos = _find_safe_position(items, groups, PERSON_W, PERSON_H, 50,
                                          max((n.y + PERSON_H for n in ctx.all_nodes), default=50) + 50,
                                          exclude_id=node.id)
                if pos:
                    node.x, node.y = pos
                else:
                    node.x = 50
                    node.y = max((n.y + (n.h if n.node_type == "dept" else PERSON_H) for n in ctx.all_nodes), default=50) + 100
            node.w, node.h = PERSON_W, PERSON_H

    # ── Handle moves (cross-dept) ──
    for move in (delta or {}).get("moves", []):
        person_name = move.get("person", "")
        to_dept_name = move.get("to_dept", "")
        person = _find_person_by_name(ctx, person_name)
        to_dept = _find_dept_by_name(ctx, to_dept_name)
        if person and to_dept:
            person.department = to_dept.name
            person.parent_dept_id = to_dept.id
            # Re-place in new dept
            users_in = [n for n in ctx.all_nodes if n.node_type == "user" and n.parent_dept_id == to_dept.id and n.id != person.id]
            slot = _find_empty_slot_in_dept(to_dept, users_in)
            if slot:
                person.x, person.y = slot
            else:
                # v4.1: 部门空间不足 → 始终自动扩展
                to_dept.h += PERSON_H + MIN_GAP_BETWEEN_USERS
                person.x = to_dept.x + DEPT_PAD_LEFT
                person.y = to_dept.y + to_dept.h - PERSON_H - DEPT_PAD_BOTTOM

    # ── Post-layout collision check ──
    items = _build_bbox_items(ctx.all_nodes)
    groups = _build_rigid_groups_v2(ctx.all_nodes)
    collisions = _check_collision(items, groups, locked_ids)
    if collisions:
        names: dict[str, str] = {n.id: n.name for n in ctx.all_nodes}
        details = "; ".join(f"{names.get(a,'?')} vs {names.get(b,'?')}: {r}" for a, b, r in collisions[:3])
        if allow_propagation:
            logger.warning("v4 layout has %d collisions (propagation allowed): %s", len(collisions), details)
        else:
            raise ValueError(f"布局冲突 ({len(collisions)}处): {details}。请设置 allow_propagation=true 或整理部门。")

    # ── Compute edge ports ──
    _compute_edge_ports(ctx.edges, id_to_node)


def _post_submit_verify(before_items: list[BBoxItem]) -> None:
    """Post-submit: verify no collisions in the submitted state.

    Route B: non-fatal. The harness may have failed to capture a screenshot
    (leaving nodes at origin) or the LLM may have skipped layout calls, so
    post-commit collisions are expected. Log and continue — the LLM will
    fix layout in the next session.
    """
    collisions = _check_collision(before_items, [])
    if collisions:
        logger.warning(
            "POST_COMMIT_COLLISION: %d conflicts detected after submit. "
            "Continuing in Route B (LLM will fix in next session).",
            len(collisions),
        )


def _find_empty_slot_in_dept(
    dept: PowerNode,
    users_in_dept: list[PowerNode],
) -> tuple[float, float] | None:
    """Find an empty position inside a dept. Excludes geometry_locked users."""
    # Filter out locked users (they don't occupy dept space conceptually)
    unlocked_users = [u for u in users_in_dept if not u.geometry_locked]
    occupied: list[tuple[float, float, float, float]] = [
        (u.x, u.y, u.x + PERSON_W, u.y + PERSON_H) for u in unlocked_users
    ]

    x_start = dept.x + DEPT_PAD_LEFT
    y_start = dept.y + DEPT_PAD_TOP
    x_end = dept.x + dept.w - DEPT_PAD_RIGHT
    y_end = dept.y + dept.h - DEPT_PAD_BOTTOM

    y = y_start
    while y + PERSON_H <= y_end:
        x = x_start
        while x + PERSON_W <= x_end:
            collides = False
            for ox1, oy1, ox2, oy2 in occupied:
                if x < ox2 and x + PERSON_W > ox1 and y < oy2 and y + PERSON_H > oy1:
                    collides = True
                    x = ox2 + MIN_GAP_BETWEEN_USERS
                    break
            if not collides:
                    return (x, y)
        y += SLOT_SEARCH_STEP

    return None


def _fits_in_dept(
    user_bbox: tuple[float, float, float, float],
    dept: PowerNode,
) -> bool:
    """Check if user_bbox (x1,y1,x2,y2) fully fits inside dept's inner bounds.

    All four edges must be inside the dept's padded boundary (DEPT_PAD_LEFT/RIGHT/TOP/BOTTOM).
    """
    ux1, uy1, ux2, uy2 = user_bbox
    return (
        ux1 >= dept.x + DEPT_PAD_LEFT
        and uy1 >= dept.y + DEPT_PAD_TOP
        and ux2 <= dept.x + dept.w - DEPT_PAD_RIGHT
        and uy2 <= dept.y + dept.h - DEPT_PAD_BOTTOM
    )


def _expand_dept_for_user(
    user_bbox: tuple[float, float, float, float],
    dept: PowerNode,
) -> bool:
    """Expand dept to contain user_bbox (with padding). Returns True if expanded."""
    _, _, ux2, uy2 = user_bbox
    expanded = False
    needed_right = ux2 + DEPT_PAD_RIGHT
    needed_bottom = uy2 + DEPT_PAD_BOTTOM
    if needed_right > dept.x + dept.w:
        dept.w = needed_right - dept.x + MIN_GAP_BETWEEN_USERS
        expanded = True
    if needed_bottom > dept.y + dept.h:
        dept.h = needed_bottom - dept.y + MIN_GAP_BETWEEN_USERS
        expanded = True
    return expanded


def _find_safe_dept_position(ctx: MergeContext) -> tuple[float, float] | None:
    """Find a safe position for a new department using full collision detection."""
    items = _build_bbox_items(ctx.all_nodes)
    groups = _build_rigid_groups_v2(ctx.all_nodes)
    return _find_safe_position(items, groups, DEPT_DEFAULT_W, DEPT_DEFAULT_H, 50, 50)


def _find_orphan_slot(ctx: MergeContext) -> tuple[float, float]:
    """Find a position for an orphan user (bottom-right of all existing content)."""
    all_nodes = ctx.all_nodes
    if not all_nodes:
        return (50, 50)
    max_x = max(n.x + (n.w if n.node_type == "dept" else PERSON_W) for n in all_nodes)
    max_y = max(n.y + (n.h if n.node_type == "dept" else PERSON_H) for n in all_nodes)
    orphan_users = [n for n in all_nodes if n.node_type == "user" and not n.parent_dept_id]
    if orphan_users:
        col = len(orphan_users) % 8
        row = len(orphan_users) // 8
        return (50 + col * (PERSON_W + MIN_GAP_BETWEEN_USERS), max_y + row * (PERSON_H + MIN_GAP_BETWEEN_USERS) + 50)
    return (50, max_y + 50)


def _rects_overlap(r1: tuple, r2: tuple) -> bool:
    """Check if two AABB rectangles overlap."""
    return not (r1[2] <= r2[0] or r1[0] >= r2[2] or r1[3] <= r2[1] or r1[1] >= r2[3])


def _rects_overlap_area(r1: tuple, r2: tuple) -> float:
    """Compute overlap area of two AABB rectangles."""
    x_overlap = max(0, min(r1[2], r2[2]) - max(r1[0], r2[0]))
    y_overlap = max(0, min(r1[3], r2[3]) - max(r1[1], r2[1]))
    return x_overlap * y_overlap


def _find_dept_by_name(ctx: MergeContext, name: str) -> PowerNode | None:
    """Find a dept node by name (case-insensitive)."""
    name_lower = name.strip().lower()
    for n in ctx.all_nodes:
        if n.node_type == "dept" and n.name.strip().lower() == name_lower:
            return n
    return None


def _find_person_by_name(ctx: MergeContext, name: str) -> PowerNode | None:
    """Find a person node by name (case-insensitive)."""
    name_lower = name.strip().lower()
    for n in ctx.all_nodes:
        if n.node_type == "user" and n.name.strip().lower() == name_lower:
            return n
    return None


def _find_dept_for_user(user: PowerNode, ctx: MergeContext) -> PowerNode | None:
    """Find the department a user belongs to."""
    if user.parent_dept_id:
        for n in ctx.all_nodes:
            if n.node_type == "dept" and n.id == user.parent_dept_id:
                return n
    if user.department:
        return _find_dept_by_name(ctx, user.department)
    return None


def _find_node_by_name(ctx: MergeContext, name: str) -> PowerNode | None:
    """Find a user or dept node by name (case-insensitive). Dept takes precedence on ties."""
    if not name:
        return None
    target = name.strip().lower()
    if not target:
        return None
    user_hit: PowerNode | None = None
    for n in ctx.all_nodes:
        if n.name.strip().lower() != target:
            continue
        if n.node_type == "dept":
            return n
        if user_hit is None:
            user_hit = n
    return user_hit


def _find_user_by_name(ctx: MergeContext, name: str) -> PowerNode | None:
    """Find a user node by name (case-insensitive). Alias for clarity in harness tools."""
    return _find_person_by_name(ctx, name)


def _node_bbox_size(node: PowerNode) -> tuple[float, float]:
    """Return (w, h) for collision purposes. Users use PERSON_W/PERSON_H, depts use stored dims."""
    if node.node_type == "user":
        return (float(PERSON_W), float(PERSON_H))
    w = float(node.w) if node.w else float(DEPT_DEFAULT_W)
    h = float(node.h) if node.h else float(DEPT_DEFAULT_H)
    return (w, h)


def _find_free_position(
    ctx: MergeContext,
    w: float,
    h: float,
    parent_id: str | None = None,
) -> tuple[float, float, str | None]:
    """Find a non-overlapping (x, y) for a new node of size (w, h).

    With parent_id (person dropping into a container): scan the parent's
    inner region on a 50px grid, requiring 10px gap from existing siblings.
    Without parent_id (top-level): scan the (0,0)-(4000,3000) canvas on a
    100px grid, requiring 50px gap from existing top-level nodes.

    Returns (x, y, warning). warning is None on success, or
    "auto_placed_with_overflow" if the scan exhausted and a fallback slot
    (parent's bottom-right / canvas right edge) was used.
    """
    parent_node: PowerNode | None = None
    pid = (parent_id or "").strip()
    if pid:
        candidate = ctx.nodes_by_id.get(pid)
        if candidate is not None and candidate.node_type == "dept":
            parent_node = candidate

    if parent_node is not None:
        inner_gap = 10.0
        step = 50.0
        avail_left = parent_node.x + DEPT_PAD_LEFT
        avail_top = parent_node.y + DEPT_PAD_TOP
        avail_right = parent_node.x + parent_node.w - DEPT_PAD_RIGHT
        avail_bottom = parent_node.y + parent_node.h - DEPT_PAD_BOTTOM

        sibling_rects: list[tuple[float, float, float, float]] = []
        for n in ctx.all_nodes:
            if n.parent_dept_id != parent_node.id:
                continue
            sw, sh = _node_bbox_size(n)
            sibling_rects.append((n.x, n.y, n.x + sw, n.y + sh))

        _existing_preview_p = [(int(r[0]), int(r[1])) for r in sibling_rects[:10]]
        logger.info(
            "[DEBUG-J] 7b.FREE_POS_IN w=%.1f h=%.1f parent_id=%s existing_count=%d existing_preview=%s",
            float(w), float(h), pid, len(sibling_rects), _existing_preview_p,
        )

        _scan_iters_p = 0
        y = avail_top
        while y + h <= avail_bottom:
            x = avail_left
            while x + w <= avail_right:
                _scan_iters_p += 1
                cand = (
                    x - inner_gap,
                    y - inner_gap,
                    x + w + inner_gap,
                    y + h + inner_gap,
                )
                if not any(_rects_overlap(cand, r) for r in sibling_rects):
                    logger.info(
                        "[DEBUG-J] 7b.FREE_POS_OUT x=%.1f y=%.1f scan_iters=%d warning=%s",
                        float(x), float(y), _scan_iters_p, None,
                    )
                    return (float(x), float(y), None)
                x += step
            y += step

        # fallback: 按 existing_count 纵向堆叠，避免全部压在同一个点
        fallback_x = float(parent_node.x + DEPT_PAD_LEFT)
        fallback_y = float(parent_node.y + DEPT_PAD_TOP + len(sibling_rects) * (h + 20.0))
        warning = "auto_placed_with_overflow"
        if warning and parent_node is not None:
            # fallback_x/y are absolute canvas coords; parent_node.w/h are sizes.
            # Must subtract parent origin to get the child's local offset before
            # comparing against the parent's width/height (otherwise the parent
            # gets inflated to roughly its absolute right-edge coordinate).
            new_w = max(parent_node.w, (fallback_x - parent_node.x) + w + DEPT_PAD_RIGHT)
            new_h = max(parent_node.h, (fallback_y - parent_node.y) + h + DEPT_PAD_BOTTOM)
            if new_w != parent_node.w or new_h != parent_node.h:
                logger.info(
                    "[DEBUG-J parent_resize] parent_id=%s old=(%.0f,%.0f) new=(%.0f,%.0f) child=%s",
                    parent_node.id, parent_node.w, parent_node.h, new_w, new_h, f"{w:.0f}x{h:.0f}",
                )
                parent_node.w = new_w
                parent_node.h = new_h
        logger.info(
            "[DEBUG-J] 7b.FREE_POS_OUT x=%.1f y=%.1f scan_iters=%d warning=%s",
            fallback_x, fallback_y, _scan_iters_p, warning,
        )
        return (fallback_x, fallback_y, warning)

    outer_gap = 50.0
    step = 100.0
    canvas_w = 4000.0
    canvas_h = 3000.0

    top_rects: list[tuple[float, float, float, float]] = []
    for n in ctx.all_nodes:
        if n.parent_dept_id:
            continue
        nw, nh = _node_bbox_size(n)
        top_rects.append((n.x, n.y, n.x + nw, n.y + nh))

    _existing_preview_t = [(int(r[0]), int(r[1])) for r in top_rects[:10]]
    logger.info(
        "[DEBUG-J] 7b.FREE_POS_IN w=%.1f h=%.1f parent_id=%s existing_count=%d existing_preview=%s",
        float(w), float(h), pid, len(top_rects), _existing_preview_t,
    )

    _scan_iters_t = 0
    y = 0.0
    while y + h <= canvas_h:
        x = 0.0
        while x + w <= canvas_w:
            _scan_iters_t += 1
            cand = (
                x - outer_gap,
                y - outer_gap,
                x + w + outer_gap,
                y + h + outer_gap,
            )
            if not any(_rects_overlap(cand, r) for r in top_rects):
                logger.info(
                    "[DEBUG-J] 7b.FREE_POS_OUT x=%.1f y=%.1f scan_iters=%d warning=%s",
                    float(x), float(y), _scan_iters_t, None,
                )
                return (float(x), float(y), None)
            x += step
        y += step

    # fallback: 右侧纵向追加
    fallback_x = float(len(top_rects) * (w + outer_gap))
    logger.info(
        "[DEBUG-J] 7b.FREE_POS_OUT x=%.1f y=%.1f scan_iters=%d warning=%s",
        fallback_x, 0.0, _scan_iters_t, "auto_placed_with_overflow",
    )
    return (fallback_x, 0.0, "auto_placed_with_overflow")


def _resolve_reference_bbox(
    ctx: MergeContext, reference: str
) -> tuple[float, float, float, float] | None:
    """Return (x, y, w, h) for the named reference. Tries dept first, then user."""
    if not reference:
        return None
    dept = _find_dept_by_name(ctx, reference)
    if dept:
        w, h = _node_bbox_size(dept)
        return (float(dept.x), float(dept.y), w, h)
    user = _find_user_by_name(ctx, reference)
    if user:
        return (float(user.x), float(user.y), float(PERSON_W), float(PERSON_H))
    return None


def _compute_position_xy(
    bbox: tuple[float, float, float, float], position: str
) -> tuple[float, float]:
    """Compute (x, y) coordinates for a PERSON_W×PERSON_H card at a semantic position."""
    x, y, w, h = bbox
    pad = 20.0
    pw = float(PERSON_W)
    ph = float(PERSON_H)
    positions = {
        "top-left": (x + pad, y + pad),
        "top": (x + w / 2 - pw / 2, y + pad),
        "top-right": (x + w - pad - pw, y + pad),
        "left": (x + pad, y + h / 2 - ph / 2),
        "center": (x + w / 2 - pw / 2, y + h / 2 - ph / 2),
        "right": (x + w - pad - pw, y + h / 2 - ph / 2),
        "bottom-left": (x + pad, y + h - pad - ph),
        "bottom": (x + w / 2 - pw / 2, y + h - pad - ph),
        "bottom-right": (x + w - pad - pw, y + h - pad - ph),
    }
    return positions.get(position, positions["center"])


def _check_collide_single(ctx: MergeContext, node: PowerNode) -> list[dict[str, Any]]:
    """Return overlapping nodes for the given node (self + own parent dept excluded)."""
    if node is None:
        return []
    nw, nh = _node_bbox_size(node)
    a_rect = (node.x, node.y, node.x + nw, node.y + nh)
    out: list[dict[str, Any]] = []
    for other in ctx.all_nodes:
        if other is node or other.id == node.id:
            continue
        ow, oh = _node_bbox_size(other)
        b_rect = (other.x, other.y, other.x + ow, other.y + oh)
        if not _rects_overlap(a_rect, b_rect):
            continue
        # user inside its own parent dept is expected, not a collision
        if node.node_type == "user" and other.node_type == "dept" and node.parent_dept_id == other.id:
            continue
        if node.node_type == "dept" and other.node_type == "user" and other.parent_dept_id == node.id:
            continue
        out.append({"id": other.id, "name": other.name, "type": other.node_type})
    return out


# ═══════════════════════════════════════════════════════════
#  v3.1 Fallback: Structure Derivation (kept for relayout mode C)
# ═══════════════════════════════════════════════════════════

def _build_dept_forest(
    dept_id: str,
    persons: list[PowerNode],
) -> list[PowerNode]:
    """Build a reporting forest within a department.

    Returns list of root nodes (in-degree 0).
    Each node gets children_ids and parent_id populated.
    Detects and breaks cycles.
    """
    if not persons:
        return []

    person_ids = {p.id for p in persons}
    id_to_person = {p.id: p for p in persons}

    # Reset layout state
    for p in persons:
        p.children_ids = []
        p.parent_id = ""
        p.depth = 0

    # Build children lists (only for pids within the same dept)
    in_degree: dict[str, int] = {p.id: 0 for p in persons}
    for p in persons:
        if p.pid and p.pid in person_ids and p.pid != p.id:
            parent = id_to_person[p.pid]
            parent.children_ids.append(p.id)
            in_degree[p.id] = in_degree.get(p.id, 0) + 1

    # Cycle detection with DFS
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {p.id: WHITE for p in persons}

    def _dfs_cycle(u: PowerNode) -> list[tuple[str, str]]:
        """Return list of back edges found."""
        back_edges: list[tuple[str, str]] = []
        color[u.id] = GRAY
        for cid in list(u.children_ids):
            if cid not in color:
                continue
            if color[cid] == GRAY:
                back_edges.append((u.id, cid))
            elif color[cid] == WHITE:
                child = id_to_person.get(cid)
                if child:
                    back_edges.extend(_dfs_cycle(child))
        color[u.id] = BLACK
        return back_edges

    for p in persons:
        if color[p.id] == WHITE:
            back_edges = _dfs_cycle(p)
            for parent_id, child_id in back_edges:
                # Break cycle by removing the edge
                parent_node = id_to_person.get(parent_id)
                if parent_node and child_id in parent_node.children_ids:
                    parent_node.children_ids.remove(child_id)
                    in_degree[child_id] = max(0, in_degree.get(child_id, 1) - 1)
                    logger.warning("Cycle detected: %s → %s, breaking edge", parent_id, child_id)

    # Collect roots (in-degree 0 or pid points outside department)
    roots: list[PowerNode] = []
    for p in persons:
        if in_degree.get(p.id, 0) == 0:
            roots.append(p)
        else:
            # Check if pid is outside this department
            pid_owner = id_to_person.get(p.pid)
            if pid_owner is None:
                roots.append(p)
                p.pid = ""  # Clear unresolvable pid

    # BFS to set depth and parent_id
    from collections import deque
    visited: set[str] = set()
    for root in roots:
        root.depth = 0
        root.parent_id = ""
        q = deque([root])
        visited.add(root.id)
        while q:
            u = q.popleft()
            for cid in u.children_ids:
                if cid in visited:
                    continue
                child = id_to_person.get(cid)
                if child:
                    child.depth = u.depth + 1
                    child.parent_id = u.id
                    visited.add(cid)
                    q.append(child)

    # Orphan nodes (not visited in BFS) → attach to virtual root
    for p in persons:
        if p.id not in visited:
            p.depth = 0
            p.parent_id = ""
            p.children_ids = []
            roots.append(p)
            logger.warning("Orphan node %s attached as root", p.name)

    return roots


# ═══════════════════════════════════════════════════════════
#  v4 Diagnostic Utilities (temporary — remove after debugging)
# ═══════════════════════════════════════════════════════════

def diag_layer1_geometry(ctx: MergeContext) -> None:
    """[Layer1] Print geometry 归属 for each user."""
    dept_nodes = [n for n in ctx.all_nodes if n.node_type == "dept"]
    print("\n===== [Layer1] 几何归属检测 =====")
    for n in ctx.all_nodes:
        if n.node_type != "user":
            continue
        dept_match = None
        for d in dept_nodes:
            if (n.x >= d.x and n.y >= d.y
                    and n.x + PERSON_W <= d.x + d.w
                    and n.y + PERSON_H <= d.y + d.h):
                dept_match = d.name
                break
        print(f"[Layer1] user={n.name} id={n.id} parent_dept_id='{n.parent_dept_id}' "
              f"bbox=({n.x},{n.y},{n.w},{n.h}) dept_match={dept_match}")


def diag_layer1_dirty(ctx: MergeContext) -> None:
    """[Layer1-DIRTY] Print distinct parent_dept_id values across all users."""
    vals: set[str] = set()
    for n in ctx.all_nodes:
        if n.node_type == "user":
            vals.add(n.parent_dept_id)
    sorted_vals = sorted(vals, key=lambda v: (v == "", v))
    print("\n===== [Layer1-DIRTY] distinct parent_dept_id values =====")
    print(f"[Layer1-DIRTY] distinct parent_dept_id values: {sorted_vals}")


def diag_layer1_dept(ctx: MergeContext) -> None:
    """[Layer1-DEPT] Print each dept's user_count and size."""
    dept_user_count: dict[str, int] = {}
    for n in ctx.all_nodes:
        if n.node_type == "dept":
            dept_user_count[n.id] = 0
    for n in ctx.all_nodes:
        if n.node_type == "user" and n.parent_dept_id in dept_user_count:
            dept_user_count[n.parent_dept_id] += 1

    print("\n===== [Layer1-DEPT] 空部门检测 =====")
    for n in ctx.all_nodes:
        if n.node_type == "dept":
            count = dept_user_count.get(n.id, 0)
            print(f"[Layer1-DEPT] dept={n.name} user_count={count} size=({n.w},{n.h})")


def diag_layer2_forest(ctx: MergeContext) -> None:
    """[Layer2] Print dept-user assignment and forest-building info (v4 equivalent)."""
    # Group users by parent_dept_id
    dept_users: dict[str, list[PowerNode]] = {}
    dept_by_id: dict[str, PowerNode] = {}
    for n in ctx.all_nodes:
        if n.node_type == "dept":
            dept_users[n.id] = []
            dept_by_id[n.id] = n
    orphan_users: list[PowerNode] = []
    for n in ctx.all_nodes:
        if n.node_type == "user":
            if n.parent_dept_id and n.parent_dept_id in dept_users:
                dept_users[n.parent_dept_id].append(n)
            else:
                orphan_users.append(n)

    print("\n===== [Layer2] 边/森林构建 =====")
    for n in ctx.all_nodes:
        if n.node_type != "dept":
            continue
        users = dept_users.get(n.id, [])
        user_names = [u.name for u in users]
        # Count edges where both source and target are inside this dept's users
        user_ids = {u.id for u in users}
        internal_edges = sum(
            1 for e in ctx.edges
            if str(e.get("source_id", "")) in user_ids
            and str(e.get("target_id", "")) in user_ids
        )
        # Count edges where at least one endpoint is in this dept
        related_edges = sum(
            1 for e in ctx.edges
            if str(e.get("source_id", "")) in user_ids
            or str(e.get("target_id", "")) in user_ids
        )
        # Build forest to get roots/orphans (deep copy to avoid mutating originals)
        import copy as _copy
        users_copy = [_copy.copy(u) for u in users]
        id_map_copy = {u.id: u for u in users_copy}
        forest_roots = _build_dept_forest(n.id, users_copy)
        visited_in_bfs: set[str] = set()
        for u in users_copy:
            if u.depth >= 0 or u.parent_id:
                visited_in_bfs.add(u.id)
        orphan_count = len([u for u in users_copy if u.id not in visited_in_bfs])
        print(f"[Layer2] dept={n.name} internal_users={user_names} "
              f"count={len(users)} edges_internal={internal_edges} "
              f"edges_related={related_edges} orphans={orphan_count} "
              f"roots={len(forest_roots)}")

    # Print orphan users (no parent_dept_id or parent_dept_id not matching any dept)
    if orphan_users:
        orphan_names = [u.name for u in orphan_users]
        print(f"[Layer2-ORPHAN] orphan_users (no dept match): {orphan_names} "
              f"count={len(orphan_users)}")


# ═══════════════════════════════════════════════════════════
#  Layer 3: Geometry — Reingold-Tilford Compact Tree
# ═══════════════════════════════════════════════════════════

@dataclass
class _TreeLayout:
    """Temporary layout state for tree nodes."""
    x_local: float = 0.0
    x_offset: float = 0.0
    y: float = 0.0
    children: list[_TreeLayout] = field(default_factory=list)
    node: PowerNode | None = None
    left_contour: list[float] = field(default_factory=list)
    right_contour: list[float] = field(default_factory=list)


def _rt_layout_forest(
    roots: list[PowerNode],
    id_to_node: dict[str, PowerNode],
) -> dict[str, tuple[float, float]]:
    """Reingold-Tilford layout for a forest of trees.

    Returns dict: node_id → (x_local, y).
    y = depth * (PERSON_H + _LEVEL_GAP_V).
    """
    if not roots:
        return {}

    def _build_tlayout(node: PowerNode) -> _TreeLayout:
        tl = _TreeLayout(node=node)
        for cid in node.children_ids:
            child = id_to_node.get(cid)
            if child:
                tl.children.append(_build_tlayout(child))
        return tl

    trees = [_build_tlayout(r) for r in roots]

    def _setup(tl: _TreeLayout, depth: int) -> None:
        tl.y = depth * (PERSON_H + _LEVEL_GAP_V)
        for child in tl.children:
            _setup(child, depth + 1)

    def _postorder(tl: _TreeLayout) -> None:
        for child in tl.children:
            _postorder(child)

        if not tl.children:
            tl.x_local = 0.0
            tl.left_contour = [0.0]
            tl.right_contour = [PERSON_W]
        else:
            # Position subtrees
            _arrange_subtrees(tl)
            first = tl.children[0]
            last = tl.children[-1]
            tl.x_local = (first.x_local + first.x_offset + last.x_local + last.x_offset) / 2.0
            # Build contours
            tl.left_contour = [tl.x_local]
            tl.right_contour = [tl.x_local + PERSON_W]
            max_depth = max(len(c.left_contour) for c in tl.children)
            for d in range(max_depth):
                left_vals = []
                right_vals = []
                for c in tl.children:
                    if d < len(c.left_contour):
                        left_vals.append(c.x_offset + c.left_contour[d])
                    if d < len(c.right_contour):
                        right_vals.append(c.x_offset + c.right_contour[d])
                if left_vals:
                    tl.left_contour.append(min(left_vals))
                if right_vals:
                    tl.right_contour.append(max(right_vals))

    def _arrange_subtrees(tl: _TreeLayout) -> None:
        """Position children with gap detection."""
        if len(tl.children) <= 1:
            for c in tl.children:
                c.x_offset = 0.0
            return

        # Start with first child at 0
        tl.children[0].x_offset = 0.0

        for i in range(1, len(tl.children)):
            left_tree = tl.children[i - 1]
            right_tree = tl.children[i]

            # Find minimum separation
            min_sep = _SIBLING_GAP_H
            max_depth = min(len(left_tree.right_contour), len(right_tree.left_contour))
            for d in range(max_depth):
                gap = (right_tree.x_offset + right_tree.left_contour[d]) - \
                      (left_tree.x_offset + left_tree.right_contour[d])
                needed = _SUBTREE_GAP_H - gap
                if needed > min_sep:
                    min_sep = needed

            right_tree.x_offset = left_tree.x_offset + min_sep

    def _preorder(tl: _TreeLayout, x_accum: float) -> None:
        tl.x_offset += x_accum
        for child in tl.children:
            _preorder(child, tl.x_offset)

    # Layout
    for tree in trees:
        _setup(tree, 0)
        _postorder(tree)

    # Calculate initial positions for roots
    if len(trees) > 1:
        # Position roots side by side
        x_cursor = 0.0
        for i, tree in enumerate(trees):
            tree.x_offset = x_cursor
            # Calculate subtree width
            if tree.right_contour:
                width = max(tree.right_contour) - min(tree.left_contour)
            else:
                width = PERSON_W
            x_cursor += max(width, PERSON_W) + _SUBTREE_GAP_H

    # Propagate offsets via preorder
    for tree in trees:
        _preorder(tree, 0.0)

    # Collect results
    result: dict[str, tuple[float, float]] = {}

    def _collect(tl: _TreeLayout) -> None:
        if tl.node:
            result[tl.node.id] = (tl.x_offset + tl.x_local, tl.y)
        for child in tl.children:
            _collect(child)

    for tree in trees:
        _collect(tree)

    return result


# ═══════════════════════════════════════════════════════════
#  Layer 3: Geometry — Department & Inter-Department Layout
# ═══════════════════════════════════════════════════════════

def _v31_global_layout(
    all_nodes: list[PowerNode],
    edges: list[dict[str, Any]],
) -> None:
    """仅供 relayout mode C (全量重排核武器) 使用，禁止从增量流程 (confirm/preview) 调用。

内置 locked-node 保护：入口快照 geometry_locked 节点坐标，出口强制恢复。
Mode C 承诺保留手动调整节点位置，即使在其他节点全局重排时也不动 locked 节点。

Always relayouts everything; no user_adjusted preservation (except locked nodes which are restored).
    """
    # v4 locked-node protection (P0-2): snapshot and restore manual node positions.
    # Mode C promises to preserve geometry_locked / user_adjusted nodes per v4 spec.
    _locked_snapshot: dict[str, tuple[float, float]] = {}
    for n in all_nodes:
        if getattr(n, 'geometry_locked', False):
            _locked_snapshot[n.id] = (n.x, n.y)

    id_to_node = {n.id: n for n in all_nodes}

    # ── Group users by parent_dept_id ──
    dept_users: dict[str, list[PowerNode]] = {}
    dept_nodes: dict[str, PowerNode] = {}
    orphan_users: list[PowerNode] = []
    nested_depts: dict[str, list[PowerNode]] = {}

    # First pass: collect dept nodes
    for n in all_nodes:
        if n.node_type == "dept":
            dept_nodes[n.id] = n
            pid = n.parent_dept_id
            if pid:
                nested_depts.setdefault(pid, []).append(n)

    # Second pass: assign users (v4 three-stage: field → geometry → orphan)
    for n in all_nodes:
        if n.node_type != "user":
            continue

        # Stage 1: field-based (non-empty parent_dept_id → direct, no geometry check)
        if n.parent_dept_id and n.parent_dept_id in dept_nodes:
            dept_users.setdefault(n.parent_dept_id, []).append(n)
            continue

        # Stage 2: geometric fallback (loose containment — dept bbox expanded by margin)
        candidates: list[PowerNode] = []
        ux1, uy1 = n.x, n.y
        ux2, uy2 = n.x + PERSON_W, n.y + PERSON_H
        for d in dept_nodes.values():
            dx1, dy1 = d.x - GEO_EMBED_SAFE_MARGIN, d.y - GEO_EMBED_SAFE_MARGIN
            dx2, dy2 = d.x + d.w + GEO_EMBED_SAFE_MARGIN, d.y + d.h + GEO_EMBED_SAFE_MARGIN
            if ux1 >= dx1 and uy1 >= dy1 and ux2 <= dx2 and uy2 <= dy2:
                candidates.append(d)

        if candidates:
            # Multi-match tie-breaking: center-point distance → area → id
            ucx, ucy = (ux1 + ux2) / 2, (uy1 + uy2) / 2
            def _sort_key(d: PowerNode) -> tuple[float, float, str]:
                dcx, dcy = d.x + d.w / 2, d.y + d.h / 2
                dist = (ucx - dcx) ** 2 + (ucy - dcy) ** 2
                area = d.w * d.h
                return (dist, area, d.id)
            best = min(candidates, key=_sort_key)
            # Auto-fill parent_dept_id for downstream consumers
            n.parent_dept_id = best.id
            dept_users.setdefault(best.id, []).append(n)
        else:
            # Stage 3: orphan
            orphan_users.append(n)

    # ── Layout within each department ──
    for dept_id, dept in dept_nodes.items():
        users = dept_users.get(dept_id, [])
        sub_depts = nested_depts.get(dept_id, [])

        roots = _build_dept_forest(dept_id, users)
        if users:
            positions = _rt_layout_forest(roots, id_to_node)
            for uid, (lx, ly) in positions.items():
                u = id_to_node.get(uid)
                if u:
                    u.x = lx
                    u.y = ly
                    u.w = PERSON_W
                    u.h = PERSON_H

        _calc_and_set_dept_bounds(dept, users, sub_depts)
        if users:
            _v31_offset_users_in_dept(dept, users)

    # ── Inter-department layout (top-level depts only) ──
    top_depts = [d for d in dept_nodes.values() if not d.parent_dept_id]
    _v31_layout_top_depts(top_depts)

    for dept in top_depts:
        users = dept_users.get(dept.id, [])
        if users:
            _v31_offset_users_in_dept(dept, users)

    # ── Layout nested sub-departments ──
    for _parent_id, sub_depts in nested_depts.items():
        for sub in sub_depts:
            sub_users = dept_users.get(sub.id, [])
            if sub_users:
                sub_sub = nested_depts.get(sub.id, [])
                _calc_and_set_dept_bounds(sub, sub_users, sub_sub)
                _v31_offset_users_in_dept(sub, sub_users)

    # ── Orphan users ──
    _v31_layout_orphans(orphan_users, all_nodes)

    # ── Port selection on edges ──
    _compute_edge_ports(edges, id_to_node)

    # v4 locked-node protection: restore manual node positions overridden by Tree Layout.
    if _locked_snapshot:
        for nid, (lx, ly) in _locked_snapshot.items():
            node = id_to_node.get(nid)
            if node:
                node.x = lx
                node.y = ly


def _calc_and_set_dept_bounds(
    dept: PowerNode,
    users: list[PowerNode],
    sub_depts: list[PowerNode],
) -> None:
    """Calculate department size based on contained users and sub-depts."""
    if not users and not sub_depts:
        dept.w = DEPT_DEFAULT_W
        dept.h = DEPT_DEFAULT_H
        return

    min_x = float("inf")
    min_y = float("inf")
    max_x = float("-inf")
    max_y = float("-inf")

    for u in users:
        min_x = min(min_x, u.x)
        min_y = min(min_y, u.y)
        max_x = max(max_x, u.x + PERSON_W)
        max_y = max(max_y, u.y + PERSON_H)

    for sd in sub_depts:
        min_x = min(min_x, sd.x)
        min_y = min(min_y, sd.y)
        max_x = max(max_x, sd.x + sd.w)
        max_y = max(max_y, sd.y + sd.h)

    content_w = max_x - min_x if min_x != float("inf") else PERSON_W
    content_h = max_y - min_y if min_y != float("inf") else PERSON_H

    dept.w = max(DEPT_MIN_W, content_w + DEPT_PAD_LEFT + DEPT_PAD_RIGHT)
    dept.h = max(DEPT_MIN_H, content_h + DEPT_PAD_TOP + DEPT_PAD_BOTTOM)


def _v31_offset_users_in_dept(
    dept: PowerNode,
    users: list[PowerNode],
) -> None:
    """Reposition all users so the leftmost aligns with dept.x + DEPT_PAD_LEFT."""
    if not users:
        return

    min_x = min(u.x for u in users)
    min_y = min(u.y for u in users)
    offset_x = dept.x + DEPT_PAD_LEFT - min_x
    offset_y = dept.y + DEPT_PAD_TOP - min_y

    for u in users:
        u.x += offset_x
        u.y += offset_y


def _v31_layout_top_depts(top_depts: list[PowerNode]) -> None:
    """Layout all top-level departments in rows."""
    if not top_depts:
        return

    start_x = _CANVAS_ORIGIN_X + 50
    start_y = _CANVAS_ORIGIN_Y + 50

    x_cursor = start_x
    y_cursor = start_y
    row_max_h = 0.0

    for dept in top_depts:
        if x_cursor + dept.w > _CANVAS_MAX_X and x_cursor > start_x:
            x_cursor = _CANVAS_ORIGIN_X + 50
            y_cursor += row_max_h + _DEPT_GAP_V
            row_max_h = 0.0

        dept.x = x_cursor
        dept.y = y_cursor
        x_cursor += dept.w + _DEPT_GAP_H
        row_max_h = max(row_max_h, dept.h)


def _v31_layout_orphans(
    orphans: list[PowerNode],
    all_nodes: list[PowerNode],
) -> None:
    """Layout unassigned users in a grid or small trees."""
    if not orphans:
        return

    # Find starting position (to the right of rightmost department)
    max_right = _CANVAS_ORIGIN_X
    for n in all_nodes:
        if n.node_type == "dept":
            max_right = max(max_right, n.x + n.w + _DEPT_GAP_H)

    # Separate: those with pid relationships vs isolated
    has_pid = [o for o in orphans if o.pid]
    no_pid = [o for o in orphans if not o.pid]

    id_to_node = {n.id: n for n in all_nodes}

    # Small tree layout for pid-related orphans
    if has_pid:
        roots = _build_dept_forest("__orphan__", has_pid)
        positions = _rt_layout_forest(roots, id_to_node)
        for uid, (lx, ly) in positions.items():
            u = id_to_node.get(uid)
            if u:
                u.x = max_right + lx
                u.y = _CANVAS_ORIGIN_Y + 50 + ly
                u.w = PERSON_W
                u.h = PERSON_H

    # Grid layout for isolated orphans
    if no_pid:
        cols = max(1, math.floor((_CANVAS_MAX_X - max_right) / (PERSON_W + _ORPHAN_GRID_GAP)))
        for i, u in enumerate(no_pid):
            row = i // cols
            col = i % cols
            u.x = max_right + col * (PERSON_W + _ORPHAN_GRID_GAP)
            u.y = _CANVAS_ORIGIN_Y + 50 + row * (PERSON_H + _ORPHAN_GRID_GAP)
            u.w = PERSON_W
            u.h = PERSON_H


def _compute_edge_ports(
    edges: list[dict[str, Any]],
    id_to_node: dict[str, PowerNode],
) -> None:
    """Select ports for all edges based on relative node positions."""
    for e in edges:
        src_id = str(e.get("source_id", ""))
        tgt_id = str(e.get("target_id", ""))
        src = id_to_node.get(src_id)
        tgt = id_to_node.get(tgt_id)
        if not src or not tgt:
            continue

        scx = src.x + src.w / 2.0
        scy = src.y + src.h / 2.0
        tcx = tgt.x + tgt.w / 2.0
        tcy = tgt.y + tgt.h / 2.0

        dx = tcx - scx
        dy = tcy - scy
        adx = abs(dx)
        ady = abs(dy)

        if adx < _PORT_THRESHOLD and ady < _PORT_THRESHOLD:
            e["source_port"] = "port-bottom"
            e["target_port"] = "port-top"
        elif ady > adx:
            if dy > 0:
                e["source_port"] = "port-bottom"
                e["target_port"] = "port-top"
            else:
                e["source_port"] = "port-top"
                e["target_port"] = "port-bottom"
        else:
            if dx > 0:
                e["source_port"] = "port-right"
                e["target_port"] = "port-left"
            else:
                e["source_port"] = "port-left"
                e["target_port"] = "port-right"


# ═══════════════════════════════════════════════════════════
#  Layer 4: Output & Submission
# ═══════════════════════════════════════════════════════════

async def _submit_to_bi(
    cfg: SystemConfig,
    prj_id: str,
    version_id: str,
    all_nodes: list[PowerNode],
    edges: list[dict[str, Any]],
    current_user: dict[str, Any] | None = None,
    ctx: "MergeContext | None" = None,
) -> dict[str, Any]:
    """Submit the complete node/edge set to BI via upInfo."""
    api_cfg = _get_power_map_config(cfg)

    # Back-fill CRM fields on LLM-created user nodes from ctx.upinfo_users
    # (exact name match) before serialising to upInfo. No-op when ctx is
    # omitted (e.g. relayout paths that never create new users).
    if ctx is not None:
        _enrich_users_from_upinfo(ctx)

    # Resolve _parent_dept_original for newly created person nodes.
    # New nodes have parent_dept_id set but _parent_dept_original is empty
    # (it only gets populated for BI-fetched nodes). Without this, par_id
    # is empty in the upInfo payload and the BI renderer treats the person
    # as a top-level orphan — appearing at (0,0) instead of inside their dept.
    _node_by_id: dict[str, PowerNode] = {n.id: n for n in all_nodes}
    for node in all_nodes:
        if node._parent_dept_original or node.node_type != "user":
            continue
        if not node.parent_dept_id:
            continue
        parent = _node_by_id.get(node.parent_dept_id)
        if parent and parent.node_type == "dept":
            # parent.id is the correct BI reference:
            # - for existing BI depts it IS the BI-native ID
            # - for new depts it's the UUID that up_nodes will submit as that dept's id
            node._parent_dept_original = parent.id
            logger.debug("submit: resolved par_id for '%s' -> parent '%s' (%s)",
                         node.name, parent.name, parent.id)

    up_nodes = [_to_up_node(n) for n in all_nodes]

    url = f"{api_cfg['base_url']}{api_cfg['update_path']}"
    headers: dict[str, str] = {"Content-Type": "application/json"}
    cookies: dict[str, str] | None = None

    if current_user:
        try:
            cookies = await cas_auth_service.get_bi_session({
                "user_id": current_user.get("user_id", ""),
                "username": current_user.get("user_name", ""),
                "bi_service": api_cfg["base_url"],
            })
        except CasAuthError:
            pass
        except Exception:
            logger.exception("CAS auth unexpected error")

    if not cookies and api_cfg["auth_token"]:
        headers["Authorization"] = f"Bearer {api_cfg['auth_token']}"

    # Strip edge_type from edges — BI HAR has no edge_type field
    clean_edges = []
    for e in edges:
        ce = {
            "color": str(e.get("color", "#A2B1C3")).upper(),
            "edge_remark": str(e.get("edge_remark", "")),
            "source_id": str(e.get("source_id", "")),
            "source_port": str(e.get("source_port", "port-bottom")),
            "target_id": str(e.get("target_id", "")),
            "target_port": str(e.get("target_port", "port-top")),
        }
        clean_edges.append(ce)

    payload: dict[str, Any] = {
        "com_id": prj_id,           # BI upInfo uses "com_id", not "prj_id"
        "up_type": "nodes",
        "up_nodes": up_nodes,
        "up_edges": clean_edges,
        "ver_id": version_id or "", # BI upInfo uses "ver_id", not "ver_info"
    }

    logger.info("submit: upInfo payload com_id=%s ver_id=%s nodes=%d edges=%d",
                prj_id, version_id, len(up_nodes), len(clean_edges))

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, json=payload, headers=headers, cookies=cookies)
        logger.info("submit: BI response status=%s body=%s", resp.status_code, resp.text[:500])
        resp.raise_for_status()
        try:
            result = resp.json()
        except Exception:
            result = {"raw": resp.text}

    return result


# ═══════════════════════════════════════════════════════════
#  LLM Client & BI Config Helpers
# ═══════════════════════════════════════════════════════════

def _get_llm_client(cfg: SystemConfig) -> OpenAICompatibleAgentClient:
    api_key = decrypt_secret(cfg.llm_api_key_encrypted) or ""
    base_url = (cfg.llm_base_url or "").strip()
    if not api_key:
        raise ValueError("LLM API Key 未配置")
    if not base_url:
        raise ValueError("LLM Base URL 未配置")
    return OpenAICompatibleAgentClient(base_url=base_url, api_key=api_key)


def _get_power_map_config(cfg: SystemConfig) -> dict[str, str]:
    base_url = (cfg.power_map_base_url or "").strip().rstrip("/")
    get_path = (cfg.power_map_get_path or "").strip()
    update_path = (cfg.power_map_update_path or "").strip()
    auth_token = decrypt_secret(cfg.power_map_auth_token_encrypted) or ""
    if not base_url:
        raise ValueError("权利地图 API 地址未配置，请前往配置页填写")
    if not get_path:
        raise ValueError("权利地图查询路径未配置，请前往配置页填写")
    return {"base_url": base_url, "get_path": get_path, "update_path": update_path, "auth_token": auth_token}


# ═══════════════════════════════════════════════════════════
#  Vision Harness: Screenshot + Layout Tool Calls
# ═══════════════════════════════════════════════════════════

_SCREENSHOT_CACHE: dict[str, tuple[float, str]] = {}
_SCREENSHOT_CACHE_TTL = 60.0
_SCREENSHOT_URL_TEMPLATE = (
    "https://crm.finereporthelp.com/WebReport/power_map/"
    "powerMap_v3.13.html?com_id={prj_id}"
)


async def _capture_power_map_screenshot(
    prj_id: str,
    *,
    cookies: dict[str, str] | None = None,
    extra_headers: dict[str, str] | None = None,
) -> str:
    """Capture a screenshot of the live power-map render and return a base64 data URL.

    Uses Playwright async API; caches per-prj_id for 60s.
    Viewport is 1920x1080; waits for the X6 SVG canvas before snapping.
    Pass cookies/headers for BI authentication (CAS or Bearer token).
    """
    now = time.time()
    cache_key = prj_id
    if cookies:
        # Include auth state in cache key so different users get different screenshots
        cache_key = f"{prj_id}:{hash(frozenset(cookies.items()))}"
    cached = _SCREENSHOT_CACHE.get(cache_key)
    if cached and (now - cached[0]) < _SCREENSHOT_CACHE_TTL:
        return cached[1]

    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:  # pragma: no cover — exercised at runtime only
        raise RuntimeError(
            "Playwright 未安装：pip install playwright && playwright install chromium"
        ) from exc

    url = _SCREENSHOT_URL_TEMPLATE.format(prj_id=prj_id)
    logger.info("harness: capturing screenshot for prj_id=%s", prj_id)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-gpu"])
        try:
            ctx_opts = {"viewport": {"width": 1920, "height": 1080}}
            page_ctx = await browser.new_context(**ctx_opts)

            # Inject auth cookies (CAS session) if available
            if cookies:
                cookie_list = [
                    {"name": k, "value": v, "domain": "crm.finereporthelp.com", "path": "/"}
                    for k, v in cookies.items()
                ]
                await page_ctx.add_cookies(cookie_list)

            page = await page_ctx.new_page()

            # Set extra headers (Bearer token via Authorization header)
            if extra_headers:
                await page.set_extra_http_headers(extra_headers)

            await page.goto(url, wait_until="networkidle", timeout=30000)
            await page.wait_for_selector(".x6-graph-svg", timeout=15000)
            # Allow X6 animations / async layout to settle.
            await page.wait_for_timeout(1500)
            png_bytes = await page.screenshot(type="png", full_page=False)
        finally:
            await browser.close()

    data_url = "data:image/png;base64," + base64.b64encode(png_bytes).decode("ascii")
    _SCREENSHOT_CACHE[cache_key] = (now, data_url)
    return data_url


def _invalidate_screenshot_cache(prj_id: str) -> None:
    _SCREENSHOT_CACHE.pop(prj_id, None)


# ── Layout tool functions ─────────────────────────────────────

# Universal title keywords used to identify department leaders. Applied to all
# companies — works across Chinese and English titles.
_LEADER_TITLE_KEYWORDS = (
    "总裁", "副总", "总经理", "总监", "总", "经理", "主管", "负责人",
    "部长", "组长", "leader", "lead", "manager", "director", "head",
    "chief", "ceo", "cto", "cfo", "coo", "vp", "president",
)


def _dept_users(ctx: MergeContext, dept: PowerNode) -> list[PowerNode]:
    """Return every user (locked or not) currently owned by this dept."""
    return [
        n for n in ctx.all_nodes
        if n.node_type == "user" and n.parent_dept_id == dept.id
    ]


def _identify_dept_leader(
    ctx: MergeContext,
    dept: PowerNode,
    users: list[PowerNode] | None = None,
) -> PowerNode | None:
    """Identify the department leader for layout purposes.

    Ranking signals (in priority order):
      1. Most direct reports inside this dept (users whose pid == candidate.id).
      2. Net outgoing edges within the dept (leaders point at subordinates).
      3. Title keywords ("总监", "manager", ...) on the user's position string.
      4. Stable name-based tiebreaker for determinism.

    This is a GENERAL heuristic — not hardcoded per company. Returns None when
    the dept has no users.
    """
    if users is None:
        users = _dept_users(ctx, dept)
    if not users:
        return None
    if len(users) == 1:
        return users[0]

    user_ids = {u.id for u in users}
    reports_to: dict[str, int] = {u.id: 0 for u in users}
    for u in users:
        if u.pid and u.pid in user_ids and u.pid != u.id:
            reports_to[u.pid] = reports_to.get(u.pid, 0) + 1

    outgoing: dict[str, int] = {u.id: 0 for u in users}
    incoming: dict[str, int] = {u.id: 0 for u in users}
    for e in ctx.edges:
        s = str(e.get("source_id", ""))
        t = str(e.get("target_id", ""))
        if s in user_ids and t in user_ids and s != t:
            outgoing[s] = outgoing.get(s, 0) + 1
            incoming[t] = incoming.get(t, 0) + 1

    def title_score(u: PowerNode) -> int:
        pos = (u.position or "").strip().lower()
        if not pos:
            return 0
        return 1 if any(kw in pos for kw in _LEADER_TITLE_KEYWORDS) else 0

    def rank(u: PowerNode) -> tuple:
        return (
            reports_to.get(u.id, 0),
            outgoing.get(u.id, 0) - incoming.get(u.id, 0),
            title_score(u),
            -len(u.name or ""),
            u.name or "",
        )

    return max(users, key=rank)


def _fit_dept_to_members(
    ctx: MergeContext, dept: PowerNode, mode: str = "exact"
) -> None:
    """Resize a dept so it encompasses all its member users with padding.

    mode = 'exact' → snap dept to fit (used after place_users/adjust_spacing).
    mode = 'min'   → only grow if too small (used after resize_dept).

    Honors geometry_locked: locked depts are left alone.
    """
    if dept.geometry_locked:
        return
    users = _dept_users(ctx, dept)
    if not users:
        dept.w = max(dept.w, DEPT_MIN_W)
        dept.h = max(dept.h, DEPT_MIN_H)
        return

    min_x = min(u.x for u in users)
    min_y = min(u.y for u in users)
    max_x = max(u.x + PERSON_W for u in users)
    max_y = max(u.y + PERSON_H for u in users)

    needed_w = (max_x - min_x) + DEPT_PAD_LEFT + DEPT_PAD_RIGHT
    needed_h = (max_y - min_y) + DEPT_PAD_TOP + DEPT_PAD_BOTTOM

    new_x = min(dept.x, min_x - DEPT_PAD_LEFT)
    new_y = min(dept.y, min_y - DEPT_PAD_TOP)

    if mode == "exact":
        dept.x = float(new_x)
        dept.y = float(new_y)
        dept.w = float(max(needed_w, DEPT_MIN_W))
        dept.h = float(max(needed_h, DEPT_MIN_H))
    else:
        if min_x < dept.x:
            dept.x = float(new_x)
        if min_y < dept.y:
            dept.y = float(new_y)
        dept.w = float(max(dept.w, needed_w, DEPT_MIN_W))
        dept.h = float(max(dept.h, needed_h, DEPT_MIN_H))


def _tool_place_users(
    ctx: MergeContext,
    dept_name: str,
    strategy: str = "auto",
    leader_name: str = "",
) -> dict[str, Any]:
    """Place users inside a department: leader on top, subordinates below.

    strategy: 'tree' | 'grid' | 'auto'. Dept box auto-fits after placement.
    The leader is identified by leader_name (provided by the LLM); if omitted,
    the first movable user is used as a default anchor.
    """
    dept = _find_dept_by_name(ctx, dept_name)
    if not dept:
        return {"ok": False, "error": f"dept '{dept_name}' not found"}
    if dept.geometry_locked:
        return {"ok": False, "error": f"dept '{dept_name}' geometry_locked"}

    all_users = _dept_users(ctx, dept)
    if not all_users:
        return {"ok": True, "moved": 0, "note": "no users"}

    movable = [u for u in all_users if not u.geometry_locked]
    if not movable:
        return {"ok": True, "moved": 0, "note": "no movable users"}

    strat = (strategy or "auto").lower()
    if strat == "auto":
        strat = "tree" if any(u.pid for u in all_users) else "grid"

    leader = _find_user_by_name(ctx, leader_name) if leader_name else None
    if leader is None and movable:
        leader = movable[0]
    leader_movable = bool(leader and not leader.geometry_locked)

    # Snapshot dept origin BEFORE placement, so we can shift users
    # after _fit_dept_to_members repositions the department box.
    _old_dept_x = dept.x
    _old_dept_y = dept.y

    inner_x = dept.x + DEPT_PAD_LEFT
    inner_y = dept.y + DEPT_PAD_TOP
    inner_w = max(dept.w - DEPT_PAD_LEFT - DEPT_PAD_RIGHT, PERSON_W)

    moved = 0
    subordinates = [u for u in movable if not leader or u.id != leader.id]
    _moved_users: list[PowerNode] = []

    if leader_movable:
        leader.x = inner_x + max(0.0, (inner_w - PERSON_W) / 2.0)
        leader.y = inner_y
        moved += 1
        _moved_users.append(leader)
        sub_top = leader.y + PERSON_H + _LEVEL_GAP_V
    elif leader and leader.geometry_locked:
        sub_top = max(inner_y, leader.y + PERSON_H + _LEVEL_GAP_V)
    else:
        sub_top = inner_y

    if strat == "grid" and subordinates:
        cols = max(1, int((inner_w + MIN_GAP_BETWEEN_USERS) // (PERSON_W + MIN_GAP_BETWEEN_USERS)))
        for i, u in enumerate(subordinates):
            r, c = divmod(i, cols)
            row_count = min(cols, len(subordinates) - r * cols) if r == len(subordinates) // cols else cols
            row_total_w = row_count * PERSON_W + (row_count - 1) * MIN_GAP_BETWEEN_USERS
            row_start_x = inner_x + max(0.0, (inner_w - row_total_w) / 2.0)
            u.x = row_start_x + c * (PERSON_W + MIN_GAP_BETWEEN_USERS)
            u.y = sub_top + r * (PERSON_H + MIN_GAP_BETWEEN_USERS)
            moved += 1
    elif strat == "tree" and subordinates:
        leader_id = leader.id if leader else ""
        direct = [u for u in subordinates if u.pid == leader_id] if leader_id else []
        leftover = [u for u in subordinates if u not in direct]
        if not direct:
            direct = subordinates
            leftover = []

        total_w = len(direct) * PERSON_W + max(0, len(direct) - 1) * _SIBLING_GAP_H
        start_x = inner_x + max(0.0, (inner_w - total_w) / 2.0)
        positions: dict[str, tuple[float, float]] = {}
        for i, u in enumerate(direct):
            u.x = start_x + i * (PERSON_W + _SIBLING_GAP_H)
            u.y = sub_top
            positions[u.id] = (u.x, u.y)
            moved += 1

        deeper_y = sub_top + PERSON_H + _LEVEL_GAP_V
        for parent in direct:
            grand = [u for u in leftover if u.pid == parent.id]
            for j, g in enumerate(grand):
                g.x = parent.x + j * (PERSON_W + _SIBLING_GAP_H)
                g.y = deeper_y
                moved += 1
                leftover.remove(g)
        if leftover:
            cols = max(1, int((inner_w + MIN_GAP_BETWEEN_USERS) // (PERSON_W + MIN_GAP_BETWEEN_USERS)))
            base_y = deeper_y + PERSON_H + _LEVEL_GAP_V
            for k, u in enumerate(leftover):
                r, c = divmod(k, cols)
                u.x = inner_x + c * (PERSON_W + MIN_GAP_BETWEEN_USERS)
                u.y = base_y + r * (PERSON_H + MIN_GAP_BETWEEN_USERS)
                moved += 1

    _fit_dept_to_members(ctx, dept, mode="exact")

    # Shift ALL users (including locked) by how much the department moved,
    # so they stay inside the resized/repositioned department box.
    dx = dept.x - _old_dept_x
    dy = dept.y - _old_dept_y
    if dx or dy:
        for u in all_users:
            u.x += dx
            u.y += dy

    return {
        "ok": True,
        "moved": moved,
        "strategy": strat,
        "leader": leader.name if leader else None,
    }


def _tool_resize_dept(ctx: MergeContext, dept_name: str, width: float, height: float) -> dict[str, Any]:
    """Resize a department to the requested size, enforcing minimum dimensions
    AND ensuring it still encompasses every member user with padding.
    Skips geometry_locked depts."""
    dept = _find_dept_by_name(ctx, dept_name)
    if not dept:
        return {"ok": False, "error": f"dept '{dept_name}' not found"}
    if dept.geometry_locked:
        return {"ok": False, "error": f"dept '{dept_name}' geometry_locked"}
    try:
        new_w = max(float(width), DEPT_MIN_W)
        new_h = max(float(height), DEPT_MIN_H)
    except (TypeError, ValueError):
        return {"ok": False, "error": "width/height must be numeric"}
    dept.w = new_w
    dept.h = new_h
    _fit_dept_to_members(ctx, dept, mode="min")
    return {"ok": True, "width": dept.w, "height": dept.h}


def _tool_adjust_spacing(
    ctx: MergeContext,
    dept_name: str,
    gap_x: float,
    gap_y: float,
    leader_name: str = "",
) -> dict[str, Any]:
    """Reflow users in a dept with the requested gaps while keeping the
    department leader anchored at the top row. Auto-fits the dept box.
    The leader is identified by leader_name (provided by the LLM); if omitted,
    the first movable user is used as a default anchor."""
    dept = _find_dept_by_name(ctx, dept_name)
    if not dept:
        return {"ok": False, "error": f"dept '{dept_name}' not found"}
    if dept.geometry_locked:
        return {"ok": False, "error": f"dept '{dept_name}' geometry_locked"}

    all_users = _dept_users(ctx, dept)
    movable = [u for u in all_users if not u.geometry_locked]
    if not movable:
        return {"ok": True, "moved": 0}
    try:
        gx = max(float(gap_x), 0.0)
        gy = max(float(gap_y), 0.0)
    except (TypeError, ValueError):
        return {"ok": False, "error": "gap_x/gap_y must be numeric"}

    leader = _find_user_by_name(ctx, leader_name) if leader_name else None
    if leader is None and movable:
        leader = movable[0]
    leader_movable = bool(leader and not leader.geometry_locked)

    # Snapshot before placement for post-fit shift
    _old_dept_x_adj = dept.x
    _old_dept_y_adj = dept.y

    inner_x = dept.x + DEPT_PAD_LEFT
    inner_y = dept.y + DEPT_PAD_TOP
    inner_w = max(dept.w - DEPT_PAD_LEFT - DEPT_PAD_RIGHT, PERSON_W)

    moved = 0
    if leader_movable:
        leader.x = inner_x + max(0.0, (inner_w - PERSON_W) / 2.0)
        leader.y = inner_y
        moved += 1
        sub_top = leader.y + PERSON_H + max(gy, _LEVEL_GAP_V * 0.5)
    elif leader and leader.geometry_locked:
        sub_top = max(inner_y, leader.y + PERSON_H + gy)
    else:
        sub_top = inner_y

    subordinates = [u for u in movable if not leader or u.id != leader.id]
    cols = max(1, int((inner_w + gx) // (PERSON_W + gx))) if (PERSON_W + gx) > 0 else 1
    for i, u in enumerate(subordinates):
        r, c = divmod(i, cols)
        u.x = inner_x + c * (PERSON_W + gx)
        u.y = sub_top + r * (PERSON_H + gy)
        moved += 1

    _fit_dept_to_members(ctx, dept, mode="exact")

    # Shift ALL users by how much the department moved
    dx_adj = dept.x - _old_dept_x_adj
    dy_adj = dept.y - _old_dept_y_adj
    if dx_adj or dy_adj:
        for u in all_users:
            u.x += dx_adj
            u.y += dy_adj

    return {
        "ok": True,
        "moved": moved,
        "cols": cols,
        "leader": leader.name if leader else None,
    }


def _tool_nudge_node(
    ctx: MergeContext,
    node_id: str,
    direction: str,
    distance: float | None = None,
) -> dict[str, Any]:
    """Nudge a node a small step in one direction.

    Last-mile micro-adjustment. The Agent can pass an explicit `distance`
    in pixels; otherwise _DIRECTION_STEP_PX (~15px) is used.
    """
    target_key = (node_id or "").strip()
    if not target_key:
        return {"ok": False, "error": "node_id is required"}
    node = ctx.nodes_by_id.get(target_key) or ctx.nodes_by_name.get(target_key)
    if not node:
        return {"ok": False, "error": f"node '{node_id}' not found"}
    if node.geometry_locked:
        return {"ok": False, "error": f"node '{node.name or node.id}' geometry_locked"}

    d = (direction or "").strip().lower()
    if d not in _VALID_DIRECTIONS:
        return {"ok": False, "error": f"invalid direction: {direction!r}; expected up/down/left/right"}

    try:
        step = float(distance) if distance is not None else float(_DIRECTION_STEP_PX)
    except (TypeError, ValueError):
        return {"ok": False, "error": f"distance must be numeric, got {distance!r}"}
    if step <= 0:
        step = float(_DIRECTION_STEP_PX)

    dx = 0.0
    dy = 0.0
    if d == "left":
        dx = -step
    elif d == "right":
        dx = step
    elif d == "up":
        dy = -step
    else:  # down
        dy = step

    node.x = float(node.x) + dx
    node.y = float(node.y) + dy

    return {
        "ok": True,
        "node_id": node.id,
        "direction": d,
        "distance": step,
        "x": round(node.x, 1),
        "y": round(node.y, 1),
    }


# Backwards-compatible alias for any in-flight callers (no external API exposure).
_tool_move_user = _tool_nudge_node


def _tool_check_collisions(
    ctx: MergeContext,
    scope_id: str = "",
) -> dict[str, Any]:
    """Scan nodes; return a structured collision report.

    scope_id (optional): restricts the scan to a container's subtree
    (the container itself + every descendant via parent_dept_id). If
    omitted, the whole graph is scanned.
    """
    in_scope: set[str] | None = None
    scope_resolved = ""
    if scope_id:
        anchor = ctx.nodes_by_id.get(scope_id) or ctx.nodes_by_name.get(scope_id)
        if anchor:
            scope_resolved = anchor.id
            in_scope = {anchor.id}
            added = True
            while added:
                added = False
                for n in ctx.all_nodes:
                    if n.parent_dept_id in in_scope and n.id not in in_scope:
                        in_scope.add(n.id)
                        added = True

    items: list[BBoxItem] = []
    locked_ids: set[str] = set()
    for n in ctx.all_nodes:
        if in_scope is not None and n.id not in in_scope:
            continue
        w, h = _node_bbox_size(n)
        items.append(BBoxItem(
            id=n.id,
            item_type=n.node_type,
            x=float(n.x),
            y=float(n.y),
            w=w,
            h=h,
            parent_dept_id=n.parent_dept_id if n.node_type == "user" else None,
        ))
        if n.geometry_locked:
            locked_ids.add(n.id)
    raw = _check_collision(items, [], locked_ids)
    id_to_node = {n.id: n for n in ctx.all_nodes}
    details: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for a_id, b_id, desc in raw:
        key = tuple(sorted((a_id, b_id)))
        if key in seen:
            continue
        seen.add(key)
        a = id_to_node.get(a_id)
        b = id_to_node.get(b_id)
        if not a or not b:
            continue
        aw, ah = _node_bbox_size(a)
        bw, bh = _node_bbox_size(b)
        area = _rects_overlap_area(
            (a.x, a.y, a.x + aw, a.y + ah),
            (b.x, b.y, b.x + bw, b.y + bh),
        )
        col_type = f"{a.node_type}-{b.node_type}"
        description = desc if area <= 0 else f"{desc} (≈{int(area)}px²)"
        details.append({
            "type": col_type,
            "node_a": a.name or a.id,
            "node_b": b.name or b.id,
            "description": description,
        })
    return {
        "ok": True,
        "total_collisions": len(details),
        "details": details,
        "scope": scope_resolved,
    }


def _tool_check_geometry(ctx: MergeContext, node_ids: list[str]) -> dict[str, Any]:
    """LLM-callable geometry check. Returns structured conflict report.

    Returns CRITICAL/HIGH/MEDIUM conflicts filtered to those involving the
    given node_ids. Called on demand by the LLM (no automatic injection).
    """
    if not node_ids:
        return {
            "ok": True,
            "conflicts": [],
            "summary": {"critical": 0, "high": 0, "medium": 0, "total": 0},
            "message": "未传入 node_ids，跳过检测",
        }

    try:
        from tests.check_geometry import find_conflicts, parse_ctx  # type: ignore
    except ImportError:
        try:
            from backend.tests.check_geometry import find_conflicts, parse_ctx  # type: ignore
        except ImportError:
            return {"ok": False, "error": "check_geometry module unavailable"}

    ctx_nodes = [{"id": n.id, "name": n.name, "node_type": n.node_type,
                  "parent_id": n.parent_id, "x": n.x, "y": n.y,
                  "w": n.w, "h": n.h} for n in ctx.all_nodes]
    ctx_edges = [{"id": e.get("id", ""), "source_id": e.get("source_id", ""),
                  "target_id": e.get("target_id", "")} for e in ctx.edges]

    data = {"nodes": ctx_nodes, "edges": ctx_edges}
    bboxes, _ = parse_ctx(data)
    touched = set(node_ids)
    report = find_conflicts(bboxes, ctx_edges, touched_ids=touched)

    conflicts = report.get("conflicts", [])

    # Detect zero-dimension nodes (BI data bug, rendering mismatch)
    target_nodes = [
        ctx.nodes_by_id.get(str(nid)) or ctx.nodes_by_name.get(str(nid))
        for nid in node_ids
    ]
    for n in target_nodes:
        if n is None:
            continue
        if (not n.w or n.w <= 0) or (not n.h or n.h <= 0):
            conflicts.append({
                "severity": "MEDIUM",
                "type": "zero_dimensions",
                "node_id": n.id,
                "node_name": n.name,
                "message": f"Node '{n.name}' has w={n.w}, h={n.h}. Rendering will not match layout data.",
            })

    summary = {
        "critical": sum(1 for c in conflicts if c.get("severity") == "CRITICAL"),
        "high": sum(1 for c in conflicts if c.get("severity") == "HIGH"),
        "medium": sum(1 for c in conflicts if c.get("severity") == "MEDIUM"),
        "total": len(conflicts),
    }

    if not conflicts:
        return {"ok": True, "conflicts": [], "summary": summary, "message": "检测通过，无冲突"}
    return {"ok": True, "conflicts": conflicts, "summary": summary}


def _tool_auto_fix_collisions(ctx: MergeContext) -> dict[str, Any]:
    """Iteratively push overlapping nodes apart along the minimum separation vector.
    geometry_locked nodes never move. Runs up to 3 internal passes per call.
    Capped at _AUTO_FIX_COLLISIONS_MAX_CALLS (=2) calls per harness session.
    """
    if ctx.auto_fix_calls >= _AUTO_FIX_COLLISIONS_MAX_CALLS:
        return {
            "ok": False,
            "error": (
                f"auto_fix_collisions exhausted ({ctx.auto_fix_calls}/"
                f"{_AUTO_FIX_COLLISIONS_MAX_CALLS} calls used). Adjust structure "
                "or constraints and relayout instead of fixing collisions."
            ),
            "calls_used": ctx.auto_fix_calls,
            "calls_remaining": 0,
        }
    ctx.auto_fix_calls += 1
    MAX_ROUNDS = 3
    fixed_total = 0
    moved_ids: set[str] = set()
    for _ in range(MAX_ROUNDS):
        report = _tool_check_collisions(ctx)
        if report["total_collisions"] == 0:
            break
        moved_this_round = 0
        for d in report["details"]:
            a = _find_node_by_name(ctx, d["node_a"])
            b = _find_node_by_name(ctx, d["node_b"])
            if not a or not b:
                continue
            if a.geometry_locked and b.geometry_locked:
                continue
            target, other = (b, a) if a.geometry_locked else (a, b)
            if target.geometry_locked:
                continue
            tw, th = _node_bbox_size(target)
            ow, oh = _node_bbox_size(other)
            t_rect = (target.x, target.y, target.x + tw, target.y + th)
            o_rect = (other.x, other.y, other.x + ow, other.y + oh)
            if not _rects_overlap(t_rect, o_rect):
                continue
            dx_right = o_rect[2] - t_rect[0] + 1
            dx_left = t_rect[2] - o_rect[0] + 1
            dy_down = o_rect[3] - t_rect[1] + 1
            dy_up = t_rect[3] - o_rect[1] + 1
            options = [
                (dx_right, 0.0),
                (-dx_left, 0.0),
                (0.0, dy_down),
                (0.0, -dy_up),
            ]
            best = min(options, key=lambda v: abs(v[0]) + abs(v[1]))
            target.x += float(best[0])
            target.y += float(best[1])
            moved_this_round += 1
            fixed_total += 1
            moved_ids.add(target.id)
        if moved_this_round == 0:
            break
    final = _tool_check_collisions(ctx)
    moved_list = []
    for nid in moved_ids:
        n = ctx.nodes_by_id.get(nid) or ctx.nodes_by_name.get(nid)
        if n:
            moved_list.append({"id": n.id, "name": n.name, "x": round(n.x), "y": round(n.y)})
    return {
        "ok": True,
        "fixed": fixed_total,
        "remaining": final["total_collisions"],
        "calls_used": ctx.auto_fix_calls,
        "calls_remaining": _AUTO_FIX_COLLISIONS_MAX_CALLS - ctx.auto_fix_calls,
        "moved_nodes": moved_list,
    }


# ═══════════════════════════════════════════════════════════
#  Structure-first toolset (v5)
# ═══════════════════════════════════════════════════════════
# These tools let the Agent reason about the org chart in semantic
# terms (nodes / edges) and delegate all geometry to `relayout`.

_VALID_NODE_TYPES = ("system", "org", "department", "person")
_CONTAINER_TYPES = ("system", "org", "department")
_VALID_EDGE_TYPES = ("reports_to", "influences")  # belongs_to is NOT an edge — use parent_id / set_parent
_VALID_ROLES = ("A", "D", "I", "S")
_VALID_DIRECTIONS = ("up", "down", "left", "right")
_DIRECTION_STEP_PX = 15
_LEADER_KEYWORDS_AUTO_REPORT = ("负责人", "部长", "总监")
_AUTO_FIX_COLLISIONS_MAX_CALLS = 2


def _node_to_dict(n: PowerNode) -> dict[str, Any]:
    """Serialise a PowerNode for the graph_state response.

    Geometry (x/y/w/h) is intentionally excluded — the front-end computes
    positions deterministically from structure. children_ids /
    incoming_edges / outgoing_edges are filled in by
    `_tool_get_graph_state` (it has the full node/edge context to compute
    them in O(N) instead of per-node O(N²))."""
    if n.node_type == "user":
        ntype = "person"
    else:
        ntype = n.subtype if n.subtype in ("system", "org", "department") else "department"
    return {
        "id": n.id,
        "type": ntype,
        "name": n.name,
        "parent_id": n.parent_dept_id or "",
        "role": n.role,
        "position": n.position,
        "children_ids": [],
        "incoming_edges": [],
        "outgoing_edges": [],
    }


def _edge_to_dict(e: dict[str, Any]) -> dict[str, Any]:
    """Serialise an edge dict for the graph_state response."""
    return {
        "id": str(e.get("id", "")),
        "source_id": str(e.get("source_id", "")),
        "target_id": str(e.get("target_id", "")),
        "edge_type": str(e.get("edge_type", "reports_to")),
        "color": str(e.get("color", "")),
        "remark": str(e.get("edge_remark", "")),
    }


def _ensure_edge_id(edge: dict[str, Any]) -> str:
    eid = str(edge.get("id", ""))
    if not eid:
        eid = uuid.uuid4().hex
        edge["id"] = eid
    return eid


def _reindex_ctx(ctx: MergeContext) -> None:
    """Rebuild name/id indices on ctx after structural changes."""
    ctx.nodes_by_id = {n.id: n for n in ctx.all_nodes}
    ctx.nodes_by_name = {}
    ctx.depts_by_name = {}
    for n in ctx.all_nodes:
        if n.name and n.name not in ctx.nodes_by_name:
            ctx.nodes_by_name[n.name] = n
        if n.node_type == "dept" and n.name:
            ctx.depts_by_name[n.name] = n


def _tool_create_node(
    ctx: MergeContext,
    type_: str,
    name: str,
    parent_id: str = "",
    attrs: dict[str, Any] | None = None,
    x: Any = None,
    y: Any = None,
    w: Any = None,
    h: Any = None,
) -> dict[str, Any]:
    """Create a new node of the requested type.

    type_ ∈ {system, org, department, person}.
    parent_id: the id of the containing system/org/department. Required for
    person nodes, optional for container nodes (omit for top-level).
    Person nodes can NEVER be a parent.
    attrs: for person, may include {role, position}. Extra keys are stored
    onto matching PowerNode fields when present.
    x, y, w, h: optional geometry. If x or y is missing/zero, the backend
    auto-selects a non-overlapping position via _find_free_position.
    """
    logger.info(
        "[DEBUG-J] 7a.CREATE_NODE_IN raw_x=%s raw_y=%s name=%s type=%s parent_id=%s",
        x, y, name, type_, parent_id,
    )
    t = (type_ or "").strip().lower()
    if t not in _VALID_NODE_TYPES:
        return {"ok": False, "error": f"invalid type: {type_!r}"}
    if not name:
        return {"ok": False, "error": "name is required"}
    attrs = dict(attrs or {})
    parent_id = (parent_id or "").strip()
    parent_node: PowerNode | None = None
    if parent_id:
        parent_node = ctx.nodes_by_id.get(parent_id) or ctx.nodes_by_name.get(parent_id)
        if not parent_node:
            return {"ok": False, "error": f"parent '{parent_id}' not found"}
        if parent_node.node_type != "dept":
            return {
                "ok": False,
                "error": (
                    f"parent '{parent_node.name or parent_node.id}' is a person — "
                    "a person can never contain another node. parent_id must point "
                    "to a system/org/department."
                ),
            }
        parent_id = parent_node.id

    def _to_float(v: Any) -> float | None:
        if v is None or v == "":
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    # J-v2: 丢弃 LLM 传入的坐标，永远走 _find_free_position 自动落位。
    # LLM 在单轮响应中一次性输出多个 create_node，无法看到前一个的执行结果，
    # 传入相同坐标会导致节点堆叠。place_node 留给 LLM 后续布局调整。
    x, y = None, None
    xv = _to_float(x)
    yv = _to_float(y)
    wv = _to_float(w)
    hv = _to_float(h)

    is_person = (t == "person")
    default_w = float(PERSON_W if is_person else DEPT_DEFAULT_W)
    default_h = float(PERSON_H if is_person else DEPT_DEFAULT_H)

    final_w = wv if (wv is not None and wv > 0) else default_w
    final_h = hv if (hv is not None and hv > 0) else default_h

    warning: str | None = None
    if xv is None or yv is None or xv == 0 or yv == 0:
        final_x, final_y, warning = _find_free_position(
            ctx, final_w, final_h, parent_id or None
        )
    else:
        final_x, final_y = xv, yv

    nid = _generate_node_id()
    if is_person:
        node = PowerNode(
            id=nid,
            node_type="user",
            name=str(name),
            subtype="",
            parent_dept_id=parent_id,
            x=final_x,
            y=final_y,
            w=final_w,
            h=final_h,
        )
        role = str(attrs.pop("role", "")).strip().upper()
        if role and role not in _VALID_ROLES:
            return {"ok": False, "error": f"invalid role: {role!r}"}
        if role:
            node.role = role
        node.position = str(attrs.pop("position", ""))
        if parent_node and parent_node.node_type == "dept":
            node.department = parent_node.name
    else:
        node = PowerNode(
            id=nid,
            node_type="dept",
            name=str(name),
            subtype=t,
            parent_dept_id=parent_id,
            x=final_x,
            y=final_y,
            w=final_w,
            h=final_h,
            background="#e9f5e9",
        )

    for k, v in attrs.items():
        if hasattr(node, k):
            try:
                setattr(node, k, v)
            except Exception:
                pass

    ctx.all_nodes.append(node)
    _reindex_ctx(ctx)

    result: dict[str, Any] = {
        "ok": True,
        "node": _node_to_dict(node),
        "x": final_x,
        "y": final_y,
        "w": final_w,
        "h": final_h,
    }
    if warning:
        result["warning"] = warning
    logger.info(
        "[DEBUG-J] 7a.CREATE_NODE_OUT node_id=%s final_x=%.1f final_y=%.1f w=%.1f h=%.1f warning=%s",
        nid, float(final_x), float(final_y), float(final_w), float(final_h), warning,
    )
    return result


def _match_user_to_upinfo(
    name: str,
    upinfo_users: list[dict],
    used_indices: set[int],
) -> tuple[dict | None, int | None]:
    """Exact-name lookup against the CRM contact roster, skipping indices
    already claimed in this commit. Strips a trailing "-N" disambiguator
    (e.g. "张三-2" → "张三") before matching."""
    base_name = name
    m = re.match(r"^(.+)-(\d+)$", name)
    if m:
        base_name = m.group(1)

    for i, c in enumerate(upinfo_users):
        if i in used_indices:
            continue
        if c.get("name", "") == base_name:
            return c, i
    return None, None


def _enrich_users_from_upinfo(ctx: MergeContext) -> None:
    """Back-fill cont_id / phone / position / department on LLM-created user
    nodes by exact name match against ctx.upinfo_users. Transparent to the
    LLM — runs immediately before commit serialisation."""
    users = ctx.upinfo_users
    if not users:
        logger.info("[DEBUG-J crm_enrich] no upinfo_users, skip")
        return

    user_nodes = [n for n in ctx.all_nodes if n.node_type == "user"]
    used_indices: set[int] = set()
    total = 0
    matched = 0
    unmatched = 0

    for node in user_nodes:
        # Only enrich nodes that look LLM-created: missing both cont_id and phone.
        if node.cont_id or node.phone:
            continue
        total += 1
        u, idx = _match_user_to_upinfo(node.name, users, used_indices)
        if u is None:
            unmatched += 1
            logger.warning(
                "[DEBUG-J crm_enrich_miss] name=%s reason=no_match_in_upinfo",
                node.name,
            )
            continue
        node.cont_id = str(u.get("cont_id", node.cont_id))
        node.phone = str(u.get("phone", node.phone))
        if not node.position:
            node.position = str(u.get("position", ""))
        if not node.department:
            node.department = str(u.get("department", ""))
        used_indices.add(idx)
        matched += 1

    logger.info(
        "[DEBUG-J crm_enrich] total_new_users=%d matched=%d unmatched=%d",
        total, matched, unmatched,
    )


def _pick_nearest_ports(src_node: PowerNode, tgt_node: PowerNode) -> tuple[str, str]:
    """Pick the closest (source_port, target_port) pair based on relative
    position. The dominant-axis policy plays well with X6's Manhattan router:
    nodes mostly side-by-side connect via left/right; otherwise top/bottom.
    Hidden from the LLM — only called inside edge-touching tools.
    """
    src_cx = src_node.x + src_node.w / 2.0
    src_cy = src_node.y + src_node.h / 2.0
    tgt_cx = tgt_node.x + tgt_node.w / 2.0
    tgt_cy = tgt_node.y + tgt_node.h / 2.0
    dx = tgt_cx - src_cx
    dy = tgt_cy - src_cy

    if abs(dx) >= abs(dy):
        if dx > 0:
            source_port, target_port = "port-right", "port-left"
        else:
            source_port, target_port = "port-left", "port-right"
    else:
        if dy > 0:
            source_port, target_port = "port-bottom", "port-top"
        else:
            source_port, target_port = "port-top", "port-bottom"

    logger.debug(
        "[DEBUG-J pick_ports] src=%s tgt=%s dx=%.1f dy=%.1f → (%s, %s)",
        src_node.name, tgt_node.name, dx, dy, source_port, target_port,
    )
    return source_port, target_port


def _recompute_edge_ports_for_node(ctx: MergeContext, node_id: str) -> int:
    """After a node's coordinates change, recompute source_port/target_port
    on every edge that touches it. Silent — LLM never sees it. Returns the
    count of edges updated.
    """
    affected = 0
    for edge in ctx.edges:
        sid = str(edge.get("source_id", ""))
        tid = str(edge.get("target_id", ""))
        if sid != node_id and tid != node_id:
            continue
        src_node = ctx.nodes_by_id.get(sid)
        tgt_node = ctx.nodes_by_id.get(tid)
        if src_node is None or tgt_node is None:
            continue
        sp, tp = _pick_nearest_ports(src_node, tgt_node)
        edge["source_port"] = sp
        edge["target_port"] = tp
        affected += 1
    if affected > 0:
        logger.debug(
            "[DEBUG-J recompute_ports] node_id=%s affected_edges=%d",
            node_id[:8], affected,
        )
    return affected


def _tool_create_edge(
    ctx: MergeContext,
    source_id: str,
    target_id: str,
    edge_type: str,
) -> dict[str, Any]:
    """Create a line edge between two nodes.

    edge_type:
      - reports_to: solid reporting line (source reports to target)
      - influences: dashed influence line

    `belongs_to` is REJECTED. Membership/containment is expressed via parent_id
    (created via create_node parent_id, or moved with set_parent), never via
    a line edge.
    """
    logger.info(
        "[DEBUG-J] 7f.CREATE_EDGE src=%s tgt=%s type=%s",
        source_id, target_id, edge_type,
    )
    et = (edge_type or "").strip().lower()
    if et == "belongs_to":
        return {
            "ok": False,
            "error": (
                "edge_type='belongs_to' is not allowed — membership goes through "
                "parent_id. Use create_node(parent_id=...) or set_parent(node_id, "
                "new_parent_id) instead."
            ),
        }
    if et not in _VALID_EDGE_TYPES:
        return {"ok": False, "error": f"invalid edge_type: {edge_type!r}"}
    if not source_id or not target_id:
        return {"ok": False, "error": "source_id and target_id are required"}
    src = ctx.nodes_by_id.get(source_id) or ctx.nodes_by_name.get(source_id)
    tgt = ctx.nodes_by_id.get(target_id) or ctx.nodes_by_name.get(target_id)
    if not src:
        return {"ok": False, "error": f"source '{source_id}' not found"}
    if not tgt:
        return {"ok": False, "error": f"target '{target_id}' not found"}
    if src.id == tgt.id:
        return {"ok": False, "error": "source and target must differ"}

    if et == "reports_to":
        if src.node_type == "user":
            src.pid = tgt.id
        style_color = "#2563eb"
    else:  # influences
        style_color = "#a855f7"

    source_port, target_port = _pick_nearest_ports(src, tgt)
    edge = {
        "id": uuid.uuid4().hex,
        "source_id": src.id,
        "target_id": tgt.id,
        "edge_type": et,
        "source_port": source_port,
        "target_port": target_port,
        "color": style_color,
        "edge_remark": "",
    }
    if et == "influences":
        edge["dashed"] = True
    ctx.edges.append(edge)
    return {"ok": True, "edge": _edge_to_dict(edge)}


def _tool_delete_node(ctx: MergeContext, id: str, cascade: bool = True) -> dict[str, Any]:
    """Remove a node and any edges that touch it.

    cascade=True (default): recursively delete every descendant under
    the node and their edges.
    cascade=False: only the node itself is removed; descendants stay but
    their parent_id is cleared (they become top-level).
    """
    nid = (id or "").strip()
    if not nid:
        return {"ok": False, "error": "id is required"}
    node = ctx.nodes_by_id.get(nid) or ctx.nodes_by_name.get(nid)
    if not node:
        return {"ok": False, "error": f"node '{id}' not found"}
    deleted_id = node.id
    deleted_name = node.name
    is_container = node.node_type == "dept"

    # Compute deletion set.
    to_delete: set[str] = {deleted_id}
    if cascade and is_container:
        # BFS through parent_dept_id graph.
        frontier = [deleted_id]
        while frontier:
            nxt: list[str] = []
            for parent_id in frontier:
                for n in ctx.all_nodes:
                    if n.parent_dept_id == parent_id and n.id not in to_delete:
                        to_delete.add(n.id)
                        nxt.append(n.id)
            frontier = nxt

    # Apply deletions.
    ctx.all_nodes = [n for n in ctx.all_nodes if n.id not in to_delete]
    if not cascade and is_container:
        # Children become top-level.
        for n in ctx.all_nodes:
            if n.parent_dept_id == deleted_id:
                n.parent_dept_id = ""
                if n.node_type == "user":
                    n.department = ""
    for n in ctx.all_nodes:
        if n.pid in to_delete:
            n.pid = ""

    before = len(ctx.edges)
    ctx.edges = [
        e for e in ctx.edges
        if str(e.get("source_id", "")) not in to_delete
        and str(e.get("target_id", "")) not in to_delete
    ]
    removed_edges = before - len(ctx.edges)
    _reindex_ctx(ctx)
    return {
        "ok": True,
        "node_id": deleted_id,
        "name": deleted_name,
        "deleted_id": deleted_id,
        "deleted_ids": sorted(to_delete),
        "removed_edges": removed_edges,
        "cascade": bool(cascade),
    }


def _tool_delete_edge(ctx: MergeContext, id: str) -> dict[str, Any]:
    """Remove an edge by id. Only operates on line edges (reports_to /
    influences); membership is via parent_id, not edges."""
    eid = (id or "").strip()
    if not eid:
        return {"ok": False, "error": "id is required"}
    found = None
    for e in ctx.edges:
        if str(e.get("id", "")) == eid:
            found = e
            break
    if not found:
        return {"ok": False, "error": f"edge '{id}' not found"}
    src_id = str(found.get("source_id", ""))
    tgt_id = str(found.get("target_id", ""))
    if str(found.get("edge_type", "")) == "reports_to":
        src = ctx.nodes_by_id.get(src_id)
        if src and src.pid == tgt_id:
            src.pid = ""
    ctx.edges = [e for e in ctx.edges if str(e.get("id", "")) != eid]
    return {
        "ok": True,
        "edge_id": eid,
        "deleted_id": eid,
        "source_id": src_id,
        "target_id": tgt_id,
    }


def _tool_list_edges(
    ctx: MergeContext,
    source_id: str = "",
    target_id: str = "",
    edge_type: str = "",
) -> dict[str, Any]:
    """Query edges by optional filters.

    Although graph_state text already lists all edges with endpoint names,
    use this tool when: (1) you need to filter by edge_type only;
    (2) you need to find all edges involving a specific node;
    (3) the graph has >50 edges and gs_text becomes hard to scan.
    For simple lookup by source+target name, prefer scanning gs_text.
    """
    src = (source_id or "").strip()
    tgt = (target_id or "").strip()
    etype = (edge_type or "").strip().lower()

    if src:
        node = ctx.nodes_by_id.get(src) or ctx.nodes_by_name.get(src)
        if node:
            src = node.id
    if tgt:
        node = ctx.nodes_by_id.get(tgt) or ctx.nodes_by_name.get(tgt)
        if node:
            tgt = node.id

    results = []
    for e in ctx.edges:
        if src and e.get("source_id") != src:
            continue
        if tgt and e.get("target_id") != tgt:
            continue
        if etype and (e.get("edge_type") or "").lower() != etype:
            continue
        sname = ctx.nodes_by_id.get(e.get("source_id", ""))
        tname = ctx.nodes_by_id.get(e.get("target_id", ""))
        results.append({
            "id": e.get("id", ""),
            "source_id": e.get("source_id", ""),
            "target_id": e.get("target_id", ""),
            "source_name": sname.name if sname else "?",
            "target_name": tname.name if tname else "?",
            "edge_type": e.get("edge_type", ""),
        })

    return {"ok": True, "edges": results, "count": len(results)}


_UPDATE_NODE_ALLOWED: tuple[str, ...] = (
    "name", "position", "role", "tagA", "background",
    "node_border_color", "if_highLight",
)


def _tool_update_node(
    ctx: MergeContext,
    node_id: str,
    attrs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Update mutable attributes on an existing node.

    Allowed keys in attrs: name, position, role, tagA, background,
    node_border_color, if_highLight. Unknown keys are silently skipped.
    """
    key = (node_id or "").strip()
    if not key:
        return {"ok": False, "error": "node_id is required"}
    node = ctx.nodes_by_id.get(key) or ctx.nodes_by_name.get(key)
    if not node:
        return {"ok": False, "error": f"node '{node_id}' not found"}
    if not isinstance(attrs, dict):
        return {"ok": False, "error": "attrs must be an object"}

    applied: dict[str, Any] = {}
    skipped: list[str] = []
    for k, v in attrs.items():
        if k not in _UPDATE_NODE_ALLOWED:
            skipped.append(k)
            continue
        if k == "role":
            role = str(v or "").strip().upper()
            if role and role not in _VALID_ROLES:
                return {"ok": False, "error": f"invalid role: {role!r}"}
            node.role = role
            applied["role"] = role
            continue
        if k == "name":
            new_name = str(v or "").strip()
            if not new_name:
                return {"ok": False, "error": "name must not be empty"}
            node.name = new_name
            applied["name"] = new_name
            continue
        # Plain string fields.
        if hasattr(node, k):
            try:
                setattr(node, k, str(v) if v is not None else "")
                applied[k] = getattr(node, k)
            except Exception as exc:
                return {"ok": False, "error": f"failed to set {k}: {exc}"}

    _reindex_ctx(ctx)
    if any(k in applied for k in ("x", "y", "w", "h")):
        _recompute_edge_ports_for_node(ctx, node.id)
    return {
        "ok": True,
        "node_id": node.id,
        "name": node.name,
        "applied": applied,
        "updated_fields": applied,
        "skipped": skipped,
    }


def _tool_update_edge(
    ctx: MergeContext,
    edge_id: str,
    new_source_id: str = "",
    new_target_id: str = "",
) -> dict[str, Any]:
    """Re-point an existing edge.

    At least one of new_source_id / new_target_id must be supplied. When
    the edge is reports_to and target changes, the source person's pid
    is updated to the new target so the implicit reporting relationship
    stays in sync.
    """
    eid = (edge_id or "").strip()
    if not eid:
        return {"ok": False, "error": "edge_id is required"}
    new_src_raw = (new_source_id or "").strip()
    new_tgt_raw = (new_target_id or "").strip()
    if not new_src_raw and not new_tgt_raw:
        return {"ok": False, "error": "supply new_source_id or new_target_id"}

    edge = None
    for e in ctx.edges:
        if str(e.get("id", "")) == eid:
            edge = e
            break
    if not edge:
        return {"ok": False, "error": f"edge '{edge_id}' not found"}

    old_src_id = str(edge.get("source_id", ""))
    old_tgt_id = str(edge.get("target_id", ""))

    new_src_node = None
    new_tgt_node = None
    if new_src_raw:
        new_src_node = ctx.nodes_by_id.get(new_src_raw) or ctx.nodes_by_name.get(new_src_raw)
        if not new_src_node:
            return {"ok": False, "error": f"new source '{new_source_id}' not found"}
    if new_tgt_raw:
        new_tgt_node = ctx.nodes_by_id.get(new_tgt_raw) or ctx.nodes_by_name.get(new_tgt_raw)
        if not new_tgt_node:
            return {"ok": False, "error": f"new target '{new_target_id}' not found"}

    final_src = new_src_node.id if new_src_node else old_src_id
    final_tgt = new_tgt_node.id if new_tgt_node else old_tgt_id
    if final_src == final_tgt:
        return {"ok": False, "error": "source and target must differ"}

    edge["source_id"] = final_src
    edge["target_id"] = final_tgt

    # Keep pid in sync for reports_to edges.
    if str(edge.get("edge_type", "")) == "reports_to":
        # Clear old pid linkage if we re-pointed the source away.
        if new_src_node and old_src_id != final_src:
            old_src_node = ctx.nodes_by_id.get(old_src_id)
            if old_src_node and old_src_node.pid == old_tgt_id:
                old_src_node.pid = ""
        src_node = ctx.nodes_by_id.get(final_src)
        if src_node and src_node.node_type == "user":
            src_node.pid = final_tgt

    return {
        "ok": True,
        "edge_id": eid,
        "source_id": final_src,
        "target_id": final_tgt,
        "new_source_id": final_src,
        "new_target_id": final_tgt,
    }


def _tool_validate_structure(ctx: MergeContext) -> dict[str, Any]:
    """Run a quick structural sanity scan.

    Detects:
      - parent_id cycles (a node is its own ancestor)
      - orphan nodes (no parent_id AND zero edges touching them)
      - dangling edges (source or target missing)
      - duplicate node names (same name, multiple nodes)
    """
    issues: list[dict[str, Any]] = []
    by_id = {n.id: n for n in ctx.all_nodes}

    # ── cycles via parent_id ──
    for n in ctx.all_nodes:
        seen: set[str] = set()
        cur = n
        while cur and cur.parent_dept_id:
            if cur.id in seen:
                issues.append({
                    "type": "cycle",
                    "node_ids": list(seen | {cur.id}),
                    "description": f"parent_id 形成环 (起点: {n.name or n.id})",
                })
                break
            seen.add(cur.id)
            cur = by_id.get(cur.parent_dept_id)

    # ── orphans: no parent AND no edge ──
    edge_touch: set[str] = set()
    for e in ctx.edges:
        edge_touch.add(str(e.get("source_id", "")))
        edge_touch.add(str(e.get("target_id", "")))
    for n in ctx.all_nodes:
        # Top-level containers are allowed to be parent-less.
        if n.parent_dept_id:
            continue
        if n.node_type == "dept":
            continue
        if n.id in edge_touch:
            continue
        issues.append({
            "type": "orphan",
            "node_ids": [n.id],
            "description": f"孤儿人员节点: {n.name or n.id} 既无 parent 也无连线",
        })

    # ── dangling edges ──
    for e in ctx.edges:
        sid = str(e.get("source_id", ""))
        tid = str(e.get("target_id", ""))
        missing = [x for x in (sid, tid) if x and x not in by_id]
        if missing:
            issues.append({
                "type": "dangling_edge",
                "node_ids": missing,
                "description": f"悬空连线 (edge_id={e.get('id', '?')}, 缺失端点: {missing})",
            })

    # ── duplicate names ──
    name_to_ids: dict[str, list[str]] = {}
    for n in ctx.all_nodes:
        if not n.name:
            continue
        name_to_ids.setdefault(n.name, []).append(n.id)
    for name, ids in name_to_ids.items():
        if len(ids) > 1:
            issues.append({
                "type": "duplicate_name",
                "node_ids": ids,
                "description": f"重名节点: {name} (共 {len(ids)} 个)",
            })

    return {"ok": True, "issues": issues, "total": len(issues)}


async def _tool_save_state(ctx: MergeContext) -> dict[str, Any]:
    """Persist the accumulated session state to BI.

    The harness binds cfg/prj_id/version_id/current_user onto the ctx
    at session start; we re-use them here. On success we drop the
    session from the in-memory cache so subsequent calls start fresh.
    """
    if not ctx.harness_cfg or not ctx.harness_prj_id:
        return {"ok": False, "error": "no persistence context bound; save_state called outside a harness session"}
    version_id = ctx.harness_version_id or ctx.bi_ver_info or ""
    try:
        result = await _submit_to_bi(
            ctx.harness_cfg,
            ctx.harness_prj_id,
            version_id,
            ctx.all_nodes,
            ctx.edges,
            ctx.harness_current_user,
            ctx=ctx,
        )
    except Exception as exc:
        logger.exception("save_state: submit_to_bi failed")
        return {"ok": False, "error": f"submit_failed: {exc}"}

    if ctx.harness_session_id:
        _drop_session(ctx.harness_session_id)

    return {
        "ok": True,
        "submitted": True,
        "nodes_count": len(ctx.all_nodes),
        "edges_count": len(ctx.edges),
        "result": result,
    }


def _build_nesting_tree(nodes: list[PowerNode]) -> list[dict[str, Any]]:
    """Build a nesting tree rooted at top-level containers.

    Top-level = parent_dept_id is empty OR points to a node that does not exist.
    Each tree entry: {id, name, type, depth, children: [...]}.
    """
    by_id = {n.id: n for n in nodes}
    children: dict[str, list[PowerNode]] = {}
    for n in nodes:
        pid = n.parent_dept_id if n.parent_dept_id and n.parent_dept_id in by_id else ""
        children.setdefault(pid, []).append(n)

    def _walk(parent_id: str, depth: int) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for n in children.get(parent_id, []):
            ntype = "person" if n.node_type == "user" else (
                n.subtype if n.subtype in _CONTAINER_TYPES else "department"
            )
            out.append({
                "id": n.id,
                "name": n.name,
                "type": ntype,
                "depth": depth,
                "children": _walk(n.id, depth + 1) if n.node_type == "dept" else [],
            })
        return out

    return _walk("", 0)


def _compute_nesting_depth_map(nodes: list[PowerNode]) -> dict[str, int]:
    """For each container node, compute its nesting depth (top-level = 0)."""
    by_id = {n.id: n for n in nodes}
    depth: dict[str, int] = {}

    def _d(nid: str) -> int:
        if nid in depth:
            return depth[nid]
        n = by_id.get(nid)
        if not n:
            return 0
        pid = n.parent_dept_id if n.parent_dept_id and n.parent_dept_id in by_id else ""
        depth[nid] = 0 if not pid else _d(pid) + 1
        return depth[nid]

    for n in nodes:
        _d(n.id)
    return depth


def _tool_get_graph_state(
    ctx: MergeContext,
    scope: str = "",
) -> dict[str, Any]:
    """Return the current graph state.

    If scope is provided, restricts nodes/edges to that subtree (the node
    itself plus all transitive descendants by parent_dept_id).
    Always includes layout_constraints + nesting_tree to help the Agent
    reason about hierarchy depth.
    """
    for e in ctx.edges:
        _ensure_edge_id(e)

    scope_id = ""
    if scope:
        scoped = ctx.nodes_by_id.get(scope) or ctx.nodes_by_name.get(scope)
        if scoped:
            scope_id = scoped.id

    if scope_id:
        keep: set[str] = {scope_id}
        # transitive descendants via parent_dept_id
        added = True
        while added:
            added = False
            for n in ctx.all_nodes:
                if n.parent_dept_id in keep and n.id not in keep:
                    keep.add(n.id)
                    added = True
        node_list = [n for n in ctx.all_nodes if n.id in keep]
        edge_list = [
            e for e in ctx.edges
            if str(e.get("source_id", "")) in keep
            and str(e.get("target_id", "")) in keep
        ]
    else:
        node_list = list(ctx.all_nodes)
        edge_list = list(ctx.edges)

    depth_map = _compute_nesting_depth_map(ctx.all_nodes)
    max_depth = max(depth_map.values()) if depth_map else 0

    # ── Build child / edge indices over the full ctx, then project them
    #     onto whatever subset of nodes we return.
    children_by_parent: dict[str, list[str]] = {}
    for child in ctx.all_nodes:
        pid = child.parent_dept_id or ""
        if pid:
            children_by_parent.setdefault(pid, []).append(child.id)

    edges_by_source: dict[str, list[dict[str, Any]]] = {}
    edges_by_target: dict[str, list[dict[str, Any]]] = {}
    for e in ctx.edges:
        ed = _edge_to_dict(e)
        sid = ed["source_id"]
        tid = ed["target_id"]
        if sid:
            edges_by_source.setdefault(sid, []).append(ed)
        if tid:
            edges_by_target.setdefault(tid, []).append(ed)

    nodes_out: list[dict[str, Any]] = []
    for n in node_list:
        d = _node_to_dict(n)
        d["depth"] = depth_map.get(n.id, 0)
        d["children_ids"] = list(children_by_parent.get(n.id, []))
        d["incoming_edges"] = list(edges_by_target.get(n.id, []))
        d["outgoing_edges"] = list(edges_by_source.get(n.id, []))
        nodes_out.append(d)

    return {
        "ok": True,
        "nodes": nodes_out,
        "edges": [_edge_to_dict(e) for e in edge_list],
        "layout_constraints": list(ctx.layout_constraints),
        "nesting_tree": _build_nesting_tree(ctx.all_nodes),
        "max_nesting_depth": max_depth,
        "scope": scope_id,
    }


# ── New structural / constraint / visual-reference tools ──


def _tool_set_parent(
    ctx: MergeContext,
    node_id: str,
    new_parent_id: str,
) -> dict[str, Any]:
    """Reparent a node. new_parent_id must point to a container (system/org/
    department) — never to a person. An empty new_parent_id detaches the node
    (makes it top-level). Cross-level moves are allowed."""
    logger.info(
        "[DEBUG-J] 7d.SET_PARENT node_id=%s new_parent=%s old_parent=%s",
        node_id, new_parent_id, "<pre-lookup>",
    )
    key = (node_id or "").strip()
    if not key:
        logger.info(
            "[DEBUG-J] 7d.SET_PARENT node_id=%s new_parent=%s old_parent=%s",
            node_id, new_parent_id, "",
        )
        return {"ok": False, "error": "node_id is required"}
    node = ctx.nodes_by_id.get(key) or ctx.nodes_by_name.get(key)
    if not node:
        logger.info(
            "[DEBUG-J] 7d.SET_PARENT node_id=%s new_parent=%s old_parent=%s",
            node_id, new_parent_id, "<not_found>",
        )
        return {"ok": False, "error": f"node '{node_id}' not found"}

    _old_parent_dbg = node.parent_dept_id or ""
    new_parent_name = ""
    new_pid = (new_parent_id or "").strip()
    if new_pid:
        parent = ctx.nodes_by_id.get(new_pid) or ctx.nodes_by_name.get(new_pid)
        if not parent:
            return {"ok": False, "error": f"new parent '{new_parent_id}' not found"}
        if parent.node_type != "dept":
            return {
                "ok": False,
                "error": (
                    f"new parent '{parent.name or parent.id}' is a person — "
                    "containers only. parent_id must be system/org/department."
                ),
            }
        if parent.id == node.id:
            return {"ok": False, "error": "cannot parent a node to itself"}
        # Cycle check: ensure parent is not a descendant of node.
        cursor = parent
        seen: set[str] = set()
        while cursor and cursor.parent_dept_id and cursor.id not in seen:
            seen.add(cursor.id)
            if cursor.parent_dept_id == node.id:
                return {"ok": False, "error": "cycle detected: new parent is a descendant"}
            cursor = ctx.nodes_by_id.get(cursor.parent_dept_id)
        node.parent_dept_id = parent.id
        new_parent_name = parent.name or ""
        if node.node_type == "user":
            node.department = parent.name
    else:
        node.parent_dept_id = ""
        if node.node_type == "user":
            node.department = ""

    logger.info(
        "[DEBUG-J] 7d.SET_PARENT node_id=%s new_parent=%s old_parent=%s",
        node.id, node.parent_dept_id, _old_parent_dbg,
    )
    _recompute_edge_ports_for_node(ctx, node.id)
    return {
        "ok": True,
        "node_id": node.id,
        "name": node.name,
        "new_parent_id": node.parent_dept_id,
        "new_parent_name": new_parent_name,
    }


def _add_layout_constraint(
    ctx: MergeContext,
    constraint: dict[str, Any],
) -> dict[str, Any]:
    """Helper for layout-constraint storage. Validates and assigns an id."""
    if not isinstance(constraint, dict):
        return {"ok": False, "error": "constraint must be an object"}
    ctype = str(constraint.get("type", "")).strip().lower()
    nodes = constraint.get("nodes", [])
    if ctype not in ("same_rank", "horizontal_order"):
        return {"ok": False, "error": f"invalid constraint type: {ctype!r}"}
    if not isinstance(nodes, list) or len(nodes) < 2:
        return {"ok": False, "error": "constraint.nodes must be a list with ≥2 entries"}
    resolved_ids: list[str] = []
    for ref in nodes:
        s = str(ref).strip()
        n = ctx.nodes_by_id.get(s) or ctx.nodes_by_name.get(s)
        if not n:
            return {"ok": False, "error": f"node '{ref}' not found"}
        resolved_ids.append(n.id)
    cid = uuid.uuid4().hex
    entry = {"id": cid, "type": ctype, "nodes": resolved_ids}
    ctx.layout_constraints.append(entry)
    return {"ok": True, "constraint": entry}


def _tool_add_layout_constraint(
    ctx: MergeContext,
    constraint: dict[str, Any],
) -> dict[str, Any]:
    """Persist a layout preference for relayout to honour.

    constraint:
      - {"type": "same_rank", "nodes": [id1, id2, ...]}
          Keep these nodes at the same rank (same column in LR, same row in TB).
      - {"type": "horizontal_order", "nodes": [id1, id2, ...]}
          Order these nodes left-to-right exactly as listed.
    """
    return _add_layout_constraint(ctx, constraint)


def _tool_remove_layout_constraint(ctx: MergeContext, constraint_id: str) -> dict[str, Any]:
    """Remove a stored layout constraint by id."""
    cid = (constraint_id or "").strip()
    if not cid:
        return {"ok": False, "error": "constraint_id is required"}
    before = len(ctx.layout_constraints)
    ctx.layout_constraints = [c for c in ctx.layout_constraints if c.get("id") != cid]
    if len(ctx.layout_constraints) == before:
        return {"ok": False, "error": f"constraint '{constraint_id}' not found"}
    return {"ok": True, "deleted_id": cid}


def _tool_list_layout_constraints(ctx: MergeContext) -> dict[str, Any]:
    """Return every persisted layout constraint."""
    return {"ok": True, "constraints": list(ctx.layout_constraints)}


# ── Visual reference resolver ──

_POSITION_KEYWORDS = {
    "上": "top",
    "顶": "top",
    "下": "bottom",
    "底": "bottom",
    "左": "left",
    "右": "right",
    "中": "center",
    "内": "inner",
    "里": "inner",
    "外": "outer",
}
_ROLE_KEYWORDS = {
    "决策者": "A", "决策": "A", "A角色": "A",
    "推动": "D", "推动者": "D", "D角色": "D",
    "知会": "I", "知会方": "I", "I角色": "I",
    "支持": "S", "支持者": "S", "S角色": "S",
    "负责人": "leader", "总监": "leader", "部长": "leader", "经理": "leader",
    "总裁": "leader", "总经理": "leader", "ceo": "leader", "cfo": "leader",
    "cto": "leader", "coo": "leader",
}


def _tool_get_node_by_visual_reference(
    ctx: MergeContext,
    description: str,
) -> dict[str, Any]:
    """Resolve a natural-language node reference (e.g. "右上那个红框的",
    "最内层的部门") to a node id, by scoring candidates against simple
    positional / role / name signals."""
    desc = (description or "").strip()
    if not desc:
        return {"ok": False, "error": "description is required"}
    desc_low = desc.lower()

    # Detect position hints.
    pos_hints: set[str] = set()
    for kw, tag in _POSITION_KEYWORDS.items():
        if kw in desc:
            pos_hints.add(tag)

    # Detect role / leader hints.
    role_hints: set[str] = set()
    for kw, tag in _ROLE_KEYWORDS.items():
        if kw in desc_low:
            role_hints.add(tag)

    type_hint = ""
    if "部门" in desc or "department" in desc_low:
        type_hint = "department"
    elif "公司" in desc or "总部" in desc or "事业部" in desc or "org" in desc_low:
        type_hint = "org"
    elif "集团" in desc or "体系" in desc or "system" in desc_low:
        type_hint = "system"
    elif "人" in desc or "员" in desc or "person" in desc_low:
        type_hint = "person"

    # Bounding box of all nodes for relative-position scoring.
    if ctx.all_nodes:
        xs = [n.x for n in ctx.all_nodes]
        ys = [n.y for n in ctx.all_nodes]
        x2s = [n.x + n.w for n in ctx.all_nodes]
        y2s = [n.y + n.h for n in ctx.all_nodes]
        canvas_x1, canvas_y1 = min(xs), min(ys)
        canvas_x2, canvas_y2 = max(x2s), max(y2s)
        canvas_w = max(canvas_x2 - canvas_x1, 1.0)
        canvas_h = max(canvas_y2 - canvas_y1, 1.0)
    else:
        return {"ok": False, "error": "no nodes in graph"}

    depth_map = _compute_nesting_depth_map(ctx.all_nodes)
    max_depth = max(depth_map.values()) if depth_map else 0

    def score(n: PowerNode) -> float:
        s = 0.0
        # Type match
        n_type = "person" if n.node_type == "user" else (
            n.subtype if n.subtype in _CONTAINER_TYPES else "department"
        )
        if type_hint:
            if n_type == type_hint:
                s += 4.0
            else:
                s -= 1.0

        # Name fragment match (longest substring shared)
        name_low = (n.name or "").lower()
        if name_low and name_low in desc_low:
            s += 5.0
        elif name_low:
            for token in desc_low.replace("，", " ").replace(",", " ").split():
                if len(token) >= 2 and token in name_low:
                    s += 2.0

        # Positional scoring
        cx = (n.x + n.w / 2.0 - canvas_x1) / canvas_w
        cy = (n.y + n.h / 2.0 - canvas_y1) / canvas_h
        if "left" in pos_hints and cx < 0.4:
            s += 1.5
        if "right" in pos_hints and cx > 0.6:
            s += 1.5
        if "top" in pos_hints and cy < 0.4:
            s += 1.5
        if "bottom" in pos_hints and cy > 0.6:
            s += 1.5
        if "center" in pos_hints and 0.3 <= cx <= 0.7 and 0.3 <= cy <= 0.7:
            s += 1.5
        if "inner" in pos_hints and max_depth:
            s += depth_map.get(n.id, 0) / max_depth * 2.0
        if "outer" in pos_hints and max_depth:
            s += (max_depth - depth_map.get(n.id, 0)) / max_depth * 2.0

        # Role hints
        if role_hints and n.node_type == "user":
            if "leader" in role_hints:
                pos_str = (n.position or "").lower()
                if any(kw in pos_str for kw in (
                    "总裁", "总监", "总经理", "经理", "部长", "负责人",
                    "ceo", "cfo", "cto", "coo", "director", "manager", "head",
                )):
                    s += 3.0
            for r in ("A", "D", "I", "S"):
                if r in role_hints and (n.role or "").upper() == r:
                    s += 3.0

        return s

    scored = [(n, score(n)) for n in ctx.all_nodes]
    scored.sort(key=lambda kv: kv[1], reverse=True)
    best, best_s = scored[0]
    if best_s <= 0:
        return {"ok": True, "node_id": None, "score": best_s, "note": "no confident match"}
    return {
        "ok": True,
        "node_id": best.id,
        "name": best.name,
        "type": "person" if best.node_type == "user" else (
            best.subtype if best.subtype in _CONTAINER_TYPES else "department"
        ),
        "score": round(best_s, 2),
    }


# ── Screenshot tool (async; refreshes the live render). ──


async def _tool_render_screenshot(
    ctx: MergeContext,
    scope: str = "",
) -> dict[str, Any]:
    """Re-capture the live power-map render. `scope` is currently ignored
    (the live render returns the whole canvas); the field is accepted for
    forward compatibility. Stores the data URL on ctx.last_screenshot_url so
    the outer harness loop can re-attach it for the next round."""
    if not ctx.harness_prj_id:
        return {"ok": False, "error": "no harness session bound to this context"}
    _invalidate_screenshot_cache(ctx.harness_prj_id)
    try:
        data_url = await _render_sandbox_preview(ctx)
    except Exception as exc:
        return {"ok": False, "error": f"screenshot_failed: {exc}"}
    ctx.last_screenshot_url = data_url
    return {
        "ok": True,
        "scope": scope or "",
        "size_bytes": len(data_url),
        "note": "screenshot refreshed; the next round will use it",
    }


# ── Edge normalization (initial load) ──


def _normalize_edges(ctx: MergeContext) -> None:
    """Convert belongs_to edges to parent_id, fix obviously-wrong directions,
    and auto-create reports_to edges from each person to their department's
    leader when the leader has role=A or a leader-title position.

    Called once on initial load (in _build_merge_context or right after).
    """
    if not ctx.all_nodes:
        return

    by_id = ctx.nodes_by_id
    remaining: list[dict[str, Any]] = []
    flagged: list[dict[str, Any]] = []

    for e in ctx.edges:
        et = str(e.get("edge_type", "")).lower()
        sid = str(e.get("source_id", ""))
        tid = str(e.get("target_id", ""))
        src = by_id.get(sid)
        tgt = by_id.get(tid)
        if not src or not tgt:
            # Drop dangling edges.
            continue

        # belongs_to → parent_id
        if et == "belongs_to":
            src.parent_dept_id = tgt.id
            if src.node_type == "user" and tgt.node_type == "dept":
                src.department = tgt.name
            continue

        # Suspicious direction: line edge target is a person but source is container.
        # Spec says: flag for user confirmation. We keep the edge but emit a warning.
        if src.node_type == "dept" and tgt.node_type == "user":
            flagged.append({
                "edge_id": str(e.get("id", "")),
                "source_id": sid,
                "target_id": tid,
                "reason": "container → person — confirm intended direction",
            })
            remaining.append(e)
            continue

        # Line edge where source=person, target=container: implicit membership.
        if et in ("", "reports_to", "influences") and src.node_type == "user" and tgt.node_type == "dept":
            # Treat as parent_id assignment, drop the edge.
            src.parent_dept_id = tgt.id
            src.department = tgt.name
            continue

        # Container → container line edge: convert to nesting (smaller inside larger).
        if src.node_type == "dept" and tgt.node_type == "dept":
            # Heuristic: line direction implies child → parent (source is inside target).
            src.parent_dept_id = tgt.id
            continue

        remaining.append(e)

    ctx.edges = remaining
    if flagged:
        ctx.warnings.append(
            f"edge_normalization: {len(flagged)} suspicious edges flagged: "
            + json.dumps(flagged[:5], ensure_ascii=False)
        )

    # Auto-report compensation: for each person inside a dept with a clear A-role
    # or title-based leader, ensure a reports_to edge from person → leader.
    # Skip users who already have pid set — LLM already specified the relationship.
    by_dept_leader: dict[str, PowerNode | None] = {}
    for n in ctx.all_nodes:
        if n.node_type != "user" or not n.parent_dept_id:
            continue
        if n.pid:       # LLM already specified reports_to via node.pid
            continue
        if n.parent_dept_id not in by_dept_leader:
            dept_node = by_id.get(n.parent_dept_id)
            if not dept_node or dept_node.node_type != "dept":
                by_dept_leader[n.parent_dept_id] = None
                continue
            users_here = [u for u in ctx.all_nodes
                          if u.node_type == "user" and u.parent_dept_id == dept_node.id]
            picked: PowerNode | None = None
            # Prefer role=A
            for u in users_here:
                if (u.role or "").upper() == "A":
                    picked = u
                    break
            # Else first user whose position contains a leader keyword
            if picked is None:
                for u in users_here:
                    pos = (u.position or "")
                    if any(kw in pos for kw in _LEADER_KEYWORDS_AUTO_REPORT):
                        picked = u
                        break
            by_dept_leader[n.parent_dept_id] = picked

        leader = by_dept_leader.get(n.parent_dept_id)
        if not leader or leader.id == n.id:
            continue

        exists = any(
            str(e.get("source_id", "")) == n.id
            and str(e.get("target_id", "")) == leader.id
            and str(e.get("edge_type", "")).lower() in ("reports_to", "")
            for e in ctx.edges
        )
        if exists:
            continue

        logger.info(
            "[DIAG] _normalize_edges auto-report: %s (%s) → %s (%s, role=%r tagA=%r)",
            n.name, n.id[-8:], leader.name, leader.id[-8:], leader.role, leader.tagA,
        )

        ctx.edges.append({
            "id": uuid.uuid4().hex,
            "source_id": n.id,
            "target_id": leader.id,
            "edge_type": "reports_to",
            "source_port": "port-bottom",
            "target_port": "port-top",
            "color": "#2563eb",
            "edge_remark": "auto-leader",
        })
        if not n.pid:
            n.pid = leader.id


# Visual styling per nesting depth: outer levels look heaviest, inner lightest.
_DEPTH_STYLES: list[dict[str, Any]] = [
    {"border": "solid", "border_width": 3, "background": "#dbeafe", "pad_scale": 1.20, "title_font": 18},
    {"border": "dashed", "border_width": 2, "background": "#e0f2fe", "pad_scale": 1.05, "title_font": 16},
    {"border": "dashed", "border_width": 1.5, "background": "#f0f9ff", "pad_scale": 0.90, "title_font": 14},
    {"border": "dashed", "border_width": 1, "background": "#f8fafc", "pad_scale": 0.78, "title_font": 13},
    {"border": "dashed", "border_width": 1, "background": "#ffffff", "pad_scale": 0.68, "title_font": 12},
]


def _style_for_depth(depth: int) -> dict[str, Any]:
    if depth < 0:
        depth = 0
    if depth >= len(_DEPTH_STYLES):
        return _DEPTH_STYLES[-1]
    return _DEPTH_STYLES[depth]


def _tool_relayout(
    ctx: MergeContext,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Recompute coordinates for every non-locked node using a compound layered
    layout (dagre compound graph). Containers auto-size to wrap their children
    with padding. reports_to edges define vertical layering within each
    container; layout constraints (same_rank / horizontal_order) influence
    ordering within each rank. Nesting depth drives container visual styles.
    """
    options = dict(options or {})
    direction = str(options.get("direction", "TB")).upper()
    if direction not in ("TB", "BT", "LR", "RL"):
        direction = "TB"
    try:
        nodesep = float(options.get("nodesep", MIN_GAP_BETWEEN_USERS))
        ranksep = float(options.get("ranksep", _LEVEL_GAP_V))
        margin = float(options.get("margin", MIN_GAP_BETWEEN_DEPTS))
    except (TypeError, ValueError):
        return {"ok": False, "error": "nodesep/ranksep/margin must be numeric"}

    locked_pos = {
        n.id: (n.x, n.y) for n in ctx.all_nodes if n.geometry_locked
    }

    # Build children map (parent_dept_id → [PowerNode]).
    children_by_parent: dict[str, list[PowerNode]] = {}
    for n in ctx.all_nodes:
        children_by_parent.setdefault(n.parent_dept_id or "", []).append(n)

    # Apply horizontal_order constraints: re-sort siblings per container so the
    # listed nodes appear in the requested order. Other siblings keep relative order.
    for c in ctx.layout_constraints:
        if str(c.get("type", "")).lower() != "horizontal_order":
            continue
        wanted = [str(x) for x in (c.get("nodes") or []) if x]
        if len(wanted) < 2:
            continue
        # Group by container: every constrained node should share a parent.
        parents: dict[str, list[str]] = {}
        for nid in wanted:
            n = ctx.nodes_by_id.get(nid)
            if not n:
                continue
            parents.setdefault(n.parent_dept_id or "", []).append(nid)
        for parent_id, ordered in parents.items():
            if len(ordered) < 2:
                continue
            kids = children_by_parent.get(parent_id, [])
            wanted_set = set(ordered)
            others = [k for k in kids if k.id not in wanted_set]
            ordered_nodes = [
                ctx.nodes_by_id[i] for i in ordered if i in ctx.nodes_by_id
            ]
            # Place ordered nodes first, then the rest, preserving original
            # order for the rest. The layout will flow left-to-right within
            # each rank, so first-in-list lands leftmost.
            children_by_parent[parent_id] = ordered_nodes + others

    # Reports-to edges drive layers.
    reports_edges: list[tuple[str, str]] = []
    for e in ctx.edges:
        et = str(e.get("edge_type", "") or "").lower()
        if et and et != "reports_to":
            continue
        s = str(e.get("source_id", ""))
        t = str(e.get("target_id", ""))
        if s and t:
            reports_edges.append((s, t))

    logger.info(
        "[DIAG] _tool_relayout: total_edges=%d reports_edges=%d",
        len(ctx.edges), len(reports_edges),
    )
    for s, t in reports_edges:
        sn = ctx.nodes_by_id.get(s)
        tn = ctx.nodes_by_id.get(t)
        logger.info(
            "[DIAG]   reports_to edge: %s → %s (direction: source→target)",
            sn.name if sn else s[-8:], tn.name if tn else t[-8:],
        )

    # same_rank constraints: union-find to identify rank-equivalence groups.
    same_rank_root: dict[str, str] = {}

    def _find(x: str) -> str:
        while same_rank_root.get(x, x) != x:
            same_rank_root[x] = same_rank_root.get(same_rank_root[x], same_rank_root[x])
            x = same_rank_root[x]
        return x

    def _union(a: str, b: str) -> None:
        ra, rb = _find(a), _find(b)
        if ra != rb:
            same_rank_root[ra] = rb

    for c in ctx.layout_constraints:
        if str(c.get("type", "")).lower() != "same_rank":
            continue
        ids = [str(x) for x in (c.get("nodes") or []) if x]
        for nid in ids:
            same_rank_root.setdefault(nid, nid)
        for i in range(1, len(ids)):
            _union(ids[0], ids[i])

    def _layer_children(kids: list[PowerNode]) -> dict[int, list[PowerNode]]:
        kid_ids = {k.id for k in kids}
        # subordinate → managers (within this container only)
        managers: dict[str, list[str]] = {k.id: [] for k in kids}
        directs: dict[str, list[str]] = {k.id: [] for k in kids}
        for s, t in reports_edges:
            if s in kid_ids and t in kid_ids:
                managers[s].append(t)
                directs[t].append(s)
        layer: dict[str, int] = {}
        from collections import deque
        queue: deque[str] = deque()
        for k in kids:
            if not managers[k.id]:
                layer[k.id] = 0
                queue.append(k.id)
        while queue:
            mid = queue.popleft()
            for sub in directs[mid]:
                cand = layer[mid] + 1
                if sub not in layer or layer[sub] < cand:
                    layer[sub] = cand
                    queue.append(sub)
        for k in kids:
            layer.setdefault(k.id, 0)

        # Apply same_rank: every member of a same_rank group lifts to the
        # maximum layer among members.
        groups: dict[str, list[str]] = {}
        for k in kids:
            if k.id in same_rank_root:
                root = _find(k.id)
                groups.setdefault(root, []).append(k.id)
        for members in groups.values():
            members_in_kids = [m for m in members if m in kid_ids]
            if len(members_in_kids) < 2:
                continue
            max_layer = max(layer[m] for m in members_in_kids)
            for m in members_in_kids:
                layer[m] = max_layer

        out: dict[int, list[PowerNode]] = {}
        for k in kids:
            out.setdefault(layer[k.id], []).append(k)
        return out

    depth_map = _compute_nesting_depth_map(ctx.all_nodes)

    def _layout(container_id: str) -> tuple[float, float]:
        """Position direct children of `container_id` relative to (0,0) and
        return the (content_w, content_h) they occupy."""
        kids = children_by_parent.get(container_id, [])
        if not kids:
            return (0.0, 0.0)
        # Lay out child containers first (post-order).
        for k in kids:
            if k.node_type == "dept":
                cw, ch = _layout(k.id)
                # Padding shrinks with depth so deeply-nested containers stay tight.
                style = _style_for_depth(depth_map.get(k.id, 0))
                pad_scale = float(style.get("pad_scale", 1.0))
                pl = DEPT_PAD_LEFT * pad_scale
                pr = DEPT_PAD_RIGHT * pad_scale
                pt = DEPT_PAD_TOP * pad_scale
                pb = DEPT_PAD_BOTTOM * pad_scale
                k.w = max(DEPT_MIN_W, cw + pl + pr)
                k.h = max(DEPT_MIN_H, ch + pt + pb)
            else:
                k.w = PERSON_W
                k.h = PERSON_H

        layers = _layer_children(kids)
        sorted_layer_keys = sorted(layers.keys())
        if direction == "BT" or direction == "RL":
            sorted_layer_keys = list(reversed(sorted_layer_keys))

        # ── DIAG: dump layer assignment ──
        _diag_layers = {}
        for lk in sorted_layer_keys:
            _diag_layers[str(lk)] = [
                {"name": k.name, "id": k.id[-8:], "type": k.node_type}
                for k in layers[lk]
            ]
        logger.info("[DIAG] _layout container=%s layers=%s", container_id or "ROOT", json.dumps(_diag_layers, ensure_ascii=False))

        if direction in ("TB", "BT"):
            # Layers stack vertically; nodes in a layer flow horizontally.
            row_widths: list[float] = []
            row_heights: list[float] = []
            for lk in sorted_layer_keys:
                row = layers[lk]
                rw = sum(c.w for c in row) + nodesep * max(0, len(row) - 1)
                rh = max((c.h for c in row), default=0.0)
                row_widths.append(rw)
                row_heights.append(rh)
            content_w = max(row_widths) if row_widths else 0.0
            content_h = sum(row_heights) + ranksep * max(0, len(row_heights) - 1)
            cur_y = 0.0
            for idx, lk in enumerate(sorted_layer_keys):
                row = layers[lk]
                rw = row_widths[idx]
                cur_x = (content_w - rw) / 2.0
                for c in row:
                    c.x = cur_x
                    c.y = cur_y + (row_heights[idx] - c.h) / 2.0
                    cur_x += c.w + nodesep
                cur_y += row_heights[idx] + ranksep
            return (content_w, content_h)
        else:
            col_widths: list[float] = []
            col_heights: list[float] = []
            for lk in sorted_layer_keys:
                col = layers[lk]
                ch = sum(c.h for c in col) + nodesep * max(0, len(col) - 1)
                cw = max((c.w for c in col), default=0.0)
                col_widths.append(cw)
                col_heights.append(ch)
            content_w = sum(col_widths) + ranksep * max(0, len(col_widths) - 1)
            content_h = max(col_heights) if col_heights else 0.0
            cur_x = 0.0
            for idx, lk in enumerate(sorted_layer_keys):
                col = layers[lk]
                ch = col_heights[idx]
                cur_y = (content_h - ch) / 2.0
                for c in col:
                    c.x = cur_x + (col_widths[idx] - c.w) / 2.0
                    c.y = cur_y
                    cur_y += c.h + nodesep
                cur_x += col_widths[idx] + ranksep
            return (content_w, content_h)

    _layout("")

    # Walk top-down to convert each node's local position to absolute.
    def _absolutise(container_id: str, base_x: float, base_y: float) -> None:
        kids = children_by_parent.get(container_id, [])
        for k in kids:
            k.x = base_x + k.x
            k.y = base_y + k.y
            if k.node_type == "dept":
                style = _style_for_depth(depth_map.get(k.id, 0))
                pad_scale = float(style.get("pad_scale", 1.0))
                _absolutise(
                    k.id,
                    k.x + DEPT_PAD_LEFT * pad_scale,
                    k.y + DEPT_PAD_TOP * pad_scale,
                )

    _absolutise("", margin, margin)

    # ── DIAG: dump final positions after relayout ──
    _diag_final = [
        {"name": n.name, "id": n.id[-8:], "type": n.node_type,
         "x": round(n.x,1), "y": round(n.y,1), "w": round(n.w,1), "h": round(n.h,1),
         "parent_id": n.parent_dept_id[-8:] if n.parent_dept_id else ""}
        for n in ctx.all_nodes
    ]
    logger.info("[DIAG] _tool_relayout final positions: %s", json.dumps(_diag_final, ensure_ascii=False))

    # Restore locked node positions (locked nodes never move).
    for nid, (lx, ly) in locked_pos.items():
        n = ctx.nodes_by_id.get(nid)
        if n:
            n.x = lx
            n.y = ly

    # Apply depth-based visual styles to container nodes.
    for n in ctx.all_nodes:
        if n.node_type != "dept":
            continue
        style = _style_for_depth(depth_map.get(n.id, 0))
        # Keep an existing user-chosen background unless it's the default seed.
        if not n.background or n.background in ("#e9f5e9", ""):
            n.background = str(style.get("background", "#ffffff"))
        # Hint the frontend on border weight (stored in node_border_color slot
        # via a small style encoding; downstream may pick it up directly).
        # We do NOT overwrite explicit border colors set by the user.
        if not n.node_border_color:
            n.node_border_color = "#475569"

    # Refresh edge ports so routing still looks sane post-layout.
    try:
        _compute_edge_ports(ctx.edges, {n.id: n for n in ctx.all_nodes})
    except Exception:
        pass

    state = _tool_get_graph_state(ctx)
    state["direction"] = direction
    state["depth_styles_applied"] = True
    return state


# ── Route B atomic geometry tools (LLM as layout engine) ──
# These tools expose the canvas as a coordinate grid the LLM can read and write
# directly. The LLM uses get_node_geometry as a ruler, then composes placements
# via place_node / arrange_* / center_* / fit_container_to_children. No more
# server-side layout passes.

def _tool_get_node_geometry(ctx: MergeContext, node_id: str) -> dict[str, Any]:
    """Return {x, y, w, h} for a single node. The LLM's ruler — call before computing placements."""
    n = ctx.nodes_by_id.get(node_id) or ctx.nodes_by_name.get(node_id)
    if not n:
        return {"ok": False, "error": f"node '{node_id}' not found"}
    return {"ok": True, "node_id": n.id, "name": n.name, "x": round(n.x), "y": round(n.y), "w": round(n.w), "h": round(n.h)}


def _tool_place_node(ctx: MergeContext, node_id: str, x: float, y: float) -> dict[str, Any]:
    """Set a node's top-left corner to (x, y)."""
    logger.info(
        "[DEBUG-J] 7c.PLACE_NODE node_id=%s x=%.1f y=%.1f",
        node_id, float(x), float(y),
    )
    n = ctx.nodes_by_id.get(node_id) or ctx.nodes_by_name.get(node_id)
    if not n:
        logger.info(
            "[DEBUG-J] 7c.PLACE_NODE node_id=%s x=%.1f y=%.1f",
            node_id, float(x), float(y),
        )
        return {"ok": False, "error": f"node '{node_id}' not found"}
    n.x, n.y = float(x), float(y)
    logger.info(
        "[DEBUG-J] 7c.PLACE_NODE node_id=%s x=%.1f y=%.1f",
        n.id, float(n.x), float(n.y),
    )
    _recompute_edge_ports_for_node(ctx, n.id)
    warning = None
    if n.node_type == "dept" and any(
        c.parent_dept_id == n.id for c in ctx.all_nodes if c.id != n.id
    ):
        warning = (
            "place_node moved the container shell only; descendants stayed at "
            "their old absolute coordinates. Use move_dept_with_children when "
            "moving a department container with children."
        )
        logger.warning(
            "[DEBUG-J place_node soft_warn] node_id=%s node_type=dept reason=has_children",
            n.id,
        )
    return {"ok": True, "node_id": n.id, "name": n.name, "x": round(n.x), "y": round(n.y), "warning": warning}


def _tool_move_dept_with_children(ctx: MergeContext, dept_id: str, new_x: float, new_y: float) -> dict[str, Any]:
    """Translate a department container plus its entire subtree by (new_x - x, new_y - y).

    Pure geometric shift: every descendant (recursive by parent_dept_id) and the
    dept itself have their absolute (x, y) offset by the same delta. Does NOT
    modify w/h or parent_dept_id. Use this whenever you need to move a dept
    container — place_node only moves the container shell, leaving children
    visually stranded at their old absolute coordinates.
    """
    n = ctx.nodes_by_id.get(dept_id) or ctx.nodes_by_name.get(dept_id)
    if not n:
        logger.info(
            "[DEBUG-J] MOVE_DEPT_TREE dept_id=%s type=- new_x=%.1f new_y=%.1f moved_count=%d",
            dept_id, float(new_x), float(new_y), 0,
        )
        return {"ok": False, "error": f"node '{dept_id}' not found"}

    delta_x = float(new_x) - n.x
    delta_y = float(new_y) - n.y

    # Collect transitive descendants by walking parent_dept_id. For user / leaf
    # nodes this set degenerates to {n.id} and the tool acts like place_node.
    descendant_ids: set[str] = {n.id}
    frontier: list[str] = [n.id]
    while frontier:
        cur = frontier.pop()
        for c in ctx.all_nodes:
            if c.parent_dept_id == cur and c.id not in descendant_ids:
                descendant_ids.add(c.id)
                frontier.append(c.id)

    moved_ids: list[str] = []
    for node in ctx.all_nodes:
        if node.id in descendant_ids:
            node.x += delta_x
            node.y += delta_y
            moved_ids.append(node.id)

    for nid in moved_ids:
        _recompute_edge_ports_for_node(ctx, nid)

    logger.info(
        "[DEBUG-J] MOVE_DEPT_TREE dept_id=%s type=%s new_x=%.1f new_y=%.1f moved_count=%d delta=(%.1f,%.1f)",
        n.id, n.node_type, float(new_x), float(new_y), len(moved_ids), delta_x, delta_y,
    )

    return {
        "ok": True,
        "dept_id": n.id,
        "name": n.name,
        "moved_count": len(moved_ids),
        "delta_x": round(delta_x, 1),
        "delta_y": round(delta_y, 1),
        "moved_node_ids": moved_ids,
    }


def _tool_resize_container(ctx: MergeContext, container_id: str, w: float, h: float) -> dict[str, Any]:
    """Set a container's width and height."""
    n = ctx.nodes_by_id.get(container_id) or ctx.nodes_by_name.get(container_id)
    if not n:
        return {"ok": False, "error": f"container '{container_id}' not found"}
    if n.node_type != "dept":
        return {"ok": False, "error": f"'{n.name}' is a person, not a container"}
    n.w, n.h = float(w), float(h)
    _recompute_edge_ports_for_node(ctx, n.id)
    for c in ctx.all_nodes:
        if c.parent_dept_id == n.id:
            _recompute_edge_ports_for_node(ctx, c.id)
    return {"ok": True, "container_id": n.id, "name": n.name, "w": round(n.w), "h": round(n.h)}


def _tool_fit_container_to_children(ctx: MergeContext, container_id: str, padding: float = 20) -> dict[str, Any]:
    """Resize container so its bounding box tightly wraps all direct child nodes + padding."""
    n = ctx.nodes_by_id.get(container_id) or ctx.nodes_by_name.get(container_id)
    if not n:
        logger.info(
            "[DEBUG-J] 7e.FIT_CONTAINER container_id=%s child_count=%d",
            container_id, 0,
        )
        return {"ok": False, "error": f"container '{container_id}' not found"}
    if n.node_type != "dept":
        logger.info(
            "[DEBUG-J] 7e.FIT_CONTAINER container_id=%s child_count=%d",
            container_id, 0,
        )
        return {"ok": False, "error": f"'{n.name}' is a person, not a container"}

    children = [u for u in ctx.all_nodes if u.parent_dept_id == n.id]
    logger.info(
        "[DEBUG-J] 7e.FIT_CONTAINER container_id=%s child_count=%d",
        n.id, len(children),
    )

    # ── 几何兜底：dept 类型节点未声明 dept 子节点，但几何上包含其它 dept 时拒绝执行 ──
    dept_children = [c for c in children if c.node_type == "dept"]
    if not dept_children:
        geo_contained_depts = [
            d for d in ctx.all_nodes
            if d.id != n.id
            and d.node_type == "dept"
            and d.x >= n.x
            and d.y >= n.y
            and d.x + d.w <= n.x + n.w
            and d.y + d.h <= n.y + n.h
        ]
        if geo_contained_depts:
            logger.info(
                "[DEBUG-J fit soft_reject] dept_id=%s name=%s geo_contained=%s",
                n.id, n.name, [d.name for d in geo_contained_depts],
            )
            # Build explicit step-by-step instructions
            _steps = []
            for _di, _d in enumerate(geo_contained_depts):
                _steps.append(
                    f"  {_di+1}. set_parent(node_id='{_d.id}', new_parent_id='{n.id}')"
                )
            _retry_step = len(geo_contained_depts) + 1
            _steps.append(
                f"  {_retry_step}. fit_container_to_children(dept_id='{n.id}')  # retry after set_parent"
            )
            _step_block = "\n".join(_steps)
            _n_contained = len(geo_contained_depts)
            return {
                "ok": False,
                "error": "geometric_containment_mismatch",
                "warning": (
                    f"BLOCKED: Cannot fit '{n.name}' until dept-dept parents are set.\n"
                    f"REQUIRED NEXT ACTIONS (in order, DO NOT skip):\n"
                    f"{_step_block}\n"
                    f"DO NOT call fit_container_to_children again before completing step 1"
                    + (f"-{_n_contained}" if _n_contained > 1 else "")
                    + "."
                ),
                "geo_contained_dept_ids": [d.id for d in geo_contained_depts],
                "geo_contained_dept_names": [d.name for d in geo_contained_depts],
            }

    if not children:
        n.w, n.h = 240, 120
        _recompute_edge_ports_for_node(ctx, n.id)
        return {"ok": True, "container_id": n.id, "name": n.name, "w": round(n.w), "h": round(n.h), "new_w": round(n.w), "new_h": round(n.h), "note": "empty container, set to minimum"}

    # Pre-align sub-departments to the right of all users so bbox doesn't
    # runaway-expand when the LLM placed a sub-dept far outside (e.g. 技术部
    # was inflating to w=2100 because "测试组" sat orphaned at x=3200).
    sub_depts = [c for c in children if c.node_type == "dept"]
    if sub_depts:
        user_children = [c for c in children if c.node_type == "user"]
        start_x = n.x + 30
        if user_children:
            max_user_right = max(u.x + u.w for u in user_children)
            start_x = max_user_right + 40
        cur_x = start_x
        dept_y = n.y + 60
        for d in sub_depts:
            d.x = cur_x
            d.y = dept_y
            cur_x += d.w + 40

    # Defend against zero-dimension children (result of BI truthy-fallback bug)
    zero_size = [c for c in children if (not c.w or c.w <= 0) or (not c.h or c.h <= 0)]
    if zero_size:
        logger.warning(
            f"[DEBUG-J fit zero_size_children] container={n.id} "
            f"affected={[c.name for c in zero_size]}"
        )
        for c in zero_size:
            if not c.w or c.w <= 0:
                c.w = float(PERSON_W if c.node_type == "user" else DEPT_DEFAULT_W)
            if not c.h or c.h <= 0:
                c.h = float(PERSON_H if c.node_type == "user" else DEPT_DEFAULT_H)

    p = float(padding)
    min_x = min(c.x for c in children) - p
    min_y = min(c.y for c in children) - p - 24  # 24px title height
    max_x = max(c.x + c.w for c in children) + p
    max_y = max(c.y + c.h for c in children) + p

    shift_x = n.x - min_x
    shift_y = n.y - min_y
    for c in children:
        c.x += shift_x
        c.y += shift_y

    n.w = max(240, max_x - min_x)
    n.h = max(120, max_y - min_y)

    _recompute_edge_ports_for_node(ctx, n.id)
    for c in children:
        _recompute_edge_ports_for_node(ctx, c.id)

    return {"ok": True, "container_id": n.id, "name": n.name, "w": round(n.w), "h": round(n.h), "new_w": round(n.w), "new_h": round(n.h), "child_count": len(children)}


def _tool_arrange_horizontally(ctx: MergeContext, node_ids: list[str], start_x: float, y: float, gap: float = 30) -> dict[str, Any]:
    """Place a list of nodes in a horizontal row starting at (start_x, y). gap between adjacent nodes.

    Dept nodes shift via move_dept_with_children so their subtrees follow; user
    nodes get x/y set directly. moved_node_ids aggregates every id that was
    translated (depts contribute their whole subtree).
    """
    resolved = []
    for nid in node_ids:
        n = ctx.nodes_by_id.get(str(nid)) or ctx.nodes_by_name.get(str(nid))
        if not n:
            return {"ok": False, "error": f"node '{nid}' not found"}
        resolved.append(n)

    g = float(gap)
    cursor = float(start_x)
    moved_node_ids: list[str] = []
    for n in resolved:
        if n.node_type == "dept":
            sub = _tool_move_dept_with_children(ctx, dept_id=n.id, new_x=cursor, new_y=float(y))
            if sub.get("ok") and isinstance(sub.get("moved_node_ids"), list):
                moved_node_ids.extend(sub["moved_node_ids"])
            else:
                moved_node_ids.append(n.id)
        else:
            n.x = cursor
            n.y = float(y)
            _recompute_edge_ports_for_node(ctx, n.id)
            moved_node_ids.append(n.id)
        cursor += n.w + g

    return {"ok": True, "placed": len(resolved), "count": len(resolved), "end_x": round(cursor - g),
            "moved_node_ids": moved_node_ids,
            "node_ids": moved_node_ids,
            "positions": [{"id": n.id, "name": n.name, "x": round(n.x), "y": round(n.y)} for n in resolved]}


def _tool_arrange_vertically(ctx: MergeContext, node_ids: list[str], x: float, start_y: float, gap: float = 30) -> dict[str, Any]:
    """Place a list of nodes in a vertical column starting at (x, start_y). gap between adjacent nodes."""
    resolved = []
    for nid in node_ids:
        n = ctx.nodes_by_id.get(str(nid)) or ctx.nodes_by_name.get(str(nid))
        if not n:
            return {"ok": False, "error": f"node '{nid}' not found"}
        resolved.append(n)

    g = float(gap)
    cursor = float(start_y)
    for n in resolved:
        n.x = float(x)
        n.y = cursor
        cursor += n.h + g

    for n in resolved:
        _recompute_edge_ports_for_node(ctx, n.id)

    return {"ok": True, "placed": len(resolved), "count": len(resolved), "end_y": round(cursor - g),
            "node_ids": [n.id for n in resolved],
            "positions": [{"id": n.id, "name": n.name, "x": round(n.x), "y": round(n.y)} for n in resolved]}


def _tool_center_above(ctx: MergeContext, node_id: str, reference_node_ids: list[str], gap: float = 80) -> dict[str, Any]:
    """Center a node horizontally above a group of reference nodes, gap pixels above their top edge."""
    n = ctx.nodes_by_id.get(node_id) or ctx.nodes_by_name.get(node_id)
    if not n:
        return {"ok": False, "error": f"node '{node_id}' not found"}

    refs = []
    for rid in reference_node_ids:
        rn = ctx.nodes_by_id.get(str(rid)) or ctx.nodes_by_name.get(str(rid))
        if not rn:
            return {"ok": False, "error": f"reference node '{rid}' not found"}
        refs.append(rn)

    min_x = min(r.x for r in refs)
    max_x = max(r.x + r.w for r in refs)
    ref_center_x = (min_x + max_x) / 2
    ref_top_y = min(r.y for r in refs)

    g = float(gap)
    n.x = ref_center_x - n.w / 2
    n.y = ref_top_y - n.h - g

    return {"ok": True, "node_id": n.id, "name": n.name, "x": round(n.x), "y": round(n.y)}


def _tool_center_below(ctx: MergeContext, node_id: str, reference_node_ids: list[str], gap: float = 80) -> dict[str, Any]:
    """Center a node horizontally below a group of reference nodes, gap pixels below their bottom edge."""
    n = ctx.nodes_by_id.get(node_id) or ctx.nodes_by_name.get(node_id)
    if not n:
        return {"ok": False, "error": f"node '{node_id}' not found"}

    refs = []
    for rid in reference_node_ids:
        rn = ctx.nodes_by_id.get(str(rid)) or ctx.nodes_by_name.get(str(rid))
        if not rn:
            return {"ok": False, "error": f"reference node '{rid}' not found"}
        refs.append(rn)

    min_x = min(r.x for r in refs)
    max_x = max(r.x + r.w for r in refs)
    ref_center_x = (min_x + max_x) / 2
    ref_bottom_y = max(r.y + r.h for r in refs)

    g = float(gap)
    n.x = ref_center_x - n.w / 2
    n.y = ref_bottom_y + g

    return {"ok": True, "node_id": n.id, "name": n.name, "x": round(n.x), "y": round(n.y)}


def _tool_align_left(ctx: MergeContext, node_ids: list[str]) -> dict[str, Any]:
    """Align a list of nodes to the same x (leftmost node's x)."""
    resolved = []
    for nid in node_ids:
        n = ctx.nodes_by_id.get(str(nid)) or ctx.nodes_by_name.get(str(nid))
        if not n:
            return {"ok": False, "error": f"node '{nid}' not found"}
        resolved.append(n)
    target_x = min(n.x for n in resolved)
    for n in resolved:
        n.x = target_x
    return {
        "ok": True,
        "aligned": len(resolved),
        "count": len(resolved),
        "node_ids": [n.id for n in resolved],
        "x": round(target_x),
    }


def _tool_align_top(ctx: MergeContext, node_ids: list[str]) -> dict[str, Any]:
    """Align a list of nodes to the same y (topmost node's y)."""
    resolved = []
    for nid in node_ids:
        n = ctx.nodes_by_id.get(str(nid)) or ctx.nodes_by_name.get(str(nid))
        if not n:
            return {"ok": False, "error": f"node '{nid}' not found"}
        resolved.append(n)
    target_y = min(n.y for n in resolved)
    for n in resolved:
        n.y = target_y
    return {
        "ok": True,
        "aligned": len(resolved),
        "count": len(resolved),
        "node_ids": [n.id for n in resolved],
        "y": round(target_y),
    }


def _tool_distribute_horizontally(ctx: MergeContext, node_ids: list[str], total_width: float | None = None) -> dict[str, Any]:
    """Evenly distribute nodes horizontally. If total_width not given, uses existing span (rightmost - leftmost)."""
    resolved = []
    for nid in node_ids:
        n = ctx.nodes_by_id.get(str(nid)) or ctx.nodes_by_name.get(str(nid))
        if not n:
            return {"ok": False, "error": f"node '{nid}' not found"}
        resolved.append(n)

    if len(resolved) < 2:
        return {"ok": True, "placed": len(resolved), "note": "fewer than 2 nodes, nothing to distribute"}

    if total_width is not None:
        span = float(total_width)
    else:
        span = max(n.x + n.w for n in resolved) - min(n.x for n in resolved)

    resolved.sort(key=lambda n: n.x)
    start_x = resolved[0].x
    gap = (span - sum(n.w for n in resolved)) / (len(resolved) - 1)
    gap = max(0, gap)

    cursor = start_x
    for n in resolved:
        n.x = cursor
        cursor += n.w + gap

    return {"ok": True, "distributed": len(resolved), "span": round(span), "gap": round(gap, 1),
            "positions": [{"id": n.id, "name": n.name, "x": round(n.x), "y": round(n.y)} for n in resolved]}


def _render_preview_png(ctx: MergeContext, *, scope_id: str = "") -> str:
    """Render the current MergeContext as a PNG and return base64 data URL.

    No Playwright, no BI auth. Direct canvas drawing with Pillow.
    Used by the LLM for fast visual self-checking during harness sessions.

    If scope_id is set, only render that container and its descendants.
    """
    from PIL import Image, ImageDraw, ImageFont
    import io

    PAD = 40
    DEPT_BG = (233, 245, 233)
    DEPT_BORDER = (162, 177, 163)
    PERSON_BG = (255, 255, 255)
    PERSON_BORDER = (162, 177, 195)
    TAG_A_COLOR = (66, 133, 244)
    TEXT_COLOR = (50, 50, 50)
    TITLE_COLOR = (30, 30, 30)
    EDGE_COLOR = (162, 177, 195)

    TITLE_H = 24

    if scope_id:
        scope_node = ctx.nodes_by_id.get(scope_id) or ctx.nodes_by_name.get(scope_id)
        if not scope_node:
            raise ValueError(f"scope '{scope_id}' not found")
        render_nodes = [scope_node]
        for n in ctx.all_nodes:
            if n.parent_dept_id == scope_node.id or (
                n.parent_dept_id and any(a.id == n.parent_dept_id for a in render_nodes)
            ):
                render_nodes.append(n)
    else:
        render_nodes = list(ctx.all_nodes)

    if not render_nodes:
        img = Image.new("RGB", (200, 100), (255, 255, 255))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()

    min_x = min(n.x for n in render_nodes if n.w > 0) - PAD
    min_y = min(n.y for n in render_nodes if n.h > 0) - PAD
    max_x = max(n.x + n.w for n in render_nodes) + PAD
    max_y = max(n.y + n.h for n in render_nodes) + PAD

    w = int(max_x - min_x)
    h = int(max_y - min_y)
    w = max(w, 200)
    h = max(h, 100)

    img = Image.new("RGB", (w, h), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    try:
        font_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 13)
        font_body = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 11)
        font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 9)
    except (IOError, OSError):
        font_title = ImageFont.load_default()
        font_body = ImageFont.load_default()
        font_small = ImageFont.load_default()

    def tx(x): return x - min_x
    def ty(y): return y - min_y

    node_map = {n.id: n for n in render_nodes}
    for e in ctx.edges:
        src_id = e.get("source_id", "")
        tgt_id = e.get("target_id", "")
        src = node_map.get(src_id)
        tgt = node_map.get(tgt_id)
        if not src or not tgt:
            continue
        edge_type = e.get("edge_type", "reports_to")
        sx = tx(src.x + src.w / 2)
        sy = ty(src.y + src.h)
        ex = tx(tgt.x + tgt.w / 2)
        ey = ty(tgt.y)
        color = (66, 133, 244) if edge_type == "reports_to" else (200, 200, 200)
        draw.line([(sx, sy), (ex, ey)], fill=color, width=2)
        angle = math.atan2(ey - sy, ex - sx)
        arrow_len = 8
        ax1 = ex - arrow_len * math.cos(angle - 0.4)
        ay1 = ey - arrow_len * math.sin(angle - 0.4)
        ax2 = ex - arrow_len * math.cos(angle + 0.4)
        ay2 = ey - arrow_len * math.sin(angle + 0.4)
        draw.polygon([(ex, ey), (ax1, ay1), (ax2, ay2)], fill=color)

    for n in render_nodes:
        if n.node_type != "dept":
            continue
        x1, y1 = tx(n.x), ty(n.y)
        x2, y2 = tx(n.x + n.w), ty(n.y + n.h)

        draw.rounded_rectangle([x1, y1, x2, y2], radius=8, fill=DEPT_BG, outline=DEPT_BORDER, width=2)

        draw.rectangle([x1, y1, x2, y1 + TITLE_H], fill=(200, 220, 200))
        draw.text((x1 + 8, y1 + 4), n.name, fill=TITLE_COLOR, font=font_title)

    for n in render_nodes:
        if n.node_type != "user":
            continue
        x1, y1 = tx(n.x), ty(n.y)
        x2, y2 = tx(n.x + n.w), ty(n.y + n.h)

        draw.rounded_rectangle([x1, y1, x2, y2], radius=6, fill=PERSON_BG, outline=PERSON_BORDER, width=1)

        name_text = n.name[:6]
        bbox = draw.textbbox((0, 0), name_text, font=font_body)
        tw = bbox[2] - bbox[0]
        draw.text((x1 + (n.w - tw) / 2, y1 + 8), name_text, fill=TEXT_COLOR, font=font_body)

        pos_text = (n.position or n.department or "")[:8]
        if pos_text:
            bbox = draw.textbbox((0, 0), pos_text, font=font_small)
            tw = bbox[2] - bbox[0]
            draw.text((x1 + (n.w - tw) / 2, y1 + 30), pos_text, fill=(120, 120, 120), font=font_small)

        if n.role == "A" or n.tagA == "A":
            cx, cy = x2 - 14, y1 + 14
            r = 10
            draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=TAG_A_COLOR)
            draw.text((cx - 3, cy - 5), "A", fill=(255, 255, 255), font=font_small)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


_SANDBOX_CACHE: dict[str, tuple[float, str]] = {}
_SANDBOX_CACHE_TTL = 60.0


def _ctx_to_getinfo_response(ctx: MergeContext) -> dict[str, Any]:
    """Build a dict matching the BI getInfo API response structure.

    BI's drawNode loop establishes X6 parent-child nesting (dept_node.addChild)
    only when ``is_support || isCustomerSuccessVersion()`` — i.e. the user is a
    CSM viewing 【客户成功】数据. Without those flags, nodes whose
    ``node_parent_dept`` points to a dept are drawn flat and never become
    children of the dept container. Sandbox preview must therefore advertise
    both flags so child departments and users render nested inside their parent.
    """
    ver_id = (
        ctx.bi_ver_info
        or ctx.bi_version
        or ctx.harness_version_id
        or "sandbox"
    )
    support_version = {
        "value": ver_id,
        "text": "【客户成功】数据",
        "ver_name": "【客户成功】数据",
    }
    version_info = [support_version]
    return {
        "node_info": [_power_node_to_bi_info_dict(n) for n in ctx.all_nodes],
        "edge_info": [dict(e) for e in ctx.edges],
        "prj_type": ctx.bi_prj_type or "company",
        "is_support": True,
        "version_info": version_info,
        "version_info_copy": [dict(v) for v in version_info],
        "company_name": ctx.harness_prj_id or "",
        "opp_info": [],
        "owner_info": [],
        "competitor_info": [],
        "contact_info": [],
        "his_arr": [],
        "his_page_size": 0,
        "his_totol_num": 0,
        "jdy_post_node": {},
        "picname": "",
    }


async def _render_sandbox_preview(ctx: MergeContext) -> str:
    """Render current graph by loading the real BI page and intercepting getInfo.

    Playwright loads the live BI page (AntV X6 + dagre), intercepts the getInfo
    AJAX, and returns our in-memory graph. The page renders the layout exactly
    as users see it, then we screenshot the SVG element.
    """
    prj_id = ctx.harness_prj_id or "default"
    headers = ctx.harness_headers or {}

    graph_data = _ctx_to_getinfo_response(ctx)
    graph_json = json.dumps(graph_data, ensure_ascii=False)

    cache_key = str(hash(graph_json))
    now = time.time()
    cached = _SANDBOX_CACHE.get(cache_key)
    if cached and (now - cached[0]) < _SANDBOX_CACHE_TTL:
        return cached[1]

    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Playwright 未安装：pip install playwright && playwright install chromium"
        ) from exc

    url = _SCREENSHOT_URL_TEMPLATE.format(prj_id=prj_id)
    logger.info(
        "sandbox preview: intercepting getInfo for %d nodes, %d edges (prj=%s)",
        len(graph_data["node_info"]), len(graph_data["edge_info"]), prj_id,
    )

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-gpu"],
        )
        try:
            context = await browser.new_context(viewport={"width": 1920, "height": 1080})

            # Inject auth cookies (CAS session) if available, same as _capture_power_map_screenshot
            cookies = ctx.harness_cookies
            if cookies:
                cookie_list = [
                    {"name": k, "value": v, "domain": "crm.finereporthelp.com", "path": "/"}
                    for k, v in cookies.items()
                ]
                await context.add_cookies(cookie_list)

            page = await context.new_page()
            # Set extra headers on page (Bearer token) — must be on page, not just context
            if headers:
                await page.set_extra_http_headers(headers)

            async def handle_route(route):
                if "getInfo" in route.request.url:
                    await route.fulfill(
                        status=200,
                        content_type="application/json;charset=UTF-8",
                        body=graph_json,
                    )
                else:
                    await route.continue_()

            await page.route("**/*", handle_route)
            await page.goto(url, wait_until="networkidle", timeout=30000)

            await page.wait_for_selector(".x6-graph-svg", timeout=15000)
            await page.wait_for_timeout(2000)

            await page.evaluate(
                """
                (function() {
                    try {
                        const svg = document.querySelector('.x6-graph-svg');
                        if (!svg) return;
                        const bbox = svg.getBBox();
                        if (!bbox || bbox.width <= 0) return;
                        const pad = 20;
                        svg.setAttribute('viewBox',
                            (bbox.x - pad) + ' ' + (bbox.y - pad) + ' ' +
                            (bbox.width + pad * 2) + ' ' + (bbox.height + pad * 2));
                        svg.setAttribute('width', bbox.width + pad * 2);
                        svg.setAttribute('height', bbox.height + pad * 2);
                    } catch (e) {}
                })();
                """
            )
            await page.wait_for_timeout(500)

            try:
                element = page.locator(".x6-graph-svg")
                png_bytes = await element.screenshot(type="png")
            except Exception:
                png_bytes = await page.screenshot(type="png", full_page=True)
        finally:
            await browser.close()

    data_url = "data:image/png;base64," + base64.b64encode(png_bytes).decode("ascii")
    _SANDBOX_CACHE[cache_key] = (now, data_url)
    return data_url


async def _tool_render_preview(ctx: MergeContext, scope: str = "") -> dict[str, Any]:
    """Render a dagre compound-graph preview PNG for LLM self-checking."""
    try:
        data_url = await _render_sandbox_preview(ctx)
        ctx.last_screenshot_url = data_url
        return {"ok": True, "scope": scope or "full", "size_bytes": len(data_url)}
    except Exception as exc:
        logger.warning("sandbox preview failed, falling back to Pillow: %s", exc)
        try:
            data_url = _render_preview_png(ctx, scope_id=scope)
            ctx.last_screenshot_url = data_url
            return {"ok": True, "scope": scope or "full", "size_bytes": len(data_url), "fallback": "pillow"}
        except Exception as exc2:
            return {"ok": False, "error": f"preview_failed: {exc2}"}


@dataclass
class HarnessEvent:
    """Event emitted by the streaming harness for SSE delivery."""
    type: str  # "round_start" | "thinking" | "tool_call_start" | "tool_call_delta"
               # | "tool_call" | "tool_result" | "done"
    data: dict[str, Any] = field(default_factory=dict)


# Legacy text-format tool list (kept as fallback for endpoints that don't
# advertise native function-calling support).
_HARNESS_TOOLS: list[dict[str, Any]] = [
    {
        "name": "create_node",
        "description": (
            "Create a node. type ∈ {system, org, department, person}. "
            "parent_id MUST point to a container (system/org/department) — never a person. "
            "For persons, attrs may include role (A/D/I/S) and position. "
            "Membership is recorded via parent_id, NOT a belongs_to edge. "
            "x/y 可省略，后端自动选不冲突的位置；w/h 也可省略，按 type 取默认尺寸。"
        ),
        "args": {
            "type": "'system' | 'org' | 'department' | 'person'",
            "name": "string",
            "parent_id": "string (required for persons)",
            "attrs": "object (optional)",
            "x": "number (optional, 可省略，后端自动选不冲突的位置)",
            "y": "number (optional, 可省略，后端自动选不冲突的位置)",
            "w": "number (optional, 按 type 取默认尺寸)",
            "h": "number (optional, 按 type 取默认尺寸)",
        },
    },
    {
        "name": "create_edge",
        "description": (
            "Create a line edge. edge_type ∈ {reports_to, influences} ONLY. "
            "belongs_to is REJECTED — membership uses parent_id / set_parent."
        ),
        "args": {
            "source_id": "string",
            "target_id": "string",
            "edge_type": "'reports_to' | 'influences'",
        },
    },
    {
        "name": "delete_node",
        "description": (
            "Remove a node. cascade=true (default) recursively deletes all "
            "descendants; cascade=false keeps descendants but clears their parent_id."
        ),
        "args": {"id": "string", "cascade": "boolean (default true)"},
    },
    {
        "name": "delete_edge",
        "description": "Remove a line edge by id.",
        "args": {"id": "string"},
    },
    {
        "name": "list_edges",
        "description": (
            "Query edges by optional filters (source_id, target_id, edge_type). "
            "graph_state already shows all edges with endpoint names — use this "
            "tool only when you need to filter by edge_type, find all edges "
            "involving a specific node, or the graph has >50 edges."
        ),
        "args": {
            "source_id": "string (optional)",
            "target_id": "string (optional)",
            "edge_type": "string (optional, 'reports_to' | 'influences')",
        },
    },
    {
        "name": "update_node",
        "description": (
            "Update mutable node attributes. Allowed keys: name, position, role "
            "(A/D/I/S), tagA, background, node_border_color, if_highLight."
        ),
        "args": {
            "node_id": "string",
            "attrs": "object",
        },
    },
    {
        "name": "update_edge",
        "description": (
            "Re-point an existing edge. Pass at least one of new_source_id / "
            "new_target_id. For reports_to edges, pid is kept in sync."
        ),
        "args": {
            "edge_id": "string",
            "new_source_id": "string (optional)",
            "new_target_id": "string (optional)",
        },
    },
    {
        "name": "validate_structure",
        "description": (
            "Scan for structural issues: parent_id cycles, orphan person nodes, "
            "dangling edges, duplicate names. Returns {ok, issues, total}."
        ),
        "args": {},
    },
    {
        "name": "set_parent",
        "description": (
            "Reparent a node. new_parent_id must be a container (system/org/department) "
            "or empty to detach (make top-level). Cross-level moves are allowed."
        ),
        "args": {
            "node_id": "string",
            "new_parent_id": "string (empty = detach)",
        },
    },
    {
        "name": "relayout",
        "description": (
            "Recompute every coordinate via a compound layered layout (dagre-style). "
            "The ONLY way to change positions. Honors parent_id nesting, reports_to "
            "edges (for layering), influences edges, and layout constraints. Applies "
            "depth-based container styling automatically."
        ),
        "args": {
            "options": (
                "object (optional): {direction: 'TB'|'BT'|'LR'|'RL', nodesep, "
                "ranksep, margin}"
            ),
        },
    },
    {
        "name": "nudge_node",
        "description": (
            "Fallback fine-tune: nudge a single node a few pixels along one direction. "
            "Pass distance to override the default 15px step."
        ),
        "args": {
            "node_id": "string",
            "direction": "'up' | 'down' | 'left' | 'right'",
            "distance": "number (optional, default 15)",
        },
    },
    {
        "name": "check_collisions",
        "description": (
            "Scan node overlaps. scope_id (optional) restricts the scan to a "
            "container's subtree."
        ),
        "args": {"scope_id": "string (optional)"},
    },
    {
        "name": "auto_fix_collisions",
        "description": (
            "Push overlapping nodes apart along minimum separation vector. "
            "Capped at 2 calls per session. Prefer adjusting structure / constraints."
        ),
        "args": {},
    },
    {
        "name": "save_state",
        "description": (
            "Persist all accumulated session changes to BI. Call this ONLY when "
            "the user has explicitly confirmed they want changes saved."
        ),
        "args": {},
    },
    {
        "name": "get_node_geometry",
        "description": "Return {x, y, w, h} for a single node. Use this as a ruler before computing placements.",
        "args": {"node_id": "string"},
    },
    {
        "name": "place_node",
        "description": "Set a node's top-left corner to exact (x, y) coordinates. 注意：移动部门容器时请改用 move_dept_with_children——place_node 只移动容器外壳，子节点的绝对坐标不会跟随，会出现'容器走了人留在原地'。place_node 仅用于移动单个用户节点或独立节点。",
        "args": {"node_id": "string", "x": "number", "y": "number"},
    },
    {
        "name": "move_dept_with_children",
        "description": "把节点及其所有递归子节点整体平移到新位置：先算 delta=new_x-当前x, new_y-当前y，再给节点自身和所有后代统一加上该 delta。不修改 width/height/parent_dept_id。无论是部门容器还是普通节点均可使用（无子节点时等价于单点移动）。移动部门容器时优先使用此工具。",
        "args": {"dept_id": "string", "new_x": "number", "new_y": "number"},
    },
    {
        "name": "resize_container",
        "description": "Set a container's width and height to exact values.",
        "args": {"container_id": "string", "w": "number", "h": "number"},
    },
    {
        "name": "fit_container_to_children",
        "description": "Resize container so its bounding box tightly wraps all direct child nodes + padding. Call after finishing interior layout. 此工具会自动将子部门预对齐到所有人员右侧后再计算包裹尺寸。",
        "args": {"container_id": "string", "padding": "number (default 20)"},
    },
    {
        "name": "arrange_horizontally",
        "description": "Place a list of nodes in a horizontal row from left to right. gap between adjacent nodes (default 30).",
        "args": {"node_ids": "[string]", "start_x": "number", "y": "number", "gap": "number (default 30)"},
    },
    {
        "name": "arrange_vertically",
        "description": "Place a list of nodes in a vertical column from top to bottom. gap between adjacent nodes (default 30).",
        "args": {"node_ids": "[string]", "x": "number", "start_y": "number", "gap": "number (default 30)"},
    },
    {
        "name": "center_above",
        "description": "Center a node horizontally above a group of reference nodes, gap pixels above their top edge (default 80). Core tool for leader centering.",
        "args": {"node_id": "string", "reference_node_ids": "[string]", "gap": "number (default 80)"},
    },
    {
        "name": "center_below",
        "description": "Center a node horizontally below a group of reference nodes, gap pixels below their bottom edge (default 80).",
        "args": {"node_id": "string", "reference_node_ids": "[string]", "gap": "number (default 80)"},
    },
    {
        "name": "align_left",
        "description": "Align a list of nodes to the same x (leftmost node's x).",
        "args": {"node_ids": "[string]"},
    },
    {
        "name": "align_top",
        "description": "Align a list of nodes to the same y (topmost node's y).",
        "args": {"node_ids": "[string]"},
    },
    {
        "name": "distribute_horizontally",
        "description": "Evenly distribute nodes horizontally within total_width (or existing span if not given).",
        "args": {"node_ids": "[string]", "total_width": "number (optional)"},
    },
    {
        "name": "check_geometry",
        "description": (
            "检测指定节点的几何状态，返回涉及这些节点的冲突清单。传入 node_ids 列表，"
            "返回 CRITICAL(同级容器重叠)/HIGH(人员或子部门未包裹)/MEDIUM(同容器人员重叠) 三级冲突。"
            "check_geometry 是按需调用的工具，后端不会自动报告几何冲突。在完成布局调整步骤后主动调用确认。"
        ),
        "args": {"node_ids": "[string]"},
    },
]


# Native OpenAI function-calling tool schema (preferred path).
_HARNESS_TOOLS_OPENAI: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "create_node",
            "description": (
                "Create a node. type ∈ {system, org, department, person}. parent_id "
                "MUST be a container (system/org/department) — passing a person is "
                "rejected. For persons, attrs may include role (A/D/I/S) and position. "
                "Membership uses parent_id; do NOT create a belongs_to edge. "
                "x/y 可省略，后端自动选不冲突的位置；w/h 也可省略，按 type 取默认尺寸。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": ["system", "org", "department", "person"],
                    },
                    "name": {"type": "string"},
                    "parent_id": {
                        "type": "string",
                        "description": "Container id. Required for persons.",
                    },
                    "attrs": {
                        "type": "object",
                        "description": "Optional. For persons: {role, position}.",
                    },
                    "x": {
                        "type": "number",
                        "description": "可省略，后端自动选不冲突的位置。",
                    },
                    "y": {
                        "type": "number",
                        "description": "可省略，后端自动选不冲突的位置。",
                    },
                    "w": {
                        "type": "number",
                        "description": "可省略，按 type 取默认尺寸。",
                    },
                    "h": {
                        "type": "number",
                        "description": "可省略，按 type 取默认尺寸。",
                    },
                },
                "required": ["type", "name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_edge",
            "description": (
                "Create a LINE edge. edge_type ∈ {reports_to, influences} ONLY. "
                "belongs_to is REJECTED — membership goes through parent_id / "
                "set_parent."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "source_id": {"type": "string"},
                    "target_id": {"type": "string"},
                    "edge_type": {
                        "type": "string",
                        "enum": ["reports_to", "influences"],
                    },
                },
                "required": ["source_id", "target_id", "edge_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_node",
            "description": (
                "Remove a node. cascade=true (default) recursively deletes every "
                "descendant; cascade=false keeps descendants but clears their parent_id."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "cascade": {
                        "type": "boolean",
                        "description": "Recursive delete (default true).",
                    },
                },
                "required": ["id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_edge",
            "description": "Remove a line edge by id.",
            "parameters": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                },
                "required": ["id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_edges",
            "description": (
                "Query edges by optional filters (source_id, target_id, edge_type). "
                "graph_state already shows all edges with endpoint names — use this "
                "tool only when you need to filter by edge_type, find all edges "
                "involving a specific node, or the graph has >50 edges."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "source_id": {"type": "string", "description": "Optional source node id or name."},
                    "target_id": {"type": "string", "description": "Optional target node id or name."},
                    "edge_type": {
                        "type": "string",
                        "enum": ["reports_to", "influences"],
                        "description": "Optional edge type filter.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_node",
            "description": (
                "Update mutable attributes. Allowed keys: name, position, role "
                "(A/D/I/S), tagA, background, node_border_color, if_highLight."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "node_id": {"type": "string"},
                    "attrs": {"type": "object"},
                },
                "required": ["node_id", "attrs"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_edge",
            "description": (
                "Re-point an existing edge. Pass at least one of new_source_id / "
                "new_target_id. For reports_to edges, pid is kept in sync."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "edge_id": {"type": "string"},
                    "new_source_id": {"type": "string"},
                    "new_target_id": {"type": "string"},
                },
                "required": ["edge_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "validate_structure",
            "description": (
                "Scan for structural issues: parent_id cycles, orphan person "
                "nodes, dangling edges, duplicate names."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_parent",
            "description": (
                "Reparent a node. new_parent_id must be a container; empty string "
                "detaches the node to top-level. Cross-level moves are allowed "
                "(no need to walk intermediate parents)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "node_id": {"type": "string"},
                    "new_parent_id": {
                        "type": "string",
                        "description": "Container id, or '' to detach.",
                    },
                },
                "required": ["node_id", "new_parent_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "relayout",
            "description": (
                "The ONLY way to change coordinates. Recomputes every node/container "
                "position via a compound layered layout based on parent_id nesting, "
                "reports_to / influences edges, and current layout_constraints. "
                "Applies depth-based container styling automatically."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "options": {
                        "type": "object",
                        "properties": {
                            "direction": {
                                "type": "string",
                                "enum": ["TB", "BT", "LR", "RL"],
                            },
                            "nodesep": {"type": "number"},
                            "ranksep": {"type": "number"},
                            "margin": {"type": "number"},
                        },
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "nudge_node",
            "description": (
                "Fallback fine-tune: nudge one node along a direction. Pass distance "
                "(in px) to override the 15px default."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "node_id": {"type": "string"},
                    "direction": {
                        "type": "string",
                        "enum": ["up", "down", "left", "right"],
                    },
                    "distance": {"type": "number"},
                },
                "required": ["node_id", "direction"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_collisions",
            "description": (
                "Return a collision report. scope_id (optional) restricts the scan "
                "to a container's subtree."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "scope_id": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "auto_fix_collisions",
            "description": (
                "Push overlapping nodes apart along the minimum separation vector. "
                "Capped at 2 calls per harness session — adjust structure or "
                "constraints instead of relying on this."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_state",
            "description": (
                "Persist all accumulated session changes to BI. Call ONLY when the "
                "user explicitly confirms they want changes saved."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_node_geometry",
            "description": "Return {x, y, w, h} for a single node. Use this as a ruler before computing placements.",
            "parameters": {
                "type": "object",
                "properties": {
                    "node_id": {"type": "string"},
                },
                "required": ["node_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "place_node",
            "description": (
                "Set a node's top-left corner to exact (x, y) coordinates. "
                "注意：移动部门容器请改用 move_dept_with_children——place_node "
                "只移动容器外壳，子节点的绝对坐标不会跟随，会出现'容器走了人留在原地'。"
                "place_node 仅用于移动单个用户节点或独立节点。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "node_id": {"type": "string"},
                    "x": {"type": "number"},
                    "y": {"type": "number"},
                },
                "required": ["node_id", "x", "y"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "move_dept_with_children",
            "description": (
                "把节点及其所有递归子节点整体平移到新位置：先算 delta = new_x - 当前x, "
                "new_y - 当前y，再给节点自身和所有后代节点统一加上该 delta。"
                "不修改 width/height/parent_dept_id。"
                "无论是部门容器还是普通节点均可使用（无子节点时等价于单点移动）。"
                "移动部门容器时优先使用此工具。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "dept_id": {"type": "string"},
                    "new_x": {"type": "number"},
                    "new_y": {"type": "number"},
                },
                "required": ["dept_id", "new_x", "new_y"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "resize_container",
            "description": "Set a container's width and height to exact values.",
            "parameters": {
                "type": "object",
                "properties": {
                    "container_id": {"type": "string"},
                    "w": {"type": "number"},
                    "h": {"type": "number"},
                },
                "required": ["container_id", "w", "h"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fit_container_to_children",
            "description": (
                "Resize container so its bounding box tightly wraps all direct "
                "child nodes + padding. Call after finishing interior layout. "
                "此工具会自动将子部门预对齐到所有人员右侧后再计算包裹尺寸。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "container_id": {"type": "string"},
                    "padding": {"type": "number", "description": "Padding in pixels (default 20)."},
                },
                "required": ["container_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "arrange_horizontally",
            "description": (
                "Place a list of nodes in a horizontal row from left to right. "
                "gap between adjacent nodes (default 30)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "node_ids": {"type": "array", "items": {"type": "string"}},
                    "start_x": {"type": "number"},
                    "y": {"type": "number"},
                    "gap": {"type": "number", "description": "Gap between nodes (default 30)."},
                },
                "required": ["node_ids", "start_x", "y"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "arrange_vertically",
            "description": (
                "Place a list of nodes in a vertical column from top to bottom. "
                "gap between adjacent nodes (default 30)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "node_ids": {"type": "array", "items": {"type": "string"}},
                    "x": {"type": "number"},
                    "start_y": {"type": "number"},
                    "gap": {"type": "number", "description": "Gap between nodes (default 30)."},
                },
                "required": ["node_ids", "x", "start_y"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "center_above",
            "description": (
                "Center a node horizontally above a group of reference nodes, "
                "gap pixels above their top edge (default 80). Core tool for "
                "leader centering."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "node_id": {"type": "string"},
                    "reference_node_ids": {"type": "array", "items": {"type": "string"}},
                    "gap": {"type": "number", "description": "Gap above reference top (default 80)."},
                },
                "required": ["node_id", "reference_node_ids"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "center_below",
            "description": (
                "Center a node horizontally below a group of reference nodes, "
                "gap pixels below their bottom edge (default 80)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "node_id": {"type": "string"},
                    "reference_node_ids": {"type": "array", "items": {"type": "string"}},
                    "gap": {"type": "number", "description": "Gap below reference bottom (default 80)."},
                },
                "required": ["node_id", "reference_node_ids"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "align_left",
            "description": "Align a list of nodes to the same x (leftmost node's x).",
            "parameters": {
                "type": "object",
                "properties": {
                    "node_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["node_ids"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "align_top",
            "description": "Align a list of nodes to the same y (topmost node's y).",
            "parameters": {
                "type": "object",
                "properties": {
                    "node_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["node_ids"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "distribute_horizontally",
            "description": (
                "Evenly distribute nodes horizontally within total_width (or "
                "existing span if not given)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "node_ids": {"type": "array", "items": {"type": "string"}},
                    "total_width": {"type": "number", "description": "Optional total span; defaults to current span."},
                },
                "required": ["node_ids"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_geometry",
            "description": (
                "检测指定节点的几何状态，返回涉及这些节点的冲突清单。传入 node_ids 列表，"
                "返回 CRITICAL/HIGH/MEDIUM 三级冲突。按需调用，后端不会自动报告几何冲突。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "node_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "要检测的节点 id 列表，至少一个",
                    },
                },
                "required": ["node_ids"],
            },
        },
    },
]


HARNESS_SYSTEM_PROMPT = """你是权力地图布局 Agent。每轮对话都会自动附带一张沙箱渲染截图——不需要你调任何感知工具，看图即所得。

## 核心原则

1. **截图自动注入**：每轮对话的用户消息中已包含截图，直接看
2. **只调布局工具**：你只能调下面列出的工具，不能调感知/截图工具（已移除）
3. **隶属走 parent_id**：create_node 的 parent_id 表达"X 属于 Y 部门"。create_edge 只接受 reports_to 和 influences
4. **变更最小化**：只改用户要求的，不顺手优化

## 可用工具

### 结构类
- create_node(type, name, parent_id, attrs?) — type ∈ {system,org,department,person}
- delete_node(node_id, cascade=true)
- update_node(node_id, attrs)
- set_parent(node_id, new_parent_id)

### 关系类
- create_edge(source_id, target_id, edge_type) — edge_type ∈ {reports_to, influences}
- delete_edge(edge_id)

### 布局类
- place_node(node_id, x, y) — 只用于移动单个用户节点或独立节点；移动部门容器请用 move_dept_with_children
- move_dept_with_children(dept_id, new_x, new_y) — 把部门容器及其全部后代整体平移；不改 w/h、不改 parent_dept_id
- fit_container_to_children(container_id, padding=20)
- center_above(node_id, reference_node_ids, gap=80)
- arrange_horizontally(node_ids, start_x, y, gap=30)
- arrange_vertically(node_ids, x, start_y, gap=30)

### 验证类
- check_collisions(scope?)
- validate_structure()

### 持久化
- save_state() — 写回 BI，仅在用户确认后调用

## 工作流

每轮你收到截图 + 布局数据（layout_summary），直接判断：
- 布局已经美观 → 回复简短文字说明，不调工具
- 需要调整 → 调布局工具，下一轮会有新截图

常见模式：
**新建部门**: create_node(财务部) → create_node(黄宇, parent_id=财务部, role=A) → create_node(下属们, parent_id=财务部) → create_edge(下属→领导, reports_to) → fit_container_to_children(财务部)
**布局调整**: 看图判断 → place_node / center_above / arrange_horizontally
**删除旧连线**: 从 graph_state / layout_summary 中定位旧边的 id（格式为 `edge_id: [源] --type--> [目标]`，如 `1de3b2: [周浩] --reports_to--> [陈大志]`），直接 delete_edge(edge_id)
**清理多余节点**: delete_node(node_id, cascade=true) 递归删除部门及其全部下属；cascade=false 只删节点、释放子节点

## dept-dept 父子关系补全（必读）

BI 系统只维护 user→dept 的父子关系（`user.parent_dept_id` 指向所属 dept）。dept-dept 嵌套关系（如"华南销售组属于销售部"）在 BI 数据中不存在，需要根据汇报关系（reports_to）推断后用 set_parent 补全。

**推断规则**：若 dept A 的负责人（部长/总监/组长，可通过 position 字段或汇报链顶端识别）向某人汇报，而那个人属于 dept B，则 A.parent_dept_id 应为 B.id。

**时机**：建图完成后、首次调用 fit_container_to_children 或 arrange 之前，集中调用 set_parent 补全所有 dept-dept 关系。

**兜底**：若 fit_container_to_children 返回 `geometric_containment_mismatch` 错误，立即按 warning 中提示的 `geo_contained_dept_ids` 调用 set_parent，然后重试 fit。

## 反模式
- ❌ create_edge 传 belongs_to
- ❌ 容器建完不调 fit_container_to_children
- ❌ 明知有错误旧连线却调 validate_structure 而不调 delete_edge——validate 是诊断工具，不是操作工具。看到旧边直接用 delete_edge 删除
- ❌ 人员离职/调岗不删旧汇报线——必须调 delete_edge 清除旧线再新建
"""



# Legacy text-format response template (used only when falling back to the
# text-based tool-calling protocol).
HARNESS_FALLBACK_RESPONSE_HINT = """【可调用工具】
- 感知: render_screenshot / get_graph_state / get_node_by_visual_reference
- 节点: create_node / delete_node / update_node / set_parent
- 关系: create_edge / delete_edge / update_edge
- 布局: layout_subtree / relayout_siblings / resolve_collisions
- 微调: nudge_node / auto_fix_collisions
- 验证: check_collisions / validate_structure
- 持久化: save_state

【create_node】
- type ∈ {system, org, department, person}
- person 的 attrs: {role: 'A'|'D'|'I'|'S', position: '职位'}
- parent_id 指向容器节点（system/org/department），不指向 person

【create_edge】
- edge_type ∈ {reports_to, influences} 仅这两个
- 隶属关系走 parent_id，不走 edge

【响应格式】仅返回 JSON 数组：
[
  {"tool": "create_node", "args": {"type": "department", "name": "财务部", "parent_id": ""}},
  {"tool": "create_node", "args": {"type": "person", "name": "黄宇", "parent_id": "<dept_id>", "attrs": {"role": "A", "position": "CFO"}}},
  {"tool": "layout_subtree", "args": {"root_node_id": "<dept_id>"}}
]
若无需操作返回 []。
"""


def _parse_harness_tool_calls(text: str) -> list[dict[str, Any]]:
    """Parse a JSON array of tool calls from LLM text. Tolerant of code fences."""
    if not text:
        return []
    s = text.strip()
    if s.startswith("```"):
        s = s.strip("`")
        nl = s.find("\n")
        if nl >= 0:
            s = s[nl + 1:]
        if s.endswith("```"):
            s = s[:-3]
        s = s.strip()
    try:
        arr = json.loads(s)
    except json.JSONDecodeError:
        lb = s.find("[")
        rb = s.rfind("]")
        if lb < 0 or rb <= lb:
            return []
        try:
            arr = json.loads(s[lb:rb + 1])
        except json.JSONDecodeError:
            return []
    if not isinstance(arr, list):
        return []
    out: list[dict[str, Any]] = []
    for item in arr:
        if isinstance(item, dict) and item.get("tool"):
            out.append(item)
    return out


async def _execute_harness_tool(
    ctx: MergeContext,
    name: str,
    args: dict[str, Any],
) -> dict[str, Any]:
    """Dispatch a harness tool call by name + arguments.

    Accepts the native function-calling shape directly (name, input). Callers
    using the legacy `{"tool": ..., "args": {...}}` shape should unpack first.
    """
    tool = str(name or "").strip()
    if not isinstance(args, dict):
        return {"ok": False, "error": "args must be object"}

    # --- Defense B: repeated failed call detection ---
    if tool == "fit_container_to_children":
        _call_key = (tool, frozenset(args.items()))
        _fail_count = sum(1 for _k, _ok in ctx._recent_tool_calls[-5:]
                          if _k == _call_key and not _ok)
        if _fail_count >= 2:
            return {
                "ok": False,
                "error": "repeated_failed_call_blocked",
                "hard_warning": (
                    f"Tool '{tool}' with same args has failed {_fail_count}+ times "
                    f"consecutively. DO NOT retry. Read the previous warning carefully "
                    f"and take a DIFFERENT action."
                ),
            }
        ctx._recent_tool_calls.append((_call_key, False))
    # --- END Defense B ---

    if tool == "render_screenshot":
        return await _tool_render_screenshot(ctx, str(args.get("scope", "")))
    if tool == "render_preview":
        return await _tool_render_preview(ctx, str(args.get("scope", "")))
    if tool == "get_graph_state":
        return _tool_get_graph_state(ctx, str(args.get("scope", "")))
    if tool == "get_node_by_visual_reference":
        return _tool_get_node_by_visual_reference(ctx, str(args.get("description", "")))
    if tool == "create_node":
        return _tool_create_node(
            ctx,
            str(args.get("type", "")),
            str(args.get("name", "")),
            str(args.get("parent_id", "")),
            args.get("attrs") if isinstance(args.get("attrs"), dict) else {},
            x=args.get("x"),
            y=args.get("y"),
            w=args.get("w"),
            h=args.get("h"),
        )
    if tool == "create_edge":
        return _tool_create_edge(
            ctx,
            str(args.get("source_id", "")),
            str(args.get("target_id", "")),
            str(args.get("edge_type", "")),
        )
    if tool == "delete_node":
        cascade_raw = args.get("cascade", True)
        if isinstance(cascade_raw, str):
            cascade_flag = cascade_raw.strip().lower() not in ("false", "0", "no", "")
        else:
            cascade_flag = bool(cascade_raw)
        return _tool_delete_node(ctx, str(args.get("id", "")), cascade=cascade_flag)
    if tool == "delete_edge":
        return _tool_delete_edge(ctx, str(args.get("id", "")))
    if tool == "list_edges":
        return _tool_list_edges(
            ctx,
            str(args.get("source_id", "")),
            str(args.get("target_id", "")),
            str(args.get("edge_type", "")),
        )
    if tool == "update_node":
        return _tool_update_node(
            ctx,
            str(args.get("node_id", "")),
            args.get("attrs") if isinstance(args.get("attrs"), dict) else {},
        )
    if tool == "update_edge":
        return _tool_update_edge(
            ctx,
            str(args.get("edge_id", "")),
            str(args.get("new_source_id", "")),
            str(args.get("new_target_id", "")),
        )
    if tool == "validate_structure":
        return _tool_validate_structure(ctx)
    if tool == "set_parent":
        return _tool_set_parent(
            ctx,
            str(args.get("node_id", "")),
            str(args.get("new_parent_id", "")),
        )
    if tool == "add_layout_constraint":
        return {"ok": True, "note": "deprecated in Route B; use place_node + arrange_* + center_* tools instead"}
    if tool == "remove_layout_constraint":
        return {"ok": True, "note": "deprecated in Route B; use place_node + arrange_* + center_* tools instead"}
    if tool == "list_layout_constraints":
        return {"ok": True, "constraints": [], "note": "deprecated in Route B; use place_node + arrange_* + center_* tools instead"}
    if tool == "relayout":
        return {"ok": True, "note": "deprecated in Route B; use place_node + arrange_* + center_* tools instead"}
    if tool in ("nudge_node", "move_user"):
        dist = args.get("distance")
        try:
            dist_val = float(dist) if dist not in (None, "") else None
        except (TypeError, ValueError):
            dist_val = None
        return _tool_nudge_node(
            ctx,
            str(args.get("node_id", "")),
            str(args.get("direction", "")),
            dist_val,
        )
    if tool == "check_collisions":
        return _tool_check_collisions(ctx, str(args.get("scope_id", "")))
    if tool == "check_geometry":
        node_ids = args.get("node_ids", [])
        if isinstance(node_ids, str):
            node_ids = [x.strip() for x in node_ids.split(",") if x.strip()]
        return _tool_check_geometry(ctx, node_ids)
    if tool == "auto_fix_collisions":
        return _tool_auto_fix_collisions(ctx)
    if tool == "save_state":
        return await _tool_save_state(ctx)
    # ── Route B atomic geometry tools ──
    if tool == "get_node_geometry":
        return _tool_get_node_geometry(ctx, str(args.get("node_id", "")))
    if tool == "place_node":
        return _tool_place_node(ctx, str(args.get("node_id", "")), float(args.get("x", 0)), float(args.get("y", 0)))
    if tool == "move_dept_with_children":
        return _tool_move_dept_with_children(
            ctx,
            str(args.get("dept_id", "")),
            float(args.get("new_x", 0)),
            float(args.get("new_y", 0)),
        )
    if tool == "resize_container":
        return _tool_resize_container(ctx, str(args.get("container_id", "")), float(args.get("w", 0)), float(args.get("h", 0)))
    if tool == "fit_container_to_children":
        pad = args.get("padding", 20)
        try:
            pad = float(pad)
        except (TypeError, ValueError):
            pad = 20.0
        result = _tool_fit_container_to_children(ctx, str(args.get("container_id", "")), pad)
        # Defense B: patch success flag on last recorded call
        if ctx._recent_tool_calls:
            _last_key, _ = ctx._recent_tool_calls[-1]
            ctx._recent_tool_calls[-1] = (_last_key, result.get("ok") is True)
        return result
    if tool == "arrange_horizontally":
        ids = args.get("node_ids", [])
        if isinstance(ids, str):
            ids = [x.strip() for x in ids.split(",") if x.strip()]
        gap_val = args.get("gap", 30)
        try:
            gap_val = float(gap_val)
        except (TypeError, ValueError):
            gap_val = 30.0
        return _tool_arrange_horizontally(ctx, ids, float(args.get("start_x", 0)), float(args.get("y", 0)), gap_val)
    if tool == "arrange_vertically":
        ids = args.get("node_ids", [])
        if isinstance(ids, str):
            ids = [x.strip() for x in ids.split(",") if x.strip()]
        gap_val = args.get("gap", 30)
        try:
            gap_val = float(gap_val)
        except (TypeError, ValueError):
            gap_val = 30.0
        return _tool_arrange_vertically(ctx, ids, float(args.get("x", 0)), float(args.get("start_y", 0)), gap_val)
    if tool == "center_above":
        refs = args.get("reference_node_ids", [])
        if isinstance(refs, str):
            refs = [x.strip() for x in refs.split(",") if x.strip()]
        gap_val = args.get("gap", 80)
        try:
            gap_val = float(gap_val)
        except (TypeError, ValueError):
            gap_val = 80.0
        return _tool_center_above(ctx, str(args.get("node_id", "")), refs, gap_val)
    if tool == "center_below":
        refs = args.get("reference_node_ids", [])
        if isinstance(refs, str):
            refs = [x.strip() for x in refs.split(",") if x.strip()]
        gap_val = args.get("gap", 80)
        try:
            gap_val = float(gap_val)
        except (TypeError, ValueError):
            gap_val = 80.0
        return _tool_center_below(ctx, str(args.get("node_id", "")), refs, gap_val)
    if tool == "align_left":
        ids = args.get("node_ids", [])
        if isinstance(ids, str):
            ids = [x.strip() for x in ids.split(",") if x.strip()]
        return _tool_align_left(ctx, ids)
    if tool == "align_top":
        ids = args.get("node_ids", [])
        if isinstance(ids, str):
            ids = [x.strip() for x in ids.split(",") if x.strip()]
        return _tool_align_top(ctx, ids)
    if tool == "distribute_horizontally":
        ids = args.get("node_ids", [])
        if isinstance(ids, str):
            ids = [x.strip() for x in ids.split(",") if x.strip()]
        tw = args.get("total_width")
        try:
            tw = float(tw) if tw is not None else None
        except (TypeError, ValueError):
            tw = None
        return _tool_distribute_horizontally(ctx, ids, tw)
    # ── Deprecated layout tools (Route B): kept for backward compatibility,
    # return a deprecation note so the LLM switches to atomic geometry tools. ──
    if tool == "layout_subtree":
        root = str(args.get("root_node_id", "") or args.get("root_id", "") or args.get("node_id", ""))
        return {
            "ok": True,
            "root_id": root,
            "note": "deprecated in Route B; use place_node + arrange_* + center_* tools instead",
        }
    if tool == "relayout_siblings":
        parent = str(args.get("parent_id", "") or args.get("container_id", ""))
        return {
            "ok": True,
            "parent_id": parent,
            "note": "deprecated in Route B; use place_node + arrange_* + center_* tools instead",
        }
    if tool == "resolve_collisions":
        scope = str(args.get("scope_id", ""))
        return {
            "ok": True,
            "scope_id": scope,
            "note": "deprecated in Route B; use place_node + arrange_* + center_* tools instead",
        }
    return {"ok": False, "error": f"unknown tool: {tool}"}


def _build_layout_summary(ctx: MergeContext) -> str:
    """Compact JSON summary the LLM can cross-reference with the screenshot."""
    depts: list[dict[str, Any]] = []
    for n in ctx.all_nodes:
        if n.node_type != "dept":
            continue
        children = [
            u.name for u in ctx.all_nodes
            if u.node_type == "user" and u.parent_dept_id == n.id
        ]
        depts.append({
            "name": n.name,
            "x": round(n.x),
            "y": round(n.y),
            "w": round(n.w),
            "h": round(n.h),
            "user_count": len(children),
            "geometry_locked": bool(n.geometry_locked),
        })
    return json.dumps({"departments": depts}, ensure_ascii=False, indent=2)


async def _execute_harness(
    ctx: MergeContext,
    delta: dict[str, Any] | None,
    prj_id: str,
    cfg: SystemConfig,
) -> dict[str, Any]:
    """Vision LLM harness: screenshot → reasoning → layout tool calls.

    Prefers native OpenAI function calling (tools=_HARNESS_TOOLS_OPENAI). If the
    endpoint rejects the tools parameter, falls back to the legacy text-based
    protocol (`_HARNESS_TOOLS` + `_parse_harness_tool_calls`).

    Never raises — degrades gracefully so the main confirm flow continues.
    Returns a summary dict (round count, executed tool count, optional error).
    """
    summary: dict[str, Any] = {"rounds": 0, "executed": 0, "skipped": False, "prj_id": prj_id}

    # Bind harness session context so render_screenshot can re-capture.
    ctx.harness_prj_id = prj_id

    # Edge normalization (idempotent: subsequent calls have no-ops since
    # legacy belongs_to edges are stripped on first pass).
    try:
        _normalize_edges(ctx)
    except Exception:
        logger.exception("harness: _normalize_edges failed (continuing)")

    try:
        # Inject BI auth so the page's getInfo API call succeeds.
        # Without auth the page HTML loads but FineUI's JS can't fetch
        # node data, so .x6-graph-svg never renders.
        from ..crypto_utils import decrypt_secret
        _harness_headers: dict[str, str] = {}
        _auth_token = decrypt_secret(getattr(cfg, "power_map_auth_token_encrypted", None) or "") or ""
        if _auth_token:
            _harness_headers["Authorization"] = f"Bearer {_auth_token}"
        ctx.harness_headers = _harness_headers  # persist for sandbox preview / refresh
        screenshot_url = await _render_sandbox_preview(ctx)
        ctx.last_screenshot_url = screenshot_url
    except Exception as exc:
        logger.warning("harness: screenshot capture failed, skipping harness: %s", exc)
        return {**summary, "skipped": True, "error": "screenshot_failed"}

    try:
        client = _get_llm_client(cfg)
    except Exception as exc:
        logger.warning("harness: LLM client unavailable, skipping: %s", exc)
        return {**summary, "skipped": True, "error": "llm_client_unavailable"}

    model = cfg.nl_chat_model or "gpt-4o"
    use_native_tools = True  # downgraded to False if endpoint rejects tools

    for round_idx in range(5):
        summary["rounds"] = round_idx + 1
        layout_summary = _build_layout_summary(ctx)

        if use_native_tools:
            user_text = (
                f"当前布局数据：\n{layout_summary}\n\n"
                + (
                    "请审视截图，必要时调用布局工具进行美化。"
                    if round_idx == 0
                    else "经过上一轮调整后，请基于新截图判断：现在的布局是否自然？"
                         "如需进一步调整，请继续调用工具；若已美观，回复一句简短文字即可。"
                )
            )
        else:
            tool_defs_json = json.dumps(_HARNESS_TOOLS, ensure_ascii=False, indent=2)
            user_text = (
                f"当前布局数据：\n{layout_summary}\n\n"
                f"可调用工具：\n{tool_defs_json}\n\n"
                + (
                    "请审视截图，输出工具调用 JSON 数组。"
                    if round_idx == 0
                    else "经过上一轮调整后，请基于新截图判断：现在的布局是否自然？"
                         "如需进一步调整，输出 JSON 数组；若已美观，输出 `[]`。"
                )
            )

        content = [
            {"type": "text", "text": user_text},
            {"type": "image_url", "image_url": {"url": screenshot_url}},
        ]

        system_prompt = HARNESS_SYSTEM_PROMPT if use_native_tools else (
            HARNESS_SYSTEM_PROMPT + "\n\n" + HARNESS_FALLBACK_RESPONSE_HINT
        )

        try:
            kwargs: dict[str, Any] = {
                "model": model,
                "system": system_prompt,
                "content": content,
                "max_tokens": 2048,
            }
            if use_native_tools:
                kwargs["tools"] = _HARNESS_TOOLS_OPENAI
            response = await client.messages_create_vision(**kwargs)
        except Exception as exc:
            if use_native_tools and _looks_like_tools_unsupported(exc):
                logger.warning(
                    "harness: tools param unsupported, falling back to text protocol: %s",
                    exc,
                )
                use_native_tools = False
                summary["rounds"] = round_idx  # retry this round on the legacy path
                continue
            logger.warning("harness: vision call failed at round %d: %s", round_idx + 1, exc)
            summary["error"] = f"vision_call_failed_round{round_idx + 1}"
            return summary

        # Native path: read tool_use blocks; legacy path: parse text payload.
        tool_calls: list[tuple[str, dict[str, Any]]] = []
        if use_native_tools:
            for block in response.content:
                if getattr(block, "type", "") == "tool_use":
                    args = block.input if isinstance(block.input, dict) else {}
                    tool_calls.append((str(block.name or ""), args))
        else:
            text = "".join(
                getattr(block, "text", "") for block in response.content
                if hasattr(block, "text")
            )
            for tc in _parse_harness_tool_calls(text):
                args = tc.get("args") or {}
                tool_calls.append((str(tc.get("tool") or ""), args if isinstance(args, dict) else {}))

        logger.info(
            "harness: round %d parsed %d tool calls (native=%s)",
            round_idx + 1, len(tool_calls), use_native_tools,
        )
        if not tool_calls:
            return summary

        for name, args in tool_calls:
            try:
                result = await _execute_harness_tool(ctx, name, args)
            except Exception as exc:
                # Tool implementation raised — log and continue with next tool.
                logger.warning("harness: tool %s raised: %s", name, exc)
                continue
            if result.get("ok"):
                summary["executed"] += 1
            else:
                # Non-ok tool result (e.g. screenshot_failed) is non-fatal:
                # log and continue so a single failed tool doesn't abort the
                # whole harness round.
                logger.warning(
                    "harness: tool %s returned not-ok (continuing): %s",
                    name, result.get("error"),
                )

        # Refresh sandbox preview so LLM sees its own tool call effects.
        try:
            screenshot_url = await _render_sandbox_preview(ctx)
            ctx.last_screenshot_url = screenshot_url
        except Exception as exc:
            logger.warning("harness: sandbox preview failed before round %d: %s", round_idx + 1, exc)
            return summary

    return summary


def _looks_like_tools_unsupported(exc: Exception) -> bool:
    """Heuristic: does the error suggest the endpoint doesn't support tools?"""
    msg = str(exc).lower()
    if "tool" not in msg:
        return False
    return any(
        kw in msg
        for kw in ("unsupport", "not support", "invalid", "unknown", "400")
    )


def _build_graph_state_text(ctx: MergeContext) -> str:
    """Build a compact text summary of the graph for LLM consumption."""
    node_name_map = {n.id: n.name for n in ctx.all_nodes}
    lines = []
    for n in ctx.all_nodes:
        pid_display = "root"
        if n.parent_dept_id and n.parent_dept_id != "root":
            pname = node_name_map.get(n.parent_dept_id)
            if pname:
                pid_display = f"{pname}({n.parent_dept_id[:8]}...)"
            else:
                pid_display = n.parent_dept_id
        extra = []
        role = getattr(n, "role", "")
        position = getattr(n, "position", "")
        if role:
            extra.append(f"role={role}")
        if position:
            extra.append(f"position={position}")
        extra_str = f" [{', '.join(extra)}]" if extra else ""
        lines.append(
            f"  [{n.id}] {n.name} ({n.node_type}){extra_str} "
            f"x={int(n.x)} y={int(n.y)} w={int(n.w)} h={int(n.h)} "
            f"parent={pid_display}"
        )
    edge_lines = []
    for e in ctx.edges:
        eid = e.get("id", "")
        sid = e.get("source_id", "")
        tid = e.get("target_id", "")
        etype = e.get("edge_type", "")
        sname = node_name_map.get(sid, "?")
        tname = node_name_map.get(tid, "?")
        edge_lines.append(
            f"  {eid}: {sname} --{etype}--> {tname} ({sid[:8]}→{tid[:8]})"
        )
    parts = ["## 当前图结构", f"节点 ({len(ctx.all_nodes)}):"] + lines
    if edge_lines:
        parts.append(f"连线 ({len(ctx.edges)}):")
        parts.extend(edge_lines)
    return "\n".join(parts)


_TOOL_TOUCH_RULES: dict[str, dict[str, Any]] = {
    "create_node":              {"type": "node", "source": "result", "path": "node.id"},
    "update_node":              {"type": "node", "source": "args",   "path": "node_id"},
    "delete_node":              {"type": "node", "source": "args",   "path": "node_id"},
    "set_parent":               {"type": "node", "source": "args",   "path": "node_id"},
    "place_node":               {"type": "node", "source": "args",   "path": "node_id"},
    "move_dept_with_children":  {"type": "result_nodes", "source": "result", "path": "moved_node_ids"},
    "resize_container":         {"type": "node", "source": "args",   "path": "node_id"},
    "fit_container_to_children":{"type": "node", "source": "args",   "path": "container_id"},
    "nudge_node":               {"type": "node", "source": "args",   "path": "node_id"},
    "arrange_horizontally":     {"type": "result_nodes", "source": "result", "path": "moved_node_ids"},
    "arrange_vertically":       {"type": "node_list", "source": "args", "path": "node_ids"},
    "distribute_horizontally":  {"type": "node_list", "source": "args", "path": "node_ids"},
    "align_left":               {"type": "node_list", "source": "args", "path": "node_ids"},
    "align_top":                {"type": "node_list", "source": "args", "path": "node_ids"},
    "center_above":             {"type": "center", "source": "args", "paths": ["node_id", "reference_node_ids"]},
    "center_below":             {"type": "center", "source": "args", "paths": ["node_id", "reference_node_ids"]},
    "auto_fix_collisions":      {"type": "result_nodes", "source": "result", "path": "moved_nodes"},
    "relayout":                 {"type": "all_nodes", "source": "special"},
    "create_edge":              {"type": "edge", "source": "result", "path": "edge_id"},
    "update_edge":              {"type": "edge", "source": "args",   "path": "edge_id"},
    "delete_edge":              {"type": "edge", "source": "args",   "path": "edge_id"},
}


def _deep_get(obj: Any, path: str) -> Any:
    keys = path.split(".")
    for k in keys:
        if isinstance(obj, dict):
            obj = obj.get(k)
        else:
            return None
        if obj is None:
            return None
    return obj


def _extract_touched_ids(
    tool_calls: list[tuple[str, dict]],
    tool_results: list[dict],
) -> set[str]:
    touched: set[str] = set()
    for i, (tname, targs) in enumerate(tool_calls):
        rule = _TOOL_TOUCH_RULES.get(tname, {"type": "none"})
        rtype = rule.get("type", "none")
        if rtype == "none":
            continue
        if rtype == "all_nodes":
            return {"__ALL__"}
        source = rule.get("source")
        data = targs if source == "args" else (tool_results[i] if i < len(tool_results) else {})
        if data is None:
            continue
        if rtype == "node":
            val = _deep_get(data, rule["path"])
            if val:
                touched.add(str(val))
        elif rtype == "node_list":
            vals = _deep_get(data, rule["path"])
            if vals and isinstance(vals, list):
                touched.update(str(v) for v in vals)
        elif rtype == "center":
            for path in rule.get("paths", []):
                val = _deep_get(data, path)
                if val:
                    if isinstance(val, list):
                        touched.update(str(v) for v in val)
                    else:
                        touched.add(str(val))
        elif rtype == "result_nodes":
            vals = _deep_get(data, rule["path"])
            if vals and isinstance(vals, list):
                touched.update(str(v) for v in vals)
        elif rtype == "edge":
            val = _deep_get(data, rule["path"])
            if val:
                touched.add(str(val))
    return touched


_TOOL_RESULT_COMPRESS_KEEP_FIELDS: dict[str, tuple[str, ...]] = {
    "create_node": ("node_id", "name", "x", "y", "type"),
    "create_edge": ("edge_id", "source_id", "target_id"),
    "place_node": ("node_id", "x", "y"),
    "move_dept_with_children": ("dept_id", "name", "moved_count", "delta_x", "delta_y"),
    "render_screenshot": (),
    "delete_node": ("node_id", "name", "cascade", "deleted_ids"),
    "delete_edge": ("edge_id", "source_id", "target_id"),
    "update_node": ("node_id", "name", "updated_fields"),
    "update_edge": ("edge_id", "new_source_id", "new_target_id"),
    "set_parent": ("node_id", "name", "new_parent_id", "new_parent_name"),
    "fit_container_to_children": ("container_id", "name", "new_w", "new_h"),
    "resize_container": ("container_id", "w", "h"),
    "arrange_horizontally": ("node_ids", "count"),
    "arrange_vertically": ("node_ids", "count"),
    "align_left": ("node_ids", "count"),
    "align_top": ("node_ids", "count"),
    "nudge_node": ("node_id", "direction", "distance"),
}


def _compress_tool_result_content(tool_name: str, content_str: str) -> str:
    """Compress a tool_result JSON content for older rounds.

    get_graph_state is never compressed (LLM relies on full state). Tools in
    _TOOL_RESULT_COMPRESS_KEEP_FIELDS retain only the listed keys; all other
    tools collapse to {ok, error?}. Compressed payloads carry _compressed=true.
    """
    if tool_name == "get_graph_state":
        return content_str
    try:
        data = json.loads(content_str)
    except (json.JSONDecodeError, TypeError):
        return content_str
    if not isinstance(data, dict):
        return content_str
    out: dict[str, Any] = {"ok": data.get("ok"), "_compressed": True}
    if tool_name in _TOOL_RESULT_COMPRESS_KEEP_FIELDS:
        for k in _TOOL_RESULT_COMPRESS_KEEP_FIELDS[tool_name]:
            if k in data:
                out[k] = data[k]
    if data.get("error") is not None:
        out["error"] = data["error"]
    return json.dumps(out, ensure_ascii=False)


def _strip_images(msg: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of msg with image_url blocks removed from its content list."""
    content = msg.get("content")
    if isinstance(content, list):
        new_content = [
            block for block in content
            if not (isinstance(block, dict) and block.get("type") == "image_url")
        ]
        return {**msg, "content": new_content}
    return msg


def _strip_graph_state_text(msg: dict[str, Any], round_num: int) -> dict[str, Any]:
    """Replace graph_state text blocks with a placeholder for older rounds.

    A gs_text block is identified by content starting with "## 当前图结构" or
    "节点 (". The latest gs_text + screenshot already reflect current state,
    so historical graph dumps are pure redundancy.
    """
    content = msg.get("content")
    placeholder = f"[graph_state at round {round_num} - elided, see latest round]"
    if isinstance(content, list):
        new_content: list[Any] = []
        for block in content:
            if (
                isinstance(block, dict)
                and block.get("type") == "text"
                and isinstance(block.get("text"), str)
                and (
                    block["text"].startswith("## 当前图结构")
                    or block["text"].startswith("节点 (")
                )
            ):
                new_content.append({"type": "text", "text": placeholder})
            else:
                new_content.append(block)
        return {**msg, "content": new_content}
    if isinstance(content, str) and (
        content.startswith("## 当前图结构") or content.startswith("节点 (")
    ):
        return {**msg, "content": placeholder}
    return msg


def _get_round_number(messages: list[dict[str, Any]], index: int) -> int:
    """Return 1-indexed round number for messages[index].

    A round starts at each user message; subsequent assistant/tool messages
    belong to the same round.
    """
    count = 0
    for j in range(index + 1):
        if messages[j].get("role") == "user":
            count += 1
    return count or 1


def _normalize_tool_call_ids(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Re-localize tool_call ids and split multi-tool-call assistant messages.

    Bedrock-backed endpoints (e.g. it-ai.fineres.com) mint a fresh
    ``toolu_bdrk_*`` set per request; any such id carried over from a prior
    round is unknown to the new session and triggers HTTP 400
    (``unexpected tool_use_id found in tool_result blocks``). The streaming
    parser already swaps incoming ``toolu_bdrk_*`` for ``call_<uuid16>`` at
    receive time, but multi-round accumulation has multiple leak points
    (missing-name first-deltas, fallback paths, hand-built history). This
    pass guarantees self-consistent id pairing within every outgoing request.

    Additionally, when an assistant message carries *multiple* tool_calls
    (``len(tool_calls) > 1``), the message is split into N separate
    ``assistant→tool`` pairs.  The it-ai.fineres.com gateway has been
    observed to mishandle OpenAI-to-Anthropic translation of multi-tool
    assistant blocks, dropping or mismatching tool_use ids.  Single-tool
    round-trips work reliably, so we avoid the buggy code-path altogether.
    """
    if not messages:
        return messages
    out: list[dict[str, Any]] = []
    i = 0
    while i < len(messages):
        msg = messages[i]
        if msg.get("role") == "assistant" and (msg.get("tool_calls") or []):
            original_calls = msg.get("tool_calls") or []
            # Generate fresh IDs for every tool_call in this message
            new_ids: list[str] = []
            for _ in original_calls:
                new_ids.append("call_" + uuid.uuid4().hex[:16])

            # Collect the following role=tool messages (belong to this assistant)
            j = i + 1
            tool_msgs: list[dict[str, Any]] = []
            while j < len(messages) and messages[j].get("role") == "tool":
                tool_msgs.append(messages[j])
                j += 1

            if len(original_calls) > 1:
                # ═══ SPLIT path: emit N assistant+tool pairs ═══
                # Avoids the gateway's multi-tool-call translation bug.
                base_msg = {k: v for k, v in msg.items() if k != "tool_calls"}
                for pos, tc in enumerate(original_calls):
                    fresh_id = new_ids[pos]
                    out.append({**base_msg, "tool_calls": [{**tc, "id": fresh_id}]})
                    if pos < len(tool_msgs):
                        out.append({**tool_msgs[pos], "tool_call_id": fresh_id})
            else:
                # ═══ Single tool_call: keep as-is (just regenerate id) ═══
                out.append({**msg, "tool_calls": [{**original_calls[0], "id": new_ids[0]}]})
                if tool_msgs:
                    out.append({**tool_msgs[0], "tool_call_id": new_ids[0]})

            i = j
            continue
        out.append(msg)
        i += 1
    return out


def _build_llm_messages(
    accumulated_messages: list[dict[str, Any]],
    current_round: int,
) -> list[dict[str, Any]]:
    """Construct messages to send to the LLM with old rounds trimmed.

    The most recent 3 rounds are kept intact (including image_url blocks and
    full tool_result payloads). For older rounds, image_url blocks are
    stripped, gs_text blocks in user messages are elided to a placeholder
    (the latest round's gs_text already reflects current state), and
    tool_result content is compressed via _compress_tool_result_content.

    A final pass via ``_normalize_tool_call_ids`` re-localizes every
    tool_use/tool_result id pair so the outgoing payload is self-consistent
    even if accumulated history contains leaked Bedrock-format ids.
    """
    tc_name_map: dict[str, str] = {}
    for m in accumulated_messages:
        if m.get("role") == "assistant":
            for tc in m.get("tool_calls") or []:
                tc_id = tc.get("id") or ""
                name = (tc.get("function") or {}).get("name") or ""
                if tc_id:
                    tc_name_map[tc_id] = name

    result: list[dict[str, Any]] = []
    for i, msg in enumerate(accumulated_messages):
        round_num = _get_round_number(accumulated_messages, i)
        if round_num >= current_round - 2:
            result.append(msg)
            continue
        if msg.get("role") == "tool":
            tc_id = msg.get("tool_call_id") or ""
            tool_name = tc_name_map.get(tc_id, "")
            compressed = _compress_tool_result_content(tool_name, msg.get("content") or "")
            result.append({**msg, "content": compressed})
        elif msg.get("role") == "user":
            result.append(_strip_graph_state_text(_strip_images(msg), round_num))
        else:
            result.append(_strip_images(msg))
    normalized = _normalize_tool_call_ids(result)

    # ── DEBUG: dump normalized messages for Bedrock ID troubleshooting ──
    try:
        import json as _json, os as _os, time as _time
        _dd = "/tmp/llm_debug"
        _os.makedirs(_dd, exist_ok=True)
        _ts = _time.strftime("%Y%m%d_%H%M%S")
        _dp = _os.path.join(_dd, f"build_norm_r{current_round}_{_ts}.json")
        _msgs = []
        for _i, _m in enumerate(normalized):
            _role = _m.get("role", "?")
            _tc_ids = [t.get("id", "?") for t in (_m.get("tool_calls") or [])]
            _tcid = _m.get("tool_call_id", "")
            _cp = ""
            _c = _m.get("content")
            if isinstance(_c, list):
                for _b in _c:
                    if isinstance(_b, dict) and _b.get("type") == "text":
                        _cp += str(_b.get("text", ""))[:100]
                    elif isinstance(_b, dict) and _b.get("type") == "image_url":
                        _cp += "[IMAGE]"
            elif isinstance(_c, str):
                _cp = _c[:100]
            _msgs.append({"idx": _i, "role": _role, "tool_calls_ids": _tc_ids, "tool_call_id": _tcid, "content_preview": _cp})
        with open(_dp, "w", encoding="utf-8") as _f:
            _json.dump(_msgs, _f, ensure_ascii=False, indent=2, default=str)
        logger.info("[norm-debug] dumped %d normalized messages to %s", len(normalized), _dp)
    except Exception:
        pass

    return normalized


async def _run_llm_tool_loop(
    ctx: MergeContext,
    user_text: str,
    system_prompt: str,
    tools: list[dict[str, Any]],
    cfg: SystemConfig,
    screenshot_fn: Callable[[MergeContext], Awaitable[str]],
    max_rounds: int,
    session_id: str = "",
) -> AsyncGenerator[HarnessEvent, None]:
    """Generic vision-LLM tool-calling loop.

    Repeatedly streams the LLM with the latest screenshot, executes any tool
    calls against ``ctx``, refreshes the screenshot via ``screenshot_fn``, and
    yields harness events. Stops when the LLM emits no tool calls, when a
    screenshot refresh fails, or after ``max_rounds`` iterations.

    Caller responsibilities:
      - mutate ``ctx`` to its starting state (BI fetch, session bind, etc.)
      - capture the initial screenshot and assign to ``ctx.last_screenshot_url``
      - own any session bookkeeping or harness-specific bookkeeping (e.g. a
        ``submitted`` flag) by observing ``tool_call`` events

    Yields the same event vocabulary as ``_execute_harness_stream`` (round_start,
    thinking, tool_call_start, tool_call_delta, tool_call, tool_result,
    graph_state, done). Includes the native→legacy ``tools`` fallback for
    endpoints that reject the ``tools`` parameter.
    """
    _loop_start_ms = time.time()
    _total_tool_invocations = 0
    try:
        client = _get_llm_client(cfg)
    except Exception as exc:
        logger.warning("llm-loop: LLM client unavailable: %s", exc)
        logger.info(
            "[DEBUG-J] 12.EXIT total_rounds=%d total_tool_calls=%d converged=%s total_ms=%d final_nodes=%d final_edges=%d exit_reason=%s",
            0, 0, "skipped", int((time.time() - _loop_start_ms) * 1000),
            len(ctx.all_nodes), len(ctx.edges), "error",
        )
        yield HarnessEvent(
            type="done",
            data={
                "skipped": True,
                "error": "llm_client_unavailable",
                "rounds": 0,
                "executed": 0,
                "session_id": session_id,
                "exit_reason": "error",
            },
        )
        return

    model = cfg.nl_chat_model or "gpt-4o"
    executed = 0
    rounds_completed = 0
    use_native_tools = True
    accumulated_messages: list[dict[str, Any]] = []

    round_idx = 0
    consecutive_no_tool_rounds = 0
    while round_idx < max_rounds:
        rounds_completed = round_idx + 1
        yield HarnessEvent(
            type="round_start",
            data={"round": rounds_completed, "session_id": session_id},
        )

        _accum_total_chars = sum(len(str(m.get("content", ""))) for m in accumulated_messages)
        _accum_screenshots = 0
        for _m in accumulated_messages:
            _c = _m.get("content")
            if isinstance(_c, list):
                for _blk in _c:
                    if isinstance(_blk, dict) and _blk.get("type") == "image_url":
                        _accum_screenshots += 1
        logger.info(
            "[DEBUG-J] 3.ROUND_START round=%d ctx_nodes=%d ctx_edges=%d accumulated_msgs=%d total_chars=%d screenshots_in_msgs=%d max_rounds=%d consecutive_no_tool=%d",
            rounds_completed, len(ctx.all_nodes), len(ctx.edges),
            len(accumulated_messages), _accum_total_chars, _accum_screenshots,
            max_rounds, consecutive_no_tool_rounds,
        )

        if round_idx == 0:
            gs_text = _build_graph_state_text(ctx)
            logger.info(
                "[DEBUG-J] 10.GRAPH_STATE round=%d text_chars=%d preview=%s",
                rounds_completed, len(gs_text), gs_text[:500],
            )
            accumulated_messages.append({
                "role": "user",
                "content": [
                    {"type": "text", "text": user_text},
                    {"type": "text", "text": gs_text},
                    {"type": "image_url", "image_url": {"url": ctx.last_screenshot_url}},
                ],
            })

        active_system_prompt = system_prompt if use_native_tools else (
            system_prompt + "\n\n" + HARNESS_FALLBACK_RESPONSE_HINT
        )

        legacy_text = ""
        tool_calls: list[tuple[str, dict[str, Any]]] = []
        partial_tool_calls: dict[int, dict[str, Any]] = {}
        assistant_text = ""
        assistant_tool_calls: list[dict[str, Any]] = []

        llm_messages = _build_llm_messages(accumulated_messages, rounds_completed)

        text_chars = sum(len(str(m.get("content", ""))) for m in llm_messages)
        image_count = sum(
            sum(
                1
                for block in (m.get("content") or [])
                if isinstance(block, dict) and block.get("type") == "image_url"
            )
            for m in llm_messages
        )
        approx_tokens = text_chars // 4 + image_count * 2766
        logger.info(
            "[loop] round=%d messages_count=%d approx_tokens=%d images_count=%d text_chars=%d",
            rounds_completed, len(llm_messages), approx_tokens, image_count, text_chars,
        )

        _last_msg = llm_messages[-1] if llm_messages else {}
        _last_msg_role = str(_last_msg.get("role", ""))
        _last_content = _last_msg.get("content")
        if isinstance(_last_content, list):
            _parts: list[str] = []
            for _blk in _last_content:
                if isinstance(_blk, dict):
                    if _blk.get("type") == "text":
                        _parts.append(str(_blk.get("text", "")))
                    elif _blk.get("type") == "image_url":
                        _parts.append("[image]")
            _last_msg_preview = " ".join(_parts)[:500]
        else:
            _last_msg_preview = str(_last_content or "")[:500]
        logger.info(
            "[DEBUG-J] 4.LLM_REQ round=%d model=%s msg_count=%d total_chars=%d est_tokens=%d max_tokens=%d last_msg_role=%s last_msg_preview=%s",
            rounds_completed, model, len(llm_messages), text_chars, approx_tokens, 8192,
            _last_msg_role, _last_msg_preview,
        )
        _llm_req_start = time.time()
        try:
            stream_kwargs: dict[str, Any] = {
                "model": model,
                "system": active_system_prompt,
                "messages": llm_messages,
                "max_tokens": 32768,
            }
            if use_native_tools:
                stream_kwargs["tools"] = tools

            async for chunk in client.messages_create_with_history_stream(**stream_kwargs):
                if use_native_tools and isinstance(chunk, dict):
                    ctype = chunk.get("type")
                    if ctype == "content":
                        text_piece = str(chunk.get("text") or "")
                        if text_piece:
                            assistant_text += text_piece
                            yield HarnessEvent(type="thinking", data={"text_chunk": text_piece})
                    elif ctype == "tool_call_start":
                        idx = int(chunk.get("index") or 0)
                        partial_tool_calls[idx] = {
                            "id": str(chunk.get("id") or ""),
                            "name": str(chunk.get("name") or ""),
                            "arguments": "",
                        }
                        yield HarnessEvent(
                            type="tool_call_start",
                            data={
                                "index": idx,
                                "id": partial_tool_calls[idx]["id"],
                                "name": partial_tool_calls[idx]["name"],
                            },
                        )
                    elif ctype == "tool_call_delta":
                        idx = int(chunk.get("index") or 0)
                        slot = partial_tool_calls.setdefault(
                            idx, {"id": "", "name": "", "arguments": ""}
                        )
                        args_chunk = str(chunk.get("arguments") or "")
                        slot["arguments"] += args_chunk
                        yield HarnessEvent(
                            type="tool_call_delta",
                            data={"index": idx, "arguments": args_chunk},
                        )
                else:
                    text_piece = chunk if isinstance(chunk, str) else ""
                    if text_piece:
                        legacy_text += text_piece
                        assistant_text += text_piece
                        yield HarnessEvent(type="thinking", data={"text_chunk": text_piece})
            _llm_latency_ms = int((time.time() - _llm_req_start) * 1000)
            _tool_names = [
                str(partial_tool_calls[_k].get("name", ""))
                for _k in sorted(partial_tool_calls.keys())
            ]
            _tool_calls_summary = f"{len(_tool_names)}: {_tool_names}"
            _finish_reason = (
                "tool_use" if partial_tool_calls
                else ("stop" if assistant_text else "empty")
            )
            _thinking_preview = (assistant_text or "")[:500]
            logger.info(
                "[DEBUG-J] 5.LLM_RESP round=%d status=%s latency_ms=%d finish_reason=%s thinking_preview=%s tool_calls_summary=%s token_usage=%s",
                rounds_completed, "ok", _llm_latency_ms, _finish_reason,
                _thinking_preview, _tool_calls_summary, "unknown",
            )
        except Exception as exc:
            _llm_latency_ms = int((time.time() - _llm_req_start) * 1000)
            logger.info(
                "[DEBUG-J] 5.LLM_RESP round=%d status=%s latency_ms=%d finish_reason=%s thinking_preview=%s tool_calls_summary=%s token_usage=%s",
                rounds_completed, "error", _llm_latency_ms, "exception",
                str(exc)[:500], "0: []", "unknown",
            )
            if use_native_tools and _looks_like_tools_unsupported(exc):
                logger.warning(
                    "llm-loop: tools param unsupported, falling back to text protocol: %s",
                    exc,
                )
                use_native_tools = False
                continue
            logger.warning("llm-loop: vision call failed at round %d: %s", rounds_completed, exc)
            logger.info(
                "[DEBUG-J] 12.EXIT total_rounds=%d total_tool_calls=%d converged=%s total_ms=%d final_nodes=%d final_edges=%d exit_reason=%s",
                rounds_completed, _total_tool_invocations, "error",
                int((time.time() - _loop_start_ms) * 1000),
                len(ctx.all_nodes), len(ctx.edges), "error",
            )
            yield HarnessEvent(
                type="done",
                data={
                    "skipped": False,
                    "error": f"vision_call_failed_round{rounds_completed}",
                    "rounds": rounds_completed,
                    "executed": executed,
                    "session_id": session_id,
                    "exit_reason": "error",
                },
            )
            return

        if use_native_tools:
            for idx in sorted(partial_tool_calls.keys()):
                slot = partial_tool_calls[idx]
                args_text = slot.get("arguments") or ""
                try:
                    args = json.loads(args_text) if args_text else {}
                except json.JSONDecodeError:
                    # 流式 chunk 边界可能截断右括号 → 尝试自动补全后再解析一次
                    args = None
                    base = (args_text or "").rstrip()
                    if base:
                        open_braces = base.count("{") - base.count("}")
                        suffix = "}" * max(open_braces, 1)
                        try:
                            args = json.loads(base + suffix)
                            logger.warning(
                                "llm-loop: auto-completed truncated JSON for %s (added %d '}')",
                                slot.get("name"), len(suffix),
                            )
                        except json.JSONDecodeError:
                            args = None
                    if args is None:
                        logger.warning(
                            "llm-loop: failed to parse tool arguments for %s: %s",
                            slot.get("name"), args_text[:120],
                        )
                        args = {}
                tool_calls.append((str(slot.get("name") or ""), args if isinstance(args, dict) else {}))
                assistant_tool_calls.append({
                    "id": str(slot.get("id") or ""),
                    "type": "function",
                    "function": {
                        "name": str(slot.get("name") or ""),
                        "arguments": args_text,
                    },
                })
        else:
            for tc in _parse_harness_tool_calls(legacy_text):
                a = tc.get("args") or {}
                tool_calls.append((str(tc.get("tool") or ""), a if isinstance(a, dict) else {}))

        assistant_msg: dict[str, Any] = {
            "role": "assistant",
            "content": assistant_text or None,
        }
        if assistant_tool_calls:
            assistant_msg["tool_calls"] = assistant_tool_calls
        accumulated_messages.append(assistant_msg)

        logger.info(
            "llm-loop: round %d parsed %d tool calls (native=%s)",
            rounds_completed, len(tool_calls), use_native_tools,
        )

        if not tool_calls:
            consecutive_no_tool_rounds += 1
            if consecutive_no_tool_rounds == 1:
                exit_reason = "natural_converge"
                logger.info(
                    "[DEBUG-J] 12.EXIT total_rounds=%d total_tool_calls=%d converged=%s total_ms=%d final_nodes=%d final_edges=%d exit_reason=%s",
                    rounds_completed, _total_tool_invocations, "true",
                    int((time.time() - _loop_start_ms) * 1000),
                    len(ctx.all_nodes), len(ctx.edges), exit_reason,
                )
                yield HarnessEvent(
                    type="done",
                    data={
                        "rounds": rounds_completed,
                        "executed": executed,
                        "session_id": session_id,
                        "converged": True,
                        "exit_reason": exit_reason,
                    },
                )
                return
            if consecutive_no_tool_rounds >= 3:
                exit_reason = "consecutive_no_tool"
                logger.info(
                    "[DEBUG-J] 12.EXIT total_rounds=%d total_tool_calls=%d converged=%s total_ms=%d final_nodes=%d final_edges=%d exit_reason=%s",
                    rounds_completed, _total_tool_invocations, "true",
                    int((time.time() - _loop_start_ms) * 1000),
                    len(ctx.all_nodes), len(ctx.edges), exit_reason,
                )
                yield HarnessEvent(
                    type="done",
                    data={
                        "rounds": rounds_completed,
                        "executed": executed,
                        "session_id": session_id,
                        "converged": True,
                        "exit_reason": exit_reason,
                    },
                )
                return
            # consecutive_no_tool_rounds == 2: give LLM one more chance
            accumulated_messages.append({
                "role": "user",
                "content": [{"type": "text", "text": "请继续确认当前状态，如有需要调整的地方请调用工具。"}],
            })
            round_idx += 1
            continue

        _total_tool_invocations += len(tool_calls)
        consecutive_no_tool_rounds = 0
        for name, args in tool_calls:
            yield HarnessEvent(type="tool_call", data={"tool": name, "args": args})

        tool_results: list[dict[str, Any]] = []
        for i, (name, args) in enumerate(tool_calls):
            _args_str = json.dumps(args, ensure_ascii=False)
            if len(_args_str) > 500:
                _args_str = _args_str[:500] + "...[truncated]"
            _tc_id_log = assistant_tool_calls[i]["id"] if i < len(assistant_tool_calls) else ""
            logger.info(
                "[DEBUG-J] 6.TOOL_IN round=%d idx=%d name=%s tool_call_id=%s args=%s",
                rounds_completed, i, name, _tc_id_log, _args_str,
            )
            try:
                result = await _execute_harness_tool(ctx, name, args)
            except Exception as exc:
                logger.warning("llm-loop: tool %s raised: %s", name, exc)
                logger.info(
                    "[DEBUG-J] 8.TOOL_OUT round=%d idx=%d name=%s ok=%s result_size=%d key_fields=%s error=%s",
                    rounds_completed, i, name, False, 0, "", f"exception: {exc}",
                )
                err_payload = {"ok": False, "error": f"exception: {exc}"}
                tc_id = assistant_tool_calls[i]["id"] if i < len(assistant_tool_calls) else ""
                tool_results.append({
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "content": json.dumps(err_payload, ensure_ascii=False),
                })
                yield HarnessEvent(
                    type="tool_result",
                    data={"tool": name, "ok": False, "error": f"exception: {exc}"},
                )
                continue
            ok = bool(result.get("ok"))
            if ok:
                executed += 1
            tc_id = assistant_tool_calls[i]["id"] if i < len(assistant_tool_calls) else ""
            llm_content = (
                json.dumps(result, ensure_ascii=False)
                if isinstance(result, dict) else str(result)
            )
            tool_results.append({
                "role": "tool",
                "tool_call_id": tc_id,
                "content": llm_content,
            })
            # P0: 完整透传工具返回值给 LLM，token 预算控制避免 SSE 帧过大
            _MAX_TOOL_RESULT_CHARS = 2000
            merged = {"tool": name, "ok": ok, **{k: v for k, v in result.items() if k != "ok"}}
            serialized = json.dumps(merged, ensure_ascii=False)
            if len(serialized) > _MAX_TOOL_RESULT_CHARS:
                # 超大返回值 → 摘要模式：保留关键标量字段
                summary: dict[str, Any] = {"tool": name, "ok": ok, "_truncated": True, "_original_size": len(serialized)}
                for key in ("node_id", "edge_id", "x", "y", "w", "h", "placed", "end_x", "end_y",
                            "total", "child_count", "aligned", "distributed", "fixed", "remaining",
                            "span", "gap", "direction", "distance", "name", "container_id",
                            "total_collisions", "scope", "calls_used", "calls_remaining"):
                    if key in result:
                        summary[key] = result[key]
                evt_data = summary
            else:
                evt_data = merged
            err = result.get("error")
            if err:
                evt_data["error"] = err
            yield HarnessEvent(type="tool_result", data=evt_data)
            _result_size = len(serialized)
            _key_parts: list[str] = []
            if isinstance(result, dict):
                for _k in ("node_id", "edge_id", "x", "y", "name"):
                    if _k in result:
                        _key_parts.append(f"{_k}={result[_k]}")
            _key_fields = ",".join(_key_parts)[:200]
            logger.info(
                "[DEBUG-J] 8.TOOL_OUT round=%d idx=%d name=%s ok=%s result_size=%d key_fields=%s error=%s",
                rounds_completed, i, name, ok, _result_size, _key_fields,
                result.get("error", "") if isinstance(result, dict) else "",
            )

        for tr in tool_results:
            accumulated_messages.append(tr)

        _nodes_snap: list[Any] = []
        for _n in ctx.all_nodes[:50]:
            _nodes_snap.append((
                str(getattr(_n, "id", ""))[:8],
                str(getattr(_n, "name", ""))[:10],
                int(getattr(_n, "x", 0) or 0),
                int(getattr(_n, "y", 0) or 0),
                int(getattr(_n, "w", 0) or 0),
                int(getattr(_n, "h", 0) or 0),
                str(getattr(_n, "parent_dept_id", "") or "")[:8],
            ))
        _edges_snap: list[Any] = []
        for _e in ctx.edges[:50]:
            _edges_snap.append((
                str(_e.get("id", ""))[:8],
                str(_e.get("source_id", ""))[:8],
                str(_e.get("target_id", ""))[:8],
            ))
        logger.info(
            "[DEBUG-J] 9.CTX_SNAPSHOT round=%d nodes=%s edges=%s",
            rounds_completed, _nodes_snap, _edges_snap,
        )

        try:
            graph_state_payload = _tool_get_graph_state(ctx)
        except Exception as exc:
            logger.warning("llm-loop: graph_state snapshot failed: %s", exc)
            graph_state_payload = {"ok": False, "error": str(exc)}
        graph_state_payload["session_id"] = session_id
        yield HarnessEvent(type="graph_state", data=graph_state_payload)

        _ss_start = time.time()
        try:
            screenshot_url = await screenshot_fn(ctx)
            ctx.last_screenshot_url = screenshot_url
            logger.info(
                "[DEBUG-J] 11.SCREENSHOT round=%d ok=%s base64_len=%d render_ms=%d",
                rounds_completed, True,
                len(screenshot_url) if isinstance(screenshot_url, str) else 0,
                int((time.time() - _ss_start) * 1000),
            )
        except Exception as exc:
            logger.info(
                "[DEBUG-J] 11.SCREENSHOT round=%d ok=%s base64_len=%d render_ms=%d",
                rounds_completed, False, 0,
                int((time.time() - _ss_start) * 1000),
            )
            logger.warning(
                "llm-loop: screenshot refresh failed before round %d: %s",
                rounds_completed + 1, exc,
            )
            logger.info(
                "[DEBUG-J] 12.EXIT total_rounds=%d total_tool_calls=%d converged=%s total_ms=%d final_nodes=%d final_edges=%d exit_reason=%s",
                rounds_completed, _total_tool_invocations, "false",
                int((time.time() - _loop_start_ms) * 1000),
                len(ctx.all_nodes), len(ctx.edges), "error",
            )
            yield HarnessEvent(
                type="done",
                data={
                    "rounds": rounds_completed,
                    "executed": executed,
                    "session_id": session_id,
                    "exit_reason": "error",
                },
            )
            return

        gs_text = _build_graph_state_text(ctx)
        logger.info(
            "[DEBUG-J] 10.GRAPH_STATE round=%d text_chars=%d preview=%s",
            rounds_completed, len(gs_text), gs_text[:500],
        )
        accumulated_messages.append({
            "role": "user",
            "content": [
                {"type": "text", "text": gs_text},
                {"type": "image_url", "image_url": {"url": screenshot_url}},
            ],
        })

        round_idx += 1

    logger.info(
        "[DEBUG-J] 12.EXIT total_rounds=%d total_tool_calls=%d converged=%s total_ms=%d final_nodes=%d final_edges=%d exit_reason=%s",
        rounds_completed, _total_tool_invocations, "false",
        int((time.time() - _loop_start_ms) * 1000),
        len(ctx.all_nodes), len(ctx.edges), "max_rounds_hit",
    )
    yield HarnessEvent(
        type="done",
        data={
            "rounds": rounds_completed,
            "executed": executed,
            "session_id": session_id,
            "converged": False,
            "exit_reason": "max_rounds_hit",
            "fallback_message": (
                "本次调整未能自动收敛，建议描述更具体的调整需求，"
                "例如：将张强移到黄宇左侧"
            ),
        },
    )


async def _execute_harness_stream(
    company_id: str,
    prj_id: str,
    cfg: SystemConfig,
    current_user: dict[str, Any] | None = None,
    session_id: str = "",
    version: str | None = None,
) -> AsyncGenerator[HarnessEvent, None]:
    """Streaming variant of _execute_harness.

    Prefers native OpenAI function calling; falls back to the legacy text
    protocol if the endpoint rejects the `tools` parameter.

    Yields HarnessEvent at each milestone:
      - round_start: each round begins
      - thinking: each text delta from the streaming vision LLM (reasoning
        before tool calls; or the model's final reply when no tools are used)
      - tool_call_start: a new tool call begins (native function-calling path)
      - tool_call_delta: incremental JSON argument chunk
      - tool_call: a fully-assembled tool call (before execution)
      - tool_result: each tool execution outcome
      - done: harness complete

    Builds an in-memory MergeContext from the current BI state; tool executions
    mutate that ctx only (no BI submit). Degrades gracefully on screenshot or
    LLM failure — emits a `done` event with diagnostic data.
    """
    # 1. Resolve session: reuse cached ctx if a valid session_id was passed,
    # otherwise fetch fresh state from BI and seed a new session.
    cached_ctx = _get_session(session_id) if session_id else None
    if cached_ctx is not None:
        ctx = cached_ctx
        active_session_id = session_id
        version_id = ctx.harness_version_id
        logger.info("harness-stream: resumed session %s (nodes=%d edges=%d)",
                    active_session_id, len(ctx.all_nodes), len(ctx.edges))
    else:
        try:
            current = await _fetch_from_external(cfg, prj_id, current_user, version=version)
        except Exception as exc:
            logger.warning("harness-stream: failed to fetch current BI state: %s", exc)
            yield HarnessEvent(type="done", data={"skipped": True, "error": "fetch_failed", "rounds": 0, "executed": 0})
            return

        current_nodes_raw = current.get("nodes", [])
        current_edges_raw = current.get("edges", [])
        current_nodes = [_node_from_bi_dict(n) for n in current_nodes_raw]
        _mark_geometry_anomalies(current_nodes)
        version_id = _extract_version_id(current, version)
        # _fetch_from_external always uses prj_type="opp" for step2 (the actual
        # nodes/edges fetch). bi_ver_info mirrors the resolved version UUID so
        # the sandbox getInfo and save_state see the same identity end-to-end.
        bi_prj_type = "opp"
        bi_ver_info = version_id
        ctx = _build_merge_context(
            current_nodes, current_edges_raw, version_id,
            bi_version=version, bi_prj_type=bi_prj_type, bi_ver_info=bi_ver_info,
        )
        # Normalize edges on initial load so the Agent inherits a clean structure.
        try:
            _normalize_edges(ctx)
        except Exception:
            logger.exception("harness-stream: _normalize_edges failed (continuing)")
        active_session_id = _new_session_id()
        _store_session(active_session_id, ctx)

    # Always rebind persistence context — cfg/cookies may have been refreshed.
    ctx.harness_session_id = active_session_id
    ctx.harness_cfg = cfg
    ctx.harness_current_user = current_user
    ctx.harness_version_id = version_id

    # 2. Capture initial screenshot with BI auth.
    api_cfg = _get_power_map_config(cfg)
    bi_headers: dict[str, str] = {}
    bi_cookies: dict[str, str] | None = None

    if current_user:
        try:
            bi_cookies = await cas_auth_service.get_bi_session({
                "user_id": current_user.get("user_id", ""),
                "username": current_user.get("user_name", ""),
                "bi_service": api_cfg["base_url"],
            })
        except CasAuthError as exc:
            logger.warning("CAS auth unavailable for screenshot: %s", exc)
        except Exception:
            logger.exception("CAS auth unexpected error")

    if not bi_cookies and api_cfg["auth_token"]:
        bi_headers["Authorization"] = f"Bearer {api_cfg['auth_token']}"

    # Bind harness session context for render_screenshot tool calls.
    ctx.harness_prj_id = prj_id
    ctx.harness_cookies = bi_cookies
    ctx.harness_headers = bi_headers or None

    try:
        screenshot_url = await _render_sandbox_preview(ctx)
        ctx.last_screenshot_url = screenshot_url
    except Exception as exc:
        logger.warning("harness-stream: screenshot capture failed: %s", exc)
        yield HarnessEvent(type="done", data={"skipped": True, "error": "screenshot_failed", "rounds": 0, "executed": 0})
        return

    # 3. Acquire LLM client. The loop also acquires one internally; this
    # pre-check yields an `llm_client_unavailable` done event before any
    # round_start so the frontend sees an immediate, terminal signal.
    try:
        client = _get_llm_client(cfg)
    except Exception as exc:
        logger.warning("harness-stream: LLM client unavailable: %s", exc)
        yield HarnessEvent(type="done", data={"skipped": True, "error": "llm_client_unavailable", "rounds": 0, "executed": 0})
        return

    model = cfg.nl_chat_model or "gpt-4o"

    layout_summary = _build_layout_summary(ctx)
    user_text = (
        f"当前布局数据：\n{layout_summary}\n\n"
        "请审视截图，必要时调用布局工具进行美化。"
    )

    async for event in _run_llm_tool_loop(
        ctx=ctx,
        user_text=user_text,
        system_prompt=HARNESS_SYSTEM_PROMPT,
        tools=_HARNESS_TOOLS_OPENAI,
        cfg=cfg,
        screenshot_fn=_render_sandbox_preview,
        max_rounds=5,
        session_id=active_session_id,
    ):
        yield event


async def _fetch_from_external(
    cfg: SystemConfig,
    company_id: str,
    current_user: dict[str, Any] | None = None,
    version: str | None = None,
) -> dict[str, Any]:
    api_cfg = _get_power_map_config(cfg)
    base = api_cfg['base_url']
    get_path = api_cfg['get_path']
    headers: dict[str, str] = {}
    cookies: dict[str, str] | None = None

    if current_user:
        try:
            cookies = await cas_auth_service.get_bi_session({
                "user_id": current_user.get("user_id", ""),
                "username": current_user.get("user_name", ""),
                "bi_service": base,
            })
        except CasAuthError as exc:
            logger.warning("CAS auth unavailable: %s", exc)
        except Exception:
            logger.exception("CAS auth unexpected error")

    if not cookies and api_cfg["auth_token"]:
        headers["Authorization"] = f"Bearer {api_cfg['auth_token']}"

    async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
        url1 = f"{base}{get_path}"
        params1 = {"prj_type": "company", "prj_id": company_id}
        resp1 = await client.get(url1, params=params1, headers=headers, cookies=cookies)
        resp1.raise_for_status()
        meta = resp1.json()
        logger.info("BI getInfo step1 keys: %s", list(meta.keys()) if isinstance(meta, dict) else type(meta).__name__)

        result: dict[str, Any] = {"nodes": [], "edges": []}
        if isinstance(meta, dict):
            for key in ("version_info", "contact_info", "company_name", "owner_info", "opp_info"):
                if key in meta:
                    result[key] = meta[key]

        ver_id = version
        if not ver_id:
            # Try prj_type=opp first for version info (customer success / opportunity view).
            # The company-level version_info may only contain the main version,
            # while opp versions carry the actual power map data.
            try:
                params_opp = {"prj_type": "opp", "prj_id": company_id}
                resp_opp = await client.get(url1, params=params_opp, headers=headers, cookies=cookies)
                resp_opp.raise_for_status()
                opp_meta = resp_opp.json()
                if isinstance(opp_meta, dict):
                    vi = opp_meta.get("version_info") or []
                    if isinstance(vi, list) and vi:
                        ver_id = vi[0].get("value") if isinstance(vi[0], dict) else vi[0]
                if ver_id:
                    # Also merge opp metadata into result
                    for key in ("version_info", "contact_info", "company_name", "owner_info", "opp_info"):
                        if key in opp_meta and key not in result:
                            result[key] = opp_meta[key]
            except Exception:
                logger.debug("prj_type=opp version lookup failed, falling back to company version_info")

        if not ver_id and isinstance(meta, dict):
            vi = meta.get("version_info") or []
            if isinstance(vi, list) and vi:
                ver_id = vi[0].get("value") if isinstance(vi[0], dict) else vi[0]

        if ver_id:
            params2 = {"prj_type": "opp", "ver_info": ver_id, "prj_id": company_id}
            resp2 = await client.get(url1, params=params2, headers=headers, cookies=cookies)
            resp2.raise_for_status()
            data = resp2.json()
            logger.info("BI getInfo step2 keys: %s", list(data.keys()) if isinstance(data, dict) else type(data).__name__)

            if isinstance(data, dict):
                raw_nodes = data.get("node_info") or data.get("nodes") or []
                raw_edges = data.get("edge_info") or data.get("edges") or []
                logger.info("BI step2 raw: node_info=%d edge_info=%d first_node_keys=%s",
                            len(raw_nodes), len(raw_edges),
                            list(raw_nodes[0].keys()) if raw_nodes else "EMPTY")
                TYPE_MAP = {"user": "person", "dept": "department"}
                nodes = []
                for n in raw_nodes:
                    node = dict(n)
                    if "node_type" in node and "type" not in node:
                        node["type"] = TYPE_MAP.get(node["node_type"], node["node_type"])
                    elif "node_type" not in node and "type" in node:
                        node["type"] = TYPE_MAP.get(node["type"], node["type"])
                    nodes.append(node)
                result["nodes"] = nodes
                result["edges"] = raw_edges

        return result


# ═══════════════════════════════════════════════════════════
#  API Functions
# ═══════════════════════════════════════════════════════════

async def _resolve_prj_id(db: Session, cfg: SystemConfig, company_id: str) -> str:
    """Resolve CRM com_id from Jiandaoyun company_id."""
    prj_id = company_id
    try:
        api_key = decrypt_secret(cfg.jiandaoyun_api_key_encrypted) if cfg.jiandaoyun_api_key_encrypted else ""
        app_id = (cfg.jiandaoyun_app_id or "").strip()
        field_mappings = dict((cfg.field_mappings or {}).get("jiandaoyun", {}) or {})
        forms = dict(field_mappings.get("forms") or {})
        main_form = dict(forms.get("客户主表") or {})
        main_entry_id = (cfg.main_entry_id or str(main_form.get("entry_id", ""))).strip()

        if api_key and app_id and main_entry_id:
            from .jiandaoyun_client import JiandaoyunClient
            client = JiandaoyunClient(api_key=api_key)
            profile_data = await client.query_single_data(
                app_id=app_id, entry_id=main_entry_id, data_id=company_id
            )
            profile = profile_data.get("data") if isinstance(profile_data, dict) else profile_data
            if isinstance(profile, dict):
                com_id = profile.get("com_id") or ""
                if com_id:
                    prj_id = com_id
                    logger.info("Resolved com_id=%s for company_id=%s", com_id, company_id)
    except Exception:
        logger.warning("Failed to resolve com_id for company_id=%s, falling back to company_id", company_id)
    return prj_id


def _extract_version_id(current_map_data: dict[str, Any], version: str | None = None) -> str:
    """Extract version_id from map data."""
    ver_id = version or ""
    if not ver_id:
        vi = current_map_data.get("version_info") or []
        if isinstance(vi, list) and vi:
            ver_id = vi[0].get("value") if isinstance(vi[0], dict) else str(vi[0])
    return ver_id


def _extract_version_name(current_map_data: dict[str, Any]) -> str:
    """Extract version_name from map data."""
    vi = current_map_data.get("version_info") or []
    if isinstance(vi, list) and vi:
        first = vi[0]
        if isinstance(first, dict):
            return str(first.get("name") or first.get("label", ""))
        return str(first)
    return ""


async def get_power_map(
    db: Session,
    company_id: str,
    current_user: dict[str, Any] | None = None,
    version: str | None = None,
) -> dict[str, Any]:
    """Fetch power map data from external BI system."""
    cfg = db.get(SystemConfig, 1)
    if not cfg:
        return {"nodes": [], "edges": []}

    prj_id = await _resolve_prj_id(db, cfg, company_id)

    try:
        return await _fetch_from_external(cfg, prj_id, current_user, version)
    except Exception:
        logger.exception("Failed to fetch power map from external system")
        return {"nodes": [], "edges": []}


async def chat_power_map(
    db: Session,
    company_id: str,
    message: str,
    current_user: dict[str, Any] | None = None,
    version: str | None = None,
) -> dict[str, Any]:
    """LLM chat: analyze NL instruction, return semantic delta (no coordinates)."""
    cfg = db.get(SystemConfig, 1)
    if not cfg:
        return {"reply": "系统未初始化", "needs_confirmation": False}

    current_map_data = await get_power_map(db, company_id, current_user, version=version)
    version_id = _extract_version_id(current_map_data, version)
    version_name = _extract_version_name(current_map_data)

    try:
        client = _get_llm_client(cfg)
        model = cfg.nl_chat_model or "qwen-plus"
        temperature = cfg.temperature if cfg.temperature is not None else 0.3
        max_tokens = cfg.max_tokens or 4096

        # Strip CRM position to prevent LLM from using it to override user intent.
        contacts = current_map_data.get("contact_info", [])
        contacts_clean = [{k: v for k, v in c.items() if k != "position"} for c in contacts]

        prompt = POWER_MAP_SYSTEM_PROMPT.format(
            version_name=version_name or "默认版本",
            version_id=version_id,
            company_name=current_map_data.get("company_name", ""),
            current_nodes=json.dumps(current_map_data["nodes"], ensure_ascii=False, indent=2),
            current_edges=json.dumps(current_map_data["edges"], ensure_ascii=False, indent=2),
            available_contacts=json.dumps(contacts_clean, ensure_ascii=False, indent=2),
            user_message=message,
        )

        response = await client.messages_create(
            model=model,
            system=prompt,
            messages=[],
            temperature=temperature,
            max_tokens=max_tokens,
        )
    except Exception as exc:
        logger.exception("power map LLM call failed")
        return {"reply": f"LLM 调用失败：{exc}", "needs_confirmation": False}

    text = ""
    for block in response.content:
        if hasattr(block, "text"):
            text += block.text

    # ── DIAG: dump raw LLM response ──
    logger.info("[DIAG] LLM raw response (first 2000 chars): %s", text[:2000])

    try:
        delta = _parse_llm_output(text, version_id, version_name)
    except json.JSONDecodeError:
        return {"reply": text or "LLM 返回格式异常", "needs_confirmation": False}

    # ── DIAG: dump parsed delta ──
    logger.info(
        "[DIAG] Parsed delta: nodes_add=%d nodes_update=%d nodes_delete=%d moves=%d custom_edges_add=%d custom_edges_delete=%d",
        len(delta.get("nodes_add", [])), len(delta.get("nodes_update", [])),
        len(delta.get("nodes_delete", [])), len(delta.get("moves", [])),
        len(delta.get("custom_edges_add", [])), len(delta.get("custom_edges_delete", [])),
    )
    for n in delta.get("nodes_add", []):
        logger.info(
            "[DIAG]   nodes_add: tmp_id=%s name=%s type=%s dept=%s reports_to=%s tagA=%s",
            n.get("tmp_id",""), n.get("name",""), n.get("node_type",""),
            n.get("department",""), n.get("reports_to",""), n.get("tagA",""),
        )

    explanation = delta.get("explanation", "")
    has_changes = any(delta.get(k) for k in [
        "nodes_add", "nodes_update", "nodes_delete", "moves",
        "custom_edges_add", "custom_edges_delete",
    ])

    logger.info("power map chat result: intent=%s explanation=%s has_changes=%s",
                delta.get("intent"), explanation[:80], has_changes)

    return {
        "reply": explanation,
        "changes": delta,
        "needs_confirmation": has_changes,
    }


async def confirm_power_map(
    db: Session,
    company_id: str,
    proposed_changes: dict[str, Any],
    current_user: dict[str, Any] | None = None,
    version: str | None = None,
) -> dict[str, Any]:
    """v4: Minimum-intrusion confirm. Only touches nodes that need changing."""
    cfg = db.get(SystemConfig, 1)
    if not cfg:
        raise ValueError("系统未初始化")

    prj_id = await _resolve_prj_id(db, cfg, company_id)

    # 1. Fetch current BI data
    current = await _fetch_from_external(cfg, prj_id, current_user, version=version)
    current_nodes_raw = current.get("nodes", [])
    current_edges_raw = current.get("edges", [])
    version_id = _extract_version_id(current, version)
    version_name = _extract_version_name(current)

    # 2. Validate version
    delta_version_id = proposed_changes.get("version_id", "")
    delta_version_name = proposed_changes.get("version_name", "")
    if delta_version_id and version_id and delta_version_id != version_id:
        raise ValueError(f"版本ID不匹配: LLM={delta_version_id}, BI={version_id}")

    # 2.5 v4.1 confirm_token for ripple threshold re-submission
    confirm_token = proposed_changes.get("confirm_token", "")
    allow_large_ripple = proposed_changes.get("scope_declaration", {}).get("allow_large_ripple", False)

    # 3. Convert to internal nodes
    current_nodes = [_node_from_bi_dict(n) for n in current_nodes_raw]

    # 3.5 Mark geometry anomalies (existing user-drawn out-of-bounds nodes)
    _mark_geometry_anomalies(current_nodes)

    # 4. Build merge context
    ctx = _build_merge_context(current_nodes, current_edges_raw, version_id)

    # 5. Apply delta
    ctx = _apply_delta(ctx, proposed_changes)

    # ── DIAG: dump after apply_delta ──
    _diag_nodes = [
        {"id": n.id[-8:], "name": n.name, "type": n.node_type, "pid": n.pid[-8:] if n.pid else "",
         "parent_dept": n.parent_dept_id[-8:] if n.parent_dept_id else "", "role": n.role, "tagA": n.tagA,
         "position": n.position, "x": n.x, "y": n.y}
        for n in ctx.all_nodes
    ]
    _diag_edges = [{"src": e.get("source_id","")[-8:], "tgt": e.get("target_id","")[-8:], "type": e.get("edge_type","")} for e in ctx.edges]
    logger.info("[DIAG] After _apply_delta: nodes=%s edges=%s", json.dumps(_diag_nodes, ensure_ascii=False), json.dumps(_diag_edges, ensure_ascii=False))

    # 6. Compute forced move set (v4: only touch what changed)
    forced = _compute_forced_move_set(ctx, proposed_changes)

    # 7. Meltdown check
    _scope_meltdown_check(forced, proposed_changes)

    # 8. Route B: LLM handles all positioning via atomic tools during the
    # harness session. _local_layout is demoted to a fallback — only run
    # when the LLM didn't place nodes (all forced nodes still at 0,0).
    id_to_node = {n.id: n for n in ctx.all_nodes}
    ripple = RippleReport()
    logger.info("[DIAG] forced set (first 10 of %d): %s", len(forced), list(forced)[:10])
    _all_forced_at_origin = all(
        id_to_node.get(nid) and id_to_node[nid].x == 0 and id_to_node[nid].y == 0
        for nid in forced
    ) if forced else False
    if _all_forced_at_origin:
        logger.info("[DIAG] All forced nodes at origin — running _local_layout fallback")
        _local_layout(ctx, forced, proposed_changes)
    else:
        logger.info("[DIAG] LLM positioned nodes — skipping _local_layout (Route B)")

    # ── DIAG: dump after layout ──
    _diag_nodes2 = [
        {"id": n.id[-8:], "name": n.name, "type": n.node_type,
         "x": round(n.x), "y": round(n.y), "w": round(n.w), "h": round(n.h),
         "parent_dept": n.parent_dept_id[-8:] if n.parent_dept_id else ""}
        for n in ctx.all_nodes
    ]
    logger.info("[DIAG] After _local_layout: %s", json.dumps(_diag_nodes2, ensure_ascii=False))

    # ── Route B: adaptive push is obsolete — LLM handles collision resolution
    # via rearrange tools. Only run as fallback when _local_layout was used.
    if _all_forced_at_origin:
        top_groups = _build_rigid_groups_v2(ctx.all_nodes)
        for nid in forced:
            node = id_to_node.get(nid)
            if node and node.node_type == "user":
                adaptive_push_v2(node, top_groups, ripple)
        for nid in forced:
            node = id_to_node.get(nid)
            if node and node.node_type == "dept":
                adaptive_push_v2(node, top_groups, ripple)
        _check_ripple_threshold(ripple, proposed_changes)

    # 8.5 Vision harness: ask a vision LLM to polish aesthetics on the live render.
    # Mutates ctx in place; degrades gracefully if screenshot/LLM unavailable.
    harness_report: dict[str, Any] = {}
    try:
        harness_report = await _execute_harness(ctx, proposed_changes, prj_id, cfg)
    except Exception:
        logger.exception("harness: unexpected failure (continuing without harness)")
        harness_report = {"skipped": True, "error": "unexpected"}

    # 9. Pre-submit version validation
    pre_check = await _fetch_from_external(cfg, prj_id, current_user, version=version)
    pre_version_name = _extract_version_name(pre_check)
    if version_name and pre_version_name and pre_version_name != version_name:
        raise ValueError(f"提交前校验失败: 版本名已变更 ({version_name} → {pre_version_name})")

    # 10. Snapshot before positions
    before_items = _build_bbox_items(current_nodes)

    # 11. Submit to BI
    result = await _submit_to_bi(cfg, prj_id, version_id, ctx.all_nodes, ctx.edges, current_user, ctx=ctx)

    # 12. Post-submit verification: collision-free guarantee
    _post_submit_verify(_build_bbox_items(ctx.all_nodes))

    warnings = ctx.warnings
    return {
        "success": True,
        "message": f"已更新：{len(ctx.all_nodes)} 节点，{len(ctx.edges)} 连线（v4 最小侵入：移动 {len(forced)} 个节点）",
        "result": result,
        "warnings": warnings if warnings else [],
        "forced_moves": len(forced),
        "ripple_report": ripple.to_dict(),
        "harness_report": harness_report,
    }


async def relayout_power_map(
    db: Session,
    company_id: str,
    mode: str = "new_nodes_only",
    dept_id: str | None = None,
    current_user: dict[str, Any] | None = None,
    version: str | None = None,
) -> dict[str, Any]:
    """v4 relayout modes.

    Args:
        mode:
            "new_nodes_only" (A) — only reorganize nodes added in this session
            "single_dept" (B) — compact tree relayout for one dept (requires dept_id)
            "full" (C) — global relayout (nuclear option, unchanged from v3.1 behavior)
    """
    cfg = db.get(SystemConfig, 1)
    if not cfg:
        raise ValueError("系统未初始化")

    prj_id = await _resolve_prj_id(db, cfg, company_id)
    current = await _fetch_from_external(cfg, prj_id, current_user, version=version)
    current_nodes_raw = current.get("nodes", [])
    current_edges_raw = current.get("edges", [])
    version_id = _extract_version_id(current, version)
    version_name = _extract_version_name(current)
    current_nodes = [_node_from_bi_dict(n) for n in current_nodes_raw]
    _mark_geometry_anomalies(current_nodes)
    current_edges = [dict(e) for e in current_edges_raw]

    if mode == "new_nodes_only":
        # Mode A: Only touch nodes without valid positions (x=0,y=0 after layout)
        forced = {n.id for n in current_nodes if n.x == 0 and n.y == 0}
        ctx = MergeContext()
        ctx.all_nodes = current_nodes
        ctx.edges = current_edges
        _local_layout(ctx, forced)
        result = await _submit_to_bi(cfg, prj_id, version_id, current_nodes, current_edges, current_user)
        return {
            "success": True,
            "message": f"整理完成（模式A）：{len(current_nodes)} 节点，{len(current_edges)} 连线，移动 {len(forced)} 个新节点",
            "result": result,
        }

    elif mode == "single_dept":
        # Mode B: Compact tree relayout for one dept
        if not dept_id:
            raise ValueError("单部门整理需要 dept_id 参数")
        target_dept = next((n for n in current_nodes if n.id == dept_id and n.node_type == "dept"), None)
        if not target_dept:
            raise ValueError(f"部门 {dept_id} 不存在")
        users_in_dept = [n for n in current_nodes if n.node_type == "user" and n.parent_dept_id == dept_id]
        x_cursor = target_dept.x + DEPT_PAD_LEFT
        y_cursor = target_dept.y + DEPT_PAD_TOP
        row_max_h = 0
        for u in users_in_dept:
            if x_cursor + PERSON_W > target_dept.x + target_dept.w - DEPT_PAD_RIGHT:
                x_cursor = target_dept.x + DEPT_PAD_LEFT
                y_cursor += row_max_h + MIN_GAP_BETWEEN_USERS
                row_max_h = 0
            u.x = x_cursor
            u.y = y_cursor
            x_cursor += PERSON_W + MIN_GAP_BETWEEN_USERS
            row_max_h = max(row_max_h, PERSON_H)
        result = await _submit_to_bi(cfg, prj_id, version_id, current_nodes, current_edges, current_user)
        return {
            "success": True,
            "message": f"整理完成（模式B）：部门 {target_dept.name} 内 {len(users_in_dept)} 人重排",
            "result": result,
        }

    elif mode == "full":
        # Mode C: Full relayout (nuclear — uses v3.1-style global layout)
        _v31_global_layout(current_nodes, current_edges)
        result = await _submit_to_bi(cfg, prj_id, version_id, current_nodes, current_edges, current_user)
        return {
            "success": True,
            "message": f"全量重排完成（模式C）：{len(current_nodes)} 节点，{len(current_edges)} 连线",
            "result": result,
        }

    else:
        raise ValueError(f"未知的 relayout 模式: {mode}")


async def preview_power_map(
    db: Session,
    company_id: str,
    proposed_changes: dict[str, Any],
    current_user: dict[str, Any] | None = None,
    version: str | None = None,
) -> dict[str, Any]:
    """v4 Preview: apply delta + local layout, return positioned nodes WITHOUT submitting to BI."""
    cfg = db.get(SystemConfig, 1)
    if not cfg:
        raise ValueError("系统未初始化")

    prj_id = await _resolve_prj_id(db, cfg, company_id)

    # 1. Fetch current BI data
    current = await _fetch_from_external(cfg, prj_id, current_user, version=version)
    current_nodes_raw = current.get("nodes", [])
    current_edges_raw = current.get("edges", [])
    version_id = _extract_version_id(current, version)
    version_name = _extract_version_name(current)

    # 2. Validate version
    delta_version_id = proposed_changes.get("version_id", "")
    if delta_version_id and version_id and delta_version_id != version_id:
        raise ValueError(f"版本ID不匹配: LLM={delta_version_id}, BI={version_id}")

    # 3. Convert to internal nodes
    current_nodes = [_node_from_bi_dict(n) for n in current_nodes_raw]
    _mark_geometry_anomalies(current_nodes)

    # 4. Detect contradictions
    add_names = set()
    del_keys = set()
    for item in proposed_changes.get("nodes_add", []):
        if isinstance(item, dict):
            add_names.add(str(item.get("name", "")))
    for item in proposed_changes.get("nodes_delete", []):
        if isinstance(item, dict):
            del_keys.add(str(item.get("id_or_name", "")))
        elif isinstance(item, str):
            del_keys.add(item)
    conflicts = add_names & del_keys
    if conflicts:
        raise ValueError(f"语义矛盾: 同时新增和删除 {conflicts}")

    # 5. Apply delta
    ctx = _build_merge_context(current_nodes, current_edges_raw, version_id)
    ctx = _apply_delta(ctx, proposed_changes)

    # 6. Compute forced set and run local layout
    forced = _compute_forced_move_set(ctx, proposed_changes)
    _scope_meltdown_check(forced, proposed_changes)
    _local_layout(ctx, forced, proposed_changes)

    # ── v4.1 adaptive push: resolve space conflicts ──
    ripple = RippleReport()
    top_groups = _build_rigid_groups_v2(ctx.all_nodes)
    id_to_node = {n.id: n for n in ctx.all_nodes}
    for nid in forced:
        node = id_to_node.get(nid)
        if node and node.node_type == "user":
            adaptive_push_v2(node, top_groups, ripple)
    for nid in forced:
        node = id_to_node.get(nid)
        if node and node.node_type == "dept":
            adaptive_push_v2(node, top_groups, ripple)

    # ── v4.1 ripple threshold check (replaces old space meltdowns) ──
    _check_ripple_threshold(ripple, proposed_changes)

    # 7. Convert back to frontend-compatible dict format
    nodes_out = []
    for n in ctx.all_nodes:
        node_dict = {
            "id": n.id,
            "name": n.name,
            "type": _TYPE_TO_BI.get(n.node_type, n.node_type),
            "node_type": n.node_type,
            "x": n.x,
            "y": n.y,
            "position": n.position,
            "department": n.department,
            "phone": n.phone,
            "cont_id": n.cont_id,
            "pid": n.pid,
            "parent_dept_id": n.parent_dept_id,
            "tagA": n.tagA,
            "tagB": n.tagB,
            "tagC_arr": n.tagC_arr,
            "tagD_label": n.tagD_label,
            "tagD_level": n.tagD_level,
            "tagD_other_name": n.tagD_other_name,
            "tagD_other_abbr": n.tagD_other_abbr,
            "information": n.information,
            "school": n.school,
            "hobby": n.hobby,
            "if_highLight": n.if_highLight,
            "node_manager": n.node_manager,
            "node_reach": n.node_reach,
            "node_border_color": n.node_border_color,
            "node_expect": n.node_expect,
            "jdy_id": n.jdy_id,
        }
        if n.node_type == "dept":
            node_dict["node_width"] = n.w
            node_dict["node_height"] = n.h
            node_dict["width"] = n.w
            node_dict["height"] = n.h
            node_dict["node_background"] = n.background or "#e9f5e9"
        else:
            node_dict["node_width"] = PERSON_W
            node_dict["node_height"] = PERSON_H
            node_dict["width"] = PERSON_W
            node_dict["height"] = PERSON_H
        nodes_out.append(node_dict)

    edges_out = [dict(e) for e in ctx.edges]

    # Build response matching get_power_map format
    result = {
        "nodes": nodes_out,
        "edges": edges_out,
        "version_name": version_name,
        "version_id": version_id,
    }
    if "contact_info" in current:
        result["contact_info"] = current["contact_info"]
    if "company_name" in current:
        result["company_name"] = current["company_name"]

    result["ripple_report"] = ripple.to_dict()
    return result


# ═══════════════════════════════════════════════════════════
#  v2: vision LLM + local sandbox (Route B — atomic geometry tools)
# ═══════════════════════════════════════════════════════════

POWER_MAP_SYSTEM_PROMPT_V2 = """你是权力地图（组织架构图）的 AI 助手。你的任务是根据用户的自然语言描述，
调用工具创建和调整组织架构图。严格遵守以下规则。
═══════════════════════════════════════════
【一、节点语义 - 数据模型】
═══════════════════════════════════════════
只有两种节点类型：
- 部门（type=department）：容器节点，可嵌套，可包含其他部门或人员
所有组织层级（集团、控股、公司、子公司、事业部、部门、子部门、组）
统一用 type=department，区别只是嵌套深度和业务叫法。
- 人员（type=user）：叶子节点，必须属于某个部门
**不存在独立的"公司"或"组织"节点类型**，不要使用 type=org / type=company。
嵌套层级判断：
只有当用户明确表达"包含"或"嵌套"语义时，才创建外层容器，否则跳过该层。
示例：
- "建个公司组织架构" → 跳过公司层，顶层直接是部门
- "我们公司叫 XX 科技" → 跳过 XX 科技这层
- "越秀集团下有越秀农业、越秀城建，越秀农业下有 A 部"
→ 越秀集团是顶层容器，越秀农业/城建是子容器，A 部是越秀农业的子容器
- "画 ZZ 控股，包含旗下子公司" → ZZ 控股是顶层容器
其他规则：
- 人员 parent_id 必须指向某个部门容器
- CEO/总裁/董事长作为人员节点放在最高级部门里，不为高管单独建容器
- 汇报关系用 create_edge 表达，不用 parent_id 表达
- create_node 不要传 x/y 坐标，由后端自动放置
═══════════════════════════════════════════
【二、信息提取规范】
═══════════════════════════════════════════
从用户自然语言中提取以下要素：
1. 部门列表（含嵌套关系）
2. 人员列表（姓名 + title 职级 + 所属部门）
3. 汇报关系（谁向谁汇报）
提取规则：
- "X 任 Y" / "X 担任 Y" → 人员 X，title=Y
- "X 下面有 A、B、C" → A、B、C 是 X 的下属
- "都向 X 汇报" → 前面列举的人都 → X
- "X 部门" / "X 部" / "X 组" → 都是 type=department
- title 写法保留用户原文（"销售总监"就是"销售总监"，不要改成"销售部总监"）
═══════════════════════════════════════════
【坐标系 - 必读】
═══════════════════════════════════════════
所有节点的 x/y/w/h 都是**画布绝对坐标**（以画布左上角为原点 (0,0)）。
画布**无限大**，没有固定宽度限制。
关键规则：
- 子节点的绝对坐标落在父容器绝对坐标范围内 = 视觉上嵌套包含
例：父容器 x=100 w=500（范围 100~600），子节点 x=150 → 在父容器内
- 所有工具（create_node, place_node, move_dept_with_children, set_parent, arrange_*,
resize_container, fit_container_to_children 等）输入和输出**全部用绝对坐标**
- **不存在"相对父容器的局部坐标"概念**
- **移动部门容器 = move_dept_with_children；移动单个用户/独立节点 = place_node**
- place_node 只移动节点自身坐标，不会让子节点跟随——所以**禁止**用 place_node 移动部门容器；
那样会出现"容器走了，人留在原地"。
- move_dept_with_children(dept_id, new_x, new_y) 会计算 delta 并对部门容器及其
全部后代（递归 parent_dept_id）统一平移，自动保持嵌套视觉。它不修改 w/h，
所以移动完无需再调 fit_container_to_children；如确需验证，请调
check_geometry(node_ids=[被移动的部门 id])。
误判防范：
- 如果你怀疑"子节点超出父容器"，先从 graph_state 读取数值验证
- 父容器和子容器的 bbox 重叠**是嵌套关系的正常现象**，不是 bug
- 不要因为视觉上"看起来超出"就反复调整坐标，以数值为准
═══════════════════════════════════════════
【几何自查 - 主动调用 check_geometry】
═══════════════════════════════════════════
check_geometry 是按需调用的工具，传入 node_ids 列表，返回涉及这些节点的冲突清单。
后端**不会自动报告**几何冲突，你必须在关键步骤后主动调用确认。
返回的冲突分三级：
- CRITICAL：同级容器重叠（必须修复，否则视觉错乱）
- HIGH：人员或子部门未完全在父容器内（必须修复）
- MEDIUM：同容器人员重叠（建议修复，影响美观）
调用时机由各场景 SOP 明确规定。一般原则：完成布局调整步骤后调用一次，
确认 conflicts 为空再进入下一步。
═══════════════════════════════════════════
【三、命名与去重规则】
═══════════════════════════════════════════
重名处理：
- 检测到同一会话内有重名人员（如两个"张强"）→ 自动加后缀
第一个保持"张强"，第二个改为"张强-1"，第三个"张强-2"，以此类推
- 在 thinking 中说明："检测到重名，已自动重命名为张强、张强-1"
- 不要因重名反问用户，直接处理
同名异写不视为重名：
- "黄宇" vs "黄宇先生" → 视为两个不同的人
- "张强" vs "Zhang Qiang" → 视为两个不同的人
- 完全按用户输入的字符串处理，不做归一化
部门同理：
- "财务部" vs "财务" → 视为两个不同部门，不要主动合并
- 如果用户混用，按出现顺序保留第一次的命名
═══════════════════════════════════════════
【四、默认值规则】
═══════════════════════════════════════════
汇报关系默认：
- 用户在部门内列举了人员但**没明确说汇报关系**
→ 默认全员向该部门负责人汇报
- 部门负责人识别（优先级从高到低）：
1. title 含"总监/CEO/CTO/CFO/COO/总经理/负责人"的人
2. 用户列举的第一个人
3. 如果都没有，跳过该部门的内部汇报关系
title 默认：
- 用户没说 title → title 留空（不要自动填"员工"）
人员数量默认：
- 用户说"几个销售" / "一些工程师" 没说具体数字 → **必须反问澄清**
不要自己假设 2 个或 3 个
═══════════════════════════════════════════
【五、模糊指令 - 反问策略】
═══════════════════════════════════════════
倾向主动反问，不要默认假设后执行。以下情况必须反问：
1. 数量模糊："几个"、"一些"、"多个"、"若干"
→ "您说的'几个销售'具体是几个？请告知人数和姓名。"
2. 范围模糊："看着挺乱的"、"调整一下"、"优化布局"
→ "您希望具体调整什么？例如：
- 移动某个节点的位置
- 改变某人的汇报关系
- 增加或删除节点
请描述具体需求。"
3. 指代不清："那个人"、"上面那个部门"、"刚才说的"
→ 反问澄清具体指哪个
4. 矛盾指令：用户描述自相矛盾（如 A 是 B 子部门，但又说 A 包含 B）
→ 指出矛盾并请用户确认
反问时的工具调用：**不要调用任何工具**，纯文本输出反问内容，自然收敛。
═══════════════════════════════════════════
【六、工作流 SOP】
═══════════════════════════════════════════
收到指令后，第一步在 thinking 中识别场景类型：
- 场景 A（从零新建）：用户描述完整架构，画布为空或几乎为空
- 场景 B（增量新增）：在已有画布上添加部门/人/连线
- 场景 C（调整）：移动、改汇报关系、改职级、改名
- 场景 D（删除）：删除节点或连线
- 场景 E（混合）：用户指令同时包含多种操作 → 按 A→B→C→D 顺序拆解执行
- 场景 F（模糊）：触发反问策略，纯文本回复，不调工具
按对应 SOP 执行，不跳步、不合并、不乱序：
──────────────────────────────────────
【SOP 执行约束 - 强制遵守】
──────────────────────────────────────
1. 严禁跳步
- 必须按 Step 1 → 2 → 3 → 4 → 5 → 6 的顺序执行
- 即使你认为某 Step "好像不必要"或"后端已经处理过了"，也必须执行
- 跳步会导致最终布局不符合产品规范
2. 结构化输出
- 每个 Step 开始时，在 thinking 中第一句话必须是："开始 Step N：step 名称"
- 每个 Step 结束时，在 thinking 中最后一句话必须是："Step N 完成"
- 不允许在一个 thinking 段落里跨多个 Step
- 不允许出现"Step 1 续"、"Step 3"（跳过 Step 2）这种编号
3. 每个 Step 必须有实际工具调用
- 如果某 Step 你判断"无需调整"，也必须至少调用一次相关工具或 check_geometry 确认
- 不允许 Step 直接 thinking 后进入下一 Step 不调工具
──────────────────────────────────────
【场景 A SOP - 从零新建】
──────────────────────────────────────
Step 1：批量创建所有部门容器
操作：
- 调用 create_node 创建所有部门（含顶层 + 子部门）
- 顶层部门 parent_id=None（不填）
- 子部门 parent_id 指向父部门
- 不传 x/y，后端自动放置
完成标志：thinking 输出"Step 1 完成"
Step 2：批量创建所有人员节点
操作：
- 按部门分组调用 create_node
- parent_id 必须指向所属部门
- 不传 x/y
- title 字段填用户原文（如"销售总监"），用户没说则留空
完成标志：thinking 输出"Step 2 完成"
Step 3：调整每个部门内人员布局
必须执行，不允许跳过
对每个部门容器依次执行：
a. 识别该部门的负责人：
- 优先匹配 title 含"总监/CEO/CTO/CFO/COO/总经理/负责人/组长"的人
- 都不匹配取该部门下第一个创建的人员
b. 把负责人放到容器顶部居中：
- 从 graph_state 读取该部门容器的 x, y, w
- 计算负责人位置：
x = 部门容器.x + (部门容器.w - 160) / 2（160 是人员默认宽度）
y = 部门容器.y + 60（60 是容器顶部留白）
- 调用 place_node(负责人 id, x, y)
c. 把下属人员横向排列在负责人下方：
- 收集该部门所有下属人员（除负责人外）
- 调用 arrange_horizontally，起始 x=部门容器.x + 30, y=部门容器.y + 200, 间距 30
- 如果下属人员数 > 6，分批调用（每批最多 6 人，第二批 y+=110 换行）
- 如果部门内包含子部门，把子部门的 node_id 也加入 arrange_horizontally 的 node_ids 列表中
d. 调用 fit_container_to_children(该部门容器 id) 收缩容器到合适尺寸
全部部门处理完后：
e. 调用 check_geometry(node_ids=[所有部门 id + 所有人员 id])
f. 如果有 HIGH 冲突（人员未完全在父容器内）：
- 调用 fit_container_to_children 重新收缩对应容器
- 再次 check_geometry 确认无冲突
g. 如果有 MEDIUM 冲突（同容器人员重叠）：
- 调用 arrange_horizontally 重新排列对应部门人员
- 再次 check_geometry 确认
完成标志：thinking 输出"Step 3 完成"，几何检测无 HIGH 及以上冲突
Step 4：批量创建所有汇报连线
操作：
- 调用 create_edge 创建所有 reports_to 关系
- 跨部门连线：部门负责人 → 上级负责人（如各部门总监 → CEO）
- 部门内连线：下属 → 部门负责人
完成标志：thinking 输出"Step 4 完成"
Step 5：调整顶层部门容器布局（最后做，避免被前面操作破坏）
必须执行，不允许跳过
**核心约束**：本步骤所有"移动部门容器"的操作必须使用 move_dept_with_children
（容器及其全部后代统一平移），**禁止**使用 place_node 移动部门容器，
否则会出现"容器走了，人留在原地"。place_node 仅用于移动单个用户/独立节点。
Step 5a - 排开非最高级的顶层部门：
a. 识别"最高级部门"：
- 优先匹配名称含"总裁办/董事会/集团总部/executive/总公司"
- 都不匹配取用户描述顺序的第一个顶层部门
（即 Step 1 中最早 create_node 创建的顶层部门）
b. 收集"其他顶层部门"：parent_id=None 且不是最高级部门的所有部门
c. 从 graph_state 读取每个其他顶层部门的 w；按顺序计算每个的目标 (new_x, new_y)：
- 第 1 个：new_x = 50
- 第 k 个（k ≥ 2）：new_x = 第 k-1 个的 new_x + 第 k-1 个的 w + 80（间距）
- 所有其他顶层部门统一 new_y = 500
d. 依次对每个其他顶层部门调用 move_dept_with_children(dept_id, new_x, new_y)。
**不要用 arrange_horizontally 排开顶层部门**——它内部走 place_node，
会让子节点留在原地。
Step 5b - 计算最高级部门居中位置：
a. 从 graph_state 读取所有其他顶层部门的 x 和 w（Step 5a 已排开）
b. 计算视觉中点：
leftmost = min(其他顶层部门.x)
rightmost = max(其他顶层部门.x + 其他顶层部门.w)
center_x = (leftmost + rightmost) / 2
c. 计算最高级部门位置：
x = center_x - 最高级部门.w / 2
y = 50
d. 调用 move_dept_with_children(最高级部门 id, x, y)
（**不要用 place_node**——最高级部门里的高管节点必须跟随容器整体平移）
Step 5c - 几何自查：
调用 check_geometry(node_ids=[所有顶层部门 id])
如果有 CRITICAL 冲突（顶层部门重叠）：
- 加大顶层部门之间的间距（如 80→120→150），按 Step 5a 的步骤 d
  用 move_dept_with_children 重新平移
- 再次 check_geometry 确认
完成标志：thinking 输出"Step 5 完成"，顶层几何无 CRITICAL 冲突
Step 6：自然收敛
操作：
- 输出纯文本总结："已完成 X 个部门、Y 个人员、Z 条汇报关系，架构图构建完成。"
- 不再调用任何工具
完成标志：thinking 输出"Step 6 完成，任务结束"
──────────────────────────────────────
【场景 B SOP - 增量新增】
──────────────────────────────────────
Step 1：读取 graph_state，识别已有结构
Step 2：仅创建新增对象（部门/人员/连线），不传 x/y
Step 3：仅对受影响的容器 fit_container_to_children
Step 4：**不重排已有节点**，保护用户已认可的视觉
Step 5：如果新增部门容器迫使已有顶层部门需要让位（如挤在右侧）：
- 移动已有部门容器**必须用 move_dept_with_children**，让子节点跟随
- 移动单个新增用户节点仍用 place_node
Step 6：自然收敛
──────────────────────────────────────
【场景 C SOP - 调整】
──────────────────────────────────────
Step 1：定位目标节点/边
Step 2：按指令类型执行：
- 移动部门容器 → **move_dept_with_children(dept_id, new_x, new_y)**
  （容器及全部后代一起平移；禁止用 place_node 移动部门容器）
- 移动单个用户/独立节点 → place_node(node_id, x, y)
- 改父部门（人员） → 必须先 set_parent 再 place_node（顺序不能反）
- 改父部门（部门容器跨容器迁移） → 先 set_parent，再 move_dept_with_children
- 改职级/改名 → update_node
- 改汇报关系 → delete_edge + create_edge
Step 3：fit_container_to_children 受影响的容器
（注意：move_dept_with_children 不会改 w/h，但如果迁移到新父容器后
新父容器的 bbox 需要收缩才能合理包裹，仍需 fit_container_to_children）
Step 4：自然收敛
──────────────────────────────────────
【场景 D SOP - 删除】
──────────────────────────────────────
特殊规则 - 删除领导：
- 删除有下属的领导 → **只删领导本人**
- 下属保留在原部门，不自动重挂到上级
- 在 thinking 中说明："删除 X，其下属 A、B、C 保留在原部门"
- 不需要反问用户
Step 1：定位目标
Step 2：delete_node 或 delete_edge
Step 3：fit_container_to_children 受影响的容器
Step 4：不为"填补空缺"重排其他节点
（如确需修复布局错位且要平移某个部门容器，使用 move_dept_with_children；
单个用户错位才用 place_node）
Step 5：自然收敛
──────────────────────────────────────
【场景 E SOP - 混合】
──────────────────────────────────────
按 A→B→C→D 顺序拆解，依次执行各场景 SOP 的相关步骤。
例如："把张强移到销售部，再加两个销售"
→ 先执行 C（移动张强）
→ 再执行 B（加两个销售）
→ 注意：B 步骤中如果人数模糊会触发反问（场景 F）
═══════════════════════════════════════════
【七、视觉美学规则】
═══════════════════════════════════════════
核心原则：**留白美观优先于紧凑**
间距规范：
- 容器内人员之间：水平间距 30px，垂直间距 30px
- 容器内边距：左右 30px，上 60px（留给标题），下 30px
- 同级容器之间：间距 80px
- 不同层级之间：垂直间距 150px
布局规范：
- 容器内人员超过 6 人 → 换行（每行最多 6 个）
- 部门负责人居中放在容器顶部
- 同级部门横向均匀分布，居中对齐画布中线
- 子部门作为容器内的特殊"人员"对待，放在最右侧
═══════════════════════════════════════════
【八、工具组合范式 - 易错点】
═══════════════════════════════════════════
移动部门容器 vs 移动单个节点（最常见的坑）：
正确：移动部门容器 → move_dept_with_children(dept_id, new_x, new_y)
（容器及其全部后代一起平移，子节点视觉跟随）
正确：移动单个用户 / 独立节点 → place_node(node_id, x, y)
错误：用 place_node(部门容器 id, ...) 移动部门
（容器走了但子节点的绝对坐标没变，会出现"人留在原地"）
错误：用 arrange_horizontally 排开多个部门容器
（arrange_horizontally 内部走 place_node，对部门容器同样会留下子节点）
跨部门移动人员：
正确：set_parent(node_id, new_parent_id) → place_node(node_id, x, y)
错误：place_node 后再 set_parent（坐标会错乱）
跨容器迁移部门容器：
正确：set_parent(dept_id, new_parent_id) → move_dept_with_children(dept_id, x, y)
错误：set_parent(dept_id, ...) → place_node(dept_id, ...)（子节点会留在原位置）
修改父子嵌套：
正确：set_parent → fit_container_to_children(old_parent) → fit_container_to_children(new_parent)
错误：只 set_parent 不收缩容器
批量创建后布局：
正确：所有 create_node 完成后再统一调 arrange_horizontally
错误：每 create_node 一个就 arrange 一次
删除节点：
正确：delete_node 会自动删除相关 edge，不需要手动删
错误：先手动 delete_edge 再 delete_node（多此一举）
═══════════════════════════════════════════
【九、错误处理与冲突解决】
═══════════════════════════════════════════
工具调用失败：
- parent_id 不存在 → 在 thinking 中说明，跳过该 tool call，继续后续步骤
- 名称冲突 → 按命名规则自动加后缀
- 几何冲突（hard_conflict）→ 调用对应布局工具修复，不要反问用户
优先级冲突（高 → 低）：
1. 用户明确指令
2. 本 prompt 的规则
3. 视觉美学规则
4. 算法默认值
矛盾指令：
- 用户指令前后矛盾 → 反问澄清
- 用户指令与已有结构矛盾 → 反问澄清
═══════════════════════════════════════════
【十、收敛判断】
═══════════════════════════════════════════
满足以下任一条件即应自然收敛（输出纯文本，不调工具）：
1. 完成了对应场景 SOP 的所有步骤
2. 触发反问策略（场景 F）
3. 用户指令已被完整满足，无遗漏要素
4. 遇到无法处理的矛盾或错误，已说明并等待用户
**禁止行为**：
- 不要在用户没要求时"再优化一下"
- 不要重复调用相同的布局工具试探
- 不要在 SOP 完成后追加"美化"步骤
- 输出纯文本总结即视为收敛，不要再调工具
═══════════════════════════════════════════
【十一、上下文边界】
═══════════════════════════════════════════
每次新会话从 BI 拉取最新已提交的架构作为初始状态。
跨会话引用支持范围：
- 支持 "刚才那个销售部" / "上面建的张强"（指当前会话内）
- 支持 "已有的财务部" / "图里的 CEO"（指 BI 已存在的）
- 不支持 "上次那个" / "我昨天加的"（无历史会话记忆，**反问澄清**）
如果用户引用了画布上不存在的节点：
- 反问："您说的 XX 在当前架构中没有找到，请确认或告知具体信息。"
"""


async def _sandbox_screenshot(
    ctx: MergeContext,
    *,
    page: Any,
    session_id: str,
    sandbox_url: str,
) -> str:
    """Reload sandbox page → wait SANDBOX_READY → screenshot .x6-graph-svg → base64 data URL.

    Bound via functools.partial in chat_power_map_v2 so it matches the
    Callable[[MergeContext], Awaitable[str]] contract that _run_llm_tool_loop
    expects for screenshot_fn. ctx is unused here — the sandbox HTML reads the
    in-memory ctx through the X-Sandbox-Session header / mock BI endpoints.
    """
    await page.goto(sandbox_url, wait_until="domcontentloaded")
    ready_result = await page.wait_for_function("window.__SANDBOX_READY__", timeout=10000)
    await page.wait_for_timeout(500)
    svg_count = await page.locator("#graphContainer .x6-graph-svg").count()
    node_count = await page.locator("#graphContainer .x6-node").count()
    logger.info(
        "[screenshot] ready=%s svg_count=%d node_count=%d session=%s",
        ready_result, svg_count, node_count, session_id,
    )
    svg_el = page.locator("#graphContainer .x6-graph-svg").first
    svg_box = await svg_el.bounding_box()
    logger.info(
        "[screenshot] svg_box=%s",
        json.dumps({"x": round(svg_box["x"]), "y": round(svg_box["y"]),
                     "w": round(svg_box["width"]), "h": round(svg_box["height"])}) if svg_box else "None",
    )
    png_bytes = await svg_el.screenshot(type="png")
    return "data:image/png;base64," + base64.b64encode(png_bytes).decode("ascii")


async def chat_power_map_v2(
    db: Session,
    company_id: str,
    message: str,
    current_user: dict[str, Any] | None = None,
    version: str | None = None,
    bi_credentials: dict[str, Any] | None = None,
) -> AsyncGenerator[HarnessEvent, None]:
    """Route B vision-LLM chat against the local sandbox renderer.

    Resolves a MergeContext (resume or fresh-fetch), launches a headless
    Playwright page pointed at /sandbox/render?session_id=..., captures the
    initial screenshot, runs the multi-turn tool loop, and cleans up the
    browser. The session stays in _SESSION_STORE for the configured TTL so
    the caller can commit or discard later.
    """
    _msg_preview = (message or "")[:500]
    logger.info(
        "[DEBUG-J] 1.ENTRY company_id=%s user_msg_preview=%s credential_present=%s ver=%s",
        company_id, _msg_preview, bool(bi_credentials), version,
    )
    # Stage 1·prep
    cfg = db.get(SystemConfig, 1)
    if not cfg:
        yield HarnessEvent(type="done", data={"skipped": True, "error": "系统未初始化", "rounds": 0, "executed": 0})
        return

    cookies = bi_credentials.get("cookies") if bi_credentials else None
    bearer_token = bi_credentials.get("bearer_token") if bi_credentials else None

    prj_id = await _resolve_prj_id(db, cfg, company_id)

    version_id = ""
    _bi_fetch_start = time.time()
    _bi_fetch_ok = False
    try:
        current = await _fetch_from_external(cfg, prj_id, current_user, version=version)
        _bi_fetch_ok = True
    except Exception as exc:
        _bi_fetch_ms = int((time.time() - _bi_fetch_start) * 1000)
        logger.info(
            "[DEBUG-J] 2.SESSION_INIT session_id=%s bi_fetch_ok=%s initial_nodes=%d initial_edges=%d bi_fetch_ms=%d",
            "", False, 0, 0, _bi_fetch_ms,
        )
        logger.warning("chat_v2: failed to fetch current BI state: %s", exc)
        yield HarnessEvent(type="done", data={"skipped": True, "error": "fetch_failed", "rounds": 0, "executed": 0})
        return
    _bi_fetch_ms = int((time.time() - _bi_fetch_start) * 1000)

    nodes_raw = current.get("nodes", [])
    edges_raw = current.get("edges", [])
    nodes = [_node_from_bi_dict(n) for n in nodes_raw]
    _mark_geometry_anomalies(nodes)
    version_id = _extract_version_id(current, version)
    bi_prj_type = "opp"
    bi_ver_info = version_id
    ctx = _build_merge_context(
        nodes, edges_raw, version_id,
        bi_version=version, bi_prj_type=bi_prj_type, bi_ver_info=bi_ver_info,
    )
    ctx.upinfo_users = current.get("contact_info", [])
    try:
        _normalize_edges(ctx)
    except Exception:
        logger.exception("chat_v2: _normalize_edges failed (continuing)")
    active_session_id = _new_session_id()
    _store_session(active_session_id, ctx)
    logger.info(
        "[DEBUG-J] 2.SESSION_INIT session_id=%s bi_fetch_ok=%s initial_nodes=%d initial_edges=%d bi_fetch_ms=%d",
        active_session_id, _bi_fetch_ok, len(ctx.all_nodes), len(ctx.edges), _bi_fetch_ms,
    )

    # Bind persistence context so commit_power_map_session can submit later.
    ctx.harness_session_id = active_session_id
    ctx.harness_cfg = cfg
    ctx.harness_current_user = current_user
    ctx.harness_prj_id = prj_id
    if version_id:
        ctx.harness_version_id = version_id

    # BI credentials carried on ctx so mock BI endpoints / future tools can reuse.
    if cookies:
        ctx.harness_cookies = cookies
    if bearer_token:
        ctx.harness_headers = {"Authorization": f"Bearer {bearer_token}"}

    # Stage 2·render initial screenshot (always — every chat is a fresh session)
    # TODO: hoist `p` / browser into a module-level singleton for throughput.
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        logger.warning("chat_v2: playwright unavailable: %s", exc)
        yield HarnessEvent(type="done", data={"skipped": True, "error": "playwright_unavailable", "rounds": 0, "executed": 0, "session_id": active_session_id})
        return

    # TODO: browser 全局单例优化
    sandbox_base = (os.getenv("SANDBOX_BASE_URL") or "http://localhost:8000").rstrip("/")
    sandbox_url = f"{sandbox_base}/sandbox/render?session_id={active_session_id}"

    p = None
    browser = None
    context = None
    page = None
    try:
        p = await async_playwright().start()
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        context = await browser.new_context(viewport={"width": 1920, "height": 1080})
        page = await context.new_page()
        await page.set_extra_http_headers({"X-Sandbox-Session": active_session_id})

        _ss0_start = time.time()
        try:
            screenshot_url = await _sandbox_screenshot(
                ctx, page=page, session_id=active_session_id, sandbox_url=sandbox_url,
            )
            ctx.last_screenshot_url = screenshot_url
            logger.info(
                "[DEBUG-J] 11.SCREENSHOT round=%d ok=%s base64_len=%d render_ms=%d",
                0, True, len(screenshot_url) if isinstance(screenshot_url, str) else 0,
                int((time.time() - _ss0_start) * 1000),
            )
        except Exception as exc:
            logger.info(
                "[DEBUG-J] 11.SCREENSHOT round=%d ok=%s base64_len=%d render_ms=%d",
                0, False, 0, int((time.time() - _ss0_start) * 1000),
            )
            logger.warning("chat_v2: initial sandbox screenshot failed: %s", exc)
            yield HarnessEvent(type="done", data={"skipped": True, "error": "screenshot_failed", "rounds": 0, "executed": 0, "session_id": active_session_id})
            return

        # Stage 3·LLM loop
        screenshot_fn = functools.partial(
            _sandbox_screenshot,
            page=page, session_id=active_session_id, sandbox_url=sandbox_url,
        )

        # Drop save_state — commit/discard are now external endpoints.
        v2_tools = [
            t for t in _HARNESS_TOOLS_OPENAI
            if t.get("function", {}).get("name") != "save_state"
        ]

        async for event in _run_llm_tool_loop(
            ctx=ctx,
            user_text=message,
            system_prompt=POWER_MAP_SYSTEM_PROMPT_V2,
            tools=v2_tools,
            cfg=cfg,
            screenshot_fn=screenshot_fn,
            max_rounds=50,
            session_id=active_session_id,
        ):
            yield event

    finally:
        # Stage 5·cleanup — keep the session in _SESSION_STORE for commit/discard.
        if page is not None:
            try:
                await page.close()
            except Exception:
                logger.debug("chat_v2: page close raised", exc_info=True)
        if context is not None:
            try:
                await context.close()
            except Exception:
                logger.debug("chat_v2: context close raised", exc_info=True)
        if browser is not None:
            try:
                await browser.close()
            except Exception:
                logger.debug("chat_v2: browser close raised", exc_info=True)
        if p is not None:
            try:
                await p.stop()
            except Exception:
                logger.debug("chat_v2: playwright stop raised", exc_info=True)


async def commit_power_map_session(
    session_id: str,
    db: Session,
) -> dict[str, Any]:
    """Look up the in-memory session, submit ctx to BI, then drop the session."""
    ctx = _get_session(session_id)
    if ctx is None:
        return {"ok": False, "error": "session_not_found"}

    if not ctx.harness_cfg or not ctx.harness_prj_id:
        return {"ok": False, "error": "session_incomplete"}

    try:
        result = await _submit_to_bi(
            cfg=ctx.harness_cfg,
            prj_id=ctx.harness_prj_id,
            version_id=ctx.harness_version_id or ctx.bi_ver_info or "",
            all_nodes=ctx.all_nodes,
            edges=ctx.edges,
            current_user=ctx.harness_current_user,
            ctx=ctx,
        )
    except Exception as exc:
        logger.exception("commit: submit_to_bi failed")
        return {"ok": False, "error": f"submit_failed: {exc}"}

    _drop_session(session_id)
    return {"ok": True, "result": result}


def discard_power_map_session(session_id: str) -> dict[str, Any]:
    """Drop the in-memory session without submitting anything."""
    _drop_session(session_id)
    return {"ok": True}
