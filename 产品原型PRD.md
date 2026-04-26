---

# 「智档」产品需求文档 PRD V0.1

**文档版本**：V0.1.5  
**创建日期**：2026-04-23  
**最后更新**：2026-04-23  
**产品负责人**：Karl  
**项目总控**：Alois  
**架构/开发**：Gust  
**知识库运营**：Ria

---

## 1. 产品概述

### 1.1 产品定位

面向客户成功（Customer Success）团队的轻量化自动化工具。将钉钉会议转写文本经**双 Agent 协作架构（A2A）**提取客户预期与业务场景，经用户审核后写入简道云客户档案，并支持自然语言查询与修改。

### 1.2 核心价值

将"听完客户会议 → 手动整理预期/场景 → 登录简道云 → 逐条填写子表单"的流程从 **30–60 分钟压缩至 3–5 分钟**，同时通过结构化日志沉淀数据资产。

### 1.3 目标用户

| 角色 | 说明 | 身份来源 |
|---|---|---|
| **一线客户成功（普通用户）** | 上传转写、审核提取结果、写入简道云、自然语言查询/修改 | 简道云 SSO 传入 |
| **系统维护者（superadmin）** | LLM 配置、简道云连接配置、字段映射、SSO 密钥管理 | 本地初始化创建 |

### 1.4 干系人

| 人员 | 职责 |
|---|---|
| Alois | 项目总控、技术评审 |
| Karl | 产品经理、需求确认、验收 |
| Gust | 架构设计、全栈开发 |
| Ria | 知识库运营、数据标注 |

---

## 2. 版本路线图

| 版本 | 状态 | 核心范围 |
|---|---|---|
| **V0.1** | 开发中 | 双通道转写输入、双 Agent 提取（识别+比对）、用户审核、简道云写入、自然语言查询/修改、SSO、超管配置（LLM+简道云+字段映射）、系统初始化 |
| **V0.2** | 规划中 | 多租户/部门隔离、待办事项提取/写入、操作日志审计面板、钉钉 AI 纪要结构化 API |
| **V0.3** | 远期 | 轻量 NLU 意图识别、知识库扩充（KnowHow/KMS）、收音硬件方案 |

---

## 3. 用户身份与权限模型

### 3.1 设计原则

V0.1 **不建多租户/用户数据库**。普通用户身份完全由简道云 SSO 跳转时携带的用户信息决定，系统不存储用户账号；仅 superadmin 在本地数据库中存储一条记录，用于管理系统配置。

### 3.2 身份来源

| 角色 | 认证方式 | 存储位置 |
|---|---|---|
| **superadmin** | 本地用户名+密码登录 | PostgreSQL `superadmin` 表 |
| **普通用户** | 简道云 SSO 跳转携带签名 Token（含 user_name、user_id） | 不存储，JWT Session 维持 |

### 3.3 权限矩阵

| 功能 | superadmin | 普通用户（SSO） |
|---|---|---|
| 系统初始化 | ✓ | ✗ |
| LLM 配置 | ✓ | ✗ |
| 简道云连接配置 | ✓ | ✗ |
| 字段映射配置 | ✓ | ✗ |
| SSO 密钥管理 | ✓ | ✗ |
| 上传转写 | ✓ | ✓ |
| 审核/写入 | ✓ | ✓ |
| 自然语言查询/修改 | ✓ | ✓ |

---

## 4. 功能清单（V0.1）

| 编号 | 功能 | 优先级 |
|---|---|---|
| US‑201A | 手动上传转写文件 | P0 |
| US‑201B | 钉钉 API 自动获取转写 | P0 |
| US‑202 | 双 Agent 提取：Agent‑A 识别 + Agent‑B 比对 | P0 |
| US‑203 | 用户审核确认 | P0 |
| US‑204 | 写入简道云（主表+子表单） | P0 |
| US‑205 | 自然语言查询档案 | P0 |
| US‑206 | 自然语言修改档案（含确认） | P0 |
| US‑207 | 简道云表单映射配置（超管） | P0 |
| US‑208 | LLM 配置管理（超管） | P0 |
| US‑209 | 系统初始化页面 | P0 |
| US‑210 | 简道云 → 智档 SSO 跳转 | P0 |

---

## 5. 双 Agent 架构设计（A2A 模式）

### 5.1 架构总览

系统采用 **Agent-to-Agent（A2A）** 流水线协作模式。Agent‑A 负责从原始转写中识别结构化信息，Agent‑B 负责将识别结果与简道云已有数据比对，判断"新增"还是"更新"，输出可审核的操作指令。

```
┌────────────────────────────────────────────────────────────────┐
│                     智档系统（Orchestrator）                     │
│                                                                │
│  ┌──────────┐    ┌────────────┐    ┌────────────┐   ┌───────┐ │
│  │ 转写输入  │───▶│  Agent‑A   │───▶│  Agent‑B   │──▶│ 审核页 │ │
│  │(上传/API) │    │  识别Agent  │    │  比对Agent  │   │       │ │
│  └──────────┘    └────────────┘    └────────────┘   └──┬────┘ │
│                                                        │      │
│                                           ┌────────────▼────┐ │
│                                           │  简道云 API 写入 │ │
│                                           └─────────────────┘ │
│                                                                │
│  ┌────────────────────────────────────┐                        │
│  │ 自然语言对话（查询/修改）→ 简道云 API │                        │
│  └────────────────────────────────────┘                        │
└────────────────────────────────────────────────────────────────┘
```

### 5.2 Orchestrator 调度流程

```
用户触发（上传文件 / 钉钉拉取）
        │
        ▼
  ┌───────────────┐
  │  解析转写文件  │ ← 正则分段，生成 raw_text + segments
  └──────┬────────┘
         │
         ▼
  ┌───────────────┐       is_customer_visit = false
  │   Agent‑A     │ ───────────────────────────────▶ 提示用户确认
  │  （识别提取）  │                                    │
  └──────┬────────┘                            ┌──────┴───────┐
         │ true                                │"仍然提取" "取消"│
         ▼                                     └──────┬───────┘
  ┌───────────────┐                                   │
  │  查询简道云    │ ◀─────────────────────────────────┘
  │  已有客户档案  │
  └──────┬────────┘
         │ 未找到 → 提示手动选择公司
         │ 找到   → 拉取主表 + 子表单全量数据
         ▼
  ┌───────────────┐
  │   Agent‑B     │
  │  （比对生成）  │
  └──────┬────────┘
         │
         ▼
  ┌───────────────┐
  │   审核页面     │ ← 展示操作卡片（新增/更新 × 预期/场景）
  │  用户逐条确认  │
  └──────┬────────┘
         │ 确认
         ▼
  ┌───────────────┐
  │  写入简道云    │ ← 调用简道云 API
  └───────────────┘
```

---

### 5.3 Agent‑A：识别 Agent（Extraction Agent）

#### 5.3.1 职责

从客户拜访转写文本中提取结构化的客户预期与业务场景。

#### 5.3.2 Agent Card

```json
{
  "name": "extraction-agent",
  "description": "从客户拜访会议转写中识别并提取客户预期、业务场景的结构化信息",
  "version": "0.1.0",
  "capabilities": { "streaming": false, "pushNotifications": false },
  "skills": [{
    "id": "extract-expectations-scenarios",
    "name": "提取客户预期与场景",
    "inputModes": ["text/plain"],
    "outputModes": ["application/json"]
  }]
}
```

#### 5.3.3 接口定义

**端点**：`POST /api/v1/agent/extraction/task`

**请求体**：

```json
{
  "task_id": "uuid",
  "transcript": {
    "source": "upload | dingtalk_api",
    "source_id": "文件名或 conferenceId",
    "title": "04-22 客户拜访：某某科技",
    "raw_text": "完整转写文本",
    "segments": [
      { "speaker": "发言人 1", "timestamp": "00:00:00", "text": "段落内容" }
    ]
  },
  "context": {
    "industry": "manufacturing",
    "department": "production",
    "company_name_hint": "某某科技有限公司"
  }
}
```

**响应体**：

```json
{
  "task_id": "uuid",
  "status": "completed | input_required | failed",
  "result": {
    "is_customer_visit": true,
    "confidence": 0.85,
    "company_name_guess": "某某科技有限公司",
    "expectations": [
      {
        "summary": "预期简述（20字内）",
        "is_first_value": true,
        "description": "预期详细描述",
        "estimated_start_time": "YYYY-MM 或 null",
        "status": "未启动|进行中|已完成|搁置",
        "progress_note": "当前进展说明",
        "source_quote": "原文引用",
        "speaker": "发言人 X",
        "timestamp": "HH:MM:SS"
      }
    ],
    "scenarios": [
      {
        "title": "场景标题（15字内）",
        "is_first_value": true,
        "pain_point": "业务诉求/痛点分析",
        "core_metric_solution": "核心指标与解决方案",
        "value_quantification": "价值量化",
        "summary": "总结沉淀",
        "source_quote": "原文引用",
        "speaker": "发言人 X",
        "timestamp": "HH:MM:SS"
      }
    ]
  },
  "message": "仅 input_required 时返回提示",
  "error": null
}
```

#### 5.3.4 LLM Prompt 模板（超管可编辑）

```
你是一个专业的客户成功分析师。请从以下客户拜访会议转写中提取信息。

## 任务
1. 判断该转写是否包含客户拜访内容（有产品讨论、客户诉求、业务场景等）
2. 若是客户拜访，提取以下两类信息：
   - **客户预期**：客户明确或隐含表达的业务期望、目标、需求
   - **业务场景**：客户当前的业务痛点、使用场景、流程描述

## 提取规则
- 忽略口语填充词（呃、嗯、好的好的、对对对等）
- 每条预期/场景必须有原文依据（引用原文片段）
- 标注说话人编号和对应时间戳
- 预期需评估"是否为第一价值实现预期"（客户购买产品最核心的期望）
- 场景需分析"业务诉求/痛点"

## 输出格式（严格 JSON，不要输出 markdown 代码块）
{
  "is_customer_visit": true/false,
  "confidence": 0.0-1.0,
  "company_name_guess": "从对话中推测的公司名",
  "expectations": [ ... ],
  "scenarios": [ ... ]
}

## 转写文本
{transcript_text}
```

#### 5.3.5 调用时机

用户上传转写文件（US‑201A）解析完成，或钉钉自动拉取成功（US‑201B）后，Orchestrator 将原始文本发送给 Agent‑A。

---

### 5.4 Agent‑B：比对 Agent（Comparison Agent）

#### 5.4.1 职责

接收 Agent‑A 的提取结果与简道云已有客户档案进行比对，输出最终写入操作指令（新增 / 更新 / 追加进度）。

#### 5.4.2 Agent Card

```json
{
  "name": "comparison-agent",
  "description": "将提取的预期/场景与简道云已有数据比对，生成写入操作指令",
  "version": "0.1.0",
  "capabilities": { "streaming": false, "pushNotifications": false },
  "skills": [{
    "id": "compare-and-generate-ops",
    "name": "比对并生成写入指令",
    "inputModes": ["application/json"],
    "outputModes": ["application/json"]
  }]
}
```

#### 5.4.3 接口定义

**端点**：`POST /api/v1/agent/comparison/task`

**请求体**：

```json
{
  "task_id": "uuid",
  "extraction_result": {
    "company_name_guess": "某某科技有限公司",
    "expectations": [ ... ],
    "scenarios": [ ... ]
  },
  "existing_record": {
    "company_id": "eb6dc9bc-a55c-11ea-ba0b-7cd30ab79bc4",
    "company_name": "某某科技有限公司",
    "existing_expectations": [
      {
        "data_id": "_id_001",
        "summary": "实现生产自动排程",
        "status": "进行中",
        "progress_history": ["2026-03: 完成需求调研"]
      }
    ],
    "existing_scenarios": [
      {
        "data_id": "_id_002",
        "title": "生产计划排程",
        "pain_point": "手动排程耗时，交期不准"
      }
    ]
  }
}
```

**响应体**：

```json
{
  "task_id": "uuid",
  "status": "completed | failed",
  "result": {
    "company_id": "eb6dc9bc-a55c-11ea-ba0b-7cd30ab79bc4",
    "operations": [
      {
        "type": "new_expectation",
        "data": {
          "summary": "实现质检自动化",
          "is_first_value": true,
          "description": "客户希望通过AI视觉识别实现产线质检...",
          "estimated_start_time": "2026-06",
          "status": "未启动",
          "progress_note": "初步沟通需求"
        },
        "source_quote": "我们希望能用AI来做质检...",
        "confidence": 0.92
      },
      {
        "type": "update_expectation",
        "match_id": "_id_001",
        "match_summary": "实现生产自动排程",
        "updates": {
          "status": "进行中",
          "append_progress": "2026-04: 客户反馈排程模块已试用，准确率待提升"
        },
        "reason": "新转写中提到排程模块试用进展，与已有预期语义匹配",
        "source_quote": "排程这块我们试了一下...",
        "confidence": 0.85
      },
      {
        "type": "new_scenario",
        "data": {
          "title": "质检缺陷识别",
          "is_first_value": true,
          "pain_point": "人工质检漏检率高、效率低",
          "core_metric_solution": "AI视觉识别，目标漏检率<1%",
          "value_quantification": "年节省质检人力成本约30万",
          "summary": ""
        },
        "source_quote": "目前质检全靠人工看...",
        "confidence": 0.88
      },
      {
        "type": "update_scenario",
        "match_id": "_id_002",
        "match_title": "生产计划排程",
        "updates": {
          "pain_point": "追加：插单频繁导致排程频繁调整"
        },
        "reason": "客户补充了排程场景的新痛点",
        "source_quote": "插单太多了...",
        "confidence": 0.80
      }
    ]
  },
  "error": null
}
```

#### 5.4.4 LLM Prompt 模板（超管可编辑）

```
你是一个客户档案管理专家。请将新提取的客户预期/场景与已有档案数据进行比对。

## 任务
对每一条新提取的预期和场景：
1. 与已有数据逐条进行语义相似度比对
2. 判断是"新增"还是"更新"
3. 若为"更新"，指定匹配的已有记录 data_id 和需要更新的字段

## 比对规则
- 预期比对维度：summary 语义相似度、description 关键词重叠
- 场景比对维度：title 语义相似度、pain_point 关键词重叠
- 语义相近且描述同一业务目标/场景即视为匹配
- 已有预期状态为"已完成"或"搁置"时，新信息仍视为"更新"（可能重新激活）
- 已有预期的更新默认生成"追加进度"操作（非覆盖）

## 输出格式（严格 JSON，不要输出 markdown 代码块）
{
  "company_id": "...",
  "operations": [
    {
      "type": "new_expectation | update_expectation | new_scenario | update_scenario",
      "data": { ... },
      "match_id": "仅 update 类型",
      "match_summary": "仅 update 类型",
      "updates": { ... },
      "reason": "比对理由",
      "source_quote": "原文引用",
      "confidence": 0.85
    }
  ]
}

## 新提取数据
{extraction_json}

## 已有档案数据
{existing_json}
```

#### 5.4.5 调用时机

Agent‑A 返回 `status: completed` 后，Orchestrator 依次：

1. 从 Agent‑A 结果中获取 `company_name_guess`
2. 调用简道云 API 按公司 ID（或公司名模糊搜索）拉取已有客户档案（含子表单数据）
3. 将 Agent‑A 结果 + 已有档案打包发送给 Agent‑B
4. Agent‑B 返回操作指令后渲染审核页

---

### 5.5 Agent 间数据流汇总

```
                    ┌──────────────┐
                    │   转写文本    │
                    └──────┬───────┘
                           │
               ┌───────────▼───────────┐
               │       Agent‑A          │
               │  输入: raw_text        │
               │       + context        │
               │  输出: expectations[]  │
               │       + scenarios[]    │
               └───────────┬───────────┘
                           │
              ┌────────────▼────────────┐
              │  Orchestrator 查询简道云  │
              │  输入: company_name_guess│
              │  输出: existing_record   │
              └────────────┬────────────┘
                           │
               ┌───────────▼───────────┐
               │       Agent‑B          │
               │  输入: extraction_result│
               │       + existing_record│
               │  输出: operations[]    │
               └───────────┬───────────┘
                           │
                    ┌──────▼───────┐
                    │   审核页面    │
                    └──────────────┘
```

---

## 6. 用户故事详述

### US‑201A：手动上传转写文件

**角色**：普通用户  
**故事**：作为一线客户成功，我希望上传钉钉 AI 听记导出的转写文件，系统自动解析后进入提取流程。

**验收标准**：
- 支持 .txt / .md / .docx，单文件 ≤ 10 MB，支持拖拽
- 上传后展示可折叠转写预览
- 自动解析发言人与时间戳（正则：`^发言人\s*(\d+)\s+(\d{2}:\d{2}:\d{2})$`）
- 格式不匹配时降级为整段 raw_text
- 上传成功自动触发 Agent‑A

**API**：`POST /api/v1/transcript/upload`（multipart/form-data）

| 字段 | 类型 | 说明 |
|---|---|---|
| file | File | 转写文件 |
| company_name_hint | string | 可选，公司名提示 |

**响应**：

```json
{
  "transcript_id": "uuid",
  "title": "解析出的标题",
  "segment_count": 42,
  "status": "parsed",
  "preview": "前500字..."
}
```

**工作量**：前端 0.5 天，后端 0.5 天

---

### US‑201B：钉钉 API 自动获取转写

**角色**：普通用户  
**故事**：作为一线客户成功，我希望系统能自动从钉钉拉取会议转写。

**实现**：
- 订阅钉钉"闪记状态变更开放事件"
- 收到事件后调用"查询会议录制中的文本信息"API
- 成功后在转写列表生成记录；失败时提示手动上传

**前置**：钉钉开发者后台已有企业内部应用（✅ 已确认）

**API**：
- 钉钉回调：`POST /api/v1/webhook/dingtalk`
- 手动触发：`POST /api/v1/transcript/dingtalk-fetch`（输入 `conference_id`）

**工作量**：前端 0.5 天，后端 2 天

---

### US‑202：双 Agent 提取

**角色**：system  
**故事**：系统在收到解析完成的转写后，依次调用 Agent‑A 和 Agent‑B 生成可审核的操作指令列表。

**流程**：
1. Agent‑A 提取 → 返回结构化预期/场景
2. 前置校验：`is_customer_visit = false` 时弹窗提示
3. 简道云查询：按 `company_name_guess` 或用户手动选择公司 ID 拉取已有档案
4. Agent‑B 比对 → 返回操作指令
5. 渲染审核页

**验收标准**：
- Agent‑A 延迟 ≤ 15 秒，Agent‑B 延迟 ≤ 10 秒
- 端到端（上传 → 审核页）≤ 30 秒
- 提取准确率 ≥ 70%（内测 5 人评估）
- 每条操作附带原文引用和置信度

**工作量**：后端 2 天

---

### US‑203：用户审核确认

**角色**：普通用户  
**故事**：作为一线客户成功，我需要在写入简道云前逐条审核 Agent 生成的操作指令，可修改、删除或确认。

**审核页设计**（详见 §8.4）：

四个区域布局：左侧转写原文（可折叠+搜索+高亮跳转）、顶部客户信息、右侧操作卡片列表、底部操作栏。

每张卡片包含：类型标签（🟢新增 / 🔵更新）、置信度百分比（< 70% 标黄）、可内联编辑的字段区、灰色原文引用块、匹配信息（仅 update 类型）、三个按钮（✓ 确认 / ✎ 编辑 / ✕ 删除）。

操作栏：「全部确认并写入」仅当所有卡片逐条处理后激活、「保存草稿」按钮、统计信息。

**验收标准**：
- 必须逐条确认或删除，不允许批量全选
- 编辑后自动标记为"已修改"
- 草稿可保存、退出后继续
- 无一条操作未经用户确认即写入

**工作量**：前端 2 天，后端 0.5 天

---

### US‑204：写入简道云

**角色**：system（用户确认触发）  
**故事**：系统在用户确认全部操作后按顺序调用简道云 API 完成写入。

**写入逻辑**：
1. 按 `new_expectation → update_expectation → new_scenario → update_scenario` 顺序
2. 新增预期写入后获取 `data_id`，供场景"关联预期"字段使用
3. 更新预期的 `append_progress`：拉取已有子表单数据 → 追加新行 → **全量回写**（防丢失）
4. 每条写入记录日志

**简道云 API 映射**：

| 操作类型 | 简道云 API | 说明 |
|---|---|---|
| `new_expectation` | `POST .../data_create` | 预期子表单新增 |
| `update_expectation` | `POST .../data_update` | 追加进度 + 更新状态 |
| `new_scenario` | `POST .../data_create` | 场景子表单新增 |
| `update_scenario` | `POST .../data_update` | 更新痛点、方案等 |

**API**：`POST /api/v1/operations/execute`

**请求体**：

```json
{
  "transcript_id": "uuid",
  "company_id": "eb6dc9bc-a55c-11ea-ba0b-7cd30ab79bc4",
  "operations": [
    { "op_id": "uuid", "type": "new_expectation", "data": { ... } },
    { "op_id": "uuid", "type": "update_expectation", "match_id": "...", "updates": { ... } }
  ]
}
```

**响应体**：

```json
{
  "success": true,
  "results": [
    { "op_id": "uuid", "status": "success", "jiandaoyun_data_id": "_id_new" }
  ],
  "failed": []
}
```

**验收标准**：写入成功率 100%（重试 3 次）、子表单数据不丢失、失败时回滚并提示、日志完整

**工作量**：后端 1.5 天

---

### US‑205：自然语言查询档案

**角色**：普通用户  
**故事**：作为一线客户成功，我希望通过自然语言快速查询客户档案。

**示例**："某某科技的预期有哪些"、"状态为进行中的预期"

**API**：`POST /api/v1/chat`

```json
{
  "message": "某某科技的预期有哪些",
  "session_id": "uuid",
  "sso_user": { "user_name": "张三", "user_id": "xxx" }
}
```

**验收标准**：查询延迟 ≤ 5 秒、支持公司名/预期状态/场景标题维度、结果卡片可展开

**工作量**：前端 1 天，后端 1.5 天

---

### US‑206：自然语言修改档案

**角色**：普通用户  
**故事**：作为一线客户成功，我希望通过自然语言修改档案，如"把排程预期状态改为已完成"。

**流程**：解析意图 → 生成修改预览 → **用户确认后才执行** → 记录日志

**验收标准**：修改前必须展示预览并获取确认、禁止自动写入、日志完整

**工作量**：前端 0.5 天（复用聊天界面），后端 1 天

---

### US‑207：简道云表单映射配置（超管）

**角色**：superadmin  
**故事**：作为系统维护者，我需要在前端配置简道云连接信息和字段映射，无需改代码。

**配置页结构**（详见 §8.7）：

**区块 1 — 简道云连接**：API Key（密码输入，AES-256 加密存储）、Base URL、「测试连接」按钮

**区块 2 — 主表单**：app_id、entry_id、公司 ID 字段 widget_id、公司名字段 widget_id

**区块 3 — 预期子表单映射**：子表单 widget_id + 动态行配置表（系统字段 ↔ widget_id ↔ 类型 ↔ 必填）

**区块 4 — 场景子表单映射**：同上

**区块 5 — 关联字段**：场景"关联预期"字段 widget_id

**验收标准**：测试连接显示结果、保存后立即生效、仅超管可见、修改需二次确认

**API**：
- `GET /api/v1/admin/config` — 获取配置
- `PUT /api/v1/admin/config` — 保存配置
- `POST /api/v1/admin/config/test` — 测试连接

**工作量**：前端 1.5 天，后端 1 天

---

### US‑208：LLM 配置管理（超管）

**角色**：superadmin  
**故事**：作为系统维护者，我需要在前端配置 LLM 调用参数，包括模型选择、API Key、生成参数、Prompt 模板，方便调优而无需改代码。

**配置项**：

| 配置项 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| LLM Provider | 下拉选择 | `dashscope` | 支持 dashscope（阿里云百炼）、openai_compatible |
| API Key | 密码输入 | — | AES-256 加密存储 |
| Base URL | 文本 | `https://dashscope.aliyuncs.com/compatible-mode/v1` | OpenAI 兼容端点 |
| Agent‑A 模型 | 文本 | `qwen-plus` | Agent‑A 使用的模型名 |
| Agent‑B 模型 | 文本 | `qwen-plus` | Agent‑B 使用的模型名 |
| NL 对话模型 | 文本 | `qwen-plus` | US-205/206 使用的模型名 |
| Temperature | 滑块 | 0.3 | 0.0–1.0 |
| Max Tokens | 数字输入 | 4096 | 最大输出 token |
| Agent‑A Prompt | 多行文本 | 见 §5.3.4 | 支持变量占位符 `{transcript_text}` |
| Agent‑B Prompt | 多行文本 | 见 §5.4.4 | 支持变量占位符 `{extraction_json}` `{existing_json}` |
| NL 查询 Prompt | 多行文本 | 系统默认 | 自然语言查询的系统提示词 |
| NL 修改 Prompt | 多行文本 | 系统默认 | 自然语言修改的系统提示词 |

**功能要求**：
- Prompt 编辑器支持语法高亮（至少高亮 `{变量}`）
- 提供「恢复默认」按钮，重置为系统内置 Prompt
- 提供「测试」按钮：输入一段示例文本，调用对应模型返回结果预览
- 配置修改记录变更日志（谁在什么时间改了什么）

**API**：
- `GET /api/v1/admin/llm-config` — 获取 LLM 配置
- `PUT /api/v1/admin/llm-config` — 保存 LLM 配置
- `POST /api/v1/admin/llm-config/test` — 测试 LLM 调用

**请求体**（保存）：

```json
{
  "provider": "dashscope",
  "api_key": "sk-xxx",
  "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
  "agent_a_model": "qwen-plus",
  "agent_b_model": "qwen-plus",
  "nl_chat_model": "qwen-plus",
  "temperature": 0.3,
  "max_tokens": 4096,
  "agent_a_prompt": "你是一个专业的客户成功分析师...",
  "agent_b_prompt": "你是一个客户档案管理专家...",
  "nl_query_prompt": "...",
  "nl_modify_prompt": "..."
}
```

**请求体**（测试）：

```json
{
  "target": "agent_a | agent_b | nl_chat",
  "test_input": "一段示例转写文本..."
}
```

**验收标准**：
- 修改后保存立即生效，下次 Agent 调用使用新配置
- API Key 前端仅显示 `sk-****xxxx`（脱敏），保存时不传则不更新
- 测试按钮返回 LLM 原始输出预览
- 恢复默认不影响已保存的 API Key

**工作量**：前端 1 天，后端 0.5 天

---

### US‑209：系统初始化页面

**角色**：superadmin（首次部署）  
**故事**：首次部署后访问系统时创建 superadmin 账号。

**行为**：
- 数据库无 superadmin 记录 → 自动跳转初始化页
- 填写用户名、密码（≥ 8 位，含大小写+数字）、确认密码
- 创建后跳转登录页；此后访问初始化路由返回 403

**API**：`POST /api/v1/system/init`

```json
{
  "username": "admin",
  "password": "xxxxx",
  "display_name": "系统管理员"
}
```

**工作量**：前端 0.5 天，后端 0.5 天

---

### US‑210：简道云 → 智档 SSO 跳转

**角色**：普通用户  
**故事**：在简道云客户档案页点击链接，直接跳转智档并自动登录，携带用户信息和客户 ID。

**方案**：

简道云客户档案主表添加超链接字段，链接格式：

```
https://zhidang.example.com/sso/entry?token={signed_token}&company_id={company_id}
```

**Token 生成流程**：
1. 智档提供 token 生成接口（超管配置共享密钥）
2. Token Payload：`{ user_name, user_id, company_id, timestamp }`
3. 签名算法：HMAC-SHA256，密钥存储在超管配置中
4. 用户点击 → 智档验证签名+时效（5 分钟）→ 签发 JWT → 跳转

**JWT Payload**（SSO 登录后签发）：

```json
{
  "user_name": "张三",
  "user_id": "jiandaoyun_user_id",
  "source": "sso",
  "exp": "24h"
}
```

**API**：
- `POST /api/v1/sso/generate` — 生成签名 token（供简道云/外部调用）
- `GET /api/v1/sso/entry?token=xxx&company_id=xxx` — 验证并登录

**验收标准**：
- Token 过期返回 403 + "链接已失效"
- 成功跳转后定位到对应公司的转写/档案页
- JWT 中包含来自简道云的 user_name

**工作量**：前端 0.5 天，后端 1 天

---

## 7. 数据模型

### 7.1 数据库表

```sql
-- 超管账号（仅一条记录）
CREATE TABLE superadmin (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username VARCHAR(50) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    display_name VARCHAR(100),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 系统配置（单行存储，所有配置集中）
CREATE TABLE system_config (
    id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),  -- 强制单行

    -- 简道云连接
    jiandaoyun_api_key_encrypted TEXT,
    jiandaoyun_base_url VARCHAR(255) DEFAULT 'https://api.jiandaoyun.com',
    jiandaoyun_app_id VARCHAR(100),
    main_entry_id VARCHAR(100),
    field_mappings JSONB NOT NULL DEFAULT '{}',

    -- LLM 配置
    llm_provider VARCHAR(50) DEFAULT 'dashscope',
    llm_api_key_encrypted TEXT,
    llm_base_url VARCHAR(255) DEFAULT 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    agent_a_model VARCHAR(100) DEFAULT 'qwen-plus',
    agent_b_model VARCHAR(100) DEFAULT 'qwen-plus',
    nl_chat_model VARCHAR(100) DEFAULT 'qwen-plus',
    temperature NUMERIC(3,2) DEFAULT 0.30,
    max_tokens INTEGER DEFAULT 4096,
    agent_a_prompt TEXT,
    agent_b_prompt TEXT,
    nl_query_prompt TEXT,
    nl_modify_prompt TEXT,

    -- SSO 配置
    sso_shared_secret VARCHAR(255),
    sso_token_ttl_minutes INTEGER DEFAULT 5,

    -- 钉钉配置
    dingtalk_app_key VARCHAR(255),
    dingtalk_app_secret_encrypted TEXT,
    dingtalk_agent_id VARCHAR(100),

    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 转写记录
CREATE TABLE transcripts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source VARCHAR(20) NOT NULL CHECK (source IN ('upload', 'dingtalk_api')),
    source_id VARCHAR(255),
    title VARCHAR(255),
    raw_text TEXT NOT NULL,
    segments JSONB,
    status VARCHAR(30) NOT NULL DEFAULT 'parsed'
        CHECK (status IN ('parsed','extracting','extracted',
                          'reviewing','confirmed','written','failed')),
    agent_a_result JSONB,
    agent_b_result JSONB,
    company_id VARCHAR(255),
    company_name VARCHAR(255),
    sso_user_name VARCHAR(100),       -- 来自 SSO 的操作人
    sso_user_id VARCHAR(255),         -- 来自 SSO 的用户 ID
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 操作日志
CREATE TABLE operation_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    transcript_id UUID REFERENCES transcripts(id),
    operation_type VARCHAR(50) NOT NULL,
    request_payload JSONB,
    response_payload JSONB,
    status VARCHAR(20) NOT NULL,
    operator_name VARCHAR(100),       -- SSO 用户名
    operator_id VARCHAR(255),         -- SSO 用户 ID
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 配置变更日志
CREATE TABLE config_change_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    config_section VARCHAR(50) NOT NULL,  -- 'llm' | 'jiandaoyun' | 'sso' | 'dingtalk'
    changed_fields JSONB NOT NULL,        -- {"temperature": {"old": 0.3, "new": 0.5}}
    changed_by VARCHAR(100) NOT NULL,     -- superadmin username
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

### 7.2 field_mappings JSON 结构

```json
{
  "main_table": {
    "company_id_widget": "_widget_xxxx",
    "company_name_widget": "_widget_xxxx"
  },
  "expectation_sub_table": {
    "sub_table_widget": "_widget_xxxx",
    "fields": {
      "summary": { "widget_id": "_widget_xxxx", "type": "text" },
      "is_first_value": { "widget_id": "_widget_xxxx", "type": "radiogroup" },
      "description": { "widget_id": "_widget_xxxx", "type": "textarea" },
      "estimated_start_time": { "widget_id": "_widget_xxxx", "type": "datetime" },
      "status": { "widget_id": "_widget_xxxx", "type": "radiogroup" },
      "progress": {
        "widget_id": "_widget_xxxx",
        "type": "subform",
        "sub_fields": {
          "date": { "widget_id": "_widget_xxxx", "type": "datetime" },
          "note": { "widget_id": "_widget_xxxx", "type": "textarea" }
        }
      }
    }
  },
  "scenario_sub_table": {
    "sub_table_widget": "_widget_xxxx",
    "fields": {
      "title": { "widget_id": "_widget_xxxx", "type": "text" },
      "is_first_value": { "widget_id": "_widget_xxxx", "type": "radiogroup" },
      "pain_point": { "widget_id": "_widget_xxxx", "type": "textarea" },
      "core_metric_solution": { "widget_id": "_widget_xxxx", "type": "textarea" },
      "value_quantification": { "widget_id": "_widget_xxxx", "type": "textarea" },
      "summary": { "widget_id": "_widget_xxxx", "type": "textarea" },
      "linked_expectation": { "widget_id": "_widget_xxxx", "type": "linkdata" }
    }
  }
}
```

### 7.3 简道云表单结构（根据截图确认）

**主表单 — 客户档案**：公司 ID（唯一键，UUID）、公司名称、行业、其他基础字段

**子表单 1 — 客户业务预期维护**：预期简述（text，必填）、是否第一价值实现预期（radiogroup，必填）、预期描述（textarea，必填）、预计启动时间（datetime）、预期状态（radiogroup，必填：未启动/进行中/已完成/搁置）、预期进度（subform：日期+说明）

**子表单 2 — 客户场景**：场景标题（text，必填）、是否第一价值实现场景（radiogroup，必填）、业务诉求/痛点分析（textarea，必填）、核心指标&解决方案（textarea）、价值量化（textarea）、总结沉淀（textarea）、关联预期（linkdata）

---

## 8. UI 架构设计

### 8.1 页面路由

```
/                               → 重定向逻辑（见下方）
/init                           → 系统初始化页（US-209）
/login                          → 超管登录页
/sso/entry?token=&company_id=   → SSO 入口（US-210）

/transcripts                    → 转写管理列表
/transcripts/upload             → 上传转写（US-201A）
/transcripts/dingtalk           → 钉钉获取（US-201B）
/transcripts/:id/review         → 审核页（US-203）

/chat                           → 自然语言对话（US-205/206）

/admin/config                   → 简道云配置（US-207，超管）
/admin/llm                      → LLM 配置（US-208，超管）
```

**重定向逻辑**：
- 无 superadmin 记录 → `/init`
- 有 JWT 且 source=sso → `/transcripts`
- 有 JWT 且 source=superadmin → `/admin/config`
- 无 JWT → `/login`

### 8.2 全局布局

```
┌─────────────────────────────────────────────────────────┐
│  顶部导航栏                                              │
│  Logo 智档  │  转写管理  │  对话  │  管理(超管)  │ 用户 ▼ │
├─────────────────────────────────────────────────────────┤
│                                                         │
│                     主内容区域                            │
│                                                         │
│                                                         │
├─────────────────────────────────────────────────────────┤
│  底部：当前用户(SSO来源显示姓名) │ 系统版本               │
└─────────────────────────────────────────────────────────┘
```

导航栏中「管理」入口仅超管 JWT 可见。普通用户看到的导航：转写管理、对话、用户姓名。

### 8.3 转写管理列表页 `/transcripts`

```
┌─────────────────────────────────────────────────────────────┐
│  转写管理                                                    │
│                                                             │
│  ┌────────────┐  ┌─────────────────┐  ┌─────────┐          │
│  │ 📤 上传文件 │  │ 📥 从钉钉获取    │  │ 🔍 搜索  │          │
│  └────────────┘  └─────────────────┘  └─────────┘          │
│                                                             │
│  ┌───┬────────────────┬───────┬───────┬─────────┬────────┐ │
│  │ # │ 标题            │ 来源  │ 状态   │ 操作人   │ 操作   │ │
│  ├───┼────────────────┼───────┼───────┼─────────┼────────┤ │
│  │ 1 │ 04-22 客户拜访  │ 手动  │ 待审核 │ 张三    │ [查看] │ │
│  │ 2 │ 04-21 项目沟通  │ 钉钉  │ 已写入 │ 李四    │ [查看] │ │
│  │ 3 │ 04-20 需求对接  │ 手动  │ 草稿   │ 张三    │ [继续] │ │
│  └───┴────────────────┴───────┴───────┴─────────┴────────┘ │
│                                                             │
│  ◀ 1 2 3 ▶                                                 │
└─────────────────────────────────────────────────────────────┘
```

### 8.4 审核页 `/transcripts/:id/review`

```
┌────────────────────────────────────────────────────────────────────┐
│  审核 - 04-22 客户拜访：某某科技                                     │
│                                                                    │
│  ┌─ 客户信息 ────────────────────────────────────────────────────┐ │
│  │  公司：某某科技有限公司  ID: eb6dc9bc-...  [🔍 重新匹配]       │ │
│  └───────────────────────────────────────────────────────────────┘ │
│                                                                    │
│  ┌─ 原文(折叠) ─────────┐  ┌─ 操作列表 ────────────────────────┐ │
│  │                       │  │                                   │ │
│  │  发言人 1  00:00:00   │  │  ┌─ 🟢 新增预期 ───────────────┐ │ │
│  │  我们希望能实现...    │  │  │  预期简述：实现质检自动化     │ │ │
│  │                       │  │  │  第一价值：是                │ │ │
│  │  发言人 2  00:01:23   │  │  │  描述：客户希望通过AI...     │ │ │
│  │  目前的痛点是...      │  │  │  状态：未启动               │ │ │
│  │                       │  │  │  置信度：92%  📄"我们希望.."│ │ │
│  │  发言人 1  00:03:45   │  │  │  [✓ 确认] [✎ 编辑] [✕ 删除]│ │ │
│  │  排程这块我们试了...  │  │  └─────────────────────────────┘ │ │
│  │                       │  │                                   │ │
│  │                       │  │  ┌─ 🔵 更新预期 ───────────────┐ │ │
│  │                       │  │  │  匹配：实现生产自动排程      │ │ │
│  │                       │  │  │  操作：追加进度              │ │ │
│  │                       │  │  │  进度内容："排程模块已试用.."│ │ │
│  │                       │  │  │  匹配理由：提到排程模块...   │ │ │
│  │                       │  │  │  置信度：85%                │ │ │
│  │  [搜索原文...]        │  │  │  [✓ 确认] [✎ 编辑] [✕ 删除]│ │ │
│  │                       │  │  └─────────────────────────────┘ │ │
│  │                       │  │                                   │ │
│  │                       │  │  ┌─ 🟢 新增场景 ───────────────┐ │ │
│  │                       │  │  │  场景标题：质检缺陷识别      │ │ │
│  │                       │  │  │  ...                         │ │ │
│  │                       │  │  └─────────────────────────────┘ │ │
│  └───────────────────────┘  └───────────────────────────────────┘ │
│                                                                    │
│  ┌────────────────────────────────────────────────────────────────┐│
│  │  共 5 条 │ 已确认 2 │ 已删除 1 │ 待处理 2                      ││
│  │                          [保存草稿]  [全部确认并写入(灰/亮)]    ││
│  └────────────────────────────────────────────────────────────────┘│
└────────────────────────────────────────────────────────────────────┘
```

### 8.5 自然语言对话页 `/chat`

```
┌──────────────────────────────────────────────────────┐
│  智档对话                                             │
│                                                      │
│  ┌─────────────────────────────────────────────────┐ │
│  │                                                 │ │
│  │  🤖 你好，我可以帮你查询或修改客户档案。         │ │
│  │     试试说"查询某某科技的预期"                   │ │
│  │                                                 │ │
│  │  👤 某某科技的预期有哪些                         │ │
│  │                                                 │ │
│  │  🤖 某某科技共有 3 条预期：                      │ │
│  │     ┌─────────────────────────────┐             │ │
│  │     │ 1. 实现生产自动排程          │             │ │
│  │     │    状态：进行中  第一价值：是 │             │ │
│  │     │    [展开详情]                │             │ │
│  │     ├─────────────────────────────┤             │ │
│  │     │ 2. 实现质检自动化            │             │ │
│  │     │    状态：未启动  第一价值：是 │             │ │
│  │     └─────────────────────────────┘             │ │
│  │                                                 │ │
│  │  👤 把排程预期的状态改为已完成                    │ │
│  │                                                 │ │
│  │  🤖 确认修改？                                   │ │
│  │     公司：某某科技  预期：实现生产自动排程         │ │
│  │     变更：状态 进行中 → 已完成                    │ │
│  │     [确认]  [取消]                               │ │
│  │                                                 │ │
│  └─────────────────────────────────────────────────┘ │
│  ┌────────────────────────────────┐ ┌────┐          │
│  │  输入你的问题或指令...          │ │ 发送 │          │
│  └────────────────────────────────┘ └────┘          │
└──────────────────────────────────────────────────────┘
```

### 8.6 超管 — 简道云配置页 `/admin/config`

```
┌──────────────────────────────────────────────────────────────┐
│  简道云配置                                                    │
│                                                              │
│  ┌─ 连接配置 ──────────────────────────────────────────────┐ │
│  │  API Key:   [••••••••••••]            [测试连接 ✅]      │ │
│  │  Base URL:  [https://api.jiandaoyun.com              ]  │ │
│  └──────────────────────────────────────────────────────────┘ │
│                                                              │
│  ┌─ 主表单 ────────────────────────────────────────────────┐ │
│  │  app_id:      [                    ]                    │ │
│  │  entry_id:    [                    ]                    │ │
│  │  公司ID字段:   [_widget_            ]                    │ │
│  │  公司名字段:   [_widget_            ]                    │ │
│  └──────────────────────────────────────────────────────────┘ │
│                                                              │
│  ┌─ 预期子表单映射 ────────────────────────────────────────┐ │
│  │  子表单 widget_id: [_widget_               ]            │ │
│  │  ┌────────────┬──────────────┬──────────┬──────┐       │ │
│  │  │ 系统字段    │ widget_id    │ 字段类型  │ 必填 │       │ │
│  │  ├────────────┼──────────────┼──────────┼──────┤       │ │
│  │  │ 预期简述    │ [          ] │ text     │ ✓    │       │ │
│  │  │ 第一价值    │ [          ] │ radio    │ ✓    │       │ │
│  │  │ 预期描述    │ [          ] │ textarea │ ✓    │       │ │
│  │  │ 启动时间    │ [          ] │ datetime │      │       │ │
│  │  │ 预期状态    │ [          ] │ radio    │ ✓    │       │ │
│  │  │ 预期进度    │ [          ] │ subform  │ ✓    │       │ │
│  │  └────────────┴──────────────┴──────────┴──────┘       │ │
│  └──────────────────────────────────────────────────────────┘ │
│                                                              │
│  ┌─ 场景子表单映射 ────────────────────────────────────────┐ │
│  │  （同上结构）                                            │ │
│  └──────────────────────────────────────────────────────────┘ │
│                                                              │
│  ┌─ SSO 配置 ──────────────────────────────────────────────┐ │
│  │  共享密钥: [••••••••••]  [🔄 重新生成]                   │ │
│  │  Token有效期: [5] 分钟                                  │ │
│  └──────────────────────────────────────────────────────────┘ │
│                                                              │
│  ┌─ 钉钉配置 ──────────────────────────────────────────────┐ │
│  │  App Key:    [                    ]                      │ │
│  │  App Secret: [••••••••••••]                              │ │
│  │  Agent ID:   [                    ]                      │ │
│  └──────────────────────────────────────────────────────────┘ │
│                                                              │
│                            [取消]  [保存配置]                 │
└──────────────────────────────────────────────────────────────┘
```

### 8.7 超管 — LLM 配置页 `/admin/llm`

```
┌──────────────────────────────────────────────────────────────┐
│  LLM 配置                                                     │
│                                                              │
│  ┌─ 基础配置 ──────────────────────────────────────────────┐ │
│  │  Provider:    [dashscope          ▼]                    │ │
│  │  API Key:     [sk-****xxxx         ]                    │ │
│  │  Base URL:    [https://dashscope...              ]      │ │
│  └──────────────────────────────────────────────────────────┘ │
│                                                              │
│  ┌─ 模型选择 ──────────────────────────────────────────────┐ │
│  │  Agent‑A 模型:  [qwen-plus        ]                     │ │
│  │  Agent‑B 模型:  [qwen-plus        ]                     │ │
│  │  对话模型:      [qwen-plus        ]                     │ │
│  └──────────────────────────────────────────────────────────┘ │
│                                                              │
│  ┌─ 生成参数 ──────────────────────────────────────────────┐ │
│  │  Temperature:  ○──────●──────○  0.3                     │ │
│  │  Max Tokens:   [4096          ]                         │ │
│  └──────────────────────────────────────────────────────────┘ │
│                                                              │
│  ┌─ Agent‑A Prompt ────────────────────────────────────────┐ │
│  │  ┌──────────────────────────────────────────────────┐   │ │
│  │  │ 你是一个专业的客户成功分析师。请从以下客户拜访    │   │ │
│  │  │ 会议转写中提取信息。                             │   │ │
│  │  │                                                  │   │ │
│  │  │ ## 任务                                          │   │ │
│  │  │ 1. 判断该转写是否包含客户拜访内容...             │   │ │
│  │  │ ...                                              │   │ │
│  │  │ {transcript_text}  ← 变量高亮                    │   │ │
│  │  └──────────────────────────────────────────────────┘   │ │
│  │  [恢复默认]  [测试 ▶]                                   │ │
│  └──────────────────────────────────────────────────────────┘ │
│                                                              │
│  ┌─ Agent‑B Prompt ────────────────────────────────────────┐ │
│  │  （同上，变量: {extraction_json} {existing_json}）       │ │
│  │  [恢复默认]  [测试 ▶]                                   │ │
│  └──────────────────────────────────────────────────────────┘ │
│                                                              │
│  ┌─ 对话 Prompt（查询）─────────────────────────────────────┐ │
│  │  （同上）  [恢复默认]  [测试 ▶]                          │ │
│  └──────────────────────────────────────────────────────────┘ │
│                                                              │
│  ┌─ 对话 Prompt（修改）─────────────────────────────────────┐ │
│  │  （同上）  [恢复默认]  [测试 ▶]                          │ │
│  └──────────────────────────────────────────────────────────┘ │
│                                                              │
│                            [取消]  [保存配置]                 │
└──────────────────────────────────────────────────────────────┘
```

### 8.8 系统初始化页 `/init`

```
┌──────────────────────────────────────┐
│                                      │
│          ⚙️  智档系统初始化           │
│                                      │
│  首次使用请创建管理员账号             │
│                                      │
│  用户名:    [              ]          │
│  显示名称:  [              ]          │
│  密码:      [              ]          │
│  确认密码:  [              ]          │
│                                      │
│        [ 初始化系统 ]                 │
│                                      │
│  密码要求：≥8位，含大小写+数字        │
│                                      │
└──────────────────────────────────────┘
```

---

## 9. 转写文件解析规则

### 9.1 钉钉 AI 听记导出格式

```
04-22 内部会议. 活动流程与线上线下协作安排
                                          ← 空行
发言人 1  00:00:00
呃，那个解拆解，不回答具体的。
                                          ← 空行
发言人 2  00:00:03
是的是的，制作看板的问题...
```

### 9.2 解析正则与代码

```python
import re

SPEAKER_PATTERN = re.compile(r'^发言人\s*(\d+)\s+(\d{2}:\d{2}:\d{2})$')

def parse_transcript(text: str) -> dict:
    lines = text.strip().split('\n')
    title = lines[0].strip() if lines else "未命名转写"

    segments = []
    current_speaker = None
    current_timestamp = None
    current_text_lines = []

    for line in lines[1:]:
        match = SPEAKER_PATTERN.match(line.strip())
        if match:
            if current_speaker is not None:
                segments.append({
                    "speaker": f"发言人 {current_speaker}",
                    "timestamp": current_timestamp,
                    "text": '\n'.join(current_text_lines).strip()
                })
            current_speaker = match.group(1)
            current_timestamp = match.group(2)
            current_text_lines = []
        elif line.strip():
            current_text_lines.append(line.strip())

    if current_speaker is not None:
        segments.append({
            "speaker": f"发言人 {current_speaker}",
            "timestamp": current_timestamp,
            "text": '\n'.join(current_text_lines).strip()
        })

    raw_text = '\n'.join(
        f"[{s['speaker']} {s['timestamp']}] {s['text']}" for s in segments
    )

    return { "title": title, "raw_text": raw_text, "segments": segments }
```

### 9.3 降级策略

文件内容不匹配发言人格式（.md / .docx 纯文本）时，不做分段解析，整段存入 `raw_text`，`segments` 为空数组。Agent‑A Prompt 兼容两种输入。

---

## 10. 技术架构

### 10.1 技术栈

| 层级 | 选型 |
|---|---|
| 前端 | Vue 3 + Element Plus |
| 后端 | Python FastAPI |
| 数据库 | PostgreSQL |
| LLM | 超管可配（默认阿里云百炼 Qwen，支持 OpenAI 兼容接口） |
| 部署 | Docker Compose |
| 认证 | JWT 24h |
| 加密 | AES-256（API Key 存储） |

### 10.2 Docker Compose

```yaml
version: '3.8'
services:
  frontend:
    build: ./frontend
    ports: ["80:80"]
    depends_on: [backend]

  backend:
    build: ./backend
    ports: ["8000:8000"]
    environment:
      - DATABASE_URL=postgresql://user:pass@postgres:5432/zhidang
      - AES_SECRET_KEY=${AES_SECRET_KEY}
    depends_on: [postgres]

  postgres:
    image: postgres:16-alpine
    volumes: [pgdata:/var/lib/postgresql/data]
    environment:
      - POSTGRES_DB=zhidang
      - POSTGRES_USER=user
      - POSTGRES_PASSWORD=pass

volumes:
  pgdata:
```

注意：LLM API Key 不再写入环境变量，而是存储在 `system_config` 表中（AES 加密），通过超管页面管理。

### 10.3 后端目录结构

```
backend/
├── app/
│   ├── main.py
│   ├── config.py                     # 从 DB 读取 system_config
│   ├── models/
│   │   ├── superadmin.py
│   │   ├── system_config.py
│   │   ├── transcript.py
│   │   └── operation_log.py
│   ├── agents/
│   │   ├── extraction_agent.py       # Agent-A
│   │   ├── comparison_agent.py       # Agent-B
│   │   └── orchestrator.py           # 调度器
│   ├── services/
│   │   ├── jiandaoyun.py             # 简道云 API
│   │   ├── dingtalk.py               # 钉钉 API
│   │   ├── llm_client.py             # LLM 调用（读取 DB 配置）
│   │   ├── transcript_parser.py
│   │   └── chat_service.py
│   ├── routers/
│   │   ├── transcript.py
│   │   ├── agent.py
│   │   ├── operations.py
│   │   ├── chat.py
│   │   ├── admin.py                  # 简道云配置 + LLM 配置
│   │   ├── auth.py
│   │   └── sso.py
│   └── utils/
│       ├── encryption.py
│       ├── auth.py
│       └── logger.py
├── logs/
│   ├── write_operations.jsonl
│   └── chat_modifications.jsonl
├── Dockerfile
└── requirements.txt
```

---

## 11. 全量 API 清单

| 端点 | 方法 | 说明 | 认证要求 |
|---|---|---|---|
| `/api/v1/system/init` | POST | 系统初始化 | 无（仅首次） |
| `/api/v1/auth/login` | POST | 超管登录 | 无 |
| `/api/v1/sso/generate` | POST | 生成 SSO Token | 共享密钥 |
| `/api/v1/sso/entry` | GET | SSO 入口验证 | Token 签名 |
| `/api/v1/transcript/upload` | POST | 上传转写 | JWT |
| `/api/v1/transcript/dingtalk-fetch` | POST | 钉钉拉取 | JWT |
| `/api/v1/webhook/dingtalk` | POST | 钉钉事件回调 | 钉钉签名 |
| `/api/v1/transcripts` | GET | 转写列表 | JWT |
| `/api/v1/transcripts/:id` | GET | 转写详情 | JWT |
| `/api/v1/agent/extraction/task` | POST | Agent‑A 提取 | 内部调用 |
| `/api/v1/agent/comparison/task` | POST | Agent‑B 比对 | 内部调用 |
| `/api/v1/operations/execute` | POST | 执行写入 | JWT |
| `/api/v1/chat` | POST | 自然语言对话 | JWT |
| `/api/v1/admin/config` | GET | 获取简道云配置 | 超管 JWT |
| `/api/v1/admin/config` | PUT | 保存简道云配置 | 超管 JWT |
| `/api/v1/admin/config/test` | POST | 测试简道云连接 | 超管 JWT |
| `/api/v1/admin/llm-config` | GET | 获取 LLM 配置 | 超管 JWT |
| `/api/v1/admin/llm-config` | PUT | 保存 LLM 配置 | 超管 JWT |
| `/api/v1/admin/llm-config/test` | POST | 测试 LLM 调用 | 超管 JWT |

---

## 12. 非功能需求

| 维度 | 要求 |
|---|---|
| Agent‑A 延迟 | ≤ 15 秒 |
| Agent‑B 延迟 | ≤ 10 秒 |
| 端到端延迟 | ≤ 30 秒 |
| 简道云写入 | ≤ 3 秒/条 |
| NL 查询 | ≤ 5 秒 |
| 并发用户 | ≤ 10 |
| 浏览器 | Chrome 最新版 |
| API Key 存储 | AES-256 加密 |
| 认证 | JWT 24h |
| 日志路径 | `logs/write_operations.jsonl`、`logs/chat_modifications.jsonl` |
| 部署 | Docker Compose 一键部署 |

---

## 13. 排期计划

### 13.1 两周冲刺（10 个工作日）

| 天 | 任务 | US 编号 | 产出 |
|---|---|---|---|
| **D1** | 系统初始化 + superadmin 认证 + DB Schema | US‑209 | 可登录 |
| **D2** | 简道云配置页（前端+后端+测试连接） | US‑207 | 配置可用 |
| **D3** | LLM 配置页（前端+后端+测试调用）+ Prompt 编辑器 | US‑208 | LLM 可配 |
| **D4** | 上传转写 + 解析 + Agent‑A 调通 | US‑201A, US‑202(A) | 提取链路 |
| **D5** | 简道云查询集成 + Agent‑B 调通 | US‑202(B) | 比对链路 |
| **D6** | 审核页前端（操作卡片、编辑、确认） | US‑203 | 审核可用 |
| **D7** | 写入简道云（全量回写、重试、日志） | US‑204 | 全链路通 |
| **D8** | 钉钉 API 集成 + SSO 跳转 | US‑201B, US‑210 | 双通道+SSO |
| **D9** | 自然语言对话（查询+修改） | US‑205, US‑206 | 对话可用 |
| **D10** | 联调、Bug 修复、内测部署 | — | 可交付 |

### 13.2 工作量汇总

| 模块 | 前端 | 后端 | 合计 |
|---|---|---|---|
| 初始化+认证 | 0.5d | 0.5d | 1d |
| 简道云配置 | 1.5d | 1d | 2.5d |
| LLM 配置 | 1d | 0.5d | 1.5d |
| 上传+解析 | 0.5d | 0.5d | 1d |
| Agent‑A+B | — | 2d | 2d |
| 审核页 | 2d | 0.5d | 2.5d |
| 写入简道云 | — | 1.5d | 1.5d |
| 钉钉 API | 0.5d | 2d | 2.5d |
| SSO | 0.5d | 1d | 1.5d |
| NL 对话 | 1d | 1.5d | 2.5d |
| 联调内测 | 0.5d | 0.5d | 1d |
| **合计** | **8d** | **11.5d** | **19.5d** |

> 单人全栈约 10 个工作日紧张。如遇阻塞，**优先保证核心链路**（D1–D7），D8 钉钉 API 和 D9 NL 对话可延至第三周。

### 13.3 里程碑

| 节点 | 里程碑 | 验收 |
|---|---|---|
| D3 结束 | 基础设施完成 | 超管可登录、配置简道云和 LLM |
| D5 结束 | 核心链路跑通 | 上传 → Agent‑A → Agent‑B → 审核页 |
| D7 结束 | 全链路跑通 | 含简道云写入 |
| D10 结束 | 内测版本交付 | 全功能可用 |

---

## 14. 验收标准

| 编号 | 验收项 | 达标标准 |
|---|---|---|
| AC‑01 | 全链路跑通 | 上传 → Agent‑A → Agent‑B → 审核 → 写入简道云 |
| AC‑02 | 提取准确率 | ≥ 70%（内测 5 人评估） |
| AC‑03 | 写入成功率 | 100%（重试后） |
| AC‑04 | 子表单完整性 | 已有行不丢失 |
| AC‑05 | SSO 成功率 | 100% |
| AC‑06 | 端到端延迟 | ≤ 30 秒 |
| AC‑07 | NL 对话 | 可完成查询和修改，修改前必须确认 |
| AC‑08 | LLM 配置 | 超管修改模型/Prompt 后下次调用立即生效 |
| AC‑09 | 配置变更日志 | 每次配置修改有记录可查 |

---

## 15. 风险与应对

| 风险 | 概率 | 影响 | 应对 |
|---|---|---|---|
| 钉钉权限审批延迟 | 中 | US‑201B 延后 | 手动上传保底，钉钉延至审批后上线 |
| Agent‑B 比对准确率不足 | 中 | 误判新增/更新 | 审核页提供"转为新增"/"转为更新"切换；低置信度标黄 |
| 子表单全量回写数据丢失 | 高 | 覆盖已有数据 | 写前拉取最新全量，追加后提交；自动备份到 operation_logs |
| LLM 返回非法 JSON | 中 | 链路中断 | Prompt 强调 JSON；后端校验+修复（去代码块、补括号）；失败重试 |
| 10 天工期紧张 | 高 | 无法全部完成 | 保证 D1–D7 核心链路；D8/D9 可延至第三周 |
| 简道云 API 限频 20 次/秒 | 低 | 批量写入受阻 | V0.1 并发低，不触发；后端加队列兜底 |
| 超管误改 Prompt 导致提取失败 | 中 | 链路异常 | 「恢复默认」按钮；配置变更日志可追溯 |

---

## 16. 开放问题追踪

| 编号 | 问题 | 状态 | 负责人 | 结论 |
|---|---|---|---|---|
| Q1 | 钉钉后台企业应用 | ✅ 关闭 | Alois | 已有 |
| Q1‑b | 转写文件格式 | ✅ 关闭 | Alois | 纯文本，发言人+时间戳 |
| Q2 | 简道云 widget_id | ✅ 关闭 | — | 前端超管配置 |
| Q3 | 客户唯一键 | ✅ 关闭 | Karl | 公司 ID（UUID） |
| Q4 | 角色模型 | ✅ 关闭 | Karl | 简化为 superadmin + SSO 普通用户 |
| Q5 | 初始化方式 | ✅ 关闭 | Gust | 系统初始化页 |
| Q6 | 待办提取 | ✅ 关闭 | Karl | V0.1 不做 |
| Q7 | SSO 方案 | ✅ 关闭 | — | 签名 Token |
| Q8 | 简道云付费 | ✅ 关闭 | — | 不涉及（帆软产品） |
| Q9 | 用户名与简道云成员同步 | 🔲 延期 | — | V0.2 处理 |

---

## 17. 变更记录

| 日期 | 编号 | 内容 |
|---|---|---|
| 2026‑04‑23 | CR‑001 | 初始版本 |
| 2026‑04‑23 | CR‑002 | 双通道转写（上传+钉钉 API） |
| 2026‑04‑23 | CR‑003 | 简道云配置改为前端超管 |
| 2026‑04‑23 | CR‑004 | 加入多租户 |
| 2026‑04‑23 | CR‑005 | Q3–Q8 确认关闭 |
| 2026‑04‑23 | CR‑006 | 预期管理改为双 Agent A2A 架构 |
| 2026‑04‑23 | CR‑007 | 新增 LLM 超管配置（US‑208） |
| 2026‑04‑23 | CR‑008 | **砍掉多租户数据库**，用户身份改为简道云 SSO 传入，仅保留 superadmin 本地账号 |

---
