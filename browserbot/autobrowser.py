from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    # Launch browser (not headless so you can log in)
    browser = p.chromium.launch(headless=False)
    context = browser.new_context()

    # Open a new page
    page = context.new_page()
    page.goto("https://mail.google.com")

    # Wait for the Gmail login email input to appear
    page.wait_for_selector('input[type="email"]', timeout=10000)
    print("Gmail login page loaded. Please log in manually.")

    # Optional: keep it open for manual interaction
    input("Press Enter to close the browser...")
    browser.close()
