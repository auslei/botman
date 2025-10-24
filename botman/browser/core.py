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
import logging
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import urlparse

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Error,
    Page,
    Playwright,
    sync_playwright,
)

from .auth import DomainConfig, default_domain_configs

ALLOWED_WAIT_STATES = {"load", "domcontentloaded", "networkidle"}
ALLOWED_SELECTOR_STATES = {"attached", "detached", "visible", "hidden"}

FieldInstruction = Dict[str, Any]

logger = logging.getLogger(__name__)


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
        domain_configs: Optional[Mapping[str, DomainConfig]] = None,
    ) -> None:
        self._headless = headless
        self._launch_args = tuple(launch_args or ())
        self._default_timeout_ms = default_timeout_ms
        self._persist_context = persist_context
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._domain_configs: Dict[str, DomainConfig] = dict(
            domain_configs or default_domain_configs()
        )
        for cfg in self._domain_configs.values():
            cfg.storage_state_path.parent.mkdir(parents=True, exist_ok=True)
        self._storage_state_cache: Dict[str, Path] = {
            domain: cfg.storage_state_path
            for domain, cfg in self._domain_configs.items()
            if cfg.storage_state_path.exists()
        }
        self._current_storage_state_key: Optional[str] = None

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
        self._close_persistent_context()
        self._current_storage_state_key = None
        if self._browser is not None:
            self._browser.close()
            self._browser = None
        if self._playwright is not None:
            self._playwright.stop()
            self._playwright = None

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def ensure_login(self, domain: str, *, force: bool = False) -> Dict[str, Any]:
        """Ensure a cached Playwright storage state exists for ``domain``."""

        config = self._domain_configs.get(domain)
        if config is None:
            raise ValueError(f"No authentication configuration for {domain!r}.")

        storage_path = config.storage_state_path
        if not force and storage_path.exists():
            self._storage_state_cache[domain] = storage_path
            return {
                "domain": domain,
                "storage_state": str(storage_path),
                "created": False,
            }

        self._run_manual_login(config)
        if storage_path.exists():
            self._storage_state_cache[domain] = storage_path
            self._invalidate_persistent_context()
            return {
                "domain": domain,
                "storage_state": str(storage_path),
                "created": True,
            }

        raise RuntimeError(
            f"Manual login for {domain!r} did not populate {storage_path}."
        )

    def navigate(self, url: str, *, wait_until: str = "load") -> Dict[str, str]:
        """Navigate to ``url`` and return the final URL and page title."""
        self._log_call("navigate", url=url, wait_until=wait_until)
        with self._open_page(url, wait_until=wait_until) as page:
            result = {"final_url": page.url, "title": page.title()}
            self._log_result("navigate", result)
            return result

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
        self._log_call(
            "list_links",
            url=url,
            wait_until=wait_until,
            limit=limit,
            root_selector=root_selector,
            link_selector=link_selector,
        )
        with self._open_page(url, wait_until=wait_until) as page:
            links, truncated, total = self._collect_links(
                page,
                limit=limit,
                root_selector=root_selector,
                link_selector=link_selector,
            )
            result = {
                "final_url": page.url,
                "title": page.title(),
                "links": links,
                "count": total,
                "truncated": truncated,
            }
            self._log_result("list_links", result)
            return result

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
        self._log_call(
            "extract_text",
            url=url,
            selector=selector,
            wait_until=wait_until,
            timeout_ms=timeout_ms,
        )
        effective_timeout = timeout_ms or self._default_timeout_ms
        with self._open_page(url, wait_until=wait_until) as page:
            element = page.wait_for_selector(selector, timeout=effective_timeout)
            text = element.inner_text() if element else ""
            result = {
                "final_url": page.url,
                "title": page.title(),
                "selector": selector,
                "text": text.strip(),
            }
            self._log_result("extract_text", result)
            return result

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
        self._log_call(
            "extract_html",
            url=url,
            wait_until=wait_until,
            selector=selector,
            timeout_ms=timeout_ms,
            inner=inner,
        )
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
            result = {
                "final_url": page.url,
                "title": page.title(),
                "selector": selector,
                "inner": inner,
                "html": html,
            }
            self._log_result("extract_html", result)
            return result

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
        self._log_call(
            "click",
            url=url,
            selector=selector,
            wait_until=wait_until,
            timeout_ms=timeout_ms,
            post_wait=post_wait,
        )
        effective_timeout = timeout_ms or self._default_timeout_ms
        with self._open_page(url, wait_until=wait_until) as page:
            page.wait_for_selector(selector, timeout=effective_timeout)
            page.click(selector, timeout=effective_timeout)
            if post_wait:
                page.wait_for_load_state(post_wait)
            result = {
                "final_url": page.url,
                "title": page.title(),
                "clicked": selector,
            }
            self._log_result("click", result)
            return result

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
        self._log_call(
            "fill_fields",
            url=url,
            wait_until=wait_until,
            timeout_ms=timeout_ms,
            clear_existing=clear_existing,
            fields_count=len(instructions),
        )
        effective_timeout = timeout_ms or self._default_timeout_ms
        with self._open_page(url, wait_until=wait_until) as page:
            filled = self._fill_fields_on_page(
                page,
                instructions,
                timeout=effective_timeout,
                clear=clear_existing,
            )
            result = {
                "final_url": page.url,
                "title": page.title(),
                "filled": filled,
                "count": len(filled),
            }
            self._log_result("fill_fields", result)
            return result

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
        self._log_call(
            "submit_form",
            url=url,
            form_selector=form_selector,
            submit_selector=submit_selector,
            fields_provided=bool(fields),
            wait_until=wait_until,
            timeout_ms=timeout_ms,
            post_wait=post_wait,
            wait_for=wait_for,
            wait_for_state=wait_for_state,
            clear_existing=clear_existing,
        )
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
            result = {
                "final_url": page.url,
                "title": page.title(),
                "submitted": submitted,
                "filled": filled,
                "waited_for": wait_for,
                "waited_state": waited_state,
            }
            self._log_result("submit_form", result)
            return result

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
        self._log_call(
            "wait_for_selector",
            url=url,
            selector=selector,
            wait_until=wait_until,
            timeout_ms=timeout_ms,
            state=state,
        )
        wait_state = self._validate_selector_state(state)
        effective_timeout = timeout_ms or self._default_timeout_ms
        with self._open_page(url, wait_until=wait_until) as page:
            element = page.wait_for_selector(
                selector,
                timeout=effective_timeout,
                state=wait_state,
            )
            result = {
                "final_url": page.url,
                "title": page.title(),
                "selector": selector,
                "state": wait_state,
                "element_found": element is not None,
            }
            self._log_result("wait_for_selector", result)
            return result

    def wait(
        self,
        url: Optional[str] = None,
        *,
        delay_ms: int = 1000,
        wait_until: str = "load",
    ) -> Dict[str, object]:
        """Pause execution for ``delay_ms`` milliseconds.

        With ``persist_context`` enabled, ``url`` may be ``None`` to
        reuse the current page.
        """
        if delay_ms < 0:
            raise ValueError("delay_ms must be non-negative.")
        self._log_call("wait", url=url, delay_ms=delay_ms, wait_until=wait_until)
        with self._open_page(url, wait_until=wait_until) as page:
            page.wait_for_timeout(delay_ms)
            result = {
                "final_url": page.url,
                "title": page.title(),
                "delay_ms": delay_ms,
            }
            self._log_result("wait", result)
            return result

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
        self._log_call(
            "screenshot",
            url=url,
            wait_until=wait_until,
            selector=selector,
            full_page=full_page,
            image_format=image_format,
            quality=quality,
        )
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
            result = {
                "final_url": page.url,
                "title": page.title(),
                "image_format": image_format,
                "screenshot_base64": encoded,
                "full_page": full_page,
                "selector": selector,
            }
            self._log_result("screenshot", result)
            return result

    def describe_dom(
        self,
        url: Optional[str] = None,
        *,
        wait_until: str = "load",
    ) -> Dict[str, object]:
        """Return a high-level structural outline of the current page."""
        self._log_call("describe_dom", url=url, wait_until=wait_until)
        script = """
        () => {
            const headings = Array.from(document.querySelectorAll('h1, h2, h3, h4, h5, h6')).map((el, index) => ({
                index: index + 1,
                tag: el.tagName.toLowerCase(),
                text: (el.innerText || '').trim(),
                id: el.id || null,
            }));

            const landmarks = [];
            const landmarkSelectors = [
                { selector: 'header', role: 'banner' },
                { selector: 'nav', role: 'navigation' },
                { selector: 'main', role: 'main' },
                { selector: 'aside', role: 'complementary' },
                { selector: 'footer', role: 'contentinfo' },
            ];
            landmarkSelectors.forEach(({ selector, role }) => {
                document.querySelectorAll(selector).forEach((el) => {
                    const text = (el.innerText || '').trim().replace(/\\s+/g, ' ').slice(0, 120);
                    landmarks.push({
                        index: landmarks.length + 1,
                        role,
                        selector,
                        text,
                    });
                });
            });
            const ariaLandmarks = ['banner', 'navigation', 'main', 'complementary', 'contentinfo', 'region'];
            document.querySelectorAll('[role]').forEach((el) => {
                const role = el.getAttribute('role');
                if (ariaLandmarks.includes(role)) {
                    const text = (el.innerText || '').trim().replace(/\\s+/g, ' ').slice(0, 120);
                    landmarks.push({
                        index: landmarks.length + 1,
                        role,
                        selector: `[role=\"${role}\"]`,
                        text,
                    });
                }
            });

            const formsSummary = Array.from(document.forms || []).map((form, index) => ({
                index: index + 1,
                id: form.id || null,
                name: form.getAttribute('name') || null,
                method: (form.method || 'get').toLowerCase(),
                action: form.getAttribute('action') || '',
                fields: form.querySelectorAll('input, textarea, select').length,
            }));

            const metadata = {
                title: document.title || '',
                description: (document.querySelector('meta[name=\"description\"]') || {}).content || null,
                language: document.documentElement.getAttribute('lang') || null,
            };

            return {
                metadata,
                headings,
                landmarks,
                forms_summary: formsSummary,
                counts: {
                    buttons: document.querySelectorAll('button, [role=\"button\"], input[type=\"button\"], input[type=\"submit\"], input[type=\"reset\"], input[type=\"image\"]').length,
                    links: document.querySelectorAll('a[href]').length,
                    images: document.querySelectorAll('img').length,
                },
            };
        }
        """
        with self._open_page(url, wait_until=wait_until) as page:
            summary = page.evaluate(script)
            result = {
                "final_url": page.url,
                "title": page.title(),
                "dom": summary,
            }
            self._log_result("describe_dom", result)
            return result

    def list_forms(
        self,
        url: Optional[str] = None,
        *,
        wait_until: str = "load",
        include_values: bool = True,
    ) -> Dict[str, object]:
        """Inspect forms on the page and return structured field metadata."""
        self._log_call("list_forms", url=url, wait_until=wait_until, include_values=include_values)
        script = """
        ({ includeValues }) => {
            const forms = Array.from(document.forms || []);
            const describeControl = (control) => {
                const tag = control.tagName.toLowerCase();
                const typeAttr = control.getAttribute('type');
                const type = (typeAttr || '').toLowerCase();
                const name = control.getAttribute('name') || null;
                const id = control.id || null;
                const placeholder = control.getAttribute('placeholder') || null;
                const required = !!control.required;
                const ariaLabel = control.getAttribute('aria-label') || null;
                const visible = !!(control.offsetParent || control.getClientRects().length);
                const disabled = !!control.disabled;
                const label = (() => {
                    if (control.labels && control.labels.length) {
                        return control.labels[0].innerText.trim();
                    }
                    const labelledBy = control.getAttribute('aria-labelledby');
                    if (labelledBy) {
                        const text = labelledBy
                            .split(/\\s+/)
                            .map((id) => document.getElementById(id))
                            .filter(Boolean)
                            .map((el) => (el.innerText || '').trim())
                            .join(' ');
                        if (text) {
                            return text;
                        }
                    }
                    const parentLabel = control.closest('label');
                    if (parentLabel) {
                        return parentLabel.innerText.trim();
                    }
                    if (ariaLabel) {
                        return ariaLabel;
                    }
                    return null;
                })();

                const base = {
                    tag,
                    type: type || (tag === 'textarea' ? 'textarea' : tag === 'select' ? 'select' : (typeAttr || '').toLowerCase() || 'text'),
                    name,
                    id,
                    label,
                    placeholder,
                    required,
                    disabled,
                    visible,
                };

                if (includeValues) {
                    if (tag === 'input' && ['checkbox', 'radio'].includes(type)) {
                        base.checked = !!control.checked;
                        base.value = control.value || null;
                    } else if (tag === 'select') {
                        base.multiple = !!control.multiple;
                        base.options = Array.from(control.options || []).map((option, index) => ({
                            index: index + 1,
                            value: option.value,
                            text: option.text.trim(),
                            selected: !!option.selected,
                        }));
                    } else if (tag === 'textarea') {
                        base.value = control.value || '';
                    } else if (tag === 'input') {
                        base.value = control.value || '';
                    }
                }

                return base;
            };

            return forms.map((form, index) => {
                const controls = Array.from(form.querySelectorAll('input, textarea, select, button'));
                const fields = controls
                    .filter((el) => {
                        const tag = el.tagName.toLowerCase();
                        if (tag === 'button') {
                            return false;
                        }
                        const type = (el.getAttribute('type') || '').toLowerCase();
                        return !['submit', 'button', 'reset', 'image'].includes(type);
                    })
                    .map(describeControl);

                const submitControls = controls
                    .filter((el) => {
                        const tag = el.tagName.toLowerCase();
                        const type = (el.getAttribute('type') || '').toLowerCase();
                        return tag === 'button' || ['submit', 'button', 'reset', 'image'].includes(type);
                    })
                    .map((el, submitIndex) => ({
                        index: submitIndex + 1,
                        tag: el.tagName.toLowerCase(),
                        type: (el.getAttribute('type') || (el.tagName.toLowerCase() === 'button' ? 'submit' : '')).toLowerCase(),
                        text: (el.innerText || el.value || '').trim(),
                        name: el.getAttribute('name') || null,
                        id: el.id || null,
                        aria_label: el.getAttribute('aria-label') || null,
                    }));

                return {
                    index: index + 1,
                    id: form.id || null,
                    name: form.getAttribute('name') || null,
                    method: (form.method || 'get').toLowerCase(),
                    action: form.getAttribute('action') || '',
                    autocomplete: form.getAttribute('autocomplete') || null,
                    fields,
                    submit_controls: submitControls,
                };
            });
        }
        """
        with self._open_page(url, wait_until=wait_until) as page:
            forms = page.evaluate(script, {"includeValues": include_values})
            result = {
                "final_url": page.url,
                "title": page.title(),
                "forms": forms,
                "count": len(forms),
            }
            self._log_result("list_forms", result)
            return result

    def list_buttons(
        self,
        url: Optional[str] = None,
        *,
        wait_until: str = "load",
    ) -> Dict[str, object]:
        """Return metadata about buttons and button-like elements on the page."""
        self._log_call("list_buttons", url=url, wait_until=wait_until)
        script = """
        () => {
            const uniqueElements = new Set();
            const addElements = (selector) => {
                document.querySelectorAll(selector).forEach((el) => uniqueElements.add(el));
            };
            addElements('button');
            addElements('[role=\"button\"]');
            addElements('input[type=\"button\"], input[type=\"submit\"], input[type=\"reset\"], input[type=\"image\"]');

            return Array.from(uniqueElements).map((el, index) => {
                const tag = el.tagName.toLowerCase();
                const typeAttr = el.getAttribute('type');
                const type = (typeAttr || (tag === 'button' ? 'submit' : '')).toLowerCase();
                const name = el.getAttribute('name') || null;
                const id = el.id || null;
                const role = el.getAttribute('role') || (tag === 'button' ? 'button' : null);
                const text = (el.innerText || el.value || '').trim();
                const ariaLabel = el.getAttribute('aria-label') || null;
                const ariaPressed = el.getAttribute('aria-pressed');
                const disabled = !!(el.disabled || el.getAttribute('aria-disabled') === 'true');
                const visible = !!(el.offsetParent || el.getClientRects().length);
                return {
                    index: index + 1,
                    tag,
                    type,
                    name,
                    id,
                    role,
                    text,
                    aria_label: ariaLabel,
                    aria_pressed: ariaPressed,
                    disabled,
                    visible,
                };
            });
        }
        """
        with self._open_page(url, wait_until=wait_until) as page:
            buttons = page.evaluate(script)
            result = {
                "final_url": page.url,
                "title": page.title(),
                "buttons": buttons,
                "count": len(buttons),
            }
            self._log_result("list_buttons", result)
            return result

    def evaluate_js(
        self,
        url: Optional[str] = None,
        script: str = "",
        *,
        wait_until: str = "load",
        arg: Optional[Any] = None,
    ) -> Dict[str, object]:
        """Evaluate custom JavaScript and return the result."""
        if not script or not isinstance(script, str):
            raise ValueError("script must be a non-empty string.")
        log_payload: Dict[str, Any] = {"url": url, "wait_until": wait_until}
        if arg is not None:
            log_payload["arg_type"] = type(arg).__name__
        self._log_call("evaluate_js", **log_payload)
        with self._open_page(url, wait_until=wait_until) as page:
            try:
                if arg is None:
                    outcome = page.evaluate(script)
                else:
                    outcome = page.evaluate(script, arg)
            except Exception as exc:
                logger.exception("evaluate_js failed: %s", exc)
                raise
            result = {
                "final_url": page.url,
                "title": page.title(),
                "result": outcome,
            }
            self._log_result("evaluate_js", result)
            return result

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

    def _storage_state_for_url(self, url: Optional[str]) -> Optional[Path]:
        if not url:
            return None
        host = urlparse(url).hostname
        if not host:
            return None
        return self._storage_state_for_host(host)

    def _storage_state_for_host(self, host: str) -> Optional[Path]:
        candidate = host.lower()
        while candidate:
            cfg = self._domain_configs.get(candidate)
            if cfg:
                path = cfg.storage_state_path
                if path.exists():
                    self._storage_state_cache[candidate] = path
                    return path
            if "." not in candidate:
                break
            candidate = candidate.split(".", 1)[1]
        return None

    def _run_manual_login(self, config: DomainConfig) -> None:
        from playwright.sync_api import sync_playwright

        logger.info("Starting manual login for domain %s", config.domain)
        print(config.instructions)
        with sync_playwright() as playwright:
            launch_kwargs = dict(config.launch_options)
            headless = launch_kwargs.pop("headless", False)
            browser = playwright.chromium.launch(headless=headless, **launch_kwargs)
            try:
                context = browser.new_context(**config.context_options)
                page = context.new_page()
                page.goto(config.login_url)
                input("Press Enter after the login completes...")
                context.storage_state(path=str(config.storage_state_path))
            finally:
                browser.close()
        logger.info(
            "Stored session for %s at %s", config.domain, config.storage_state_path
        )

    def _invalidate_persistent_context(self) -> None:
        self._close_persistent_context()
        self._current_storage_state_key = None

    def _close_persistent_context(self) -> None:
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


    @contextmanager
    def _open_page(self, url: Optional[str], *, wait_until: str) -> Iterator[Page]:
        wait_state = self._validate_wait_state(wait_until)
        storage_state = self._storage_state_for_url(url)
        if self._persist_context:
            page = self._ensure_persistent_page(storage_state)
            if url:
                target = url.strip()
                if not target:
                    raise ValueError("url must be a non-empty string.")
                if self._urls_differ(page.url, target):
                    page.goto(target, wait_until=wait_state)
                page.wait_for_load_state(wait_state)
            elif not page.url:
                raise ValueError(
                    "A non-empty url is required for the initial navigation when "
                    "persist_context is enabled."
                )
            else:
                page.wait_for_load_state(wait_state)
            yield page
        else:
            if not url:
                raise ValueError("url must be a non-empty string.")
            target = url.strip()
            if not target:
                raise ValueError("url must be a non-empty string.")
            browser = self._ensure_browser()
            context = browser.new_context(
                storage_state=str(storage_state) if storage_state else None
            )
            page = context.new_page()
            try:
                page.goto(target, wait_until=wait_state)
                yield page
            finally:
                context.close()

    def _ensure_persistent_page(self, storage_state: Optional[Path]) -> Page:
        browser = self._ensure_browser()
        storage_key = str(storage_state) if storage_state else None
        needs_new_context = (
            self._context is None
            or self._page is None
            or self._page.is_closed()
            or self._current_storage_state_key != storage_key
        )
        if needs_new_context:
            self._close_persistent_context()
            state_arg = str(storage_state) if storage_state and storage_state.exists() else None
            self._context = browser.new_context(storage_state=state_arg)
            try:
                self._context.set_default_timeout(self._default_timeout_ms)
            except Exception:
                pass
            self._page = self._context.new_page()
            try:
                self._page.set_default_timeout(self._default_timeout_ms)
            except Exception:
                pass
            self._current_storage_state_key = storage_key
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
            logger.debug(
                "collect_links result: total=%s truncated=%s returned=%s",
                total,
                truncated,
                len(links),
            )
            return links, truncated, total
        return [], False, 0

    def _log_call(self, action: str, **kwargs: Any) -> None:
        logger.info("%s call: %s", action, {k: v for k, v in kwargs.items() if v is not None})

    def _log_result(self, action: str, result: Mapping[str, Any]) -> None:
        summary: Dict[str, Any] = {}
        for key, value in result.items():
            if key == "screenshot_base64" and isinstance(value, str):
                summary[key] = f"<{len(value)} chars>"
            elif key == "links" and isinstance(value, list):
                summary[key] = f"<{len(value)} links>"
            elif key == "filled" and isinstance(value, list):
                summary[key] = value
            else:
                summary[key] = value
        logger.info("%s result: %s", action, summary)


def create_browserbot(
    *,
    headless: bool = True,
    persist_context: bool = False,
    domain_configs: Optional[Mapping[str, DomainConfig]] = None,
) -> BrowserBot:
    """Factory helper for parity with existing usage sites."""
    return BrowserBot(
        headless=headless,
        persist_context=persist_context,
        domain_configs=domain_configs,
    )


__all__ = ["BrowserBot", "create_browserbot"]
