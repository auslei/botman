"""Helper script to capture and reuse a Gmail authentication session."""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
    # Allow running the file directly via ``python browserbot/google.py``.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from browserbot.agentkit import create_agent  # noqa: E402


def main() -> None:
    """Launch a headed browser so the user can complete Gmail login once."""
    agent = create_agent(headless=False)
    with agent:
        #agent.ensure_login("mail.google.com", force=True)
        
        session = agent.open_session("https://www.webpagetest.org/")
        print(f"Opened session: {session}")
        session_id = session["session_id"]
        result = agent.session_extract_text(session_id=session_id, selector="body", timeout_ms=120000)
        print(f"Extracted {len(result['text'])} characters of text from the page.")
        
        # Click the About navigation item
        click_result = agent.session_click(
            session_id=session_id,
            selector='text=About',         # Playwright text selector
            post_wait="load",               # wait for the next page to load
            timeout_ms=6000
        )
        print(click_result)
        
        agent.close_session(session_id)
    print("Gmail session stored. You can close this terminal.")


if __name__ == "__main__":
    main()
