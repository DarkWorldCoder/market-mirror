"""Efficiency must preserve decision context and account for unknown usage."""
import copy
from types import SimpleNamespace

import pytest

from app.services import website_efficiency as efficiency
from app.services import website_test as wt


@pytest.mark.parametrize('key,value', [
    ('max_model_calls', True), ('max_model_calls', 1.5), ('max_model_calls', 601),
    ('max_input_tokens', -1), ('max_elapsed_s', float('nan')), ('max_elapsed_s', float('inf')),
    ('observation_text_chars', 999), ('loop_limit', 1), ('observation_mode', 'unknown')])
def test_invalid_limits_rejected(key, value):
    with pytest.raises(ValueError, match=key):
        wt.normalize({'url': 'https://example.com', key: value})


def observation():
    return {'observation_id': 'o1', 'url': 'https://example.com', 'title': 'Product',
            'text': 'Shoes $50. Returns accepted. ' * 300, 'active_tab': 'tab0',
            'tabs': [{'id': 'tab0', 'url': 'https://example.com', 'active': True}],
            'controls': [{'id': 'o1-e0', 'tag': 'input', 'type': 'checkbox', 'label': 'Blue laces',
                'checked': False, 'disabled': False, 'has_value': False, 'frame': 'frame0',
                'rect': {'x': 1, 'y': 2, 'width': 100, 'height': 20}, 'form_fields': [], 'dom_id': 'laces',
                'href': None, 'options': []}], 'frames': [], 'allowed_urls': [], 'browser_events': []}


def test_compact_view_keeps_choices_and_false_state_without_mutating_evidence():
    full = observation()
    before = copy.deepcopy(full)
    compact = efficiency.model_observation(full, wt.normalize({'url': full['url']}))
    assert full == before
    assert compact['controls'][0]['id'] == 'o1-e0'
    assert compact['controls'][0]['checked'] is False
    assert compact['controls'][0]['has_value'] is False
    assert compact['text_truncated'] is True
    assert len(compact['text']) == 4000 and 'rect' not in compact['controls'][0]
    assert len(efficiency.dumps(compact)) < len(efficiency.dumps(full))
    assert efficiency.model_observation(full, {'observation_mode': 'full'}) is full
    full['controls'][0]['options'] = [{'value': '', 'label': 'Choose size', 'selected': True, 'disabled': False}]
    assert efficiency.model_observation(full, wt.normalize({'url': full['url']}))['controls'][0]['options'][0]['value'] == ''


def test_choose_preserves_cache_breakdown_cost_model_and_payload_metrics(monkeypatch):
    requests = []
    def create(*args, **kwargs):
        requests.append(kwargs)
        return SimpleNamespace(model='actual-model', choices=[SimpleNamespace(message=SimpleNamespace(content='{"action":"leave"}'))],
            usage=SimpleNamespace(prompt_tokens=100, completion_tokens=5), usage_source='provider',
            usage_breakdown={'uncached_input_tokens': 10, 'cache_read_input_tokens': 70, 'cache_creation_input_tokens': 20},
            cost_usd=.001, cost_basis='cli_reported_list_cost')
    monkeypatch.setattr(wt, 'create_chat_completion', create)
    action, usage = wt.choose(None, 'alias', {'name': 'Buyer'}, wt.normalize({'url': 'https://example.com'}), observation(), [])
    assert action['action'] == 'leave'
    assert usage['input_tokens'] == 100 and usage['uncached_input_tokens'] == 10
    assert usage['cache_read_input_tokens'] == 70 and usage['cache_creation_input_tokens'] == 20
    assert usage['cost_usd'] == .001 and usage['model'] == 'actual-model'
    assert usage['prompt_chars'] < usage['full_prompt_chars']
    assert usage['prompt_chars'] == len(requests[0]['messages'][1]['content'])


def test_openai_cached_tokens_and_missing_cost_are_not_invented(monkeypatch):
    monkeypatch.setattr(wt, 'create_chat_completion', lambda *a, **k: SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='{"action":"leave"}'))],
        usage=SimpleNamespace(prompt_tokens=100, completion_tokens=5, prompt_tokens_details=SimpleNamespace(cached_tokens=80))))
    _, usage = wt.choose(None, 'fixture', {}, wt.normalize({'url': 'https://example.com'}), observation(), [])
    assert usage['cache_read_input_tokens'] == 80 and usage['uncached_input_tokens'] == 20
    assert usage['cost_usd'] is None and usage['cache_creation_input_tokens'] is None
    result = efficiency.usage_summary([{'model_calls': 2, 'steps': [{'usage': usage}]}])
    assert result['cost_usd'] is None and not result['cost_complete']
    assert result['uncached_input_tokens'] is None and result['measured_calls'] == 1


def test_malformed_decision_retains_provider_usage(monkeypatch):
    monkeypatch.setattr(wt, 'create_chat_completion', lambda *a, **k: SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='not valid JSON'))],
        usage=SimpleNamespace(prompt_tokens=100, completion_tokens=5), cost_usd=.001, cost_basis='cli_reported_list_cost'))
    action, usage = wt.choose(None, 'fixture', {}, wt.normalize({'url': 'https://example.com'}), observation(), [])
    assert action is None and usage['input_tokens'] == 100 and usage['cost_usd'] == .001


def test_run_budgets_stop_on_calls_tokens_unknown_usage_and_time(monkeypatch):
    clock = [0]
    monkeypatch.setattr(efficiency, 'time', SimpleNamespace(monotonic=lambda: clock[0]))
    spec = wt.normalize({'url': 'https://example.com', 'max_model_calls': 2, 'max_input_tokens': 100, 'max_elapsed_s': 10})
    budget = efficiency.RunBudget(spec)
    budget.calls = 1
    budget.charge({'input_tokens': 99})
    assert budget.reason() is None
    budget.charge({'input_tokens': 1})
    assert budget.reason() == 'max_input_tokens'
    budget.calls = 2
    assert budget.reason() == 'max_model_calls'
    clock[0] = 10
    assert budget.reason() == 'max_elapsed_s'
    unknown = efficiency.RunBudget(spec)
    unknown.charge({'input_tokens': None})
    assert unknown.reason() == 'input_usage_unavailable'


def test_loop_detection_ignores_new_ids_but_recognizes_state_progress():
    guard = efficiency.LoopGuard(3)
    full = observation()
    action = {'action': 'focus', 'target': 'o1-e0', 'observation_id': 'o1', 'reason': 'one'}
    assert not guard.repeated(full, action)
    full['observation_id'] = 'o2'
    full['controls'][0]['id'] = 'o2-e0'
    action.update(target='o2-e0', observation_id='o2', reason='two')
    assert not guard.repeated(full, action)
    assert guard.repeated(full, action)
    full['controls'][0]['checked'] = True
    assert not guard.repeated(full, action)
    assert not any(guard.repeated(full, {'action': 'scroll'}) for _ in range(10))
