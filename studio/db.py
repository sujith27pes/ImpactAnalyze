"""Portable durable queue and provider admission control; PostgreSQL shares state across replicas."""
import json, time, uuid, hashlib, os
from contextlib import contextmanager
from pathlib import Path
from sqlalchemy import create_engine, MetaData, Table, Column, String, Text, Float, Integer, select, update, insert, and_, or_, event
from sqlalchemy.exc import IntegrityError

metadata = MetaData()
repositories = Table('repositories', metadata, Column('id', String(40), primary_key=True), Column('name', String(160)), Column('root', Text), Column('created', Float))
snapshots = Table('snapshots', metadata, Column('id', String(64), primary_key=True), Column('repository_id', String(40), index=True), Column('created', Float), Column('payload', Text))
jobs = Table('jobs', metadata, Column('id', String(40), primary_key=True), Column('request_key', String(64), unique=True), Column('state', String(30), index=True), Column('owner', String(80)), Column('lease_until', Float, default=0), Column('next_run', Float, default=0), Column('attempts', Integer, default=0), Column('payload', Text), Column('result', Text), Column('error', Text), Column('created', Float), Column('updated', Float))
events = Table('job_events', metadata, Column('id', Integer, primary_key=True, autoincrement=True), Column('job_id', String(40), index=True), Column('at', Float), Column('message', Text))
cache = Table('inference_cache', metadata, Column('id', String(64), primary_key=True), Column('payload', Text), Column('created', Float))
budgets = Table('provider_budgets', metadata, Column('id', String(100), primary_key=True), Column('minute', Integer), Column('day', Integer), Column('calls', Integer), Column('tokens', Integer), Column('daily', Integer), Column('lease_owner', String(80)), Column('lease_until', Float), Column('blocked_until', Float), Column('failures', Integer), Column('requests', Integer), Column('cache_hits', Integer))
queue_guard = Table('queue_guard', metadata, Column('id', Integer, primary_key=True), Column('version', Integer))
graph_cache = Table('source_graph_cache', metadata, Column('id', String(64), primary_key=True), Column('payload', Text), Column('created', Float))
reviews = Table('change_reviews', metadata, Column('id',String(40),primary_key=True),Column('job_id',String(40),index=True),Column('created',Float),Column('payload',Text))
knowledge_nodes = Table('knowledge_nodes',metadata,Column('id',String(64),primary_key=True),Column('job_id',String(40),index=True),Column('node_id',String(600),index=True),Column('kind',String(40),index=True),Column('payload',Text))
knowledge_edges = Table('knowledge_edges',metadata,Column('id',String(64),primary_key=True),Column('job_id',String(40),index=True),Column('source',String(600),index=True),Column('target',String(600),index=True),Column('kind',String(80),index=True),Column('payload',Text))

def encode(value): return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
def digest(value): return hashlib.sha256(encode(value).encode()).hexdigest()

class Deferred(Exception):
    def __init__(self, until, reason): self.until, self.reason = until, reason; super().__init__(reason)

class Store:
    def __init__(self, url):
        if url.startswith('sqlite:///'):
            Path(url.removeprefix('sqlite:///')).parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(url, connect_args={'check_same_thread': False, 'timeout': 20} if url.startswith('sqlite') else {}, pool_pre_ping=True)
        if url.startswith('sqlite'):
            @event.listens_for(self.engine, 'connect')
            def sqlite_setup(connection, _):
                cursor = connection.cursor(); cursor.execute('PRAGMA journal_mode=WAL'); cursor.execute('PRAGMA busy_timeout=20000'); cursor.close()
        if os.getenv('IMPACT_INITIALIZE_SCHEMA','1')=='1': metadata.create_all(self.engine)
        try:
            with self.engine.begin() as c: c.execute(insert(queue_guard).values(id=1,version=0))
        except IntegrityError: pass
    def row(self, table, id):
        with self.engine.connect() as c:
            row = c.execute(select(table).where(table.c.id == id)).mappings().first()
            return dict(row) if row else None
    def add_repository(self, name, root):
        id = str(uuid.uuid4())
        with self.engine.begin() as c: c.execute(insert(repositories).values(id=id, name=name, root=str(root), created=time.time()))
        return self.row(repositories, id)
    def repository_list(self):
        with self.engine.connect() as c: return [dict(r) for r in c.execute(select(repositories).order_by(repositories.c.created.desc())).mappings()]
    def snapshot(self, repository_id, data):
        id = digest({'repository': repository_id, 'files': data['file_hashes'], 'skipped':data.get('skipped',[]), 'index_version': data.get('ingest_version','legacy')})
        try:
            with self.engine.begin() as c: c.execute(insert(snapshots).values(id=id, repository_id=repository_id, created=time.time(), payload=encode(data)))
        except IntegrityError: pass
        return id
    def enqueue(self, payload, key):
        id, now = str(uuid.uuid4()), time.time()
        try:
            with self.engine.begin() as c:
                # Serialize admission only, not execution; prevents capacity races across API replicas.
                c.execute(update(queue_guard).where(queue_guard.c.id==1).values(version=queue_guard.c.version+1))
                existing=c.execute(select(jobs.c.id).where(jobs.c.request_key==key)).scalar_one_or_none()
                if existing: id=existing
                else:
                    if len(c.execute(select(jobs.c.id).where(jobs.c.state.in_(['QUEUED', 'RUNNING', 'WAITING_PROVIDER']))).fetchall()) >= 100:
                        raise Deferred(now+5, 'Job queue capacity reached')
                    c.execute(insert(jobs).values(id=id, request_key=key, state='QUEUED', owner='', lease_until=0, next_run=0, attempts=0, payload=encode(payload), result='', error='', created=now, updated=now))
                    c.execute(insert(events).values(job_id=id, at=now, message='Queued for repository evidence analysis'))
        except IntegrityError:
            with self.engine.connect() as c: id = c.execute(select(jobs.c.id).where(jobs.c.request_key == key)).scalar_one()
        return self.job(id)
    def job(self, id):
        row = self.row(jobs, id)
        if row:
            for key in ('payload', 'result'): row[key] = json.loads(row[key]) if row[key] else None
        return row
    def claim(self, owner, seconds=240):
        now = time.time()
        claimed = None
        eligible = and_(jobs.c.attempts < 4, or_(and_(jobs.c.state.in_(['QUEUED', 'WAITING_PROVIDER']), jobs.c.next_run <= now), and_(jobs.c.state == 'RUNNING', jobs.c.lease_until < now)))
        with self.engine.begin() as c:
            c.execute(update(jobs).where(jobs.c.state=='RUNNING', jobs.c.lease_until<now, jobs.c.attempts>=4).values(state='FAILED', error='Worker recovery limit reached', lease_until=0, updated=now))
            candidates = c.execute(select(jobs.c.id).where(eligible).order_by(jobs.c.created).limit(8)).scalars().all()
            for id in candidates:
                changed = c.execute(update(jobs).where(jobs.c.id == id, eligible).values(state='RUNNING', owner=owner, lease_until=now+seconds, attempts=jobs.c.attempts+1, updated=now))
                if changed.rowcount:
                    claimed = id
                    break
        return self.job(claimed) if claimed else None
    def heartbeat(self, id, owner, seconds=240):
        with self.engine.begin() as c:
            return bool(c.execute(update(jobs).where(jobs.c.id==id, jobs.c.owner==owner, jobs.c.state=='RUNNING').values(lease_until=time.time()+seconds)).rowcount)
    def progress(self, id, message):
        with self.engine.begin() as c: c.execute(insert(events).values(job_id=id, at=time.time(), message=message))
    def finish(self, id, owner, result):
        with self.engine.begin() as c:
            changed=c.execute(update(jobs).where(jobs.c.id==id, jobs.c.owner==owner, jobs.c.state=='RUNNING', jobs.c.lease_until >= time.time()).values(state='COMPLETED', result=encode(result), updated=time.time(), lease_until=0)).rowcount
            if not changed: return False
            graph=result.get('graph',{})
            node_rows=[{'id':digest([id,n['id']]),'job_id':id,'node_id':n['id'],'kind':n['kind'],'payload':encode(n)} for n in graph.get('nodes',[])]
            edge_rows=[{'id':digest([id,e['source'],e['target'],e['kind']]),'job_id':id,'source':e['source'],'target':e['target'],'kind':e['kind'],'payload':encode(e)} for e in graph.get('edges',[])]
            for table,rows in [(knowledge_nodes,node_rows),(knowledge_edges,edge_rows)]:
                for start in range(0,len(rows),500): c.execute(insert(table),rows[start:start+500])
            return True
    def graph_page(self,job_id,node_id='',kind='',limit=100,offset=0):
        from sqlalchemy import func
        with self.engine.connect() as c:
            query=select(knowledge_nodes).where(knowledge_nodes.c.job_id==job_id)
            if kind: query=query.where(knowledge_nodes.c.kind==kind)
            if node_id:
                inbound=select(knowledge_edges.c.source).where(knowledge_edges.c.job_id==job_id,knowledge_edges.c.target==node_id)
                outbound=select(knowledge_edges.c.target).where(knowledge_edges.c.job_id==job_id,knowledge_edges.c.source==node_id)
                query=query.where(or_(knowledge_nodes.c.node_id==node_id,knowledge_nodes.c.node_id.in_(inbound),knowledge_nodes.c.node_id.in_(outbound)))
            count=c.execute(select(func.count()).select_from(query.subquery())).scalar_one()
            rows=c.execute(query.order_by(knowledge_nodes.c.node_id).offset(offset).limit(limit)).mappings().all()
            nodes=[json.loads(r['payload']) for r in rows]; ids=[n['id'] for n in nodes]
            edges=[json.loads(r['payload']) for r in c.execute(select(knowledge_edges.c.payload).where(knowledge_edges.c.job_id==job_id,knowledge_edges.c.source.in_(ids),knowledge_edges.c.target.in_(ids))).mappings()]
            return {'nodes':nodes,'edges':edges,'total_matching':count,'truncated':count>offset+len(nodes),'offset':offset,'next_offset':offset+len(nodes) if count>offset+len(nodes) else None}
    def defer(self, id, owner, until, reason):
        with self.engine.begin() as c: c.execute(update(jobs).where(jobs.c.id==id, jobs.c.owner==owner, jobs.c.state=='RUNNING').values(state='WAITING_PROVIDER', next_run=until, attempts=jobs.c.attempts-1, error=reason, lease_until=0, updated=time.time()))
        self.progress(id, reason)
    def fail(self, id, owner, reason):
        with self.engine.begin() as c: c.execute(update(jobs).where(jobs.c.id==id, jobs.c.owner==owner, jobs.c.state=='RUNNING').values(state='FAILED', error=reason, lease_until=0, updated=time.time()))
    def cancel(self, id):
        with self.engine.begin() as c: c.execute(update(jobs).where(jobs.c.id==id, jobs.c.state.in_(['QUEUED','WAITING_PROVIDER','RUNNING'])).values(state='CANCELLED', lease_until=0, updated=time.time()))
        return self.job(id)
    def event_list(self, id, after=0):
        with self.engine.connect() as c: return [dict(r) for r in c.execute(select(events).where(events.c.job_id==id, events.c.id>after).order_by(events.c.id).limit(100)).mappings()]
    def cached(self, key):
        row = self.row(cache, key); return json.loads(row['payload']) if row else None
    def graph_cached(self,key):
        row=self.row(graph_cache,key); return json.loads(row['payload']) if row else None
    def put_graph_cache(self,key,graph):
        try:
            with self.engine.begin() as c: c.execute(insert(graph_cache).values(id=key,payload=encode(graph),created=time.time()))
        except IntegrityError: pass
    def remember(self,job_id,review):
        id=str(uuid.uuid4())
        with self.engine.begin() as c: c.execute(insert(reviews).values(id=id,job_id=job_id,created=time.time(),payload=encode(review)))
        return dict(review,id=id,job_id=job_id)
    def related_reviews(self,report):
        from .analysis import terms
        query=terms(report['intent']); current={n['id'] for n in report['impacted']}; ranked=[]
        with self.engine.connect() as c: rows=c.execute(select(reviews).order_by(reviews.c.created.desc()).limit(200)).mappings().all()
        for row in rows:
            review=json.loads(row['payload']); overlap=query & terms(review['intent']); shared=current & set(review['node_ids'])
            score=len(overlap)+len(shared)*2
            if score: ranked.append((score,dict(review,id=row['id'],job_id=row['job_id'],created=row['created'],shared_node_count=len(shared),matched_terms=sorted(overlap))))
        return {'basis':'Historical human review + lexical / graph overlap; suggestions only, never current dependency or test proof','items':[r for _,r in sorted(ranked,key=lambda x:x[0],reverse=True)[:5]]}
    def put_cache(self, key, result):
        try:
            with self.engine.begin() as c: c.execute(insert(cache).values(id=key, payload=encode(result), created=time.time()))
        except IntegrityError: pass
    def ensure_budget(self, id):
        try:
            with self.engine.begin() as c: c.execute(insert(budgets).values(id=id, minute=0, day=0, calls=0, tokens=0, daily=0, lease_owner='', lease_until=0, blocked_until=0, failures=0, requests=0, cache_hits=0))
        except IntegrityError: pass
    def admit(self, id, owner, tokens, settings, now=None):
        now = time.time() if now is None else now
        self.ensure_budget(id)
        # A conditional update provides a shared semaphore, not a process-local limiter.
        with self.engine.begin() as c:
            locked = c.execute(update(budgets).where(budgets.c.id==id, budgets.c.lease_until <= now).values(lease_owner=owner, lease_until=now+settings.lease_seconds))
            if not locked.rowcount: raise Deferred(now+3, 'Another worker holds the shared NVIDIA inference slot')
            row = dict(c.execute(select(budgets).where(budgets.c.id==id)).mappings().one())
            minute, day = int(now//60), int(now//86400)
            calls, used = (row['calls'],row['tokens']) if row['minute']==minute else (0,0)
            daily = row['daily'] if row['day']==day else 0
            delay, reason = 0, ''
            if row['blocked_until'] > now: delay,reason=row['blocked_until'],'NVIDIA cooldown / circuit breaker is active'
            elif daily >= settings.daily_calls: delay,reason=(day+1)*86400,'Application daily inference budget reached'
            elif tokens > settings.tpm: delay,reason=now+60,'Context exceeds configured per-minute token budget'
            elif calls >= settings.rpm or used+tokens > settings.tpm: delay,reason=(minute+1)*60+1,'Application NVIDIA request/token budget reached'
            if delay:
                c.execute(update(budgets).where(budgets.c.id==id).values(lease_until=0, lease_owner=''))
            else:
                c.execute(update(budgets).where(budgets.c.id==id).values(minute=minute, day=day, calls=calls+1, tokens=used+tokens, daily=daily+1, requests=row['requests']+1))
        if delay: raise Deferred(delay,reason)
    def release(self, id, owner, failure=False, cooldown=0):
        with self.engine.begin() as c:
            row = c.execute(select(budgets).where(budgets.c.id==id)).mappings().one()
            count = row['failures']+1 if failure else 0
            until = max(time.time()+cooldown if cooldown>0 else 0, time.time()+60 if count>=3 else 0, row['blocked_until'])
            c.execute(update(budgets).where(budgets.c.id==id, budgets.c.lease_owner==owner).values(lease_owner='', lease_until=0, failures=count, blocked_until=until))
    def reserve_poll(self, id, owner, settings):
        """Status GETs consume request quota while retaining the inference semaphore."""
        now=time.time(); minute=int(now//60); day=int(now//86400)
        with self.engine.begin() as c:
            row=c.execute(select(budgets).where(budgets.c.id==id)).mappings().one()
            if row['lease_owner']!=owner or row['lease_until']<=now: return False
            calls=row['calls'] if row['minute']==minute else 0
            daily=row['daily'] if row['day']==day else 0
            if calls>=settings.rpm or daily>=settings.daily_calls: return False
            c.execute(update(budgets).where(budgets.c.id==id,budgets.c.lease_owner==owner).values(minute=minute,day=day,calls=calls+1,daily=daily+1,requests=budgets.c.requests+1,tokens=row['tokens'] if row['minute']==minute else 0))
            return True
    def cache_hit(self, id):
        self.ensure_budget(id)
        with self.engine.begin() as c: c.execute(update(budgets).where(budgets.c.id==id).values(cache_hits=budgets.c.cache_hits+1))
