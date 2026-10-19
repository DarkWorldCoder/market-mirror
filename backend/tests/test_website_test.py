"""Browser policy, outcome integrity and real Chromium journeys on an owned fixture."""
import importlib.util
import json
from pathlib import Path
import socket
import threading
from types import SimpleNamespace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.services import website_test as wt


def test_spec_requires_explicit_signup_data_and_checks():
    with pytest.raises(ValueError, match="complete_signup"):
        wt.normalize({"url": "https://example.com", "goal": "complete_signup"})
    with pytest.raises(ValueError, match="test email"):
        wt.normalize({"url": "https://example.com", "allow_signup_submit": True})
    with pytest.raises(ValueError, match="unique"):
        wt.normalize({"url": "https://example.com", "goal": "complete_signup", "allow_signup_submit": True,
                      "test_data": {"email": "test@example.com"}, "goal_check": "welcome",
                      "checks": [{"name": "welcome", "selector": "h1"}]})
    with pytest.raises(ValueError, match="goal_check"):
        wt.normalize({"url": "https://example.com", "goal_check": "missing"})
    with pytest.raises(ValueError, match="unique"):
        wt.normalize({"url": "https://example.com", "checks": [{"name": "a", "selector": "h1"}, {"name": "a", "selector": "h2"}]})


def test_network_policy_blocks_private_redirects_and_unapproved_writes(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 443))])
    spec = wt.normalize({"url": "https://shop.example", "goal": "add_to_cart"})
    assert wt.request_allowed("https://shop.example/cart/add", "POST", "{}", spec)
    assert not wt.request_allowed("https://shop.example/orders", "POST", '{"cart":1}', spec)
    assert not wt.request_allowed("https://shop.example/cart/checkout", "POST", '{}', spec)
    assert not wt.request_allowed("https://shop.example/graphql", "POST", '{"operationName":"orderCreate","cart":1}', spec)
    assert not wt.request_allowed("https://shop.example/register", "POST", "{}", spec)
    assert not wt.request_allowed("https://shop.example/contact", "POST", '{"message":"help with my cart"}', spec)
    assert wt.request_allowed("https://shop.example/graphql", "POST", '{"query":"query Products { products { name } }"}', spec)
    assert wt.request_allowed("https://shop.example/graphql", "POST", '{"query":"mutation Add { cartLinesAdd(cartId:1) { cart { id } } }"}', spec)
    assert not wt.request_allowed("https://elsewhere.example/cart", "POST", "{}", spec)
    assert not wt.request_allowed("https://elsewhere.example/page", "GET", None, spec, navigation=True)
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('169.254.169.254', 80))])
    with pytest.raises(ValueError, match="private"):
        wt.validate_url("http://metadata.example")
    with pytest.raises(ValueError):
        wt.validate_url("file:///etc/passwd")


def test_action_policy_does_not_allow_payments_or_invented_identity():
    spec = wt.normalize({"url": "https://example.com"})
    for control, action in [
        ({"id": "e0", "tag": "button", "label": "Place order"}, {"action": "click", "target": "e0"}),
        ({"id": "e0", "tag": "input", "label": "Email", "type": "email"}, {"action": "fill", "target": "e0", "value": "invented@example.com"}),
        ({"id": "e0", "tag": "button", "label": "Create account", "type": "submit", "form_fields": ["email"]}, {"action": "click", "target": "e0"})]:
        with pytest.raises(ValueError):
            wt.validate_action(action, {"controls": [control]}, spec)


@pytest.fixture
def shop():
    state = {"cart_writes": 0, "signups": 0, "orders": 0}
    class Shop(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_GET(self):
            if self.path == '/signup':
                page = '''<h1>Create an account</h1><form onsubmit="event.preventDefault();fetch('/register',{method:'POST',body:'test'}).then(()=>{document.body.innerHTML='<h1 data-testid=welcome>Account created</h1>'})"><label>Email<input type=email></label><label>Password<input type=password></label><button type=submit>Create account</button></form>'''
            else:
                page = '''<h1>Fixture running shoes · $50</h1><p>Lightweight everyday shoes.</p><button onclick="fetch('/cart/add',{method:'POST',body:'test'}).then(()=>{document.querySelector('#cart').textContent='1 item in cart'})">Add to cart</button><p id=cart data-testid=cart-count>Empty cart</p><a href=/signup>Sign up</a><button onclick="fetch('/orders',{method:'POST'})">Place order</button>'''
            encoded = ('<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1"><title>Owned shop fixture</title>' + page).encode()
            self.send_response(200)
            self.send_header('Content-Type','text/html; charset=utf-8')
            self.send_header('Content-Length',str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)
        def do_POST(self):
            self.rfile.read(int(self.headers.get('Content-Length', '0')))
            state[{'/cart/add': 'cart_writes', '/register': 'signups', '/orders': 'orders'}[self.path]] += 1
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{}')
    server = ThreadingHTTPServer(('127.0.0.1',0), Shop)
    thread = threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    yield f'http://127.0.0.1:{server.server_port}', state
    server.shutdown()
    server.server_close()


browser_available = importlib.util.find_spec('playwright') is not None


@pytest.mark.skipif(not browser_available, reason="optional browser extra is not installed")
def test_real_browser_cart_abandonment_signup_and_failure(shop, tmp_path, monkeypatch):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        if not Path(p.chromium.executable_path).exists():
            pytest.skip('Chromium binary is not installed')
    url, state = shop
    monkeypatch.setenv('MARKET_MIRROR_ALLOW_LOCAL_WEBSITE_TESTS','1')
    def choose(_client, _model, person, spec, obs, history):
        if person['name'] == 'Declines':
            action = {'action':'leave','reason':'Over my budget.'}
        elif person['name'] == 'Provider fails':
            raise RuntimeError('model unavailable')
        elif spec['goal'] == 'complete_signup':
            field = ('email','password')[len(history)] if len(history) < 2 else None
            control = next(c for c in obs['controls'] if (c.get('type') == field if field else c['tag']=='button'))
            action = {'action':'fill' if field else 'click','target':control['id'],'test_data_key':field,'reason':'Continue signup with the supplied test identity.'}
        else:
            control = next(c for c in obs['controls'] if c['label']=='Add to cart')
            action = {'action':'click','target':control['id'],'reason':'The price fits my budget.'}
        return action, {'input_tokens':10,'output_tokens':5}
    monkeypatch.setattr(wt,'choose',choose)
    cart = wt.run(None,'fixture',[{'agent_id':1,'name':'Buyer'},{'agent_id':2,'name':'Declines'},{'agent_id':3,'name':'Provider fails'}],
        {'url':url,'goal':'add_to_cart','checks':[{'name':'cart_added','selector':'#cart','text':'1 item'}], 'goal_check':'cart_added'},tmp_path/'cart')
    assert cart['summary']['goal_observed'] == 1
    assert cart['summary']['left'] == 1
    assert cart['summary']['execution_failed'] == 1
    assert cart['milestones']['cart_added'] == 1
    assert state == {'cart_writes':1,'signups':0,'orders':0}
    assert 'data:image/jpeg;base64,' in Path(cart['files']['dashboard']).read_text()
    signup = wt.run(None,'fixture',[{'agent_id':1,'name':'Buyer'}],
        {'url':url+'/signup','goal':'complete_signup','allow_signup_submit':True,'max_personas':1,
         'test_data':{'email':'test@example.com','password':'fixture-only-secret'},
         'checks':[{'name':'welcome','selector':'[data-testid=welcome]','text':'Account created'}],'goal_check':'welcome'},tmp_path/'signup')
    assert signup['summary']['goal_observed'] == 1
    assert state['signups'] == 1 and state['orders'] == 0
    assert 'fixture-only-secret' not in Path(signup['files']['result']).read_text()
    assert 'test@example.com' not in Path(signup['files']['result']).read_text()


@pytest.mark.skipif(not browser_available, reason="optional browser extra is not installed")
def test_agent_claim_is_not_verified_goal(shop, tmp_path, monkeypatch):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        if not Path(p.chromium.executable_path).exists():
            pytest.skip('Chromium binary is not installed')
    monkeypatch.setenv('MARKET_MIRROR_ALLOW_LOCAL_WEBSITE_TESTS','1')
    monkeypatch.setattr(wt,'choose',lambda *a: ({'action':'finish','reason':'I think I did it.'},{'input_tokens':1,'output_tokens':1}))
    result = wt.run(None,'fixture',[{'agent_id':1}],{'url':shop[0],'goal':'add_to_cart','max_personas':1},tmp_path)
    assert result['summary']['completed_unverified'] == 1
    assert result['summary']['goal_observed'] == 0
    assert not result['sessions'][0]['goal_verified']


def test_api_start_and_specific_result_paths(tmp_path, monkeypatch):
    from app import create_app
    from app.api import market
    monkeypatch.setattr(market,'_sim_dir',lambda sid: str(tmp_path))
    monkeypatch.setattr(market,'_people',lambda sid: ([{'agent_id':1}],{}))
    seen = []
    monkeypatch.setattr(market,'_start',lambda kind,sid,work: seen.append((kind,sid)) or 'task_x')
    client = create_app().test_client()
    response = client.post('/api/simulation/website-test',json={'simulation_id':'sim_x','spec':{'url':'https://example.com'}})
    assert response.status_code == 200
    run_id = response.get_json()['data']['run_id']
    assert seen == [('website-test','sim_x')]
    folder = tmp_path/run_id
    folder.mkdir()
    (folder/'website_test.json').write_text('{"status":"completed"}')
    assert client.get(f'/api/simulation/sim_x/website-test?run_id={run_id}').get_json()['data']['status'] == 'completed'
    assert client.get('/api/simulation/sim_x/website-test?run_id=../../escape').status_code == 400
    assert client.post('/api/simulation/website-test',json={'simulation_id':'sim_x','spec':{'url':'file:///etc/passwd'}}).status_code == 400
    assert client.post('/api/simulation/website-test',json=['invalid']).status_code == 400


@pytest.mark.skipif(not browser_available, reason="optional browser extra is not installed")
@pytest.mark.parametrize('mode', ['compact', 'full'])
def test_model_view_preserves_verified_cart_and_shared_call_budget(shop, tmp_path, monkeypatch, mode):
    monkeypatch.setenv('MARKET_MIRROR_ALLOW_LOCAL_WEBSITE_TESTS', '1')
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        if not Path(p.chromium.executable_path).exists():
            pytest.skip('Chromium binary is not installed')
    requests = []
    def create(*args, **kwargs):
        payload = json.loads(kwargs['messages'][1]['content'])
        requests.append(payload)
        obs = payload['observation']
        control = next(c for c in obs['controls'] if c['label'] == 'Add to cart')
        action = {'action': 'click', 'target': control['id'], 'observation_id': obs['observation_id']}
        return SimpleNamespace(model='fixture', usage=SimpleNamespace(prompt_tokens=20, completion_tokens=5),
            usage_source='provider', usage_breakdown={'uncached_input_tokens': 10, 'cache_read_input_tokens': 8, 'cache_creation_input_tokens': 2},
            cost_usd=.002, cost_basis='cli_reported_list_cost',
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(action)))])
    monkeypatch.setattr(wt, 'create_chat_completion', create)
    result = wt.run(None, 'fixture', [{'agent_id': 1}, {'agent_id': 2}],
        {'url': shop[0], 'goal': 'add_to_cart', 'observation_mode': mode, 'max_model_calls': 1,
         'checks': [{'name': 'cart', 'selector': '#cart', 'text': '1 item'}], 'goal_check': 'cart'}, tmp_path)
    assert result['status'] == 'stopped'
    assert result['summary']['goal_observed'] == 1 and result['summary']['started_visitors'] == 1
    assert result['summary']['budget_exhausted'] == 1 and result['summary']['left'] == 0
    assert result['sessions'][1]['started'] is False
    assert shop[1]['cart_writes'] == 1 and len(requests) == 1
    assert result['efficiency']['usage']['cost_usd'] == .002
    assert result['efficiency']['usage']['uncached_input_tokens'] == 10
    assert 'rect' in result['sessions'][0]['steps'][0]['controls'][0]
    assert ('rect' in requests[0]['observation']['controls'][0]) == (mode == 'full')
    report = Path(result['files']['dashboard']).read_text()
    assert 'CLI list cost is not an invoice' in report and 'These are not buyer departures' in report


@pytest.mark.skipif(not browser_available, reason="optional browser extra is not installed")
def test_browser_loop_is_separate_from_buyer_departure_and_does_not_write(shop, tmp_path, monkeypatch):
    monkeypatch.setenv('MARKET_MIRROR_ALLOW_LOCAL_WEBSITE_TESTS', '1')
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        if not Path(p.chromium.executable_path).exists():
            pytest.skip('Chromium binary is not installed')
    def choose(client, model, person, spec, obs, history):
        control = next(c for c in obs['controls'] if c['label'] == 'Add to cart')
        return {'action': 'focus', 'target': control['id']}, {'input_tokens': 10, 'output_tokens': 5}
    monkeypatch.setattr(wt, 'choose', choose)
    result = wt.run(None, 'fixture', [{'agent_id': 1}], {'url': shop[0], 'loop_limit': 3}, tmp_path)
    assert result['summary']['loop_detected'] == 1 and result['summary']['left'] == 0
    assert result['summary']['model_calls'] == 3 and shop[1]['cart_writes'] == 0
    assert result['sessions'][0]['steps'][-1].get('outcome') is None


@pytest.mark.skipif(not browser_available, reason="optional browser extra is not installed")
@pytest.mark.parametrize('input_tokens,reason', [(60, 'max_input_tokens'), (None, 'input_usage_unavailable')])
def test_token_threshold_or_unknown_usage_prevents_more_calls(shop, tmp_path, monkeypatch, input_tokens, reason):
    monkeypatch.setenv('MARKET_MIRROR_ALLOW_LOCAL_WEBSITE_TESTS', '1')
    def choose(client, model, person, spec, obs, history):
        control = next(c for c in obs['controls'] if c['label'] == 'Add to cart')
        return {'action': 'focus', 'target': control['id']}, {'input_tokens': input_tokens, 'output_tokens': 5}
    monkeypatch.setattr(wt, 'choose', choose)
    result = wt.run(None, 'fixture', [{'agent_id': 1}, {'agent_id': 2}],
        {'url': shop[0], 'max_input_tokens': 50}, tmp_path)
    assert result['summary']['model_calls'] == 1 and result['summary']['budget_exhausted'] == 2
    assert result['efficiency']['budget_stop_reason'] == reason
    assert result['sessions'][1]['started'] is False and shop[1]['cart_writes'] == 0


@pytest.mark.skipif(not browser_available, reason="optional browser extra is not installed")
def test_elapsed_limit_after_model_call_prevents_late_cart_action(shop, tmp_path, monkeypatch):
    from app.services import website_efficiency as efficiency
    clock = [0]
    monkeypatch.setattr(efficiency, 'time', SimpleNamespace(monotonic=lambda: clock[0]))
    monkeypatch.setenv('MARKET_MIRROR_ALLOW_LOCAL_WEBSITE_TESTS', '1')
    def choose(client, model, person, spec, obs, history):
        clock[0] = 11
        control = next(c for c in obs['controls'] if c['label'] == 'Add to cart')
        return {'action': 'click', 'target': control['id']}, {'input_tokens': 10, 'output_tokens': 5}
    monkeypatch.setattr(wt, 'choose', choose)
    result = wt.run(None, 'fixture', [{'agent_id': 1}],
        {'url': shop[0], 'goal': 'add_to_cart', 'max_elapsed_s': 10}, tmp_path)
    assert result['summary']['budget_exhausted'] == 1
    assert result['efficiency']['budget_stop_reason'] == 'max_elapsed_s'
    assert result['summary']['model_calls'] == 1 and shop[1]['cart_writes'] == 0
