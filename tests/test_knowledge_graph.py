import copy, hashlib, json
from pathlib import Path
import pytest
from studio import contracts, engine
from studio.config import ROOT
from studio.indexer import capture, build_index, redact
from studio.graph import build, combine
from studio.analysis import analyze_workspace
from studio.db import Store

POLYGLOT=ROOT/'examples/polyglot-bank'

def entries():
    return [{'repository_id':name,'name':name,'snapshot_id':name,'snapshot':capture(POLYGLOT/name)} for name in ['payments-api','customer-web','audit-worker','analytics']]

@pytest.fixture(scope='module')
def graph():
    return combine([build(e['snapshot'],e['repository_id'],e['name']) for e in entries()])

def test_real_polyglot_parser_and_scoped_downstream_paths(graph):
    assert engine.identity()['status']=='READY'
    assert all(r['receipt']['status']=='PARSED' for r in graph['repositories'])
    assert {n['repository_id'] for n in graph['nodes']}=={'payments-api','customer-web','audit-worker','analytics'}
    cross=[e for e in graph['edges'] if e.get('cross_repository')]
    assert len(cross)==4
    assert {e['kind'] for e in cross}=={'CROSS_REPO_HTTP','CROSS_REPO_EVENT','CROSS_REPO_DATABASE'}
    assert len({n['id'] for n in graph['nodes']})==len(graph['nodes'])
    for edge in graph['edges']:
        assert edge['source'] in {n['id'] for n in graph['nodes']}
        assert edge['target'] in {n['id'] for n in graph['nodes']}
        assert all(eid in graph['evidence'] for eid in edge['evidence'])
    assert any(n['kind']=='symbol' and n['repository_id']=='audit-worker' for n in graph['nodes'])
    assert any(n['kind']=='symbol' and n['repository_id']=='customer-web' for n in graph['nodes'])

def test_endpoint_rehearsal_detects_lost_consumer_and_selects_actual_http_test():
    result=analyze_workspace(entries(),'payments-api','Rename the payment endpoint while preserving downstream audit',(POLYGLOT/'endpoint-v2.patch').read_text(encoding='utf-8'))
    assert result['counterfactual']['available']
    assert len(result['contract_alerts'])==1
    assert result['contract_alerts'][0]['consumer'].startswith('customer-web::')
    assert any(t['class']=='test_app.test_consumer_endpoint' for t in result['selected_tests'])
    assert {n['repository_id'] for n in result['impacted']}=={'payments-api','customer-web','audit-worker','analytics'}
    assert result['gate']=='REVIEW_REQUIRED' and result['tests_executed'] is False

@pytest.mark.parametrize('protocol,role,field,value',[('http','consumes','method','DELETE'),('http','consumes','scope','https://unrelated.bank'),('event','subscribes','scope','another-kafka'),('event','subscribes','environment','production'),('database','reads','scope','another-database')])
def test_same_name_wrong_method_host_broker_environment_database_never_links(graph,protocol,role,field,value):
    candidate=copy.deepcopy(graph); candidate['edges']=[e for e in candidate['edges'] if not e.get('cross_repository')]
    node=next(n for n in candidate['nodes'] if n.get('contract',{}).get('protocol')==protocol and n['contract']['role']==role)
    node['contract'][field]=value; contracts.join(candidate)
    assert not any(e['target']==node['id'] for e in candidate['edges'] if e.get('cross_repository'))
    assert any(u.get('repository_id')==node['repository_id'] and node['contract']['resource'] in u['reason'] for u in candidate['unknown'])

def test_duplicate_endpoint_providers_are_unknown_not_arbitrary_winner(graph):
    candidate=copy.deepcopy(graph); candidate['edges']=[e for e in candidate['edges'] if not e.get('cross_repository')]
    provider=copy.deepcopy(next(n for n in candidate['nodes'] if n.get('contract',{}).get('protocol')=='http' and n['contract']['role']=='provides'))
    provider['id']='other::provider';provider['repository_id']='another-payments';candidate['nodes'].append(provider)
    contracts.join(candidate)
    assert not any(e['kind']=='CROSS_REPO_HTTP' for e in candidate['edges'])
    assert any('Ambiguous http consumer' in u['reason'] and len(u['candidate_ids'])==2 for u in candidate['unknown'])

def test_provider_declaration_that_contradicts_source_is_withheld():
    selected=entries(); focus=selected[0]['snapshot'];declaration=json.loads(focus['files']['.impact-contracts.json'])
    declaration['contracts'][0]['resource']='/nonexistent'
    focus['files']['.impact-contracts.json']=json.dumps(declaration)
    other=json.loads(selected[1]['snapshot']['files']['.impact-contracts.json']);other['contracts'][0]['resource']='/nonexistent';selected[1]['snapshot']['files']['.impact-contracts.json']=json.dumps(other)
    graph=combine([build(e['snapshot'],e['repository_id'],e['name']) for e in selected])
    assert not any(e['kind']=='CROSS_REPO_HTTP' for e in graph['edges'])
    assert any('contradicts parsed routes' in u['reason'] for u in graph['unknown'])

def test_parse_failure_and_unsupported_language_remain_visible(tmp_path):
    (tmp_path/'broken.py').write_text('def broken(:\n',encoding='utf-8')
    (tmp_path/'legacy.cob').write_text('IDENTIFICATION DIVISION.\n',encoding='utf-8')
    (tmp_path/'opaque.xyz').write_text('unknown source',encoding='utf-8')
    snap=capture(tmp_path); graph=build(snap)
    assert 'legacy.cob' in snap['files'] and 'opaque.xyz' in snap['files']
    assert 'legacy.cob' in graph['coverage_ledger']['unsupported_source_files']
    assert graph['unknown'] or graph['parser_receipt'].get('quality',{}).get('parse_errors')
    assert 'opaque.xyz' in graph['coverage_ledger']['unsupported_source_files']

def test_provider_configuration_never_executes_or_mutates_repository(tmp_path):
    marker=tmp_path/'executed.txt'
    (tmp_path/'main.py').write_text('def value():\n    return 7\n',encoding='utf-8')
    (tmp_path/'mcp-arch.yaml').write_text(json.dumps({'providers':[{'name':'evil','command':['python','-c',f"open({str(marker)!r},'w').write('executed')"]}]}),encoding='utf-8')
    graph=build(capture(tmp_path))
    assert graph['parser_receipt']['status']=='PARSED'
    assert not marker.exists() and not (tmp_path/'.impact-engine').exists() and not (tmp_path/'.enola').exists()

def test_namespace_prevents_identical_repository_symbols_colliding():
    snapshot=entries()[0]['snapshot']; graph=combine([build(snapshot,'a','A'),build(snapshot,'b','B')])
    assert len({n['id'] for n in graph['nodes']})==len(graph['nodes'])
    assert not any(e.get('cross_repository') for e in graph['edges'])

def test_graph_cache_invalidates_on_parser_policy_and_source(tmp_path,monkeypatch):
    store=Store('sqlite:///'+(tmp_path/'index.db').as_posix());snapshot=entries()[0]['snapshot'];calls=[]
    original=engine.extract
    def tracked(s):calls.append(1);return original(s)
    monkeypatch.setattr(engine,'extract',tracked)
    build(snapshot,'repo','Repo',store);build(snapshot,'repo','Repo',store)
    assert len(calls)==1
    changed=copy.deepcopy(snapshot);changed['files']['app.py']+='\n# source changed\n';build(changed,'repo','Repo',store)
    assert len(calls)==2
    monkeypatch.setattr(engine,'fingerprint',lambda:'different-policy');build(snapshot,'repo','Repo',store)
    assert len(calls)==3

def test_json_credentials_redacted_without_breaking_structure():
    text=redact('{"password": "sensitive-value", "api_key": "sensitive-key", "normal": "value"}')
    assert json.loads(text)['normal']=='value'
    assert 'sensitive' not in text

def test_wrong_http_verb_is_not_matched_to_java_post_endpoint():
    snapshot=capture(ROOT/'examples/banking-platform');path='payments-service/src/main/java/bank/payments/LedgerClient.java'
    snapshot['files'][path]=snapshot['files'][path].replace('.post()', '.get()')
    graph=build_index(snapshot)
    assert graph['stats']['http_edges']==2
    assert any('/ledger/postings' in u['reason'] for u in graph['unknown'])

def test_historical_review_is_a_suggestion_and_cannot_change_gate(tmp_path):
    store=Store('sqlite:///'+(tmp_path/'memory.db').as_posix());report={'intent':'Change payment endpoint for downstream audit','impacted':[{'id':'repo::endpoint'}],'gate':'REVIEW_REQUIRED'}
    store.remember('past',{'intent':'Payment endpoint migration','lesson':'Check legacy web consumers and mixed version deployment','node_ids':['repo::endpoint'],'reviewer':'QA','disposition':'NEEDS_TESTING'})
    memory=store.related_reviews(report)
    assert memory['items'][0]['shared_node_count']==1
    assert 'suggestions only' in memory['basis'] and report['gate']=='REVIEW_REQUIRED'

def test_http_route_template_direction():
    assert contracts.route_matches('/payments/{id}','/payments/123')
    assert not contracts.route_matches('/payments/123','/payments/{id}')
    assert not contracts.route_matches('/payments/{id}','/payments/123/extra')

def test_concurrent_source_edit_refuses_hybrid_snapshot(tmp_path,monkeypatch):
    source=tmp_path/'app.py';source.write_text('def value():\n    return 1\n',encoding='utf-8')
    original=Path.read_bytes; calls=[]
    def racing(path):
        data=original(path)
        if path==source and not calls:
            calls.append(1);source.write_text('def value():\n    return 2\n',encoding='utf-8')
        return data
    monkeypatch.setattr(Path,'read_bytes',racing)
    with pytest.raises(ValueError,match='changed during capture'): capture(tmp_path)

def test_unfamiliar_language_diff_has_file_scope_and_unknown(tmp_path):
    source=tmp_path/'program.xyz';source.write_text('custom behavior v1\n',encoding='utf-8')
    snap=capture(tmp_path)
    result=analyze_workspace([{'repository_id':'unknown','name':'Custom language','snapshot_id':'source','snapshot':snap}],'unknown','Change the custom behavior version','--- a/program.xyz\n+++ b/program.xyz\n@@ -1 +1 @@\n-custom behavior v1\n+custom behavior v2\n')
    assert result['roots']==['unknown::file:program.xyz']
    assert result['graph']['unknown'] and result['gate']=='REVIEW_REQUIRED'
    assert result['tests_executed'] is False

def test_proposal_parser_failure_is_not_a_dependency_removal(monkeypatch):
    original=engine.extract
    def failure(snapshot):
        if '/payments/v2' in snapshot['files'].get('app.py',''):
            return {'facts':[],'receipt':{'status':'FAILED'},'error':'Injected parser failure; source relationships unknown'}
        return original(snapshot)
    monkeypatch.setattr(engine,'extract',failure)
    result=analyze_workspace(entries(),'payments-api','Rename the payment endpoint while preserving downstream audit',(POLYGLOT/'endpoint-v2.patch').read_text(encoding='utf-8'))
    assert result['counterfactual']['available'] is False
    assert result['counterfactual']['comparable'] is False
    assert result['contract_alerts']==[] and result['gate']=='REVIEW_REQUIRED'

def test_infrastructure_repo_has_static_resource_dependency_without_execution(tmp_path):
    (tmp_path/'main.tf').write_text('resource "aws_s3_bucket" "payments" {\n  bucket = "synthetic-payments"\n}\nresource "aws_s3_bucket_policy" "policy" {\n  bucket = aws_s3_bucket.payments.id\n  policy = jsonencode({})\n}\n',encoding='utf-8')
    graph=build(capture(tmp_path))
    resources={n['label']:n['id'] for n in graph['nodes'] if n['kind']=='symbol'}
    assert graph['parser_receipt']['status']=='PARSED'
    assert any(e['source']==resources['aws_s3_bucket.payments'] and e['target']==resources['aws_s3_bucket_policy.policy'] and e['kind']=='PARSER_DEPENDS_ON' for e in graph['edges'])
    assert not (tmp_path/'.terraform').exists() and not (tmp_path/'.impact-engine').exists()

def test_maven_manifest_change_reaches_dependent_builds_and_source():
    snapshot=capture(ROOT/'examples/banking-platform')
    path='contracts/pom.xml';old=snapshot['files'][path];import difflib
    patch=''.join(difflib.unified_diff(old.splitlines(True),(old+'<!-- proposed build metadata -->\n').splitlines(True),fromfile='a/'+path,tofile='b/'+path))
    result=analyze_workspace([{'repository_id':'bank','name':'Bank','snapshot_id':'before','snapshot':snapshot}],'bank','Review the shared contract module build change',patch)
    assert 'bank::module:contracts' in result['roots']
    assert {'payments-service','ledger-service','reconciliation-service','reporting-service'}<={n['module'] for n in result['impacted']}
    assert result['selected_tests'] and result['tests_executed'] is False
    assert result['gate']=='REVIEW_REQUIRED'
