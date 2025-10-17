# Botman Browser Agent Kit

`botman` bundles Playwright-powered browser automation utilities that capture reusable sessions (e.g., Gmail) and expose agent-friendly tool surfaces. You can run it directly from Python, or host the tools as Model Context Protocol (MCP) endpoints using FastMCP.

## Prerequisites

- Python 3.12+
- Playwright browsers installed (run `uv run playwright install chromium` after syncing dependencies)

## Installation

```bash
uv sync
uv run playwright install chromium  # first-time browser download
```

## Manual Gmail Login

Before running automated tasks, capture a Gmail session once:

```bash
uv run python browserbot/google.py
```

This launches a headed Chromium window. Complete the login flow (including MFA) and press Enter in the terminal so the storage state is saved under `browserbot/tmp/`.

## Using the Browser Agent Programmatically

```python
from browserbot.agentkit import create_agent

with create_agent(headless=False) as agent:
    session = agent.open_session("https://mail.google.com/")
    sid = session["session_id"]

    inbox = agent.session_extract_text(sid, selector="div[role='main']")
    print(inbox["title"], inbox["final_url"])

    agent.session_click(sid, selector='text=Compose')
    agent.close_session(sid)
```

Each helper returns typed dictionaries. If a Playwright wait hits a timeout, the payload includes `{"error": "timeout", "operation": "...", ...}` so callers can branch without exception handling.

## Hosting with FastMCP

Install dependencies via `uv sync` then start the server with the bundled script:

```bash
uv run --script fastmcp-server -- --headed
```

- Omit `--headed` for headless mode (default).
- The FastMCP server runs over STDIO and registers tools: `ensure_login`, `navigate`, `extract_text`, `click`, `list_links`, `list_forms`, `list_tables`, `take_screenshot`, `open_session`, `session_goto`, `session_extract_text`, `session_click`, and `close_session`.
- Tool responses have explicit JSON schemas (success vs timeout payloads) so LLM clients know exactly what to expect.

### Installing in MCP Clients

Use FastMCP’s installers to register the server with compatible clients. Always run the command from the project root (or pass `--project`) so UV loads this repo’s dependencies.

```bash
# Claude Desktop (adjust the absolute path if your checkout lives elsewhere)
uv run fastmcp install claude-desktop browserbot/fastmcp_server.py --project G:\dev\botman

# Claude Code (example)
uv run fastmcp install claude-code browserbot/fastmcp_server.py --project G:\dev\botman

# Generate a generic MCP JSON config
uv run fastmcp install mcp-json browserbot/fastmcp_server.py --project G:\dev\botman
```

The installers produce entries that launch the server via:

```
uv run --with fastmcp --project G:\dev\botman fastmcp run G:\dev\botman\browserbot\fastmcp_server.py
```

That ensures the `browserbot` package and Playwright dependencies are available even when invoked outside the repo.

### Current Capabilities

- Credential priming through `ensure_login` with domain-specific session reuse.
- Typed navigation helpers (`navigate`, `open_session`, `session_goto`) that return page URL/title metadata.
- Content extraction (`extract_text`, `session_extract_text`) with timeout diagnostics.
- Interaction helpers (`click`, `session_click`) with optional post-wait handling.
- Structured DOM inspection (`list_links`, `list_forms`, `list_tables`) delivering normalized metadata with pagination flags.
- Screenshot capture (`take_screenshot`) with selector/full-page support and base64-encoded artifacts.
- Deterministic session lifecycle (`open_session`, `close_session`) so multi-step flows operate on stable contexts.
- Async-friendly FastMCP endpoints that wrap the Playwright sync API via background threads.

### Upcoming Additions

The next iteration will expand the tool surface to cover:

- Advanced DOM semantics (heuristic element selection, change detection, richer metadata).
- Rich interaction utilities (form fill, typing, scrolling, tab/window control, file uploads/downloads).
- Security and compliance helpers (MFA handling, domain allowlists, audit logging).
- Data packaging improvements (table-to-CSV/JSON exports, screenshot capture resources).
- Human-in-the-loop bridges (approval prompts, summarized status reports).

Follow progress in `browserbot/agentkit/AGENTS.md` for implementation details and sequencing.

## Development Notes

- All sources live under `browserbot/`; the flattened `agentkit.py` contains both the browser orchestration logic and the MCP adapter.
- Timeout handling is uniform across tools—inspect the returned dictionary before proceeding.
- To update Playwright binaries or dependencies, run `uv sync` and `uv run playwright install chromium` again.
