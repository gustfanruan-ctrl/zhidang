import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import main as main_module  # noqa: E402
from app.schemas import ChatPayload  # noqa: E402


@pytest.mark.asyncio
async def test_chat_keeps_pending_write_when_scene_create_is_missing_fields(monkeypatch):
    session_id = "session-scene-missing"
    main_module.PENDING_CHAT_ACTIONS.clear()

    class DummyRunner:
        def __init__(self, *args, **kwargs):
            self.pending_write = {
                "tool_name": "create_customer_record",
                "tool_input": {
                    "company_id": "company-1",
                    "target_form": "场景表",
                    "fields": {
                        "场景标题": "供应链ai告警机器人",
                        "业务诉求/痛点分析": "现状：目前供应链告警依靠邮件和人工检验；痛点：耗时耗力；方案目标：通过fde机器人实现供应链自动监控",
                        "核心指标&解决方案": "待补充",
                    },
                },
                "validated": False,
            }

        async def run(self, *args, **kwargs):
            return SimpleNamespace(status="success", final_text="", message="")

    monkeypatch.setattr(main_module, "AgentRunner", DummyRunner)
    monkeypatch.setattr(main_module, "ensure_system_config", lambda db: SimpleNamespace(nl_chat_model="qwen-plus"))
    monkeypatch.setattr(
        main_module,
        "_get_llm_runtime_config",
        lambda cfg: {"provider": "openai_compatible", "api_key": "k", "base_url": "https://example.com"},
    )
    monkeypatch.setattr(main_module, "_build_agent_llm_client", lambda cfg: object())
    monkeypatch.setattr(
        main_module,
        "get_jiandaoyun_runtime_config",
        lambda cfg: {
            "mapping": {
                "forms": {
                    "场景表": {
                        "field_mapping": {
                            "场景标题": {"widget": "title"},
                            "业务诉求/痛点分析": {"widget": "solve_what_ques"},
                            "核心指标&解决方案": {"widget": "solve_what_ans"},
                        }
                    }
                }
            }
        },
    )

    payload = ChatPayload(message="新增一个场景", company_id="company-1", session_id=session_id)
    result = await main_module.chat(payload, db=None, user={"username": "tester"})

    assert result["needs_confirmation"] is False
    assert "关联预期" in result["reply"]
    assert session_id in main_module.PENDING_CHAT_ACTIONS
    pending = main_module.PENDING_CHAT_ACTIONS[session_id]
    assert pending["tool_name"] == "create_customer_record"
    assert pending["tool_input"]["target_form"] == "场景表"
    assert pending["tool_input"]["fields"]["场景标题"] == "供应链ai告警机器人"


def test_build_chat_user_message_includes_pending_action_snapshot():
    message = main_module._build_chat_user_message(
        "company-1",
        "关联预期：业务通过AI自助分析",
        [{"role": "assistant", "text": "这个场景还缺少这些关键信息：关联预期。请先补充，我再帮你生成待确认写入。"}],
        {
            "tool_name": "create_customer_record",
            "tool_input": {
                "target_form": "场景表",
                "fields": {"场景标题": "供应链ai告警机器人"},
            },
        },
    )

    assert "当前有一条待补全的写入操作" in message
    assert "场景表" in message
    assert "供应链ai告警机器人" in message
