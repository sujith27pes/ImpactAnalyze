import json, hashlib, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import httpx, pytest
from studio.config import Settings, ROOT
from studio.db import Store, Deferred
from studio.indexer import capture, build_index, apply_patch, redact
from studio.analysis import analyze
from studio.analysis import inference_context
from studio.provider import Nvidia
from studio.worker import run_once

FIXTURE=ROOT/'examples/banking-platform'
@pytest.fixture
def snapshot(): return capture(FIXTURE)
@pytest.fixture
def report(snapshot): return analyze(snapshot,'Change payment events from minor to major units', (FIXTURE/'changes/major-unit.patch').read_text(encoding='utf-8'))
@pytest.fixture
def store(tmp_path): return Store('sqlite:///'+(tmp_path/'test.db').as_posix())
def config(**kwargs): return Settings(api_key='synthetic-test-key',**kwargs)
def model_output(report,unknown=False):
    eid=next(iter(report['graph']['evidence']))
    return {'choices':[{'finish_reason':'stop','message':{'content':json.dumps({'summary':'A draft for review','risks':[{'title':'Unit semantics','explanation':'Confirm consumer interpretation','evidence_ids':['E-invented' if unknown else eid]}],'tests':[],'ba_questions':['Must existing consumers support both units?']})}}],'usage':{'prompt_tokens':100,'completion_tokens':50}}
def valid_output(request):
    context=json.loads(json.loads(request.content)['messages'][1]['content']); eid=context['allowed_evidence_ids'][0]
    return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps({'summary':'Confirm financial semantics','risks':[{'title':'Consumer unit change','explanation':'Hypothesis requires review','evidence_ids':[eid]}],'tests':[{'name':'Value conservation','given':'125.50 USD','when':'all consumers process the event','then':'all balances equal 125.50 USD','evidence_ids':[eid]}],'ba_questions':['Is a mixed-version rollout required?']})}}],'usage':{'prompt_tokens':100,'completion_tokens':200}})

def test_real_dependency_graph_and_semantic_break(report):
    assert report['roots']==['class:bank.payments.PaymentService']
    assert {n['module'] for n in report['impacted']}=={'payments-service','ledger-service','reconciliation-service','reporting-service'}
    assert report['graph']['stats']['http_edges']==3
    assert report['findings'][0]['observed_counterfactual']=='1.255'
    assert report['gate']=='BLOCKED_BY_SOURCE_RULE'
    assert report['selected_tests'][0]['class']=='MoneyJourneyTest'
    assert report['tests_executed'] is False
    for edge in report['graph']['edges']:
        assert edge['evidence'] and all(id in report['graph']['evidence'] for id in edge['evidence'])

def test_model_sees_validated_before_after_proposal(report):
    context=inference_context(report,16000)
    assert 'AmountUnit.MINOR' in context['change_excerpts'][0]['before']
    assert 'AmountUnit.MAJOR' in context['change_excerpts'][0]['after']
    assert context['allowed_evidence_ids']

def test_insert_only_patch_with_zero_context():
    result,_=apply_patch({'a.java':'class A {}\n'},'--- a/a.java\n+++ b/a.java\n@@ -0,0 +1 @@\n+// documentation\n')
    assert result['a.java']=='// documentation\nclass A {}\n'

def test_schema_claim_is_removed_when_no_supporting_schema(snapshot):
    snapshot['files']={p:t for p,t in snapshot['files'].items() if not p.endswith('.schema.json')}
    result=analyze(snapshot,'Change producer units',(FIXTURE/'changes/major-unit.patch').read_text(encoding='utf-8'))
    assert 'Schema-valid' not in result['findings'][0]['title']
    assert 'wire schema' not in result['findings'][0]['explanation']

def test_route_discovery_changes_with_source(snapshot):
    path='payments-service/src/main/java/bank/payments/LedgerClient.java'
    snapshot['files'][path]=snapshot['files'][path].replace('/ledger/postings','/unknown/postings')
    graph=build_index(snapshot)
    assert graph['stats']['http_edges']==2
    assert any('/unknown/postings' in u['reason'] for u in graph['unknown'])

def test_patch_is_in_memory_and_validates_context(snapshot):
    patch=(FIXTURE/'changes/major-unit.patch').read_text(encoding='utf-8')
    original=dict(snapshot['files']); modified,changes=apply_patch(original,patch)
    assert snapshot['files']==original and changes
    assert modified!=original
    with pytest.raises(ValueError): apply_patch(original,patch.replace('amountMajor.movePointRight(2)','NOT_THE_SOURCE'))
    with pytest.raises(ValueError): apply_patch(original,patch.replace('a/payments-service/','a/../payments-service/'))

def test_fixed_counterfactual_has_no_unit_violation(snapshot):
    files,_=apply_patch(snapshot['files'],(FIXTURE/'changes/ledger-unit-fix.patch').read_text(encoding='utf-8'))
    snapshot=dict(snapshot,files=files,file_hashes={p:hashlib.sha256(t.encode()).hexdigest() for p,t in files.items()})
    result=analyze(snapshot,'Major unit transition',(FIXTURE/'changes/major-unit.patch').read_text(encoding='utf-8'))
    assert result['findings']==[] and result['gate']=='REVIEW_REQUIRED'

def test_intent_is_never_presented_as_actual_diff(snapshot):
    report=analyze(snapshot,'Change payment duplicate handling to preserve idempotency')
    assert report['mode']=='INTENT' and 'hypotheses' in report['entry_basis']
    assert report['gate']=='REVIEW_REQUIRED'

def test_capture_excludes_secrets_and_build_output(tmp_path):
    (tmp_path/'pom.xml').write_text('<project><artifactId>demo</artifactId></project>')
    (tmp_path/'.env').write_text('NVIDIA_API_KEY=private')
    (tmp_path/'target').mkdir(); (tmp_path/'target/Generated.java').write_text('secret')
    (tmp_path/'application.properties').write_text('password=very-secret\nserver.port=9000')
    data=capture(tmp_path)
    assert '.env' not in data['files'] and 'target/Generated.java' not in data['files']
    assert 'very-secret' not in data['files']['application.properties']
    assert 'sk-abc123456789000' not in redact('sk-abc123456789000')

def test_job_claim_is_exclusive_and_cancel_prevents_commit(store):
    job=store.enqueue({'snapshot_id':'demo'},'unique')
    with ThreadPoolExecutor(max_workers=6) as pool:
        claims=list(pool.map(lambda i:store.claim(str(i)),range(6)))
    claimed=[j for j in claims if j]; assert len(claimed)==1
    assert claimed[0]['state']=='RUNNING'
    store.cancel(job['id'])
    assert not store.finish(job['id'],claimed[0]['owner'],{'unsafe':'late result'})
    assert store.enqueue({'snapshot_id':'demo'},'unique')['id']==job['id']

def test_shared_provider_admission_and_daily_budget(store):
    s=config(rpm=1,daily_calls=1)
    store.admit('scope','worker-a',100,s,now=1000)
    with pytest.raises(Deferred): store.admit('scope','worker-b',100,s,now=1001)
    store.release('scope','worker-a')
    with pytest.raises(Deferred) as error: store.admit('scope','worker-b',100,s,now=1100)
    assert 'daily' in str(error.value)

def test_grounded_nvidia_result_cached_and_secrets_not_sent_as_context(store,report):
    seen=[]
    def transport(request): seen.append(request); return valid_output(request)
    provider=Nvidia(store,config(),httpx.MockTransport(transport))
    result=provider.infer(report); assert result['status']=='GROUNDED_DRAFT'
    second=provider.infer(report); assert second['cache_hit'] and len(seen)==1
    assert 'synthetic-test-key' not in seen[0].content.decode()
    assert seen[0].headers['Authorization']=='Bearer synthetic-test-key'
    assert report['gate']=='BLOCKED_BY_SOURCE_RULE'

def test_unknown_citations_are_rejected(store,report):
    provider=Nvidia(store,config(),httpx.MockTransport(lambda _:httpx.Response(200,json=model_output(report,True))))
    result=provider.infer(report)
    assert result['status']=='REJECTED_OR_FAILED'
    assert result['failure_reason']=='INVALID_CITATIONS'
    assert result['retry_automatic'] is False

@pytest.mark.parametrize('reason',['TIMEOUT','TRANSPORT_ERROR','TRUNCATED_OUTPUT','INVALID_FORMAT'])
def test_provider_reports_safe_actionable_failure_category(store,report,reason):
    calls=[]
    def handler(request):
        calls.append(request)
        if reason=='TIMEOUT': raise httpx.ReadTimeout('synthetic-secret-body',request=request)
        if reason=='TRANSPORT_ERROR': raise httpx.ConnectError('synthetic-secret-body',request=request)
        payload=model_output(report)
        if reason=='TRUNCATED_OUTPUT': payload['choices'][0]['finish_reason']='length'
        else: payload['choices'][0]['message']['content']='synthetic-secret-body invalid JSON'
        return httpx.Response(200,json=payload)
    provider=Nvidia(store,config(),httpx.MockTransport(handler))
    result=provider.infer(report)
    assert result['status']=='REJECTED_OR_FAILED'
    assert result['failure_reason']==reason and result['retry_automatic'] is False
    assert 'synthetic-secret-body' not in json.dumps(result)
    assert 'source results remain available' in result['message']
    assert len(calls)==1

@pytest.mark.parametrize('status',[401,402,410,429,503])
def test_provider_failure_has_no_retry_storm(store,report,status):
    count=[]
    def handler(request): count.append(request); return httpx.Response(status,headers={'Retry-After':'120'},json={'error':'sensitive body intentionally excluded'})
    provider=Nvidia(store,config(),httpx.MockTransport(handler))
    result=provider.infer(report)
    assert result['status']=='PROVIDER_UNAVAILABLE' and len(count)==1
    assert 'sensitive' not in json.dumps(result)
    if status in (429,503):
        with pytest.raises(Deferred): provider.infer(report)
        assert len(count)==1

def test_pending_is_not_success_or_resubmitted(store,report):
    provider=Nvidia(store,config(),httpx.MockTransport(lambda _:httpx.Response(202,headers={'nvcf-reqid':'pending-demo'})))
    result=provider.infer(report)
    assert result['status']=='PROVIDER_PENDING' and result['retry_automatic'] is False

def test_pending_resolves_with_budgeted_status_get_not_duplicate_post(store,report):
    seen=[]; rid='ae1d5335-1b65-429a-b4b9-64bb60f7a3f7'
    def handler(request):
        seen.append(request)
        if request.method=='POST':
            context=json.loads(json.loads(request.content)['messages'][1]['content'])
            seen.append(context)
            return httpx.Response(202,headers={'nvcf-reqid':rid})
        eid=seen[1]['allowed_evidence_ids'][0]
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps({'summary':'Resolved invocation','risks':[{'title':'Review','explanation':'Review consumer units','evidence_ids':[eid]}],'tests':[],'ba_questions':[]})}}]})
    provider=Nvidia(store,config(),httpx.MockTransport(handler))
    assert provider.infer(report)['status']=='GROUNDED_DRAFT'
    assert seen[0].method=='POST' and seen[2].method=='GET'
    assert seen[2].url.host=='api.nvcf.nvidia.com'
    assert provider.status()['requests']==2

def test_expired_worker_can_be_recovered_and_old_owner_cannot_commit(store):
    job=store.enqueue({'demo':True},'recovery')
    old=store.claim('old',seconds=-1); new=store.claim('new')
    assert old['id']==new['id']==job['id']
    assert not store.finish(job['id'],'old',{'old':True})
    assert store.finish(job['id'],'new',{'recovered':True})

def test_worker_degrades_honestly_without_key(store,snapshot):
    repo=store.add_repository('fixture',FIXTURE); sid=store.snapshot(repo['id'],snapshot)
    job=store.enqueue({'repository_id':repo['id'],'snapshot_id':sid,'intent':'Change payment events to major units','patch':(FIXTURE/'changes/major-unit.patch').read_text(encoding='utf-8')},'worker-demo')
    assert run_once(store,Settings(api_key=''))
    finished=store.job(job['id']); assert finished['state']=='COMPLETED'
    assert finished['result']['ai']['status']=='NOT_CONFIGURED'
    assert finished['result']['gate']=='BLOCKED_BY_SOURCE_RULE'
