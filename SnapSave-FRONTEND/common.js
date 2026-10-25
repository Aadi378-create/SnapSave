function escapeHTML(value) {
  return String(value ?? "").replace(/[&<>"']/g, ch => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[ch]);
}
function utcDate(value) { return new Date(value && !/(Z|[+-]\d{2}:\d{2})$/.test(value) ? value+"Z" : value); }
function singleFlightPolling(callback, interval) {
  let stopped=false, timer=null, failures=0;
  const run=async()=>{
    if(stopped) return;
    try { if(!document.hidden) { await callback(); failures=0; } }
    catch(e) { failures=Math.min(failures+1,3); }
    if(!stopped) timer=setTimeout(run,interval*Math.pow(2,failures));
  };
  timer=setTimeout(run,interval);
  return ()=>{stopped=true; clearTimeout(timer);};
}
function showAlert(containerId, msg, type="error") {
  const element=document.getElementById(containerId);
  if(element) element.textContent=msg;
}
function createSessionScope() {
  let version=0, controller=new AbortController();
  return {
    get version(){return version;}, get signal(){return controller.signal;},
    current(value){return value===version;},
    assert(value){if(value!==version)throw new DOMException('Session changed','AbortError');},
    reset(){version++;controller.abort();controller=new AbortController();}
  };
}
function boundedAuth(promise) {
  let timer;
  return Promise.race([promise,new Promise((_,reject)=>{timer=setTimeout(()=>reject(new Error('Authentication connection timed out')),15000);})]).finally(()=>clearTimeout(timer));
}
function showAuthUnavailable(root) {
  if(root.querySelector('[data-auth-retry]'))return;
  const panel=document.createElement('div');panel.setAttribute('role','alert');
  const text=document.createElement('p');text.textContent='Unable to connect to secure sign-in. Check your connection and retry.';
  const retry=document.createElement('button');retry.type='button';retry.dataset.authRetry='true';retry.className='btn btn-primary';retry.textContent='Retry sign-in';retry.onclick=()=>location.reload();panel.append(text,retry);root.append(panel);
}
window.SnapSaveAuth = {
  auth:null, api:null, confirmation:null, initializing:null, ready:false,
  async initialize() {
    if(this.ready)return;
    if(!this.initializing)this.initializing=(async()=>{
      const [apps,api]=await boundedAuth(Promise.all([import("https://www.gstatic.com/firebasejs/10.12.2/firebase-app.js"), import("https://www.gstatic.com/firebasejs/10.12.2/firebase-auth.js")]));
      const app=apps.getApps()[0] || apps.initializeApp({apiKey:"AIzaSyC2usgMofYuKhLrmERkuYgFY0WmNkfMXIY",authDomain:"snapsave-501c7.firebaseapp.com",projectId:"snapsave-501c7",appId:"1:20754709166:web:22949551e251e0e9078b3f"});
      this.api=api;this.auth=api.getAuth(app);
      await boundedAuth(this.auth.authStateReady());this.ready=true;
    })().catch(error=>{this.initializing=null;throw error;});
    await this.initializing;
  },
  async token() { await this.initialize(); return this.auth.currentUser ? boundedAuth(this.auth.currentUser.getIdToken()) : null; },
  async createVerifier(container,options) {
    await this.initialize();
    const verifier=new this.api.RecaptchaVerifier(this.auth,container,options);
    try {await verifier.render();return verifier;}
    catch(error){try {verifier.clear();} catch(e) {} throw error;}
  },
  async send(phone,verifier) {
    await this.initialize();
    this.confirmation=await this.api.signInWithPhoneNumber(this.auth,phone,verifier);
    return this.confirmation;
  },
  async verify(code) { const result=await this.confirmation.confirm(code); return result.user.getIdToken(); },
  async logout() { if(this.auth) await this.api.signOut(this.auth); }
};

// Reuse ICU formatting instead of constructing a formatter per chat bubble.
const conversationClock = new Intl.DateTimeFormat(undefined,{hour:"2-digit",minute:"2-digit"});
function formatConversationTime(value) { const date=utcDate(value);return Number.isNaN(date.getTime()) ? "" : conversationClock.format(date); }

// Coalesce simultaneous, explicitly allowlisted GETs; never cache identity or response data.
const batchedReadPaths=new Set(['/api/addresses','/api/orders','/api/moderator/queue','/api/admin/dashboard/metrics','/api/admin/settings/orders','/api/admin/settings/maintenance','/api/admin/delivery-config','/api/admin/settings/ai-status','/api/admin/moderators','/api/admin/customers','/api/admin/help/summary']);
let pendingReads=[],readFlush=null;
function readFetch(base,endpoint,options) {
  const url=new URL(endpoint,base),path=url.pathname;
  if(!batchedReadPaths.has(path)&&!/^\/api\/chat\/[A-Za-z0-9_-]{1,128}\/messages$/.test(path)&&!/^\/api\/orders\/[A-Za-z0-9_-]{1,36}$/.test(path))return fetch(base+endpoint,options);
  return new Promise((resolve,reject)=>{
    if(options.signal?.aborted){reject(options.signal.reason);return;}
    const entry={base,endpoint,options,resolve,reject};pendingReads.push(entry);
    if(readFlush===null)readFlush=setTimeout(flushReads,0);
  });
}
async function flushReads() {
  const reads=pendingReads;pendingReads=[];readFlush=null;
  const groups=new Map();
  for(const entry of reads) {
    if(entry.options.signal?.aborted){entry.reject(entry.options.signal.reason);continue;}
    const config=/^\/api\/admin\/(settings\/|delivery-config|moderators|customers)/.test(new URL(entry.endpoint,entry.base).pathname);
    const key=entry.base+'|'+(entry.options.headers.Authorization||'')+'|'+(config?'configuration':'workspace');
    if(!groups.has(key))groups.set(key,[]);groups.get(key).push(entry);
  }
  await Promise.all([...groups.values()].flatMap(group=>Array.from({length:Math.ceil(group.length/8)},(_,index)=>sendReadGroup(group.slice(index*8,index*8+8)))));
}
async function sendReadGroup(group) {
  if(group.length===1){const e=group[0];try{e.resolve(await fetch(e.base+e.endpoint,e.options));}catch(error){e.reject(error);}return;}
  try {
    const reads=group.map(entry=>{
      const url=new URL(entry.endpoint,entry.base),options={};
      for(const [key,value] of url.searchParams)options[key]=['limit','offset'].includes(key)?Number(value):['summary_only','active_only'].includes(key)?value==='true':value;
      return {path:url.pathname,options};
    });
    const response=await fetch(group[0].base+'/api/read-batch',{method:'POST',headers:group[0].options.headers,body:JSON.stringify({reads}),signal:AbortSignal.timeout(20000)});
    if(!response.ok){const body=await response.text();group.forEach(entry=>entry.resolve(new Response(body,{status:response.status,headers:{'Content-Type':'application/json'}})));return;}
    const payload=await response.json();
    if(!Array.isArray(payload.results)||payload.results.length!==group.length)throw new Error('Invalid read batch response');
    group.forEach((entry,index)=>{
      if(entry.options.signal?.aborted){entry.reject(entry.options.signal.reason);return;}
      const result=payload.results[index];entry.resolve(new Response(JSON.stringify(result.data),{status:result.status,headers:{'Content-Type':'application/json'}}));
    });
  }catch(error){group.forEach(entry=>entry.reject(error));}
}
