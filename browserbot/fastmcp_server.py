"""FastMCP server that exposes the lightweight BrowserBot helpers."""

from __future__ import annotations

import asyncio
from threading import Lock
from typing import Any, Dict, Optional, Sequence

from fastmcp import FastMCP
from playwright.sync_api import Error, TimeoutError

from browserbot.browser_bot import BrowserBot, create_browserbot

mcp = FastMCP(name="browserbot-agent")

_agent_lock = Lock()
_agent: BrowserBot = create_browserbot()


def configure_browser_agent(
    *,
    headless: bool = True,
    persist_context: bool = False,
) -> None:
    """Recreate the BrowserBot with the desired headless/persistence settings."""
    global _agent
    with _agent_lock:
        try:
            _agent.shutdown()
        except Exception:
            pass
        _agent = BrowserBot(headless=headless, persist_context=persist_context)


def _call_agent(method: str, *args, **kwargs) -> Dict[str, Any]:
    """Invoke ``BrowserBot`` methods inside a thread-safe section."""
    with _agent_lock:
        agent_method = getattr(_agent, method)
        return agent_method(*args, **kwargs)


async def _run_agent(method: str, *args, **kwargs) -> Dict[str, Any]:
    return await asyncio.to_thread(_call_with_errors, method, *args, **kwargs)


def _call_with_errors(method: str, *args, **kwargs) -> Dict[str, Any]:
    try:
        return _call_agent(method, *args, **kwargs)
    except TimeoutError as exc:
        return {"error": "timeout", "operation": method, "message": str(exc)}
    except Error as exc:
        return {"error": "playwright", "operation": method, "message": str(exc)}
    except Exception as exc:
        return {"error": "unexpected", "operation": method, "message": str(exc)}


@mcp.tool
async def navigate(url: str, wait_until: str = "load") -> Dict[str, Any]:
    """Navigate to ``url`` and return the final location and title."""
    return await _run_agent("navigate", url, wait_until=wait_until)


@mcp.tool
async def list_links(
    url: Optional[str] = None,
    wait_until: str = "load",
    limit: Optional[int] = 200,
    root_selector: Optional[str] = None,
    link_selector: Optional[str] = None,
) -> Dict[str, Any]:
    """List anchor tags found on ``url`` with basic metadata."""
    return await _run_agent(
        "list_links",
        url,
        wait_until=wait_until,
        limit=limit,
        root_selector=root_selector,
        link_selector=link_selector,
    )


@mcp.tool
async def extract_text(
    url: Optional[str] = None,
    *,
    selector: str,
    wait_until: str = "load",
    timeout_ms: Optional[int] = None,
) -> Dict[str, Any]:
    """Extract text for the given CSS selector."""
    return await _run_agent(
        "extract_text",
        url,
        selector=selector,
        wait_until=wait_until,
        timeout_ms=timeout_ms,
    )


@mcp.tool
async def extract_html(
    url: Optional[str] = None,
    wait_until: str = "load",
    selector: Optional[str] = None,
    timeout_ms: Optional[int] = None,
    inner: bool = False,
) -> Dict[str, Any]:
    """Return raw HTML for the page or a specific selector."""
    return await _run_agent(
        "extract_html",
        url,
        wait_until=wait_until,
        selector=selector,
        timeout_ms=timeout_ms,
        inner=inner,
    )


@mcp.tool
async def click(
    url: Optional[str] = None,
    *,
    selector: str,
    wait_until: str = "load",
    timeout_ms: Optional[int] = None,
    post_wait: Optional[str] = "networkidle",
) -> Dict[str, Any]:
    """Click a selector on ``url`` and report the resulting page."""
    return await _run_agent(
        "click",
        url,
        selector=selector,
        wait_until=wait_until,
        timeout_ms=timeout_ms,
        post_wait=post_wait,
    )


@mcp.tool
async def fill_fields(
    url: Optional[str] = None,
    *,
    fields: Dict[str, Any] | Sequence[Any],
    wait_until: str = "load",
    timeout_ms: Optional[int] = None,
    clear_existing: bool = True,
) -> Dict[str, Any]:
    """Populate one or more form fields."""
    return await _run_agent(
        "fill_fields",
        url,
        fields=fields,
        wait_until=wait_until,
        timeout_ms=timeout_ms,
        clear_existing=clear_existing,
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
    )


@mcp.tool
async def wait_for_selector(
    url: Optional[str] = None,
    *,
    selector: str,
    wait_until: str = "load",
    timeout_ms: Optional[int] = None,
    state: str = "visible",
) -> Dict[str, Any]:
    """Wait until the selector reaches the requested state."""
    return await _run_agent(
        "wait_for_selector",
        url,
        selector=selector,
        wait_until=wait_until,
        timeout_ms=timeout_ms,
        state=state,
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
    )


__all__ = [
    "mcp",
    "configure_browser_agent",
    "navigate",
    "list_links",
    "extract_text",
    "extract_html",
    "click",
    "fill_fields",
    "submit_form",
    "wait_for_selector",
    "take_screenshot",
]
