"""FastMCP server that exposes the lightweight BrowserAgent helpers."""

from __future__ import annotations

import asyncio
from threading import Lock
from typing import Any, Dict, Optional

from fastmcp import FastMCP
from playwright.sync_api import Error, TimeoutError

from browserbot.agentkit import BrowserAgent, create_agent

mcp = FastMCP(name="browserbot-agent")

_agent_lock = Lock()
_agent: BrowserAgent = create_agent()


def configure_browser_agent(*, headless: bool = True) -> None:
    """Recreate the BrowserAgent with the desired headless setting."""
    global _agent
    with _agent_lock:
        try:
            _agent.shutdown()
        except Exception:
            pass
        _agent = BrowserAgent(headless=headless)


def _call_agent(method: str, *args, **kwargs) -> Dict[str, Any]:
    """Invoke ``BrowserAgent`` methods inside a thread-safe section."""
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
    url: str,
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
    url: str,
    selector: str,
    wait_until: str = "load",
    timeout_ms: Optional[int] = None,
) -> Dict[str, Any]:
    """Extract text for the given CSS selector."""
    return await _run_agent(
        "extract_text",
        url,
        selector,
        wait_until=wait_until,
        timeout_ms=timeout_ms,
    )


@mcp.tool
async def click(
    url: str,
    selector: str,
    wait_until: str = "load",
    timeout_ms: Optional[int] = None,
    post_wait: Optional[str] = "networkidle",
) -> Dict[str, Any]:
    """Click a selector on ``url`` and report the resulting page."""
    return await _run_agent(
        "click",
        url,
        selector,
        wait_until=wait_until,
        timeout_ms=timeout_ms,
        post_wait=post_wait,
    )


@mcp.tool
async def take_screenshot(
    url: str,
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
    "click",
    "take_screenshot",
]
