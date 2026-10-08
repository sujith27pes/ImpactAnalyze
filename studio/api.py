import json, secrets, time
from pathlib import Path
from urllib.parse import urlsplit
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse, Response, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import select
from .config import settings, ROOT
from .db import Store, snapshots, repositories, jobs, digest, Deferred
from .indexer import capture, apply_patch, redact
from .provider import Nvidia
from .reporting import jira_review

store=Store(settings.database_url)
app=FastAPI(title='Impact Studio',version='2.0.0',docs_url='/docs' if not settings.api_token else None)

@app.middleware('http')
async def boundary(request:Request, call_next):
    if request.url.path.startswith('/api/'):
        if settings.api_token and not secrets.compare_digest(request.headers.get('authorization',''),'Bearer '+settings.api_token):
            return JSONResponse({'detail':'API authentication required'},status_code=401)
        origin=request.headers.get('origin')
        if request.method not in ('GET','HEAD') and origin and urlsplit(origin).netloc!=request.headers.get('host'):
            return JSONResponse({'detail':'Cross-origin writes rejected'},status_code=403)
        try: size=int(request.headers.get('content-length','0') or 0)
        except ValueError: return JSONResponse({'detail':'Invalid Content-Length'},status_code=400)
        if size>150000:
            return JSONResponse({'detail':'Request body exceeds 150 KB'},status_code=413)
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Referrer-Policy']='no-referrer'
    response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
    return response

class RepositoryInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    name:str=Field(min_length=1,max_length=120)
    path:str=Field(min_length=1,max_length=500)
class AnalysisInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    repository_id:str=Field(max_length=40)
    repository_ids:list[str]=Field(default_factory=list,max_length=8)
    intent:str=Field(min_length=15,max_length=4000)
    patch:str=Field(default='',max_length=100000)
    idempotency_key:str=Field(default='',max_length=100)

class ReviewInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    lesson:str=Field(min_length=20,max_length=2000)
    reviewer:str=Field(min_length=2,max_length=120)
    disposition:str=Field(pattern='^(NEEDS_TESTING|ACCEPTED_FOR_PLANNING)$')

def repo_or_404(id):
    repo=store.row(repositories,id)
    if not repo: raise HTTPException(404,'Repository not found')
    root=Path(repo['root']).resolve()
    if not any(root.is_relative_to(Path(p).resolve()) for p in settings.roots): raise HTTPException(403,'Repository is outside configured roots')
    return repo
def job_or_404(id):
    job=store.job(id)
    if not job: raise HTTPException(404,'Job not found')
    return job

@app.get('/health')
def health(): return {'status':'ok','service':'impact-studio','queue':'durable-sql','ai_configured':bool(settings.api_key)}
@app.get('/api/status')
def status():
    with store.engine.connect() as c:
        recent=[dict(r) for r in c.execute(select(jobs.c.id,jobs.c.state,jobs.c.created,jobs.c.updated,jobs.c.error).order_by(jobs.c.created.desc()).limit(20)).mappings()]
    return {'provider':Nvidia(store,settings).status(),'jobs':recent,'repository_roots':[str(p) for p in settings.roots],'read_only':True,'database':'PostgreSQL' if not settings.database_url.startswith('sqlite') else 'SQLite (local demo)','auth_enabled':bool(settings.api_token)}
@app.get('/api/repositories')
def repository_list(): return store.repository_list()
@app.post('/api/repositories',status_code=201)
def register(data:RepositoryInput):
    root=Path(data.path).resolve()
    if not any(root.is_relative_to(Path(p).resolve()) for p in settings.roots): raise HTTPException(403,'Repository must be within REPOSITORY_ROOTS')
    try: snapshot=capture(root)
    except (ValueError,OSError) as exc: raise HTTPException(422,str(exc))
    existing=next((r for r in store.repository_list() if Path(r['root'])==root),None)
    repo=existing or store.add_repository(data.name,root)
    id=store.snapshot(repo['id'],snapshot)
    return dict(repo,snapshot_id=id,files=len(snapshot['files']),skipped=len(snapshot['skipped']),ingest_version=snapshot['ingest_version'])
@app.post('/api/demo')
def demo():
    return register(RepositoryInput(name='Synthetic banking platform',path=str(ROOT/'examples/banking-platform')))
@app.post('/api/demo/workspace')
def polyglot_demo():
    repos=[register(RepositoryInput(name=name,path=str(ROOT/'examples/polyglot-bank'/directory))) for directory,name in [('payments-api','Payments API · Python'),('customer-web','Customer web · TypeScript'),('audit-worker','Audit worker · Go'),('analytics','Analytics · SQL')]]
    return {'repositories':repos,'repository_id':repos[0]['id'],'repository_ids':[r['id'] for r in repos],'intent':'Move the payment acceptance endpoint from /payments to /payments/v2. Preserve audit events and reporting. Identify affected repositories, consumers which lose their contract match, and targeted regression tests.','patch':(ROOT/'examples/polyglot-bank/endpoint-v2.patch').read_text(encoding='utf-8')}
@app.get('/api/demo/patch')
def demo_patch():
    return {'intent':'Change payment events from minor units to major units while preserving monetary value across ledger, reconciliation and reporting. Identify downstream changes, risks and required tests.','patch':(ROOT/'examples/banking-platform/changes/major-unit.patch').read_text()}
@app.get('/api/demo/workspace/verification')
def polyglot_verification():
    path=ROOT/'data/polyglot-verification/results.json'
    if not path.is_file(): return {'available':False}
    data=json.loads(path.read_text(encoding='utf-8')); fixture=ROOT/'examples/polyglot-bank'
    return dict(data,available=True,matches_current_source=data['fixture_fingerprint']==digest(capture(fixture/'payments-api')['file_hashes']) and data['patch_fingerprint']==digest((fixture/'endpoint-v2.patch').read_text(encoding='utf-8')))
@app.get('/api/demo/verification')
def fixture_verification():
    path=ROOT/'data/verification/results.json'
    if not path.is_file(): return {'available':False,'message':'Run scripts/verify_fixture.py to produce executable evidence for the authored fixture.'}
    fixture=ROOT/'examples/banking-platform'; data=json.loads(path.read_text(encoding='utf-8')); fingerprint=digest(capture(fixture)['file_hashes'])
    patch_fingerprints={p.name:digest(p.read_text(encoding='utf-8')) for p in (fixture/'changes').glob('*.patch')}
    return {'available':True,'matches_current_source':data['fixture_fingerprint']==fingerprint and data.get('patch_fingerprints')==patch_fingerprints,'created':data['created'],'results':[{k:v for k,v in r.items() if k!='disposable_copy'} for r in data['results']],'scope':'Executed authored fixture, not tests executed by the analysis job'}
@app.post('/api/analyses',status_code=202)
def submit(data:AnalysisInput):
    repo=repo_or_404(data.repository_id)
    try:
        snap=capture(repo['root']); apply_patch(snap['files'],data.patch)
    except (ValueError,OSError) as exc: raise HTTPException(422,str(exc))
    id=store.snapshot(repo['id'],snap)
    workspace=[{'repository_id':repo['id'],'snapshot_id':id,'name':repo['name']}]
    for other_id in sorted(set(data.repository_ids)-{repo['id']}):
        other=repo_or_404(other_id)
        try: captured=capture(other['root'])
        except (ValueError,OSError) as exc: raise HTTPException(422,str(exc))
        workspace.append({'repository_id':other_id,'snapshot_id':store.snapshot(other_id,captured),'name':other['name']})
    if len(workspace)>8: raise HTTPException(422,'Workspace supports up to 8 repositories per analysis')
    payload={'repository_id':repo['id'],'snapshot_id':id,'workspace':workspace,'intent':redact(data.intent),'patch':redact(data.patch)}
    from .graph import VERSION
    from .engine import fingerprint
    key=digest({'payload':payload,'graph_version':VERSION,'engine':fingerprint(),'model':settings.model,'provider_configured':bool(settings.api_key),'idempotency':data.idempotency_key})
    try: return store.enqueue(payload,key)
    except Deferred as exc: raise HTTPException(429,str(exc),headers={'Retry-After':'5'})
@app.get('/api/jobs/{id}')
def get_job(id:str): return job_or_404(id)
@app.get('/api/jobs/{id}/events')
def get_events(id:str,after:int=0):
    job_or_404(id); return store.event_list(id,after)
@app.post('/api/jobs/{id}/cancel')
def cancel(id:str): job_or_404(id); return store.cancel(id)
@app.get('/api/jobs/{id}/drift')
def drift(id:str):
    job=job_or_404(id); results=[]
    for entry in job['payload'].get('workspace',[{'repository_id':job['payload']['repository_id'],'snapshot_id':job['payload']['snapshot_id'],'name':'Repository'}]):
        repo=repo_or_404(entry['repository_id']); baseline=json.loads(store.row(snapshots,entry['snapshot_id'])['payload'])
        try: current=capture(repo['root'])
        except (ValueError,OSError) as exc: raise HTTPException(422,str(exc))
        paths=set(current['file_hashes'])|set(baseline['file_hashes'])
        changed=sorted(p for p in paths if current['file_hashes'].get(p)!=baseline['file_hashes'].get(p))
        results.append(dict(entry,stale=bool(changed) or current.get('skipped',[])!=baseline.get('skipped',[]),changed_files=changed))
    return {'stale':any(r['stale'] for r in results),'changed_files':[r['name']+'/'+p for r in results for p in r['changed_files']],'repositories':results,'snapshot_id':job['payload']['snapshot_id'],'checked_at':time.time()}

@app.get('/api/jobs/{id}/graph')
def query_graph(id:str,node_id:str='',kind:str='',limit:int=100,offset:int=0):
    report=job_or_404(id).get('result')
    if not report: raise HTTPException(409,'Graph not ready')
    if not 1<=limit<=200 or offset<0: raise HTTPException(422,'Graph limit must be 1–200 and offset non-negative')
    return dict(store.graph_page(id,node_id,kind,limit,offset),stats=report['graph']['stats'])

@app.post('/api/jobs/{id}/reviews',status_code=201)
def remember_review(id:str,data:ReviewInput):
    report=job_or_404(id).get('result')
    if not report: raise HTTPException(409,'Review requires a completed evidence report')
    return store.remember(id,{'intent':report['intent'],'lesson':redact(data.lesson),'reviewer':redact(data.reviewer),'disposition':data.disposition,'node_ids':[n['id'] for n in report['impacted']],'evidence_fingerprint':report.get('knowledge_graph',{}).get('evidence_fingerprint',report['snapshot']),'test_status':'HUMAN_NOTE_NOT_EXECUTION_EVIDENCE','gate_at_review':report['gate']})
@app.get('/api/jobs/{id}/export')
def export(id:str,format:str='json'):
    job=job_or_404(id); report=job.get('result')
    if not report: raise HTTPException(409,'Report not ready')
    if format=='bdd': return Response(report['bdd']['content'],media_type='text/plain',headers={'Content-Disposition':'attachment; filename="impact-review.feature"'})
    if format=='jira':
        return Response(jira_review(report),media_type='text/plain',headers={'Content-Disposition':'attachment; filename="jira-impact-review.txt"'})
    if format!='json': raise HTTPException(422,'Use json, bdd or jira')
    return JSONResponse(report,headers={'Content-Disposition':'attachment; filename="impact-evidence.json"'})

app.mount('/static',StaticFiles(directory=ROOT/'studio/static'),name='static')
@app.get('/')
def home(): return FileResponse(ROOT/'studio/static/index.html')
