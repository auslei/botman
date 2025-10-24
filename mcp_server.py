"""Top-level FastMCP server entrypoint for Botman.

FastMCP Cloud expects to inspect a module path like ``mcp_server:mcp``.  This
thin wrapper re-exports the configured server from the packaged implementation.
"""

from botman.mcp.server import configure_browser_agent, mcp  # noqa: F401

__all__ = ["mcp", "configure_browser_agent"]
