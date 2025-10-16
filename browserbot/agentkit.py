"""Lightweight browser agent kit with Playwright pre-auth support.

This module exposes two primary entry points:

* :class:`BrowserAgent` – manages Playwright startup, session reuse, and
  domain-specific login flows plus common page actions.
* :class:`BrowserAgentMCPServer` – wraps a ``BrowserAgent`` and exposes
  Model Context Protocol style tools for navigation, interaction, text extraction,
  and long-lived session control.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple, Union
from urllib.parse import urlparse
from uuid import uuid4

from playwright.sync_api import Browser, BrowserContext, Page, Playwright, TimeoutError, sync_playwright

STEALTH_ARGS: tuple[str, ...] = (
    "--disable-blink-features=AutomationControlled",
    "--disable-infobars",
    "--disable-web-security",
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--start-maximized",
    "--disable-extensions",
    "--disable-default-apps",
    "--disable-popup-blocking",
    "--disable-hang-monitor",
)

ALLOWED_WAIT_STATES = {"load", "domcontentloaded", "networkidle"}

@dataclass(frozen=True)
class DomainConfig:
    """Configuration describing how to authenticate and cache sessions."""

    domain: str
    login_url: str
    instructions: str
    session_path: Path
    persistent_profile_path: Path
    launch_args: tuple[str, ...] = STEALTH_ARGS


@dataclass
class _SessionState:
    """Internal structure for tracking open Playwright sessions."""

    context: BrowserContext
    page: Page

    def close(self) -> None:
        """Close the page and its backing context."""
        try:
            self.page.close()
        except Exception:
            pass
        try:
            self.context.close()
        except Exception:
            pass


def default_domain_configs(base_dir: Optional[Path] = None) -> Dict[str, DomainConfig]:
    """Return the default domain configuration map (currently just Gmail)."""
    root = base_dir or Path(__file__).resolve().parent
    tmp_dir = root / "tmp"
    session_dir = tmp_dir / "sessions"
    profile_dir = tmp_dir / "stealth-profile"
    session_dir.mkdir(parents=True, exist_ok=True)
    profile_dir.mkdir(parents=True, exist_ok=True)

    gmail_domain = "mail.google.com"
    return {
        gmail_domain: DomainConfig(
            domain=gmail_domain,
            login_url="https://mail.google.com/",
            instructions=(
                "Sign in with your Google account. Complete any MFA prompts. "
                "Return to the terminal once your inbox is visible."
            ),
            session_path=session_dir / "mail.google.com.json",
            persistent_profile_path=profile_dir,
        )
    }


class BrowserAgent(AbstractContextManager["BrowserAgent"]):
    """Manage Playwright lifecycle plus domain-specific pre-auth flows."""

    def __init__(
        self,
        *,
        headless: bool = True,
        domain_configs: Optional[Mapping[str, DomainConfig]] = None,
    ) -> None:
        self._headless = headless
        self._configs: Dict[str, DomainConfig] = dict(domain_configs or default_domain_configs())
        for cfg in self._configs.values():
            cfg.session_path.parent.mkdir(parents=True, exist_ok=True)
            cfg.persistent_profile_path.mkdir(parents=True, exist_ok=True)
        self._sessions: Dict[str, _SessionState] = {}
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None

    def __enter__(self) -> "BrowserAgent":
        self.startup()
        return self

    def __exit__(self, *exc_info) -> None:
        self.shutdown()

    def startup(self) -> None:
        """Boot Playwright and launch Chromium if not already running."""
        if self._playwright is not None:
            return
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=self._headless)

    def shutdown(self) -> None:
        """Close Chromium and stop Playwright if running."""
        for session_id in list(self._sessions.keys()):
            session = self._pop_session(session_id, suppress_errors=True)
            if session is None:
                continue
            session.close()
        if self._browser is not None:
            self._browser.close()
            self._browser = None
        if self._playwright is not None:
            self._playwright.stop()
            self._playwright = None

    def ensure_login(self, domain: str, *, force: bool = False) -> None:
        """Ensure the stored session for ``domain`` is available."""
        config = self._config_for(domain)
        if not force and self._existing_storage_path(config) is not None:
            return
        self._run_manual_login(config)

    def navigate(self, url: str, *, wait_until: str = "load") -> Dict[str, Any]:
        """Navigate to ``url`` using an authenticated context when possible."""
        context, page, error = self._open_page(url, wait_until=wait_until, operation="navigate")
        try:
            if error is not None:
                return error
            return {"final_url": page.url, "title": page.title()}
        finally:
            context.close()

    def extract_text(
        self,
        url: str,
        selector: str,
        *,
        wait_until: str = "load",
        timeout_ms: int = 5000,
    ) -> Dict[str, Any]:
        """Return the text content of ``selector`` after visiting ``url``."""
        if not selector:
            raise ValueError("selector must be a non-empty string.")
        context, page, error = self._open_page(url, wait_until=wait_until, operation="extract_text")
        try:
            if error is not None:
                return error
            try:
                element = page.wait_for_selector(selector, timeout=timeout_ms)
            except TimeoutError:
                return self._timeout_result(
                    "extract_text",
                    selector=selector,
                    url=url,
                    final_url=page.url,
                    timeout_ms=timeout_ms,
                )
            text = element.inner_text()
            return {"final_url": page.url, "title": page.title(), "text": text or ""}
        finally:
            context.close()

    def click(
        self,
        url: str,
        selector: str,
        *,
        wait_until: str = "load",
        post_wait: Optional[str] = "networkidle",
        timeout_ms: int = 5000,
    ) -> Dict[str, Any]:
        """Click ``selector`` on ``url`` and return the resulting page metadata."""
        if not selector:
            raise ValueError("selector must be a non-empty string.")
        context, page, error = self._open_page(url, wait_until=wait_until, operation="click")
        try:
            if error is not None:
                return error
            try:
                page.wait_for_selector(selector, timeout=timeout_ms)
            except TimeoutError:
                return self._timeout_result(
                    "click",
                    selector=selector,
                    url=url,
                    final_url=page.url,
                    timeout_ms=timeout_ms,
                )
            try:
                page.click(selector, timeout=timeout_ms)
            except TimeoutError:
                return self._timeout_result(
                    "click",
                    selector=selector,
                    url=url,
                    final_url=page.url,
                    timeout_ms=timeout_ms,
                    phase="click",
                )
            if post_wait:
                try:
                    page.wait_for_load_state(post_wait)
                except TimeoutError:
                    return self._timeout_result(
                        "click",
                        selector=selector,
                        url=url,
                        final_url=page.url,
                        timeout_ms=timeout_ms,
                        phase="post_wait",
                    )
            return {"final_url": page.url, "title": page.title(), "clicked": selector}
        finally:
            context.close()

    def open_session(self, url: str, *, wait_until: str = "load") -> Dict[str, Any]:
        """Open a persistent session for ``url`` and return its identifier."""
        if wait_until not in ALLOWED_WAIT_STATES:
            allowed = ", ".join(sorted(ALLOWED_WAIT_STATES))
            raise ValueError(f"open_session.wait_until must be one of {{{allowed}}}.")
        context = self._new_context_for_url(url)
        page = context.new_page()
        try:
            page.goto(url, wait_until=wait_until)
        except TimeoutError:
            context.close()
            return self._timeout_result(
                "open_session",
                url=url,
                final_url=page.url,
                timeout_ms=None,
            )
        session_id = self._register_session(context, page)
        return self._session_result(session_id, page)

    def close_session(self, session_id: str) -> Dict[str, Any]:
        """Close the session identified by ``session_id``."""
        session = self._pop_session(session_id)
        if session is None:
            raise KeyError(f"Session '{session_id}' does not exist.")
        meta = self._session_result(session_id, session.page)
        session.close()
        meta["closed"] = True
        return meta

    def session_goto(self, session_id: str, url: str, *, wait_until: str = "load") -> Dict[str, Any]:
        """Navigate an existing session to a new ``url``."""
        if wait_until not in ALLOWED_WAIT_STATES:
            allowed = ", ".join(sorted(ALLOWED_WAIT_STATES))
            raise ValueError(f"session_goto.wait_until must be one of {{{allowed}}}.")
        session = self._require_session(session_id)
        if not url:
            raise ValueError("session_goto.url must be a non-empty string.")
        try:
            session.page.goto(url, wait_until=wait_until)
        except TimeoutError:
            return self._timeout_result(
                "session_goto",
                session_id=session_id,
                url=url,
                final_url=session.page.url,
                timeout_ms=None,
            )
        return self._session_result(session_id, session.page)

    def session_extract_text(
        self,
        session_id: str,
        selector: str,
        *,
        timeout_ms: int = 5000,
    ) -> Dict[str, Any]:
        """Extract text from ``selector`` within an existing session page."""
        if not selector:
            raise ValueError("session_extract_text.selector must be a non-empty string.")
        session = self._require_session(session_id)
        try:
            element = session.page.wait_for_selector(selector, timeout=timeout_ms)
        except TimeoutError:
            return self._timeout_result(
                "session_extract_text",
                session_id=session_id,
                selector=selector,
                final_url=session.page.url,
                timeout_ms=timeout_ms,
            )
        text = element.inner_text()
        return self._session_result(session_id, session.page, {"text": text or ""})

    def session_click(
        self,
        session_id: str,
        selector: str,
        *,
        timeout_ms: int = 5000,
        post_wait: Optional[str] = "networkidle",
    ) -> Dict[str, Any]:
        """Click ``selector`` within an existing session page."""
        if not selector:
            raise ValueError("session_click.selector must be a non-empty string.")
        if post_wait is not None and post_wait not in ALLOWED_WAIT_STATES:
            allowed = ", ".join(sorted(ALLOWED_WAIT_STATES))
            raise ValueError(f"session_click.post_wait must be one of {{{allowed}}} or None.")
        session = self._require_session(session_id)
        page = session.page
        try:
            page.wait_for_selector(selector, timeout=timeout_ms)
        except TimeoutError:
            return self._timeout_result(
                "session_click",
                session_id=session_id,
                selector=selector,
                final_url=page.url,
                timeout_ms=timeout_ms,
            )
        try:
            page.click(selector, timeout=timeout_ms)
        except TimeoutError:
            return self._timeout_result(
                "session_click",
                session_id=session_id,
                selector=selector,
                final_url=page.url,
                timeout_ms=timeout_ms,
                phase="click",
            )
        if post_wait:
            try:
                page.wait_for_load_state(post_wait)
            except TimeoutError:
                return self._timeout_result(
                    "session_click",
                    session_id=session_id,
                    selector=selector,
                    final_url=page.url,
                    timeout_ms=timeout_ms,
                    phase="post_wait",
                )
        return self._session_result(session_id, page, {"clicked": selector})

    def _ensure_storage_state(self, config: DomainConfig) -> Optional[str]:
        """Return a storage state path, prompting for login when necessary."""
        storage_path = self._existing_storage_path(config)
        if storage_path is not None:
            return storage_path
        self._run_manual_login(config)
        return self._existing_storage_path(config)

    def _existing_storage_path(self, config: DomainConfig) -> Optional[str]:
        """Return the storage state path if it exists."""
        if config.session_path.exists():
            return str(config.session_path)
        return None

    def _register_session(self, context: BrowserContext, page: Page) -> str:
        """Store the context/page pair and return a new session identifier."""
        session_id = str(uuid4())
        while session_id in self._sessions:
            session_id = str(uuid4())
        self._sessions[session_id] = _SessionState(context=context, page=page)
        return session_id

    def _session_result(
        self,
        session_id: str,
        page: Page,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Return a combined payload describing the session page."""
        result: Dict[str, Any] = {
            "session_id": session_id,
            "final_url": page.url,
            "title": page.title(),
        }
        if extra:
            result.update(extra)
        return result

    def _require_session(self, session_id: str) -> _SessionState:
        """Return the session identified by ``session_id`` or raise."""
        try:
            return self._sessions[session_id]
        except KeyError as exc:
            raise KeyError(f"Session '{session_id}' does not exist.") from exc

    def _pop_session(self, session_id: str, *, suppress_errors: bool = False) -> Optional[_SessionState]:
        """Remove and return the session identified by ``session_id``."""
        try:
            return self._sessions.pop(session_id)
        except KeyError:
            if suppress_errors:
                return None
            raise KeyError(f"Session '{session_id}' does not exist.")

    def _open_page(
        self,
        url: str,
        *,
        wait_until: str,
        operation: str,
    ) -> Tuple[BrowserContext, Page, Optional[Dict[str, Any]]]:
        """Return a ``(context, page)`` tuple after navigating to ``url``."""
        if not url:
            raise ValueError("URL must be a non-empty string.")
        if wait_until not in ALLOWED_WAIT_STATES:
            allowed = ", ".join(sorted(ALLOWED_WAIT_STATES))
            raise ValueError(f"wait_until must be one of {{{allowed}}}.")
        context = self._new_context_for_url(url)
        page = context.new_page()
        try:
            page.goto(url, wait_until=wait_until)
        except TimeoutError:
            error = self._timeout_result(
                operation,
                url=url,
                final_url=page.url,
                timeout_ms=None,
                phase="goto",
            )
            return context, page, error
        return context, page, None

    def _timeout_result(
        self,
        operation: str,
        *,
        selector: Optional[str] = None,
        session_id: Optional[str] = None,
        url: Optional[str] = None,
        final_url: Optional[str] = None,
        timeout_ms: Optional[int],
        phase: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Return a structured payload describing a timeout."""
        result: Dict[str, Any] = {"error": "timeout", "operation": operation}
        if session_id is not None:
            result["session_id"] = session_id
        if selector is not None:
            result["selector"] = selector
        if url is not None:
            result["url"] = url
        if final_url is not None:
            result["final_url"] = final_url
        if timeout_ms is not None:
            result["timeout_ms"] = timeout_ms
        if phase is not None:
            result["phase"] = phase
        return result

    def _new_context_for_url(self, url: str) -> BrowserContext:
        """Create a browser context hydrated with any known domain session."""
        self.startup()
        browser = self._require_browser()
        domain = urlparse(url).netloc or url
        config = self._configs.get(domain)
        storage_state = self._ensure_storage_state(config) if config else None
        return browser.new_context(storage_state=storage_state)

    def _run_manual_login(self, config: DomainConfig) -> None:
        """Launch a persistent context so the user can authenticate manually."""
        self.startup()
        playwright = self._require_playwright()
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(config.persistent_profile_path),
            headless=self._headless,
            args=list(config.launch_args),
            viewport=None,
        )
        try:
            page = context.new_page()
            page.goto(config.login_url)
            print(f"[PreAuth] Manual login required for {config.domain}.")
            if config.instructions:
                print(f"[PreAuth] {config.instructions}")
            input("Press Enter after completing login...")
            context.storage_state(path=str(config.session_path))
        finally:
            context.close()

    def _config_for(self, domain: str) -> DomainConfig:
        """Return the :class:`DomainConfig` for ``domain`` or raise."""
        try:
            return self._configs[domain]
        except KeyError as exc:
            raise KeyError(f"No domain configuration defined for '{domain}'.") from exc

    def _require_browser(self) -> Browser:
        if self._browser is None:
            raise RuntimeError("Browser is not started. Call startup() first.")
        return self._browser

    def _require_playwright(self) -> Playwright:
        if self._playwright is None:
            raise RuntimeError("Playwright is not started. Call startup() first.")
        return self._playwright


class BrowserAgentMCPServer(AbstractContextManager["BrowserAgentMCPServer"]):
    """Expose a ``BrowserAgent`` as a minimal MCP-compatible server."""

    def __init__(self, agent: BrowserAgent) -> None:
        self._agent = agent

    def __enter__(self) -> "BrowserAgentMCPServer":
        self.startup()
        return self

    def __exit__(self, *exc_info) -> None:
        self.shutdown()

    def startup(self) -> None:
        """Start the underlying browser agent."""
        self._agent.startup()

    def shutdown(self) -> None:
        """Shut down the underlying browser agent."""
        self._agent.shutdown()

    def handle(
        self,
        tool_name: str,
        arguments: Optional[Mapping[str, object]] = None,
    ) -> Dict[str, object]:
        """Execute a registered tool (`navigate`, `extract_text`, or `click`)."""
        args = dict(arguments or {})
        if tool_name == "navigate":
            return self._handle_navigate(args)
        if tool_name == "extract_text":
            return self._handle_extract_text(args)
        if tool_name == "click":
            return self._handle_click(args)
        if tool_name == "open_session":
            return self._handle_open_session(args)
        if tool_name == "session_goto":
            return self._handle_session_goto(args)
        if tool_name == "session_extract_text":
            return self._handle_session_extract_text(args)
        if tool_name == "session_click":
            return self._handle_session_click(args)
        if tool_name == "close_session":
            return self._handle_close_session(args)
        raise KeyError(f"Tool '{tool_name}' is not registered.")

    def _handle_navigate(self, args: Dict[str, object]) -> Dict[str, str]:
        url = args.get("url")
        if not isinstance(url, str) or not url:
            raise ValueError("navigate.url must be a non-empty string.")
        wait_until = args.get("wait_until", "load")
        if not isinstance(wait_until, str):
            raise ValueError("navigate.wait_until must be a string.")
        if wait_until not in ALLOWED_WAIT_STATES:
            allowed = ", ".join(sorted(ALLOWED_WAIT_STATES))
            raise ValueError(f"navigate.wait_until must be one of {{{allowed}}}.")
        return self._agent.navigate(url, wait_until=wait_until)

    def _handle_extract_text(self, args: Dict[str, object]) -> Dict[str, str]:
        url = args.get("url")
        selector = args.get("selector")
        if not isinstance(url, str) or not url:
            raise ValueError("extract_text.url must be a non-empty string.")
        if not isinstance(selector, str) or not selector:
            raise ValueError("extract_text.selector must be a non-empty string.")
        wait_until = args.get("wait_until", "load")
        if not isinstance(wait_until, str):
            raise ValueError("extract_text.wait_until must be a string.")
        if wait_until not in ALLOWED_WAIT_STATES:
            allowed = ", ".join(sorted(ALLOWED_WAIT_STATES))
            raise ValueError(f"extract_text.wait_until must be one of {{{allowed}}}.")
        timeout_ms = args.get("timeout_ms", 5000)
        if not isinstance(timeout_ms, int):
            raise ValueError("extract_text.timeout_ms must be an integer.")
        return self._agent.extract_text(url, selector, wait_until=wait_until, timeout_ms=timeout_ms)

    def _handle_click(self, args: Dict[str, object]) -> Dict[str, str]:
        url = args.get("url")
        selector = args.get("selector")
        if not isinstance(url, str) or not url:
            raise ValueError("click.url must be a non-empty string.")
        if not isinstance(selector, str) or not selector:
            raise ValueError("click.selector must be a non-empty string.")
        wait_until = args.get("wait_until", "load")
        if not isinstance(wait_until, str):
            raise ValueError("click.wait_until must be a string.")
        if wait_until not in ALLOWED_WAIT_STATES:
            allowed = ", ".join(sorted(ALLOWED_WAIT_STATES))
            raise ValueError(f"click.wait_until must be one of {{{allowed}}}.")
        post_wait = args.get("post_wait", "networkidle")
        if post_wait is not None and not isinstance(post_wait, str):
            raise ValueError("click.post_wait must be ``None`` or a string.")
        if isinstance(post_wait, str) and post_wait not in ALLOWED_WAIT_STATES:
            allowed = ", ".join(sorted(ALLOWED_WAIT_STATES))
            raise ValueError(f"click.post_wait must be one of {{{allowed}}} or None.")
        timeout_ms = args.get("timeout_ms", 5000)
        if not isinstance(timeout_ms, int):
            raise ValueError("click.timeout_ms must be an integer.")
        return self._agent.click(
            url,
            selector,
            wait_until=wait_until,
            post_wait=post_wait,
            timeout_ms=timeout_ms,
        )

    def _handle_open_session(self, args: Dict[str, object]) -> Dict[str, str]:
        url = args.get("url")
        if not isinstance(url, str) or not url:
            raise ValueError("open_session.url must be a non-empty string.")
        wait_until = args.get("wait_until", "load")
        if not isinstance(wait_until, str):
            raise ValueError("open_session.wait_until must be a string.")
        if wait_until not in ALLOWED_WAIT_STATES:
            allowed = ", ".join(sorted(ALLOWED_WAIT_STATES))
            raise ValueError(f"open_session.wait_until must be one of {{{allowed}}}.")
        return self._agent.open_session(url, wait_until=wait_until)

    def _handle_session_goto(self, args: Dict[str, object]) -> Dict[str, str]:
        session_id = args.get("session_id")
        url = args.get("url")
        if not isinstance(session_id, str) or not session_id:
            raise ValueError("session_goto.session_id must be a non-empty string.")
        if not isinstance(url, str) or not url:
            raise ValueError("session_goto.url must be a non-empty string.")
        wait_until = args.get("wait_until", "load")
        if not isinstance(wait_until, str):
            raise ValueError("session_goto.wait_until must be a string.")
        if wait_until not in ALLOWED_WAIT_STATES:
            allowed = ", ".join(sorted(ALLOWED_WAIT_STATES))
            raise ValueError(f"session_goto.wait_until must be one of {{{allowed}}}.")
        return self._agent.session_goto(session_id, url, wait_until=wait_until)

    def _handle_session_extract_text(self, args: Dict[str, object]) -> Dict[str, str]:
        session_id = args.get("session_id")
        selector = args.get("selector")
        if not isinstance(session_id, str) or not session_id:
            raise ValueError("session_extract_text.session_id must be a non-empty string.")
        if not isinstance(selector, str) or not selector:
            raise ValueError("session_extract_text.selector must be a non-empty string.")
        timeout_ms = args.get("timeout_ms", 5000)
        if not isinstance(timeout_ms, int):
            raise ValueError("session_extract_text.timeout_ms must be an integer.")
        return self._agent.session_extract_text(session_id, selector, timeout_ms=timeout_ms)

    def _handle_session_click(self, args: Dict[str, object]) -> Dict[str, str]:
        session_id = args.get("session_id")
        selector = args.get("selector")
        if not isinstance(session_id, str) or not session_id:
            raise ValueError("session_click.session_id must be a non-empty string.")
        if not isinstance(selector, str) or not selector:
            raise ValueError("session_click.selector must be a non-empty string.")
        timeout_ms = args.get("timeout_ms", 5000)
        if not isinstance(timeout_ms, int):
            raise ValueError("session_click.timeout_ms must be an integer.")
        post_wait = args.get("post_wait", "networkidle")
        if post_wait is not None and not isinstance(post_wait, str):
            raise ValueError("session_click.post_wait must be ``None`` or a string.")
        if isinstance(post_wait, str) and post_wait not in ALLOWED_WAIT_STATES:
            allowed = ", ".join(sorted(ALLOWED_WAIT_STATES))
            raise ValueError(f"session_click.post_wait must be one of {{{allowed}}} or None.")
        return self._agent.session_click(
            session_id,
            selector,
            timeout_ms=timeout_ms,
            post_wait=post_wait,
        )

    def _handle_close_session(self, args: Dict[str, object]) -> Dict[str, object]:
        session_id = args.get("session_id")
        if not isinstance(session_id, str) or not session_id:
            raise ValueError("close_session.session_id must be a non-empty string.")
        return self._agent.close_session(session_id)


def create_agent(*, headless: bool = True) -> BrowserAgent:
    """Return a ``BrowserAgent`` instance with default Gmail configuration."""
    return BrowserAgent(headless=headless)


def create_mcp_server(*, headless: bool = True) -> BrowserAgentMCPServer:
    """Convenience helper that wraps ``create_agent`` in an MCP server."""
    agent = create_agent(headless=headless)
    return BrowserAgentMCPServer(agent)


__all__ = [
    "BrowserAgent",
    "BrowserAgentMCPServer",
    "DomainConfig",
    "create_agent",
    "create_mcp_server",
    "default_domain_configs",
]
