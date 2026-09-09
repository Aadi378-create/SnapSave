from playwright.sync_api import sync_playwright

with sync_playwright() as p:

    browser = p.chromium.launch(headless=False)
    page = browser.new_page()

    page.goto("https://www.bigbasket.com/ps/?q=milk")

    page.wait_for_timeout(10000)

    print("Page loaded")

    browser.close()