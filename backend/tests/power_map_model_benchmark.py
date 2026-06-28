from __future__ import annotations

import asyncio
import copy
import json
import os
import re
import sys
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal
from app.models import SystemConfig
from app.services import power_map_service
from app.services.openai_compatible_agent_client import OpenAICompatibleAgentClient
from tests.power_map_context_builder import PowerMapContextBuilder
from tests.test_power_map_cleaning_contract import LONG_HAIYOU_RAW


DEFAULT_MODELS = [
    "glm-5.1",
    "kimi-k2.6",
    "qwen3.7-max",
    "claude-haiku-4-5",
    "claude-sonnet-4-6",
]

COMPANY_ID = "591b9750ee5634a14faed52c682b71066fa4b1ab2096cfc73e763de04d51dc4f"
PRJ_ID = "798b6f52-2d62-48cf-b40a-dac5d37cc767"
VERSION_ID_MAIN = "74385bec-e172-447e-940a-622bc5885c24"
VERSION_ID_CS = "028bf0a8-9867-47f9-8993-2434dcf8f1a9"
DEFAULT_VERSION_ID = VERSION_ID_CS
TRACE_FILE: Path | None = None
TEXT_ONLY_MODELS = {"qwen3.7-max"}
STUB_SCREENSHOT = (os.getenv("POWERMAP_BENCH_STUB_SCREENSHOT") or "").strip().lower() in {"1", "true", "yes", "on"}
BLANK_PNG_DATA_URL = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9sZ4Vf8AAAAASUVORK5CYII="
)

MESSAGE = """建一个完整的公司组织架构：

总裁办：黄宇任 CEO，苏女士任总裁助理向黄宇汇报。

下设五个部门，部门负责人都向黄宇汇报：

财务部：纪成任财务总监，下面有王女士、占荣两个会计，都向纪成汇报。

销售部：张强任销售总监，下设两个小组：
- 华东销售组：王伟任组长向张强汇报，李光昭、艾翔两位销售经理向王伟汇报
- 华南销售组：陈大志任组长向张强汇报，谭杰桂、周浩两位销售经理向陈大志汇报

市场部：吴博昂任市场总监，下面有谢博、朱先生两个市场专员，都向吴博昂汇报。

技术部：王先生任技术总监，下设测试组，程凯任测试组长向王先生汇报，虚拟测试人员、测试、测试2 三人都向程凯汇报。

人力资源部：黄先生任 HR 总监，下面有曹强、陆冠顺两个 HR 专员，都向黄先生汇报。"""

HAIYOU_MESSAGE = LONG_HAIYOU_RAW * 5

HQ_SUBSIDIARY_MESSAGE = """建立集团总部组织：
集团总部下设财务中心、信息中心、华东子公司、华南子公司。
集团总裁在集团总部。
财务负责人在财务中心，CIO 在信息中心，华东总经理在华东子公司，华南总经理在华南子公司。
财务负责人、CIO、华东总经理、华南总经理都向集团总裁汇报。
注意：财务中心、信息中心、两家子公司都是集团总部下的同级容器，不要互相嵌套。"""

MATRIX_PROJECT_MESSAGE = """建立工程公司矩阵项目关系：
工程公司下设设计院、采购中心、建造基地、海上项目组。
项目经理在海上项目组；设计负责人在设计院；采购负责人在采购中心；建造负责人在建造基地。
设计负责人、采购负责人、建造负责人对项目经理是项目协作/影响关系，不是组织归属。
不要把设计院、采购中心、建造基地放到海上项目组下面。"""

THREE_LEVEL_COMPANY_TEAM_MESSAGE = """建立三级客户成功组织：
华东公司下设客户成功部。
客户成功部下设 KA小组、续费小组。
公司总经理在华东公司；客户成功负责人在客户成功部；KA组长在 KA小组；续费组长在续费小组。
客户成功负责人向公司总经理汇报，KA组长和续费组长都向客户成功负责人汇报。
注意：KA小组、续费小组是客户成功部下属小组，不要和客户成功部并列，也不要挂到华东公司下。"""

FOUR_LEVEL_REGION_STORE_MESSAGE = """建立四级零售组织：
零售公司下设华南大区，华南大区下设广州城市组，广州城市组下设天河门店，天河门店下设早班班组。
零售总经理在零售公司；大区经理在华南大区；城市经理在广州城市组；店长在天河门店；班组长在早班班组。
大区经理向零售总经理汇报，城市经理向大区经理汇报，店长向城市经理汇报，班组长向店长汇报。
注意：这是逐级容器归属，不要因为汇报链把门店或班组拉平。"""

BENCHMARK_CASES = {
    "huangyu_org": MESSAGE,
    "haiyou_long_prompt": HAIYOU_MESSAGE,
    "hq_subsidiary": HQ_SUBSIDIARY_MESSAGE,
    "matrix_project": MATRIX_PROJECT_MESSAGE,
    "three_level_company_team": THREE_LEVEL_COMPANY_TEAM_MESSAGE,
    "four_level_region_store": FOUR_LEVEL_REGION_STORE_MESSAGE,
}

BENCHMARK_CASE_GROUPS = {
    "semantic_smoke": [
        "huangyu_org",
        "three_level_company_team",
        "four_level_region_store",
        "haiyou_long_prompt",
    ],
    "business_semantics": [
        "huangyu_org",
        "three_level_company_team",
        "four_level_region_store",
        "hq_subsidiary",
        "matrix_project",
        "haiyou_long_prompt",
    ],
}

CASE_EXPECTATIONS: dict[str, dict[str, Any]] = {
    "huangyu_org": {
        "min_nodes": 32,
        "min_edges": 22,
        "allowed_top_level_parents": {"公司总部"},
        "dept_parents": {
            "总裁办": "",
            "财务部": "",
            "销售部": "",
            "华东销售组": "销售部",
            "华南销售组": "销售部",
            "市场部": "",
            "技术部": "",
            "测试组": "技术部",
            "人力资源部": "",
        },
        "person_parents": {
            "黄宇": "总裁办",
            "苏女士": "总裁办",
            "纪成": "财务部",
            "张强": "销售部",
            "程凯": "测试组",
        },
        "report_edges": {
            ("苏女士", "黄宇"),
            ("纪成", "黄宇"),
            ("张强", "黄宇"),
            ("王伟", "张强"),
            ("李光昭", "王伟"),
            ("陈大志", "张强"),
            ("程凯", "王先生"),
            ("曹强", "黄先生"),
        },
    },
    "haiyou_long_prompt": {
        "dept_parents": {
            "中国海洋石油集团": "",
            "海油工程": "中国海洋石油集团",
            "机关部室": "海油工程",
            "科技信息部": "机关部室",
            "研发中心": "科技信息部",
            "ITC": "研发中心",
            "设计院": "设计板块",
        },
        "person_parents": {
            "吕亚平": "研发中心",
            "你本人": "ITC",
            "刘墨林": "科技信息部",
        },
        "report_edges": {
            ("你本人", "吕亚平"),
        },
    },
    "hq_subsidiary": {
        "dept_parents": {
            "集团总部": "",
            "财务中心": "集团总部",
            "信息中心": "集团总部",
            "华东子公司": "集团总部",
            "华南子公司": "集团总部",
        },
        "report_edges": {
            ("财务负责人", "集团总裁"),
            ("CIO", "集团总裁"),
            ("华东总经理", "集团总裁"),
            ("华南总经理", "集团总裁"),
        },
    },
    "matrix_project": {
        "dept_parents": {
            "工程公司": "",
            "设计院": "工程公司",
            "采购中心": "工程公司",
            "建造基地": "工程公司",
            "海上项目组": "工程公司",
        },
        "influences": {
            ("设计负责人", "项目经理"),
            ("采购负责人", "项目经理"),
            ("建造负责人", "项目经理"),
        },
    },
    "three_level_company_team": {
        "dept_parents": {
            "华东公司": "",
            "客户成功部": "华东公司",
            "KA小组": "客户成功部",
            "续费小组": "客户成功部",
        },
        "person_parents": {
            "公司总经理": "华东公司",
            "客户成功负责人": "客户成功部",
            "KA组长": "KA小组",
            "续费组长": "续费小组",
        },
        "report_edges": {
            ("客户成功负责人", "公司总经理"),
            ("KA组长", "客户成功负责人"),
            ("续费组长", "客户成功负责人"),
        },
    },
    "four_level_region_store": {
        "dept_parents": {
            "零售公司": "",
            "华南大区": "零售公司",
            "广州城市组": "华南大区",
            "天河门店": "广州城市组",
            "早班班组": "天河门店",
        },
        "person_parents": {
            "零售总经理": "零售公司",
            "大区经理": "华南大区",
            "城市经理": "广州城市组",
            "店长": "天河门店",
            "班组长": "早班班组",
        },
        "report_edges": {
            ("大区经理", "零售总经理"),
            ("城市经理", "大区经理"),
            ("店长", "城市经理"),
            ("班组长", "店长"),
        },
    },
}

BENCHMARK_INTENTS: dict[str, dict[str, Any]] = {
    "huangyu_org": {
        "departments": [
            {"name": "总裁办", "parent": ""},
            {"name": "财务部", "parent": ""},
            {"name": "销售部", "parent": ""},
            {"name": "华东销售组", "parent": "销售部"},
            {"name": "华南销售组", "parent": "销售部"},
            {"name": "市场部", "parent": ""},
            {"name": "技术部", "parent": ""},
            {"name": "测试组", "parent": "技术部"},
            {"name": "人力资源部", "parent": ""},
        ],
        "people": [
            {"name": "黄宇", "title": "CEO", "parent": "总裁办"},
            {"name": "苏女士", "title": "总裁助理", "parent": "总裁办"},
            {"name": "纪成", "title": "财务总监", "parent": "财务部"},
            {"name": "王女士", "title": "会计", "parent": "财务部"},
            {"name": "占荣", "title": "会计", "parent": "财务部"},
            {"name": "张强", "title": "销售总监", "parent": "销售部"},
            {"name": "王伟", "title": "华东组长", "parent": "华东销售组"},
            {"name": "李光昭", "title": "销售经理", "parent": "华东销售组"},
            {"name": "艾翔", "title": "销售经理", "parent": "华东销售组"},
            {"name": "陈大志", "title": "华南组长", "parent": "华南销售组"},
            {"name": "谭杰桂", "title": "销售经理", "parent": "华南销售组"},
            {"name": "周浩", "title": "销售经理", "parent": "华南销售组"},
            {"name": "吴博昂", "title": "市场总监", "parent": "市场部"},
            {"name": "谢博", "title": "市场专员", "parent": "市场部"},
            {"name": "朱先生", "title": "市场专员", "parent": "市场部"},
            {"name": "王先生", "title": "技术总监", "parent": "技术部"},
            {"name": "程凯", "title": "测试组长", "parent": "测试组"},
            {"name": "虚拟测试人员", "title": "测试人员", "parent": "测试组"},
            {"name": "测试", "title": "测试人员", "parent": "测试组"},
            {"name": "测试2", "title": "测试人员", "parent": "测试组"},
            {"name": "黄先生", "title": "HR 总监", "parent": "人力资源部"},
            {"name": "曹强", "title": "HR 专员", "parent": "人力资源部"},
            {"name": "陆冠顺", "title": "HR 专员", "parent": "人力资源部"},
        ],
        "report_edges": [
            {"source": "苏女士", "target": "黄宇"},
            {"source": "纪成", "target": "黄宇"},
            {"source": "张强", "target": "黄宇"},
            {"source": "吴博昂", "target": "黄宇"},
            {"source": "王先生", "target": "黄宇"},
            {"source": "黄先生", "target": "黄宇"},
            {"source": "王女士", "target": "纪成"},
            {"source": "占荣", "target": "纪成"},
            {"source": "王伟", "target": "张强"},
            {"source": "陈大志", "target": "张强"},
            {"source": "李光昭", "target": "王伟"},
            {"source": "艾翔", "target": "王伟"},
            {"source": "谭杰桂", "target": "陈大志"},
            {"source": "周浩", "target": "陈大志"},
            {"source": "谢博", "target": "吴博昂"},
            {"source": "朱先生", "target": "吴博昂"},
            {"source": "程凯", "target": "王先生"},
            {"source": "虚拟测试人员", "target": "程凯"},
            {"source": "测试", "target": "程凯"},
            {"source": "测试2", "target": "程凯"},
            {"source": "曹强", "target": "黄先生"},
            {"source": "陆冠顺", "target": "黄先生"},
        ],
    },
    "haiyou_long_prompt": {
        "departments": [
            {"name": "中国海洋石油集团", "parent": ""},
            {"name": "海油工程", "parent": "中国海洋石油集团"},
            {"name": "机关部室", "parent": "海油工程"},
            {"name": "人事", "parent": "机关部室"},
            {"name": "财务", "parent": "机关部室"},
            {"name": "党群", "parent": "机关部室"},
            {"name": "科技信息部", "parent": "机关部室"},
            {"name": "研发中心", "parent": "科技信息部"},
            {"name": "ITC", "parent": "研发中心"},
            {"name": "设计板块", "parent": "海油工程"},
            {"name": "设计院", "parent": "设计板块"},
            {"name": "上海分部", "parent": "设计院"},
            {"name": "深圳分部", "parent": "设计院"},
            {"name": "采购板块", "parent": "海油工程"},
            {"name": "采办共享中心", "parent": "采购板块"},
            {"name": "建造板块", "parent": "海油工程"},
            {"name": "天津智能制造基地", "parent": "建造板块"},
            {"name": "中海福陆", "parent": "建造板块"},
            {"name": "青岛子公司", "parent": "建造板块"},
            {"name": "塘沽基地", "parent": "建造板块"},
            {"name": "安装板块", "parent": "海油工程"},
            {"name": "安装分公司", "parent": "安装板块"},
            {"name": "深圳子公司", "parent": "安装板块"},
            {"name": "运维/项目管理板块", "parent": "海油工程"},
            {"name": "工程项目分公司", "parent": "运维/项目管理板块"},
            {"name": "海油工程国际有限公司", "parent": "运维/项目管理板块"},
            {"name": "特种/新能源板块", "parent": "海油工程"},
        ],
        "people": [
            {"name": "分管领导", "title": "信息化分管领导", "parent": "海油工程"},
            {"name": "吕亚平", "title": "研发中心领导", "parent": "研发中心"},
            {"name": "你本人", "title": "ITC 副职/技术负责人", "parent": "ITC"},
            {"name": "刘墨林", "title": "科技信息部联系人", "parent": "科技信息部"},
        ],
        "report_edges": [
            {"source": "你本人", "target": "吕亚平"},
            {"source": "刘墨林", "target": "分管领导"},
        ],
        "constraints": ["天津中车不是天津智能制造基地"],
    },
    "hq_subsidiary": {
        "departments": [
            {"name": "集团总部", "parent": ""},
            {"name": "财务中心", "parent": "集团总部"},
            {"name": "信息中心", "parent": "集团总部"},
            {"name": "华东子公司", "parent": "集团总部"},
            {"name": "华南子公司", "parent": "集团总部"},
        ],
        "people": [
            {"name": "集团总裁", "title": "总裁", "parent": "集团总部"},
            {"name": "财务负责人", "parent": "财务中心"},
            {"name": "CIO", "parent": "信息中心"},
            {"name": "华东总经理", "parent": "华东子公司"},
            {"name": "华南总经理", "parent": "华南子公司"},
        ],
        "report_edges": [
            {"source": "财务负责人", "target": "集团总裁"},
            {"source": "CIO", "target": "集团总裁"},
            {"source": "华东总经理", "target": "集团总裁"},
            {"source": "华南总经理", "target": "集团总裁"},
        ],
    },
    "matrix_project": {
        "departments": [
            {"name": "工程公司", "parent": ""},
            {"name": "设计院", "parent": "工程公司"},
            {"name": "采购中心", "parent": "工程公司"},
            {"name": "建造基地", "parent": "工程公司"},
            {"name": "海上项目组", "parent": "工程公司"},
        ],
        "people": [
            {"name": "项目经理", "title": "项目经理", "parent": "海上项目组"},
            {"name": "设计负责人", "title": "设计负责人", "parent": "设计院"},
            {"name": "采购负责人", "title": "采购负责人", "parent": "采购中心"},
            {"name": "建造负责人", "title": "建造负责人", "parent": "建造基地"},
        ],
        "report_edges": [
            {"source": "设计负责人", "target": "项目经理", "relation": "influences"},
            {"source": "采购负责人", "target": "项目经理", "relation": "influences"},
            {"source": "建造负责人", "target": "项目经理", "relation": "influences"},
        ],
        "constraints": ["项目矩阵是协作关系，不改变组织归属"],
    },
    "three_level_company_team": {
        "departments": [
            {"name": "华东公司", "parent": ""},
            {"name": "客户成功部", "parent": "华东公司"},
            {"name": "KA小组", "parent": "客户成功部"},
            {"name": "续费小组", "parent": "客户成功部"},
        ],
        "people": [
            {"name": "公司总经理", "parent": "华东公司"},
            {"name": "客户成功负责人", "parent": "客户成功部"},
            {"name": "KA组长", "parent": "KA小组"},
            {"name": "续费组长", "parent": "续费小组"},
        ],
        "report_edges": [
            {"source": "客户成功负责人", "target": "公司总经理"},
            {"source": "KA组长", "target": "客户成功负责人"},
            {"source": "续费组长", "target": "客户成功负责人"},
        ],
    },
    "four_level_region_store": {
        "departments": [
            {"name": "零售公司", "parent": ""},
            {"name": "华南大区", "parent": "零售公司"},
            {"name": "广州城市组", "parent": "华南大区"},
            {"name": "天河门店", "parent": "广州城市组"},
            {"name": "早班班组", "parent": "天河门店"},
        ],
        "people": [
            {"name": "零售总经理", "parent": "零售公司"},
            {"name": "大区经理", "parent": "华南大区"},
            {"name": "城市经理", "parent": "广州城市组"},
            {"name": "店长", "parent": "天河门店"},
            {"name": "班组长", "parent": "早班班组"},
        ],
        "report_edges": [
            {"source": "大区经理", "target": "零售总经理"},
            {"source": "城市经理", "target": "大区经理"},
            {"source": "店长", "target": "城市经理"},
            {"source": "班组长", "target": "店长"},
        ],
    },
}


@dataclass
class RunStat:
    model: str
    case: str = ""
    version_id: str = DEFAULT_VERSION_ID
    prj_id: str = PRJ_ID
    ok: bool = False
    error: str = ""
    session_id: str = ""
    rounds: int = 0
    elapsed_s: float = 0.0
    tool_calls: int = 0
    tool_results: int = 0
    relayout_called: bool = False
    radial_fast_path: bool = False
    final_event: str = ""
    final_payload: dict[str, Any] = field(default_factory=dict)
    validation: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)


class DbProxy:
    def __init__(self, db, cfg_override):
        self._db = db
        self._cfg_override = cfg_override

    def get(self, model, ident):
        if model is SystemConfig and ident == 1:
            return self._cfg_override
        return self._db.get(model, ident)

    def __getattr__(self, name):
        return getattr(self._db, name)


def _trace(payload: dict[str, Any]) -> None:
    line = json.dumps(payload, ensure_ascii=False)
    if TRACE_FILE is not None:
        TRACE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with TRACE_FILE.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    print(line, flush=True)


def _clone_cfg(cfg: SystemConfig, model_name: str) -> SystemConfig:
    cloned = copy.copy(cfg)
    cloned.nl_chat_model = model_name
    cloned.agent_a_model = model_name
    cloned.agent_b_model = model_name
    provider = os.getenv("POWERMAP_BENCH_LLM_PROVIDER", "").strip()
    base_url = os.getenv("POWERMAP_BENCH_LLM_BASE_URL", "").strip()
    api_key = os.getenv("POWERMAP_BENCH_LLM_API_KEY", "").strip()
    if provider:
        cloned.llm_provider = provider
    if base_url:
        cloned.llm_base_url = base_url
    if api_key:
        cloned.llm_api_key_encrypted = api_key
    return cloned


async def _fixed_resolve_prj_id(db, cfg, company_id: str) -> str:
    return PRJ_ID


async def _benchmark_sandbox_screenshot(*args, **kwargs) -> str:
    _trace({"stage": "sandbox_screenshot_stub"})
    return BLANK_PNG_DATA_URL


def _wrap_async_trace(name: str, fn):
    async def _wrapped(*args, **kwargs):
        _trace({"stage": f"{name}_start"})
        started = time.monotonic()
        try:
            result = await fn(*args, **kwargs)
            summary: dict[str, Any] = {"stage": f"{name}_done", "elapsed_s": round(time.monotonic() - started, 3)}
            if isinstance(result, dict):
                if "nodes" in result:
                    summary["nodes"] = len(result.get("nodes") or [])
                if "edges" in result:
                    summary["edges"] = len(result.get("edges") or [])
            _trace(summary)
            return result
        except Exception as exc:
            _trace({"stage": f"{name}_error", "elapsed_s": round(time.monotonic() - started, 3), "error": f"{type(exc).__name__}: {exc}"})
            raise

    return _wrapped


def _strip_image_blocks(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    stripped: list[dict[str, Any]] = []
    for msg in messages:
        cloned = copy.deepcopy(msg)
        content = cloned.get("content")
        if isinstance(content, list):
            cloned["content"] = [
                block
                for block in content
                if not (isinstance(block, dict) and block.get("type") == "image_url")
            ]
        stripped.append(cloned)
    return stripped


def _last_layout_snapshot(stat: RunStat) -> dict[str, Any] | None:
    for event in reversed(stat.events):
        if event.get("type") != "graph_state":
            continue
        data = event.get("data") or {}
        snapshot = data.get("layout_snapshot")
        if isinstance(snapshot, dict):
            return snapshot
    return None


def _boxes_overlap(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return not (
        float(a.get("x", 0)) + float(a.get("w", 0)) <= float(b.get("x", 0))
        or float(b.get("x", 0)) + float(b.get("w", 0)) <= float(a.get("x", 0))
        or float(a.get("y", 0)) + float(a.get("h", 0)) <= float(b.get("y", 0))
        or float(b.get("y", 0)) + float(b.get("h", 0)) <= float(a.get("y", 0))
    )


def _box_contains(outer: dict[str, Any], inner: dict[str, Any]) -> bool:
    return (
        float(outer.get("x", 0)) <= float(inner.get("x", 0))
        and float(outer.get("y", 0)) <= float(inner.get("y", 0))
        and float(inner.get("x", 0)) + float(inner.get("w", 0))
        <= float(outer.get("x", 0)) + float(outer.get("w", 0))
        and float(inner.get("y", 0)) + float(inner.get("h", 0))
        <= float(outer.get("y", 0)) + float(outer.get("h", 0))
    )


def _validate_case_result(case_name: str, stat: RunStat) -> dict[str, Any]:
    expected = CASE_EXPECTATIONS.get(case_name, {})
    errors: list[str] = []
    snapshot = _last_layout_snapshot(stat)
    if not snapshot:
        return {"ok": False, "errors": ["missing layout_snapshot"]}

    nodes = snapshot.get("nodes") or []
    edges = snapshot.get("edges") or []
    by_id = {str(n.get("id")): n for n in nodes if n.get("id")}
    by_name = {str(n.get("name")): n for n in nodes if n.get("name")}

    if len(nodes) < int(expected.get("min_nodes", 0)):
        errors.append(f"nodes {len(nodes)} < expected {expected['min_nodes']}")
    if len(edges) < int(expected.get("min_edges", 0)):
        errors.append(f"edges {len(edges)} < expected {expected['min_edges']}")

    def parent_name(node: dict[str, Any]) -> str:
        parent_id = str(node.get("parent_dept_id") or "")
        if not parent_id:
            return ""
        return str((by_id.get(parent_id) or {}).get("name") or "")

    def is_descendant(node: dict[str, Any], ancestor: dict[str, Any]) -> bool:
        ancestor_id = str(ancestor.get("id") or "")
        parent_id = str(node.get("parent_dept_id") or "")
        seen: set[str] = set()
        while parent_id and parent_id not in seen:
            if parent_id == ancestor_id:
                return True
            seen.add(parent_id)
            parent_id = str((by_id.get(parent_id) or {}).get("parent_dept_id") or "")
        return False

    for child, parent in (expected.get("dept_parents") or {}).items():
        node = by_name.get(child)
        if not node:
            errors.append(f"missing dept {child}")
            continue
        actual = parent_name(node)
        allowed_top_level_parents = set(expected.get("allowed_top_level_parents") or set())
        if parent == "" and actual in allowed_top_level_parents:
            actual_parent_node = by_name.get(actual)
            if actual_parent_node and parent_name(actual_parent_node) == "":
                continue
        if actual != parent:
            errors.append(f"dept_parent {child}: {actual!r} != {parent!r}")

    for child, parent in (expected.get("person_parents") or {}).items():
        node = by_name.get(child)
        if not node:
            errors.append(f"missing person {child}")
            continue
        actual = parent_name(node)
        if actual != parent:
            errors.append(f"person_parent {child}: {actual!r} != {parent!r}")

    edge_pairs_by_type: dict[str, set[tuple[str, str]]] = {}
    for edge in edges:
        src = by_id.get(str(edge.get("source_id") or ""))
        tgt = by_id.get(str(edge.get("target_id") or ""))
        if not src or not tgt:
            continue
        edge_type = str(edge.get("edge_type") or "reports_to")
        edge_pairs_by_type.setdefault(edge_type, set()).add((str(src.get("name")), str(tgt.get("name"))))
    missing_reports = set(expected.get("report_edges") or set()) - edge_pairs_by_type.get("reports_to", set())
    missing_influences = set(expected.get("influences") or set()) - edge_pairs_by_type.get("influences", set())
    for pair in sorted(missing_reports):
        errors.append(f"missing report_edge {pair[0]}->{pair[1]}")
    for pair in sorted(missing_influences):
        errors.append(f"missing influence_edge {pair[0]}->{pair[1]}")

    for node in nodes:
        parent_id = str(node.get("parent_dept_id") or "")
        if not parent_id:
            continue
        parent = by_id.get(parent_id)
        if not parent:
            errors.append(f"{node.get('name')} parent id missing: {parent_id}")
            continue
        if (
            float(node.get("x", 0)) < float(parent.get("x", 0))
            or float(node.get("y", 0)) < float(parent.get("y", 0))
            or float(node.get("x", 0)) + float(node.get("w", 0)) > float(parent.get("x", 0)) + float(parent.get("w", 0))
            or float(node.get("y", 0)) + float(node.get("h", 0)) > float(parent.get("y", 0)) + float(parent.get("h", 0))
        ):
            errors.append(f"{node.get('name')} is outside parent {parent.get('name')}")

    siblings_by_parent: dict[str, list[dict[str, Any]]] = {}
    for node in nodes:
        siblings_by_parent.setdefault(str(node.get("parent_dept_id") or ""), []).append(node)
    for siblings in siblings_by_parent.values():
        for idx, left in enumerate(siblings):
            for right in siblings[idx + 1 :]:
                if _boxes_overlap(left, right):
                    errors.append(f"sibling overlap {left.get('name')} <-> {right.get('name')}")

    dept_nodes = [node for node in nodes if node.get("type") == "department"]
    for outer in dept_nodes:
        for inner in dept_nodes:
            if outer is inner or is_descendant(inner, outer):
                continue
            if _box_contains(outer, inner):
                errors.append(
                    f"false dept containment {outer.get('name')} wraps non-child {inner.get('name')}"
                )

    for source, target in edge_pairs_by_type.get("reports_to", set()):
        src = by_name.get(source)
        tgt = by_name.get(target)
        if src and tgt and float(src.get("y", 0)) <= float(tgt.get("y", 0)):
            errors.append(f"report edge not downward {source}->{target}")

    return {
        "ok": not errors,
        "errors": errors,
        "nodes": len(nodes),
        "edges": len(edges),
        "departments": sum(1 for node in nodes if node.get("type") == "department"),
        "people": sum(1 for node in nodes if node.get("type") == "person"),
        "reports_to_edges": len(edge_pairs_by_type.get("reports_to", set())),
        "influences_edges": len(edge_pairs_by_type.get("influences", set())),
    }


def _resolve_case_names(case: str, cases: str | None = None) -> list[str]:
    """Resolve CLI case selection while preserving a stable output order."""
    spec = (cases or case or "huangyu_org").strip()
    if spec.lower() in {"all", "*"}:
        return sorted(BENCHMARK_CASES.keys())

    selected: list[str] = []
    unknown: list[str] = []
    for raw_name in spec.split(","):
        name = raw_name.strip()
        if not name:
            continue
        if name in BENCHMARK_CASE_GROUPS:
            for grouped_name in BENCHMARK_CASE_GROUPS[name]:
                if grouped_name not in selected:
                    selected.append(grouped_name)
            continue
        if name not in BENCHMARK_CASES:
            unknown.append(name)
            continue
        if name not in selected:
            selected.append(name)
    if unknown:
        raise ValueError(f"unknown benchmark case(s): {', '.join(unknown)}")
    if not selected:
        raise ValueError("no benchmark cases selected")
    return selected


def _benchmark_output_filename(case_name: str, model_name: str, *, multi_case: bool) -> str:
    safe_case = re.sub(r"[^A-Za-z0-9_.-]+", "_", case_name)
    safe_model = re.sub(r"[^A-Za-z0-9_.-]+", "_", model_name)
    return f"{safe_case}__{safe_model}.json" if multi_case else f"{safe_model}.json"


def _build_benchmark_summary(
    *,
    stats: list[RunStat],
    run_cases: list[str],
    version_id: str,
    no_commit: bool,
    dry_run_intent: bool,
) -> dict[str, Any]:
    failed = [
        {"case": s.case, "model": s.model, "error": s.error, "validation": s.validation}
        for s in stats
        if not s.ok
    ]
    passed = [s for s in stats if s.ok]
    return {
        "company_id": COMPANY_ID,
        "prj_id": PRJ_ID,
        "version_id": version_id,
        "case": run_cases[0] if len(run_cases) == 1 else None,
        "cases": run_cases,
        "dry_run_intent": bool(dry_run_intent),
        "no_commit": bool(no_commit),
        "models": [asdict(s) for s in stats] if len(run_cases) == 1 else [],
        "runs": [asdict(s) for s in stats],
        "ok": not failed and len(stats) > 0,
        "pass_count": len(passed),
        "fail_count": len(failed),
        "run_count": len(stats),
        "failed": failed,
    }


def _layout_snapshot_from_context(ctx) -> dict[str, Any]:
    return {
        "nodes": [
            {
                "id": n.id,
                "name": n.name,
                "type": "person" if n.node_type == "user" else "department",
                "subtype": n.subtype,
                "parent_dept_id": n.parent_dept_id,
                "pid": n.pid,
                "position": n.position,
                "x": round(float(n.x), 2),
                "y": round(float(n.y), 2),
                "w": round(float(n.w), 2),
                "h": round(float(n.h), 2),
            }
            for n in ctx.all_nodes
        ],
        "edges": [
            {
                "id": str(e.get("id", "")),
                "source_id": str(e.get("source_id", "")),
                "target_id": str(e.get("target_id", "")),
                "edge_type": str(e.get("edge_type", "")),
            }
            for e in ctx.edges
        ],
    }


async def _run_intent_case(case_name: str, model_name: str, version_id: str) -> RunStat:
    started = time.monotonic()
    stat = RunStat(model=model_name, case=case_name, version_id=version_id, prj_id=PRJ_ID)
    intent_data = BENCHMARK_INTENTS.get(case_name)
    if not intent_data:
        stat.error = f"intent_missing_for_case:{case_name}"
        stat.validation = {"ok": False, "errors": [stat.error]}
        stat.elapsed_s = time.monotonic() - started
        return stat

    ctx = power_map_service.MergeContext()
    try:
        intent = power_map_service._parse_power_map_intent(json.dumps(intent_data, ensure_ascii=False))
        result = power_map_service._apply_power_map_intent_to_context(ctx, intent)
        stat.final_event = "dry_run_intent"
        stat.final_payload = result
        stat.radial_fast_path = bool(result.get("radial_layout_used"))
        stat.relayout_called = bool(result.get("relayout_called"))
        stat.tool_results = len(ctx.edges)
        stat.events.append({"type": "graph_state", "data": {"layout_snapshot": _layout_snapshot_from_context(ctx)}})
        if result.get("ok"):
            stat.ok = True
        else:
            stat.error = "intent_apply_failed: " + "; ".join(str(x) for x in result.get("errors", [])[:5])
    except Exception as exc:
        stat.error = f"{type(exc).__name__}: {exc}"
    stat.elapsed_s = time.monotonic() - started
    return stat


async def _run_one(model_name: str, version_id: str, message: str = MESSAGE, case_name: str = "") -> RunStat:
    db = SessionLocal()
    stat = RunStat(model=model_name, case=case_name, version_id=version_id, prj_id=PRJ_ID)
    start = time.monotonic()
    original_resolve_prj_id = power_map_service._resolve_prj_id
    original_fetch_from_external = power_map_service._fetch_from_external
    original_sandbox_screenshot = power_map_service._sandbox_screenshot
    original_execute_harness_tool = power_map_service._execute_harness_tool
    original_build_graph_state_text = power_map_service._build_graph_state_text
    original_tool_get_graph_state = power_map_service._tool_get_graph_state
    original_history_stream = OpenAICompatibleAgentClient.messages_create_with_history_stream
    formatter = PowerMapContextBuilder()
    try:
        _trace({"stage": "start", "model": model_name, "version_id": version_id, "prj_id": PRJ_ID})
        cfg = db.get(SystemConfig, 1)
        if not cfg:
            stat.error = "system_config_missing"
            return stat

        proxy = DbProxy(db, _clone_cfg(cfg, model_name))
        user = {"user_id": "admin", "user_name": "admin", "source": "superadmin"}
        power_map_service._resolve_prj_id = _fixed_resolve_prj_id
        power_map_service._fetch_from_external = _wrap_async_trace("fetch_from_external", original_fetch_from_external)
        if model_name in TEXT_ONLY_MODELS or STUB_SCREENSHOT:
            power_map_service._sandbox_screenshot = _benchmark_sandbox_screenshot
        else:
            power_map_service._sandbox_screenshot = _wrap_async_trace("sandbox_screenshot", original_sandbox_screenshot)

        async def _recording_execute_harness_tool(ctx, name, args):
            formatter.record_tool_call(str(name or ""), args if isinstance(args, dict) else {})
            result = await original_execute_harness_tool(ctx, name, args)
            if isinstance(result, dict):
                formatter.record_tool_result(str(name or ""), result)
            else:
                formatter.record_tool_result(str(name or ""), {"ok": False, "raw": str(result)})
            return result

        def _benchmark_graph_state_text(ctx):
            return formatter.build(ctx)

        def _benchmark_tool_get_graph_state(ctx):
            result = original_tool_get_graph_state(ctx)
            result["layout_snapshot"] = {
                "nodes": [
                    {
                        "id": n.id,
                        "name": n.name,
                        "type": "person" if n.node_type == "user" else "department",
                        "subtype": n.subtype,
                        "parent_dept_id": n.parent_dept_id,
                        "pid": n.pid,
                        "position": n.position,
                        "x": round(float(n.x), 2),
                        "y": round(float(n.y), 2),
                        "w": round(float(n.w), 2),
                        "h": round(float(n.h), 2),
                    }
                    for n in ctx.all_nodes
                ],
                "edges": [
                    {
                        "id": str(e.get("id", "")),
                        "source_id": str(e.get("source_id", "")),
                        "target_id": str(e.get("target_id", "")),
                        "edge_type": str(e.get("edge_type", "")),
                    }
                    for e in ctx.edges
                ],
            }
            return result

        power_map_service._execute_harness_tool = _recording_execute_harness_tool
        power_map_service._build_graph_state_text = _benchmark_graph_state_text
        power_map_service._tool_get_graph_state = _benchmark_tool_get_graph_state

        if model_name in TEXT_ONLY_MODELS:
            async def _text_only_history_stream(self, *, model: str, system: str, messages: list[dict[str, Any]], tools=None, max_tokens: int = 2048, temperature: float = 0.1):
                sanitized = _strip_image_blocks(messages)
                _trace({"stage": "text_only_history_stream", "model": model_name, "sanitized_messages": len(sanitized)})
                async for chunk in original_history_stream(
                    self,
                    model=model,
                    system=system,
                    messages=sanitized,
                    tools=tools,
                    max_tokens=max_tokens,
                    temperature=temperature,
                ):
                    yield chunk

            OpenAICompatibleAgentClient.messages_create_with_history_stream = _text_only_history_stream

        _trace({"stage": "chat_enter", "model": model_name})
        async for event in power_map_service.chat_power_map_v2(
            db=proxy,
            company_id=COMPANY_ID,
            message=message,
            current_user=user,
            version=version_id,
            bi_credentials={"cookies": {}, "bearer_token": None},
        ):
            data = event.data if isinstance(event.data, dict) else {"raw": event.data}
            stat.events.append({"type": event.type, "data": data})
            _trace(
                {
                    "stage": "event",
                    "model": model_name,
                    "event_type": event.type,
                    "keys": sorted(data.keys()) if isinstance(data, dict) else [],
                }
            )
            if event.type == "round_start":
                stat.rounds = max(stat.rounds, int(data.get("round", 0) or 0))
                stat.session_id = str(data.get("session_id") or stat.session_id)
                formatter.begin_round(int(data.get("round", 0) or 0))
            elif event.type == "tool_call":
                stat.tool_calls += 1
                if str(data.get("tool") or "") == "relayout":
                    stat.relayout_called = True
            elif event.type == "tool_result":
                stat.tool_results += 1
            elif event.type == "done":
                stat.final_event = "done"
                stat.final_payload = data
                stat.radial_fast_path = bool(data.get("radial_fast_path"))
                if not data.get("error") and not data.get("skipped"):
                    stat.ok = True
                else:
                    stat.error = str(data.get("error") or "")
        stat.elapsed_s = time.monotonic() - start
        return stat
    except Exception as exc:
        stat.error = f"{type(exc).__name__}: {exc}"
        stat.elapsed_s = time.monotonic() - start
        return stat
    finally:
        power_map_service._resolve_prj_id = original_resolve_prj_id
        power_map_service._fetch_from_external = original_fetch_from_external
        power_map_service._sandbox_screenshot = original_sandbox_screenshot
        power_map_service._execute_harness_tool = original_execute_harness_tool
        power_map_service._build_graph_state_text = original_build_graph_state_text
        power_map_service._tool_get_graph_state = original_tool_get_graph_state
        OpenAICompatibleAgentClient.messages_create_with_history_stream = original_history_stream
        db.close()


async def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Power Map model benchmark")
    parser.add_argument("--model", help="Run a single model only")
    parser.add_argument("--case", default="huangyu_org", choices=sorted(BENCHMARK_CASES.keys()))
    parser.add_argument(
        "--cases",
        help="Comma-separated case names, case groups (semantic_smoke/business_semantics), or 'all'. Overrides --case.",
    )
    parser.add_argument("--dry-run-intent", action="store_true", help="Run deterministic local intents through the same validator without LLM/BI.")
    parser.add_argument("--strict-exit", action="store_true", help="Exit with code 1 when any selected case/model fails.")
    parser.add_argument("--no-commit", action="store_true", help="Accepted for safety; benchmark never commits BI.")
    parser.add_argument("--version-id", default=DEFAULT_VERSION_ID, help="BI version id to benchmark against")
    parser.add_argument("--output-dir", default="backend/e2e_output/model_benchmark")
    args = parser.parse_args()

    run_models = [args.model] if args.model else (["intent-dry-run"] if args.dry_run_intent else DEFAULT_MODELS)
    run_cases = _resolve_case_names(args.case, args.cases)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    global TRACE_FILE
    TRACE_FILE = out_dir / "trace.jsonl"
    stats: list[RunStat] = []
    multi_case = len(run_cases) > 1
    _trace({"stage": "main_enter", "models": run_models, "cases": run_cases, "dry_run_intent": bool(args.dry_run_intent), "no_commit": bool(args.no_commit), "output_dir": str(out_dir), "version_id": args.version_id})
    for case_name in run_cases:
        message = BENCHMARK_CASES[case_name]
        for model in run_models:
            if args.dry_run_intent:
                stat = await _run_intent_case(case_name, model, args.version_id)
            else:
                stat = await _run_one(model, args.version_id, message=message, case_name=case_name)
            if stat.ok:
                stat.validation = _validate_case_result(case_name, stat)
                if not stat.validation.get("ok"):
                    stat.ok = False
                    stat.error = "validation_failed: " + "; ".join(stat.validation.get("errors", [])[:5])
            else:
                stat.validation = {"ok": False, "errors": [stat.error or "run_failed"]}
            stats.append(stat)
            (out_dir / _benchmark_output_filename(case_name, model, multi_case=multi_case)).write_text(
                json.dumps(asdict(stat), ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
            print(
                json.dumps(
                    {
                        "case": stat.case,
                        "model": stat.model,
                        "ok": stat.ok,
                        "elapsed_s": round(stat.elapsed_s, 2),
                        "rounds": stat.rounds,
                        "tool_calls": stat.tool_calls,
                        "tool_results": stat.tool_results,
                        "relayout_called": stat.relayout_called,
                        "radial_fast_path": stat.radial_fast_path,
                        "session_id": stat.session_id,
                        "version_id": stat.version_id,
                        "prj_id": stat.prj_id,
                        "validation": stat.validation,
                        "error": stat.error,
                    },
                    ensure_ascii=False,
                )
            )

    summary = _build_benchmark_summary(
        stats=stats,
        run_cases=run_cases,
        version_id=args.version_id,
        no_commit=bool(args.no_commit),
        dry_run_intent=bool(args.dry_run_intent),
    )
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(
        json.dumps(
            {
                "stage": "summary",
                "ok": summary["ok"],
                "pass_count": summary["pass_count"],
                "fail_count": summary["fail_count"],
                "failed": summary["failed"],
            },
            ensure_ascii=False,
        )
    )
    if args.strict_exit and not summary["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
