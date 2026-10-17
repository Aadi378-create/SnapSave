/* Shared UI state only. Firebase continues to verify CAPTCHA and SMS codes. */
window.createPhoneLogin = function(root, adapter) {
  const find = name => root.querySelector(`[data-auth-${name}]`);
  const phoneForm=find('phone-form'), otpForm=find('otp-form');
  const phone=find('phone'), code=find('code'), send=find('send'), verify=find('verify');
  const change=find('change'), resend=find('resend'), retry=find('retry-captcha');
  const captcha=find('captcha'), hint=find('captcha-hint'), status=find('status');
  let verifier=null, confirmation=null, solved=false, busy=false, verifying=false;
  let epoch=0, rendering=null, cooldownUntil=0, sentNumber=null, timer=null;

  function number() {
    let value=phone.value.replace(/[\s()-]/g,'');
    if(value.startsWith('+91'))value=value.slice(3);
    return /^[0-9]{10}$/.test(value) ? '+91'+value : null;
  }
  function message(text='',tone='info') {
    status.textContent=text;status.dataset.tone=tone;status.hidden=!text;
    status.setAttribute('role',tone==='error'?'alert':'status');
  }
  function errorText(error, stage) {
    const messages={
      'auth/invalid-verification-code':'That code is incorrect. Check the SMS and try again.',
      'auth/code-expired':'This code has expired. Request a new code.',
      'auth/session-expired':'This code has expired. Request a new code.',
      'auth/too-many-requests':'Too many attempts. Please wait a few minutes before trying again.',
      'auth/quota-exceeded':'SMS sign-in is temporarily unavailable. Please try again later.',
      'auth/network-request-failed':'Could not connect. Check your connection and try again.',
      'auth/captcha-check-failed':'The security check expired or could not be verified. Complete it again.',
      'auth/invalid-phone-number':'Enter a valid 10-digit Indian mobile number.',
      'auth/invalid-app-credential':'The security check could not be verified. Refresh it and try again.',
      'auth/internal-error':'Sign-in could not be completed. Refresh the security check and try again.'
    };
    return messages[error?.code] || (stage==='verify'?'Could not verify the code. Please try again.':'Could not load or send verification. Check your connection and try again.');
  }
  function update() {
    const seconds=Math.max(0,Math.ceil((cooldownUntil-Date.now())/1000));
    const waiting=number()===sentNumber && seconds>0;
    phone.disabled=busy;code.disabled=busy;change.disabled=busy;retry.disabled=busy || !!rendering || !number();
    send.disabled=busy || !number() || !solved || waiting;
    verify.disabled=busy || !confirmation || !/^[0-9]{6}$/.test(code.value.trim());
    resend.disabled=busy || seconds>0;
    send.textContent=busy&&!verifying?'Sending code…':waiting?`Send again in ${seconds}s`:'Send code';
    verify.textContent=verifying?'Verifying…':'Verify & sign in';
    resend.textContent=seconds>0?`Resend in ${seconds}s`:'Resend code';
    root.setAttribute('aria-busy',String(busy));
  }
  function clearCaptcha() {
    epoch++;solved=false;
    if(verifier) {try {verifier.clear();} catch(e) {} }
    verifier=null;rendering=null;captcha.replaceChildren();
    hint.textContent='Enter your number to load the security check.';
  }
  async function prepare() {
    if(verifier || rendering || !number() || phoneForm.hidden || busy)return;
    const version=epoch;
    hint.textContent='Loading security check…';
    const task=Promise.resolve().then(()=>adapter.captcha(captcha.id,{
      size:captcha.clientWidth<304?'compact':'normal',
      callback:()=>{if(version===epoch){solved=true;hint.textContent='Security check complete.';update();}},
      'expired-callback':()=>{if(version===epoch){solved=false;hint.textContent='Security check expired. Please complete it again.';update();}},
      'error-callback':()=>{if(version===epoch){solved=false;hint.textContent='Security check could not load. Use Refresh check to retry.';update();}}
    }));
    rendering=task;update();
    try {
      const result=await task;
      if(version!==epoch){try {result.clear();} catch(e) {} return;}
      verifier=result;
      if(!solved)hint.textContent='Complete the security check before sending your code.';
    } catch(error) {
      if(version===epoch){message(errorText(error,'send'),'error');hint.textContent='Use Refresh check to try again.';}
    } finally {if(rendering===task)rendering=null;update();}
  }
  function startTimer() {
    clearInterval(timer);
    timer=setInterval(()=>{update();if(Date.now()>=cooldownUntil){clearInterval(timer);timer=null;}},1000);
  }
  async function sendCode() {
    if(busy)return;
    const destination=number();
    if(!destination){message('Enter your 10-digit mobile number.','error');phone.focus();return;}
    if(destination===sentNumber && Date.now()<cooldownUntil){message('Please wait for the resend countdown before requesting another code.');return;}
    if(!solved || !verifier){message('Complete the security check before sending your code.');await prepare();return;}
    busy=true;message();update();
    try {
      confirmation=await adapter.send(destination,verifier);
      sentNumber=destination;cooldownUntil=Date.now()+60000;startTimer();
      phoneForm.hidden=true;otpForm.hidden=false;code.value='';
      find('destination').textContent=`+91 ${destination.slice(3,8)} ${destination.slice(8)}`;
      clearCaptcha();message('Code sent. Enter the six-digit code from your SMS.','success');
      code.focus();
    } catch(error) {
      confirmation=null;clearCaptcha();message(errorText(error,'send'),'error');
    } finally {busy=false;update();if(!phoneForm.hidden)await prepare();else code.focus();}
  }
  async function verifyCode() {
    if(busy)return;
    if(!confirmation){message('Request a verification code first.','error');return;}
    if(!/^[0-9]{6}$/.test(code.value.trim())){message('Enter all six digits from your SMS.','error');code.focus();return;}
    busy=true;verifying=true;message();code.removeAttribute('aria-invalid');update();
    try {const credential=await confirmation.confirm(code.value.trim());await adapter.verified(credential);}
    catch(error){code.setAttribute('aria-invalid','true');message(errorText(error,'verify'),'error');}
    finally {busy=false;verifying=false;update();if(!otpForm.hidden)code.focus();}
  }
  function backToPhone(resending=false) {
    if(busy)return;
    confirmation=null;code.value='';code.removeAttribute('aria-invalid');
    otpForm.hidden=true;phoneForm.hidden=false;clearCaptcha();
    message(resending?'Complete the security check to request another code.':'');
    phone.focus();update();void prepare();
  }
  phoneForm.addEventListener('submit',event=>{event.preventDefault();void sendCode();});
  otpForm.addEventListener('submit',event=>{event.preventDefault();void verifyCode();});
  phone.addEventListener('input',()=>{message();update();void prepare();});
  code.addEventListener('input',()=>{code.removeAttribute('aria-invalid');update();});
  change.addEventListener('click',()=>backToPhone());
  resend.addEventListener('click',()=>{if(Date.now()>=cooldownUntil)backToPhone(true);});
  retry.addEventListener('click',()=>{if(!busy){clearCaptcha();void prepare();}});
  update();
  return {
    send:sendCode,verify:verifyCode,change:backToPhone,isVerifying:()=>verifying,
    reset(){if(busy)return;clearInterval(timer);timer=null;cooldownUntil=0;phone.value='';backToPhone();},
    message
  };
};
