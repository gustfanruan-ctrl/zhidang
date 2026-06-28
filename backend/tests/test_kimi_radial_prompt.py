import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.power_map_service import (  # noqa: E402
    POWER_MAP_SYSTEM_PROMPT_V2,
    _KIMI_PLANNING_SYSTEM_PROMPT,
    _build_kimi_execution_seed,
)


def test_kimi_planning_prompt_prefers_radial_intent_over_relayout():
    assert "radial" in _KIMI_PLANNING_SYSTEM_PROMPT.lower()
    assert "部门人数" in _KIMI_PLANNING_SYSTEM_PROMPT or "人员数" in _KIMI_PLANNING_SYSTEM_PROMPT
    assert "relayout(direction=TB)" not in _KIMI_PLANNING_SYSTEM_PROMPT
    assert "relayout 作为 layout_steps 第一步" not in _KIMI_PLANNING_SYSTEM_PROMPT


def test_scene_a_sop_no_longer_requires_relayout():
    scene_a_start = POWER_MAP_SYSTEM_PROMPT_V2.index("【场景 A SOP - 从零新建】")
    scene_b_start = POWER_MAP_SYSTEM_PROMPT_V2.index("【场景 B SOP - 增量新增】")
    scene_a = POWER_MAP_SYSTEM_PROMPT_V2[scene_a_start:scene_b_start]

    assert "radial" in scene_a.lower()
    assert "默认必经" not in scene_a
    assert "必须先调用一次 relayout" not in scene_a
    assert "relayout(options={\"direction\":\"TB\"})" not in scene_a


def test_kimi_execution_seed_says_backend_handles_layout():
    seed = _build_kimi_execution_seed(
        graph_state_text="## 当前图结构\n节点 (0):",
        plan_text='{"goal":"建图","departments":[],"people":[]}',
    )
    text = "\n".join(str(block.get("text", "")) for block in seed if block.get("type") == "text")

    assert "后端" in text
    assert "radial" in text.lower()
    assert "不要猜坐标" in text or "不要负责像素级" in text
