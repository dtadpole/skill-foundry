"""
StealthBrowser — Playwright wrapper that bypasses bot detection.

Usage:
    from tools.stealth_browser import StealthBrowser

    with StealthBrowser() as sb:
        page = sb.new_page()
        page.goto("https://chatgpt.com")
        html = page.content()
"""
from .browser import StealthBrowser, StealthPage

__all__ = ["StealthBrowser", "StealthPage"]
