from playwright.sync_api import sync_playwright


def get_blinkit_price(product, quantity=1, city=None):

    try:

        with sync_playwright() as p:

            browser = p.chromium.launch(headless=False)

            context = browser.new_context()

            # default location (Gurgaon example)
            lat = "28.4132534"
            lon = "77.07271589999999"
            locality = "1849"

            # set Blinkit location cookies
            context.add_cookies([
                {
                    "name": "gr_1_lat",
                    "value": lat,
                    "domain": ".blinkit.com",
                    "path": "/"
                },
                {
                    "name": "gr_1_lon",
                    "value": lon,
                    "domain": ".blinkit.com",
                    "path": "/"
                },
                {
                    "name": "gr_1_locality",
                    "value": locality,
                    "domain": ".blinkit.com",
                    "path": "/"
                }
            ])

            page = context.new_page()

            products = []

            def handle_response(response):

                if "/v1/layout/search" in response.url:

                    data = response.json()

                    def scan(obj):

                        if isinstance(obj, dict):

                            if "name" in obj and "price" in obj:

                                products.append({
                                    "name": obj["name"],
                                    "price": int(obj["price"]) * quantity
                                })

                            for v in obj.values():
                                scan(v)

                        elif isinstance(obj, list):

                            for item in obj:
                                scan(item)

                    scan(data)

            page.on("response", handle_response)

            page.goto("https://blinkit.com/s/")

            page.wait_for_timeout(3000)

            search = page.locator("input").first

            search.click()
            search.fill(product)

            page.keyboard.press("Enter")

            page.wait_for_timeout(6000)

            browser.close()

        if not products:
            return None

        return products[:4]

    except:
        return None