# HANDOFF.md — 智档 (ZhiDang) 权力地图子系统

> 生成时间：2026-05-23
> 交接人：Hermes Agent
> 部署环境：47.98.102.197（生产），本地 WSL `/mnt/d/智档`

---

## 1. 项目定位

**智档**是帆软 CS 部门（Customer Success）的自动化平台。核心管线：CSM 会议录音/截图 → LLM 提取结构化事实 → 对比简道云存量 → 生成操作卡片 → 人工审核 → 写回简道云。

**权力地图**是智档的子功能：从 BI（FineBI）加载组织架构，通过 LLM + 25+ 个工具操纵节点/边/布局，最终写回 BI。渲染引擎是 AntV X6 + dagre（iframe 嵌入 BI HTML 页面）。

---

## 2. 关键入口文件（按必读顺序）

### 2.1 `backend/app/services/power_map_service.py` — 权力地图核心

| 区域 | 行号 | 职责 |
|------|------|------|
| 常量 `PERSON_W=160` / `DEPt_DEFAULT_W=700` | L41-50 | 节点默认尺寸，前端完全一致 |
| `PowerNode` dataclass | L169-221 | 内存节点模型，含 `w:float=0` / `parent_dept_id` |
| `_node_from_bi_dict` | L360-397 | BI → PowerNode 转换。**刚修复 truthy 陷阱**，用 `_safe_pos_float` |
| `_power_node_to_bi_info_dict` | L400-447 | PowerNode → BI writeback。user 强制写 `width="160"` |
| `_tool_create_node` | L3796-3920 | LLM 工具：新建节点。person 默认 160×72，走 `_find_free_position` |
| `_tool_set_parent` | L4592-4660 | LLM 工具：重设父子。已补 `name` + `new_parent_name` 返回值 |
| `_tool_fit_container_to_children` | L5460-5570 | LLM 工具：容器收缩。**刚加 zero-size 防御** |
| `_tool_list_edges` | L4221-4270 | LLM 工具：按 source/target/type 过滤边，**2026-05-23 新增** |
| `_tool_delete_node` / `_tool_delete_edge` | L4128/4189 | LLM 工具：节点/边删除 |
| `_tool_check_geometry` | L3602 | LLM 工具：碰撞检测。**刚加 `zero_dimensions` 告警** |
| `HARNESS_SYSTEM_PROMPT` | L6764-6835 | LLM system prompt（harness 多轮工具调用流用） |
| `_build_graph_state_text` | L7447-7487 | ctx → 文本注入 LLM user message。**刚加边端点和父部门名** |
| `_TOOL_RESULT_COMPRESS_KEEP_FIELDS` | L7570-7588 | 旧轮 tool_result 压缩白名单，**5→17，2026-05-23 扩** |
| `_normalize_tool_call_ids` | ~L7437 | Bedrock 400 修复：规范化 tool_call ID，拆多 tool_call 为单条 |
| `_run_llm_tool_loop` | ~L7730 | harness 主循环，每轮注入 gs_text + 截图 |
| `_build_merge_context` | L837-865 | 从 BI 加载数据构建 MergeContext。**刚加 wh_sanity 兜底** |
| `_execute_harness_tool` | ~L7060 | 工具调用分发。**含重复失败检测**（防线 B） |
| `_fetch_from_external` | L8479 | BI 数据拉取。prj_type=opp 取节点/边，company 取元数据 |
| `_safe_pos_float` | 新函数 | **2026-05-23 新增**，结束 `or` truthy 陷阱 |

文件当前 ~9800 行 / 395KB。**所有 CC 任务必须加 `--disallowedTools Task` 防止 superpowers 子代理僵尸**。

### 2.2 `backend/app/main.py` — API 路由（2400+ 行单体）
FastAPI 路由：`/api/power-map/chat`, `/api/power-map/getInfo`, `/api/power-map/upInfo`, `/api/power-map/harness/*` 等。

### 2.3 `backend/app/services/prompts.py` — LLM system prompts
含 `POWER_MAP_SYSTEM_PROMPT`（单轮 JSON delta）和 `HARNESS_SYSTEM_PROMPT`（多轮工具调用）。**两者不可互换**。

### 2.4 `backend/app/static/sandbox/powerMap_v3.13.html` — 生产视图
AntV X6 渲染引擎。user 卡片 160×72（L6640-6641）。**iframe 是唯一生产视图**，不存在替代品。

### 2.5 `frontend/src/pages/PowerMapPage.vue` — 前端壳
Vue 3 组件，包含 iframe 加载 BI 页面 + 聊天面板。`viewMode` 默认 `'iframe'`。

---

## 3. 当前架构关键约束

### 3.1 不要碰 BI 数据加载路径
`_fetch_from_external` → `_node_from_bi_dict` 是唯一入口。**不要新增数据源，不要修改 prj_type 逻辑**（company 取元信息，opp 取实际节点/边）。

### 3.2 不要碰 writeback 逻辑
`_power_node_to_bi_info_dict` 已正确：user 强制 160×72，dept 取 `node.w`。writeback 走 `upInfo` API。

### 3.3 不要碰多 tool_call → 单条拆分的 normalize 层
`_normalize_tool_call_ids` 解决了 Bedrock 400 bug。不要修改或绕过。

### 3.4 不要碰防线 A/B/C
- 防线 A：`_tool_fit_container_to_children` 的 `geometric_containment_mismatch` 检测
- 防线 B：`_execute_harness_tool` 的重复失败调用检测（ring buffer）
- 这两套防御**修改时不能破坏语义**

### 3.5 不要用 `or` 链做 fallback
`_node_from_bi_dict` L395 的原 `or` 链已被 `_safe_pos_float` 替代。**禁止在任何 BI 字段读取中用 `or` 链**——字符串 `"0"` 是 truthy。

### 3.6 CC 调用铁律
- 395KB 文件必须加 `--disallowedTools Task` + DIRECTIVE 前缀
- 大文件预算：<50KB→$2, 100-150→$4, >300→$4+（即使只读诊断）
- 所有代码改动必须委托 CC，禁止手动写 Python

### 3.7 部署铁律
scp → docker cp → docker compose restart。生产容器名 `zhidang-backend-1`，docker-compose 路径 `/opt/zhidang/docker-compose.yml`。

### 3.8 两个 LLM 流不可互换
- `chat_power_map`：单轮 JSON delta，使用 `POWER_MAP_SYSTEM_PROMPT`
- `chat_power_map_v2` / harness：多轮工具调用，使用 `HARNESS_SYSTEM_PROMPT`

---

## 4. 已知未解决问题

### 4.1 [P2] 多 tool_call 触发 Bedrock 400 — 未完全结案
- **复现条件**：单轮 LLM 返回多个 tool_call（如 `create_node`×2）
- **当前状态**：`_normalize_tool_call_ids` 拆多 tool_call 为单条绕过网关翻译路径。**未在真实多 tool_call 场景验证**。
- **验证方法**：构造 `create_node` 两个并发的 harness session，确认无 400。

### 4.2 [P2] user 节点 w=0 在旧 session 残留
- **复现条件**：BI 内存有字符串 `"width": "0"` 的老数据，且未经过新增节点触发 writeback
- **当前状态**：P0 `_safe_pos_float` + P1 `wh_sanity` + P1 fit 防御 + P2 check_geometry 四层兜底已部署。**新 session 不受影响**。旧 session 在下次 fit_container/check_geometry 时自动修正。

### 4.3 [P3] dept-dept 父子关系完全依赖 LLM 推断
- **复现条件**：BI 中部门间无 `par_id` 关联（如销售部与华南销售组平级），LLM 未主动调 `set_parent`
- **当前状态**：SOP prompt + 几何兜底已部署。未实现自动化补全，依赖 LLM 自觉。

---

## 5. 最近一周重要修复（倒序）

| 日期 | 修复 | 文件 | 关键行 |
|------|------|------|--------|
| 05-23 | user w/h=0 truthy trap | `power_map_service.py` | `_safe_pos_float` + L394 + L898 + L5662 + L3683 |
| 05-23 | 上下文质量 3 件套 | `power_map_service.py` | L7480 边加名、L7570 keep_fields、L4221 list_edges |
| 05-22 | Bedrock 400 修复 | `power_map_service.py` | `_normalize_tool_call_ids` ~L7437 |
| 05-22 | dept-dept 父子 3 防线 | `power_map_service.py` | fit 几何兜底 + 重复失败检测 + SOP prompt |
| 05-22 | 边 ID 暴露 | `power_map_service.py` | `_build_graph_state_text` L7480 边格式 `eid: name --type--> name` |
| 05-21 | `set_parent` 补返回值 | `power_map_service.py` | L4656 `name` + `new_parent_name` |
| 05-21 | Harness tool 设计原则确立 | 文档 | 工具是纯算法，LLM 管语义 |

---

## 6. 当前任务交接清单

| 状态 | 任务 | 说明 |
|------|------|------|
| ✅ 已完成 | zero-wh 四层兜底 | `_safe_pos_float` + wh_sanity + fit防御 + check_geometry，已部署 |
| ✅ 已完成 | 上下文质量 3 件套 | 边名 + keep_fields扩建 + list_edges，已部署 |
| 🔜 下一步 | 验证 zero-wh 修复生效 | 重启后建新 harness session，检查 CTX_SNAPSHOT 中 user 节点 w/h |
| 🔜 下一步 | 多 tool_call 400 验证 | 构造并发 create_node 场景测试 normalize 拆分 |
| 🛑 禁止 | 新增 `find_nodes` 工具 | gs_text 已全量提供节点信息，除非实测失败 |
| 🛑 禁止 | 修改 BI 加载路径 | 不改 `_fetch_from_external`、不改 prj_type |
| 🛑 禁止 | 回滚任何 P0 修复 | _safe_pos_float、_normalize_tool_call_ids、防线 A/B |
| ❓ 疑问 | 部署后是否需要旧 session 清理 | 旧 session 中的 w=0 节点需跑一次 fit_container 触发自动修正 |
