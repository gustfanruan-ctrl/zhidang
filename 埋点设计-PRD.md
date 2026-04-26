---
# 「智档」埋点与数据采集 PRD‑Pro

**文档版本**：V1.0  
**创建日期**：2026-04-23  
**依赖文档**：「智档」PRD V0.1.5  
**产品负责人**：Karl  
**项目总控**：Alois

---

## 1. 文档目的

本文档独立于主 PRD，专门定义智档系统的**全链路埋点方案**，服务于两个核心目标：

**目标一（业务分析）**：让管理层和区域负责人能够回答——"我们的客户成功团队去客户现场都聊了什么、质量怎么样、有没有抓住关键预期"。

**目标二（系统调优）**：让产品和技术团队能够回答——"Agent‑A 提取了多少条预期/场景、用户采纳了几条、改了几条、删了几条，Prompt 和模型应该往哪个方向调"。

---

## 2. 埋点设计原则

**原则一：跟着用户动作走**。每一个用户的主动操作（上传、确认、删除、编辑、写入、对话）都产生一条事件，不遗漏不冗余。

**原则二：跟着数据流转走**。从转写文本进入系统到最终写入简道云，每个环节的输入输出都可追溯，形成完整证据链。

**原则三：不侵入主流程**。埋点采集不阻塞用户操作，所有写入异步完成。即使埋点服务故障，主业务流程不受影响。

**原则四：脱敏优先**。原始转写文本不进埋点表，仅记录摘要和统计量。敏感信息（客户名、公司ID）做哈希或脱敏处理后存入分析表，原始值仅保留在主业务表中。

---

## 3. 事件模型

### 3.1 事件通用结构

每条埋点事件统一遵循以下结构：

```json
{
  "event_id": "uuid",
  "event_type": "事件类型标识",
  "timestamp": "ISO-8601",
  "operator": {
    "user_name": "张三",
    "user_id": "sso_user_id",
    "source": "sso | superadmin"
  },
  "context": {
    "transcript_id": "uuid",
    "company_id_hash": "sha256(公司ID)",
    "session_id": "uuid"
  },
  "payload": { }
}
```

`context` 中的 `company_id_hash` 为脱敏后的公司标识，用于聚合分析但不泄露具体客户。需要关联原始客户时，通过 `transcript_id` 回查主业务表。

### 3.2 全量事件清单

系统定义以下 14 类事件，按用户操作链路排列：

---

#### E‑01 transcript.uploaded — 转写上传

用户上传转写文件或钉钉自动拉取成功时触发。

```json
{
  "event_type": "transcript.uploaded",
  "payload": {
    "source": "upload | dingtalk_api",
    "file_name": "04-22 客户拜访.txt",
    "file_size_bytes": 12480,
    "segment_count": 42,
    "char_count": 8500,
    "speaker_count": 3,
    "duration_estimate_minutes": 35
  }
}
```

**业务价值**：统计团队拜访频次、平均会议时长、活跃用户。  
**系统价值**：分析文件大小与后续提取延迟的关系。

---

#### E‑02 extraction.started — Agent‑A 开始提取

Orchestrator 发起 Agent‑A 调用时触发。

```json
{
  "event_type": "extraction.started",
  "payload": {
    "model": "qwen-plus",
    "prompt_version": "sha256(prompt_text)前8位",
    "input_char_count": 8500
  }
}
```

---

#### E‑03 extraction.completed — Agent‑A 提取完成

Agent‑A 返回结果后触发。

```json
{
  "event_type": "extraction.completed",
  "payload": {
    "is_customer_visit": true,
    "confidence": 0.85,
    "expectation_count": 3,
    "scenario_count": 2,
    "latency_ms": 8420,
    "model": "qwen-plus",
    "prompt_version": "a1b2c3d4",
    "token_usage": {
      "prompt_tokens": 2100,
      "completion_tokens": 850,
      "total_tokens": 2950
    },
    "expectations_summary": [
      { "index": 0, "summary": "实现质检自动化", "confidence": 0.92 },
      { "index": 1, "summary": "实现生产自动排程", "confidence": 0.88 },
      { "index": 2, "summary": "建立数据看板", "confidence": 0.75 }
    ],
    "scenarios_summary": [
      { "index": 0, "title": "质检缺陷识别", "confidence": 0.90 },
      { "index": 1, "title": "生产计划排程", "confidence": 0.85 }
    ]
  }
}
```

**业务价值**：客户在意什么（预期/场景关键词词频）、单次拜访信息密度。  
**系统价值**：模型延迟、token 消耗、置信度分布，用于 Prompt 调优基准线。

---

#### E‑04 extraction.failed — Agent‑A 提取失败

```json
{
  "event_type": "extraction.failed",
  "payload": {
    "error_type": "json_parse_error | timeout | llm_error | unknown",
    "error_message": "Invalid JSON: unexpected token...",
    "latency_ms": 15000,
    "retry_count": 1
  }
}
```

---

#### E‑05 extraction.rejected — 用户判定非客户拜访

Agent‑A 返回 `is_customer_visit: false`，用户选择"取消"时触发。

```json
{
  "event_type": "extraction.rejected",
  "payload": {
    "agent_confidence": 0.3,
    "user_action": "cancel | force_extract"
  }
}
```

---

#### E‑06 comparison.completed — Agent‑B 比对完成

```json
{
  "event_type": "comparison.completed",
  "payload": {
    "latency_ms": 6200,
    "model": "qwen-plus",
    "prompt_version": "e5f6g7h8",
    "token_usage": { "prompt_tokens": 3200, "completion_tokens": 1100, "total_tokens": 4300 },
    "existing_expectation_count": 5,
    "existing_scenario_count": 3,
    "operations": {
      "new_expectation": 1,
      "update_expectation": 2,
      "new_scenario": 1,
      "update_scenario": 1,
      "total": 5
    },
    "confidence_distribution": {
      "high_90_100": 2,
      "medium_70_90": 2,
      "low_0_70": 1
    }
  }
}
```

**系统价值**：比对准确性基准（后续与用户审核结果对比）。

---

#### E‑07 review.action — 用户审核操作（核心埋点）

用户对每一张操作卡片做出动作时触发。**每张卡片独立一条事件**。

```json
{
  "event_type": "review.action",
  "payload": {
    "operation_id": "uuid",
    "operation_type": "new_expectation | update_expectation | new_scenario | update_scenario",
    "action": "confirm | edit_then_confirm | delete | convert_to_new | convert_to_update",
    "agent_confidence": 0.85,
    "match_id": "_id_001（仅 update 类型）",

    "edit_details": {
      "edited_fields": ["summary", "status"],
      "field_changes": [
        {
          "field": "summary",
          "before": "实现质检自动化",
          "after": "实现AI视觉质检",
          "change_type": "minor_reword | major_rewrite | value_change"
        },
        {
          "field": "status",
          "before": "未启动",
          "after": "进行中",
          "change_type": "value_change"
        }
      ]
    },

    "time_spent_seconds": 45,
    "card_position": 2,
    "total_cards": 5
  }
}
```

**action 枚举说明**：

| action | 含义 |
|---|---|
| `confirm` | 直接确认，不修改 |
| `edit_then_confirm` | 编辑后确认 |
| `delete` | 删除该操作卡片 |
| `convert_to_new` | 将"更新"转为"新增"（Agent‑B 匹配错误） |
| `convert_to_update` | 将"新增"转为"更新"（Agent‑B 遗漏匹配） |

**change_type 枚举说明**：

| change_type | 含义 | 判定规则 |
|---|---|---|
| `minor_reword` | 小幅措辞调整 | 编辑距离 < 原文 30% |
| `major_rewrite` | 大幅重写 | 编辑距离 ≥ 原文 30% |
| `value_change` | 枚举/状态值变更 | radiogroup、datetime 等字段 |

**业务价值**：哪些预期/场景被保留了、被删了（说明 Agent 提取的不是重点）、用户改了什么（说明 Agent 表述不够准确）。  
**系统价值**：这是**准确率计算的核心数据源**。

---

#### E‑08 review.session — 审核会话汇总

用户点击"全部确认并写入"或"保存草稿"时触发，汇总本次审核全貌。

```json
{
  "event_type": "review.session",
  "payload": {
    "total_operations": 5,
    "confirmed": 3,
    "edited_then_confirmed": 1,
    "deleted": 1,
    "converted": 0,
    "final_action": "submit | save_draft",
    "total_review_time_seconds": 180,
    "avg_time_per_card_seconds": 36
  }
}
```

---

#### E‑09 write.completed — 简道云写入完成

```json
{
  "event_type": "write.completed",
  "payload": {
    "operations_submitted": 4,
    "operations_succeeded": 4,
    "operations_failed": 0,
    "total_latency_ms": 3200,
    "details": [
      { "op_id": "uuid", "type": "new_expectation", "status": "success", "latency_ms": 800 },
      { "op_id": "uuid", "type": "update_expectation", "status": "success", "latency_ms": 1200 }
    ]
  }
}
```

---

#### E‑10 write.failed — 简道云写入失败

```json
{
  "event_type": "write.failed",
  "payload": {
    "op_id": "uuid",
    "operation_type": "new_expectation",
    "error_type": "api_error | timeout | validation_error",
    "error_message": "...",
    "retry_count": 3,
    "jiandaoyun_error_code": "1001"
  }
}
```

---

#### E‑11 chat.query — 自然语言查询

```json
{
  "event_type": "chat.query",
  "payload": {
    "intent": "query_expectation | query_scenario | query_company | unknown",
    "query_text_length": 15,
    "result_count": 3,
    "latency_ms": 2800,
    "model": "qwen-plus",
    "token_usage": { "prompt_tokens": 500, "completion_tokens": 300, "total_tokens": 800 }
  }
}
```

---

#### E‑12 chat.modify — 自然语言修改

```json
{
  "event_type": "chat.modify",
  "payload": {
    "intent": "modify_status | modify_field | unknown",
    "target_type": "expectation | scenario",
    "user_confirmed": true,
    "field_modified": "status",
    "latency_ms": 3500,
    "modify_succeeded": true
  }
}
```

---

#### E‑13 config.changed — 系统配置变更

```json
{
  "event_type": "config.changed",
  "payload": {
    "config_section": "llm | jiandaoyun | sso | dingtalk",
    "changed_fields": ["temperature", "agent_a_prompt"],
    "changed_by": "admin"
  }
}
```

---

#### E‑14 system.error — 系统级异常

```json
{
  "event_type": "system.error",
  "payload": {
    "error_source": "agent_a | agent_b | jiandaoyun | dingtalk | orchestrator",
    "error_type": "timeout | api_error | json_parse | auth_error",
    "error_message": "...",
    "stack_trace_hash": "sha256前8位"
  }
}
```

---

## 4. 数据存储

### 4.1 存储方案

V0.1 采用**PostgreSQL 单表 + JSONB**方案，零外部依赖，与主库共用实例但逻辑隔离。后续数据量增长后可平滑迁移到 ClickHouse 或导出到 BI 系统。

```sql
-- 埋点事件表
CREATE TABLE analytics_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type VARCHAR(50) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- 操作人
    operator_name VARCHAR(100),
    operator_id VARCHAR(255),
    operator_source VARCHAR(20),

    -- 上下文关联
    transcript_id UUID,
    company_id_hash VARCHAR(64),
    session_id UUID,

    -- 事件载荷
    payload JSONB NOT NULL DEFAULT '{}',

    -- 便于查询的冗余字段
    operation_type VARCHAR(50),
    action VARCHAR(50),
    latency_ms INTEGER,
    model VARCHAR(50),
    prompt_version VARCHAR(20)
);

-- 索引
CREATE INDEX idx_events_type_time ON analytics_events (event_type, timestamp DESC);
CREATE INDEX idx_events_transcript ON analytics_events (transcript_id);
CREATE INDEX idx_events_operator ON analytics_events (operator_name, timestamp DESC);
CREATE INDEX idx_events_company ON analytics_events (company_id_hash);
CREATE INDEX idx_events_action ON analytics_events (event_type, action) WHERE event_type = 'review.action';
```

### 4.2 写入方式

后端实现一个轻量 `AnalyticsCollector` 类，所有埋点通过异步队列写入，不阻塞主流程。

```python
import asyncio
from datetime import datetime
from uuid import uuid4

class AnalyticsCollector:
    """异步埋点采集器，主流程无感"""

    def __init__(self, db_pool):
        self._db_pool = db_pool
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._running = False

    async def start(self):
        self._running = True
        asyncio.create_task(self._flush_loop())

    async def track(self, event_type: str, operator: dict,
                    context: dict, payload: dict):
        event = {
            "id": str(uuid4()),
            "event_type": event_type,
            "timestamp": datetime.utcnow().isoformat(),
            "operator": operator,
            "context": context,
            "payload": payload
        }
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            pass  # 丢弃而非阻塞主流程

    async def _flush_loop(self):
        while self._running:
            batch = []
            try:
                while len(batch) < 50:
                    event = await asyncio.wait_for(
                        self._queue.get(), timeout=2.0
                    )
                    batch.append(event)
            except asyncio.TimeoutError:
                pass
            if batch:
                await self._batch_insert(batch)

    async def _batch_insert(self, events: list):
        async with self._db_pool.acquire() as conn:
            await conn.executemany(
                """INSERT INTO analytics_events
                   (id, event_type, timestamp, operator_name, operator_id,
                    operator_source, transcript_id, company_id_hash,
                    session_id, payload, operation_type, action,
                    latency_ms, model, prompt_version)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)""",
                [self._flatten(e) for e in events]
            )
```

### 4.3 数据保留策略

| 时间范围 | 策略 |
|---|---|
| 0–90 天 | 全量保留，支持明细查询 |
| 90–365 天 | 保留聚合数据（日级汇总），明细数据归档到冷存储或导出 CSV |
| 365 天以上 | 仅保留月级统计指标 |

---

## 5. 指标体系

### 5.1 业务指标（团队管理视角）

这一组指标回答"客户成功团队的拜访质量怎么样"。

#### M‑B01 拜访活跃度

| 指标 | 计算方式 | 数据源 |
|---|---|---|
| 周拜访次数（团队） | `COUNT(E-01) WHERE timestamp IN 本周` | E‑01 |
| 周拜访次数（个人） | 同上，GROUP BY operator_name | E‑01 |
| 人均周拜访次数 | 团队总次数 / 活跃用户数 | E‑01 |
| 平均会议时长 | `AVG(payload.duration_estimate_minutes)` | E‑01 |

#### M‑B02 拜访信息密度

| 指标 | 计算方式 | 数据源 |
|---|---|---|
| 单次拜访提取预期数 | `AVG(payload.expectation_count)` | E‑03 |
| 单次拜访提取场景数 | `AVG(payload.scenario_count)` | E‑03 |
| 信息密度得分 | `(预期数 + 场景数) / 会议时长` | E‑01, E‑03 |
| 空拜访率 | `COUNT(E-05 WHERE cancel) / COUNT(E-01)` | E‑01, E‑05 |

#### M‑B03 预期/场景内容分析

| 指标 | 计算方式 | 数据源 |
|---|---|---|
| 预期关键词 Top‑20 | 对 `expectations_summary[].summary` 做分词统计 | E‑03 |
| 场景关键词 Top‑20 | 对 `scenarios_summary[].title` 做分词统计 | E‑03 |
| 第一价值预期占比 | `COUNT(is_first_value=true) / COUNT(全部预期)` | E‑03 |
| 高频客户痛点 | 对 `pain_point` 字段做聚类 | E‑07 中 confirm 的场景 |

#### M‑B04 拜访质量评分（综合）

| 指标 | 计算方式 | 说明 |
|---|---|---|
| 采纳率 | `(confirmed + edited_confirmed) / total` | 来自 E‑08 |
| 有效拜访率 | `1 - 空拜访率` | 来自 M‑B02 |
| 质量得分 | `采纳率 × 0.5 + 信息密度得分 × 0.3 + 有效拜访率 × 0.2` | 综合评分 |

---

### 5.2 系统指标（调优视角）

这一组指标回答"Agent 提取准确不准确、Prompt 要不要调"。

#### M‑S01 Agent‑A 提取质量

| 指标 | 计算方式 | 数据源 | 目标 |
|---|---|---|---|
| **直接采纳率** | `COUNT(action=confirm) / COUNT(E-07)` | E‑07 | ≥ 50% |
| **编辑后采纳率** | `COUNT(action=edit_then_confirm) / COUNT(E-07)` | E‑07 | — |
| **总采纳率** | `(confirm + edit_then_confirm) / total` | E‑07 | **≥ 70%** |
| **删除率** | `COUNT(action=delete) / COUNT(E-07)` | E‑07 | ≤ 20% |
| **小修率** | `COUNT(change_type=minor_reword) / COUNT(edit_then_confirm)` | E‑07 | ≥ 60% |
| **大改率** | `COUNT(change_type=major_rewrite) / COUNT(edit_then_confirm)` | E‑07 | ≤ 30% |
| 非客户拜访误识别率 | `COUNT(E-05 WHERE force_extract AND 后续采纳率>50%) / COUNT(E-05)` | E‑05, E‑07 | — |

**关键解读**：总采纳率是最核心的系统质量指标。当总采纳率 < 70% 时触发 Prompt 调优流程。大改率反映 Agent 表述质量，小修率反映 Agent 理解准确但措辞需调整的比例。

#### M‑S02 Agent‑B 比对质量

| 指标 | 计算方式 | 数据源 | 目标 |
|---|---|---|---|
| **匹配正确率** | `1 - (convert_to_new + convert_to_update) / COUNT(E-07)` | E‑07 | ≥ 80% |
| 误判为更新率 | `COUNT(convert_to_new) / COUNT(type=update_*)` | E‑07 | ≤ 15% |
| 遗漏匹配率 | `COUNT(convert_to_update) / COUNT(type=new_*)` | E‑07 | ≤ 15% |
| 置信度校准 | 对比 `agent_confidence` 与实际 `action` 的相关性 | E‑07 | 正相关 |

#### M‑S03 性能指标

| 指标 | 计算方式 | 数据源 | 目标 |
|---|---|---|---|
| Agent‑A P50 延迟 | `PERCENTILE(latency_ms, 0.5)` | E‑03 | ≤ 10s |
| Agent‑A P95 延迟 | `PERCENTILE(latency_ms, 0.95)` | E‑03 | ≤ 15s |
| Agent‑B P50 延迟 | 同上 | E‑06 | ≤ 8s |
| Agent‑B P95 延迟 | 同上 | E‑06 | ≤ 12s |
| 端到端 P50 | `E-09.timestamp - E-01.timestamp` | E‑01, E‑09 | ≤ 25s |
| 写入成功率 | `succeeded / submitted` | E‑09 | 100% |
| Agent 失败率 | `COUNT(E-04) / COUNT(E-02)` | E‑02, E‑04 | ≤ 5% |
| 日均 Token 消耗 | `SUM(total_tokens)` | E‑03, E‑06, E‑11, E‑12 | 监控即可 |
| 日均 LLM 成本（估） | `总 token × 单价` | 同上 | 监控即可 |

#### M‑S04 Prompt 版本对比

| 指标 | 计算方式 | 数据源 |
|---|---|---|
| 各 prompt_version 的采纳率 | `GROUP BY prompt_version` 计算 M‑S01 | E‑03, E‑07 |
| 各 prompt_version 的延迟 | 同上 | E‑03, E‑06 |
| 各 prompt_version 的 token 消耗 | 同上 | E‑03, E‑06 |

通过对比不同 `prompt_version`（超管每次修改 Prompt 产生新版本 hash），可量化每次 Prompt 调整的效果。

---

### 5.3 指标关系图

```
拜访活跃度 (M-B01)
  │
  ├── 拜访信息密度 (M-B02)
  │     │
  │     ├── 预期/场景关键词 (M-B03)  ← 业务洞察
  │     │
  │     └── 空拜访率
  │
  └── 拜访质量评分 (M-B04) ←──── 采纳率 (M-S01) ←── review.action (E-07)
                                    │
                                    ├── Agent-A 提取质量 (M-S01)
                                    │     ├── 直接采纳率
                                    │     ├── 编辑后采纳率
                                    │     ├── 删除率
                                    │     └── 大改率 / 小修率
                                    │
                                    ├── Agent-B 比对质量 (M-S02)
                                    │     ├── 匹配正确率
                                    │     └── 误判率 / 遗漏率
                                    │
                                    └── Prompt 版本效果 (M-S04)
                                          └── A/B 对比
```

---

## 6. 埋点注入点（代码层面）

### 6.1 注入位置清单

| 事件 | 注入位置 | 触发条件 |
|---|---|---|
| E‑01 | `routers/transcript.py` upload / dingtalk-fetch 成功返回后 | 上传成功或拉取成功 |
| E‑02 | `agents/orchestrator.py` 调用 Agent‑A 前 | 发起 LLM 请求前 |
| E‑03 | `agents/extraction_agent.py` LLM 返回并解析成功后 | Agent‑A 完成 |
| E‑04 | `agents/extraction_agent.py` 异常捕获 | Agent‑A 失败 |
| E‑05 | `routers/transcript.py` 用户对非拜访判定做出选择时 | 前端回调 |
| E‑06 | `agents/comparison_agent.py` LLM 返回并解析成功后 | Agent‑B 完成 |
| E‑07 | `routers/operations.py` 用户对单张卡片执行动作时 | **前端调后端** |
| E‑08 | `routers/operations.py` 用户点击"全部确认并写入"或"保存草稿" | 审核会话结束 |
| E‑09 | `services/jiandaoyun.py` 全部写入操作完成后 | 写入完成 |
| E‑10 | `services/jiandaoyun.py` 单条写入失败时 | 写入失败 |
| E‑11 | `services/chat_service.py` 查询完成后 | 对话查询 |
| E‑12 | `services/chat_service.py` 修改执行后 | 对话修改 |
| E‑13 | `routers/admin.py` 配置保存成功后 | 配置变更 |
| E‑14 | 全局异常处理中间件 | 未捕获异常 |

### 6.2 前端埋点补充

E‑07 需要前端配合采集 `time_spent_seconds`（用户在该卡片上的停留时间）。前端在卡片获得焦点时开始计时，用户执行操作时将耗时随请求发送到后端。

```typescript
// 前端审核页 - 卡片停留时间追踪
const cardTimers = new Map<string, number>();

function onCardFocus(opId: string) {
  cardTimers.set(opId, Date.now());
}

function onCardAction(opId: string, action: string) {
  const startTime = cardTimers.get(opId) || Date.now();
  const timeSpent = Math.round((Date.now() - startTime) / 1000);

  api.post('/api/v1/operations/review-action', {
    operation_id: opId,
    action: action,
    time_spent_seconds: timeSpent,
    // ... 其他字段
  });
}
```

---

## 7. 查询与分析 API

为管理层和调优提供查询接口。V0.1 不做独立 BI 面板，通过 API 返回 JSON 供前端或外部工具消费。

### 7.1 API 端点

| 端点 | 方法 | 说明 | 认证 |
|---|---|---|---|
| `/api/v1/analytics/business/overview` | GET | 业务指标总览 | 超管 JWT |
| `/api/v1/analytics/business/operator/:name` | GET | 个人拜访分析 | 超管 JWT |
| `/api/v1/analytics/business/keywords` | GET | 预期/场景关键词统计 | 超管 JWT |
| `/api/v1/analytics/system/accuracy` | GET | Agent 准确率指标 | 超管 JWT |
| `/api/v1/analytics/system/performance` | GET | 性能与延迟指标 | 超管 JWT |
| `/api/v1/analytics/system/prompt-compare` | GET | Prompt 版本对比 | 超管 JWT |
| `/api/v1/analytics/system/cost` | GET | Token 消耗与成本 | 超管 JWT |
| `/api/v1/analytics/export` | GET | 导出原始事件 CSV | 超管 JWT |

### 7.2 业务总览响应示例

`GET /api/v1/analytics/business/overview?period=7d`

```json
{
  "period": "2026-04-17 ~ 2026-04-23",
  "visit_count": 28,
  "active_operators": 5,
  "avg_visits_per_operator": 5.6,
  "avg_meeting_duration_min": 38,
  "avg_expectations_per_visit": 2.3,
  "avg_scenarios_per_visit": 1.8,
  "empty_visit_rate": 0.07,
  "overall_adoption_rate": 0.74,
  "quality_score": 0.72,
  "top_operators": [
    { "name": "张三", "visits": 8, "adoption_rate": 0.82, "quality_score": 0.78 },
    { "name": "李四", "visits": 6, "adoption_rate": 0.70, "quality_score": 0.68 }
  ]
}
```

### 7.3 系统准确率响应示例

`GET /api/v1/analytics/system/accuracy?period=7d`

```json
{
  "period": "2026-04-17 ~ 2026-04-23",
  "agent_a": {
    "total_operations_generated": 140,
    "direct_confirm_rate": 0.52,
    "edit_then_confirm_rate": 0.22,
    "total_adoption_rate": 0.74,
    "delete_rate": 0.18,
    "minor_reword_rate": 0.65,
    "major_rewrite_rate": 0.25,
    "avg_confidence": 0.83,
    "by_type": {
      "expectation": { "adoption_rate": 0.78, "delete_rate": 0.15 },
      "scenario": { "adoption_rate": 0.70, "delete_rate": 0.22 }
    }
  },
  "agent_b": {
    "match_accuracy": 0.85,
    "false_update_rate": 0.10,
    "missed_match_rate": 0.05
  },
  "prompt_version_current": {
    "agent_a": "a1b2c3d4",
    "agent_b": "e5f6g7h8"
  }
}
```

### 7.4 Prompt 版本对比响应示例

`GET /api/v1/analytics/system/prompt-compare?agent=agent_a&period=30d`

```json
{
  "versions": [
    {
      "prompt_version": "a1b2c3d4",
      "active_period": "04-01 ~ 04-15",
      "sample_count": 45,
      "adoption_rate": 0.68,
      "delete_rate": 0.22,
      "avg_latency_ms": 9500,
      "avg_tokens": 2800
    },
    {
      "prompt_version": "f9e8d7c6",
      "active_period": "04-16 ~ 04-23",
      "sample_count": 32,
      "adoption_rate": 0.74,
      "delete_rate": 0.18,
      "avg_latency_ms": 8800,
      "avg_tokens": 2650
    }
  ],
  "improvement": {
    "adoption_rate_delta": "+0.06",
    "delete_rate_delta": "-0.04",
    "latency_delta_ms": "-700",
    "conclusion": "新版 Prompt 在采纳率和延迟上均有提升"
  }
}
```

---

## 8. 对主 PRD 的影响

### 8.1 需修改的用户故事

| 主 PRD US | 新增内容 |
|---|---|
| US‑203（审核页） | 每张卡片增加"转为新增"/"转为更新"切换按钮；前端追踪卡片停留时间；每次操作调用后端埋点接口 |
| US‑208（LLM 配置） | Prompt 保存时自动计算 `sha256(prompt_text)` 前 8 位作为 `prompt_version` |

### 8.2 新增用户故事

| 编号 | 标题 | 角色 | 优先级 |
|---|---|---|---|
| US‑301 | 埋点采集基础设施 | system | P0 |
| US‑302 | 业务分析 API | superadmin | P1 |
| US‑303 | 系统调优 API | superadmin | P1 |
| US‑304 | 数据导出 | superadmin | P2 |

### 8.3 新增数据库表

`analytics_events` 表（见 §4.1），添加到 Docker Compose 的 init SQL 中。

---

## 9. 排期

| 任务 | 工作量 | 依赖 | 建议排入 |
|---|---|---|---|
| `analytics_events` 表 + `AnalyticsCollector` 类 | 后端 0.5 天 | 无 | **V0.1 D1**（随 DB Schema 一起建） |
| 各事件埋点注入（E‑01 ~ E‑14） | 后端 1 天 | 对应功能开发完成 | **V0.1 各对应开发日尾部** |
| 审核页前端改造（停留时间+转换按钮） | 前端 0.5 天 | US‑203 | **V0.1 D6** |
| Prompt 版本 hash 生成 | 后端 0.5h | US‑208 | **V0.1 D3** |
| 分析 API（US‑302 / US‑303） | 后端 1.5 天 | 埋点数据积累 | **V0.1 D10 或 V0.2 首周** |
| 数据导出（US‑304） | 后端 0.5 天 | US‑302 | V0.2 |

**总新增工作量**：后端约 3.5 天，前端 0.5 天。

建议策略：埋点基础设施和事件注入随 V0.1 各功能同步交付（增量很小，每个注入点约 3–5 行代码）；分析 API 在内测启动后（D10）或 V0.2 首周集中开发，此时已有真实数据可验证。

---

## 10. 调优工作流

基于埋点数据建立的闭环调优流程：

```
 ┌──────────────────────────────────────────────────────────┐
 │                   每周调优循环                             │
 │                                                          │
 │  ① 查看 /analytics/system/accuracy                       │
 │     → 总采纳率 < 70%？                                    │
 │        │                                                  │
 │     ├─ 是：进入 ②                                         │
 │     └─ 否：记录本周指标，跳过                              │
 │                                                          │
 │  ② 定位问题：                                             │
 │     → 删除率高？→ Agent 提取了不相关内容 → 调 Agent-A Prompt│
 │     → 大改率高？→ Agent 表述不准确 → 调 Agent-A Prompt     │
 │     → 误判率高？→ 匹配逻辑有误 → 调 Agent-B Prompt        │
 │     → 遗漏率高？→ 匹配遗漏 → 降低 Agent-B 匹配阈值       │
 │                                                          │
 │  ③ 修改 Prompt（超管 /admin/llm 页面）                    │
 │     → 自动生成新 prompt_version                           │
 │                                                          │
 │  ④ 运行 1-2 天积累样本                                    │
 │                                                          │
 │  ⑤ 查看 /analytics/system/prompt-compare                  │
 │     → 新版采纳率提升？→ 保留                              │
 │     → 新版下降？→ 恢复默认或继续调整                       │
 │                                                          │
 │  ⑥ 记录本轮调优结论（config_change_logs 自动留痕）         │
 │                                                          │
 └──────────────────────────────────────────────────────────┘
```

---

## 11. 风险

| 风险 | 概率 | 影响 | 应对 |
|---|---|---|---|
| 埋点写入影响主流程性能 | 低 | 主流程变慢 | 异步队列 + 队满丢弃策略 |
| 埋点数据量膨胀 | 中 | 磁盘/查询慢 | 90 天归档策略 + 索引优化 |
| 前端停留时间不准（切Tab等） | 中 | M‑S01 数据噪声 | 增加 `visibilitychange` 监听暂停计时 |
| 内测样本不足导致指标不稳 | 高 | 误判 Prompt 效果 | 设最小样本量阈值（≥ 20 条）才计算指标 |
| 脱敏不彻底 | 低 | 数据泄露 | 埋点表仅存 hash，原始值在主表 |

---

## 12. 变更记录

| 日期 | 编号 | 内容 |
|---|---|---|
| 2026-04-23 | PRD‑Pro‑001 | 初始版本 |

---
