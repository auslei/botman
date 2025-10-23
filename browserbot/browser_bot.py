"""Minimal browser automation building blocks for BrowserBot.

This module intentionally keeps a small surface area: a single
`BrowserBot` class wraps the Playwright sync API with a few helper
methods, and `create_browserbot` returns a ready-to-use instance.  The agent
is designed for short-lived interactions that open a fresh context for
each action, which keeps the implementation straightforward while still
being reliable for the MCP tooling.
"""

from __future__ import annotations

import base64
from contextlib import AbstractContextManager, contextmanager
from typing import Any, Dict, Iterator, List, Mapping, Optional, Sequence, Tuple

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Error,
    Page,
    Playwright,
    sync_playwright,
)

ALLOWED_WAIT_STATES = {"load", "domcontentloaded", "networkidle"}
ALLOWED_SELECTOR_STATES = {"attached", "detached", "visible", "hidden"}

FieldInstruction = Dict[str, Any]


class BrowserBot(AbstractContextManager["BrowserBot"]):
    """Thin wrapper around Playwright for one-off page interactions.

    By default each helper opens a fresh Chromium context, performs
    the requested operation, and closes the context again.  Set
    ``persist_context=True`` to reuse a single browser context/page
    across calls for session continuity (cookies, navigation history).
    """

    def __init__(
        self,
        *,
        headless: bool = True,
        launch_args: Optional[Sequence[str]] = None,
        default_timeout_ms: int = 5000,
        persist_context: bool = False,
    ) -> None:
        self._headless = headless
        self._launch_args = tuple(launch_args or ())
        self._default_timeout_ms = default_timeout_ms
        self._persist_context = persist_context
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    # ------------------------------------------------------------------ #
    # Lifecycle helpers
    # ------------------------------------------------------------------ #

    def __enter__(self) -> "BrowserBot":
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
        if self._page is not None:
            try:
                if not self._page.is_closed():
                    self._page.close()
            except Exception:
                pass
            finally:
                self._page = None
        if self._context is not None:
            try:
                self._context.close()
            except Exception:
                pass
            finally:
                self._context = None
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
        url: Optional[str] = None,
        *,
        wait_until: str = "load",
        limit: Optional[int] = 200,
        root_selector: Optional[str] = None,
        link_selector: Optional[str] = None,
    ) -> Dict[str, object]:
        """Return metadata about anchor tags discovered on ``url``.

        When ``persist_context`` is enabled, ``url`` may be ``None`` to
        operate on the currently loaded page.
        """
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
        url: Optional[str] = None,
        *,
        selector: str,
        wait_until: str = "load",
        timeout_ms: Optional[int] = None,
    ) -> Dict[str, str]:
        """Return the text content for ``selector`` on ``url``.

        With ``persist_context`` enabled, ``url`` may be ``None`` to
        reuse the current page.
        """
        if not selector:
            raise ValueError("selector must be a non-empty string.")
        effective_timeout = timeout_ms or self._default_timeout_ms
        with self._open_page(url, wait_until=wait_until) as page:
            element = page.wait_for_selector(selector, timeout=effective_timeout)
            text = element.inner_text() if element else ""
            return {
                "final_url": page.url,
                "title": page.title(),
                "selector": selector,
                "text": text.strip(),
            }

    def extract_html(
        self,
        url: Optional[str] = None,
        *,
        wait_until: str = "load",
        selector: Optional[str] = None,
        timeout_ms: Optional[int] = None,
        inner: bool = False,
    ) -> Dict[str, str]:
        """Return the HTML for ``selector`` (or the full page when omitted).

        With ``persist_context`` enabled, ``url`` may be ``None`` to
        reuse the current page.
        """
        effective_timeout = timeout_ms or self._default_timeout_ms
        with self._open_page(url, wait_until=wait_until) as page:
            if selector:
                element = page.wait_for_selector(selector, timeout=effective_timeout)
                if not element:
                    html = ""
                elif inner:
                    html = element.inner_html()
                else:
                    html = element.evaluate("node => node.outerHTML")
            else:
                html = page.content()
            return {
                "final_url": page.url,
                "title": page.title(),
                "selector": selector,
                "inner": inner,
                "html": html,
            }

    def click(
        self,
        url: Optional[str] = None,
        *,
        selector: str,
        wait_until: str = "load",
        timeout_ms: Optional[int] = None,
        post_wait: Optional[str] = "networkidle",
    ) -> Dict[str, str]:
        """Click ``selector`` on ``url`` and return the resulting page info.

        With ``persist_context`` enabled, ``url`` may be ``None`` to
        reuse the current page.
        """
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

    def fill_fields(
        self,
        url: Optional[str] = None,
        *,
        fields: Mapping[str, Any] | Sequence[object],
        wait_until: str = "load",
        timeout_ms: Optional[int] = None,
        clear_existing: bool = True,
    ) -> Dict[str, object]:
        """Populate form controls identified by ``fields`` on ``url``.

        With ``persist_context`` enabled, ``url`` may be ``None`` to
        reuse the current page.
        """
        instructions = self._normalize_fields(fields)
        effective_timeout = timeout_ms or self._default_timeout_ms
        with self._open_page(url, wait_until=wait_until) as page:
            filled = self._fill_fields_on_page(
                page,
                instructions,
                timeout=effective_timeout,
                clear=clear_existing,
            )
            return {
                "final_url": page.url,
                "title": page.title(),
                "filled": filled,
                "count": len(filled),
            }

    def submit_form(
        self,
        url: Optional[str] = None,
        *,
        form_selector: Optional[str] = None,
        submit_selector: Optional[str] = None,
        fields: Optional[Mapping[str, Any] | Sequence[object]] = None,
        wait_until: str = "load",
        timeout_ms: Optional[int] = None,
        post_wait: Optional[str] = "networkidle",
        wait_for: Optional[str] = None,
        wait_for_state: str = "visible",
        clear_existing: bool = True,
    ) -> Dict[str, object]:
        """Fill (optional) ``fields`` and submit a form on ``url``.

        With ``persist_context`` enabled, ``url`` may be ``None`` to
        reuse the current page.
        """
        if not form_selector and not submit_selector:
            raise ValueError("Provide either form_selector or submit_selector.")
        effective_timeout = timeout_ms or self._default_timeout_ms
        wait_state = self._validate_selector_state(wait_for_state)
        field_instructions = self._normalize_fields(fields) if fields else ()
        with self._open_page(url, wait_until=wait_until) as page:
            filled: List[Dict[str, object]] = []
            if field_instructions:
                filled = self._fill_fields_on_page(
                    page,
                    field_instructions,
                    timeout=effective_timeout,
                    clear=clear_existing,
                )
            if submit_selector:
                page.wait_for_selector(submit_selector, timeout=effective_timeout)
                page.click(submit_selector, timeout=effective_timeout)
                submitted = submit_selector
            else:
                form = page.wait_for_selector(form_selector, timeout=effective_timeout)
                if not form:
                    raise RuntimeError(f"form {form_selector!r} not found.")
                form.evaluate(
                    """element => {
                        if (element.requestSubmit) {
                            element.requestSubmit();
                        } else {
                            element.submit();
                        }
                    }"""
                )
                submitted = form_selector
            if post_wait:
                page.wait_for_load_state(post_wait)
            waited_state: Optional[str] = None
            if wait_for:
                page.wait_for_selector(wait_for, timeout=effective_timeout, state=wait_state)
                waited_state = wait_state
            return {
                "final_url": page.url,
                "title": page.title(),
                "submitted": submitted,
                "filled": filled,
                "waited_for": wait_for,
                "waited_state": waited_state,
            }

    def wait_for_selector(
        self,
        url: Optional[str] = None,
        *,
        selector: str,
        wait_until: str = "load",
        timeout_ms: Optional[int] = None,
        state: str = "visible",
    ) -> Dict[str, object]:
        """Block until ``selector`` reaches ``state`` on ``url``.

        With ``persist_context`` enabled, ``url`` may be ``None`` to
        reuse the current page.
        """
        if not selector:
            raise ValueError("selector must be a non-empty string.")
        wait_state = self._validate_selector_state(state)
        effective_timeout = timeout_ms or self._default_timeout_ms
        with self._open_page(url, wait_until=wait_until) as page:
            element = page.wait_for_selector(
                selector,
                timeout=effective_timeout,
                state=wait_state,
            )
            return {
                "final_url": page.url,
                "title": page.title(),
                "selector": selector,
                "state": wait_state,
                "element_found": element is not None,
            }

    def screenshot(
        self,
        url: Optional[str] = None,
        *,
        wait_until: str = "load",
        selector: Optional[str] = None,
        full_page: bool = True,
        image_format: str = "png",
        quality: Optional[int] = None,
    ) -> Dict[str, object]:
        """Capture a screenshot of ``url`` and return it as a base64 string.

        With ``persist_context`` enabled, ``url`` may be ``None`` to
        reuse the current page.
        """
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

    def _validate_selector_state(self, state: str) -> str:
        if state not in ALLOWED_SELECTOR_STATES:
            allowed = ", ".join(sorted(ALLOWED_SELECTOR_STATES))
            raise ValueError(f"state must be one of {{{allowed}}}.")
        return state

    def _normalize_fields(
        self,
        fields: Optional[Mapping[str, Any] | Sequence[object]],
    ) -> List[FieldInstruction]:
        if fields is None:
            return []
        instructions: List[FieldInstruction] = []
        if isinstance(fields, Mapping):
            for selector, value in fields.items():
                instructions.append({"selector": selector, "value": value})
        else:
            for entry in fields:
                if isinstance(entry, dict):
                    if "selector" not in entry or "value" not in entry:
                        raise ValueError("Each field mapping must include 'selector' and 'value'.")
                    item: FieldInstruction = {
                        "selector": entry["selector"],
                        "value": entry["value"],
                    }
                    if "strategy" in entry:
                        item["strategy"] = entry["strategy"]
                    elif "mode" in entry:
                        item["strategy"] = entry["mode"]
                    elif "action" in entry:
                        item["strategy"] = entry["action"]
                    if "clear" in entry:
                        item["clear"] = bool(entry["clear"])
                    if "delay" in entry:
                        item["delay"] = entry["delay"]
                    instructions.append(item)
                elif isinstance(entry, (list, tuple)) and len(entry) == 2:
                    selector, value = entry
                    instructions.append({"selector": selector, "value": value})
                else:
                    raise TypeError(
                        "fields must be a mapping, or a sequence of "
                        "two-tuples/mappings with 'selector' and 'value'."
                    )
        normalized: List[FieldInstruction] = []
        for item in instructions:
            selector = str(item.get("selector") or "").strip()
            if not selector:
                raise ValueError("Field selector must be a non-empty string.")
            normalized.append({**item, "selector": selector})
        if not normalized:
            raise ValueError("fields must include at least one entry.")
        return normalized

    def _fill_fields_on_page(
        self,
        page: Page,
        instructions: Sequence[FieldInstruction],
        *,
        timeout: int,
        clear: bool,
    ) -> List[Dict[str, object]]:
        results: List[Dict[str, object]] = []
        allowed_strategies = {"fill", "type", "check", "uncheck", "select"}
        for instruction in instructions:
            selector = instruction["selector"]
            value = instruction.get("value")
            strategy_raw = instruction.get("strategy")
            strategy = strategy_raw.lower() if isinstance(strategy_raw, str) else None
            entry_clear = bool(instruction.get("clear")) if "clear" in instruction else clear

            action = ""
            if strategy and strategy not in allowed_strategies:
                raise ValueError(f"Unsupported field strategy: {strategy_raw!r}.")

            if strategy in {"check", "uncheck"}:
                should_check = strategy == "check"
            elif isinstance(value, bool):
                should_check = value
                strategy = "check" if value else "uncheck"
            else:
                should_check = None

            if should_check is not None:
                locator = page.locator(selector)
                if bool(should_check):
                    locator.check(timeout=timeout)
                    action = "check"
                    effective_value: object = True
                else:
                    locator.uncheck(timeout=timeout)
                    action = "uncheck"
                    effective_value = False
            elif strategy == "select" or self._is_select_value(value):
                selected = self._select_option(page, selector, value, timeout=timeout)
                action = "select"
                effective_value = selected
            elif strategy == "type" or not entry_clear:
                text = "" if value is None else str(value)
                delay = instruction.get("delay")
                type_kwargs = {"delay": float(delay)} if isinstance(delay, (int, float)) else {}
                page.type(selector, text, timeout=timeout, **type_kwargs)
                action = "type"
                effective_value = text
            else:
                text = "" if value is None else str(value)
                page.fill(selector, text, timeout=timeout)
                action = "fill"
                effective_value = text

            results.append(
                {
                    "selector": selector,
                    "action": action or "fill",
                    "value": effective_value,
                }
            )
        return results

    def _is_select_value(self, value: Any) -> bool:
        if isinstance(value, dict):
            return any(key in value for key in ("value", "label", "index"))
        if isinstance(value, (list, tuple)):
            return all(
                isinstance(item, (str, dict))
                for item in value
            )
        return False

    def _select_option(
        self,
        page: Page,
        selector: str,
        value: Any,
        *,
        timeout: int,
    ) -> Sequence[str]:
        if isinstance(value, dict):
            option = self._normalize_select_option(value)
            return page.select_option(selector, option, timeout=timeout)
        if isinstance(value, (list, tuple)):
            options: List[dict[str, str] | str] = []
            for item in value:
                if isinstance(item, dict):
                    options.append(self._normalize_select_option(item))
                else:
                    options.append(str(item))
            return page.select_option(selector, options, timeout=timeout)
        return page.select_option(selector, str(value), timeout=timeout)

    def _normalize_select_option(self, option: Mapping[str, Any]) -> Dict[str, str]:
        allowed_keys = {"value", "label", "index"}
        normalized: Dict[str, str] = {}
        for key in allowed_keys:
            if key in option and option[key] is not None:
                normalized[key] = str(option[key])
        if not normalized:
            raise ValueError("Select option mappings must include 'value', 'label', or 'index'.")
        return normalized


    @contextmanager
    def _open_page(self, url: Optional[str], *, wait_until: str) -> Iterator[Page]:
        wait_state = self._validate_wait_state(wait_until)
        if self._persist_context:
            page = self._ensure_persistent_page()
            if url:
                target = url.strip()
                if not target:
                    raise ValueError("url must be a non-empty string.")
                if self._urls_differ(page.url, target):
                    page.goto(target, wait_until=wait_state)
                else:
                    page.wait_for_load_state(wait_state)
            elif not page.url:
                raise ValueError(
                    "A non-empty url is required for the initial navigation when "
                    "persist_context is enabled."
                )
            yield page
        else:
            if not url:
                raise ValueError("url must be a non-empty string.")
            target = url.strip()
            if not target:
                raise ValueError("url must be a non-empty string.")
            browser = self._ensure_browser()
            context = browser.new_context()
            page = context.new_page()
            try:
                page.goto(target, wait_until=wait_state)
                yield page
            finally:
                context.close()

    def _ensure_persistent_page(self) -> Page:
        browser = self._ensure_browser()
        if self._context is None:
            self._context = browser.new_context()
            try:
                self._context.set_default_timeout(self._default_timeout_ms)
            except Exception:
                pass
        if self._page is None or self._page.is_closed():
            self._page = self._context.new_page()
            try:
                self._page.set_default_timeout(self._default_timeout_ms)
            except Exception:
                pass
        return self._page

    def _urls_differ(self, current: str, target: str) -> bool:
        if not current:
            return True
        if current == target:
            return False
        return current.rstrip("/") != target.rstrip("/")

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


def create_browserbot(
    *,
    headless: bool = True,
    persist_context: bool = False,
) -> BrowserBot:
    """Factory helper for parity with existing usage sites."""
    return BrowserBot(headless=headless, persist_context=persist_context)


__all__ = ["BrowserBot", "create_browserbot"]
