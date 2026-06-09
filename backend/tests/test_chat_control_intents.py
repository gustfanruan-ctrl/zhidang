import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import _is_affirmative, _is_negative  # noqa: E402


def test_negative_intent_does_not_match_normal_business_text_with_english_n():
    text = (
        "新增一个预期，预期简述：业务通过AI自助分析 "
        "背景：集团推动全员ai提效，希望通过vibe coding解放it压力 "
        "需求内容：调研业务场景，设计fde项目 "
        "达成状态：试点部门落地3个fde应用"
    )
    assert _is_negative(text) is False
    assert _is_affirmative(text) is False


def test_negative_intent_matches_only_short_cancel_phrases():
    assert _is_negative("取消") is True
    assert _is_negative("不执行了") is True
    assert _is_negative("no") is True
    assert _is_negative("取消这个字段里的旧描述，改成新的版本") is False


def test_affirmative_intent_matches_only_short_confirmation_phrases():
    assert _is_affirmative("确认") is True
    assert _is_affirmative("好的") is True
    assert _is_affirmative("yes") is True
    assert _is_affirmative("可以帮我新增一个预期，内容如下") is False
