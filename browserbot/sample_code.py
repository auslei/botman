"""Quick usage example for the simplified BrowserBot."""

from __future__ import annotations

from browserbot.browser_bot import create_browserbot


def main() -> None:
    with create_browserbot(headless=False, persist_context=True) as agent:
        meta = agent.navigate("https://example.com")
        print(f"Visited {meta['final_url']} -> {meta['title']}")

        links = agent.list_links("https://example.com", limit=5)
        for link in links['links']:
            print(f"[{link['position']}] {link['text']} ({link['href']})")

        heading = agent.extract_text("https://example.com", selector="h1")
        print(f"Heading: {heading['text']}")

        agent.wait_for_selector("https://example.com", selector="p")
        print("Paragraph selector is present.")
        
        print(agent.extract_html("https://example.com", selector="p")['html'])

if __name__ == "__main__":
    main()
