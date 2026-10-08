import json, time, uuid, threading, logging, os
from .config import settings
from .db import Store, snapshots, Deferred
from .analysis import analyze_workspace
from .provider import Nvidia

def run_once(store, config=settings):
    owner=str(uuid.uuid4()); job=store.claim(owner,config.lease_seconds)
    if not job: return False
    stop=threading.Event()
    def renew():
        while not stop.wait(15):
            if not store.heartbeat(job['id'],owner,config.lease_seconds): break
    thread=threading.Thread(target=renew,daemon=True); thread.start()
    try:
        payload=job['payload']; row=store.row(snapshots,payload['snapshot_id'])
        if not row: raise ValueError('Snapshot not found')
        store.progress(job['id'],'Building evidence knowledge graph across immutable repository snapshots')
        entries=[]
        for entry in payload.get('workspace',[{'repository_id':payload['repository_id'],'snapshot_id':payload['snapshot_id'],'name':'Repository'}]):
            captured=store.row(snapshots,entry['snapshot_id'])
            if not captured or captured['repository_id']!=entry['repository_id']: raise ValueError('Workspace snapshot ownership mismatch')
            entries.append(dict(entry,snapshot=json.loads(captured['payload'])))
        report=analyze_workspace(entries,payload['repository_id'],payload['intent'],payload.get('patch',''),store)
        report['change_memory']=store.related_reviews(report)
        store.progress(job['id'],f"Located {len(report['impacted'])} impacted nodes, {len(report['findings'])} source-rule findings; regression tests selected, not executed")
        active=store.job(job['id'])
        if not active or active['state']!='RUNNING' or active['owner']!=owner or active['lease_until']<time.time():
            return True
        store.progress(job['id'],'Requesting bounded Nemotron analysis; shared budget and cache apply')
        report['ai']=Nvidia(store,config).infer(report)
        report['snapshot_id']=payload['snapshot_id']; report['repository_id']=payload['repository_id']; report['job_id']=job['id']
        if report['ai']['status']=='GROUNDED_DRAFT':
            lines=['@nemotron @review_required','Feature: '+report['intent'][:150].replace('\n',' ')]
            for test in report['ai']['analysis']['tests']:
                test={key:(' '.join(value.splitlines()) if isinstance(value,str) else value) for key,value in test.items()}
                lines+=['  # Evidence: '+', '.join(test['evidence_ids']),'  Scenario: '+test['name'],'    Given '+test['given'],'    When '+test['when'],'    Then '+test['then']]
            report['bdd']={'status':'MODEL_DRAFT_REVIEW_REQUIRED','content':'\n'.join(lines)+'\n'}
        if store.finish(job['id'],owner,report): store.progress(job['id'],'Report committed with citations. Human review and executed tests are required.')
    except Deferred as exc: store.defer(job['id'],owner,exc.until,str(exc))
    except Exception as exc:
        # Only internal error type is persisted. Avoid leaking source / provider credentials.
        store.fail(job['id'],owner,'Analysis failed: '+type(exc).__name__)
        logging.exception('Analysis job %s failed',job['id'])
    finally: stop.set(); thread.join(timeout=1)
    return True

def main():
    store=Store(settings.database_url)
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    print('Impact Studio worker ready; PID:',os.getpid(),'; hosted model:',settings.model,flush=True)
    while True:
        if not run_once(store): time.sleep(1)

if __name__=='__main__': main()
