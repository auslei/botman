"""FastMCP wrapper that exposes the BrowserAgent as an MCP server."""

from __future__ import annotations

import argparse
import asyncio
from typing import Any, Optional

from fastmcp import Application

try:
    from fastmcp.server import serve_application
except ImportError:  # pragma: no cover - fallback for older FastMCP releases
    serve_application = None  # type: ignore[assignment]

from .agentkit import BrowserAgent, create_agent


class BrowserAgentFastMCP:
    """Convenience wrapper that binds a ``BrowserAgent`` to FastMCP."""

    def __init__(self, agent: Optional[BrowserAgent] = None) -> None:
        self._agent = agent or create_agent()
        self._lock = asyncio.Lock()

    def create_app(self, name: str = "browserbot-agent") -> Application:
        """Return a FastMCP ``Application`` instance with registered tools."""
        app = Application(name)

        @app.on_startup
        async def _startup(*_: Any) -> None:
            await self._call(self._agent.startup)

        @app.on_shutdown
        async def _shutdown(*_: Any) -> None:
            await self._call(self._agent.shutdown)

        @app.tool()
        async def ensure_login(domain: str, force: bool = False) -> dict[str, Any]:
            await self._call(self._agent.ensure_login, domain, force=force)
            return {"domain": domain, "force": force, "status": "ok"}

        @app.tool()
        async def navigate(url: str, wait_until: str = "load") -> dict[str, Any]:
            return await self._call(self._agent.navigate, url, wait_until=wait_until)

        @app.tool()
        async def extract_text(
            url: str,
            selector: str,
            wait_until: str = "load",
            timeout_ms: int = 5000,
        ) -> dict[str, Any]:
            return await self._call(
                self._agent.extract_text,
                url,
                selector,
                wait_until=wait_until,
                timeout_ms=timeout_ms,
            )

        @app.tool()
        async def click(
            url: str,
            selector: str,
            wait_until: str = "load",
            post_wait: Optional[str] = "networkidle",
            timeout_ms: int = 5000,
        ) -> dict[str, Any]:
            return await self._call(
                self._agent.click,
                url,
                selector,
                wait_until=wait_until,
                post_wait=post_wait,
                timeout_ms=timeout_ms,
            )

        @app.tool()
        async def open_session(url: str, wait_until: str = "load") -> dict[str, Any]:
            return await self._call(self._agent.open_session, url, wait_until=wait_until)

        @app.tool()
        async def session_goto(session_id: str, url: str, wait_until: str = "load") -> dict[str, Any]:
            return await self._call(
                self._agent.session_goto,
                session_id,
                url,
                wait_until=wait_until,
            )

        @app.tool()
        async def session_extract_text(
            session_id: str,
            selector: str,
            timeout_ms: int = 5000,
        ) -> dict[str, Any]:
            return await self._call(
                self._agent.session_extract_text,
                session_id,
                selector,
                timeout_ms=timeout_ms,
            )

        @app.tool()
        async def session_click(
            session_id: str,
            selector: str,
            timeout_ms: int = 5000,
            post_wait: Optional[str] = "networkidle",
        ) -> dict[str, Any]:
            return await self._call(
                self._agent.session_click,
                session_id,
                selector,
                timeout_ms=timeout_ms,
                post_wait=post_wait,
            )

        @app.tool()
        async def close_session(session_id: str) -> dict[str, Any]:
            return await self._call(self._agent.close_session, session_id)

        return app

    async def _call(self, func, *args, **kwargs) -> Any:
        async with self._lock:
            return await asyncio.to_thread(func, *args, **kwargs)


def create_fastmcp_app(headless: bool = True, name: str = "browserbot-agent") -> Application:
    """Construct a FastMCP ``Application`` with a fresh ``BrowserAgent``."""
    wrapper = BrowserAgentFastMCP(create_agent(headless=headless))
    return wrapper.create_app(name=name)


def main() -> None:
    """CLI entry point for launching the FastMCP server."""
    parser = argparse.ArgumentParser(description="Start the BrowserBot FastMCP server.")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface to bind.")
    parser.add_argument("--port", type=int, default=8000, help="Port to listen on.")
    parser.add_argument("--headed", action="store_true", help="Launch Chromium in headed mode.")
    parser.add_argument("--name", default="browserbot-agent", help="FastMCP application name.")
    args = parser.parse_args()

    app = create_fastmcp_app(headless=not args.headed, name=args.name)

    if serve_application is not None:
        asyncio.run(serve_application(app, host=args.host, port=args.port))
        return

    serve_attr = getattr(app, "serve", None)
    if serve_attr is None:
        raise RuntimeError(
            "fastmcp.server.serve_application is unavailable and the Application "
            "object does not expose a 'serve' coroutine. Update FastMCP or provide "
            "a compatible runner."
        )
    asyncio.run(serve_attr(host=args.host, port=args.port))


__all__ = ["BrowserAgentFastMCP", "create_fastmcp_app", "main"]


if __name__ == "__main__":
    main()
