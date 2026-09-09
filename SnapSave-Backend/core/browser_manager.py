from playwright.sync_api import sync_playwright

playwright = None
browser_context = None


def get_browser():

    global playwright
    global browser_context

    if browser_context is None:

        playwright = sync_playwright().start()

        browser_context = playwright.chromium.launch_persistent_context(
            "browser_profile",
            headless=True
        )

    return browser_context


def close_browser():

    global playwright
    global browser_context

    if browser_context:
        browser_context.close()
        playwright.stop()