from __future__ import annotations

import asyncio
import os
from pathlib import Path

from playwright.async_api import async_playwright

from genspark_chat import send_and_receive


async def main() -> None:
    url = (os.getenv("GENSPARK_CHAT_URL") or "").strip()
    if not url:
        raise SystemExit("缺少 GENSPARK_CHAT_URL")
    user_data_dir = (Path.home() / ".cursor" / "genspark_browser_data").resolve()
    user_data_dir.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(user_data_dir),
            headless=False,
            channel="chrome",
            ignore_default_args=["--enable-automation"],
            args=["--disable-blink-features=AutomationControlled", "--start-maximized"],
        )
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto(url, wait_until="domcontentloaded")
        reply = await send_and_receive(
            page,
            "你好，我是 Cursor，正在测试与产品经理 AI 的自动化对话链路。请回复收到。",
            timeout=120,
        )
        print("REPLY_START")
        print(reply)
        print("REPLY_END")


if __name__ == "__main__":
    asyncio.run(main())

