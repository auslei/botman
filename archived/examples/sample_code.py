"""Quick usage example for the simplified BrowserBot.

This script exercises every public helper offered by BrowserBot and can
double as a lightweight smoke test.  When run successfully it confirms:

- Stateless mode (fresh browser context per call) works for navigation,
  listing links, extracting text/HTML, clicking, screenshots, and form helpers.
- Persistent mode keeps a single page alive, enabling multi-step flows (e.g.
  clicking through, filling forms, waiting for selectors) without reloading.
"""

from __future__ import annotations

import logging

from botman.browser import create_browserbot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


def _print_section(title: str) -> None:
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)


def _run_stateless_examples() -> None:
    _print_section("Stateless helpers (fresh context per call)")
    with create_browserbot(headless=True, persist_context=False) as agent:
        meta = agent.navigate("https://example.com")
        print(f"[navigate] final_url={meta['final_url']} title={meta['title']}")

        links = agent.list_links("https://example.com", limit=3)
        print(f"[list_links] total={links['count']} truncated={links['truncated']}")
        for link in links["links"]:
            print(f"[list_links] #{link['position']} text={link['text']!r} href={link['href']!r}")

        summary = agent.describe_dom("https://example.com")
        dom_info = summary["dom"]
        print(
            f"[describe_dom] headings={len(dom_info['headings'])} forms={len(dom_info['forms_summary'])} "
            f"links={dom_info['counts']['links']}"
        )

        buttons = agent.list_buttons("https://example.com")
        sample_buttons = buttons["buttons"][:3]
        print(f"[list_buttons] count={buttons['count']} sample={sample_buttons}")

        heading = agent.extract_text("https://example.com", selector="h1")
        print(f"[extract_text] selector='h1' text={heading['text']!r}")

        markup = agent.extract_html("https://example.com", selector="h1", inner=True)
        snippet = markup["html"].strip().replace("\n", " ")
        print(f"[extract_html] inner snippet={snippet!r}")

        wait_info = agent.wait("https://example.com", delay_ms=1500)
        print(f"[wait] delay_ms={wait_info['delay_ms']} on url={wait_info['final_url']}")

        # Using click in stateless mode is of limited value (it runs in a fresh
        # context that is immediately discarded), but call it to ensure wiring.
        result = agent.click(
            "https://example.com",
            selector="text=/More information|Learn More/i",
            timeout_ms=10_000,
        )
        print(f"[click] final_url_after_click={result['final_url']} title={result['title']}")

        wait_result = agent.wait_for_selector(
            "https://example.com",
            selector="h1",
            state="visible",
        )
        print(f"[wait_for_selector] state={wait_result['state']}")

        shot = agent.screenshot("https://example.com", full_page=False)
        print(f"[screenshot] format={shot['image_format']} bytes={len(shot['screenshot_base64'])}")


def _run_persistent_examples() -> None:
    _print_section("Persistent session (reuse same page between calls)")
    with create_browserbot(headless=False, persist_context=True) as agent:
        # Initial navigation – required before calling helpers without a URL.
        meta = agent.navigate("https://example.com")
        print(f"[persistent navigate] final_url={meta['final_url']} title={meta['title']}")

        # Click a link on the existing page (no url argument needed).
        agent.click(
            selector="text=/More information|Learn More/i",
            timeout_ms=10_000,
            post_wait="load",
        )
        current_meta = agent.extract_html(selector="h1")
        print(f"[persistent click] now at url={current_meta['final_url']} title={current_meta['title']}")

        wait_info = agent.wait(delay_ms=1000)
        print(f"[persistent wait] delay_ms={wait_info['delay_ms']} on url={wait_info['final_url']}")

        # Wait for a heading on the new page and extract its text.
        agent.wait_for_selector(selector="h1", state="visible", timeout_ms=10_000)
        heading = agent.extract_text(selector="h1")
        print(f"[persistent] heading={heading['text']!r}")

        # Work with a simple form on httpbin.org.
        meta = agent.navigate("https://httpbin.org/forms/post")
        print(f"[persistent form navigate] url={meta['final_url']} title={meta['title']}")

        agent.wait_for_selector(
            selector="form input[name='custname']",
            state="visible",
            timeout_ms=10_000,
        )
        print("[persistent] form inputs became visible")
        dom_snapshot = agent.describe_dom()
        print(f"[persistent] form count={len(dom_snapshot['dom']['forms_summary'])}")
        body_snapshot = agent.extract_html(selector="body")
        first_chunk = body_snapshot["html"][:400].replace("\n", " ")
        has_radio_size = 'input type="radio" name="size"' in body_snapshot["html"]
        print(f"[persistent] body snapshot (pre-form fill): {first_chunk}...")
        print(f"[persistent] contains radio size inputs: {has_radio_size}")
        forms_detail = agent.list_forms()
        if forms_detail["forms"]:
            first_form = forms_detail["forms"][0]
            print(f"[list_forms] first form fields={len(first_form['fields'])} submitters={len(first_form['submit_controls'])}")

        agent.fill_fields(
            fields=[
                ("input[name='custname']", "Ada Lovelace"),
                ("input[name='custtel']", "1234567890"),
                ("input[name='custemail']", "ada@example.com"),
                {"selector": "input[name='size'][value='medium']", "value": True},
                ("input[name='topping'][value='cheese']", True),
            ],
            timeout_ms=10_000,
        )
        print("[persistent] fill_fields completed")
        agent.submit_form(
            submit_selector="form button",
            wait_for="pre",
            timeout_ms=10_000,
        )
        eval_result = agent.evaluate_js(script="() => document.title")
        print(f"[evaluate_js] title via JS={eval_result['result']!r}")
        summary = agent.extract_text(selector="pre")
        print(f"[persistent] form response snippet={summary['text'][:120]!r}...")

        html_dump = agent.extract_html(selector="pre")
        print(f"[persistent] response html length={len(html_dump['html'])}")

        shot = agent.screenshot(full_page=True)
        print(f"[persistent screenshot] format={shot['image_format']} bytes={len(shot['screenshot_base64'])}")


def main() -> None:
    _run_stateless_examples()
    _run_persistent_examples()


if __name__ == "__main__":
    main()
