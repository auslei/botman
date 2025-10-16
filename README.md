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

Each helper returns dictionaries. If a Playwright wait hits a timeout, the payload includes `{"error": "timeout", "operation": "...", ...}` so callers can branch without exception handling.

## Hosting with FastMCP

Install dependencies via `uv sync` then start the server with the bundled script:

```bash
uv run fastmcp-server -- --headed --host 0.0.0.0 --port 8080
```

- Omit `--headed` for headless mode.
- The FastMCP app registers tools: `ensure_login`, `navigate`, `extract_text`, `click`, `open_session`, `session_goto`, `session_extract_text`, `session_click`, and `close_session`.

## Development Notes

- All sources live under `browserbot/`; the flattened `agentkit.py` contains both the browser orchestration logic and the MCP adapter.
- Timeout handling is uniform across tools—inspect the returned dictionary before proceeding.
- To update Playwright binaries or dependencies, run `uv sync` and `uv run playwright install chromium` again.
