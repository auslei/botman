# Browser Agent Kit

The current kit keeps the browser automation surface intentionally small so it is easy to understand, extend, and debug.

## Layout
- `browserbot/browser_bot.py` – defines the `BrowserBot` class plus a `create_browserbot()` helper.
- `browserbot/fastmcp_server.py` – wraps a single `BrowserBot` instance in a FastMCP server and exposes a handful of tools.

## BrowserBot Highlights
- Starts Chromium on demand and opens a fresh context for every action (or reuse a single context with `persist_context=True`).
- Provides minimal helpers: `navigate`, `list_links`, `extract_text`, `click`, and `screenshot`.
- Raises regular Python exceptions (e.g. `TimeoutError`) so callers can decide how to handle errors.

Example:

```python
from browserbot.browser_bot import create_browserbot

with create_browserbot(headless=False, persist_context=True) as agent:
    page = agent.navigate("https://example.com")
    print(page["title"])
    agent.click(selector="text=More information")
    details = agent.extract_text(selector="h2")
    print(details["text"])
```

## FastMCP Wrapper

`browserbot/fastmcp_server.py` keeps a single global agent behind a lock and registers tools that call into the agent on a background thread. Each tool returns either the agent result or a structured error payload.

Available tools today:

- `navigate`
- `list_links`
- `extract_text`
- `extract_html`
- `click`
- `fill_fields`
- `submit_form`
- `wait_for_selector`
- `take_screenshot`

Potential next helpers to round out the surface:

- `scroll` – scroll by pixels or to a given element, enabling lazy-loaded content access.
- `download` – fetch a resource triggered by clicking a link/button and expose the file metadata.
- `evaluate_script` – run a short JavaScript snippet when no dedicated helper fits.

Future additions should follow the existing pattern: implement the helper on `BrowserBot`, keep the wrapper thin, and register the corresponding FastMCP tool.

You can tweak headless mode before running the server:

```python
from browserbot.fastmcp_server import configure_browser_agent, mcp
from fastmcp.server import run_application

configure_browser_agent(headless=False, persist_context=True)
run_application(mcp)
```

This arrangement keeps the codebase approachable while leaving room to add more tools if they become necessary. Each new helper should live on `BrowserBot` and be registered in the FastMCP layer with a short docstring describing its behaviour.
