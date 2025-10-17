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


class NotFoundError(TypedDict):
    error: Literal["not_found"]
    operation: str
    selector: str
    final_url: str


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


class SessionListLinksResult(SessionBase):
    count: int
    links: list[LinkInfo]
    truncated: bool


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


class FilledField(TypedDict):
    selector: str
    value: str


class SkippedField(TypedDict):
    selector: str
    reason: str


class SessionTypeTextResult(SessionBase):
    selector: str
    value: str
    append: bool
    submitted: bool
    submission_method: NotRequired[str | None]


class SubmissionInfo(TypedDict, total=False):
    method: str
    selector: NotRequired[str]
    reason: NotRequired[str]


class SessionFillFormResult(SessionBase):
    filled: list[FilledField]
    skipped: list[SkippedField]
    submitted: bool
    submission: NotRequired[SubmissionInfo | None]


class SessionScrollResult(SessionBase):
    direction: Literal["down", "up", "to_top", "to_bottom"]
    amount: int
    scroll_x: int
    scroll_y: int
    max_scroll_y: int
    viewport_height: int


class SessionSwitchTabResult(SessionBase):
    active_index: int
    page_count: int
    open_urls: list[str]


class SessionUploadFileResult(SessionBase):
    selector: str
    files: list[str]


class SessionDownloadFileResult(SessionBase):
    trigger_selector: str
    download_path: str
    suggested_filename: str
    download_url: str


class FileMissingError(TypedDict):
    error: Literal["file_missing"]
    operation: str
    session_id: str
    missing: list[str]


class DownloadFailedError(TypedDict):
    error: Literal["download_failed"]
    operation: str
    session_id: str
    final_url: str
    message: str


class TabOutOfRangeError(TypedDict):
    error: Literal["tab_out_of_range"]
    operation: str
    session_id: str
    requested_index: int
    page_count: int


class NoTabsError(TypedDict):
    error: Literal["no_tabs"]
    operation: str
    session_id: str


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
    return isinstance(result, dict) and result.get('error') == 'timeout'


def _is_not_found(result: Any) -> bool:
    return isinstance(result, dict) and result.get('error') == 'not_found'


def _is_file_missing(result: Any) -> bool:
    return isinstance(result, dict) and result.get('error') == 'file_missing'


def _is_download_failed(result: Any) -> bool:
    return isinstance(result, dict) and result.get('error') == 'download_failed'


def _tab_error_code(result: Any) -> str | None:
    if not isinstance(result, dict):
        return None
    error = result.get('error')
    if error in {'no_tabs', 'tab_out_of_range'}:
        return error
    return None
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
    wait_selector: str | None = None,
    root_selector: str | None = None,
    link_selector: str | None = None,
) -> ListLinksResult | TimeoutResult:
    """Return structured metadata for anchor tags found at ``url``."""
    result = await _call_agent(
        _agent.list_links,
        url,
        wait_until=wait_until,
        limit=limit,
        wait_selector=wait_selector,
        root_selector=root_selector,
        link_selector=link_selector,
    )
    if _is_timeout(result):
        return cast(TimeoutResult, result)
    return cast(ListLinksResult, result)


@mcp.tool
async def session_list_links(
    session_id: str,
    limit: int | None = 200,
    wait_selector: str | None = None,
    root_selector: str | None = None,
    link_selector: str | None = None,
    timeout_ms: int = 5000,
) -> SessionListLinksResult | TimeoutResult:
    """Return structured metadata for links on the current session page."""
    result = await _call_agent(
        _agent.session_list_links,
        session_id,
        limit=limit,
        wait_selector=wait_selector,
        root_selector=root_selector,
        link_selector=link_selector,
        timeout_ms=timeout_ms,
    )
    if _is_timeout(result):
        return cast(TimeoutResult, result)
    return cast(SessionListLinksResult, result)


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
) -> ScreenshotResult | TimeoutResult | NotFoundError:
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
        return cast(NotFoundError, result)
    return cast(ScreenshotResult, result)


@mcp.tool
async def type_text(
    session_id: str,
    selector: str,
    value: str,
    append: bool = False,
    delay_ms: int | None = None,
    submit: bool = False,
    timeout_ms: int = 5000,
) -> SessionTypeTextResult | TimeoutResult:
    """Type text into an element within an existing session."""
    result = await _call_agent(
        _agent.session_type_text,
        session_id,
        selector,
        value,
        append=append,
        delay_ms=delay_ms,
        submit=submit,
        timeout_ms=timeout_ms,
    )
    if _is_timeout(result):
        return cast(TimeoutResult, result)
    return cast(SessionTypeTextResult, result)


@mcp.tool
async def fill_form(
    session_id: str,
    fields: dict[str, str] | list[dict[str, str]],
    submit: bool = False,
    submit_selector: str | None = None,
    timeout_ms: int = 5000,
) -> SessionFillFormResult | TimeoutResult:
    """Fill multiple selectors with values inside a session."""
    result = await _call_agent(
        _agent.session_fill_form,
        session_id,
        fields,
        submit=submit,
        submit_selector=submit_selector,
        timeout_ms=timeout_ms,
    )
    if _is_timeout(result):
        return cast(TimeoutResult, result)
    return cast(SessionFillFormResult, result)


@mcp.tool
async def scroll(
    session_id: str,
    direction: Literal["down", "up", "to_top", "to_bottom"] = "down",
    amount: int = 1000,
) -> SessionScrollResult:
    """Scroll the active session page."""
    result = await _call_agent(
        _agent.session_scroll,
        session_id,
        direction=direction,
        amount=amount,
    )
    return cast(SessionScrollResult, result)


@mcp.tool
async def switch_tab(
    session_id: str,
    tab_index: int,
) -> SessionSwitchTabResult | TabOutOfRangeError | NoTabsError:
    """Switch focus to the specified tab within the session."""
    result = await _call_agent(
        _agent.session_switch_tab,
        session_id,
        tab_index,
    )
    code = _tab_error_code(result)
    if code == "no_tabs":
        return cast(NoTabsError, result)
    if code == "tab_out_of_range":
        return cast(TabOutOfRangeError, result)
    return cast(SessionSwitchTabResult, result)


@mcp.tool
async def upload_file(
    session_id: str,
    selector: str,
    files: str | list[str],
    timeout_ms: int = 5000,
) -> SessionUploadFileResult | TimeoutResult | FileMissingError:
    """Upload files via an `<input type=file>` element."""
    result = await _call_agent(
        _agent.session_upload_file,
        session_id,
        selector,
        files,
        timeout_ms=timeout_ms,
    )
    if _is_timeout(result):
        return cast(TimeoutResult, result)
    if _is_file_missing(result):
        return cast(FileMissingError, result)
    return cast(SessionUploadFileResult, result)


@mcp.tool
async def download_file(
    session_id: str,
    trigger_selector: str,
    timeout_ms: int = 15000,
    save_as: str | None = None,
) -> SessionDownloadFileResult | TimeoutResult | DownloadFailedError:
    """Trigger a download and return the saved file path."""
    result = await _call_agent(
        _agent.session_download_file,
        session_id,
        trigger_selector,
        timeout_ms=timeout_ms,
        save_as=save_as,
    )
    if _is_timeout(result):
        return cast(TimeoutResult, result)
    if _is_download_failed(result):
        return cast(DownloadFailedError, result)
    return cast(SessionDownloadFileResult, result)


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
