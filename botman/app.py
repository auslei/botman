"""ASGI entrypoints for hosting Botman as an MCP server."""

from __future__ import annotations

from fastmcp import FastMCP

from botman.mcp import mcp

# FastMCP Cloud expects an ASGI application.  Reuse FastMCP's helper.
app = mcp.http_app()


def get_app() -> FastMCP:
    """Return the FastMCP server instance for inspection."""
    return mcp
