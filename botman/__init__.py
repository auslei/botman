"""Botman: browser automation tools packaged with an MCP server."""

from .app import app
from .browser import BrowserBot, create_browserbot
from .mcp import configure_browser_agent, mcp

__all__ = [
    "BrowserBot",
    "create_browserbot",
    "mcp",
    "configure_browser_agent",
    "app",
]
