/* Only a toolbar click grants access. No background scraping or persistent host access. */
export function supportedPage(value) {
    try {
        const url=new URL(value);
        if(url.protocol!=='https:' || url.username || url.password || (url.port && url.port!=='443'))return false;
        const paths={
            'www.bigbasket.com':/^\/(pd|pc)\//,'bigbasket.com':/^\/(pd|pc)\//,
            'www.zepto.com':/^\/(category|pn|cn)\//,'zepto.com':/^\/(category|pn|cn)\//,
            'blinkit.com':/^\/(cn|prn|dc)\//,'www.blinkit.com':/^\/(cn|prn|dc)\//,
            'www.swiggy.com':/^\/instamart(?:\/|$)/,'swiggy.com':/^\/instamart(?:\/|$)/
        };
        return !!paths[url.hostname]?.test(url.pathname);
    } catch(error){return false;}
}

const busyTabs=new Set();
export async function captureTab(tab,api) {
    if(!Number.isInteger(tab?.id) || !supportedPage(tab.url)) {
        if(Number.isInteger(tab?.id))await api.action.setTitle({tabId:tab.id,title:'Open a supported public retailer product/category page first.'});
        return false;
    }
    const tabId=tab.id;
    if(busyTabs.has(tabId))return false;
    busyTabs.add(tabId);
    try {
        await api.action.setBadgeText({tabId,text:'…'});
        const results=await api.scripting.executeScript({target:{tabId},files:['capture.js'],world:'ISOLATED'});
        const result=results[0]?.result;
        if(result?.ok!==true)throw new Error(result?.error||'Capture was not completed.');
        await api.action.setBadgeText({tabId,text:'OK'});
        await api.action.setTitle({tabId,title:'Capture downloaded. Import the JSON into the same SnapSave ticket within 15 minutes.'});
        return true;
    } catch(error) {
        await api.action.setBadgeText({tabId,text:'!'});
        await api.action.setTitle({tabId,title:'SnapSave capture failed: '+String(error.message).slice(0,180)});
        return false;
    } finally {busyTabs.delete(tabId);}
}

if(typeof chrome!=='undefined' && chrome.action?.onClicked) {
    chrome.action.onClicked.addListener(tab=>{void captureTab(tab,chrome).catch(()=>{});});
}
