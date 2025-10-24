"""CLI helper to prime cached sessions for Botman domains."""

from __future__ import annotations

import argparse

from botman.browser.core import create_browserbot


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Launch a headed browser and cache the login session for a domain.",
    )
    parser.add_argument("domain", help="Domain to authenticate (e.g. mail.google.com)")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force the login flow even if a storage state already exists.",
    )
    parser.add_argument(
        "--persist",
        dest="persist",
        action="store_true",
        help="Keep a persistent context alive after login (default: transient).",
    )
    args = parser.parse_args()

    with create_browserbot(headless=False, persist_context=args.persist) as agent:
        result = agent.ensure_login(args.domain, force=args.force)
        print(
            "Cached storage state for {domain} at {path}".format(
                domain=result["domain"], path=result["storage_state"]
            )
        )


if __name__ == "__main__":
    main()
