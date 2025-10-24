# Botman Agent Overview

Botman couples a lightweight Playwright wrapper with a FastMCP server surface.
This document captures the intent of the code that lives under the `botman/`
package so future changes are easy to reason about.

## Package Layout

- `botman/browser/core.py` — `BrowserBot` and `create_browserbot()` plus
  low-level helpers for interacting with the DOM.
- `botman/mcp/server.py` — FastMCP server instance (`mcp`) exposing the browser
  helpers as tools.  Includes per-client session bundles keyed by
  `ctx.client_id`.
- `botman/app.py` — ASGI entrypoint (`app = mcp.http_app()`) for FastMCP Cloud
  or other HTTP deployments.
- `botman/__init__.py` — Re-exports both the browser helpers and the MCP server
  so consumers can stick with `import botman`.

Legacy imports continue to work because `browserbot/browser_bot.py` re-exports
from `botman.browser`.  The old sample scripts were archived under
`archived/examples/` to keep the runtime package minimal.

## Session Handling

The MCP tools expect the FastMCP `Context` parameter.  We use
`ctx.client_id` to look up a dedicated `BrowserBot` + `Lock` bundle.  Each
client therefore keeps its own persistent Playwright context (cookies, DOM
state, etc.) while still running synchronously to satisfy Playwright’s thread
constraints.  `configure_browser_agent()` updates defaults and resets all
sessions.

## Deployment Paths

- Local testing: `uv run fastmcp run botman/mcp/server.py`
- FastMCP Cloud / HTTP: reference `botman/app:app`
- Inspection: `fastmcp inspect botman/mcp/server.py:mcp`

## Keeping Tooling Current

Whenever you need reference material (FastMCP changelog, LangChain agent
cookbooks, etc.), fetch it via Context7 so you are always reading the latest
published docs:

```bash
context7 resolve fastmcp
context7 docs /websites/gofastmcp --topic deployment
```

Keep this file updated as the surface area grows so downstream agents know what
capabilities they can rely on.
