# Botman Browser Agent Kit

`botman` ships a small set of Playwright-powered helpers that are easy to embed in autonomous agents. The codebase now favours clarity over breadth: a single `BrowserBot` class wraps the Playwright sync API and a FastMCP adapter exposes those helpers as tools.

## Prerequisites

- Python 3.12+
- Playwright browsers (run `uv run playwright install chromium` after syncing dependencies)

## Installation

```bash
uv sync
uv run playwright install chromium  # downloads Chromium the first time
```

## Using the BrowserBot Directly

```python
from browserbot.browser_bot import create_browserbot

with create_browserbot(headless=False, persist_context=True) as agent:
    meta = agent.navigate("https://example.com")
    print(meta["title"])

    links = agent.list_links("https://example.com")
    for link in links["links"][:5]:
        print(link["text"], link["href"])

    agent.click(selector="text=More information")
    hero_copy = agent.extract_text(selector="h1")
    print(hero_copy["text"])
```

By default every helper opens a fresh browser context, performs the requested action, and closes the context again. Pass `persist_context=True` to reuse a single page across calls (handy for multi-step flows that need to retain login cookies or navigation state). If Playwright raises (for example `TimeoutError`), the exception is propagated so you can decide how to handle it.

## Hosting the Tools with FastMCP

The FastMCP wrapper runs the same helpers behind a lightweight STDIO server.

```bash
uv run fastmcp run browserbot/fastmcp_server.py
```

Switch to headed mode before starting the server, if desired:

```python
from browserbot.fastmcp_server import configure_browser_agent

configure_browser_agent(headless=False, persist_context=True)
```

### Registered Tools

The MCP surface intentionally mirrors the `BrowserBot` methods:

- `navigate(url, wait_until="load")`
- `list_links(url=None, wait_until="load", limit=200, root_selector=None, link_selector=None)`
- `extract_text(url=None, selector=..., wait_until="load", timeout_ms=None)`
- `extract_html(url=None, wait_until="load", selector=None, timeout_ms=None, inner=False)`
- `click(url=None, selector=..., wait_until="load", timeout_ms=None, post_wait="networkidle")`
- `fill_fields(url=None, fields=..., wait_until="load", timeout_ms=None, clear_existing=True)`
- `submit_form(url=None, form_selector=None, submit_selector=None, fields=None, wait_until="load", timeout_ms=None, post_wait="networkidle", wait_for=None, wait_for_state="visible", clear_existing=True)`
- `wait_for_selector(url=None, selector=..., wait_until="load", timeout_ms=None, state="visible")`
- `take_screenshot(url=None, wait_until="load", selector=None, full_page=True, image_format="png", quality=None)`

Each tool returns the underlying result or a structured error dictionary (`{"error": "...", "operation": "...", "message": "..."}`) when Playwright raises.

### Installing in MCP Clients

```bash
uv run fastmcp install claude-desktop browserbot/fastmcp_server.py --project /path/to/botman
```

Adjust the client target (`claude-desktop`, `claude-code`, `mcp-json`, etc.) and project path as needed.

## Development Notes

- Source lives under `browserbot/`. `agentkit.py` holds the browser helper and `fastmcp_server.py` registers MCP tools.
- The codebase keeps concurrency simple: the FastMCP adapter serialises Playwright access behind a thread lock and executes synchronous Playwright calls on a background thread.
- Additions should follow the same pattern: implement a helper on `BrowserBot`, document it with a short docstring, then expose it via FastMCP.
