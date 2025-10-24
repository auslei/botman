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
from botman.browser import create_browserbot

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
uv run fastmcp run botman/mcp/server.py
```

Switch to headed mode before starting the server, if desired:

```python
from botman.mcp import configure_browser_agent

configure_browser_agent(headless=False, persist_context=True)
```

### Deploying to FastMCP Cloud

FastMCP Cloud expects a module path and server object. The Botman tree exposes the
`FastMCP` instance at `botman.mcp.server:mcp`, so you can validate the package
before uploading:

```bash
fastmcp inspect botman/mcp/server.py:mcp
```

To run as an ASGI app (for cloud hosting or custom infrastructure), point your
server at `botman:app`.

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
- `wait(url=None, delay_ms=1000, wait_until="load")`
- `describe_dom(url=None, wait_until="load")`
- `list_forms(url=None, wait_until="load", include_values=True)`
- `list_buttons(url=None, wait_until="load")`
- `evaluate_js(script, url=None, wait_until="load", arg=None)`
- `take_screenshot(url=None, wait_until="load", selector=None, full_page=True, image_format="png", quality=None)`

Each tool returns the underlying result or a structured error dictionary (`{"error": "...", "operation": "...", "message": "..."}`) when Playwright raises.

### Installing in MCP Clients

```bash
uv run fastmcp install claude-desktop botman/mcp/server.py --project /path/to/botman
```

Adjust the client target (`claude-desktop`, `claude-code`, `mcp-json`, etc.) and project path as needed.

## Development Notes

- Core modules live under `botman/`. `botman/browser/core.py` holds the helper and `botman/mcp/server.py` registers MCP tools.
- The codebase keeps concurrency simple: the FastMCP adapter serialises Playwright access behind a thread lock and executes synchronous Playwright calls on a background thread.
- Additions should follow the same pattern: implement a helper on `BrowserBot`, document it with a short docstring, then expose it via FastMCP.
- Example scripts that exercise the tools live under `archived/examples/` to keep the main package slim while preserving reference material.

## Documentation & Context7

- High-level architecture notes live in `docs/AGENTS.md` and `botman/AGENT.md`.
- When you need up-to-date FastMCP or LangChain information, use Context7 (e.g.
  `context7 resolve fastmcp` followed by `context7 docs ...`) so the agent is
  always aligned with the latest upstream changes.
