"""FastMCP server that exposes BrowserAgent tools."""

from __future__ import annotations

import argparse
import asyncio
import atexit
import sys
from pathlib import Path
from threading import Lock
from typing import Any, Callable, Literal, NotRequired, TypedDict, TypeVar, cast

from fastmcp import FastMCP

_PACKAGE_DIR = Path(__file__).resolve().parent
_PROJECT_DIR = _PACKAGE_DIR.parent
if str(_PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(_PROJECT_DIR))

from browserbot.agentkit import BrowserAgent, create_agent

T = TypeVar("T")


class EnsureLoginResult(TypedDict):
    domain: str
    force: bool
    status: Literal["ok"]


class PageMetadata(TypedDict):
    final_url: str
    title: str


class ExtractTextSuccess(PageMetadata):
    text: str


class ClickSuccess(PageMetadata):
    clicked: str


class SessionBase(TypedDict):
    session_id: str
    final_url: str
    title: str


class SessionTextSuccess(SessionBase):
    text: str


class SessionClickSuccess(SessionBase):
    clicked: str


class SessionCloseSuccess(SessionBase):
    closed: bool


class TimeoutResult(TypedDict):
    error: Literal["timeout"]
    operation: str
    session_id: NotRequired[str]
    selector: NotRequired[str]
    url: NotRequired[str]
    final_url: NotRequired[str]
    timeout_ms: NotRequired[int]
    phase: NotRequired[str]


class LinkInfo(TypedDict):
    position: int
    href: str
    text: str
    title: NotRequired[str | None]
    aria_label: NotRequired[str | None]
    target: NotRequired[str | None]
    rel: NotRequired[str | None]


class ListLinksResult(PageMetadata):
    count: int
    links: list[LinkInfo]
    truncated: bool


class FormControlInfo(TypedDict):
    tag: str
    type: NotRequired[str | None]
    name: NotRequired[str | None]
    id: NotRequired[str | None]
    placeholder: NotRequired[str | None]
    aria_label: NotRequired[str | None]
    value: NotRequired[str | None]
    required: bool
    disabled: bool
    labels: list[str]


class FormInfo(TypedDict):
    position: int
    action: str
    method: str
    id: NotRequired[str | None]
    name: NotRequired[str | None]
    enctype: NotRequired[str | None]
    controls: list[FormControlInfo]
    control_count: int
    controls_truncated: bool


class ListFormsResult(PageMetadata):
    count: int
    forms: list[FormInfo]
    truncated: bool


class TableInfo(TypedDict):
    position: int
    caption: NotRequired[str | None]
    headers: list[str]
    rows: list[list[str]]
    row_count: int
    rows_truncated: bool


class ListTablesResult(PageMetadata):
    count: int
    tables: list[TableInfo]
    truncated: bool


class ScreenshotResult(PageMetadata):
    image_format: Literal["png", "jpeg"]
    screenshot_base64: str
    full_page: bool
    selector: NotRequired[str]


class ScreenshotNotFound(TypedDict):
    error: Literal["not_found"]
    operation: Literal["take_screenshot"]
    selector: str
    final_url: str


_agent_lock = Lock()
_agent: BrowserAgent = create_agent()


def _replace_agent(*, headless: bool) -> None:
    """Swap the global BrowserAgent with the requested headless mode."""
    global _agent
    with _agent_lock:
        try:
            _agent.shutdown()
        except Exception:
            pass
        _agent = create_agent(headless=headless)


def configure_browser_agent(*, headless: bool) -> None:
    """Public helper to reconfigure headless mode before running the server."""
    _replace_agent(headless=headless)


def _call(func: Callable[..., T], *args, **kwargs) -> T:
    with _agent_lock:
        return func(*args, **kwargs)


async def _call_agent(func: Callable[..., T], *args, **kwargs) -> T:
    return await asyncio.to_thread(_call, func, *args, **kwargs)


def _is_timeout(result: Any) -> bool:
    return isinstance(result, dict) and result.get("error") == "timeout"


def _is_not_found(result: Any) -> bool:
    return isinstance(result, dict) and result.get("error") == "not_found"
mcp = FastMCP(name="browserbot-agent")


@mcp.tool
async def ensure_login(domain: str, force: bool = False) -> EnsureLoginResult:
    """Ensure the cached session for ``domain`` is valid, renewing if needed."""
    await _call_agent(_agent.ensure_login, domain, force=force)
    return {"domain": domain, "force": force, "status": "ok"}


@mcp.tool
async def navigate(url: str, wait_until: str = "load") -> PageMetadata | TimeoutResult:
    """Navigate to ``url`` and return final metadata about the page."""
    result = await _call_agent(_agent.navigate, url, wait_until=wait_until)
    if _is_timeout(result):
        return cast(TimeoutResult, result)
    return cast(PageMetadata, result)


@mcp.tool
async def extract_text(
    url: str,
    selector: str,
    wait_until: str = "load",
    timeout_ms: int = 5000,
) -> ExtractTextSuccess | TimeoutResult:
    """Visit ``url`` and return text content for ``selector``."""
    result = await _call_agent(
        _agent.extract_text,
        url,
        selector,
        wait_until=wait_until,
        timeout_ms=timeout_ms,
    )
    if _is_timeout(result):
        return cast(TimeoutResult, result)
    return cast(ExtractTextSuccess, result)


@mcp.tool
async def click(
    url: str,
    selector: str,
    wait_until: str = "load",
    post_wait: str | None = "networkidle",
    timeout_ms: int = 5000,
) -> ClickSuccess | TimeoutResult:
    """Load ``url`` and click ``selector``, optionally waiting for network idle."""
    result = await _call_agent(
        _agent.click,
        url,
        selector,
        wait_until=wait_until,
        post_wait=post_wait,
        timeout_ms=timeout_ms,
    )
    if _is_timeout(result):
        return cast(TimeoutResult, result)
    return cast(ClickSuccess, result)


@mcp.tool
async def list_links(
    url: str,
    wait_until: str = "load",
    limit: int | None = 200,
) -> ListLinksResult | TimeoutResult:
    """Return structured metadata for anchor tags found at ``url``."""
    result = await _call_agent(_agent.list_links, url, wait_until=wait_until, limit=limit)
    if _is_timeout(result):
        return cast(TimeoutResult, result)
    return cast(ListLinksResult, result)


@mcp.tool
async def list_forms(
    url: str,
    wait_until: str = "load",
    limit: int | None = 50,
    max_fields_per_form: int = 25,
) -> ListFormsResult | TimeoutResult:
    """Return structured metadata for forms on ``url``."""
    result = await _call_agent(
        _agent.list_forms,
        url,
        wait_until=wait_until,
        limit=limit,
        max_fields_per_form=max_fields_per_form,
    )
    if _is_timeout(result):
        return cast(TimeoutResult, result)
    return cast(ListFormsResult, result)


@mcp.tool
async def list_tables(
    url: str,
    wait_until: str = "load",
    limit: int | None = 20,
    max_rows: int = 25,
) -> ListTablesResult | TimeoutResult:
    """Return structured table data discovered on ``url``."""
    result = await _call_agent(
        _agent.list_tables,
        url,
        wait_until=wait_until,
        limit=limit,
        max_rows=max_rows,
    )
    if _is_timeout(result):
        return cast(TimeoutResult, result)
    return cast(ListTablesResult, result)


@mcp.tool
async def take_screenshot(
    url: str,
    wait_until: str = "load",
    selector: str | None = None,
    full_page: bool = True,
    image_format: Literal["png", "jpeg"] = "png",
    quality: int | None = None,
) -> ScreenshotResult | TimeoutResult | ScreenshotNotFound:
    """Capture a screenshot of ``url`` (optionally scoped to ``selector``)."""
    result = await _call_agent(
        _agent.take_screenshot,
        url,
        wait_until=wait_until,
        selector=selector,
        full_page=full_page,
        image_format=image_format,
        quality=quality,
    )
    if _is_timeout(result):
        return cast(TimeoutResult, result)
    if _is_not_found(result):
        return cast(ScreenshotNotFound, result)
    return cast(ScreenshotResult, result)


@mcp.tool
async def open_session(url: str, wait_until: str = "load") -> SessionBase | TimeoutResult:
    """Open a long-lived session anchored at ``url`` for multi-step flows."""
    result = await _call_agent(_agent.open_session, url, wait_until=wait_until)
    if _is_timeout(result):
        return cast(TimeoutResult, result)
    return cast(SessionBase, result)


@mcp.tool
async def session_goto(
    session_id: str,
    url: str,
    wait_until: str = "load",
) -> SessionBase | TimeoutResult:
    """Navigate an existing session to ``url`` and report the resulting page."""
    result = await _call_agent(_agent.session_goto, session_id, url, wait_until=wait_until)
    if _is_timeout(result):
        return cast(TimeoutResult, result)
    return cast(SessionBase, result)


@mcp.tool
async def session_extract_text(
    session_id: str,
    selector: str,
    timeout_ms: int = 5000,
) -> SessionTextSuccess | TimeoutResult:
    """Pull text for ``selector`` within an existing session page."""
    result = await _call_agent(
        _agent.session_extract_text,
        session_id,
        selector,
        timeout_ms=timeout_ms,
    )
    if _is_timeout(result):
        return cast(TimeoutResult, result)
    return cast(SessionTextSuccess, result)


@mcp.tool
async def session_click(
    session_id: str,
    selector: str,
    timeout_ms: int = 5000,
    post_wait: str | None = "networkidle",
) -> SessionClickSuccess | TimeoutResult:
    """Click ``selector`` inside the session page, allowing optional waits."""
    result = await _call_agent(
        _agent.session_click,
        session_id,
        selector,
        timeout_ms=timeout_ms,
        post_wait=post_wait,
    )
    if _is_timeout(result):
        return cast(TimeoutResult, result)
    return cast(SessionClickSuccess, result)


@mcp.tool
async def close_session(session_id: str) -> SessionCloseSuccess:
    """Terminate a session created with ``open_session``."""
    result = await _call_agent(_agent.close_session, session_id)
    return cast(SessionCloseSuccess, result)


def main() -> None:
    """CLI entry point for running the FastMCP server over stdio."""
    parser = argparse.ArgumentParser(description="Start the BrowserBot FastMCP server.")
    parser.add_argument("--headed", action="store_true", help="Launch browsers in headed mode.")
    parser.add_argument("--name", default="browserbot-agent", help="FastMCP server name.")
    args = parser.parse_args()

    if args.name != mcp.name:
        mcp.name = args.name

    configure_browser_agent(headless=not args.headed)
    try:
        mcp.run()
    finally:
        with _agent_lock:
            _agent.shutdown()


# FastMCP discovers module-level variables named "app" or "mcp".
app = mcp
atexit.register(lambda: _agent.shutdown())

__all__ = [
    "app",
    "configure_browser_agent",
    "ensure_login",
    "mcp",
    "main",
]


if __name__ == "__main__":
    main()
