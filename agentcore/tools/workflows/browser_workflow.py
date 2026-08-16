"""AgentCore — tools/workflows/browser_workflow.py
Browser workflow (REAL — Playwright async API + Chromium):
  open browser → navigate to URL → wait for page load → verify URL → screenshot.

No mocks: a real headless Chromium is launched, a real page navigates, the
URL is verified against the target, and a real PNG screenshot is captured.
Uses Playwright's ASYNC API because the executor runs tools inside asyncio
(the sync API refuses inside a running loop).
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from core.contracts import ToolResult
from tools.base import Tool

# module-level browser state keyed by session_id — the executor passes a fresh
# ctx per tool call, so the REAL browser must live across the workflow's steps
_BROWSER_STATE: dict[str, dict] = {}


class _BrowserBase(Tool):
    capability = "workflow.browser"
    timeout_s = 60.0

    def __init__(self, shots_dir: str | Path) -> None:
        self.shots_dir = Path(shots_dir).resolve()
        self.shots_dir.mkdir(parents=True, exist_ok=True)

    def _st(self, ctx):
        return _BROWSER_STATE.setdefault(ctx.get("session_id", "default"), {})


class BrowserOpen(_BrowserBase):
    name = "browser_open"
    description = "Open a (headless) browser."
    parameters = {"type": "object", "properties": {}}
    idempotent = True

    async def execute(self, params: dict, ctx: dict) -> ToolResult:
        from playwright.async_api import async_playwright
        st = self._st(ctx)
        if st.get("page") is not None:
            return ToolResult(ok=True, data={"browser": "already open"})
        p = await async_playwright().start()
        browser = await p.chromium.launch()
        page = await browser.new_page()
        st.update({"pw": p, "browser": browser, "page": page})
        return ToolResult(ok=True, data={"browser": "chromium (headless)"})


class BrowserNavigate(_BrowserBase):
    name = "browser_navigate"
    description = "Navigate the open browser to a URL."
    parameters = {"type": "object", "properties": {"url": {"type": "string"}},
                  "required": ["url"]}

    async def execute(self, params: dict, ctx: dict) -> ToolResult:
        page = self._st(ctx).get("page")
        if page is None:
            return ToolResult(ok=False, error="browser not open (call browser_open first)")
        url = params["url"]
        await page.goto(url, timeout=self.timeout_s * 1000, wait_until="load")
        return ToolResult(ok=True, data={"url": page.url, "title": await page.title()})


class BrowserWaitLoad(_BrowserBase):
    name = "browser_wait_load"
    description = "Wait until the page finishes loading (network idle)."
    parameters = {"type": "object", "properties": {}}
    idempotent = True

    async def execute(self, params: dict, ctx: dict) -> ToolResult:
        page = self._st(ctx).get("page")
        if page is None:
            return ToolResult(ok=False, error="browser not open")
        await page.wait_for_load_state("networkidle", timeout=self.timeout_s * 1000)
        return ToolResult(ok=True, data={"url": page.url, "title": await page.title()})


class BrowserVerifyUrl(_BrowserBase):
    name = "browser_verify_url"
    description = "Verify the browser's current URL matches the expected URL."
    parameters = {"type": "object", "properties": {"expected": {"type": "string"}},
                  "required": ["expected"]}
    idempotent = True

    async def execute(self, params: dict, ctx: dict) -> ToolResult:
        page = self._st(ctx).get("page")
        if page is None:
            return ToolResult(ok=False, error="browser not open")
        current = page.url
        expected = params["expected"]
        ok = current.rstrip("/") == expected.rstrip("/")
        return ToolResult(ok=ok, data={"current": current, "expected": expected,
                                       "match": ok})


class BrowserScreenshot(_BrowserBase):
    name = "browser_screenshot"
    description = "Capture a screenshot of the current page."
    parameters = {"type": "object", "properties": {}}
    idempotent = True

    async def execute(self, params: dict, ctx: dict) -> ToolResult:
        page = self._st(ctx).get("page")
        if page is None:
            return ToolResult(ok=False, error="browser not open")
        fname = f"browser_{int(time.time()*1000)}.png"
        path = self.shots_dir / fname
        await page.screenshot(path=str(path))
        return ToolResult(ok=True, data={"file": str(path),
                                         "size": path.stat().st_size,
                                         "mime": "image/png"})


class BrowserClose(_BrowserBase):
    name = "browser_close"
    description = "Close the browser."
    parameters = {"type": "object", "properties": {}}
    idempotent = True

    async def execute(self, params: dict, ctx: dict) -> ToolResult:
        st = self._st(ctx)
        browser = st.get("browser"); pw = st.get("pw")
        if browser is not None:
            try:
                await browser.close()
            except Exception:  # noqa: BLE001
                pass
        if pw is not None:
            try:
                await pw.stop()
            except Exception:  # noqa: BLE001
                pass
        _BROWSER_STATE.pop(ctx.get("session_id", "default"), None)
        return ToolResult(ok=True, data={"closed": True})


def register_all(registry, shots_dir: str | Path) -> None:
    for t in (BrowserOpen(shots_dir), BrowserNavigate(shots_dir),
              BrowserWaitLoad(shots_dir), BrowserVerifyUrl(shots_dir),
              BrowserScreenshot(shots_dir), BrowserClose(shots_dir)):
        registry.register(t)
