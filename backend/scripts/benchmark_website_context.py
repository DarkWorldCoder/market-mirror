"""Compare model payloads on an owned Chromium fixture; no external inference.

Requires the browser extra, Chromium, and pytest for the shared test fixture.
Run from the checkout: backend/.venv/bin/python backend/scripts/benchmark_website_context.py
Writes ignored journey evidence and benchmarks/browser_context_fixture.json.
"""
import json, os, sys
from pathlib import Path
from types import SimpleNamespace
root = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(root/'backend'), str(root/'backend/tests')]
from app.services import website_test as wt
from test_website_browser import catalog
os.environ['MARKET_MIRROR_ALLOW_LOCAL_WEBSITE_TESTS'] = '1'
fixture = catalog.__wrapped__()
url, state = next(fixture)
measurements = []
def create(client, **kwargs):
    payload = json.loads(kwargs['messages'][1]['content'])
    obs, history = payload['observation'], payload['previous_steps']
    # Deterministic acceptance policy; no external model or invented usage.
    if obs['url'].endswith('/product'):
        size = next(c for c in obs['controls'] if c['label'] == 'Size')
        laces = next(c for c in obs['controls'] if c['label'] == 'Blue laces')
        if not any(o.get('selected') and o['value'] == 'M' for o in size['options']):
            action = {'action':'select','target':size['id'],'value':'Medium'}
        elif not laces['checked']:
            action = {'action':'check','target':laces['id'],'checked':True}
        else:
            action = {'action':'click','target':next(c['id'] for c in obs['controls'] if c['label']=='Add selected pair')}
    elif len(obs['tabs']) == 2:
        action = {'action':'switch_tab','tab_id':next(t['id'] for t in obs['tabs'] if t['url'].endswith('/product'))}
    elif any(c['label']=='Trail shoes' for c in obs['controls']):
        action = {'action':'click','target':next(c['id'] for c in obs['controls'] if c['label']=='Trail shoes')}
    else:
        search = next(c for c in obs['controls'] if c['type']=='search')
        action = {'action':'press','target':search['id'],'key':'Enter'} if search['has_value'] else {'action':'fill','target':search['id'],'value':'trail shoes'}
    action['observation_id'] = obs['observation_id']
    return SimpleNamespace(model='deterministic-fixture-policy', usage=None,
        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(action)))])
wt.create_chat_completion = create
try:
    for mode in ('full','compact'):
        result = wt.run(None, 'deterministic-fixture-policy', [{'agent_id':1,'name':'Fixture runner','bio':'Evaluate $50 trail shoes, Medium with blue laces.'}],
            {'url':url, 'goal':'add_to_cart','max_personas':1,'max_steps':12, 'observation_mode':mode,
             'task':'Search for trail shoes, select Medium and blue laces, and add the configured pair.',
             'checks':[{'name':'cart_added','selector':'#cart','text':'1 item'}], 'goal_check':'cart_added'},
            root/'mirofish_runs'/f'context_fixture_{mode}')
        assert result['summary']['goal_observed'] == 1, result['sessions'][0]['errors']
        assert result['summary']['model_calls'] == 7
        metrics = result['efficiency']['usage']
        measurements.append({'mode':mode, 'model_requests_to_stub':7, 'verified_goal':True,
            'payload_characters':metrics['prompt_chars'], 'full_payload_characters':metrics['full_prompt_chars'],
            'wall_seconds_without_provider_inference':result['elapsed_s'], 'provider_tokens':None,'invoiced_cost_usd':None})
    assert state['cart'] == 2 and state['queries'] == 2 and state['options'] == {'size':'M','laces':True}
    benchmark = {'benchmark':'browser_context_fixture','date':'2026-10-19','policy':'Deterministic model-response stub; real Chromium on an owned catalog fixture.',
        'measurements':measurements,'payload_character_reduction_percent':round(100*(1-measurements[1]['payload_characters']/measurements[0]['payload_characters']),2),
        'limitations':['No external model inference or provider token measurement; character reduction is not token or cost savings.',
            'One controlled journey; does not establish model completion rates, real-customer behavior, or production throughput.',
            'Wall times exclude provider inference and must not be used to claim model speed improvements.']}
    (root/'benchmarks/browser_context_fixture.json').write_text(json.dumps(benchmark,indent=2)+'\n')
    print(json.dumps(benchmark))
finally:
    fixture.close()
