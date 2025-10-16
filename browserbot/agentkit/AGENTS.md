# Browser Agent Kit

## Purpose
Provide a compact browser automation helper that Playwright-powered agents can call to reuse authenticated Gmail sessions and perform basic page actions (navigate, extract text, click) with minimal boilerplate.

## Layout
- `browserbot/agentkit.py` – contains everything: the Playwright-aware `BrowserAgent`, the `BrowserAgentMCPServer` wrapper, and small factory helpers such as `create_agent()` and `create_mcp_server()`.
- `browserbot/google.py` – CLI helper that forces a manual Gmail login so the session profile can be cached for later automation.
- `browserbot/fastmcp_server.py` – optional FastMCP bindings that expose the same tools over a FastMCP `Application`.
- `AGENTS.md` (this document) – integration notes and usage examples.

## Key Components
- **DomainConfig** – tiny dataclass describing how to log into a domain (login URL, CLI instructions, session file path, persistent profile directory, launch flags).
- **BrowserAgent** – context-managed wrapper around Playwright. It handles:
  - starting/stopping Playwright and Chromium,
  - launching a persistent “stealth” context for manual login when no session exists,
  - caching storage-state files per domain,
  - returning authenticated contexts for navigation,
  - helper actions like `extract_text()` and `click()`,
  - long-lived session handles so multi-step flows can run against the same Playwright context.
- **BrowserAgentMCPServer** – minimal façade that exposes MCP-style tools: `navigate`, `extract_text`, `click`, plus session-aware helpers `open_session`, `session_goto`, `session_extract_text`, `session_click`, and `close_session`.
- **BrowserAgentFastMCP** – utility that registers the same tool set with a FastMCP application for easy hosting without custom boilerplate.
- **Structured responses** – all tools return dictionaries. On timeouts the payload has `{"error": "timeout", "operation": "...", ...}` so agents can branch without parsing exceptions.

## Interaction Flow
1. Call `create_mcp_server()` (browserbot/agentkit.py) to build a `BrowserAgent` and wrap it for MCP usage.
2. Entering `with create_mcp_server(...) as server:` starts Playwright via `BrowserAgent.startup()`.
3. `server.handle("navigate" | "extract_text" | "click", {...})` validates inputs and delegates to the matching ephemeral helper. For multi-step work, call `open_session` first to receive a `session_id`, then chain `session_goto`, `session_extract_text`, `session_click`, and finally `close_session`.
4. `BrowserAgent` parses the domain, ensures a session by consulting `DomainConfig`, triggers the manual login helper if needed, and then opens a fresh context with the saved storage state.
5. The handler returns structured results (e.g., final URL/title, extracted text) or a timeout descriptor. Exiting the `with` block shuts down Playwright cleanly.

## Session Workflow Example

```python
from browserbot.agentkit import create_mcp_server

with create_mcp_server(headless=False) as server:
    session = server.handle("open_session", {"url": "https://mail.google.com"})
    sid = session["session_id"]
    threads = server.handle("session_extract_text", {
        "session_id": sid,
        "selector": "div[role='main']"
    })
    server.handle("session_click", {
        "session_id": sid,
        "selector": "text=Compose"
    })
    server.handle("close_session", {"session_id": sid})
```

## FastMCP Hosting

`browserbot/fastmcp_server.py` exposes `create_fastmcp_app()` and `BrowserAgentFastMCP`. Example CLI adapter:

```python
from fastmcp.server import run_application  # or preferred runner
from browserbot.fastmcp_server import create_fastmcp_app

app = create_fastmcp_app(headless=False)

if __name__ == "__main__":
    run_application(app)
```

The registered tools mirror the `BrowserAgentMCPServer` surface (`ensure_login`, `navigate`, `extract_text`, `click`, `open_session`, `session_goto`, `session_extract_text`, `session_click`, `close_session`). Each tool call runs in a protected section (`asyncio.Lock`) to keep Playwright’s sync API safe inside FastMCP’s async runtime.

You can also rely on the bundled UV script:

```bash
uv run fastmcp-server -- --headed --host 0.0.0.0 --port 8080
```

## Manual Gmail Login
Run `uv run python browserbot/google.py`. The helper calls `create_agent(headless=False)` and `ensure_login("mail.google.com", force=True)`. You’ll see a headed browser with Gmail; complete the login (including MFA if required) and press Enter in the terminal to save the storage state for reuse.

## Roadmap Ideas
1. Add more MCP tools (DOM querying, button clicks, data extraction) on top of `BrowserAgent`.
2. Extend `BrowserAgent` with optional validation hooks to confirm a session is still valid before reuse.
3. Expose the same agent through FastAPI or FastMCP if a REST or socket transport is needed.
4. Add automated tests using mocked Playwright contexts to cover navigation and session caching paths.
