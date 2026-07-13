from __future__ import annotations

import copy
import json
import re
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import User

DEFAULT_FOLLOWUP_REVIEW_TEMPLATE: list[dict[str, Any]] = [
    {
        "key": "purpose",
        "title": "跟进目的",
        "instruction": "一句话概括本次沟通目的，10字以内",
        "enabled": True,
    },
    {
        "key": "details",
        "title": "沟通详情",
        "instruction": "客观详细记录沟通内容，保留数字、版本号、规模",
        "enabled": True,
    },
    {
        "key": "overall_review",
        "title": "整体Review",
        "instruction": "整体归纳本次沟通：客户核心预期、当前关注点、客户态度、推进风险、下一步建议",
        "enabled": True,
    },
]

_INVALID_KEY_RE = re.compile(r"[^a-z0-9_]+", re.IGNORECASE)


def _user_name(user: dict[str, Any]) -> str:
    return str(user.get("username") or user.get("user_name") or "").strip()


def _slugify_key(title: str) -> str:
    value = _INVALID_KEY_RE.sub("_", title.strip().lower()).strip("_")
    return value or ""


def _dedupe_key(key: str, used_keys: set[str], index: int) -> str:
    base = key or f"section_{index}"
    if base not in used_keys:
        used_keys.add(base)
        return base
    suffix = 2
    while f"{base}_{suffix}" in used_keys:
        suffix += 1
    final = f"{base}_{suffix}"
    used_keys.add(final)
    return final


def normalize_followup_review_template(raw_template: Any, *, fallback_to_default: bool = True) -> list[dict[str, Any]]:
    source: Any = raw_template
    if isinstance(raw_template, dict):
        source = raw_template.get("sections") or raw_template.get("template") or raw_template.get("items") or []

    normalized: list[dict[str, Any]] = []
    used_keys: set[str] = set()
    if isinstance(source, list):
        for index, item in enumerate(source, start=1):
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            instruction = str(item.get("instruction") or "").strip()
            key = str(item.get("key") or "").strip()
            if not key:
                key = _slugify_key(title) or f"section_{index}"
            key = _dedupe_key(key, used_keys, index)
            normalized.append(
                {
                    "key": key,
                    "title": title,
                    "instruction": instruction,
                    "enabled": bool(item.get("enabled", True)),
                }
            )

    if normalized or not fallback_to_default:
        return normalized
    return copy.deepcopy(DEFAULT_FOLLOWUP_REVIEW_TEMPLATE)


def validate_followup_review_template(template_sections: Any) -> list[dict[str, Any]]:
    normalized = normalize_followup_review_template(template_sections, fallback_to_default=False)
    if not normalized:
        raise ValueError("正文模板至少需要一个段落")
    if not any(section.get("enabled", True) for section in normalized):
        raise ValueError("正文模板至少需要启用一个段落")
    for index, section in enumerate(normalized, start=1):
        if not str(section.get("title") or "").strip():
            raise ValueError(f"第 {index} 个段落标题不能为空")
        if not str(section.get("instruction") or "").strip():
            raise ValueError(f"第 {index} 个段落生成要求不能为空")
    return normalized


def load_followup_review_template(db: Session, user: dict[str, Any]) -> dict[str, Any]:
    username = _user_name(user)
    user_row = db.scalar(select(User).where(User.username == username)) if username else None
    raw_template = user_row.followup_review_template if user_row else None
    sections = normalize_followup_review_template(raw_template, fallback_to_default=True)
    return {
        "sections": sections,
        "use_default": raw_template is None,
        "customized": raw_template is not None,
        "editable": bool(user_row),
    }


def save_followup_review_template(db: Session, user: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    username = _user_name(user)
    if not username:
        raise HTTPException(status_code=401, detail="未登录")

    user_row = db.scalar(select(User).where(User.username == username))
    if not user_row:
        raise HTTPException(status_code=404, detail="当前账号未绑定用户模板")

    if bool(payload.get("use_default")):
        user_row.followup_review_template = None
        db.commit()
        return {
            "sections": copy.deepcopy(DEFAULT_FOLLOWUP_REVIEW_TEMPLATE),
            "use_default": True,
            "customized": False,
            "editable": True,
        }

    sections = validate_followup_review_template(payload.get("sections"))
    user_row.followup_review_template = sections
    db.commit()
    return {
        "sections": sections,
        "use_default": False,
        "customized": True,
        "editable": True,
    }


def build_followup_review_system_prompt(
    reviewer_name: str,
    tag_tree_data: Any,
    template_sections: list[dict[str, Any]],
) -> str:
    sections = [section for section in normalize_followup_review_template(template_sections) if section.get("enabled", True)]
    if not sections:
        sections = [section for section in DEFAULT_FOLLOWUP_REVIEW_TEMPLATE if section.get("enabled", True)]
    section_lines: list[str] = []
    for index, section in enumerate(sections, start=1):
        section_lines.append(
            f"{index}. key: {section['key']}\n"
            f"   title: {section['title']}\n"
            f"   instruction: {section['instruction']}"
        )
    sections_text = "\n".join(section_lines)

    return f"""你是帆软内部的客户成功记录员。
从会议转写或图片中提取结构化跟进记录。
输出纯 JSON，包含以下字段：
{{
  "follow_type": "线上跟进/线下跟进/内部沟通 选一个",
  "review_date": "YYYY-MM-DD",
  "review_sections": {{
    "section_key": "按模板要求生成的正文段落内容"
  }},
  "genjin_tags": [{{"level1": "...", "level2": "...", "level3": "..."}}],
  "contact_names": "字符串",
  "if_tuisong": "否"
}}

## 正文模板
{sections_text}

## 生成要求
- review_sections 必须包含模板中所有启用段落的 key。
- 每个 key 的值都必须是字符串，内容由你根据模板 instruction 完成语义归纳。
- 特别注意“客户预期、关注点、客户态度、推进风险、下一步建议”等内容必须由你识别并写入对应段落。
- 只能依据输入中明确出现的信息生成，严禁根据客户名称、常识、模板标题或零散关键词脑补会议背景、需求、方案、版本、数字、角色关系。
- 如果输入是占位词、测试词、寒暄、无意义短句，或有效信息不足以支撑生成跟进记录，则返回“信息不足”的保守结果，不要编造内容。
- “信息不足”的保守结果规则：
  - review_sections 仍需包含所有启用段落的 key。
  - 跟进目的、整体Review 等无法判断的段落返回空字符串。
  - 沟通详情等事实记录段落，只能填写输入里确实出现的原文；如果连可引用原文都没有，就返回空字符串。
  - genjin_tags 返回空数组。
  - contact_names 返回空字符串。
  - review_date 无法判断时返回空字符串。
- 不要输出 review_record，后端会按模板顺序渲染。
- 我方记录人：{reviewer_name}
- genjin_tags 从下面树中选择，level3 可为空字符串：
{json.dumps(tag_tree_data, ensure_ascii=False, indent=2)}
- 只输出纯 JSON，不要 markdown 代码块，不要额外文字。"""


def render_followup_review_record(
    template_sections: list[dict[str, Any]],
    review_sections: dict[str, Any] | None,
) -> str:
    sections = [section for section in normalize_followup_review_template(template_sections) if section.get("enabled", True)]
    if not sections:
        sections = [section for section in DEFAULT_FOLLOWUP_REVIEW_TEMPLATE if section.get("enabled", True)]
    review_sections = review_sections or {}
    blocks: list[str] = []
    for section in sections:
        key = str(section.get("key") or "").strip()
        title = str(section.get("title") or "").strip()
        if not title:
            continue
        content = str(review_sections.get(key, "") or "").strip()
        block = f"【{title}】"
        if content:
            block = f"{block}\n{content}"
        blocks.append(block)
    return "\n\n".join(blocks).strip()
