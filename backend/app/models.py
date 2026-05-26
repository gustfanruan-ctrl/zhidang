# CR-FINAL-FIX: 为SSO nonce、业务查询与埋点分析补充索引并扩展必要表结构。
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)


class Superadmin(Base, TimestampMixin):
    __tablename__ = "superadmin"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(100))


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(150))
    integrate_id: Mapped[str | None] = mapped_column(String(100))
    departments: Mapped[list[int] | None] = mapped_column(JSON)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    onboarding_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    role: Mapped[str] = mapped_column(String(20), default="user", nullable=False)  # "superadmin" | "user"
    followup_review_template: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)


class SystemConfig(Base, TimestampMixin):
    __tablename__ = "system_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    jiandaoyun_api_key_encrypted: Mapped[str | None] = mapped_column(Text)
    jiandaoyun_base_url: Mapped[str] = mapped_column(String(255), default="https://api.jiandaoyun.com")
    jiandaoyun_app_id: Mapped[str | None] = mapped_column(String(100))
    main_entry_id: Mapped[str | None] = mapped_column(String(100))
    field_mappings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    llm_provider: Mapped[str] = mapped_column(String(50), default="dashscope")
    llm_api_key_encrypted: Mapped[str | None] = mapped_column(Text)
    llm_base_url: Mapped[str] = mapped_column(String(255), default="https://dashscope.aliyuncs.com/compatible-mode/v1")
    agent_a_model: Mapped[str] = mapped_column(String(100), default="qwen-plus")
    agent_b_model: Mapped[str] = mapped_column(String(100), default="qwen-plus")
    nl_chat_model: Mapped[str] = mapped_column(String(100), default="qwen-plus")
    temperature: Mapped[float] = mapped_column(Float, default=0.3)
    max_tokens: Mapped[int] = mapped_column(Integer, default=4096)
    agent_a_prompt: Mapped[str] = mapped_column(Text, default="你是一个专业的客户成功分析师，专门从客户拜访会议转写文本中提取结构化信息。\n\n## 你的任务\n分析以下会议转写文本，识别并提取其中的「客户预期」和「业务场景」。\n\n## 关键定义\n- **客户预期**：客户明确或隐含表达的期望、需求、目标、希望达成的效果。包括功能需求、时间节点要求、效果预期等。\n- **业务场景**：客户当前面临的业务痛点、正在使用的工作流程、希望优化的具体场景。\n\n## 工具使用规则\n1. 对识别到的每一条预期，调用 `add_expectation` 工具\n2. 对识别到的每一条场景，调用 `add_scenario` 工具\n3. 每条提取必须附带原文引用（source_quote），用于用户审核时溯源\n4. 如果转写内容明显不是客户拜访（如内部会议、闲聊），不调用任何工具，直接回复说明原因\n5. 宁可多提取、不要遗漏，用户后续会审核\n\n## 字段填写指南\n- summary：一句话概括，不超过50字\n- is_first_value：如果是首次提出该预期/场景，为 true；如果是对已有内容的补充或跟进，为 false\n- description：详细描述，2-3句话\n- status：根据上下文判断，可选值为「未启动」「进行中」「已完成」「已搁置」，无法判断时默认「未启动」\n- source_quote：从原文中摘录最相关的一段话，保持原文不改动\n- speaker：说话人姓名或角色（如「客户方张总」「我方小李」），无法识别时填「未知」\n- timestamp：如果转写中有时间标记，填写对应时间段；没有则留空\n\n## 上下文信息\n- 行业：{industry}\n- 部门：{department}\n- 公司：{company_name}\n\n## 转写文本\n{transcript_text}\n")
    agent_b_prompt: Mapped[str] = mapped_column(Text, default="你是一个客户档案管理专家，负责将新提取的客户预期和场景与简道云中已有的档案数据进行智能比对，生成精确的操作指令。\n\n## 你的任务\n对比「新提取的数据」和「已有档案数据」，判断每条提取内容应该执行什么操作。\n\n## 操作类型判断规则\n1. **新增（create）**：提取内容在已有档案中无相似项（语义相似度 < 70%），调用 `create_expectation` 或 `create_scenario`\n2. **更新（update）**：提取内容与已有档案某条记录语义高度相似（≥ 70%），但有新信息需要补充或状态需要变更，调用 `update_expectation` 或 `update_scenario`，并填写 match_id 指向已有记录\n3. **跳过**：提取内容与已有记录完全重复且无新信息，不调用任何工具\n\n## 工具使用规则\n1. 对每条需要操作的内容，调用对应的工具，逐条调用\n2. update 操作必须提供 match_id（已有记录的 ID）和 reason（为什么认为匹配）\n3. confidence 取值 0.0-1.0，反映你对这个操作判断的确信程度\n4. 相似度判断基于语义，不要求字面完全一致。例如「希望提升审批效率」和「审批流程太慢需要优化」应视为相似\n\n## 字段更新规则\n- update 操作时，只填写需要变更的字段，未提及的字段留空（不覆盖）\n- 如果新提取的 description 比已有的更详细，更新 description 并在 reason 中说明\n- status 变更需要有明确的原文依据\n\n## 新提取的数据（来自 Agent-A）\n{agent_a_result}\n\n## 简道云已有档案数据\n{jiandaoyun_existing_data}\n")
    nl_query_prompt: Mapped[str] = mapped_column(Text, default="你是一个客户档案查询助手，帮助用户通过自然语言查询简道云中的客户档案信息。\n\n## 能力范围\n你可以帮用户查询以下信息：\n- 某个客户的所有预期管理记录\n- 某个客户的所有业务场景记录\n- 按状态筛选（如「查看所有进行中的预期」）\n- 按时间范围筛选（如「最近一个月新增的场景」）\n\n## 回复规则\n1. 将查询结果以清晰的结构化方式呈现，每条记录包括：摘要、状态、最后更新时间\n2. 如果查询无结果，明确告知并建议调整关键词\n3. 如果用户的查询意图不明确，主动追问确认\n4. 不要编造数据，所有信息必须来自简道云查询结果\n5. 涉及修改操作时，告知用户切换到修改模式或直接引导到修改流程\n\n## 当前用户\n{user_name}（{user_role}）\n\n## 用户输入\n{user_query}\n")
    nl_modify_prompt: Mapped[str] = mapped_column(Text, default="你是一个客户档案修改助手，帮助用户通过自然语言修改简道云中的客户档案信息。\n\n## 能力范围\n你可以帮用户执行以下修改：\n- 修改预期/场景的状态（未启动、进行中、已完成、已搁置）\n- 修改预期/场景的描述、摘要\n- 添加进度备注（progress_note）\n- 删除错误的预期/场景记录\n\n## 安全规则（必须严格遵守）\n1. **任何修改操作必须先生成预览，等待用户明确确认后才执行**\n2. 预览格式：显示「修改前 → 修改后」的对比\n3. 批量修改时，逐条列出所有变更供用户确认\n4. 如果用户指令模糊（如「改一下那个」），必须追问确认具体目标\n5. 删除操作需要二次确认\n\n## 回复格式\n当用户发出修改指令时：\n1. 先查询目标记录的当前状态\n2. 生成修改预览：\n   📝 修改预览\n   目标：{company_name} - {record_summary}\n   字段：{field_name}\n   当前值：{old_value}\n   修改为：{new_value}\n\n   请确认是否执行此修改？（是/否）\n3. 用户确认后执行修改并返回结果\n\n## 当前用户\n{user_name}（{user_role}）\n\n## 用户输入\n{user_query}\n")
    sso_shared_secret: Mapped[str | None] = mapped_column(String(255))
    sso_token_ttl_minutes: Mapped[int] = mapped_column(Integer, default=5)
    dingtalk_app_key: Mapped[str | None] = mapped_column(String(255))
    dingtalk_app_secret_encrypted: Mapped[str | None] = mapped_column(Text)
    dingtalk_agent_id: Mapped[str | None] = mapped_column(String(100))
    agent_a_max_rounds: Mapped[int] = mapped_column(Integer, default=5)
    agent_b_max_rounds: Mapped[int] = mapped_column(Integer, default=5)
    data_retention_days: Mapped[int] = mapped_column(Integer, default=90)
    power_map_base_url: Mapped[str | None] = mapped_column(String(500), default="https://crm.finereporthelp.com/WebReport/decision")
    power_map_get_path: Mapped[str | None] = mapped_column(String(200), default="/url/power_map/getInfo")
    power_map_update_path: Mapped[str | None] = mapped_column(String(200), default="/url/power_map/upInfo")
    power_map_auth_token_encrypted: Mapped[str | None] = mapped_column(Text, default="")




class Transcript(Base, TimestampMixin):
    __tablename__ = "transcripts"
    __table_args__ = (
        Index("ix_transcripts_company_id_status", "company_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    source_id: Mapped[str | None] = mapped_column(String(255))
    title: Mapped[str | None] = mapped_column(String(255))
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    segments: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)
    input_type: Mapped[str] = mapped_column(String(20), default="text")
    status: Mapped[str] = mapped_column(String(30), default="parsed")
    agent_a_result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    agent_b_result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    company_id: Mapped[str | None] = mapped_column(String(255), index=True)
    company_name: Mapped[str | None] = mapped_column(String(255))
    sso_user_name: Mapped[str | None] = mapped_column(String(100))
    sso_user_id: Mapped[str | None] = mapped_column(String(255))


class FollowupRecord(Base, TimestampMixin):
    __tablename__ = "followup_records"
    __table_args__ = (
        Index("ix_followup_records_company_id_status", "company_id", "status"),
        Index("ix_followup_records_source_id", "source_id"),
        Index("ix_followup_records_sso_user_name", "sso_user_name"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="jiandaoyun")
    source_id: Mapped[str | None] = mapped_column(String(255))
    title: Mapped[str | None] = mapped_column(String(255))
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    segments: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)
    input_type: Mapped[str] = mapped_column(String(20), default="followup")
    status: Mapped[str] = mapped_column(String(30), default="parsed")
    agent_a_result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    agent_b_result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    company_id: Mapped[str | None] = mapped_column(String(255), index=True)
    company_name: Mapped[str | None] = mapped_column(String(255))
    sso_user_name: Mapped[str | None] = mapped_column(String(100))
    sso_user_id: Mapped[str | None] = mapped_column(String(255))
    review_date: Mapped[str | None] = mapped_column(String(50))
    follow_type: Mapped[str | None] = mapped_column(String(50))
    raw_record: Mapped[dict[str, Any] | None] = mapped_column(JSON)


class SsoNonceUsed(Base, TimestampMixin):
    __tablename__ = "sso_nonce_used"

    nonce: Mapped[str] = mapped_column(String(64), primary_key=True)
    used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class OperationLog(Base, TimestampMixin):
    __tablename__ = "operation_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    transcript_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("transcripts.id"))
    operation_type: Mapped[str] = mapped_column(String(50), nullable=False)
    request_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    response_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    operator_name: Mapped[str | None] = mapped_column(String(100))
    operator_id: Mapped[str | None] = mapped_column(String(255))


class ConfigChangeLog(Base, TimestampMixin):
    __tablename__ = "config_change_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    config_section: Mapped[str] = mapped_column(String(50), nullable=False)
    changed_fields: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    changed_by: Mapped[str] = mapped_column(String(100), nullable=False)


class AnalyticsEvent(Base, TimestampMixin):
    __tablename__ = "analytics_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    event_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    operator_name: Mapped[str | None] = mapped_column(String(100), index=True)
    operator_id: Mapped[str | None] = mapped_column(String(255))
    operator_source: Mapped[str | None] = mapped_column(String(20))
    transcript_id: Mapped[str | None] = mapped_column(String(36), index=True)
    company_id_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    session_id: Mapped[str | None] = mapped_column(String(36))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    operation_type: Mapped[str | None] = mapped_column(String(50))
    action: Mapped[str | None] = mapped_column(String(50))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    model: Mapped[str | None] = mapped_column(String(50))
    prompt_version: Mapped[str | None] = mapped_column(String(20))


class OperationCardLog(Base, TimestampMixin):
    __tablename__ = "operation_card_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    transcript_id: Mapped[str | None] = mapped_column(String(36), index=True)
    card_index: Mapped[int | None] = mapped_column(Integer)
    target_form: Mapped[str | None] = mapped_column(String(50))
    operation_type: Mapped[str] = mapped_column(String(50), nullable=False)
    widget_name: Mapped[str | None] = mapped_column(String(100))
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    safety_status: Mapped[str | None] = mapped_column(String(30))
    execute_status: Mapped[str] = mapped_column(String(20), default="pending")
    jiandaoyun_response: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


