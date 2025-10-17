"""Quick usage example for the simplified BrowserAgent."""

from __future__ import annotations

from browserbot.agentkit import create_agent


def main() -> None:
    with create_agent(headless=True) as agent:
        meta = agent.navigate("https://example.com")
        print(f"Visited {meta['final_url']} -> {meta['title']}")

        links = agent.list_links("https://example.com", limit=5)
        for link in links["links"]:
            print(f"[{link['position']}] {link['text']} ({link['href']})")

        heading = agent.extract_text("https://example.com", "h1")
        print(f"Heading: {heading['text']}")


if __name__ == "__main__":
    main()
