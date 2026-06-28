# 05_DANGER_ZONES

> 当前为候选清单，不是最终定稿。按来源分成：注释信号、异常处理厚块、分支复杂函数。

## A. 注释 / TODO / FIXME 候选

| 候选点 | 文件位置 | 观察 |
|---|---|---|
| 简道云字段映射里仍有占位 `TODO: 待补全` | `backend/app/config/jiandaoyun_field_mapping.json:52` | `allowed_values` 仍是占位值，说明映射/枚举约束可能未完成。 |
| 简道云字段映射里仍有占位 `TODO: 待补全` | `backend/app/config/jiandaoyun_field_mapping.json:60` | 同上，容易让写回校验和前端选项不一致。 |
| compare mock 仍写着“替换为简道云真实调用” | `backend/app/services/tool_registry.py:343` | 说明某段比对链路仍可能混有 mock 逻辑或历史兼容逻辑。 |
| Power Map chat_v2 里浏览器全局单例优化未做 | `backend/app/services/power_map_service.py:9670` | 明确指向吞吐/资源占用问题。 |
| Power Map chat_v2 里浏览器全局单例优化未做 | `backend/app/services/power_map_service.py:9678` | 同一风险的中文注释，说明这里是已知性能热点。 |
| startup 的 sandbox 清单校验是 warn-only | `backend/app/main.py:826` | 启动时资源缺失不会阻塞，适合排查“运行后才坏”的问题。 |

## B. 异常处理特别厚的函数

| 函数 | 文件位置 | try/except 数量 | 观察 |
|---|---|---:|---|
| `chat_power_map_v2` | `backend/app/services/power_map_service.py:9583` | 9 | SSE、Playwright、LLM、sandbox 会话都叠在一起，失败模式很多。 |
| `_run_llm_tool_loop` | `backend/app/services/power_map_service.py:7875` | 8 | Power Map 的工具循环核心，异常路径多。 |
| `_execute_harness_tool` | `backend/app/services/power_map_service.py:7079` | 7 | 工具执行层，输入/输出/状态收敛复杂。 |
| `_execute_harness` | `backend/app/services/power_map_service.py:7340` | 6 | harness 主线较厚，值得重点盯。 |
| `async_efficiency_review` | `backend/app/services/efficiency_review.py:179` | 6 | review 旁路能力，失败时可能很难判断是模型、I/O 还是数据问题。 |
| `_execute_harness_stream` | `backend/app/services/power_map_service.py:8432` | 5 | 流式执行链路，和前端卡死/半断流类问题相关。 |
| `messages_create_with_history_stream` | `backend/app/services/openai_compatible_agent_client.py:363` | 4 | OpenAI-compatible 流式 client 适合作为 API 兼容问题候选。 |
| `run_analysis_pipeline` | `backend/app/services/analysis_pipeline.py:31` | 4 | transcripts 主链路后台任务，覆盖提取/比对两阶段。 |
| `power_map_sandbox` | `backend/app/main.py:3125` | 3 | sandbox 页面注入与代理混在一起，排查渲染问题时要看。 |
| `transcript_progress` | `backend/app/main.py:3427` | 3 | 额外自己开 `SessionLocal`，进度接口容易出边界问题。 |

## C. if/elif 分支特别多的函数

| 函数 | 文件位置 | If 数量 | 观察 |
|---|---|---:|---|
| `_execute_harness_tool` | `backend/app/services/power_map_service.py:7079` | 50 | 非常像“路由器型函数”，后续改动很容易牵一发而动全身。 |
| `_apply_delta` | `backend/app/services/power_map_service.py:911` | 46 | Power Map 变更应用核心，几乎必然是高风险区。 |
| `_run_llm_tool_loop` | `backend/app/services/power_map_service.py:7875` | 30 | LLM 工具循环本身就复杂，分支数进一步抬高维护成本。 |
| `_tool_get_node_by_visual_reference` | `backend/app/services/power_map_service.py:4866` | 25 | 视觉引用解析逻辑重，容易出模糊匹配问题。 |
| `_local_layout` | `backend/app/services/power_map_service.py:1710` | 24 | 布局规则集很重，和“改一点动全图”类问题相关。 |
| `chat` | `backend/app/main.py:2683` | 24 | chat 路由本身承担了较多编排职责。 |
| `_tool_relayout` | `backend/app/services/power_map_service.py:5162` | 23 | 局部重排工具复杂度高。 |
| `execute_cards` | `backend/app/services/operation_executor.py:44` | 21 | 简道云写回主线，符合“高价值高风险”特征。 |
| `customers_list` | `backend/app/main.py:1791` | 21 | 缓存、搜索、刷新逻辑混在一个入口。 |
| `submit_review` | `backend/app/main.py:3686` | 20 | review 提交链路较厚，适合作为跟进记录写回重点风险区。 |
| `_normalize_edges` | `backend/app/services/power_map_service.py:5016` | 18 | 图边标准化逻辑复杂。 |
| `_fetch_from_external` | `backend/app/services/power_map_service.py:8568` | 15 | 外部 BI/远端抓取层，易受上游返回变化影响。 |
| `exec_compare_ops_llm` | `backend/app/services/tool_registry.py:387` | 14 | 比对阶段规则 + LLM 输出收敛点。 |
| `execute_operations` | `backend/app/main.py:2572` | 14 | 审核通过后的执行总入口。 |
| `_resolve_field_rule` | `backend/app/services/tool_registry.py:78` | 13 | 字段安全/映射判定基础函数。 |
| `generate_review` | `backend/app/main.py:3571` | 10 | review 生成入口承担数据适配和模型编排。 |
| `refresh_customer_index_cache` | `backend/app/main.py:640` | 10 | 缓存刷新逻辑复杂，和“客户搜不到/延迟出现”问题相关。 |

## D. 结合项目说明的优先怀疑区

| 候选点 | 文件位置 | 观察 |
|---|---|---|
| `OPERATION_CARD_STORE` 内存态 | `backend/app/main.py:2494`, `backend/app/main.py:2575` | 审核卡片和执行都依赖内存，重启即丢。 |
| `transcript_progress` 自开 DB session | `backend/app/main.py:3427` | 没走标准依赖注入路径，值得单独盯。 |
| review / followup 双入口复用 | `backend/app/main.py:3890`, `backend/app/main.py:3894` | `followup_generate/submit` 直接转调 `generate_review/submit_review`，后续需求分叉时容易互相影响。 |
| Power Map sandbox 与 mock BI 接口耦合 | `backend/app/main.py:3124`, `backend/app/main.py:3202`, `backend/app/main.py:3308` | 本地预览、代理、mock 返回形状绑定较深。 |
| Power Map 服务过大 | `backend/app/services/power_map_service.py` | 8484 行，且同时命中 TODO / 高异常密度 / 高分支密度三类信号。 |

## 建议你优先裁决的候选

1. `backend/app/services/power_map_service.py`
2. `backend/app/main.py` 中 `chat` / `execute_operations` / `generate_review` / `submit_review`
3. `backend/app/services/operation_executor.py`
4. `backend/app/services/tool_registry.py`
5. `backend/app/config/jiandaoyun_field_mapping.json`
