from tests.test_browser import browser, open_app


def test_created_order_refresh_failure_and_history_retry(browser,client,actors,order,db):
    page,errors=open_app(browser,client,actors['customer'],db,'index.html')
    try:
        page.locator('#chat-textarea').wait_for(state='visible')
        page.wait_for_function("document.querySelector('#active-order-container').textContent.includes('pending review')")
        page.evaluate('''()=>{window.startNewOrder();const original=window.fetch;
          window.__created=false;window.__cursors=[];window.__failHistory=true;
          window.fetch=async(url,options)=>{
            const path=String(url);
            if(path.includes('before=')){
              window.__cursors.push(new URL(path).searchParams.get('before'));
              if(window.__failHistory){window.__failHistory=false;throw Error('History offline');}
            }
            if(window.__created&&(path.includes('/api/customer/workspace')||(path.endsWith('/api/read-batch')&&String(options?.body).includes('\"active_only\":true'))))throw Error('Refresh offline');
            const response=await original(url,options);
            if(path.endsWith('/api/orders')&&options?.method==='POST')window.__created=true;
            return response;
          };}''')
        page.locator('#chat-textarea').fill('6 eggs')
        page.locator('#btn-send-chat').click()
        page.wait_for_function("document.querySelector('#customer-chat-feedback').textContent.startsWith('Sent.')")
        assert page.locator('#chat-textarea').input_value()==''
        assert page.locator('#customer-chat-feedback').get_attribute('data-error')=='false'
        page.evaluate('window.loadMoreHistory()')
        page.evaluate('window.loadMoreHistory()')
        cursors=page.evaluate('window.__cursors')
        assert len(cursors)==2 and cursors[0]==cursors[1]
        assert not errors,errors
    finally:page.close()


def test_support_poll_keeps_new_typing_and_focus(browser,client,actors,db):
    client.post('/api/help',headers=actors['customer']['headers'],json={'message':'Need help with an order'})
    page,errors=open_app(browser,client,actors['admin'],db,'admin.html')
    try:
        page.locator('.admin-nav').wait_for(state='visible')
        page.locator('.admin-nav-item[data-section="help"]').click()
        page.locator('#help-thread-list .queue-card').first.click()
        field=page.locator('#help-reply-input')
        field.fill('First draft')
        page.evaluate('''()=>{const original=window.fetch;
          window.fetch=async(url,options)=>{
            if(String(url).includes('/api/admin/help/')&&String(url).endsWith('/messages'))
              await new Promise(resolve=>window.__releaseHelp=resolve);
            const result=await original(url,options);window.__helpFetched=true;return result;
          };}''')
        page.locator('#help-thread-list .queue-card').first.click()
        page.wait_for_function('!!window.__releaseHelp')
        field.fill('New text typed during refresh')
        page.evaluate('window.__releaseHelp()')
        page.wait_for_function("window.__helpFetched")
        # Wait for the async refresh, checking the original input is still attached.
        page.wait_for_function("document.querySelector('#help-reply-input')===document.activeElement")
        assert field.input_value()=='New text typed during refresh'
        assert not errors,errors
    finally:page.close()
