from __future__ import annotations

import argparse
import asyncio
import json
import os
import sqlite3
import time
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

SYSTEM_PROMPT = """你是一个测试数据生成器。根据给定的难度和场景类型，生成一段模拟的客户拜访会议转写文本，并附带标准答案。

要求：
1. 转写文本必须模拟真实会议风格：包含寒暄、跑题、技术讨论、多人发言（用"张三："格式标注说话人）
2. 文本中必须包含明确的客户预期（中长期目标/方向）和具体场景（可落地的功能/报表/看板）
3. 同时必须包含干扰信息（产品 bug 反馈、闲聊、与本次无关的话题），这些不应被识别为预期或场景
4. 预期和场景的信息应分散在文本各处，不集中出现
5. 每条预期应包含背景、需求、达成状态等要素
6. 每条场景应包含现状、痛点、目标、方案要素

输出 JSON 格式：
{
  "case_id": "auto_{difficulty}_{n}",
  "description": "一句话说明本 case 测试重点",
  "difficulty": "simple|medium|complex",
  "company_name": "虚构公司名",
  "company_id": "test_company_001",
  "input_text": "完整的转写文本（2000-8000字）",
  "expected": {
    "expectations_count": 数字,
    "scenarios_count": 数字,
    "should_contain_titles": ["场景标题1", "场景标题2"],
    "should_contain_yuqi_briefs": ["预期简述1"],
    "should_not_contain": ["不应识别为卡片的干扰项"],
    "notes": "本 case 的特殊测试意图说明"
  }
}
"""

DEFAULT_OUTPUT = Path(__file__).resolve().parent / "output" / "generated_test_cases.json"
DEFAULT_COMPANY_ID = "test_company_001"
DEFAULT_DIFFICULTIES = ["simple", "medium", "complex"]
DEFAULT_MIN_LENGTH = 2000
DEFAULT_MAX_LENGTH = 8000
DEFAULT_COUNT = 6


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate automated quality test cases with expected labels.")
    parser.add_argument("--count", type=int, default=DEFAULT_COUNT, help="Total number of cases.")
    parser.add_argument(
        "--difficulties",
        default="simple,medium,complex",
        help="Comma-separated difficulties, auto-evenly distributed.",
    )
    parser.add_argument("--min-length", type=int, default=DEFAULT_MIN_LENGTH)
    parser.add_argument("--max-length", type=int, default=DEFAULT_MAX_LENGTH)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--api-key", default=(os.getenv("LLM_API_KEY") or "").strip())
    parser.add_argument("--base-url", default=(os.getenv("LLM_BASE_URL") or "").strip())
    parser.add_argument(
        "--model",
        default=(os.getenv("LLM_MODEL") or os.getenv("AGENT_A_MODEL") or "").strip(),
    )
    parser.add_argument(
        "--provider",
        default=(os.getenv("LLM_PROVIDER") or "").strip(),
        help="Only openai-compatible providers are supported by this script.",
    )
    parser.add_argument("--sleep-seconds", type=float, default=5.0, help="Sleep between cases to avoid rate limit.")
    return parser.parse_args()


def _parse_env_file(env_path: Path) -> dict[str, str]:
    if not env_path.exists():
        return {}
    result: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip()] = value.strip().strip("'").strip('"')
    return result


def _sqlite_path_from_database_url(database_url: str) -> Path | None:
    if not database_url.startswith("sqlite:///"):
        return None
    raw = database_url.replace("sqlite:///", "", 1)
    path = Path(raw)
    if not path.is_absolute():
        path = (Path(__file__).resolve().parents[1] / path).resolve()
    return path


def _derive_aes_key(secret_seed: str) -> bytes:
    import hashlib

    return hashlib.sha256(secret_seed.encode("utf-8")).digest()


def _decrypt_secret(value: str | None, secret_seed: str) -> str:
    if not value:
        return ""
    if not value.startswith("aesgcm:"):
        return value
    import base64

    raw = base64.b64decode(value.split(":", 1)[1])
    nonce, ciphertext = raw[:12], raw[12:]
    aesgcm = AESGCM(_derive_aes_key(secret_seed))
    return aesgcm.decrypt(nonce, ciphertext, None).decode("utf-8")


def _load_config_from_system_config_table() -> dict[str, str]:
    backend_root = Path(__file__).resolve().parents[1]
    env_file = _parse_env_file(backend_root / ".env")
    database_url = os.getenv("DATABASE_URL") or env_file.get("DATABASE_URL") or "sqlite:///./zhidang.db"
    sqlite_path = _sqlite_path_from_database_url(database_url)
    if sqlite_path is None or (not sqlite_path.exists()):
        return {}

    jwt_secret = os.getenv("ZHIDANG_SECRET_KEY") or env_file.get("ZHIDANG_SECRET_KEY") or env_file.get("JWT_SECRET") or "change-me"
    conn = sqlite3.connect(str(sqlite_path))
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT llm_provider, llm_base_url, agent_a_model, llm_api_key_encrypted FROM system_config WHERE id = 1 LIMIT 1"
        )
        row = cur.fetchone()
        if not row:
            return {}
        provider, base_url, model_name, encrypted_key = row
        api_key = _decrypt_secret(encrypted_key, jwt_secret)
        return {
            "provider": (provider or "").strip(),
            "base_url": (base_url or "").strip(),
            "model": (model_name or "").strip(),
            "api_key": (api_key or "").strip(),
        }
    finally:
        conn.close()


def load_llm_config(args: argparse.Namespace) -> dict[str, str]:
    table_cfg = _load_config_from_system_config_table()
    provider = (args.provider or table_cfg.get("provider") or "openai_compatible").strip().lower()
    base_url = (args.base_url or table_cfg.get("base_url") or "").strip().rstrip("/")
    model = (args.model or table_cfg.get("model") or "").strip()
    api_key = (args.api_key or table_cfg.get("api_key") or "").strip()
    if provider not in {"openai_compatible", "dashscope"}:
        raise ValueError(f"不支持 provider={provider}，仅支持 openai_compatible/dashscope。")
    if not base_url:
        raise ValueError("未获取到 LLM base_url，请配置 system_config 或传入 --base-url。")
    if not model:
        raise ValueError("未获取到 LLM model，请配置 system_config 或传入 --model。")
    if not api_key:
        raise ValueError("未获取到 LLM API key，请配置环境变量 LLM_API_KEY 或 system_config。")
    return {
        "provider": provider,
        "base_url": base_url,
        "model": model,
        "api_key": api_key,
    }


def build_distribution(total: int, difficulties: Iterable[str]) -> list[str]:
    items = [d.strip() for d in difficulties if d.strip()]
    if not items:
        items = list(DEFAULT_DIFFICULTIES)
    base = total // len(items)
    remainder = total % len(items)
    result: list[str] = []
    for idx, difficulty in enumerate(items):
        count = base + (1 if idx < remainder else 0)
        result.extend([difficulty] * count)
    return result


def _extract_first_json_block(content: str) -> dict[str, Any]:
    text = (content or "").strip()
    if not text:
        raise ValueError("LLM 返回为空")
    if text.startswith("```"):
        text = text.strip("`")
        if "\n" in text:
            text = text.split("\n", 1)[1]
    decoder = json.JSONDecoder()
    for idx, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(text[idx:])
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            continue
    raise ValueError("未能从 LLM 返回中解析 JSON")


def _difficulty_prompt_hint(difficulty: str) -> str:
    if difficulty == "simple":
        return "simple: 1个预期 + 1-2个场景，干扰少，说话人2人。"
    if difficulty == "medium":
        return "medium: 2个预期 + 3-4个场景，中等干扰，说话人3-4人。"
    return "complex: 2-3个预期 + 4-5个场景，大量干扰，说话人5+人，信息高度分散。"


async def generate_one_case(
    client: httpx.AsyncClient,
    llm_cfg: dict[str, str],
    difficulty: str,
    seq_num: int,
    min_length: int,
    max_length: int,
) -> dict[str, Any]:
    user_prompt = (
        f"请生成 1 条测试 case。\n"
        f"- difficulty: {difficulty}\n"
        f"- 序号: {seq_num}\n"
        f"- 文本长度范围: {min_length}-{max_length} 字\n"
        f"- 难度规则: {_difficulty_prompt_hint(difficulty)}\n"
        f"- company_id 固定为: {DEFAULT_COMPANY_ID}\n"
        f"- case_id 必须严格为: auto_{difficulty}_{seq_num}\n"
        "只输出 JSON，不要额外解释。"
    )
    payload = {
        "model": llm_cfg["model"],
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.7,
    }
    resp = await client.post(
        f"{llm_cfg['base_url']}/chat/completions",
        headers={"Authorization": f"Bearer {llm_cfg['api_key']}", "Content-Type": "application/json"},
        json=payload,
    )
    resp.raise_for_status()
    data = resp.json()
    content = (
        ((((data.get("choices") or [{}])[0]).get("message") or {}).get("content")) or ""
    )
    case = _extract_first_json_block(content)
    case["case_id"] = f"auto_{difficulty}_{seq_num}"
    case["difficulty"] = difficulty
    case["company_id"] = DEFAULT_COMPANY_ID
    case.setdefault("expected", {})
    text = str(case.get("input_text") or "")
    if len(text) < min_length or len(text) > max_length:
        raise ValueError(f"{case['case_id']} 文本长度 {len(text)} 不在范围 {min_length}-{max_length}")
    return case


def _validate_case_shape(case: dict[str, Any]) -> dict[str, Any]:
    expected = case.setdefault("expected", {})
    expected.setdefault("expectations_count", 0)
    expected.setdefault("scenarios_count", 0)
    expected.setdefault("should_contain_titles", [])
    expected.setdefault("should_contain_yuqi_briefs", [])
    expected.setdefault("should_not_contain", [])
    expected.setdefault("notes", "")
    case.setdefault("description", "")
    case.setdefault("company_name", "测试公司")
    case.setdefault("company_id", DEFAULT_COMPANY_ID)
    return case


async def main() -> None:
    args = parse_args()
    if args.count <= 0:
        raise SystemExit("--count 必须大于 0")
    if args.min_length < 200 or args.max_length < args.min_length:
        raise SystemExit("长度参数不合法")

    llm_cfg = load_llm_config(args)
    distribution = build_distribution(args.count, args.difficulties.split(","))
    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    difficulty_seen: dict[str, int] = {}
    cases: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=httpx.Timeout(180.0)) as client:
        for idx, difficulty in enumerate(distribution):
            difficulty_seen[difficulty] = difficulty_seen.get(difficulty, 0) + 1
            seq_num = difficulty_seen[difficulty]
            for attempt in range(1, 4):
                try:
                    case = await generate_one_case(
                        client=client,
                        llm_cfg=llm_cfg,
                        difficulty=difficulty,
                        seq_num=seq_num,
                        min_length=args.min_length,
                        max_length=args.max_length,
                    )
                    cases.append(_validate_case_shape(case))
                    print(f"[{idx + 1}/{len(distribution)}] 生成成功: {case['case_id']}")
                    break
                except Exception as exc:
                    if attempt >= 3:
                        raise
                    print(f"[{idx + 1}/{len(distribution)}] 重试 {attempt}/3: {exc}")
                    await asyncio.sleep(2)
            if idx < len(distribution) - 1:
                await asyncio.sleep(max(0.0, float(args.sleep_seconds)))

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model_used": llm_cfg["model"],
        "provider": llm_cfg["provider"],
        "base_url": llm_cfg["base_url"],
        "count": len(cases),
        "generation_seconds": round(time.time(), 3),
        "cases": cases,
    }
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n已输出: {output_path}")
    print(f"model_used: {llm_cfg['model']}")
    print(f"总计: {len(cases)} 条")


if __name__ == "__main__":
    asyncio.run(main())
