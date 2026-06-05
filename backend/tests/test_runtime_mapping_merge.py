import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import get_jiandaoyun_runtime_config  # noqa: E402


def test_runtime_mapping_falls_back_to_seed_when_db_scene_form_is_empty(monkeypatch):
    monkeypatch.setattr(
        "app.main._load_jiandaoyun_seed_mapping",
        lambda: {
            "app_id": "seed-app",
            "forms": {
                "客户主表": {"entry_id": "main-entry"},
                "场景表": {
                    "entry_id": "scene-entry",
                    "field_mapping": {
                        "场景标题": {"widget": "title"},
                        "业务诉求/痛点分析": {"widget": "solve_what_ques"},
                        "核心指标&解决方案": {"widget": "solve_what_ans"},
                    },
                },
            },
        },
    )

    cfg = SimpleNamespace(
        field_mappings={"jiandaoyun": {"forms": {"场景表": {}}}},
        jiandaoyun_app_id="",
        jiandaoyun_api_key_encrypted="",
        main_entry_id="",
    )

    runtime = get_jiandaoyun_runtime_config(cfg)
    scene_form = ((runtime.get("mapping") or {}).get("forms") or {}).get("场景表") or {}

    assert runtime["app_id"] == "seed-app"
    assert scene_form["entry_id"] == "scene-entry"
    assert scene_form["field_mapping"]["业务诉求/痛点分析"]["widget"] == "solve_what_ques"
