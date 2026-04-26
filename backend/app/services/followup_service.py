"""
US-2 跟进记录生成 · 服务层
截图/文字 → LLM 四段式提取 → 简道云写入
"""
from __future__ import annotations
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import httpx
from sqlalchemy.orm import Session

from ..schemas.followup import (
    ACTION_PURPOSES,
    BUSINESS_ACTIONS,
    GENJIN_TAGS,
    FollowupGenerateRequest,
    FollowupRecord,
    FollowupSubmitRequest,
    GenjinTag,
)
from .jiandaoyun_client import JiandaoyunClient, JiandaoyunClientError
from .jiandaoyun_writer import JiandaoyunWriter

logger = logging.getLogger("zhidang.followup")

# ── 四段式 System Prompt ────────────────────────────────────

FOLLOWUP_SYSTEM_PROMPT = """你是一名 CRM 数据录入助手。从以下沟通记录中提取信息，输出严格 JSON。

## 输出格式（只输出 JSON，不要 markdown 代码块）
{
  "company_name": "公司名",
  "contact_person": "联系人姓名",
  "followup_date": "YYYY-MM-DD",
  "business_action": "枚举值",
  "action_purpose": "枚举值",
  "background": "【背景】一句话说明本次沟通的起因",
  "communication_details": ["要点1", "要点2"],
  "conclusion": "【结论】本次沟通达成的共识或结果",
  "followup_actions": [{"person":"负责人","task":"待办事项","deadline":"YYYY-MM-DD"}],
  "genjin_tags": [{"level1":"一级","level2":"二级","level3":"三级"}]
}

## 商务行为枚举（必须从中选择）
线上沟通 / 电话沟通 / 邮件跟进 / 现场拜访 / 问题处理 / 需求跟进 / 资料发送 / 其他

## 行为目的枚举（必须从中选择）
问题解决 / 需求收集 / 关系维护 / 续费推进 / 增购推进 / 培训支持 / 其他

## 跟进标签三级体系
使用推进：常态化跟进 / 预期跟进 / 系统部署环境确认 / 价值汇报高层触达 / 价值宣导方案讲解
数字人才服务：线上课程 / 线下培训 / 业务沙盘 / 翻转课堂 / 人才大赛（三级：意愿触达/过程执行）
续费增购：服务ARR推动 / 年费续费推动 / 增购推动 / 签单辅助

标签推断规则（必须至少生成一个标签）：
- 提到部署、上线、环境 → 系统部署/环境确认
- 提到培训、学习、课程 → 数字人才服务 → 二级标签选"线下培训"或"线上课程"
- 提到续费、合同、金额 → 续费增购
- 提到bug、故障、问题 → 常态化跟进
- 提到高层、汇报、价值 → 价值汇报/高层触达
- 提到方案、宣讲、介绍 → 价值宣导/方案讲解
- 以上都不匹配时，默认使用 使用推进 → 常态化跟进
- genjin_tags 不能为空数组，至少包含一条标签

## 处理规则
- communication_details 每条省略主语，以动词开头
- 保留客户问题/需求、帆软回复/结果、约定的后续行动、项目进展
- 跳过纯寒暄、表情包、与业务无关的闲聊
- 多张截图合并为一条记录
- 日期优先使用截图中显示的消息时间戳，其次使用文件名日期，无法识别时用"待确认"
- 如果完全无法提取有效信息，返回空的 communication_details 并在 background 中说明原因
"""


# ── 辅助函数 ────────────────────────────────────────────────

def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_date(text: str, date_hint: str | None = None) -> str:
    """日期优先级：截图时间戳 > 文件名 > 用户补充 > 待确认"""
    # 尝试从文本中提取 YYYY-MM-DD 或 MM-DD
    patterns = [
        r"(\d{4}-\d{2}-\d{2})",
        r"(\d{4}/\d{2}/\d{2})",
        r"(\d{2}-\d{2})\s+\d{2}:\d{2}",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            d = m.group(1).replace("/", "-")
            if len(d) == 5:  # MM-DD
                d = f"{now_utc().year}-{d}"
            return d
    if date_hint and re.match(r"\d{4}-\d{2}-\d{2}", date_hint):
        return date_hint
    return "待确认"


def _build_review_record_text(record: FollowupRecord) -> str:
    """将 FollowupRecord 转为 review_record Markdown 文本"""
    parts: list[str] = []

    # 行为目的
    if record.action_purpose:
        parts.append(f"**行为目的**：{record.action_purpose}")

    # 背景
    if record.background:
        parts.append(f"## 【背景】\n{record.background}")

    # 沟通详情
    if record.communication_details:
        items = "\n".join(f"- {item}" for item in record.communication_details)
        parts.append(f"## 【沟通详情】\n{items}")

    # 结论
    if record.conclusion:
        parts.append(f"## 【结论】\n{record.conclusion}")

    # 后续行动
    if record.followup_actions:
        actions = "\n".join(
            f"- {a.person}：{a.task}（{a.deadline}）"
            for a in record.followup_actions
        )
        parts.append(f"## 【后续行动】\n{actions}")

    return "\n\n".join(parts)


def _build_genjin_subform_rows(tags: list[GenjinTag]) -> list[dict[str, Any]]:
    """构建 genjin 子表单行数据"""
    rows: list[dict[str, Any]] = []
    for tag in tags:
        if not tag.level1 or not tag.level2:
            continue
        row: dict[str, Any] = {
            "genjin_level1": {"value": tag.level1},
            "genjin_level2": {"value": tag.level2},
        }
        if tag.level3:
            row["genjin_level3"] = {"value": tag.level3}
        rows.append(row)
    return rows


def _validate_genjin_tag(tag: GenjinTag) -> bool:
    """校验标签是否在三级体系中"""
    level2_map = GENJIN_TAGS.get(tag.level1)
    if not level2_map:
        return False
    if tag.level2 not in level2_map:
        return False
    if tag.level3:
        allowed_l3 = level2_map[tag.level2]
        if allowed_l3 and tag.level3 not in allowed_l3:
            return False
    return True


# ── 核心服务类 ──────────────────────────────────────────────

class FollowupService:
    """跟进记录生成与提交服务"""

    def __init__(
        self,
        api_key: str,
        app_id: str,
        llm_api_key: str,
        llm_base_url: str,
        llm_model: str,
    ):
        self.writer = JiandaoyunWriter(api_key=api_key, app_id=app_id)
        self.client = JiandaoyunClient(api_key=api_key)
        self.app_id = app_id
        self.llm_api_key = llm_api_key
        self.llm_base_url = llm_base_url.rstrip("/")
        self.llm_model = llm_model

    async def generate(
        self,
        payload: FollowupGenerateRequest,
    ) -> FollowupRecord:
        """从截图或文字生成跟进记录"""
        # 1. 处理截图 → 文字
        content = payload.content or ""
        if payload.input_type == "screenshot" and payload.images:
            ocr_text = await self._ocr_screenshots(payload.images)
            if ocr_text:
                content = ocr_text

        if not content.strip():
            return FollowupRecord(
                background="未能从输入中提取到有效文字内容，请检查截图或手动粘贴文字。",
            )

        # 2. 调用 LLM
        raw_json = await self._call_llm(content)

        # 3. 解析并校验
        record = self._parse_llm_output(raw_json, content, payload.date_hint)

        return record

    async def submit(
        self,
        payload: FollowupSubmitRequest,
        db: Session | None = None,
    ) -> dict[str, Any]:
        """提交跟进记录到简道云"""
        entry_id = "670a28334883adafb152a869"

        # 构建 data payload
        data: dict[str, Any] = {}

        # lookup 关联公司
        if payload.company_id:
            data["_widget_1744600409845"] = {"value": payload.company_id}

        # 跟进人
        if payload.follower:
            data["follower"] = {"value": payload.follower}

        # 跟进类型
        data["follow_type"] = {"value": payload.follow_type}

        # 跟进日期
        data["review_date"] = {"value": payload.review_date}

        # 跟进记录
        data["review_record"] = {"value": payload.review_record}

        # 跟进标签 subform
        genjin_rows = _build_genjin_subform_rows(payload.genjin_tags)
        if genjin_rows:
            data["genjin"] = {"value": genjin_rows}

        # 推送前方
        data["if_tuisong"] = {"value": payload.if_tuisong}

        # 联系人
        if payload.contid:
            data["contid"] = {"value": payload.contid}
        if payload.contname:
            data["contname"] = {"value": payload.contname}

        # 关联预期（可选）
        if payload.yuqi_id:
            data["_widget_1757576851901"] = {"value": payload.yuqi_id}

        # 写入
        try:
            result = await self.writer.create_record(entry_id, data)
            return result
        except JiandaoyunClientError as exc:
            logger.exception("Failed to submit followup record")
            return {"success": False, "error_code": "submit_failed", "detail": str(exc)}

    # ── 私有方法 ────────────────────────────────────────────

    async def _ocr_screenshots(self, images: list[Any]) -> str:
        """截图 OCR：调用 LLM vision 能力提取文字"""
        # 构建 vision API 请求
        image_contents: list[dict[str, Any]] = []
        for img in images:
            image_contents.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:{img.media_type};base64,{img.data}",
                },
            })

        messages = [
            {
                "role": "user",
                "content": [
                    *image_contents,
                    {
                        "type": "text",
                        "text": (
                            "请提取以上截图中的所有文字内容，包括消息发送者、时间戳和消息正文。"
                            "按时间顺序输出，格式：\n"
                            "[发送者] HH:MM\n消息内容\n\n"
                            "不要添加任何额外解释。"
                        ),
                    },
                ],
            }
        ]

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
                resp = await client.post(
                    f"{self.llm_base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.llm_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.llm_model,
                        "messages": messages,
                        "max_tokens": 4096,
                        "temperature": 0.1,
                    },
                )
                if resp.status_code >= 400:
                    logger.warning("OCR failed: %s %s", resp.status_code, resp.text[:200])
                    return ""
                data = resp.json()
                return data["choices"][0]["message"]["content"]
        except Exception:
            logger.exception("OCR request failed")
            return ""

    async def _call_llm(self, content: str) -> str:
        """调用 LLM 生成结构化跟进记录"""
        messages = [
            {"role": "system", "content": FOLLOWUP_SYSTEM_PROMPT},
            {"role": "user", "content": f"## 输入内容\n{content}"},
        ]

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
                resp = await client.post(
                    f"{self.llm_base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.llm_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.llm_model,
                        "messages": messages,
                        "max_tokens": 4096,
                        "temperature": 0.3,
                    },
                )
                if resp.status_code >= 400:
                    logger.error("LLM call failed: %s %s", resp.status_code, resp.text[:200])
                    raise RuntimeError(f"LLM 调用失败: {resp.status_code}")
                data = resp.json()
                return data["choices"][0]["message"]["content"]
        except Exception as exc:
            logger.exception("LLM request failed")
            raise RuntimeError(f"LLM 请求异常: {exc}") from exc

    def _parse_llm_output(
        self,
        raw_json: str,
        source_text: str,
        date_hint: str | None,
    ) -> FollowupRecord:
        """解析 LLM 输出为 FollowupRecord"""
        try:
            # 清理可能的 markdown 代码块
            cleaned = raw_json.strip()
            if cleaned.startswith("```"):
                cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
                cleaned = re.sub(r"\s*```$", "", cleaned)
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            logger.warning("Failed to parse LLM output as JSON: %s", raw_json[:200])
            return FollowupRecord(
                background="LLM 返回格式异常，请重试。",
                communication_details=[raw_json[:500]],
            )

        # 日期解析
        followup_date = data.get("followup_date", "")
        if not followup_date or followup_date == "待确认":
            followup_date = _parse_date(source_text, date_hint)

        # 校验枚举值
        business_action = data.get("business_action", "")
        if business_action not in BUSINESS_ACTIONS:
            business_action = "其他"

        action_purpose = data.get("action_purpose", "")
        if action_purpose not in ACTION_PURPOSES:
            action_purpose = "其他"

        # 解析后续行动
        followup_actions = []
        for item in data.get("followup_actions", []):
            if isinstance(item, dict):
                followup_actions.append({
                    "person": str(item.get("person", "")),
                    "task": str(item.get("task", "")),
                    "deadline": str(item.get("deadline", "")),
                })

        # 解析跟进标签
        genjin_tags = []
        for tag in data.get("genjin_tags", []):
            if isinstance(tag, dict):
                gt = GenjinTag(
                    level1=str(tag.get("level1", "")),
                    level2=str(tag.get("level2", "")),
                    level3=str(tag.get("level3", "")),
                )
                if _validate_genjin_tag(gt):
                    genjin_tags.append(gt)

        return FollowupRecord(
            company_name=str(data.get("company_name", "")),
            contact_person=str(data.get("contact_person", "")),
            followup_date=followup_date,
            business_action=business_action,
            action_purpose=action_purpose,
            background=str(data.get("background", "")),
            communication_details=[
                str(d) for d in data.get("communication_details", [])
            ],
            conclusion=str(data.get("conclusion", "")),
            followup_actions=followup_actions,
            genjin_tags=genjin_tags,
        )
