"""Shim forwarding to the canonical BrowserBot implementation.

Prefer importing from ``botman.browser`` directly; this module is only maintained
for backwards compatibility.
"""

from botman.browser.core import *  # noqa: F401,F403

__all__ = ["BrowserBot", "create_browserbot"]
