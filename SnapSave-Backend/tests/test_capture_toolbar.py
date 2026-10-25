"""Toolbar packaging, permission boundaries and the real capture/import interface."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
from zipfile import ZipFile
import pytest
from tests.test_browser import browser
from core.catalog_research import BrowserCaptureClient,extract_products

ROOT=Path(__file__).resolve().parents[2]
EXT=ROOT/'SnapSave-Backend/tools/retailer-capture-extension'
OBSERVED=ROOT/'audit/2026-10-25/retailer-browser-resolution/live-captures.json'


def build(target):
    spec=importlib.util.spec_from_file_location('capture_build',EXT/'build.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module.build(target)


def test_toolbar_build_has_only_temporary_access_and_shares_exporter(tmp_path):
    target=build(tmp_path/'extension')
    manifest=json.loads((target/'manifest.json').read_text())
    assert manifest['permissions']==['activeTab','scripting']
    assert not {'host_permissions','content_scripts','externally_connectable','update_url'} & manifest.keys()
    with ZipFile(target/'snapsave-retailer-capture.zip') as archive:
        assert set(archive.namelist())=={'manifest.json','background.js','capture.js'}
    assert 'No supported rendered product markup found' in (target/'capture.js').read_text()
    (target/'unexpected.env').write_text('not a real secret')
    with pytest.raises(ValueError):build(target)


def test_toolbar_dispatch_validates_page_and_reports_failures(tmp_path):
    # The worker itself is exercised with browser APIs mocked, without installing
    # an extension or granting the test runner access to the user's browser.
    module=EXT.joinpath('background.js').read_text(encoding='utf-8')
    assertions='''
    import assert from 'node:assert/strict';
    for(const url of ['https://blinkit.com/cn/milk/cid/14/922','https://www.zepto.com/category/milk',
        'https://www.swiggy.com/instamart/','https://www.bigbasket.com/pd/1/milk/'])assert.ok(supportedPage(url));
    for(const url of ['https://blinkit.com/account','https://www.zepto.com/api/products',
        'http://blinkit.com/cn/milk','https://blinkit.com.evil.test/cn/milk',
        'https://user:pass@blinkit.com/cn/milk','https://blinkit.com:999/cn/milk'])assert.ok(!supportedPage(url));
    const calls=[];
    const api={action:{setTitle:async x=>calls.push(x),setBadgeText:async x=>calls.push(x)},
        scripting:{executeScript:async x=>{calls.push(x);return [{result:{ok:true}}];}}};
    assert.equal(await captureTab({id:1,url:'https://blinkit.com/account'},api),false);
    assert.ok(!calls.some(x=>x.target));
    assert.equal(await captureTab({id:1,url:'https://blinkit.com/cn/milk'},api),true);
    assert.deepEqual(calls.find(x=>x.target),{target:{tabId:1},files:['capture.js'],world:'ISOLATED'});
    assert.equal(calls.at(-2).text,'OK');
    api.scripting.executeScript=async()=>[{result:{ok:false,error:'HTTP 202'}}];
    assert.equal(await captureTab({id:1,url:'https://blinkit.com/cn/milk'},api),false);
    assert.equal(calls.at(-2).text,'!');
    assert.ok(calls.at(-1).title.includes('HTTP 202'));
    let release,requests=0;
    api.scripting.executeScript=async()=>{requests++;await new Promise(r=>release=r);return [{result:{ok:true}}];};
    const first=captureTab({id:2,url:'https://blinkit.com/cn/milk'},api);
    await new Promise(r=>setTimeout(r,0));
    assert.equal(await captureTab({id:2,url:'https://blinkit.com/cn/milk'},api),false);
    release();assert.equal(await first,true);assert.equal(requests,1);
    '''
    script=tmp_path/'worker-test.mjs';script.write_text(module+assertions,encoding='utf-8')
    result=subprocess.run([shutil.which('node'),str(script)],capture_output=True,text=True,timeout=20)
    assert result.returncode==0,result.stderr


@pytest.mark.parametrize('store,price',[('zepto',77),('instamart',150),('blinkit',77)])
def test_packaged_exporter_downloads_importable_evidence(browser,tmp_path,store,price):
    entry=next(row for row in json.loads(OBSERVED.read_text(encoding='utf-8')) if row['store']==store)
    target=build(tmp_path/'extension')
    page=browser.new_page()
    context={'order_id':'test-order','revision':1,'postal_code':'382421'}
    page.on('dialog',lambda dialog:dialog.accept(json.dumps(context)) if dialog.type=='prompt' else dialog.accept())
    try:
        page.route('**/*',lambda route:route.fulfill(status=200,content_type='text/plain; charset=utf-8' if route.request.url.endswith('/robots.txt') else 'text/html; charset=utf-8',body=entry['robots'] if route.request.url.endswith('/robots.txt') else entry['html']))
        page.goto(entry['url'])
        with page.expect_download() as pending:
            assert page.evaluate((target/'capture.js').read_text(encoding='utf-8'))=={'ok':True}
        saved=tmp_path/'capture.json';pending.value.save_as(str(saved))
        captures=json.loads(saved.read_text(encoding='utf-8'))
        client=BrowserCaptureClient(captures)
        products=extract_products(*client.fetch(entry['url'],store),store)
        assert products[0]['price']==price
        assert captures[0]['research_context']==context
        assert captures[0]['location_context']['attested_postal_code']=='382421'
    finally:page.close()


@pytest.mark.parametrize('status',[202,403])
def test_capture_stops_on_challenge_policy_status(browser,tmp_path,status):
    target=build(tmp_path/'extension');page=browser.new_page();dialogs=[]
    def handle(dialog):
        if dialog.type=='prompt':dialog.accept('')
        else:dialogs.append(dialog.message);dialog.dismiss()
    page.on('dialog',handle)
    try:
        page.route('**/*',lambda route:route.fulfill(status=status if route.request.url.endswith('/robots.txt') else 200,body='User-agent: *\nAllow: /'))
        page.goto('https://www.zepto.com/category/milk')
        result=page.evaluate((target/'capture.js').read_text(encoding='utf-8'))
        assert result['ok'] is False and f'HTTP {status}' in result['error']
        assert len(dialogs)==1
    finally:page.close()
