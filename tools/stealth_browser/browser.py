"""
StealthBrowser
==============
Playwright wrapper 规避各大网站（Cloudflare、ChatGPT、Claude、Gemini 等）的 bot 检测。

设计原则
--------
1. headless=False  —— 有界面模式，Cloudflare 等无法通过 headless 检测
2. 真实 User-Agent  —— 覆盖默认 UA（含 HeadlessChrome 字样）
3. stealth.js 注入  —— 覆盖 navigator.webdriver、plugins、chrome 对象等 JS 特征
4. storage_state 复用 —— 持久化 cookies/localStorage，避免频繁登录触发安全警报
5. 关闭自动化标志位  —— --disable-blink-features=AutomationControlled

用法
----
基础用法：
    from tools.stealth_browser import StealthBrowser

    with StealthBrowser() as sb:
        page = sb.new_page()
        page.goto("https://chatgpt.com")
        print(page.title())

带 session 持久化：
    with StealthBrowser(session_path="~/.my_sessions/chatgpt.json") as sb:
        page = sb.new_page()
        page.goto("https://chatgpt.com")
        sb.save_session()   # 保存 cookies

拦截 Bearer token（ChatGPT 专用）：
    with StealthBrowser() as sb:
        token = sb.capture_bearer_token("https://chatgpt.com", "backend-api/conversations")
        print("token:", token[:20])

异步用法：
    from tools.stealth_browser import StealthBrowser
    import asyncio

    async def main():
        async with StealthBrowser(async_mode=True) as sb:
            page = await sb.new_page_async()
            await page.goto("https://claude.ai")

    asyncio.run(main())
"""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Optional

log = logging.getLogger(__name__)

# ── Defaults ──────────────────────────────────────────────────────────────────
_HERE = Path(__file__).parent

DEFAULT_CHROMIUM = (
    Path.home()
    / "Library/Caches/ms-playwright/chromium-1208"
    / "chrome-mac-arm64"
    / "Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"
)

DEFAULT_SESSION  = Path.home() / ".playwright-stealth/storage/session.json"
DEFAULT_STEALTH  = _HERE / "stealth.js"

DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)

LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox",
    "--start-maximized",
    "--disable-infobars",
]

CONTEXT_OPTIONS = {
    "viewport":     {"width": 1280, "height": 800},
    "locale":       "en-US",
    "timezone_id":  "America/Los_Angeles",
}


# ── StealthBrowser ────────────────────────────────────────────────────────────
class StealthBrowser:
    """
    同步 Playwright 浏览器，自动应用所有反检测配置。

    Parameters
    ----------
    session_path : str | Path | None
        storage_state 文件路径。None = 不加载/不保存 session。
    user_agent : str
        覆盖 User-Agent（默认：macOS Chrome 122）。
    headless : bool
        是否无界面模式。**强烈建议保持 False**（有界面）以绕过 Cloudflare 等检测。
    chromium_path : str | Path | None
        Chromium 二进制路径。None = 使用本机默认路径。
    stealth_js : str | Path | None
        stealth.js 注入脚本路径。None = 使用内置脚本。
    extra_args : list[str]
        额外的 Chromium 启动参数。
    """

    def __init__(
        self,
        session_path: str | Path | None = None,
        user_agent:   str                = DEFAULT_UA,
        headless:     bool               = False,
        chromium_path: str | Path | None = None,
        stealth_js:   str | Path | None  = None,
        extra_args:   list[str]          = None,
    ):
        self.session_path  = Path(session_path).expanduser() if session_path else None
        self.user_agent    = user_agent
        self.headless      = headless
        self.chromium_path = Path(chromium_path) if chromium_path else DEFAULT_CHROMIUM
        self.stealth_js    = Path(stealth_js) if stealth_js else DEFAULT_STEALTH
        self.extra_args    = extra_args or []

        self._pw       = None
        self._browser  = None
        self._context  = None

    # ── Context manager ────────────────────────────────────────────────────────
    def __enter__(self) -> "StealthBrowser":
        self.start()
        return self

    def __exit__(self, *_):
        self.stop()

    # ── Lifecycle ──────────────────────────────────────────────────────────────
    def start(self):
        """启动浏览器，应用所有反检测配置。"""
        from playwright.sync_api import sync_playwright

        self._pw      = sync_playwright().start()
        self._browser = self._pw.chromium.launch(
            executable_path=str(self.chromium_path),
            headless=self.headless,
            args=LAUNCH_ARGS + self.extra_args,
        )
        ctx_kwargs = dict(CONTEXT_OPTIONS, user_agent=self.user_agent)

        # 加载持久化 session
        if self.session_path and self.session_path.exists():
            ctx_kwargs["storage_state"] = str(self.session_path)
            log.debug(f"StealthBrowser: loaded session from {self.session_path}")

        self._context = self._browser.new_context(**ctx_kwargs)

        # 注入 stealth.js
        if self.stealth_js.exists():
            self._context.add_init_script(self.stealth_js.read_text())
        else:
            log.warning(f"StealthBrowser: stealth.js not found at {self.stealth_js}")

        log.debug(f"StealthBrowser: started (headless={self.headless}, ua={self.user_agent[:40]}...)")

    def stop(self):
        """关闭浏览器。"""
        try:
            if self._browser:
                self._browser.close()
            if self._pw:
                self._pw.stop()
        except Exception:
            pass
        self._pw = self._browser = self._context = None

    # ── Page factory ───────────────────────────────────────────────────────────
    def new_page(self):
        """创建新标签页（已注入 stealth.js）。"""
        if not self._context:
            raise RuntimeError("StealthBrowser not started. Use 'with StealthBrowser() as sb:'")
        return self._context.new_page()

    @property
    def context(self):
        """返回底层 BrowserContext（用于监听 request/response 等事件）。"""
        return self._context

    # ── Session management ─────────────────────────────────────────────────────
    def save_session(self, path: str | Path | None = None):
        """保存当前 cookies/localStorage 到 session 文件。"""
        target = Path(path).expanduser() if path else self.session_path
        if not target:
            raise ValueError("No session_path configured")
        target.parent.mkdir(parents=True, exist_ok=True)
        self._context.storage_state(path=str(target))
        log.info(f"StealthBrowser: session saved → {target}")

    def load_session_google_only(self) -> dict:
        """
        从 session_path 只读取 Google 的 cookies（剔除 ChatGPT/Claude 等）。
        用于 ChatGPT 首次登录：避免旧的匿名 ChatGPT cookies 污染新登录。

        Returns
        -------
        dict  符合 Playwright storage_state 格式的字典。
        """
        if not (self.session_path and self.session_path.exists()):
            return {"cookies": [], "origins": []}
        data = json.loads(self.session_path.read_text())
        return {
            "cookies": [
                c for c in data.get("cookies", [])
                if "google" in c.get("domain", "") or "gmail" in c.get("domain", "")
            ],
            "origins": [
                o for o in data.get("origins", [])
                if "google" in o.get("origin", "")
            ],
        }

    # ── Utility methods ────────────────────────────────────────────────────────
    def goto(self, url: str, wait_until: str = "domcontentloaded", timeout_ms: int = 3000) -> "Page":
        """快捷方式：新建 page 并导航到 URL。"""
        page = self.new_page()
        page.goto(url, wait_until=wait_until)
        page.wait_for_timeout(timeout_ms)
        return page

    def capture_bearer_token(
        self,
        url: str,
        url_contains: str,
        wait_ms: int = 5000,
    ) -> Optional[str]:
        """
        打开页面，拦截页面发出的带 Bearer token 的请求，返回 token 字符串。

        Parameters
        ----------
        url         : 要打开的页面 URL
        url_contains: 用于匹配目标请求的 URL 片段（如 "backend-api/conversations"）
        wait_ms     : 等待请求出现的毫秒数

        Example
        -------
        token = sb.capture_bearer_token("https://chatgpt.com", "backend-api/conversations")
        """
        captured: list[str] = []

        def on_request(req):
            if url_contains in req.url and not captured:
                auth = req.headers.get("authorization", "")
                if auth.startswith("Bearer "):
                    captured.append(auth[7:])

        self._context.on("request", on_request)
        page = self.new_page()
        page.goto(url, wait_until="networkidle")
        page.wait_for_timeout(wait_ms)
        self._context.remove_listener("request", on_request)

        return captured[0] if captured else None

    def fetch_json(self, page, url: str, headers: dict = None) -> dict:
        """
        在页面上下文中发起 fetch 请求，返回 JSON 结果。

        Parameters
        ----------
        page    : Playwright Page 对象
        url     : 目标 URL
        headers : 额外 HTTP headers（如 Authorization: Bearer ...）
        """
        headers_js = json.dumps(headers or {})
        result = page.evaluate(f"""async () => {{
            const r = await fetch({json.dumps(url)}, {{
                credentials: 'include',
                headers: {headers_js},
            }});
            if (!r.ok) return {{__error: r.status, __text: await r.text()}};
            return await r.json();
        }}""")
        if isinstance(result, dict) and "__error" in result:
            log.warning(f"fetch_json {url} → HTTP {result['__error']}: {result.get('__text','')[:100]}")
            return {}
        return result or {}

    def new_context_google_only(self) -> "StealthBrowser":
        """
        返回一个新的 StealthBrowser 实例，只加载 Google 的 cookies。
        用于需要 Google OAuth 重新登录某个服务（如 ChatGPT）的场景。
        """
        google_state = self.load_session_google_only()
        with open("/tmp/_google_only_session.json", "w") as f:
            json.dump(google_state, f)
        return StealthBrowser(
            session_path=None,
            user_agent=self.user_agent,
            headless=self.headless,
            chromium_path=self.chromium_path,
            stealth_js=self.stealth_js,
        )


# ── StealthPage convenience wrapper ──────────────────────────────────────────
class StealthPage:
    """
    对 Playwright Page 的薄封装，提供更便捷的方法。

    Example
    -------
    with StealthBrowser() as sb:
        sp = StealthPage(sb.new_page())
        sp.goto("https://chatgpt.com")
        data = sp.fetch_json("/backend-api/conversations?limit=3")
    """

    def __init__(self, page):
        self._page = page

    def __getattr__(self, name):
        return getattr(self._page, name)

    def goto(self, url: str, wait_until: str = "domcontentloaded", sleep_ms: int = 2000):
        self._page.goto(url, wait_until=wait_until)
        self._page.wait_for_timeout(sleep_ms)
        return self

    def fetch_json(self, url: str, headers: dict = None) -> dict:
        headers_js = json.dumps(headers or {})
        result = self._page.evaluate(f"""async () => {{
            const r = await fetch({json.dumps(url)}, {{
                credentials: 'include',
                headers: {headers_js},
            }});
            if (!r.ok) return {{__error: r.status}};
            return await r.json();
        }}""")
        return result or {}

    def wait(self, ms: int = 2000):
        self._page.wait_for_timeout(ms)
        return self

    @property
    def raw(self):
        """返回底层 Playwright Page 对象。"""
        return self._page
