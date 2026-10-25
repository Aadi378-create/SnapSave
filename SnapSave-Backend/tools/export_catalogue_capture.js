/* Run manually on a permitted public retailer page after selecting the order location.
 * Downloads public product markup only; no account/profile/cookies are exported.
 */
(async () => {
    const host = location.hostname;
    const store = ({'www.bigbasket.com':'bigbasket','bigbasket.com':'bigbasket','www.zepto.com':'zepto','zepto.com':'zepto',
        'blinkit.com':'blinkit','www.blinkit.com':'blinkit','www.swiggy.com':'instamart','swiggy.com':'instamart'})[host];
    if (location.protocol !== 'https:' || !store) throw new Error('Open a supported public retailer page first.');
    const source = new URL(location.href); source.hash = '';
    const permitted = {bigbasket:/^\/(pd|pc)\//,zepto:/^\/(category|pn|cn)\//,blinkit:/^\/(cn|prn|dc)\//,instamart:/^\/instamart(?:\/|$)/};
    if (!permitted[store].test(source.pathname)) throw new Error('Only public product/category captures are supported.');
    const input = prompt('Paste the research context copied from the SnapSave ticket. Leave blank for a standalone CLI capture.');
    if (input === null) throw new Error('Capture cancelled.');
    let context = {};
    if (input?.trim()) {
        context = JSON.parse(input);
        if (typeof context.order_id !== 'string' || !Number.isInteger(context.revision) || !/^[1-9][0-9]{5}$/.test(context.postal_code)) throw new Error('Invalid research context. Copy it again from the ticket.');
        context = {order_id:context.order_id, revision:context.revision, postal_code:context.postal_code};
    }
    const header = document.querySelector('header,[role="banner"]')?.innerText || '';
    const pins = [...new Set(header.match(/\b[1-9][0-9]{5}\b/g) || [])];
    const selected = pins.length === 1 ? pins[0] : null;
    if (selected && context.postal_code && selected !== context.postal_code) throw new Error('Retailer postcode differs from this order. Change its location and retry.');
    const confirmed = !!context.postal_code && confirm('Have you selected the retailer delivery area for customer postcode '+context.postal_code+' and waited for products to reload? Confirm only if checked. Stock and fees still need review.');
    if (context.postal_code && !confirmed) throw new Error('Select the customer location before exporting.');
    const response = await fetch('/robots.txt', { credentials: 'omit', redirect:'error', signal:AbortSignal.timeout(10000) });
    if (response.status !== 200) throw new Error('Cannot read retailer robots policy (HTTP '+response.status+'). No capture exported.');
    const robots = await response.text();
    if (new TextEncoder().encode(robots).length > 512000 || !/^user-agent\s*:/im.test(robots)) throw new Error('Invalid robots policy.');
    const selectors = {zepto:'a[data-testid="product-card"][href*="/pvid/"]',instamart:'div._1fi7p',blinkit:'[role="button"][id]',bigbasket:'[class*="SKUDeck___StyledDiv"]'};
    let nodes = store === 'bigbasket' && source.pathname.startsWith('/pd/')
        ? [document.querySelector('h1')?.closest('section')].filter(Boolean)
        : [...document.querySelectorAll(selectors[store])];
    if (store === 'blinkit') nodes = nodes.filter(node => /^\d+$/.test(node.id));
    const count = Math.min(nodes.length, 30);
    nodes = nodes.slice(0, count);
    if (!nodes.length) throw new Error('No supported rendered product markup found.');
    const html = nodes.map(node => {
        const clone = node.cloneNode(true);
        clone.querySelectorAll('script,style,img,svg,input,textarea,iframe,form').forEach(el => el.remove());
        [clone, ...clone.querySelectorAll('*')].forEach(el => {
            [...el.attributes].forEach(attr => {
                if (!['class','href','id','role','data-testid','data-slot-id','data-is-out-of-stock'].includes(attr.name)) el.removeAttribute(attr.name);
            });
        });
        return clone.outerHTML;
    }).join('');
    // Location can hydrate/change while the policy request is in flight.
    const finalHeader = document.querySelector('header,[role="banner"]')?.innerText || '';
    const finalPins = [...new Set(finalHeader.match(/\b[1-9][0-9]{5}\b/g) || [])];
    const finalSelected = finalPins.length === 1 ? finalPins[0] : null;
    if (selected !== finalSelected || (finalSelected && context.postal_code && finalSelected !== context.postal_code)) {
        throw new Error('Retailer location changed while capturing. Check the postcode and recapture.');
    }
    const payload = [{store, url:source.href, captured_at:new Date().toISOString(), html, robots,
        research_context:context, location_context:{selected_postal_code:selected,staff_confirmed:confirmed,attested_postal_code:confirmed?context.postal_code:null}}];
    const body = JSON.stringify(payload);
    if (new TextEncoder().encode(body).length > 60000) throw new Error('Capture exceeds 60 KB. Use a smaller category or product page.');
    const url = URL.createObjectURL(new Blob([body], {type:'application/json'}));
    const link = document.createElement('a'); link.href=url; link.download='snapsave-'+store+'-capture.json'; link.click();
    setTimeout(() => URL.revokeObjectURL(url),1000);
    console.info('Exported '+count+' public cards. Import within 15 minutes. Postcode selection is staff-attested; coverage and fees remain unverified.');
})();
