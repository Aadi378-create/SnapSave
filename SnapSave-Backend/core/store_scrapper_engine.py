from core.browser_manager import get_browser


def run_scraper(search_url, search_selector, card_selector, name_selector, price_selector, product):

    context = get_browser()

    page = context.new_page()

    page.goto(search_url)

    page.wait_for_selector(search_selector)

    search_box = page.locator(search_selector).first

    search_box.click()
    search_box.fill(product)

    page.keyboard.press("Enter")

    try:
        page.wait_for_selector(card_selector, timeout=3000)
    except:
        pass

    products = []

    cards = page.locator(card_selector).all()

    for card in cards:

        try:

            name = card.locator(name_selector).first.inner_text()

            price_text = card.locator(price_selector).first.inner_text()

            price = int("".join(filter(str.isdigit, price_text)))

            products.append({
                "name": name,
                "price": price
            })

        except:
            continue

        if len(products) >= 4:
            break

    page.close()

    return products