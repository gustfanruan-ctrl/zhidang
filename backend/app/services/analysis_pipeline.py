"""
后台分析管道：在 asyncio.create_task 中运行提取+比对全流程。
创建独立 DB session，结果持久化到 Transcript.agent_a_result / agent_b_result。
"""
from __future__ import annotations

import logging
from typing import Any

from ..database import SessionLocal
from ..models import FollowupRecord, Transcript, SystemConfig

logger = logging.getLogger("zhidang.pipeline")


async def run_analysis_pipeline(transcript_id: str, source_type: str = "transcript") -> None:
    """后台运行提取→比对全流程，结果写入 DB。source_type ∈ {"transcript","followup"}。"""
    # 延迟导入避免循环依赖（main 模块在 app 启动后才完整加载）
    from ..main import (  # noqa: E402
        TASK_PROGRESS, OPERATION_CARD_STORE, _append_llm_line,
        ensure_system_config, run_extraction_task, get_jiandaoyun_runtime_config,
        _get_llm_runtime_config, get_executors, check_operation_cards,
        validate_comparison_output, hash_company_id, emit_event,
        _format_exc,
    )
    from ..schemas import AgentExtractionPayload

    Model = FollowupRecord if source_type == "followup" else Transcript

    db = SessionLocal()
    try:
        transcript = db.get(Model, transcript_id)
        if not transcript:
            logger.error("%s %s not found", source_type, transcript_id)
            return

        cfg = ensure_system_config(db)

        # ── Phase 1: 提取 ──
        transcript.status = "extracting"
        db.commit()

        TASK_PROGRESS[transcript_id] = {
            "mode": "llm",
            "input_type": transcript.input_type,
            "current_turn": 0,
            "max_turns": 8,
            "extraction_status": "processing",
            "comparison_status": "pending",
            "llm_lines": [],
        }
        _append_llm_line(transcript_id, "后台分析已启动")

        try:
            payload = AgentExtractionPayload(
                transcript_id=transcript_id,
                input_type=transcript.input_type or "text",
                content=transcript.raw_text,
                images=[],
                transcript={"id": transcript_id, "raw_text": transcript.raw_text},
            )
            result = await run_extraction_task(payload, cfg)
            transcript.agent_a_result = result
            transcript.status = "extraction_done"
            db.commit()
            _append_llm_line(transcript_id, "提取完成，结果已保存")
        except Exception as exc:
            logger.exception("Extraction failed for %s", transcript_id)
            transcript.status = "error"
            transcript.agent_a_result = {"error": str(exc), "phase": "extraction"}
            db.commit()
            TASK_PROGRESS.setdefault(transcript_id, {}).update({"extraction_status": "error"})
            _append_llm_line(transcript_id, f"提取失败：{_format_exc(exc)}")
            return

        # ── Phase 2: 比对 ──
        transcript.status = "comparing"
        db.commit()

        TASK_PROGRESS.setdefault(transcript_id, {}).update({"comparison_status": "processing"})
        _append_llm_line(transcript_id, "进入比对阶段：生成操作卡片")

        try:
            extraction_result = result.get("result", {})
            company_id = transcript.company_id or "demo"
            company_name = transcript.company_name or ""

            runtime_cfg = get_jiandaoyun_runtime_config(cfg)
            llm_cfg = _get_llm_runtime_config(cfg)

            # 拉取简道云客户档案
            executors = get_executors("comparison")
            profile = await executors["fetch_customer_profile"](
                {
                    "company_id": company_id,
                    "company_name": company_name,
                    "runtime_cfg": runtime_cfg,
                }
            )

            # 比对生成操作卡片
            compare_result = await executors["compare_and_generate_operations"](
                {
                    "extracted_facts": extraction_result.get("facts", []),
                    "existing_profile": profile,
                    "runtime_cfg": runtime_cfg,
                    "llm_cfg": llm_cfg,
                    "agent_b_prompt": cfg.agent_b_prompt,
                }
            )

            # 安全校验
            cfg_mapping = (cfg.field_mappings or {}).get("jiandaoyun", {})
            forms_cfg = (cfg_mapping.get("forms") or {})
            enhanced_cards: list[dict[str, Any]] = []
            for card in compare_result.get("operation_cards", []):
                target_form = str(card.get("target_form") or "未知")
                form_cfg = forms_cfg.get(target_form, {})
                safe_card = check_operation_cards([card], form_cfg)[0] if form_cfg else {
                    **card, "safety_status": "unknown", "safety_reason": "form mapping missing"
                }
                enhanced_cards.append(safe_card)
            compare_result["operation_cards"] = enhanced_cards
            compare_result["total"] = len(enhanced_cards)
            compare_result = validate_comparison_output(compare_result)
            compare_result["company_id"] = profile.get("_id")

            # 持久化到 DB
            full_result = {
                "result": compare_result,
                "status": "completed",
                "mode": "fallback" if profile.get("_mock") else "llm",
            }
            transcript.agent_b_result = full_result
            transcript.status = "comparison_done"
            db.commit()

            # 加载到内存供审核端点使用
            OPERATION_CARD_STORE[transcript_id] = [
                dict(card) for card in compare_result.get("operation_cards", [])
            ]

            TASK_PROGRESS.setdefault(transcript_id, {}).update({"comparison_status": "completed"})
            _append_llm_line(transcript_id, "比对完成：已生成审核卡片")

        except Exception as exc:
            logger.exception("Comparison failed for %s", transcript_id)
            transcript.status = "error"
            transcript.agent_b_result = {"error": str(exc), "phase": "comparison"}
            db.commit()
            TASK_PROGRESS.setdefault(transcript_id, {}).update({"comparison_status": "error"})
            _append_llm_line(transcript_id, f"比对失败：{_format_exc(exc)}")

    except Exception as exc:
        logger.exception("Pipeline fatal error for %s", transcript_id)
        try:
            transcript = db.get(Transcript, transcript_id)
            if transcript:
                transcript.status = "error"
                transcript.agent_a_result = transcript.agent_a_result or {}
                transcript.agent_a_result["pipeline_error"] = str(exc)
                db.commit()
        except Exception:
            pass
    finally:
        db.close()
