"""Public catalogue evidence, never a claim of postcode stock or checkout fees.

Beautiful Soup parses product-scoped structured data. Requests are bounded,
robots-aware and confined to supported retailer origins. No login or checkout.
"""
import json
import os
import re
import time
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import quote, urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

USER_AGENT='SnapSaveResearch/0.1'
HOSTS={
    'bigbasket':{'www.bigbasket.com','bigbasket.com'},
    'zepto':{'www.zepto.com','zepto.com'},
    'blinkit':{'blinkit.com','www.blinkit.com'},
    'instamart':{'www.swiggy.com','swiggy.com'},
    'jiomart':{'www.jiomart.com','jiomart.com'},
}
DEFAULT_SOURCES={
    'bigbasket':['https://www.bigbasket.com/ps/?q={query}'],
    'zepto':['https://www.zepto.com/category/dairy-bread-eggs/milk'],
    'instamart':['https://www.swiggy.com/instamart/search?query={query}'],
    'jiomart':['https://www.jiomart.com/'],
}


class ResearchUnavailable(ValueError):
    pass


def safe_url(url, store=None):
    if not isinstance(url,str) or len(url)>2000:
        raise ResearchUnavailable('Invalid retailer URL')
    try:
        parsed=urlsplit(url)
        allowed=HOSTS.get(store,set()) if store else set().union(*HOSTS.values())
        valid=parsed.scheme=='https' and parsed.hostname in allowed and parsed.port in {None,443} and not parsed.username and not parsed.password and not parsed.fragment
    except ValueError:
        valid=False
    if not valid:
        raise ResearchUnavailable('Only configured HTTPS retailer origins are permitted')
    return url


def price(value):
    if isinstance(value,bool):
        raise ValueError('Boolean is not a price')
    text=str(value).strip().replace(',','')
    text=re.sub(r'^(?:₹|INR\s*|Rs\.?\s*)','',text,flags=re.I).strip()
    if not re.fullmatch(r'\d+(?:\.\d{1,2})?',text):
        raise ValueError('Not an exact selling price')
    try:
        amount=Decimal(text)
    except InvalidOperation:
        raise ValueError('Invalid price')
    if not amount.is_finite() or not Decimal(0)<amount<=Decimal('9999999'):
        raise ValueError('Price outside supported range')
    return float(amount)


def extract_products(html, url, store):
    """Never pair independent title/price lists or read the first rupee on a page."""
    safe_url(url,store)
    soup=BeautifulSoup(html,'html.parser')
    visible=soup.get_text(' ',strip=True).lower()
    if any(term in visible[:6000] for term in ('verify you are human','access denied','complete the captcha','unusual traffic')):
        raise ResearchUnavailable('Retailer returned a challenge or access-denied page')
    found=[]

    def add(name, amount, currency, availability, link, sku=None, method='json-ld'):
        if not isinstance(name,str) or not name.strip() or str(currency).upper()!='INR':
            return
        try:
            amount=price(amount)
            link=safe_url(urljoin(url,link or url),store)
        except (ValueError,TypeError):
            return
        availability=str(availability or '').rsplit('/',1)[-1].lower()
        stock='in_stock' if availability=='instock' else 'out_of_stock' if availability in {'outofstock','discontinued','soldout'} else 'unknown'
        found.append({'name':name.strip()[:300],'price':amount,'currency':'INR','availability':stock,
                      'source_url':link,'sku':str(sku)[:120] if sku is not None else None,'method':method})

    # Iterative traversal avoids recursive walks over large/untrusted graphs.
    for script in soup.select('script[type="application/ld+json"]')[:100]:
        try:
            data=json.loads(script.string or script.get_text())
        except (ValueError,RecursionError):
            continue
        queue=[data];visited=0
        while queue and visited<10000 and len(found)<200:
            node=queue.pop();visited+=1
            if isinstance(node,list):
                queue.extend(node[:1000]);continue
            if not isinstance(node,dict):
                continue
            types=node.get('@type',[])
            types=types if isinstance(types,list) else [types]
            if any(str(t).rsplit('/',1)[-1]=='Product' for t in types):
                offers=node.get('offers',[])
                offers=offers if isinstance(offers,list) else [offers]
                for offer in offers[:30]:
                    if isinstance(offer,dict) and 'price' in offer:
                        add(node.get('name'),offer.get('price'),offer.get('priceCurrency'),offer.get('availability'),offer.get('url') or node.get('url'),node.get('sku'))
            queue.extend(v for k,v in node.items() if isinstance(v,(dict,list)))
    for product in soup.select('[itemtype$="/Product"]')[:200]:
        def field(name):
            tag=next((tag for tag in product.select(f'[itemprop="{name}"]') if tag.find_parent(attrs={'itemtype':re.compile(r'/Product$')}) is product),None)
            return tag.get('content') or tag.get('href') or tag.get_text(' ',strip=True) if tag else None
        add(field('name'),field('price'),field('priceCurrency'),field('availability'),field('url'),field('sku'),'microdata')
    unique={}
    for row in found:
        unique.setdefault((row['name'],row['price'],row['source_url']),row)
    return list(unique.values())


class PublicCatalogClient:
    def __init__(self, timeout=30, max_requests=12, session=None):
        self.deadline=time.monotonic()+timeout
        self.max_requests=max_requests;self.requests=0
        self.session=session or requests.Session()
        self.policies={};self.pages={};self.last_request={};self.failures={}

    def close(self):
        self.session.close()

    def _get(self,url,store,limit):
        safe_url(url,store)
        is_policy=urlsplit(url).path=='/robots.txt'
        for redirect in range(3):
            remaining=self.deadline-time.monotonic()
            if remaining<=0 or self.requests>=self.max_requests:
                raise ResearchUnavailable('Research time/request budget exhausted')
            self.requests+=1
            try:
                with self.session.get(url,headers={'User-Agent':USER_AGENT,'Accept':'text/html,application/xhtml+xml,text/plain'},timeout=(min(4,remaining),min(8,remaining)),stream=True,allow_redirects=False) as response:
                    if response.status_code in {301,302,303,307,308}:
                        target=safe_url(urljoin(url,response.headers.get('Location','')),store)
                        if urlsplit(target).netloc!=urlsplit(url).netloc:
                            raise ResearchUnavailable('Cross-origin redirect requires separate policy verification')
                        # A redirect target also needs robots authorization.
                        if not is_policy and not self.allowed(target,store):
                            raise ResearchUnavailable('Redirect target is disallowed by robots policy')
                        url=target;continue
                    if response.status_code!=200:
                        raise ResearchUnavailable(f'HTTP {response.status_code}; no catalogue data accepted')
                    content=bytearray()
                    for chunk in response.iter_content(16384):
                        if len(content)+len(chunk)>limit or time.monotonic()>self.deadline:
                            raise ResearchUnavailable('Response exceeded size/time budget')
                        content.extend(chunk)
                    return content.decode(response.encoding or 'utf-8',errors='replace'),url
            except requests.RequestException as exc:
                raise ResearchUnavailable(f'Retailer connection failed: {type(exc).__name__}') from exc
        raise ResearchUnavailable('Too many redirects')

    def allowed(self,url,store):
        safe_url(url,store);origin='https://'+urlsplit(url).netloc
        if origin+'/robots.txt' in self.failures:
            raise ResearchUnavailable(self.failures[origin+'/robots.txt'])
        if origin not in self.policies:
            try:
                text,_=self._get(origin+'/robots.txt',store,512000)
                if not re.search(r'^user-agent\s*:',text,re.I|re.M):
                    raise ResearchUnavailable('No valid robots policy was returned')
            except ResearchUnavailable as exc:
                self.failures[origin+'/robots.txt']=str(exc);raise
            parser=RobotFileParser();parser.parse(text.splitlines());self.policies[origin]=parser
            self.last_request[origin]=time.monotonic()
        return self.policies[origin].can_fetch(USER_AGENT,url)

    def fetch(self,url,store):
        safe_url(url,store)
        if url in self.failures:
            raise ResearchUnavailable(self.failures[url])
        if url in self.pages:
            return self.pages[url]
        if not self.allowed(url,store):
            raise ResearchUnavailable('Retailer robots policy disallows this URL')
        origin='https://'+urlsplit(url).netloc
        delay=max(1,self.policies[origin].crawl_delay(USER_AGENT) or 0)
        wait=delay-(time.monotonic()-self.last_request.get(origin,0))
        if wait>0:
            if time.monotonic()+wait>=self.deadline:
                raise ResearchUnavailable('Crawl delay exceeds remaining research budget')
            time.sleep(wait)
        self.last_request[origin]=time.monotonic()
        try:
            html,final_url=self._get(url,store,2_000_000)
        except ResearchUnavailable as exc:
            self.failures[url]=str(exc);raise
        self.pages[url]=(html,final_url)
        return html,final_url


def sources():
    configured=os.getenv('RESEARCH_CATALOG_SOURCES')
    try:
        values=json.loads(configured) if configured else DEFAULT_SOURCES
    except ValueError as exc:
        raise ResearchUnavailable('Catalogue source configuration is not valid JSON') from exc
    if not isinstance(values,dict) or len(values)>5:
        raise ResearchUnavailable('Catalogue sources must be a supported store-to-URL-list mapping')
    for store,urls in values.items():
        if store not in HOSTS or not isinstance(urls,list) or not 1<=len(urls)<=3:
            raise ResearchUnavailable('Invalid catalogue source configuration')
        for url in urls:
            safe_url(url,store)
    return values


def matching_candidates(query,products):
    from core.product_ranker import score_product
    from core.query_parser import parse_query
    wanted=parse_query(query)
    def pack(value):
        if value['volume'] is None:
            return None
        amount=Decimal(str(value['volume']));unit=value['unit']
        return (amount*1000,'g') if unit=='kg' else (amount*1000,'ml') if unit=='l' else (amount,unit)
    result=[]
    for row in products:
        if row['availability']=='out_of_stock' or score_product(query,row['name'])<=0:
            continue
        if pack(wanted) is not None and pack(parse_query(row['name']))!=pack(wanted):
            continue
        result.append(row)
    return sorted(result,key=lambda r:(r['price'],r['name']))[:4]


def research_catalog(items,postal_code,client=None):
    """Configured AI provider: collect review-only evidence, never verified totals."""
    if not re.fullmatch(r'[1-9][0-9]{5}',str(postal_code)):
        raise ResearchUnavailable('A six-digit Indian delivery postcode is required')
    if not isinstance(items,list) or not 1<=len(items)<=20:
        raise ResearchUnavailable('Catalogue research supports 1–20 items per job')
    seen=set()
    for item in items:
        if not isinstance(item,dict) or not isinstance(item.get('item_id'),str) or item['item_id'] in seen or not isinstance(item.get('name'),str) or not 1<=len(item['name'].strip())<=500 or type(item.get('quantity')) is not int or not 1<=item['quantity']<=10000:
            raise ResearchUnavailable('Research items need unique IDs, a product query and positive integer quantity')
        seen.add(item['item_id'])
    config=sources();owned=client is None;client=client or PublicCatalogClient()
    result=[];diagnostics=[];parsed_pages={}
    try:
        for item in items:
            query=item['name'];candidates=[]
            for store,urls in config.items():
                for template in urls:
                    url=template.replace('{query}',quote(query,safe=''))
                    try:
                        key=(store,url)
                        if key not in parsed_pages:
                            html,final_url=client.fetch(url,store)
                            parsed_pages[key]=extract_products(html,final_url,store)
                        rows=matching_candidates(query,parsed_pages[key])
                        for row in rows:
                            candidates.append({**row,'store':store})
                        diagnostics.append({'store':store,'url':url,'status':'candidates' if rows else 'no_product_evidence','count':len(rows)})
                    except ResearchUnavailable as exc:
                        diagnostics.append({'store':store,'url':url,'status':'unavailable','reason':str(exc)})
            result.append({'item_id':item['item_id'],'query':query,'quantity':item['quantity'],'candidates':sorted(candidates,key=lambda r:r['price'])[:6]})
    finally:
        if owned:client.close()
    return {'verified':False,'requires_human_review':True,'postal_code':str(postal_code),
            'source':'Public catalogue evidence (Beautiful Soup)','observed_at':datetime.now(timezone.utc).isoformat(),
            'warnings':['Delivery postcode, stock, exact pack, checkout fees and promotions require human verification. Public prices are not a payable quote.'],
            'items':result,'diagnostics':diagnostics[:100]}
