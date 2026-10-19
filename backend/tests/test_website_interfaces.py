"""Check website journeys retain exact task/run identity across agent interfaces."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_mcp_website_job_writes_private_spec_and_results(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location('website_mcp', ROOT/'plugin/skills/market-mirror/scripts/mcp_server.py')
    mcp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mcp)
    monkeypatch.setattr(mcp,'home',lambda: str(tmp_path))
    jobs = []
    monkeypatch.setattr(mcp,'job',lambda args,label: jobs.append((args,label)) or {'job_id':'x'})
    mcp.call('website_test',{'simulation_id':'sim_x','spec':{'url':'https://example.com', 'max_model_calls':4, 'observation_mode':'full'},'out':str(tmp_path/'out')})
    args, label = jobs[0]
    assert args[:4] == ['cli','website-test','--simulation','sim_x'] and label == 'website-test'
    saved = Path(args[5][1:])
    assert saved.stat().st_mode & 0o777 == 0o600
    assert json.loads(saved.read_text())['url'] == 'https://example.com'
    assert json.loads(saved.read_text())['max_model_calls'] == 4
    fields = next(tool for tool in mcp.TOOLS if tool['name'] == 'website_test')['inputSchema']['properties']['spec']['properties']
    assert {'max_model_calls', 'max_input_tokens', 'max_elapsed_s', 'observation_mode', 'loop_limit'} <= fields.keys()
    (tmp_path/'website_test.json').write_text('{"type":"website_test","status":"completed","summary":{"visitors":1}}')
    assert mcp.results(str(tmp_path))['summary']['visitors'] == 1


def test_sdk_waits_and_reads_exact_run(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT/'sdk'))
    from marketmirror import MarketMirror
    client = MarketMirror()
    calls = []
    def call(method,path,**kwargs):
        calls.append((method,path,kwargs))
        return {'task_id':'task_x','run_id':'website_123'} if method == 'POST' else {'status':'completed'}
    monkeypatch.setattr(client,'_call',call)
    monkeypatch.setattr(client,'wait',lambda task: calls.append(('wait',task,{})))
    assert client.website_test('sim_x',{'url':'https://example.com'})['status'] == 'completed'
    assert calls[1][1] == 'task_x'
    assert calls[2][2]['params']['run_id'] == 'website_123'


def test_sdk_results_support_standalone_website_and_mixed_run(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT/'sdk'))
    from marketmirror import MarketMirror
    client = MarketMirror(repo=str(tmp_path))
    (tmp_path/'website_test.json').write_text('{"type":"website_test","summary":{"visitors":2}}')
    assert client.results(str(tmp_path))['summary']['visitors'] == 2
    (tmp_path/'summary.json').write_text('{"decision":"iterate"}')
    assert client.results(str(tmp_path))['decision'] == 'iterate'
    assert client.results(str(tmp_path))['website_test']['type'] == 'website_test'


def test_cli_exports_website_report_and_rejects_invalid_specs(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT/'backend/claude_cli'))
    import mirofish
    from app.services import website_test
    monkeypatch.setattr(mirofish.market_cli,'wait_task',lambda *a: None)
    monkeypatch.setattr(website_test,'render_report',lambda result: '<html>Website evidence</html>')
    class Client:
        def data(self,method,path,**kwargs):
            if method == 'POST':
                assert kwargs['json']['spec']['max_model_calls'] == 4
                assert kwargs['json']['spec']['observation_mode'] == 'full'
                return {'task_id':'task_x','run_id':'website_aabbccddeeff'}
            assert kwargs['params']['run_id'] == 'website_aabbccddeeff'
            return {'status':'completed','summary':{'visitors':1},'milestones':{},'files':{},'interpretation':'Synthetic visitors'}
    args = mirofish.build_parser().parse_args(['website-test','--simulation','sim_x','--url','https://example.com','--out',str(tmp_path), '--max-model-calls', '4', '--observation-mode', 'full'])
    result = mirofish.cmd_website_test(Client(),args)
    assert Path(result['dashboard']).read_text() == '<html>Website evidence</html>'
    assert Path(result['result_file']).is_file()
    args.url = 'file:///etc/passwd'
    with pytest.raises(mirofish.CLIError,match='HTTP'):
        mirofish.cmd_website_test(Client(),args)
