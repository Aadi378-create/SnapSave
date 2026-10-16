from decimal import Decimal
import re
import logging
from core.browser_manager import get_browser,close_browser

def currency(text):
    match=re.search(r"(?:₹|Rs\.?\s*)?([\d,]+(?:\.\d{1,2})?)",text)
    if not match:raise ValueError("Unrecognized price")
    return float(Decimal(match.group(1).replace(",","")))

def run_scraper(search_url,search_selector,card_selector,name_selector,price_selector,product):
    page=None
    try:
        context=get_browser();page=context.new_page()
        page.goto(search_url,timeout=15000)
        box=page.locator(search_selector).first
        box.wait_for(timeout=5000);box.fill(product);page.keyboard.press("Enter")
        page.locator(card_selector).first.wait_for(timeout=5000)
        products=[]
        for card in page.locator(card_selector).all()[:100]:
            try:
                name=card.locator(name_selector).first.inner_text(timeout=1000)
                price=currency(card.locator(price_selector).first.inner_text(timeout=1000))
                products.append({"name":name,"price":price})
            except Exception:continue
            if len(products)>=10:break
        return products
    finally:
        try:
            if page:page.close()
        except Exception:
            logging.warning("Scraper page cleanup failed",exc_info=True)
        finally:
            close_browser()
