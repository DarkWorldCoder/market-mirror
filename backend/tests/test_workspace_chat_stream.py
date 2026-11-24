"""Actual public progress framing with a fake provider; no paid model calls."""
import json
import threading
import time

import pytest

from app import create_app
from app.api import setup
from app.services import workspace_chat as service

H = {"X-Setup-Token": "stream-test"}
INPUT = {"messages": [{"role":"user", "content":"Explore my saved results"}]}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(setup, "SETUP_TOKEN", "stream-test")
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def parse(response):
    frames = []
    for block in response.get_data(as_text=True).strip().split("\n\n"):
        lines = block.splitlines()
        if len(lines) >= 2 and lines[0].startswith("event: "):
            frames.append((lines[0][7:],json.loads(lines[1][6:])))
    return frames


def test_stage_events_precede_final_result_and_hide_unknown_private_fields(client, monkeypatch):
    def fake(value, on_event):
        from flask import current_app
        assert current_app.testing
        assert value == INPUT
        on_event({"type":"model","status":"working","label":"Preparing an answer","private_reasoning":"DO_NOT_STREAM"})
        on_event({"type":"tool","status":"completed","label":"Read actual evidence","tool":"read_run","run":"saved-run"})
        on_event({"type":"agent","status":"completed","label":"Evidence review","summary":"Checked the supplied evidence"})
        return {"message":"Saved answer नेपाल", "artifacts":[]}
    monkeypatch.setattr(service,"chat",fake)
    response = client.post('/api/workspace/chat/stream',json=INPUT,headers=H)
    frames = parse(response)
    assert [name for name,_ in frames] == ['progress','progress','progress','result']
    assert frames[-1][1]['message'] == 'Saved answer नेपाल'
    assert 'DO_NOT_STREAM' not in response.get_data(as_text=True)
    assert response.headers['Content-Type'].startswith('text/event-stream')
    assert response.headers['X-Accel-Buffering'] == 'no'
    assert 'no-store' in response.headers['Cache-Control']


@pytest.mark.parametrize('error,status,message',[(service.ChatError('Provider unavailable',503),503,'Provider unavailable'),(ValueError('Choose an available model'),400,'Choose an available model'),(RuntimeError('private details'),500,'Could not complete this response. Try again.')])
def test_worker_errors_are_terminal_actual_status_events(client,monkeypatch,error,status,message):
    def fake(value,on_event):
        raise error
    monkeypatch.setattr(service,'chat',fake)
    frames = parse(client.post('/api/workspace/chat/stream',json=INPUT,headers=H))
    assert frames == [('error',{'message':message,'status':status})]


def test_validation_and_guards_precede_any_worker_call(client,monkeypatch):
    def never(*args,**kwargs):
        raise AssertionError('No provider call is allowed')
    monkeypatch.setattr(service,'chat',never)
    assert client.post('/api/workspace/chat/stream',json=INPUT).status_code == 403
    assert client.post('/api/workspace/chat/stream',json=INPUT,headers=H,environ_base={'REMOTE_ADDR':'10.0.0.5'}).status_code == 403
    assert client.post('/api/workspace/chat/stream',json=INPUT,headers={**H,'Origin':'https://evil.example'}).status_code == 403
    assert client.post('/api/workspace/chat/stream',json={'messages':[]},headers=H).status_code == 400
    assert client.post('/api/workspace/chat/stream',data='x'*200001,headers={**H,'Content-Type':'application/json'}).status_code == 413


def test_closed_delivery_does_not_block_worker_or_claim_upstream_cancellation(client,monkeypatch):
    finished = threading.Event()
    def fake(value,on_event):
        for index in range(100):
            on_event({'type':'tool','status':'working','label':f'Stage {index}'})
        finished.set()
        return {'message':'Work completed'}
    monkeypatch.setattr(service,'chat',fake)
    response = client.post('/api/workspace/chat/stream',json=INPUT,headers=H,buffered=False)
    assert next(iter(response.response)).startswith(b'event: progress')
    response.close()
    assert finished.wait(2)
