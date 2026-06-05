"""
US-2 跟进记录生成 · Schema 层
基于 SKILL-09 规范，对齐简道云跟进记录表单字段。
"""
from __future__ import annotations
from typing import Any, Literal
from pydantic import Field
from . import BaseAPIModel, ImageInputItem

# ── 常量：商务行为枚举 ─────────────────────────────────────
BUSINESS_ACTIONS = [
    "线上沟通", "电话沟通", "邮件跟进", "现场拜访",
    "问题处理", "需求跟进", "资料发送", "其他",
]

# ── 常量：行为目的枚举 ─────────────────────────────────────
ACTION_PURPOSES = [
    "问题解决", "需求收集", "关系维护",
    "续费推进", "增购推进", "培训支持", "其他",
]

# ── 常量：跟进标签三级体系 ─────────────────────────────────
GENJIN_TAGS: dict[str, dict[str, list[str]]] = {
    "使用推进": {
        "常态化跟进": [],
        "预期跟进": [],
        "系统部署/环境确认": [],
        "价值汇报/高层触达": [],
        "价值宣导/方案讲解": [],
    },
    "数字人才服务": {
        "线上课程": ["意愿触达", "过程执行"],
        "线下培训": ["意愿触达", "过程执行"],
        "业务沙盘": ["意愿触达", "过程执行"],
        "翻转课堂": ["意愿触达", "过程执行"],
        "人才大赛": ["意愿触达", "过程执行"],
    },
    "续费增购": {
        "服务ARR推动": [],
        "年费续费推动": [],
        "增购推动": [],
        "签单辅助": [],
    },
}


# ── 请求模型 ────────────────────────────────────────────────

class FollowupGenerateRequest(BaseAPIModel):
    """生成跟进记录请求（截图或文字输入）"""
    input_type: Literal["text", "screenshot"] = "text"
    content: str | None = None                     # 文字输入内容
    images: list[ImageInputItem] = []              # 截图 base64 列表
    company_id: str | None = None                  # 已选客户 ID
    company_name: str | None = None                # 公司名提示
    contact_name_hint: str | None = None           # 联系人提示
    date_hint: str | None = None                   # 用户补充日期 YYYY-MM-DD


class FollowupActionItem(BaseAPIModel):
    """后续行动项"""
    person: str = ""                               # 负责人
    task: str = ""                                 # 待办事项
    deadline: str = ""                             # 截止日期 YYYY-MM-DD


class GenjinTag(BaseAPIModel):
    """跟进标签（三级结构）"""
    level1: str = ""                               # 使用推进 | 数字人才服务 | 续费增购
    level2: str = ""                               # 常态化跟进 | 线上课程 | 服务ARR推动 ...
    level3: str = ""                               # 意愿触达 | 过程执行 | ""


class FollowupRecord(BaseAPIModel):
    """LLM 生成的跟进记录（内部结构，用于前端预览编辑）"""
    company_name: str = ""
    contact_person: str = ""
    followup_date: str = ""                        # YYYY-MM-DD
    business_action: str = ""                      # follow_type 枚举值
    action_purpose: str = ""                       # 行为目的枚举值
    background: str = ""                           # 【背景】
    communication_details: list[str] = []          # 【沟通详情】要点
    conclusion: str = ""                           # 【结论】
    followup_actions: list[FollowupActionItem] = []
    genjin_tags: list[GenjinTag] = []              # 跟进标签


# ── 提交模型（对齐简道云 widget）─────────────────────────────

class FollowupSubmitRequest(BaseAPIModel):
    """提交跟进记录到简道云"""
    # 客户名称 → com_name (combo)  — 与 comid 配对，直接写入即选中
    com_name: str = ""
    # 客户ID → comid (text)       — 与 com_name 配对
    comid: str = ""
    # lookup 关联公司 → _widget_1744600409845（可选，用于关联客户主表）
    company_id: str = ""
    # 跟进人 → follower (user)
    follower: str = ""
    # 跟进类型 → follow_type (combo)
    follow_type: str
    # 跟进日期 → review_date (datetime)
    review_date: str
    # 跟进记录 → review_record (textarea) 四段式 Markdown
    review_record: str
    # 跟进标签 → genjin (subform)
    genjin_tags: list[GenjinTag] = []
    # 推送前方 → if_tuisong (radiogroup)
    if_tuisong: str = "否"
    # 联系人ID → contid
    contid: str = ""
    # 联系人姓名 → contname
    contname: str = ""
    # 关联预期 ID；提交时会同时写 review_yuqi_id(text) 和 lookup 关联字段
    yuqi_id: str = ""
