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
- **BrowserAgent** - context-managed wrapper around Playwright. It handles:
  - starting/stopping Playwright and Chromium,
  - launching a persistent "stealth" context for manual login when no session exists,
  - caching storage-state files per domain,
  - returning authenticated contexts for navigation,
  - helper actions like `extract_text()` and `click()`,
  - long-lived session handles so multi-step flows can run against the same Playwright context,
  - structured discovery helpers (`list_links`, `list_forms`, `list_tables`) and `take_screenshot` for artifact capture.
- **BrowserAgentMCPServer** - minimal façade that exposes MCP-style tools: `navigate`, `extract_text`, `click`, plus session-aware helpers `open_session`, `session_goto`, `session_extract_text`, `session_click`, and `close_session`.
- **FastMCP globals** - `browserbot.fastmcp_server.mcp` exposes the ready-to-run FastMCP server, `app` aliases it for tooling, and `configure_browser_agent()` toggles headless/headed mode.
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

`browserbot/fastmcp_server.py` exports an `mcp` instance and helper to reconfigure headless mode. Example CLI adapter:

```python
from fastmcp.server import run_application  # or preferred runner
from browserbot.fastmcp_server import configure_browser_agent, mcp

configure_browser_agent(headless=False)
app = mcp

if __name__ == "__main__":
    run_application(app)
```

The registered tools mirror the `BrowserAgentMCPServer` surface (`ensure_login`, `navigate`, `extract_text`, `click`, `list_links`, `list_forms`, `list_tables`, `take_screenshot`, `open_session`, `session_goto`, `session_extract_text`, `session_click`, `close_session`). Calls are serialized via a `threading.Lock` so Playwright's sync API stays safe inside FastMCP's async loop.
Structured inspection helpers power DOM discovery and artifact capture while retaining the same structured timeout payloads.

The module also exports a default `app`, so tooling like `fastmcp run browserbot.fastmcp_server` can discover it without additional wiring.

You can also rely on the bundled entry point:

```bash
uv run --script fastmcp-server -- --headed
```

### Client Installation Shortcuts

Use FastMCP’s installers from the repo root so UV resolves this package and its dependencies:

```bash
# Claude Desktop
uv run fastmcp install claude-desktop browserbot/fastmcp_server.py --project G:\dev\botman

# Claude Code (example)
uv run fastmcp install claude-code browserbot/fastmcp_server.py --project G:\dev\botman

# Emit a portable MCP config
uv run fastmcp install mcp-json browserbot/fastmcp_server.py --project G:\dev\botman
```

The generated entries invoke:

```
uv run --with fastmcp --project G:\dev\botman fastmcp run G:\dev\botman\browserbot\fastmcp_server.py
```

Adjust `G:\dev\botman` if the project lives elsewhere.

### FastMCP Reference Docs
- `dev_documents/fastmcp_llms_doc.txt` – index of official FastMCP documentation links.
- `dev_documents/fastmcp_server_doc.md` – snapshot of the FastMCP server guide.
- `dev_documents/fastmcp_tools_doc.md` – snapshot of the FastMCP tools guide.

## Manual Gmail Login
Run `uv run python browserbot/google.py`. The helper calls `create_agent(headless=False)` and `ensure_login("mail.google.com", force=True)`. You’ll see a headed browser with Gmail; complete the login (including MFA if required) and press Enter in the terminal to save the storage state for reuse.

## Capability Expansion Plan

The FastMCP surface will grow in staged waves so clients can adopt changes incrementally:

1. **Page Discovery Toolkit (shipped)**
   - Tools: `list_links`, `list_forms`, `list_tables`, `take_screenshot`.
   - Output: structured element summaries (href, labels, input types) plus base64 screenshot artifacts.
   - Follow-up: expand heuristics (semantic labeling, diff detection) as needed.

2. **Interaction & Automation**
   - Tools: `fill_form`, `type_text`, `scroll`, `switch_tab`, `upload_file`, `download_file`.
   - Behavior: consistent wait strategy options and explicit success/error payloads (e.g., new URL, downloaded file path).
   - Safety: annotate destructive operations and require explicit domain checks before executing.

3. **Security & Session Reliability**
   - Tools: `start_mfa_challenge`, `submit_totp`, `validate_session`.
   - Features: domain allowlists, credential vault integration hooks, and session health probes that surface diagnostics before performing sensitive actions.
   - Documentation: outline approval flows and client side obligations for secrets.

4. **Observability & Data Products**
   - Tools/resources: `get_event_log`, `export_table_csv`, `capture_html`, `capture_screenshot`.
   - Goal: make it easy for agents to hand back artifacts, audit transcripts, or structured datasets without manual scraping.

5. **Human-in-the-Loop Bridges**
   - Tools/prompts: `request_human_approval`, `summarize_page`, reusable prompt templates for status updates.
   - Integration: leverage FastMCP elicitation so flows pause safely when confidence is low.

Each wave will ship with schema updates, docstrings, and examples. Tracking and implementation details will live beside the relevant code in `browserbot/agentkit.py` and `browserbot/fastmcp_server.py`; this document records sequencing and design guidance.
