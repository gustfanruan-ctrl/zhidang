from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from playwright.async_api import Page, async_playwright

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from genspark_chat import INPUT_SELECTORS, SEND_BUTTON_SELECTORS, send_and_receive


TEST_MESSAGE = "你好，我是 Cursor，正在测试与产品经理 AI 的自动化对话链路。请回复收到。"


async def _find_first_visible(page: Page, selectors: list[str]):
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            if await locator.count() > 0 and await locator.is_visible():
                return selector, locator
        except Exception:
            continue
    return None, None


async def _wait_chat_ready(page: Page, seconds: int = 15) -> bool:
    deadline = asyncio.get_event_loop().time() + max(1, seconds)
    while asyncio.get_event_loop().time() < deadline:
        _, input_locator = await _find_first_visible(page, INPUT_SELECTORS)
        if input_locator is not None:
            return True
        await asyncio.sleep(1)
    return False


async def main() -> None:
    chat_url = (os.getenv("GENSPARK_CHAT_URL") or "").strip()
    if not chat_url:
        raise SystemExit("缺少环境变量 GENSPARK_CHAT_URL")

    user_data_dir = (Path.home() / ".cursor" / "genspark_browser_data").resolve()
    user_data_dir.mkdir(parents=True, exist_ok=True)
    print(f"user_data_dir: {user_data_dir}")
    cdp_url = (os.getenv("CHROME_CDP_URL") or "").strip()

    async with async_playwright() as p:
        if cdp_url:
            browser = await p.chromium.connect_over_cdp(cdp_url)
            context = browser.contexts[0] if browser.contexts else await browser.new_context()
            page = context.pages[0] if context.pages else await context.new_page()
            print(f"已连接现有 Chrome: {cdp_url}")
            await page.goto(chat_url, wait_until="domcontentloaded")
            ready = await _wait_chat_ready(page, seconds=15)
            if not ready:
                raise RuntimeError("已连接现有 Chrome，但未检测到聊天输入框。请确认当前标签页已完成登录。")
            input_selector, _ = await _find_first_visible(page, INPUT_SELECTORS)
            send_selector, _ = await _find_first_visible(page, SEND_BUTTON_SELECTORS)
            print(f"输入框选择器: {input_selector or '未命中，将由回车兜底'}")
            print(f"发送按钮选择器: {send_selector or '未命中，将由回车兜底'}")
            reply = await send_and_receive(page, TEST_MESSAGE, timeout=120)
            print("\n===== Genspark 回复 =====\n")
            print(reply)
            print("\n浏览器保持打开，便于后续复用。按 Ctrl+C 结束脚本。")
            await asyncio.Event().wait()
            return

        launch_errors: list[str] = []
        context = None
        # Prefer local Chrome to avoid playwright browser download issues.
        try:
            context = await p.chromium.launch_persistent_context(
                user_data_dir=str(user_data_dir),
                headless=False,
                channel="chrome",
                ignore_default_args=["--enable-automation"],
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-features=IsolateOrigins,site-per-process",
                    "--start-maximized",
                ],
            )
            print("已使用本机 Chrome 启动。")
        except Exception as exc:
            launch_errors.append(f"chrome channel 启动失败: {exc}")
        if context is None:
            try:
                context = await p.chromium.launch_persistent_context(
                    user_data_dir=str(user_data_dir),
                    headless=False,
                )
                print("已使用 Playwright Chromium 启动。")
            except Exception as exc:
                launch_errors.append(f"chromium 启动失败: {exc}")
                raise RuntimeError("浏览器启动失败；请先安装 Chrome 或执行 playwright install chromium。\n" + "\n".join(launch_errors))
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto(chat_url, wait_until="domcontentloaded")
        page_text = (await page.locator("body").inner_text()).strip()
        if "此浏览器或应用可能不安全" in page_text:
            print("检测到 Google 安全限制页面。建议改用已手动登录的本机 Chrome，并通过 CDP 连接运行：")
            print("1) 先手动启动 Chrome: chrome.exe --remote-debugging-port=9222")
            print("2) 设置环境变量 CHROME_CDP_URL=http://127.0.0.1:9222")
            print("3) 重新运行本脚本")
            await asyncio.sleep(60)
            await page.goto(chat_url, wait_until="domcontentloaded")

        ready = await _wait_chat_ready(page, seconds=15)
        if not ready:
            print("未检测到聊天输入框，可能尚未登录。请在 60 秒内手动登录 Genspark...")
            await asyncio.sleep(60)
            await page.goto(chat_url, wait_until="domcontentloaded")
            ready = await _wait_chat_ready(page, seconds=20)
            if not ready:
                raise RuntimeError("登录后仍未检测到聊天输入框，请检查页面状态或选择器。")

        input_selector, _ = await _find_first_visible(page, INPUT_SELECTORS)
        send_selector, _ = await _find_first_visible(page, SEND_BUTTON_SELECTORS)
        print(f"输入框选择器: {input_selector or '未命中，将由回车兜底'}")
        print(f"发送按钮选择器: {send_selector or '未命中，将由回车兜底'}")

        reply = await send_and_receive(page, TEST_MESSAGE, timeout=120)
        print("\n===== Genspark 回复 =====\n")
        print(reply)
        print("\n浏览器保持打开，便于后续复用。按 Ctrl+C 结束脚本。")

        await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())

