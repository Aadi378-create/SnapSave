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
    'bigbasket':['https://www.bigbasket.com/pc/bakery-cakes-dairy/dairy/milk/'],
    'zepto':['https://www.zepto.com/category/dairy-bread-eggs/milk'],
    'instamart':['https://www.swiggy.com/instamart/'],
    'blinkit':['https://blinkit.com/cn/milk/cid/14/922'],
    'jiomart':['https://www.jiomart.com/'],
}


class ResearchUnavailable(ValueError):
    pass


class RobotsPolicy:
    """Longest matching rule, wildcard and end-anchor support for retailer policies."""
    def __init__(self, text):
        self.groups=[];agents=[];rules=[];delay=None;started=False
        for line in text.splitlines()+['User-agent: __end__']:
            key,sep,value=line.partition('#')[0].partition(':')
            if not sep:continue
            key=key.strip().lower();value=value.strip()
            if key=='user-agent':
                if started:
                    self.groups.append((agents,rules,delay));agents=[];rules=[];delay=None;started=False
                agents.append(value.lower())
            elif agents and key in {'allow','disallow','crawl-delay'}:
                started=True
                if key=='crawl-delay':
                    try:delay=max(0,float(value))
                    except ValueError:pass
                elif value:rules.append((value,key=='allow'))

    def _groups(self, agent):
        token=agent.split('/')[0].lower()
        specific=[g for g in self.groups if token in g[0]]
        return specific or [g for g in self.groups if '*' in g[0]]

    def can_fetch(self, agent, url):
        parts=urlsplit(url);path=parts.path or '/'
        if parts.query:path+='?'+parts.query
        # Decode only unreserved escapes; encoded slashes stay distinct.
        def normalize(value):
            value=quote(value,safe='/%?=&*.$~!()+,;:@-_')
            return re.sub(r'%([0-9a-fA-F]{2})',lambda m:chr(int(m[1],16)) if chr(int(m[1],16)) in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~' else '%'+m[1].upper(),value)
        path=normalize(path);matches=[]
        for _,rules,_ in self._groups(agent):
            for rule,allowed in rules:
                rule=normalize(rule);end=rule.endswith('$');body=rule[:-1] if end else rule
                # Only '*' is special. Ordered literal searches avoid regex
                # backtracking on adversarial policies supplied in captures.
                parts=body.split('*')
                matched=False
                if len(parts)==1:
                    matched=path==body if end else path.startswith(body)
                elif path.startswith(parts[0]):
                    cursor=len(parts[0]);matched=True
                    for part in parts[1:-1]:
                        position=path.find(part,cursor)
                        if position<0:matched=False;break
                        cursor=position+len(part)
                    if matched:
                        tail=parts[-1]
                        matched=(path.endswith(tail) and len(path)-len(tail)>=cursor) if end else path.find(tail,cursor)>=0
                if matched:matches.append((len(body.replace('*','').encode()),allowed))
        return max(matches,default=(0,True))[1]

    def crawl_delay(self,agent):
        return max((g[2] or 0 for g in self._groups(agent)),default=0)


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

    def add(name, amount, currency, availability, link, sku=None, method='json-ld', pack_label=None):
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
                      'source_url':link,'sku':str(sku)[:120] if sku is not None else None,'method':method,
                      **({'pack_size':pack_label} if pack_label else {})})

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
    if store=='bigbasket':
        # Observed rendered product page: labelled Price cell excludes MRP/unit price.
        for heading in soup.select('h1')[:1]:
            section=heading.find_parent('section')
            if not section or not re.match(r'/pd/\d+/',urlsplit(url).path):continue
            cells=[cell.get_text(' ',strip=True) for cell in section.select('td')]
            selling=[re.sub(r'^Price:\s*','',cell) for cell in cells if re.match(r'^Price:\s*₹',cell)]
            if len(selling)==1:
                add(heading.get_text(' ',strip=True),selling[0],'INR',None,url,urlsplit(url).path.split('/')[2],'bigbasket-rendered-product')
        # Product cards keep the heading, selected pack and selling price together.
        for card in soup.select('[class*="SKUDeck___StyledDiv"]')[:200]:
            link=card.select_one('h3 a[href^="/pd/"]')
            pack=card.select_one('h3 button, h3 [class*="PackSelector___StyledLabel"]')
            prices=card.select('span.sc-guJBdh')
            if not link or not pack or len(prices)!=1:continue
            href=link.get('href','').split('?')[0]
            match=re.match(r'^/pd/(\d+)/',href)
            if not match:continue
            stock='OutOfStock' if re.search(r'\b(not available|out of stock)\b',card.get_text(' ',strip=True),re.I) else None
            add(link.get_text(' ',strip=True)+' '+pack.get_text(' ',strip=True),prices[0].get_text(strip=True),'INR',stock,href,match[1],'bigbasket-rendered-card',pack.get_text(' ',strip=True))
    if store=='zepto':
        for card in soup.select('a[data-testid="product-card"][href*="/pvid/"]')[:200]:
            name=card.select_one('[data-slot-id="ProductName"]');pack=card.select_one('[data-slot-id="PackSize"]')
            amounts=card.select('[data-slot-id="EdlpPrice"] > span.cptQT7')
            if not name or not pack or len(amounts)!=1:continue
            # Some pages advertise alternative pack sizes in the same label.
            if re.search(r'\bor\b|\d\s*[x×]\s*\d',pack.get_text(' ',strip=True),re.I):continue
            stock=card.select_one('[data-is-out-of-stock="true"]')
            href=card['href'].split('?')[0]
            add(name.get_text(' ',strip=True)+' '+pack.get_text(' ',strip=True),amounts[0].get_text(strip=True),'INR','OutOfStock' if stock else None,href,href.rsplit('/',1)[-1],'zepto-rendered-card',pack.get_text(' ',strip=True))
    if store=='instamart':
        for card in soup.select('div._1fi7p')[:200]:
            name=card.select_one('div._1iFYi');pack=card.select_one('div._3wq_F')
            amounts=card.select('div._2enD- > div._2jn41:not(._3eAjW):not(._1VrXB)')
            if not name or not pack or len(amounts)!=1:continue
            add(name.get_text(' ',strip=True)+' '+pack.get_text(' ',strip=True),amounts[0].get_text(strip=True),'INR',None,url,None,'instamart-rendered-card',pack.get_text(' ',strip=True))
    if store=='blinkit':
        for card in soup.select('[role="button"][id]')[:200]:
            sku=card.get('id','')
            if not sku.isdigit():continue
            name=card.select_one('.tw-line-clamp-2');pack=card.select_one('.tw-line-clamp-1')
            amounts=[n for n in card.select('.tw-text-200.tw-font-semibold') if n.get_text(strip=True).startswith('₹')]
            if not name or not pack or len(amounts)!=1:continue
            if re.search(r'\d\s*[x×]\s*\d',pack.get_text(' ',strip=True),re.I):continue
            # Numeric card ID is the observed product identifier; source remains
            # the actual category page rather than inventing a product URL.
            add(name.get_text(' ',strip=True)+' '+pack.get_text(' ',strip=True),amounts[0].get_text(strip=True),'INR',None,url,sku,'blinkit-rendered-card',pack.get_text(' ',strip=True))
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
            self.policies[origin]=RobotsPolicy(text)
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


class BrowserCaptureClient:
    """Explicit offline import of public DOM captures; never simulates a live fetch.

    Captures contain product markup only, no cookies, profiles or credentials.
    The capture's robots policy is supplied evidence, not server authentication.
    """
    def __init__(self, captures, max_age=900):
        if not isinstance(captures,list) or not 1<=len(captures)<=15:
            raise ResearchUnavailable('Supply 1–15 browser captures')
        self.captures={};self.observed_at={};self.locations={};self.contexts={}
        now=datetime.now(timezone.utc)
        for capture in captures:
            if not isinstance(capture,dict):raise ResearchUnavailable('Invalid browser capture')
            url=capture.get('url');store=capture.get('store');safe_url(url,store)
            if store not in HOSTS:raise ResearchUnavailable('Unsupported capture store')
            html=capture.get('html');robots=capture.get('robots');stamp=capture.get('captured_at')
            if not isinstance(html,str) or len(html.encode())>2_000_000 or not isinstance(robots,str) or len(robots.encode())>512000:
                raise ResearchUnavailable('Capture markup/policy missing or too large')
            try:
                observed=datetime.fromisoformat(stamp)
                if observed.tzinfo is None:raise ValueError()
                age=(now-observed).total_seconds()
                if not 0<=age<=max_age:raise ValueError()
            except (TypeError,ValueError):
                raise ResearchUnavailable('Browser capture must be timestamped within the last 15 minutes')
            if not re.search(r'^user-agent\s*:',robots,re.I|re.M) or not RobotsPolicy(robots).can_fetch(USER_AGENT,url):
                raise ResearchUnavailable('Capture URL lacks a permitting robots policy')
            self.captures[(store,url)]=html
            self.observed_at[(store,url)]=observed.isoformat()
            context=capture.get('research_context') or {}
            location=capture.get('location_context') or {}
            if not isinstance(context,dict) or not isinstance(location,dict):raise ResearchUnavailable('Invalid capture location context')
            self.contexts[(store,url)]=context
            self.locations[(store,url)]=location

    def fetch(self,url,store):
        if (store,url) not in self.captures:raise ResearchUnavailable('No browser capture supplied for this URL')
        return self.captures[(store,url)],url

    def close(self):pass


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
        label=row.get('pack_size') or row['name']
        if re.search(r'\d\s*[x×]\s*\d|\b\d+\s*(?:ml|ltr|l|g|kg)\s+or\b',label,re.I):continue
        if pack(wanted) is not None and pack(parse_query(label))!=pack(wanted):
            continue
        result.append(row)
    return sorted(result,key=lambda r:(r['price'],r['name']))[:4]


def capture_location(context,postal_code):
    """A supplied postcode/attestation is evidence, never proof of serviceability."""
    selected=context.get('selected_postal_code')
    if selected is not None and not re.fullmatch(r'[1-9][0-9]{5}',str(selected)):
        raise ResearchUnavailable('Invalid retailer location postcode')
    status='mismatch' if selected and str(selected)!=postal_code else 'postcode_observed' if selected else 'needs_location'
    if not selected and context.get('staff_confirmed') is True and context.get('attested_postal_code')==postal_code:
        status='staff_attested'
    return {'requested_postal_code':postal_code,'selected_postal_code':str(selected) if selected else None,
            'status':status,'serviceability_verified':False}


def location_plan(order_id,revision,postal_code):
    """Only order-bound postcode goes into research setup, never street/contact data."""
    if not re.fullmatch(r'[1-9][0-9]{5}',str(postal_code)):
        raise ResearchUnavailable('A six-digit Indian delivery postcode is required')
    return {'order_id':order_id,'revision':revision,'postal_code':str(postal_code),
            'stores':{store:urls[0] for store,urls in DEFAULT_SOURCES.items() if store in {'bigbasket','zepto','instamart','blinkit'}},
            'steps':['Open the retailer in a separate research tab for this order.',
                     'Use its location selector to enter this postcode and choose the matching area; never accept the previous browser location.',
                     'If it requires an exact address or cannot confirm the area, stop and request location review.',
                     'Wait for products to reload. If closed or unserviceable, record that state; do not claim stock.',
                     'Export public product evidence with this order context, then import it into this ticket.',
                     'Staff must verify availability and checkout fees before publishing any quote.']}


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
    config=sources();owned=client is None
    if client is None and os.getenv('RESEARCH_BROWSER_CAPTURE_FILE'):
        from pathlib import Path
        path=Path(os.environ['RESEARCH_BROWSER_CAPTURE_FILE'])
        try:
            if path.stat().st_size>8_000_000:raise ResearchUnavailable('Capture file exceeds 8 MB')
            client=BrowserCaptureClient(json.loads(path.read_text(encoding='utf-8')))
        except OSError as exc:
            raise ResearchUnavailable('Configured browser capture file cannot be read') from exc
    client=client or PublicCatalogClient()
    captured=isinstance(client,BrowserCaptureClient)
    if captured:
        config={}
        for store,url in client.captures:config.setdefault(store,[]).append(url)
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
                        location=capture_location(client.locations[key],str(postal_code)) if captured else capture_location({},str(postal_code))
                        if captured and client.contexts[key].get('postal_code') not in {None,str(postal_code)}:
                            raise ResearchUnavailable('Capture was prepared for a different customer postcode')
                        if location['status']=='mismatch':
                            raise ResearchUnavailable('Retailer location postcode does not match this order')
                        rows=matching_candidates(query,parsed_pages[key])
                        for row in rows:
                            candidates.append({**row,'store':store,'location_context':location,**({'observed_at':client.observed_at[key]} if captured else {})})
                        diagnostics.append({'store':store,'url':url,'status':'candidates' if rows else 'no_product_evidence','count':len(rows)})
                    except ResearchUnavailable as exc:
                        diagnostics.append({'store':store,'url':url,'status':'unavailable','reason':str(exc)})
            unique={}
            for row in candidates:
                unique.setdefault((row['store'],row.get('sku') or row['name'],row['source_url'],row['price']),row)
            result.append({'item_id':item['item_id'],'query':query,'quantity':item['quantity'],'candidates':sorted(unique.values(),key=lambda r:r['price'])[:6]})
    finally:
        if owned:client.close()
    return {'verified':False,'requires_human_review':True,'postal_code':str(postal_code),
            'research_contexts':[{k:context.get(k) for k in ('order_id','revision','postal_code')} for context in client.contexts.values() if context.get('order_id')] if captured else [],
            'source':'Browser-assisted catalogue capture (Beautiful Soup)' if captured else 'Public catalogue evidence (Beautiful Soup)',
            'transport':'browser_capture' if captured else 'http','observed_at':datetime.now(timezone.utc).isoformat(),
            'warnings':['Delivery postcode, stock, exact pack, checkout fees and promotions require human verification. Public prices are not a payable quote.'],
            'items':result,'diagnostics':diagnostics[:100]}
