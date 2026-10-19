"""Real browser control across tabs, frames, forms and changing DOM elements."""
import importlib.util
import json
from pathlib import Path
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.services import website_test as wt
from app.services.website_browser import BrowserController, PolicyBlocked, StaleTarget


@pytest.fixture
def catalog():
    state = {'queries': 0, 'cart': 0, 'options': None}
    class Site(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_GET(self):
            pages = {
                '/': '''<h1>Catalog</h1><form onsubmit="event.preventDefault();fetch('/graphql',{method:'POST',body:JSON.stringify({query:'query Products { products { name } }'})}).then(()=>document.querySelector('#results').hidden=false)"><input type=search aria-label="Search catalog"><button>Search</button></form><div id=results hidden><a href=/product target=_blank>Trail shoes</a></div>''',
                '/product': '''<h1>Trail shoes · $50</h1><label>Size<select id=size><option value=''>Choose size</option><option value=M>Medium</option><option value=L>Large</option></select></label><label><input id=laces type=checkbox>Blue laces</label><button aria-label="More details" onmouseover="document.querySelector('#menu').hidden=false">Details</button><div id=menu hidden><a href=/guide>Sizing guide</a></div><iframe title="Cart widget" src=/widget style="display:block;height:180px;width:280px"></iframe>''',
                '/widget': '''<p id=cart>Cart empty</p><button onclick="fetch('/cart/add',{method:'POST',body:JSON.stringify({size:parent.document.querySelector('#size').value,laces:parent.document.querySelector('#laces').checked})}).then(()=>document.querySelector('#cart').textContent='1 item added')">Add selected pair</button>''',
                '/guide': '''<h1>Sizing guide</h1><p>Measure heel to toe.</p><fit-note></fit-note><script>customElements.define('fit-note',class extends HTMLElement{connectedCallback(){const r=this.attachShadow({mode:'open'});r.innerHTML='<button>Reveal fit note</button><p id=fit-note hidden>Wide fit available</p>';r.querySelector('button').onclick=()=>r.querySelector('p').hidden=false;}});</script>''',
            }
            body = ('<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1"><title>Browser control fixture</title>'+pages[self.path]).encode()
            self.send_response(200)
            self.send_header('Content-Type','text/html')
            self.send_header('Content-Length',str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def do_POST(self):
            data = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            if self.path == '/graphql':
                state['queries'] += 1
            elif self.path == '/cart/add':
                state['cart'] += 1
                state['options'] = data
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{}')
    server = ThreadingHTTPServer(('127.0.0.1',0), Site)
    thread = threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    yield f'http://127.0.0.1:{server.server_port}', state
    server.shutdown()
    server.server_close()


@pytest.fixture
def browser():
    pytest.importorskip('playwright.sync_api')
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        if not Path(p.chromium.executable_path).exists():
            pytest.skip('optional Chromium binary is not installed')
        instance = p.chromium.launch()
        yield instance
        instance.close()


def test_controls_across_tabs_frames_and_navigation(browser, catalog):
    url, state = catalog
    spec = wt.normalize({'url':url,'goal':'add_to_cart'})
    context = browser.new_context(viewport={'width':390,'height':844},service_workers='block')
    page = context.new_page()
    controller = BrowserController(context,page,spec,wt.validate_action)
    try:
        page.goto(url)
        def act(kind,label=None,**values):
            obs=controller.observe()
            decision={'action':kind,'observation_id':obs['observation_id'],**values}
            if label:
                decision['target']=next(c['id'] for c in obs['controls'] if c['label']==label)
            return controller.act(decision)
        act('fill','Search catalog',value='trail shoes')
        filled=controller.observe()
        assert next(c for c in filled['controls'] if c['label']=='Search catalog')['has_value']
        act('press','Search catalog',key='Enter')
        assert state['queries']==1
        act('click','Trail shoes')
        obs=controller.observe()
        assert len(obs['tabs'])==2
        product_tab=next(t['id'] for t in obs['tabs'] if t['url'].endswith('/product'))
        controller.act({'action':'switch_tab','tab_id':product_tab})
        act('select','Size',value='Medium')
        act('check','Blue laces',checked=True)
        act('hover','More details')
        obs=controller.observe()
        widget=next(c for c in obs['controls'] if c['label']=='Add selected pair')
        assert widget['frame']!='frame0'
        outcome=controller.act({'action':'click','target':widget['id']})
        assert outcome['frame']!='frame0'
        assert state['cart']==1 and state['options']=={'size':'M','laces':True}
        checked=wt.check_outcomes(controller.page,[{'name':'cart','selector':'#cart','text':'1 item'}],controller.frames())
        assert checked['cart']['passed']
        assert checked['cart']['matches'][0]['document_url'].endswith('/widget')
        act('click','Sizing guide')
        assert controller.page.url.endswith('/guide')
        act('back')
        assert controller.page.url.endswith('/product')
        act('forward')
        act('reload')
        assert controller.page.url.endswith('/guide')
        act('click','Reveal fit note')
        assert wt.check_outcomes(controller.page,[{'name':'fit','selector':'#fit-note','text':'Wide fit'}])['fit']['passed']
        act('close_tab')
        assert controller.page==page
        act('scroll',direction='down',amount=200)
        act('scroll',direction='up',amount=200)
        obs=controller.observe()
        with pytest.raises(PolicyBlocked):
            controller.act({'action':'navigate','url':url+'/unseen-admin'})
        controller.observe()
        controller.act({'action':'navigate','url':url})
    finally:
        controller.close()
        context.close()


def test_stale_reference_never_clicks_replacement(browser, catalog):
    url,state=catalog
    context=browser.new_context()
    page=context.new_page()
    page.goto(url+'/widget')
    spec=wt.normalize({'url':url,'goal':'add_to_cart'})
    controller=BrowserController(context,page,spec,wt.validate_action)
    obs=controller.observe()
    target=next(c for c in obs['controls'] if c['tag']=='button')
    page.locator('button').evaluate("e=>{const replacement=document.createElement('button');replacement.textContent='Place order';e.replaceWith(replacement)}")
    with pytest.raises(StaleTarget):
        controller.act({'action':'click','target':target['id']})
    assert state['cart']==0
    with pytest.raises(StaleTarget,match='Observe'):
        controller.act({'action':'click','target':target['id']})
    fresh=controller.observe()
    with pytest.raises(PolicyBlocked):
        controller.act({'action':'click','target':fresh['controls'][0]['id']})
    controller.close()
    context.close()


def test_timeout_after_cart_write_checks_state_before_any_retry(catalog, tmp_path, monkeypatch):
    pytest.importorskip('playwright.sync_api')
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        if not Path(p.chromium.executable_path).exists():
            pytest.skip('optional Chromium binary is not installed')
    url,state=catalog
    monkeypatch.setenv('MARKET_MIRROR_ALLOW_LOCAL_WEBSITE_TESTS','1')
    original=BrowserController.act
    def timeout_after_write(self,action):
        result=original(self,action)
        if action['action']=='click':
            raise TimeoutError('navigation timed out after the cart write')
        return result
    monkeypatch.setattr(BrowserController,'act',timeout_after_write)
    def choose(*args):
        obs=args[4]
        return ({'action':'click','target':next(c['id'] for c in obs['controls'] if c['tag']=='button')},
                {'input_tokens':1,'output_tokens':1})
    monkeypatch.setattr(wt,'choose',choose)
    # The top-level widget's handler uses parent DOM; replace it with a standalone
    # fixture cart write while retaining the actual browser and HTTP mutation.
    original_observe=BrowserController.observe
    def observe(self):
        if self.sequence==0:
            self.page.locator('button').evaluate("e=>e.onclick=()=>fetch('/cart/add',{method:'POST',body:'{}'}).then(()=>document.querySelector('#cart').textContent='1 item added')")
        return original_observe(self)
    monkeypatch.setattr(BrowserController,'observe',observe)
    result=wt.run(None,'fixture',[{'agent_id':1}],{'url':url+'/widget','goal':'add_to_cart','max_personas':1,
        'checks':[{'name':'cart','selector':'#cart','text':'1 item'}],'goal_check':'cart'},tmp_path)
    assert result['summary']['goal_observed']==1
    assert result['summary']['model_calls']==1
    assert result['summary']['recoveries']==1
    assert state['cart']==1
    assert result['sessions'][0]['steps'][0]['outcome']['action_may_have_executed']


def test_opt_in_video_and_trace_are_saved(catalog, tmp_path, monkeypatch):
    pytest.importorskip('playwright.sync_api')
    from playwright.sync_api import sync_playwright
    from zipfile import ZipFile
    with sync_playwright() as p:
        if not Path(p.chromium.executable_path).exists():
            pytest.skip('optional Chromium binary is not installed')
    monkeypatch.setenv('MARKET_MIRROR_ALLOW_LOCAL_WEBSITE_TESTS','1')
    result=wt.run(None,'fixture',[{'agent_id':1}],{'url':catalog[0], 'max_personas':1,
        'record_video':True,'record_trace':True,
        'checks':[{'name':'catalog','selector':'h1','text':'Catalog'}],'goal_check':'catalog'},tmp_path)
    artifacts=result['sessions'][0]['artifacts']
    assert Path(artifacts['videos'][0]['file']).stat().st_size>0
    with ZipFile(artifacts['trace']) as trace:
        assert any(name.endswith('.trace') for name in trace.namelist())
    assert result['summary']['already_satisfied']==1
    assert result['summary']['model_calls']==0


def test_keyboard_and_option_validation_preserve_boundaries():
    spec=wt.normalize({'url':'https://example.com'})
    email={'id':'e0','tag':'input','type':'email','label':'Email','form_fields':['email','password']}
    with pytest.raises(PolicyBlocked):
        wt.validate_action({'action':'press','target':'e0','key':'Enter'},{'controls':[email]},spec)
    with pytest.raises(ValueError,match='keyboard'):
        wt.validate_action({'action':'press','target':'e0','key':'Control+L'},{'controls':[email]},spec)
    select={'id':'e1','tag':'select','label':'Size','options':[{'value':'M','label':'Medium','disabled':False}]}
    assert wt.validate_action({'action':'select','target':'e1','value':'Medium'},{'controls':[select]},spec)==select
    with pytest.raises(ValueError,match='option'):
        wt.validate_action({'action':'select','target':'e1','value':'unseen'},{'controls':[select]},spec)
    search={'id':'e2','tag':'input','type':'search','label':'Search'}
    with pytest.raises(ValueError,match='explicit value'):
        wt.validate_action({'action':'fill','target':'e2'},{'controls':[search]},spec)
