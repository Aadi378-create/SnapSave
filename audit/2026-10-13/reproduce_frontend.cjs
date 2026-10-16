// Execute the existing inline scripts with a small DOM/fetch fixture; no browser/network.
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const root = path.resolve(__dirname, '../..');
const results = {};
function fixture() {
  const els = new Map();
  function el() { return { innerHTML: '', innerText: '', value: '', style: {}, dataset: {}, disabled: false, children: [], classList: { add(){}, remove(){}, toggle(){} }, addEventListener(){}, querySelectorAll(){return []}, appendChild(x){this.children.push(x)}, querySelector(){return el()} }; }
  const context = { console, window: { location: { hostname: 'localhost', origin: 'http://localhost:3000' } }, document: { getElementById(id){ if(!els.has(id)) els.set(id, el()); return els.get(id); }, querySelectorAll(){return []}, querySelector(){return el()}, createElement: el }, localStorage: {getItem(){return null}, setItem(){}, removeItem(){}}, setInterval(){return 1}, clearInterval(){}, initializeApp(){return {}}, getAuth(){return {}}, onAuthStateChanged(){}, alert(){}, confirm(){return true} };
  context.window.window = context.window;
  vm.createContext(context);
  return context;
}
async function main() {
  const html = fs.readFileSync(path.join(root, 'SnapSave-FRONTEND/index.html'), 'utf8');
  let source = html.match(/<script type="module">([\s\S]*?)<\/script>/)[1];
  source = source.replace(/import[\s\S]*?from\s+"[^"]+";/g, '');
  const x = fixture();
  let orders = [{id:'active',status:'reviewing',final_price:0,subtotal:0,savings:0}, {id:'past',status:'delivered',final_price:100,subtotal:100,savings:0}];
  x.fetch = async url => ({ok:true, json:async()=>url.endsWith('/api/orders') ? orders : []});
  vm.runInContext(source + '\n globalThis.audit={loadOrders,pollMessages,renderChatMessages,renderActiveTracker,setUser(v){currentUser=v},getOrder(){return activeOrder}};', x);
  x.audit.setUser({id:'customer'});
  await x.audit.loadOrders();
  // These global handlers call bare global names, as they do in a browser.
  Object.assign(x, x.window);
  await x.window.viewHistoryOrder('past');
  results.history_switch = {requested:'past',actual:x.audit.getOrder()?.id};
  await x.window.startNewOrder();
  results.new_order = {actual:x.audit.getOrder()?.id};
  x.audit.renderActiveTracker({id:'placed',status:'placed',final_price:100});
  results.placed_tracker_delivered = /step-item completed">5\. Delivered/.test(x.document.getElementById('active-order-container').innerHTML);
  x.audit.renderChatMessages([{id:'m',order_id:'active',sender_role:'CUSTOMER',message:'<img src=x onerror="AUDIT_MARKER()">'}]);
  results.unescaped_message_html = x.document.getElementById('chat-stream').children.some(e=>e.innerHTML.includes('onerror="AUDIT_MARKER()"'));
  results.syntax = {};
  for (const name of ['index.html','admin.html']) {
    const body = fs.readFileSync(path.join(root,'SnapSave-FRONTEND',name),'utf8');
    let i=0;
    for(const m of body.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/g)){
      if(!m[2].trim())continue;
      let script=m[2].replace(/import[\s\S]*?from\s+"[^"]+";/g,'');
      new vm.Script(script,{filename:name+':'+(++i)});
    }
    results.syntax[name]='valid';
  }
  for(const name of ['common.js','admin_script.js','_admin_check.js']){
    new vm.Script(fs.readFileSync(path.join(root,'SnapSave-FRONTEND',name),'utf8'),{filename:name});
    results.syntax[name]='valid';
  }
  fs.writeFileSync(path.join(__dirname,'frontend-results.json'),JSON.stringify(results,null,2));
  console.log(JSON.stringify(results,null,2));
}
main().catch(e=>{console.error(e);process.exitCode=1});
