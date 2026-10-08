from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from studio import api
from studio.config import ROOT
from studio.db import Store
from studio.worker import run_once

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(api,'store',Store('sqlite:///'+(tmp_path/'api.db').as_posix()))
    monkeypatch.setattr(api.settings,'api_token','')
    monkeypatch.setattr(api.settings,'api_key','')
    monkeypatch.setattr(api.settings,'roots',(ROOT/'examples',))
    return TestClient(api.app)

def test_full_api_job_snapshot_report_and_exports(client):
    repo=client.post('/api/demo').json(); example=client.get('/api/demo/patch').json()
    payload={'repository_id':repo['id'],**example,'idempotency_key':'same-request'}
    first=client.post('/api/analyses',json=payload)
    assert first.status_code==202
    assert client.post('/api/analyses',json=payload).json()['id']==first.json()['id']
    assert run_once(api.store,api.settings)
    id=first.json()['id']; job=client.get('/api/jobs/'+id).json()
    assert job['state']=='COMPLETED' and job['result']['findings']
    assert client.get(f'/api/jobs/{id}/drift').json()['stale'] is False
    assert 'Given' in client.get(f'/api/jobs/{id}/export?format=bdd').text
    assert 'Tests: selected; not executed' in client.get(f'/api/jobs/{id}/export?format=jira').text
    assert client.get(f'/api/jobs/{id}/events').json()

def test_registration_allowlist_and_invalid_patch(client):
    assert client.post('/api/repositories',json={'name':'outside','path':str(ROOT.parent)}).status_code==403
    repo=client.post('/api/demo').json()
    assert client.post('/api/analyses',json={'repository_id':repo['id'],'intent':'Change payment event semantics','patch':'arbitrary text'}).status_code==422

def test_token_and_cross_origin_boundaries(client,monkeypatch):
    monkeypatch.setattr(api.settings,'api_token','local-test-token')
    assert client.get('/api/status').status_code==401
    assert client.get('/api/status',headers={'Authorization':'Bearer local-test-token'}).status_code==200
    assert client.post('/api/demo',headers={'Authorization':'Bearer local-test-token','Origin':'https://unrelated.example'}).status_code==403
    assert client.get('/').headers['content-security-policy'].startswith("default-src 'self'")

def test_polyglot_workspace_indexed_graph_review_and_exports(client):
    demo=client.post('/api/demo/workspace').json()
    queued=client.post('/api/analyses',json={key:demo[key] for key in ('repository_id','repository_ids','intent','patch')})
    assert queued.status_code==202
    assert run_once(api.store,api.settings)
    id=queued.json()['id'];report=client.get('/api/jobs/'+id).json()['result']
    assert report['knowledge_graph']['repository_count']==4 and report['knowledge_graph']['cross_repository_edges']==4
    assert report['contract_alerts'] and report['ai']['status']=='NOT_CONFIGURED'
    brief=client.get(f'/api/jobs/{id}/export?format=jira').text
    assert 'Contract compatibility alerts:' in brief
    assert 'A previously linked consumer loses its contract match' in brief
    assert 'Customer web · TypeScript / HTTP POST /payments' in brief
    assert 'no code, tests or deployment executed' in brief
    assert 'No narrow source-rule violation found; review contract alerts' in brief
    assert 'Payments API · Python / test_app.py' in brief
    graph=client.get(f'/api/jobs/{id}/graph?kind=contract&limit=2').json()
    assert len(graph['nodes'])==2 and graph['truncated'] and graph['next_offset']==2
    assert client.get(f'/api/jobs/{id}/graph?limit=201').status_code==422
    assert len(client.get(f'/api/jobs/{id}/drift').json()['repositories'])==4
    saved=client.post(f'/api/jobs/{id}/reviews',json={'reviewer':'QA team','lesson':'Verify legacy payment consumers during mixed version rollout.','disposition':'NEEDS_TESTING'})
    assert saved.status_code==201 and saved.json()['test_status']=='HUMAN_NOTE_NOT_EXECUTION_EVIDENCE'
    assert client.get('/api/jobs/'+id).json()['result']['gate']=='REVIEW_REQUIRED'

def test_provider_failure_and_contract_alert_both_survive_jira_export(client,monkeypatch):
    from studio import worker
    unavailable={'status':'PROVIDER_UNAVAILABLE','http_status':503,'message':'Provider temporarily unavailable',
                 'retry_after_seconds':60,'retry_automatic':False}
    monkeypatch.setattr(worker.Nvidia,'infer',lambda *args,**kwargs: unavailable)
    demo=client.post('/api/demo/workspace').json()
    queued=client.post('/api/analyses',json={key:demo[key] for key in ('repository_id','repository_ids','intent','patch')}).json()
    assert worker.run_once(api.store,api.settings)
    job=client.get('/api/jobs/'+queued['id']).json()
    assert job['state']=='COMPLETED' and job['result']['gate']=='REVIEW_REQUIRED'
    brief=client.get(f"/api/jobs/{queued['id']}/export?format=jira").text
    assert 'AI: PROVIDER_UNAVAILABLE' in brief and 'Provider HTTP status: 503' in brief
    assert 'AI details: Provider temporarily unavailable' in brief
    assert 'Consumer: Customer web · TypeScript / HTTP POST /payments' in brief
    assert 'Tests: selected; not executed' in brief and 'Unresolved scope:' in brief
    assert 'api_key' not in brief and 'Authorization' not in brief

def test_cancel_during_indexing_prevents_a_new_provider_call(client,monkeypatch):
    from studio import worker
    repo=client.post('/api/demo').json()
    queued=client.post('/api/analyses',json={'repository_id':repo['id'],'intent':'Review payment downstream dependencies'}).json()
    original=worker.analyze_workspace
    def cancelled(*args,**kwargs):
        report=original(*args,**kwargs);api.store.cancel(queued['id']);return report
    def unexpected(*args,**kwargs): raise AssertionError('Cancelled job must not start inference')
    monkeypatch.setattr(worker,'analyze_workspace',cancelled)
    monkeypatch.setattr(worker.Nvidia,'infer',unexpected)
    assert worker.run_once(api.store,api.settings)
    result=client.get('/api/jobs/'+queued['id']).json()
    assert result['state']=='CANCELLED' and result['result'] is None
