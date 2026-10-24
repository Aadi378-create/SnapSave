/* Run manually in a permitted public BigBasket catalogue/product page's console.
 * Downloads public product markup only. No account/profile/cookies are exported.
 * Import with research_catalog.py --browser-capture <downloaded file>.
 */
(async () => {
    if (location.protocol !== 'https:' || !['www.bigbasket.com', 'bigbasket.com'].includes(location.hostname)) {
        throw new Error('Open a public BigBasket product or catalogue page first.');
    }
    const source = new URL(location.href);
    source.hash = '';
    if (!/^\/(pd|pc)\//.test(source.pathname)) throw new Error('Only product/category captures are supported.');
    const response = await fetch('/robots.txt', { credentials: 'omit' });
    if (!response.ok) throw new Error('Cannot read retailer robots policy. No capture exported.');
    const robots = await response.text();
    if (robots.length > 512000 || !/^user-agent\s*:/im.test(robots)) throw new Error('Invalid robots policy.');
    const nodes = source.pathname.startsWith('/pd/')
        ? [document.querySelector('h1')?.closest('section')].filter(Boolean)
        : [...document.querySelectorAll('[class*="SKUDeck___StyledDiv"]')].slice(0, 200);
    if (!nodes.length) throw new Error('No supported rendered product markup found.');
    const html = nodes.map(node => {
        const clone = node.cloneNode(true);
        clone.querySelectorAll('script,style,img,svg,input,textarea,iframe,form').forEach(el => el.remove());
        [clone, ...clone.querySelectorAll('*')].forEach(el => {
            [...el.attributes].forEach(attr => {
                if (!['class', 'href'].includes(attr.name)) el.removeAttribute(attr.name);
            });
        });
        return clone.outerHTML;
    }).join('\n');
    if (new TextEncoder().encode(html).length > 2000000) throw new Error('Capture exceeds size budget.');
    const payload = [{store: 'bigbasket', url: source.href, captured_at: new Date().toISOString(), html, robots}];
    const url = URL.createObjectURL(new Blob([JSON.stringify(payload)], {type: 'application/json'}));
    const link = document.createElement('a');
    link.href = url; link.download = 'snapsave-catalogue-capture.json'; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    console.info('Public catalogue exported. Import within 15 minutes; stock/postcode/fees still need review.');
})();
