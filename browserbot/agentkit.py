"""Minimal browser automation building blocks for BrowserBot.

This module intentionally keeps a small surface area: a single
`BrowserAgent` class wraps the Playwright sync API with a few helper
methods, and `create_agent` returns a ready-to-use instance.  The agent
is designed for short-lived interactions that open a fresh context for
each action, which keeps the implementation straightforward while still
being reliable for the MCP tooling.
"""

from __future__ import annotations

import base64
from contextlib import AbstractContextManager, contextmanager
from typing import Dict, Iterator, List, Optional, Sequence, Tuple

from playwright.sync_api import (
    Browser,
    Error,
    Page,
    Playwright,
    sync_playwright,
)

ALLOWED_WAIT_STATES = {"load", "domcontentloaded", "networkidle"}


class BrowserAgent(AbstractContextManager["BrowserAgent"]):
    """Thin wrapper around Playwright for one-off page interactions.

    Each public helper opens a fresh Chromium context, performs the
    requested operation, and closes the context again.  Keeping state as
    small as possible makes it easy to reason about behaviour and avoids
    resource leaks when the agent is used from asynchronous code.
    """

    def __init__(
        self,
        *,
        headless: bool = True,
        launch_args: Optional[Sequence[str]] = None,
        default_timeout_ms: int = 5000,
    ) -> None:
        self._headless = headless
        self._launch_args = tuple(launch_args or ())
        self._default_timeout_ms = default_timeout_ms
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None

    # ------------------------------------------------------------------ #
    # Lifecycle helpers
    # ------------------------------------------------------------------ #

    def __enter__(self) -> "BrowserAgent":
        self.startup()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.shutdown()

    def startup(self) -> None:
        """Ensure a Chromium instance is available."""
        if self._playwright is not None:
            return
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            headless=self._headless,
            args=list(self._launch_args),
        )

    def shutdown(self) -> None:
        """Close Chromium and release Playwright resources."""
        if self._browser is not None:
            self._browser.close()
            self._browser = None
        if self._playwright is not None:
            self._playwright.stop()
            self._playwright = None

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def navigate(self, url: str, *, wait_until: str = "load") -> Dict[str, str]:
        """Navigate to ``url`` and return the final URL and page title."""
        with self._open_page(url, wait_until=wait_until) as page:
            return {"final_url": page.url, "title": page.title()}

    def list_links(
        self,
        url: str,
        *,
        wait_until: str = "load",
        limit: Optional[int] = 200,
        root_selector: Optional[str] = None,
        link_selector: Optional[str] = None,
    ) -> Dict[str, object]:
        """Return metadata about anchor tags discovered on ``url``."""
        with self._open_page(url, wait_until=wait_until) as page:
            links, truncated, total = self._collect_links(
                page,
                limit=limit,
                root_selector=root_selector,
                link_selector=link_selector,
            )
            return {
                "final_url": page.url,
                "title": page.title(),
                "links": links,
                "count": total,
                "truncated": truncated,
            }

    def extract_text(
        self,
        url: str,
        selector: str,
        *,
        wait_until: str = "load",
        timeout_ms: Optional[int] = None,
    ) -> Dict[str, str]:
        """Return the text content for ``selector`` on ``url``."""
        if not selector:
            raise ValueError("selector must be a non-empty string.")
        effective_timeout = timeout_ms or self._default_timeout_ms
        with self._open_page(url, wait_until=wait_until) as page:
            element = page.wait_for_selector(selector, timeout=effective_timeout)
            text = element.inner_text() or ""
            return {
                "final_url": page.url,
                "title": page.title(),
                "selector": selector,
                "text": text.strip(),
            }

    def click(
        self,
        url: str,
        selector: str,
        *,
        wait_until: str = "load",
        timeout_ms: Optional[int] = None,
        post_wait: Optional[str] = "networkidle",
    ) -> Dict[str, str]:
        """Click ``selector`` on ``url`` and return the resulting page info."""
        if not selector:
            raise ValueError("selector must be a non-empty string.")
        effective_timeout = timeout_ms or self._default_timeout_ms
        with self._open_page(url, wait_until=wait_until) as page:
            page.wait_for_selector(selector, timeout=effective_timeout)
            page.click(selector, timeout=effective_timeout)
            if post_wait:
                page.wait_for_load_state(post_wait)
            return {
                "final_url": page.url,
                "title": page.title(),
                "clicked": selector,
            }

    def screenshot(
        self,
        url: str,
        *,
        wait_until: str = "load",
        selector: Optional[str] = None,
        full_page: bool = True,
        image_format: str = "png",
        quality: Optional[int] = None,
    ) -> Dict[str, object]:
        """Capture a screenshot of ``url`` and return it as a base64 string."""
        valid_formats = {"png", "jpeg"}
        if image_format not in valid_formats:
            raise ValueError(f"image_format must be one of {valid_formats}.")
        with self._open_page(url, wait_until=wait_until) as page:
            if selector:
                element = page.wait_for_selector(selector, timeout=self._default_timeout_ms)
                data = element.screenshot(type=image_format, quality=quality)
            else:
                data = page.screenshot(full_page=full_page, type=image_format, quality=quality)
            if isinstance(data, bytes):
                encoded = base64.b64encode(data).decode("ascii")
            else:
                encoded = data
            return {
                "final_url": page.url,
                "title": page.title(),
                "image_format": image_format,
                "screenshot_base64": encoded,
                "full_page": full_page,
                "selector": selector,
            }

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _ensure_browser(self) -> Browser:
        self.startup()
        if self._browser is None:
            raise RuntimeError("Playwright failed to launch Chromium.")
        return self._browser

    def _validate_wait_state(self, wait_until: str) -> str:
        if wait_until not in ALLOWED_WAIT_STATES:
            allowed = ", ".join(sorted(ALLOWED_WAIT_STATES))
            raise ValueError(f"wait_until must be one of {{{allowed}}}.")
        return wait_until

    @contextmanager
    def _open_page(self, url: str, *, wait_until: str) -> Iterator[Page]:
        if not url:
            raise ValueError("url must be a non-empty string.")
        wait_state = self._validate_wait_state(wait_until)
        browser = self._ensure_browser()
        context = browser.new_context()
        page = context.new_page()
        try:
            page.goto(url, wait_until=wait_state)
            yield page
        finally:
            context.close()

    def _collect_links(
        self,
        page: Page,
        *,
        limit: Optional[int],
        root_selector: Optional[str],
        link_selector: Optional[str],
    ) -> Tuple[List[Dict[str, object]], bool, int]:
        selector = link_selector or "a"
        script = """({ rootSelector, selector, limit }) => {
            const root = rootSelector ? document.querySelector(rootSelector) : document;
            if (!root) {
                return { links: [], truncated: false, total: 0 };
            }
            const elements = Array.from(root.querySelectorAll(selector || "a"));
            const total = elements.length;
            const unlimited = limit === null || limit === undefined;
            const truncated = unlimited ? false : total > limit;
            const slice = truncated ? elements.slice(0, limit) : elements;
            const links = slice.map((element, index) => ({
                position: index + 1,
                href: element.getAttribute("href") ?? "",
                text: (element.innerText ?? "").trim(),
                title: element.getAttribute("title"),
                aria_label: element.getAttribute("aria-label"),
                target: element.getAttribute("target"),
                rel: element.getAttribute("rel"),
            }));
            return { links, truncated, total };
        }"""

        for attempt in range(3):
            try:
                result = page.evaluate(
                    script,
                    {"rootSelector": root_selector, "selector": selector, "limit": limit},
                )
            except Error as exc:
                if "Execution context was destroyed" in str(exc) and attempt < 2:
                    page.wait_for_load_state("load")
                    continue
                raise
            if not result:
                return [], False, 0
            links = list(result.get("links") or [])
            truncated = bool(result.get("truncated"))
            total = int(result.get("total") or 0)
            return links, truncated, total
        return [], False, 0


def create_agent(*, headless: bool = True) -> BrowserAgent:
    """Factory helper for parity with existing usage sites."""
    return BrowserAgent(headless=headless)


__all__ = ["BrowserAgent", "create_agent"]
