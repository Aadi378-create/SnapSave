from scrapers.bigbasket_scraper import search_bigbasket

results = search_bigbasket("amul milk")

for r in results:
    print(r)