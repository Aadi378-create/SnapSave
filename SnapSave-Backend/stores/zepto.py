def search_zepto(page, product):

    page.goto("https://www.zepto.com/search")

    page.wait_for_selector('input[placeholder*="Search"]')

    search_box = page.locator('input[placeholder*="Search"]').first

    search_box.click()
    search_box.fill(product)
    page.keyboard.press("Enter")

    page.wait_for_timeout(5000)

    try:
        price_text = page.locator("text=₹").first.inner_text()
        price = int("".join(filter(str.isdigit, price_text)))
        return price
    except:
        return None


from playwright.sync_api import sync_playwright

def get_zepto_price(product, quantity=1, city=None):
    """
    Compatibility wrapper returning legacy numeric price.
    """
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()
            price = search_zepto(page, product)
            browser.close()
        if price is None:
            return None
        return [{"name": product, "price": price * quantity}]
    except Exception:
        return None