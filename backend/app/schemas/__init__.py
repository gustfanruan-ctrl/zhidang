"""
智档 · Schema 层（含 US-2 跟进记录生成）
"""
from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel, Field, field_validator, model_validator

class BaseAPIModel(BaseModel):
    model_config = {"extra": "forbid"}

class SystemInitPayload(BaseAPIModel):
    username: str = Field(min_length=2, max_length=50)
    password: str = Field(min_length=8, max_length=128)
    display_name: str | None = Field(default=None, max_length=100)

    @field_validator("username")
    @classmethod
    def username_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("username 不能为空")
        return value.strip()

class LoginPayload(BaseAPIModel):
    username: str = Field(min_length=2, max_length=50)
    password: str = Field(min_length=1, max_length=128)

class AdminConfigPayload(BaseAPIModel):
    jiandaoyun_api_key: str | None = None
    jiandaoyun_base_url: str | None = None
    jiandaoyun_app_id: str | None = None
    main_entry_id: str | None = None
    field_mappings: dict[str, Any] | None = None
    sso_shared_secret: str | None = None
    sso_token_ttl_minutes: int | None = Field(default=None, ge=1, le=1440)
    dingtalk_app_key: str | None = None
    dingtalk_app_secret: str | None = None
    dingtalk_agent_id: str | None = None
    agent_a_max_rounds: int | None = Field(default=None, ge=1, le=20)
    agent_b_max_rounds: int | None = Field(default=None, ge=1, le=20)
    data_retention_days: int | None = Field(default=None, ge=30, le=3650)
    power_map_base_url: str | None = None
    power_map_get_path: str | None = None
    power_map_update_path: str | None = None
    power_map_auth_token: str | None = None
    power_map_login_mobile: str | None = None
    power_map_login_password: str | None = None

class LlmConfigPayload(BaseAPIModel):
    api_key: str | None = None
    provider: str | None = None
    base_url: str | None = None
    agent_a_model: str | None = None
    agent_b_model: str | None = None
    nl_chat_model: str | None = None
    power_map_llm_model: str | None = None
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, ge=1, le=32768)
    agent_a_prompt: str | None = None
    agent_b_prompt: str | None = None
    nl_query_prompt: str | None = None
    nl_modify_prompt: str | None = None

class AgentTaskBase(BaseAPIModel):
    task_id: str | None = None

class TranscriptPayload(BaseAPIModel):
    id: str | None = None
    company_name_hint: str | None = None
    raw_text: str | None = None

class ImageInputItem(BaseAPIModel):
    type: Literal["base64"] = "base64"
    media_type: str
    data: str

class AgentExtractionPayload(AgentTaskBase):
    transcript: TranscriptPayload = Field(default_factory=TranscriptPayload)
    transcript_id: str | None = None
    input_type: Literal["text", "image", "mixed"] = "text"
    content: str | None = None
    images: list[ImageInputItem] = Field(default_factory=list)
    llm_request_timeout_seconds: int | None = Field(default=None, ge=10, le=7200)
    llm_connect_timeout_seconds: int | None = Field(default=None, ge=3, le=7200)
    agent_total_timeout_seconds: int | None = Field(default=None, ge=30, le=7200)
    agent_tool_timeout_seconds: int | None = Field(default=None, ge=5, le=7200)
    agent_max_iterations: int | None = Field(default=None, ge=1, le=20)

class ComparisonTaskPayload(AgentTaskBase):
    extraction_result: dict[str, Any]
    existing_record: dict[str, Any]
    transcript_id: str | None = None
    company_id: str | None = None

class AgentComparisonPayload(ComparisonTaskPayload):
    pass

class ReviewActionPayload(BaseAPIModel):
    operation_id: str
    operation_type: str
    action: str
    agent_confidence: float = Field(ge=0, le=1)
    time_spent_seconds: int = Field(ge=0)
    card_position: int = Field(ge=1)
    total_cards: int = Field(ge=1)
    edit_details: dict[str, Any] | None = None

class ReviewSessionPayload(BaseAPIModel):
    transcript_id: str | None = None
    total_operations: int = Field(ge=0)
    confirmed: int = Field(ge=0)
    edited_then_confirmed: int = Field(ge=0)
    deleted: int = Field(ge=0)
    final_action: str
    total_review_time_seconds: int = Field(ge=0)
    avg_time_per_card_seconds: float = Field(ge=0)

    @model_validator(mode="after")
    def validate_counts(self):
        if self.confirmed + self.deleted > self.total_operations:
            raise ValueError("审核统计不合法")
        return self

class SsoGeneratePayload(BaseAPIModel):
    user_name: str = Field(min_length=1, max_length=100)
    user_id: str = Field(min_length=1, max_length=255)
    company_id: str = Field(min_length=1, max_length=255)

class SsoEntryQuery(BaseAPIModel):
    token: str = ""                                         # HMAC token（完整 SSO 模式，兼容旧版）
    company_id: str = ""                                    # 公司 ID（完整 SSO 模式）
    portal_key: str = ""                                    # 简化模式：固定入口密钥（配置中的 sso_shared_secret）
    jdy_username: str = ""                                  # JDY 超链接 {username} 动态传入的当前用户

class OperationItem(BaseAPIModel):
    op_id: str | None = None
    type: str
    data: dict[str, Any] = Field(default_factory=dict)
    source_quote: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)

class ExecuteOperationsPayload(BaseAPIModel):
    transcript_id: str | None = None
    company_id: str | None = None
    session_id: str | None = None
    operations: list[OperationItem] = Field(default_factory=list)

class ChatPayload(BaseAPIModel):
    message: str = Field(min_length=1, max_length=4000)
    session_id: str | None = None
    company_id: str | None = None
    confirm: bool = False

    @field_validator("message")
    @classmethod
    def normalize_message(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("message 不能为空")
        return normalized

class LlmTestPayload(BaseAPIModel):
    target: str = Field(min_length=1, max_length=100)
    transcript_text: str | None = None
    agent_a_result: dict[str, Any] | None = None
    jiandaoyun_existing_data: dict[str, Any] | None = None
    user_query: str | None = None
    industry: str | None = None
    department: str | None = None
    company_name: str | None = None

class TranscriptUploadResponse(BaseAPIModel):
    transcript_id: str
    title: str
    segment_count: int = Field(ge=0)
    status: str
    preview: str
    file_count: int = 1


class TranscriptAnalyzeResponse(BaseAPIModel):
    transcript_id: str
    status: str
    message: str

class CompanySearchQuery(BaseAPIModel):
    q: str = Field(default="", max_length=100)

class CustomerSwitchPayload(BaseAPIModel):
    company_id_from: str | None = None
    company_id_to: str
    trigger: str = Field(default="manual", max_length=20)

class DingtalkFetchPayload(BaseAPIModel):
    conference_id: str = Field(min_length=1, max_length=255)
    raw_text: str | None = None
    title: str | None = Field(default=None, max_length=255)

class AdminFetchWidgetsPayload(BaseAPIModel):
    form_name: str = Field(min_length=1, max_length=100)
    entry_id: str = Field(min_length=1, max_length=100)

ConfigPayload = AdminConfigPayload


# ── 权利地图 ──────────────────────────────────────
class PowerMapChatPayload(BaseAPIModel):
    message: str = Field(min_length=1, max_length=4000)
    session_id: str | None = None  # DEPRECATED: rejected with 400; every chat starts a new session
    confirm: bool = False
    version: str | None = None

    @field_validator("message")
    @classmethod
    def normalize_message(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("message 不能为空")
        return normalized


class PowerMapConfirmPayload(BaseAPIModel):
    proposed_changes: dict[str, Any]
    version: str | None = None


class PowerMapRelayoutPayload(BaseAPIModel):
    mode: str = "new_nodes_only"  # "new_nodes_only" | "single_dept" | "full"
    dept_id: str | None = None    # required for mode "single_dept"
    version: str | None = None


class PowerMapPreviewPayload(BaseAPIModel):
    """Payload for power map preview (dry-run layout)."""
    proposed_changes: dict[str, Any]
    version: str | None = None


# ── US-2 跟进记录生成 ──────────────────────────────────────
from .followup import (  # noqa: E402, F401
    ACTION_PURPOSES,
    BUSINESS_ACTIONS,
    GENJIN_TAGS,
    FollowupActionItem,
    FollowupGenerateRequest,
    FollowupRecord,
    FollowupSubmitRequest,
    GenjinTag,
)
