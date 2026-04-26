from __future__ import annotations

import asyncio
import time
from typing import Any

try:
    from playwright.async_api import Page
except Exception:  # pragma: no cover
    Page = Any  # type: ignore[misc,assignment]


INPUT_SELECTORS = [
    "textarea",
    "textarea[placeholder*='message' i]",
    "textarea[placeholder*='发送' i]",
    "[contenteditable='true'][role='textbox']",
    "[contenteditable='true'][data-testid*='input' i]",
    "[contenteditable='true']",
]

SEND_BUTTON_SELECTORS = [
    "button[data-testid*='send' i]",
    "button[aria-label*='send' i]",
    "button[aria-label*='发送' i]",
    "button:has-text('Send')",
    "button:has-text('发送')",
]


async def _find_input(page: Page):
    for selector in INPUT_SELECTORS:
        locator = page.locator(selector).first
        try:
            if await locator.count() > 0 and await locator.is_visible():
                return locator
        except Exception:
            continue
    raise RuntimeError("未找到可用的消息输入框（textarea/contenteditable）。")


async def _read_message_texts(page: Page) -> list[str]:
    return await page.evaluate(
        """
        () => {
          const selectors = [
            '[data-message-id]',
            '[data-testid*="message"]',
            '[data-testid*="chat-message"]',
            '.message',
            '.chat-message',
            'article',
            '.markdown',
            '.prose',
          ];
          const nodes = [];
          for (const sel of selectors) {
            document.querySelectorAll(sel).forEach((el) => nodes.push(el));
          }
          const uniq = [...new Set(nodes)];
          const texts = [];
          for (const el of uniq) {
            if (!(el instanceof HTMLElement)) continue;
            if (el.closest('form')) continue;
            if (el.closest('[contenteditable="true"]')) continue;
            const text = (el.innerText || '').trim();
            if (!text) continue;
            if (text.length < 2) continue;
            texts.push(text);
          }
          return texts;
        }
        """
    )


async def _send_message(page: Page, message: str) -> None:
    input_box = await _find_input(page)
    await input_box.click()

    tag_name = (await input_box.evaluate("el => (el.tagName || '').toLowerCase()")).strip()
    if tag_name == "textarea":
        await input_box.fill(message)
    else:
        await page.keyboard.press("Control+A")
        await page.keyboard.press("Backspace")
        await page.keyboard.type(message)

    for selector in SEND_BUTTON_SELECTORS:
        button = page.locator(selector).first
        try:
            if await button.count() > 0 and await button.is_visible() and await button.is_enabled():
                await button.click()
                return
        except Exception:
            continue

    # Fallback: simulate Enter.
    await input_box.press("Enter")


async def send_and_receive(page: Page, message: str, timeout: int = 120) -> str:
    """
    在已打开的 Genspark 对话页面发送消息并等待回复

    Args:
        page: Playwright page 对象（已打开 Genspark 对话页面）
        message: 要发送的消息文本
        timeout: 等待回复的超时秒数

    Returns:
        AI 的回复文本
    """
    message = (message or "").strip()
    if not message:
        raise ValueError("message 不能为空")

    before_texts = await _read_message_texts(page)
    before_last = before_texts[-1] if before_texts else ""

    await _send_message(page, message)

    deadline = time.monotonic() + max(1, timeout)
    last_text = ""
    stable_rounds = 0

    while time.monotonic() < deadline:
        await asyncio.sleep(2)
        texts = await _read_message_texts(page)
        if not texts:
            continue

        current_last = texts[-1].strip()
        if not current_last:
            continue

        has_new_message = len(texts) > len(before_texts)
        changed_from_before = current_last != before_last
        if not (has_new_message or changed_from_before):
            continue

        if current_last == last_text:
            stable_rounds += 1
        else:
            last_text = current_last
            stable_rounds = 0

        # Require two stable polls (~4s) to avoid returning streaming partials.
        if stable_rounds >= 1:
            return current_last

    raise TimeoutError(f"等待 Genspark 回复超时（{timeout}s）")

