import re, json
from collections import deque
from decimal import Decimal
from .indexer import build_index, apply_patch
from .db import digest

def terms(text):
    text=re.sub(r'([a-z])([A-Z])',r'\1 \2',text)
    return set(re.findall(r'[a-z]{3,}',text.lower()))-{'the','and','with','from','for','this','that','service','change','request','should','new','amount'}

def analyze(snapshot, intent, patch='', graph=None, focus_repository_id=''):
    graph=graph or build_index(snapshot); proposed,changes=apply_patch(snapshot['files'],patch)
    excerpts=[]
    for change in changes:
        path=change['path']; old=change['old_start']-1; new=change['new_start']-1
        excerpts.append({'path':path,'basis':'Validated in-memory proposal; not merged or executed','before':'\n'.join(snapshot['files'][path].splitlines()[max(0,old-2):old+change['old_count']+2])[:1200],'after':'\n'.join(proposed[path].splitlines()[max(0,new-2):new+change['new_count']+2])[:1200]})
    for change,excerpt in zip(changes,excerpts): change['excerpt']=excerpt
    production=[n for n in graph['nodes'] if n['kind'] in {'class','symbol','route','storage','contract','module','service'}]
    focused=[n for n in production if n.get('repository_id','')==focus_repository_id]
    scores=[]; query=terms(intent)
    for node in focused:
        text=' '.join(graph['evidence'][id]['snippet'] for id in node['evidence'])
        score=len(query & terms(node['label']))*4 + len(query & terms(text))
        if score: scores.append((score,node['id']))
    scores.sort(reverse=True)
    if changes:
        roots=sorted({n['id'] for c in changes for n in focused if n['path']==c['path'] and any(n['start']<=line<=n['end'] for line in c['lines'])})
        # Build / contract edits can be anchored to a module if no class intersects.
        for c in changes:
            # Unsupported source / manifests still get an explicit, conservative file anchor.
            if not any(n['id'] in roots and n['path']==c['path'] for n in focused):
                roots += [n['id'] for n in graph['nodes'] if n['kind']=='file' and n['path']==c['path'] and n.get('repository_id','')==focus_repository_id]
            # Owner-declared file associations are deliberately coarse and visibly labelled.
            roots += [n['id'] for n in focused if n['kind']=='contract' and (n['path']==c['path'] or c['path']=='.impact-contracts.json')]
        roots=sorted(set(roots))
        basis='Validated diff against captured source'
    else:
        roots=[id for _,id in scores[:3]]; basis='Lexical intent hypotheses; BA / developer must confirm entry points'
    nodes={n['id']:n for n in graph['nodes']}; paths={id:[] for id in roots}; queue=deque(roots)
    adjacency={}
    for edge in graph['edges']: adjacency.setdefault(edge['source'],[]).append(edge)
    frontier=set(); node_limit=2000; hop_limit=12
    while queue:
        current=queue.popleft()
        for edge in adjacency.get(current,[]):
            target=edge['target']
            if target not in paths:
                if len(paths)>=node_limit or len(paths[current])>=hop_limit:
                    frontier.add(target); continue
                paths[target]=paths[current]+[edge]; queue.append(target)
    impacted=[dict(nodes[id],via=path,depth=len(path),impact_status='DECLARED_REVIEW_SCOPE' if any(e.get('resolution') in {'DECLARED','DECLARED_MATCH'} for e in path) else 'STATIC_REVIEW_SCOPE') for id,path in paths.items() if id in nodes and nodes[id]['kind']!='test']
    truncated=bool(frontier-set(paths))
    if truncated: graph['unknown'].append({'path':'Traversal','reason':'Impact traversal reached the 2,000 node / 12 hop review bound. Untraversed scope remains unknown.'})
    excluded=[{'id':n['id'],'label':n['label'],'module':n['module'],'reason':('Not reached within the bounded review traversal. Scope remains unknown.' if truncated else 'No path from the selected entry points in captured static evidence. This is not a safety proof.')} for n in production if n['id'] not in paths]
    tests=[]; targets=set(paths)
    for n in graph['nodes']:
        if n['kind']!='test': continue
        coverage={e['source'] for e in graph['edges'] if e['target']==n['id'] and e['source'] in targets}
        if coverage:
            tests.append({'class':n['label'],'module':n['module'],'path':n['path'],'methods':[m['name'] for m in n['methods'] if m['test']],'covers':sorted(coverage),'evidence':n['evidence'],'status':'SELECTED_NOT_RUN'})
    # Class-level static coverage: greedy set cover is a proposal, not runtime coverage.
    uncovered=set().union(*(set(t['covers']) for t in tests)) if tests else set()
    selected=[]; remaining=list(tests)
    while uncovered and remaining:
        chosen=max(remaining,key=lambda t:len(set(t['covers']) & uncovered))
        if not set(chosen['covers']) & uncovered: break
        selected.append(chosen); uncovered-=set(chosen['covers']); remaining.remove(chosen)
    findings=[]
    unit_schemas=[]
    for path,text in snapshot['files'].items():
        if not path.endswith('.schema.json'): continue
        try:
            if {'MINOR','MAJOR'}<=set(json.loads(text).get('properties',{}).get('amountUnit',{}).get('enum',[])): unit_schemas.append(path)
        except (ValueError,AttributeError,TypeError): pass
    # Deliberately narrow, inspectable financial rule. Not an LLM calculation or general oracle.
    for change in changes:
        path=change['path']; before=snapshot['files'][path]; after=proposed[path]
        if 'amountMajor.movePointRight(2), AmountUnit.MINOR' in before and 'amountMajor, AmountUnit.MAJOR' in after:
            consumers=[n for n in focused if n['kind']=='class' and 'event.amount().movePointLeft(2)' in proposed[n['path']] and 'event.amountUnit() ==' not in proposed[n['path']]]
            producer=next((n for n in focused if n['kind']=='class' and n['path']==path),None)
            for consumer in consumers:
                if consumer['id'] not in paths: continue
                value=Decimal('125.50'); actual=value/Decimal(100)
                findings.append({'id':'F-'+digest([path,consumer['path']])[:10],'severity':'CRITICAL','title':'Schema-valid amount unit change breaks monetary conservation','explanation':f'Producer now emits MAJOR units; reachable consumer still unconditionally divides by 100. Synthetic 125.50 USD becomes {actual} USD. Both units remain accepted by the wire schema.','basis':'Narrow source-pattern rule + Decimal arithmetic; execution must be verified separately','evidence':producer['evidence']+consumer['evidence'],'expected':str(value),'observed_counterfactual':str(actual),'ratio':'0.01','test_required':'Amount conservation across payment, ledger, reconciliation and reporting'})
                if unit_schemas:
                    findings[-1]['evidence'] += [id for id,e in graph['evidence'].items() if e['path'] in unit_schemas]
                    findings[-1]['explanation'] = findings[-1]['explanation'].replace('the wire schema','a captured amountUnit schema')
                else:
                    findings[-1]['title']='Amount unit change breaks monetary conservation'
                    findings[-1]['explanation']=findings[-1]['explanation'].split(' Both units')[0]
    handoffs=[]
    for repository_id,module in sorted({(n.get('repository_id',''),n['module']) for n in impacted}):
        members=[n for n in impacted if n['module']==module and n.get('repository_id','')==repository_id]
        owner=next((n['owner'] for n in members if n.get('owner','Unassigned')!='Unassigned'),'Unassigned')
        handoffs.append({'module':module,'repository_id':repository_id,'repository':members[0].get('repository',''),'owner':owner,'reason':'Review cited dependency paths and selected regression tests','actions':{'BA':'Confirm business semantics and acceptance examples','Developer':'Review consumers of changed contracts and units','QA':'Run selected tests and review generated BDD before use'}})
    report = {'snapshot':digest(snapshot['file_hashes']),'intent':intent,'mode':'DIFF' if changes else 'INTENT','entry_basis':basis,'roots':roots,'root_candidates':[{'id':id,'score':score} for score,id in scores[:8]],'changes':changes,'graph':graph,'impacted':impacted,'excluded':excluded,'selected_tests':selected,'coverage':{'basis':'Class-level static references, not observed runtime coverage','uncovered_classes':[n['id'] for n in impacted if n['kind']=='class' and not any(n['id'] in t['covers'] for t in selected)]},'findings':findings,'handoffs':handoffs,'gate':'BLOCKED_BY_SOURCE_RULE' if findings else 'REVIEW_REQUIRED','tests_executed':False,'ai':{'status':'PENDING'},'bdd':{'status':'DRAFT_REVIEW_REQUIRED','content':'@impact @review_required\nFeature: Preserve behavior across changed downstream contracts\n  Scenario: Monetary conservation after change\n    Given a synthetic USD payment of 125.50\n    When the payment travels through every impacted downstream\n    Then each posted and reported value equals 125.50 USD\n  Scenario: Idempotent replay\n    Given a payment already accepted by all impacted consumers\n    When the identical event is replayed\n    Then it contributes to each balance once\n'},'limitations':graph['limitations']+['Generated BDD is a review artifact. No Defender adapter or BDD execution is claimed.','No analysis can guarantee zero defects. Release approval requires executed evidence and accountable review.']}

    if not findings:
        report['bdd'] = {'status':'DRAFT_REVIEW_REQUIRED','content':'@impact @review_required\nFeature: Verify the requested change across affected consumers\n  Scenario: Approved business acceptance examples\n    Given BA-approved acceptance examples for the requested behavior\n    When the candidate implementation is exercised across affected consumers\n    Then observed results match approved expectations\n    And existing covered contracts remain compatible\n'}
    report['traversal']={'node_limit':node_limit,'hop_limit':hop_limit,'truncated':truncated,'untraversed_frontier_count':len(frontier-set(paths))}
    return report

def analyze_workspace(entries, focus_repository_id, intent, patch='', store=None):
    """One immutable snapshot per selected repository; patch only the focus repository."""
    import hashlib
    from .graph import build, combine, delta
    focus=next(e for e in entries if e['repository_id']==focus_repository_id)
    graphs=[build(e['snapshot'],e['repository_id'],e['name'],store) for e in entries]
    graph=combine(graphs)
    report=analyze(focus['snapshot'],intent,patch,graph,focus_repository_id)
    report['workspace']=[{'repository_id':e['repository_id'],'name':e['name'],'snapshot_id':e['snapshot_id']} for e in entries]
    report['knowledge_graph']={'version':graph['graph_version'],'repository_count':len(entries),'cross_repository_edges':graph['stats']['cross_repository_edges'],'unresolved':len(graph['unknown']),'resolution_counts':dict(__import__('collections').Counter(e.get('resolution','UNKNOWN') for e in graph['edges'])),'evidence_fingerprint':digest({e['repository_id']:e['snapshot']['file_hashes'] for e in entries})}
    report['counterfactual']={'available':False,'reason':'Provide a validated diff to compare dependency structure.'}
    if patch:
        proposed,_=apply_patch(focus['snapshot']['files'],patch)
        hashes={p:(hashlib.sha256(text.encode()).hexdigest() if text!=focus['snapshot']['files'][p] else focus['snapshot']['file_hashes'][p]) for p,text in proposed.items()}
        candidate=dict(focus['snapshot'],files=proposed,file_hashes=hashes)
        after=combine([build(candidate,e['repository_id'],e['name'],store) if e['repository_id']==focus_repository_id else g for e,g in zip(entries,graphs)])
        comparable=all(b['receipt'].get('status')==a['receipt'].get('status')=='PARSED' and all(b['receipt'].get(k)==a['receipt'].get(k) for k in ('enola_version','extractor_version','binary_sha256','policy')) for b,a in zip(graph['repositories'],after['repositories']))
        syntax_unknown=any(any(marker in u['reason'] for marker in ('syntax error','parse errors')) for u in graph['unknown']+after['unknown'])
        if not comparable or syntax_unknown:
            report['counterfactual']={'available':False,'comparable':False,'reason':'Structural delta withheld: parser failure, syntax errors or incompatible receipts leave proposal relationships unknown. Fix extraction before treating missing edges as removed.','unknown_after':after['unknown'][:200],'unknown_after_count':len(after['unknown'])}
            report['contract_alerts']=[]
        else:
            report['counterfactual']=dict(delta(graph,after),available=True,comparable=True,unknown_after=after['unknown'][:200],unknown_after_count=len(after['unknown']),evidence=after['evidence'],nodes=after['nodes'])
        # A disappearing cross-repo join is actionable evidence, but not a runtime failure claim.
        removed=[e for e in report['counterfactual'].get('removed_edges',[]) if e.get('cross_repository')]
        report['contract_alerts']=[{'severity':'REVIEW','title':'A previously linked consumer loses its contract match','source':e['source'],'consumer':e['target'],'evidence':e['evidence'],'basis':'Static / declared graph delta. Verify compatibility and deployment mapping.'} for e in removed]
    else: report['contract_alerts']=[]
    report['coverage']['uncovered_classes']=[n['id'] for n in report['impacted'] if n['kind'] in {'class','symbol','contract'} and not any(n['id'] in t['covers'] for t in report['selected_tests'])]
    report['coverage']['basis']='Existing static test references; selected tests were not executed. Declared and file-level paths are conservative review scope.'
    report['limitations']+=['All selected repositories are captured independently; unregistered repositories and deployed configuration remain outside this analysis.','No observed test coverage is inferred from file names or a generated BDD scenario.']
    return report

def inference_context(report, max_chars):
    evidence=report['graph']['evidence']; ids=[]
    for n in report['impacted']:
        ids+=n['evidence']
        for edge in n['via']: ids+=edge['evidence']
    for f in report['findings']: ids+=f['evidence']
    context={'intent':report['intent'],'mode':report['mode'],'entry_points':report['roots'],'findings':report['findings'],'patch_changes':[{k:v for k,v in c.items() if k!='excerpt'} for c in report['changes']],'evidence':[],'known_limitations':report['limitations']}
    context['coverage']=report['graph'].get('coverage_ledger',{})
    context['unresolved_relationships']=report['graph']['unknown'][:20]
    context['unresolved_total']=len(report['graph']['unknown'])
    if report.get('counterfactual',{}).get('available'):
        delta=report['counterfactual']
        context['dependency_rehearsal']={'added_count':delta['added_count'],'removed_count':delta['removed_count'],'unknown_after':delta['unknown_after_count'],'basis':delta['basis'],'contract_alerts':report.get('contract_alerts',[])}
    from .db import encode
    excerpts=[c['excerpt'] for c in report['changes'] if 'excerpt' in c]
    context['change_excerpts']=[dict(e,before=e['before'][:800],after=e['after'][:800]) for e in excerpts[:4]]
    context['omitted_change_excerpts']=max(0,len(excerpts)-4)
    allowed=[]
    for id in dict.fromkeys(ids):
        if id not in evidence: continue
        item=dict(evidence[id]); item['snippet']=item['snippet'][:4000]
        candidate=dict(context,evidence=context['evidence']+[item])
        if len(encode(candidate))>max_chars: continue
        context=candidate; allowed.append(id)
    # Finding citations may be omitted by the budget; model is told only available IDs count.
    context['allowed_evidence_ids']=allowed
    return context
