# Browser Agent Kit

The current kit keeps the browser automation surface intentionally small so it is easy to understand, extend, and debug.

## Layout
- `browserbot/agentkit.py` – defines the `BrowserAgent` class plus a `create_agent()` helper.
- `browserbot/fastmcp_server.py` – wraps a single `BrowserAgent` instance in a FastMCP server and exposes a handful of tools.

## BrowserAgent Highlights
- Starts Chromium on demand and opens a fresh context for every action.
- Provides minimal helpers: `navigate`, `list_links`, `extract_text`, `click`, and `screenshot`.
- Raises regular Python exceptions (e.g. `TimeoutError`) so callers can decide how to handle errors.

Example:

```python
from browserbot.agentkit import create_agent

with create_agent(headless=False) as agent:
    page = agent.navigate("https://example.com")
    print(page["title"])
    links = agent.list_links("https://example.com")
    print(len(links["links"]))
```

## FastMCP Wrapper

`browserbot/fastmcp_server.py` keeps a single global agent behind a lock and registers tools that call into the agent on a background thread. Each tool returns either the agent result or a structured error payload.

Available tools: `navigate`, `list_links`, `extract_text`, `click`, `take_screenshot`.

You can tweak headless mode before running the server:

```python
from browserbot.fastmcp_server import configure_browser_agent, mcp
from fastmcp.server import run_application

configure_browser_agent(headless=False)
run_application(mcp)
```

This arrangement keeps the codebase approachable while leaving room to add more tools if they become necessary. Each new helper should live on `BrowserAgent` and be registered in the FastMCP layer with a short docstring describing its behaviour.
