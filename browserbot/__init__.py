"""Compatibility layer for legacy imports.

Import from :mod:`botman` directly in new code.  This module only exists to
keep older scripts working until they can be updated.
"""

from botman.browser import BrowserBot, create_browserbot
from botman.mcp import configure_browser_agent, mcp

__all__ = [
    "BrowserBot",
    "create_browserbot",
    "mcp",
    "configure_browser_agent",
]
