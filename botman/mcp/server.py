"""FastMCP server that exposes the lightweight BrowserBot helpers."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from threading import Lock
from typing import Any, Dict, Optional, Sequence

from fastmcp import Context, FastMCP
from playwright.sync_api import Error, TimeoutError

from botman.browser.core import BrowserBot, create_browserbot

mcp = FastMCP(name="botman-browser")


@dataclass
class _AgentBundle:
    bot: BrowserBot
    lock: Lock


_SESSION_KEY_DEFAULT = "__default__"
_session_config: Dict[str, Any] = {"headless": True, "persist_context": True}
_session_agents: Dict[str, _AgentBundle] = {}
_session_registry_lock = Lock()


def configure_browser_agent(
    *,
    headless: bool = True,
    persist_context: bool = True,
) -> None:
    """Set the default BrowserBot configuration and reset existing sessions."""
    global _session_config
    _session_config = {"headless": headless, "persist_context": persist_context}
    _reset_sessions()


def _call_agent(
    method: str,
    client_id: Optional[str],
    *args,
    **kwargs,
) -> Dict[str, Any]:
    """Invoke ``BrowserBot`` methods inside a session-aware, thread-safe section."""
    bundle = _get_agent_bundle(client_id)
    with bundle.lock:
        agent_method = getattr(bundle.bot, method)
        return agent_method(*args, **kwargs)


async def _run_agent(
    method: str,
    *args,
    client_id: Optional[str] = None,
    **kwargs,
) -> Dict[str, Any]:
    return await asyncio.to_thread(
        _call_with_errors,
        method,
        client_id,
        args,
        kwargs,
    )


def _call_with_errors(
    method: str,
    client_id: Optional[str],
    args: Sequence[Any],
    kwargs: Dict[str, Any],
) -> Dict[str, Any]:
    try:
        return _call_agent(method, client_id, *args, **kwargs)
    except TimeoutError as exc:
        return {"error": "timeout", "operation": method, "message": str(exc)}
    except Error as exc:
        return {"error": "playwright", "operation": method, "message": str(exc)}
    except Exception as exc:
        return {"error": "unexpected", "operation": method, "message": str(exc)}


def _reset_sessions() -> None:
    """Shutdown and clear all active BrowserBot sessions."""
    with _session_registry_lock:
        bundles = list(_session_agents.values())
        _session_agents.clear()
    for bundle in bundles:
        try:
            bundle.bot.shutdown()
        except Exception:
            pass


def _get_agent_bundle(client_id: Optional[str]) -> _AgentBundle:
    """Return the BrowserBot bundle for the given client, creating it if needed."""
    key = client_id or _SESSION_KEY_DEFAULT
    with _session_registry_lock:
        bundle = _session_agents.get(key)
        if bundle is None:
            bot = create_browserbot(
                headless=_session_config["headless"],
                persist_context=_session_config["persist_context"],
            )
            bundle = _AgentBundle(bot=bot, lock=Lock())
            _session_agents[key] = bundle
    return bundle


def _client_id_from_context(ctx: Optional[Context]) -> Optional[str]:
    return getattr(ctx, "client_id", None) if ctx is not None else None


@mcp.tool
async def ensure_login(
    domain: str,
    *,
    force: bool = False,
    ctx: Optional[Context] = None,
) -> Dict[str, Any]:
    """Ensure an authenticated session is cached for ``domain``."""
    return await _run_agent(
        "ensure_login",
        domain,
        force=force,
        client_id=_client_id_from_context(ctx),
    )


@mcp.tool
async def navigate(
    url: str,
    *,
    wait_until: str = "load",
    ctx: Optional[Context] = None,
) -> Dict[str, Any]:
    """Navigate to ``url`` and return the final location and title."""
    return await _run_agent(
        "navigate",
        url,
        wait_until=wait_until,
        client_id=_client_id_from_context(ctx),
    )


@mcp.tool
async def list_links(
    url: Optional[str] = None,
    *,
    wait_until: str = "load",
    limit: Optional[int] = 200,
    root_selector: Optional[str] = None,
    link_selector: Optional[str] = None,
    ctx: Optional[Context] = None,
) -> Dict[str, Any]:
    """List anchor tags found on ``url`` with basic metadata."""
    return await _run_agent(
        "list_links",
        url,
        wait_until=wait_until,
        limit=limit,
        root_selector=root_selector,
        link_selector=link_selector,
        client_id=_client_id_from_context(ctx),
    )


@mcp.tool
async def extract_text(
    url: Optional[str] = None,
    *,
    selector: str,
    wait_until: str = "load",
    timeout_ms: Optional[int] = None,
    ctx: Optional[Context] = None,
) -> Dict[str, Any]:
    """Extract text for the given CSS selector."""
    return await _run_agent(
        "extract_text",
        url,
        selector=selector,
        wait_until=wait_until,
        timeout_ms=timeout_ms,
        client_id=_client_id_from_context(ctx),
    )


@mcp.tool
async def extract_html(
    url: Optional[str] = None,
    *,
    wait_until: str = "load",
    selector: Optional[str] = None,
    timeout_ms: Optional[int] = None,
    inner: bool = False,
    ctx: Optional[Context] = None,
) -> Dict[str, Any]:
    """Return raw HTML for the page or a specific selector."""
    return await _run_agent(
        "extract_html",
        url,
        wait_until=wait_until,
        selector=selector,
        timeout_ms=timeout_ms,
        inner=inner,
        client_id=_client_id_from_context(ctx),
    )


@mcp.tool
async def click(
    url: Optional[str] = None,
    *,
    selector: str,
    wait_until: str = "load",
    timeout_ms: Optional[int] = None,
    post_wait: Optional[str] = "networkidle",
    ctx: Optional[Context] = None,
) -> Dict[str, Any]:
    """Click a selector on ``url`` and report the resulting page."""
    return await _run_agent(
        "click",
        url,
        selector=selector,
        wait_until=wait_until,
        timeout_ms=timeout_ms,
        post_wait=post_wait,
        client_id=_client_id_from_context(ctx),
    )


@mcp.tool
async def fill_fields(
    url: Optional[str] = None,
    *,
    fields: Dict[str, Any] | Sequence[Any],
    wait_until: str = "load",
    timeout_ms: Optional[int] = None,
    clear_existing: bool = True,
    ctx: Optional[Context] = None,
) -> Dict[str, Any]:
    """Populate one or more form fields."""
    return await _run_agent(
        "fill_fields",
        url,
        fields=fields,
        wait_until=wait_until,
        timeout_ms=timeout_ms,
        clear_existing=clear_existing,
        client_id=_client_id_from_context(ctx),
    )


@mcp.tool
async def submit_form(
    url: Optional[str] = None,
    *,
    form_selector: Optional[str] = None,
    submit_selector: Optional[str] = None,
    fields: Optional[Dict[str, Any] | Sequence[Any]] = None,
    wait_until: str = "load",
    timeout_ms: Optional[int] = None,
    post_wait: Optional[str] = "networkidle",
    wait_for: Optional[str] = None,
    wait_for_state: str = "visible",
    clear_existing: bool = True,
    ctx: Optional[Context] = None,
) -> Dict[str, Any]:
    """Fill optional fields and submit the targeted form."""
    return await _run_agent(
        "submit_form",
        url,
        form_selector=form_selector,
        submit_selector=submit_selector,
        fields=fields,
        wait_until=wait_until,
        timeout_ms=timeout_ms,
        post_wait=post_wait,
        wait_for=wait_for,
        wait_for_state=wait_for_state,
        clear_existing=clear_existing,
        client_id=_client_id_from_context(ctx),
    )


@mcp.tool
async def wait_for_selector(
    url: Optional[str] = None,
    *,
    selector: str,
    wait_until: str = "load",
    timeout_ms: Optional[int] = None,
    state: str = "visible",
    ctx: Optional[Context] = None,
) -> Dict[str, Any]:
    """Wait until the selector reaches the requested state."""
    return await _run_agent(
        "wait_for_selector",
        url,
        selector=selector,
        wait_until=wait_until,
        timeout_ms=timeout_ms,
        state=state,
        client_id=_client_id_from_context(ctx),
    )


@mcp.tool
async def wait(
    url: Optional[str] = None,
    *,
    delay_ms: int = 1000,
    wait_until: str = "load",
    ctx: Optional[Context] = None,
) -> Dict[str, Any]:
    """Pause execution for ``delay_ms`` milliseconds."""
    return await _run_agent(
        "wait",
        url,
        delay_ms=delay_ms,
        wait_until=wait_until,
        client_id=_client_id_from_context(ctx),
    )


@mcp.tool
async def describe_dom(
    url: Optional[str] = None,
    *,
    wait_until: str = "load",
    ctx: Optional[Context] = None,
) -> Dict[str, Any]:
    """Return a structural outline of the page."""
    return await _run_agent(
        "describe_dom",
        url,
        wait_until=wait_until,
        client_id=_client_id_from_context(ctx),
    )


@mcp.tool
async def list_forms(
    url: Optional[str] = None,
    *,
    wait_until: str = "load",
    include_values: bool = True,
    ctx: Optional[Context] = None,
) -> Dict[str, Any]:
    """Return structured metadata for forms on the page."""
    return await _run_agent(
        "list_forms",
        url,
        wait_until=wait_until,
        include_values=include_values,
        client_id=_client_id_from_context(ctx),
    )


@mcp.tool
async def list_buttons(
    url: Optional[str] = None,
    *,
    wait_until: str = "load",
    ctx: Optional[Context] = None,
) -> Dict[str, Any]:
    """List button-like elements present on the page."""
    return await _run_agent(
        "list_buttons",
        url,
        wait_until=wait_until,
        client_id=_client_id_from_context(ctx),
    )


@mcp.tool
async def evaluate_js(
    script: str,
    url: Optional[str] = None,
    wait_until: str = "load",
    arg: Optional[Any] = None,
    ctx: Optional[Context] = None,
) -> Dict[str, Any]:
    """Evaluate arbitrary JavaScript and return the result."""
    return await _run_agent(
        "evaluate_js",
        url,
        script=script,
        wait_until=wait_until,
        arg=arg,
        client_id=_client_id_from_context(ctx),
    )


@mcp.tool
async def take_screenshot(
    url: Optional[str] = None,
    *,
    wait_until: str = "load",
    selector: Optional[str] = None,
    full_page: bool = True,
    image_format: str = "png",
    quality: Optional[int] = None,
    ctx: Optional[Context] = None,
) -> Dict[str, Any]:
    """Capture a screenshot of ``url`` (or ``selector``) as base64."""
    return await _run_agent(
        "screenshot",
        url,
        wait_until=wait_until,
        selector=selector,
        full_page=full_page,
        image_format=image_format,
        quality=quality,
        client_id=_client_id_from_context(ctx),
    )


def main() -> None:
    """Run the Botman MCP server using the default configuration."""
    mcp.run()


__all__ = [
    "mcp",
    "configure_browser_agent",
    "ensure_login",
    "navigate",
    "list_links",
    "extract_text",
    "extract_html",
    "click",
    "fill_fields",
    "submit_form",
    "wait_for_selector",
    "wait",
    "describe_dom",
    "list_forms",
    "list_buttons",
    "evaluate_js",
    "take_screenshot",
    "main",
]
