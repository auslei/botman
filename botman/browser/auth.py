"""Domain authentication helpers for BrowserBot.

This module defines small configuration objects that describe how to perform a
manual login for specific domains (e.g. Gmail) and where to cache the resulting
Playwright storage state. The goal is to let BrowserBot ensure an authenticated
session is available before autom autom autom.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Mapping

# Args that minimise automation fingerprints when launching a headed browser.
DEFAULT_STEALTH_ARGS: tuple[str, ...] = (
    "--disable-blink-features=AutomationControlled",
    "--disable-dev-shm-usage",
    "--disable-features=IsolateOrigins,site-per-process",
    "--disable-extensions",
    "--disable-gpu",
    "--disable-background-networking",
    "--disable-renderer-backgrounding",
)


@dataclass(frozen=True)
class DomainConfig:
    """Describe how to obtain and cache a login session for a domain."""

    domain: str
    login_url: str
    instructions: str
    storage_state_path: Path
    launch_options: Mapping[str, object] = field(default_factory=dict)
    context_options: Mapping[str, object] = field(default_factory=dict)


def default_domain_configs(base_dir: Path | None = None) -> Dict[str, DomainConfig]:
    """Return the default domain configuration set (currently Gmail only)."""

    root = base_dir or Path(__file__).resolve().parent
    storage_dir = root / "storage"
    storage_dir.mkdir(parents=True, exist_ok=True)

    gmail_storage = storage_dir / "mail.google.com.json"

    gmail_config = DomainConfig(
        domain="mail.google.com",
        login_url="https://accounts.google.com/ServiceLogin?service=mail",
        instructions=(
            "A headed Chrome window will open. Sign in to Gmail manually (including "
            "any MFA). Once your inbox loads, return to the terminal and press Enter "
            "to cache the session."
        ),
        storage_state_path=gmail_storage,
        launch_options={
            "headless": False,
            "channel": "chrome",
            "args": DEFAULT_STEALTH_ARGS,
            "slow_mo": 150,
        },
        context_options={
            "accept_downloads": True,
            "viewport": {"width": 1280, "height": 900},
        },
    )

    return {gmail_config.domain: gmail_config}


__all__ = ["DomainConfig", "default_domain_configs"]
