from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from scripts.generate_test_cases import DEFAULT_COMPANY_ID, DEFAULT_OUTPUT as CASE_OUTPUT_PATH
from scripts.generate_test_cases import load_llm_config
from scripts.generate_test_cases import main as generate_cases_main

OUTPUT_DIR = Path(__file__).resolve().parent / "output"
DEFAULT_REPORT_PATH = OUTPUT_DIR / "agent_quality_report.json"
DEFAULT_INPUT_PATH = CASE_OUTPUT_PATH

PROMPT_OPTIMIZE_TEMPLATE = """以下是 Agent 提取+聚合的质量评测报告，总分 {overall_score}。
主要问题：{top_issues}
具体失败 case 示例：{worst_case_detail}

请根据这些问题，给出对 EXTRACTION_SYSTEM_PROMPT 和 CHAT_SYSTEM_PROMPT 的具体修改建议。
要求：
1. 针对每个问题给出修改位置和修改内容
2. 不改变 Tool Schema，只调整提示词文本
3. 保留现有的三段式格式要求和字段规范
4. 给出修改后预期改善的效果
"""

WEIGHTS = {
    "expectations_count": 0.15,
    "scenarios_count": 0.15,
    "title_recall": 0.20,
    "yuqi_brief_recall": 0.10,
    "noise_filtering": 0.15,
    "card_structure": 0.10,
    "expectation_quality": 0.075,
    "scenario_quality": 0.075,
}

CURRENT_STATE_KEYWORDS = ["现状", "目前", "当前", "现在", "一直在", "每次都", "过去"]
PAIN_POINT_KEYWORDS = ["痛点", "问题", "困难", "挑战", "瓶颈", "不满", "低效", "耗时", "无法", "难以", "不能", "缺乏"]
SOLUTION_KEYWORDS = ["方案", "目标", "期望", "希望", "实现", "建设", "构建", "打造", "搭建", "优化", "提升"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Batch quality test for extraction+comparison agent.")
    parser.add_argument("--input", default=str(DEFAULT_INPUT_PATH))
    parser.add_argument("--output", default=str(DEFAULT_REPORT_PATH))
    parser.add_argument("--model", default=(os.getenv("LLM_MODEL") or os.getenv("AGENT_A_MODEL") or "").strip())
    parser.add_argument("--api-base", default=(os.getenv("AGENT_API_BASE") or "http://127.0.0.1:8000").rstrip("/"))
    parser.add_argument("--token", default=(os.getenv("AGENT_TEST_TOKEN") or "").strip())
    parser.add_argument("--username", default=(os.getenv("SUPERADMIN_USERNAME") or "").strip())
    parser.add_argument("--password", default=(os.getenv("SUPERADMIN_PASSWORD") or "").strip())
    parser.add_argument("--sleep-seconds", type=float, default=5.0)
    parser.add_argument("--iterate", action="store_true")
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--reuse-cases", action="store_true", help="In iterate mode, reuse existing case file.")
    parser.add_argument("--generate-count", type=int, default=6)
    parser.add_argument("--generate-difficulties", default="simple,medium,complex")
    parser.add_argument("--min-length", type=int, default=2000)
    parser.add_argument("--max-length", type=int, default=8000)
    parser.add_argument("--suggest-from-report", default="", help="Only generate prompt suggestion from an existing report JSON.")
    parser.add_argument("--suggest-output", default="", help="Output path for suggestion markdown.")
    return parser.parse_args()


def _ensure_output_dir() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def _sim(a: str, b: str) -> float:
    return SequenceMatcher(None, (a or "").strip(), (b or "").strip()).ratio()


def _count_score(expected: int, actual: int) -> float:
    gap = abs(int(expected) - int(actual))
    if gap <= 1:
        return 1.0
    if gap == 2:
        return 0.5
    return 0.0


def _extract_change_items(card: dict[str, Any]) -> list[dict[str, Any]]:
    items = list(card.get("change_items") or [])
    if not items and card.get("field_name"):
        items = [
            {
                "field_name": card.get("field_name"),
                "new_value": card.get("new_value"),
            }
        ]
    return [it for it in items if isinstance(it, dict)]


def _extract_card_text_pool(card: dict[str, Any]) -> list[str]:
    texts: list[str] = []
    for key in ("title", "detail_brief", "detail", "summary"):
        value = card.get(key)
        if isinstance(value, str) and value.strip():
            texts.append(value.strip())
    for item in _extract_change_items(card):
        field_name = str(item.get("field_name") or "")
        value = item.get("new_value")
        if isinstance(value, str) and value.strip():
            texts.append(value.strip())
        if isinstance(value, (int, float)):
            texts.append(str(value))
        if field_name:
            texts.append(field_name)
    return texts


def _is_expectation_card(card: dict[str, Any]) -> bool:
    target = str(card.get("target_form") or "")
    return "预期" in target or target.lower() in {"expectation", "expectation_form"}


def _is_scenario_card(card: dict[str, Any]) -> bool:
    target = str(card.get("target_form") or "")
    return "场景" in target or target.lower() in {"scenario", "scenario_form"}


def _best_match(query: str, candidates: list[str]) -> tuple[float, str]:
    best_score = 0.0
    best_text = ""
    for text in candidates:
        score = _sim(query, text)
        if score > best_score:
            best_score = score
            best_text = text
    return best_score, best_text


def _evaluate_title_recall(
    expected_titles: list[str], cards: list[dict[str, Any]], threshold: float = 0.6
) -> tuple[float, list[str]]:
    if not expected_titles:
        return 1.0, []
    pool: list[str] = []
    for card in cards:
        pool.extend(_extract_card_text_pool(card))
    matched: list[str] = []
    for title in expected_titles:
        score, _ = _best_match(title, pool)
        if score > threshold:
            matched.append(title)
    return len(matched) / len(expected_titles), matched


def _evaluate_noise_filter(expected_noises: list[str], cards: list[dict[str, Any]]) -> tuple[float, list[str]]:
    if not expected_noises:
        return 1.0, []
    pool: list[str] = []
    for card in cards:
        pool.extend(_extract_card_text_pool(card))
    leaked: list[str] = []
    for noise in expected_noises:
        score, best = _best_match(noise, pool)
        if score > 0.6 or noise in best:
            leaked.append(noise)
    clean_ratio = (len(expected_noises) - len(leaked)) / len(expected_noises)
    return clean_ratio, leaked


def _evaluate_structure(cards: list[dict[str, Any]]) -> tuple[float, list[str]]:
    if not cards:
        return 1.0, []
    valid_count = 0
    errors: list[str] = []
    for idx, card in enumerate(cards):
        ok = True
        operation = str(card.get("operation_type") or card.get("operation") or "").lower()
        data_id = card.get("data_id")
        items = _extract_change_items(card)
        fields = [str(it.get("field_name") or "") for it in items if it.get("field_name")]
        if len(fields) != len(set(fields)):
            ok = False
            errors.append(f"card[{idx}] change_items 存在重复 field_name")
        if operation == "create" and str(data_id or "").strip():
            ok = False
            errors.append(f"card[{idx}] create 操作 data_id 非空")
        if ok:
            valid_count += 1
    return valid_count / len(cards), errors


def _extract_field_value(card: dict[str, Any], keywords: tuple[str, ...]) -> str:
    for item in _extract_change_items(card):
        field_name = str(item.get("field_name") or "")
        if any(k in field_name for k in keywords):
            value = item.get("new_value")
            if isinstance(value, str):
                return value
            if value is not None:
                return json.dumps(value, ensure_ascii=False)
    for key in ("detail", "solve_what_ques", "solve_what_ans"):
        value = card.get(key)
        if isinstance(value, str):
            return value
    return ""


def _evaluate_expectation_quality(cards: list[dict[str, Any]]) -> tuple[float, list[str]]:
    exp_cards = [c for c in cards if _is_expectation_card(c)]
    if not exp_cards:
        return 0.0, ["未识别出预期卡片，无法评估预期内容质量"]
    passed = 0
    issues: list[str] = []
    for idx, card in enumerate(exp_cards):
        detail = _extract_field_value(card, ("预期详情", "预期描述", "detail"))
        has_bg = "预期背景" in detail or "背景" in detail
        has_need = "预期需求" in detail or "需求" in detail
        has_state = "达成状态" in detail or "输出物" in detail or "状态" in detail
        if has_bg and has_need and has_state:
            passed += 1
        else:
            issues.append(f"预期卡[{idx}] detail 缺少背景/需求/达成状态要素")
    return passed / len(exp_cards), issues


def check_scenario_quality(solve_what_ques: str, solve_what_ans: str) -> tuple[bool, list[str], bool]:
    issues: list[str] = []
    has_current = any(kw in solve_what_ques for kw in CURRENT_STATE_KEYWORDS)
    has_pain = any(kw in solve_what_ques for kw in PAIN_POINT_KEYWORDS)
    has_solution = any(kw in (solve_what_ques + solve_what_ans) for kw in SOLUTION_KEYWORDS)

    if not has_current:
        issues.append("缺少现状描述")
    if not has_pain:
        issues.append("缺少痛点描述")
    if not has_solution:
        issues.append("缺少方案/目标描述")

    # 长度兜底：关键词可能没命中，但内容仍然充实
    content_rich = len(solve_what_ques) > 80 and len(solve_what_ans) > 100

    # 允许缺一个要素仍算通过
    passed = len(issues) <= 1
    return passed, issues, content_rich


def _evaluate_scenario_quality(cards: list[dict[str, Any]]) -> tuple[float, list[str]]:
    sc_cards = [c for c in cards if _is_scenario_card(c)]
    if not sc_cards:
        return 0.0, ["未识别出场景卡片，无法评估场景内容质量"]
    score_total = 0.0
    issues: list[str] = []
    for idx, card in enumerate(sc_cards):
        ques = _extract_field_value(card, ("解决什么问题", "业务诉求", "痛点", "solve_what_ques"))
        ans = _extract_field_value(card, ("怎样解决", "解决方案", "核心指标", "solve_what_ans"))
        passed, card_issues, content_rich = check_scenario_quality(ques or "", ans or "")
        if passed:
            score_total += 1.0
        elif content_rich:
            score_total += 0.5
            issues.append(f"场景卡[{idx}] 要素命中不足但文本较充实（按0.5计分）: {'、'.join(card_issues)}")
        else:
            issues.append(f"场景卡[{idx}] 结构不完整（现状/痛点/方案要素不足）: {'、'.join(card_issues)}")
    return score_total / len(sc_cards), issues


def _cards_summary(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for idx, card in enumerate(cards):
        items = _extract_change_items(card)
        result.append(
            {
                "card_index": idx,
                "target_form": card.get("target_form"),
                "operation": card.get("operation_type") or card.get("operation"),
                "primary_field": (items[0].get("field_name") if items else None),
            }
        )
    return result


def _calc_case_result(case: dict[str, Any], cards: list[dict[str, Any]]) -> dict[str, Any]:
    expected = case.get("expected", {}) or {}
    expected_exp_count = int(expected.get("expectations_count") or 0)
    expected_sc_count = int(expected.get("scenarios_count") or 0)

    exp_cards = [c for c in cards if _is_expectation_card(c)]
    sc_cards = [c for c in cards if _is_scenario_card(c)]
    actual_exp_count = len(exp_cards)
    actual_sc_count = len(sc_cards)

    title_score, title_matched = _evaluate_title_recall(list(expected.get("should_contain_titles") or []), cards)
    yuqi_score, yuqi_matched = _evaluate_title_recall(
        list(expected.get("should_contain_yuqi_briefs") or []), exp_cards, threshold=0.5
    )
    noise_score, leaked_noises = _evaluate_noise_filter(list(expected.get("should_not_contain") or []), cards)
    structure_score, structure_issues = _evaluate_structure(cards)
    exp_quality_score, exp_quality_issues = _evaluate_expectation_quality(cards)
    sc_quality_score, sc_quality_issues = _evaluate_scenario_quality(cards)

    dimensions = {
        "expectations_count": {
            "expected": expected_exp_count,
            "actual": actual_exp_count,
            "score": _count_score(expected_exp_count, actual_exp_count),
        },
        "scenarios_count": {
            "expected": expected_sc_count,
            "actual": actual_sc_count,
            "score": _count_score(expected_sc_count, actual_sc_count),
        },
        "title_recall": {
            "expected": list(expected.get("should_contain_titles") or []),
            "matched": title_matched,
            "score": title_score,
        },
        "yuqi_brief_recall": {
            "expected": list(expected.get("should_contain_yuqi_briefs") or []),
            "matched": yuqi_matched,
            "score": yuqi_score,
        },
        "noise_filtering": {
            "expected": list(expected.get("should_not_contain") or []),
            "leaked": leaked_noises,
            "score": noise_score,
        },
        "card_structure": {
            "issues": structure_issues,
            "score": structure_score,
        },
        "expectation_quality": {
            "issues": exp_quality_issues,
            "score": exp_quality_score,
        },
        "scenario_quality": {
            "issues": sc_quality_issues,
            "score": sc_quality_score,
        },
    }

    weighted_score = 0.0
    for name, weight in WEIGHTS.items():
        weighted_score += float(dimensions[name]["score"]) * weight

    issues: list[str] = []
    if dimensions["expectations_count"]["score"] < 1:
        issues.append("预期数量偏差")
    if dimensions["scenarios_count"]["score"] < 1:
        issues.append("场景数量偏差")
    if dimensions["title_recall"]["score"] < 1:
        issues.append("场景遗漏")
    if dimensions["yuqi_brief_recall"]["score"] < 1:
        issues.append("预期召回不足")
    if dimensions["noise_filtering"]["score"] < 1:
        issues.append("干扰项误识别")
    if dimensions["card_structure"]["score"] < 1:
        issues.append("卡片结构不合规")
    if dimensions["expectation_quality"]["score"] < 1:
        issues.append("预期内容质量不足")
    if dimensions["scenario_quality"]["score"] < 1:
        issues.append("场景内容质量不足")

    return {
        "case_id": case.get("case_id"),
        "score": round(weighted_score, 4),
        "dimensions": dimensions,
        "issues": issues,
        "cards_summary": _cards_summary(cards),
    }


async def _login_and_get_token(client: httpx.AsyncClient, api_base: str, username: str, password: str) -> str:
    if not username or not password:
        raise ValueError("未提供 AGENT_TEST_TOKEN，且缺少 SUPERADMIN_USERNAME/SUPERADMIN_PASSWORD。")
    resp = await client.post(f"{api_base}/api/v1/auth/login", json={"username": username, "password": password})
    resp.raise_for_status()
    token = (resp.json() or {}).get("token", "")
    if not token:
        raise ValueError("登录成功但未返回 token")
    return token


async def _run_case(
    client: httpx.AsyncClient,
    api_base: str,
    token: str,
    case: dict[str, Any],
) -> dict[str, Any]:
    transcript_id = f"qa-{case.get('case_id', uuid4())}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    extraction_payload = {
        "task_id": f"ext-{transcript_id}",
        "transcript_id": transcript_id,
        "input_type": "text",
        "content": case.get("input_text", ""),
        "transcript": {
            "id": transcript_id,
            "company_name_hint": case.get("company_name", "测试公司"),
            "raw_text": case.get("input_text", ""),
        },
    }
    ext_resp = await client.post(f"{api_base}/api/v1/agent/extraction/task", headers=headers, json=extraction_payload)
    ext_resp.raise_for_status()
    ext_json = ext_resp.json()
    facts = ((ext_json.get("result") or {}).get("facts")) or []

    cmp_payload = {
        "task_id": f"cmp-{transcript_id}",
        "transcript_id": transcript_id,
        "company_id": case.get("company_id") or DEFAULT_COMPANY_ID,
        "existing_record": {
            "company_id": case.get("company_id") or DEFAULT_COMPANY_ID,
            "company_name": case.get("company_name", "测试公司"),
        },
        "extraction_result": {"facts": facts},
    }
    cmp_resp = await client.post(f"{api_base}/api/v1/agent/comparison/task", headers=headers, json=cmp_payload)
    cmp_resp.raise_for_status()
    cmp_json = cmp_resp.json()
    cards = list(cmp_json.get("cards_with_safety") or ((cmp_json.get("result") or {}).get("operation_cards")) or [])
    return {
        "facts": facts,
        "cards": cards,
        "raw_extraction": ext_json,
        "raw_comparison": cmp_json,
    }


def _print_report_summary(report: dict[str, Any]) -> None:
    print("\n===== Agent Quality Summary =====")
    print(f"run_time: {report['run_time']}")
    print(f"model_used: {report.get('model_used')}")
    print(f"total_cases: {report['total_cases']}")
    print(f"overall_score: {report['overall_score']:.4f}")
    print("---------------------------------")
    print(f"{'case_id':<22} {'score':<8} {'issues'}")
    for row in report.get("results", []):
        issues = "、".join(row.get("issues", [])) or "-"
        print(f"{str(row.get('case_id')):<22} {float(row.get('score', 0)):<8.4f} {issues}")
    print("---------------------------------")
    print("Top issues:")
    for item in report.get("top_issues", []):
        print(f"- {item['issue']}: {item['frequency']} ({','.join(item['affected_cases'])})")


def _build_top_issues(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issue_cases: dict[str, list[str]] = defaultdict(list)
    for row in results:
        case_id = str(row.get("case_id"))
        for issue in row.get("issues", []):
            issue_cases[issue].append(case_id)
    counter = Counter({k: len(v) for k, v in issue_cases.items()})
    top = []
    for issue, freq in counter.most_common(10):
        top.append({"issue": issue, "frequency": freq, "affected_cases": issue_cases.get(issue, [])})
    return top


async def evaluate_cases(args: argparse.Namespace, input_path: Path, output_path: Path) -> dict[str, Any]:
    cases_doc = json.loads(input_path.read_text(encoding="utf-8"))
    cases = list(cases_doc.get("cases") or [])
    if not cases:
        raise ValueError(f"测试输入为空: {input_path}")

    token = args.token
    async with httpx.AsyncClient(timeout=httpx.Timeout(300.0)) as client:
        if not token:
            token = await _login_and_get_token(client, args.api_base, args.username, args.password)

        results: list[dict[str, Any]] = []
        for idx, case in enumerate(cases):
            try:
                run_data = await _run_case(client, args.api_base, token, case)
                case_result = _calc_case_result(case, run_data["cards"])
                results.append(case_result)
                print(f"[{idx + 1}/{len(cases)}] 完成: {case.get('case_id')} score={case_result['score']:.4f}")
            except Exception as exc:
                fail_result = {
                    "case_id": case.get("case_id"),
                    "score": 0.0,
                    "dimensions": {},
                    "issues": [f"执行失败: {exc}"],
                    "cards_summary": [],
                }
                results.append(fail_result)
                print(f"[{idx + 1}/{len(cases)}] 失败: {case.get('case_id')} {exc}")
            if idx < len(cases) - 1:
                await asyncio.sleep(max(0.0, float(args.sleep_seconds)))

    overall_score = sum(float(r.get("score", 0.0)) for r in results) / len(results)
    report = {
        "run_time": datetime.now(timezone.utc).isoformat(),
        "model_used": cases_doc.get("model_used") or "",
        "total_cases": len(cases),
        "results": results,
        "overall_score": round(overall_score, 4),
        "top_issues": _build_top_issues(results),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    _print_report_summary(report)
    return report


async def _llm_suggest(
    llm_cfg: dict[str, str],
    report: dict[str, Any],
    out_path: Path,
) -> None:
    worst_case = min(report.get("results", []), key=lambda x: float(x.get("score", 0.0)), default={})
    prompt = PROMPT_OPTIMIZE_TEMPLATE.format(
        overall_score=report.get("overall_score"),
        top_issues=json.dumps(report.get("top_issues", []), ensure_ascii=False),
        worst_case_detail=json.dumps(worst_case, ensure_ascii=False),
    )
    payload = {
        "model": llm_cfg["model"],
        "messages": [
            {"role": "system", "content": "你是提示词优化专家。请给出可执行、可落地的修改建议。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.3,
    }
    last_err: Exception | None = None
    for attempt in range(1, 4):
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(240.0)) as client:
                resp = await client.post(
                    f"{llm_cfg['base_url']}/chat/completions",
                    headers={"Authorization": f"Bearer {llm_cfg['api_key']}", "Content-Type": "application/json"},
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
                content = (((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
            out_path.write_text(content + "\n", encoding="utf-8")
            return
        except Exception as exc:
            last_err = exc
            if attempt < 3:
                await asyncio.sleep(3 * attempt)
    raise RuntimeError(f"生成 prompt 建议失败: {last_err}")


async def _generate_cases_via_subprocess_style(args: argparse.Namespace) -> None:
    # Reuse generate script internals by temporarily patching sys.argv-like parameters via env/CLI behavior.
    os.environ["LLM_PROVIDER"] = os.getenv("LLM_PROVIDER", "")
    argv = [
        "generate_test_cases.py",
        "--count",
        str(args.generate_count),
        "--difficulties",
        args.generate_difficulties,
        "--min-length",
        str(args.min_length),
        "--max-length",
        str(args.max_length),
        "--output",
        str(DEFAULT_INPUT_PATH),
    ]
    if args.model.strip():
        argv.extend(["--model", args.model.strip()])
    import sys

    old_argv = sys.argv
    try:
        sys.argv = argv
        await generate_cases_main()
    finally:
        sys.argv = old_argv


async def run_iteration(args: argparse.Namespace) -> None:
    llm_cfg = load_llm_config(
        argparse.Namespace(
            provider=(os.getenv("LLM_PROVIDER") or "").strip(),
            base_url=(os.getenv("LLM_BASE_URL") or "").strip(),
            model=(args.model or os.getenv("LLM_MODEL") or os.getenv("AGENT_A_MODEL") or "").strip(),
            api_key=(os.getenv("LLM_API_KEY") or "").strip(),
        )
    )
    for round_idx in range(1, args.rounds + 1):
        print(f"\n========== Round {round_idx}/{args.rounds} ==========")
        if (not args.reuse_cases) or (not DEFAULT_INPUT_PATH.exists()):
            await _generate_cases_via_subprocess_style(args)
        round_report_path = OUTPUT_DIR / f"agent_quality_round_{round_idx}.json"
        report = await evaluate_cases(args, DEFAULT_INPUT_PATH, round_report_path)
        suggestion_path = OUTPUT_DIR / f"prompt_suggestion_round_{round_idx}.md"
        try:
            await _llm_suggest(llm_cfg, report, suggestion_path)
        except Exception as exc:
            suggestion_path.write_text(f"# Prompt Suggestion Round {round_idx}\n\n生成失败：{exc}\n", encoding="utf-8")
            print(f"prompt suggestion failed (round {round_idx}): {exc}")
        print(f"round report: {round_report_path}")
        print(f"prompt suggestion: {suggestion_path}")


async def main() -> None:
    args = parse_args()
    _ensure_output_dir()
    if args.suggest_from_report:
        report_path = Path(args.suggest_from_report).resolve()
        if not report_path.exists():
            raise SystemExit(f"报告文件不存在: {report_path}")
        suggest_output = (
            Path(args.suggest_output).resolve()
            if args.suggest_output.strip()
            else (OUTPUT_DIR / f"prompt_suggestion_{report_path.stem}.md")
        )
        await generate_suggestion_from_report(report_path, suggest_output)
        return

    if args.iterate:
        if args.rounds <= 0:
            raise SystemExit("--rounds 必须大于 0")
        await run_iteration(args)
        return

    input_path = Path(args.input).resolve()
    output_path = Path(args.output).resolve()
    report = await evaluate_cases(args, input_path, output_path)
    print(f"\n报告输出: {output_path}")
    print(f"overall_score={report['overall_score']:.4f}")


async def generate_suggestion_from_report(report_path: Path, suggestion_path: Path) -> None:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    args = parse_args()
    llm_cfg = load_llm_config(
        argparse.Namespace(
            provider=(os.getenv("LLM_PROVIDER") or "").strip(),
            base_url=(os.getenv("LLM_BASE_URL") or "").strip(),
            model=(args.model or os.getenv("LLM_MODEL") or os.getenv("AGENT_A_MODEL") or "").strip(),
            api_key=(os.getenv("LLM_API_KEY") or "").strip(),
        )
    )
    try:
        await _llm_suggest(llm_cfg, report, suggestion_path)
        print(f"prompt suggestion: {suggestion_path}")
    except Exception as exc:
        suggestion_path.write_text(f"# Prompt Suggestion\n\n生成失败：{exc}\n", encoding="utf-8")
        print(f"prompt suggestion failed: {exc}")


if __name__ == "__main__":
    asyncio.run(main())
