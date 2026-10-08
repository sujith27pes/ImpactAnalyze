"""Evidence graph over immutable source, with separate dependency and execution views."""
import ast, json
from urllib.parse import urlsplit
from collections import Counter
from pathlib import PurePosixPath
from . import engine, contracts
from .db import digest

VERSION='knowledge-graph-v11'

def build(snapshot, repository_id='', name='Repository', store=None):
    key=digest({'namespace':'source-graph','version':VERSION,'engine':engine.fingerprint(),'repository_id':repository_id,'name':name,'content':snapshot['files'],'hashes':snapshot['file_hashes'],'skipped':snapshot.get('skipped',[])})
    if store:
        cached=store.graph_cached(key)
        if cached: return cached
    from .indexer import build_java_index
    graph=build_java_index(snapshot)
    files=snapshot['files']; evidence=graph['evidence']; nodes=graph['nodes']; edges=graph['edges']
    collisions={id for id,count in Counter(n['id'] for n in nodes).items() if count>1}
    if collisions:
        edges[:]=[e for e in edges if e['source'] not in collisions and e['target'] not in collisions]
        for node in nodes:
            if node['id'] in collisions:
                graph['unknown'].append({'path':node.get('path',''),'reason':'Duplicate Java qualified symbol identity; ambiguous edges withheld: '+node['id']})
                node['id']+=':'+digest(node.get('path',''))[:12]
    graph['execution_edges']=[]
    for edge in edges:
        edge['resolution']='STATIC_RULE'
        edge['direction']='request flow' if edge['kind'] in {'HTTP_ROUTE','REQUEST_DISPATCH'} else 'dependency change → consumer'
    def cite(path,line=1,end=None,basis='Captured source'):
        lines=files[path].splitlines(); line=max(1,min(line,max(1,len(lines)))); end=min(end or line+4,max(1,len(lines)))
        id='E-'+digest([path,line,end,snapshot['file_hashes'].get(path),basis])[:14]
        evidence[id]={'id':id,'path':path,'start':line,'end':end,'sha256':snapshot['file_hashes'].get(path),'basis':basis,'snippet':'\n'.join(lines[line-1:end])}
        return id
    file_nodes={}
    for path in files:
        file_nodes[path]='file:'+path
        nodes.append({'id':file_nodes[path],'label':path,'path':path,'start':1,'end':max(1,len(files[path].splitlines())),'kind':'file','module':name,'evidence':[cite(path,basis='Captured file; fallback change anchor')],'owner':'Unassigned','methods':[]})
    file_node_lookup={n['path']:n for n in nodes if n['kind']=='file'}
    for node in [n for n in nodes if n['kind'] in {'class','test','module'}]:
        path=node.get('path') or evidence[node['evidence'][0]]['path']
        if path not in file_nodes: continue
        if node['kind']=='module': node.update(path=path,start=1,end=max(1,len(files[path].splitlines())))
        edges.append({'source':file_nodes[path],'target':node['id'],'kind':'FILE_ANCHOR','evidence':node['evidence'],'basis':'Conservative source / manifest file fallback; not an execution relationship','resolution':'COARSE_FILE_SCOPE','direction':'changed file → declaration'})
        if node['kind'] in {'class','test'} and node['module'] in graph['modules']:
            module=graph['modules'][node['module']]
            edges.append({'source':'module:'+node['module'],'target':node['id'],'kind':'BUILD_MODULE_SCOPE','evidence':[module['evidence']]+node['evidence'],'basis':'Coarse Maven build scope; a changed module build includes its declarations and tests','resolution':'COARSE_BUILD_SCOPE','direction':'module build change → contained source'})
    parsed=engine.extract(snapshot); graph['parser_receipt']=parsed['receipt']
    if parsed['error']: graph['unknown'].append({'path':'Repository','reason':parsed['error']})
    if parsed['receipt'].get('quality',{}).get('parse_errors',0):
        graph['unknown'].append({'path':'Repository','reason':'Parser reports syntax errors; relationships may be missing. Count: '+str(parsed['receipt']['quality']['parse_errors'])})
    facts=parsed['facts']; by_fact={}; parsed_files=set(); symbol_positions={}
    spans={}; python_tests={}; python_trees={}
    for path,text in files.items():
        if not path.endswith('.py'): continue
        try:
            tree=ast.parse(text)
            python_trees[path]=tree
            spans[path]={n.lineno:n.end_lineno for n in ast.walk(tree) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef))}
            if PurePosixPath(path).name.startswith('test_') or any(p in {'tests','test'} for p in PurePosixPath(path).parts):
                python_tests[path]={n.lineno for n in ast.walk(tree) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name.startswith('test_')}
        except SyntaxError as exc:
            graph['unknown'].append({'path':path,'reason':'Python AST syntax error at line '+str(exc.lineno)+'; extraction may be incomplete'})
    for fact in facts:
        path=fact.get('file','').replace('\\','/')
        if path in files: parsed_files.add(path)
        if fact.get('kind')=='symbol': symbol_positions.setdefault(path,[]).append(fact.get('line',1))
    for fact in facts:
        path=fact.get('file','').replace('\\','/'); kind=fact.get('kind',''); fid=fact.get('id')
        if kind=='file_ref' and path in file_nodes and not path.endswith('.java'):
            by_fact[fid]=file_node_lookup[path]; continue
        if not fid or path not in files or path.endswith('.java'): continue
        if kind not in {'symbol','test_ref','route','storage','dependency','module','service'}: continue
        line=fact.get('line') or 1
        if not isinstance(line,int) or not 1<=line<=max(1,len(files[path].splitlines())):
            graph['unknown'].append({'path':path,'reason':'Parser fact has invalid source location; withheld'}); continue
        next_lines=[p for p in symbol_positions.get(path,[]) if p>line]
        end=spans.get(path,{}).get(line,min(next_lines)-1 if next_lines else max(1,len(files[path].splitlines())))
        props=fact.get('props') or {}; node_kind='test' if kind=='test_ref' or kind=='symbol' and line in python_tests.get(path,set()) else kind
        eid=cite(path,line,min(end,line+18),'Local '+kind+' extraction; '+str(props.get('language','unknown')))
        node={'id':'fact:'+fid,'label':fact.get('name',fid),'path':path,'start':line,'end':end,'kind':node_kind,'module':name,'evidence':[eid],'owner':'Unassigned','methods':[],'properties':props}
        if node_kind=='test': node['methods']=[{'name':node['label'],'test':True}]
        nodes.append(node); by_fact[fid]=node
        if node_kind in {'symbol','route','storage','test','module','service'}:
            edges.append({'source':file_nodes[path],'target':node['id'],'kind':'FILE_ANCHOR','evidence':[eid],'basis':'Conservative file fallback; not an execution relationship','resolution':'COARSE_FILE_SCOPE','direction':'changed file → declaration'})
    for fact in facts:
        source=by_fact.get(fact.get('id'))
        if not source: continue
        for rel in fact.get('relations') or []:
            kind=rel.get('kind'); target=by_fact.get(rel.get('target_id'))
            if kind not in {'calls','imports','implements','depends_on','instantiates','injects','handled_by','has_method'}: continue
            if not target:
                graph['unknown'].append({'path':source['path'],'reason':'Unresolved '+str(kind)+': '+str(rel.get('target','?')),'source_id':source['id']}); continue
            eids=source['evidence']+target['evidence']
            edges.append({'source':target['id'],'target':source['id'],'kind':'PARSER_'+kind.upper(),'evidence':eids,'basis':'Local parser target_id resolution; static relationship, not measured runtime','resolution':'PARSER_RESOLVED','direction':'dependency change → consumer'})
            if kind in {'calls','handled_by'}:
                graph['execution_edges'].append({'source':source['id'],'target':target['id'],'kind':kind.upper(),'evidence':eids,'basis':'Separate static execution / dispatch view','resolution':'PARSER_RESOLVED'})
    # Narrow HTTP test adapter: explicit TestClient(imported_app).verb(literal_url).
    # Naming identifies test roles; coverage requires the actual request and bound app.
    for path,tree in python_trees.items():
        imports={}; testclient=False
        for statement in tree.body:
            if isinstance(statement,ast.ImportFrom):
                for alias in statement.names: imports[alias.asname or alias.name]=statement.module
                if statement.module in {'fastapi.testclient','starlette.testclient'} and any(a.name=='TestClient' and not a.asname for a in statement.names): testclient=True
        if not testclient: continue
        for test in [n for n in nodes if n['kind']=='test' and n['path']==path]:
            function=next((n for n in ast.walk(tree) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.lineno==test['start']),None)
            if not function: continue
            for call in ast.walk(function):
                if not isinstance(call,ast.Call) or not isinstance(call.func,ast.Attribute): continue
                receiver=call.func.value
                if not isinstance(receiver,ast.Call) or not isinstance(receiver.func,ast.Name) or receiver.func.id!='TestClient' or not receiver.args: continue
                app=receiver.args[0]
                if not isinstance(app,ast.Name) or app.id not in imports or not call.args or not isinstance(call.args[0],ast.Constant) or not isinstance(call.args[0].value,str): continue
                module=imports[app.id] or ''; candidates=[module.replace('.','/')+'.py',str(PurePosixPath(path).parent/(module.replace('.','/')+'.py'))]
                target_files={p for p in candidates if p in files}
                routes=[n for n in nodes if n['kind']=='route' and n['path'] in target_files and n['properties'].get('method','').upper()==call.func.attr.upper() and contracts.route_matches(n['properties'].get('path',n['label']),urlsplit(call.args[0].value).path)]
                if len(routes)==1:
                    route=routes[0]; eid=cite(path,call.lineno,basis='Static test HTTP request bound to imported app; not executed coverage')
                    edges.append({'source':route['id'],'target':test['id'],'kind':'HTTP_TEST_REFERENCE','evidence':route['evidence']+[eid],'basis':'Literal test verb + route + explicitly imported TestClient app','resolution':'STATIC_RULE','direction':'endpoint change → existing test'})
    declaration=contracts.load(snapshot,graph['unknown'])
    if declaration:
        graph['owners'][name]=declaration.owner
        for i,c in enumerate(declaration.contracts):
            eid=cite(c.file,c.line,basis='Owner-declared contract source association; validate against source')
            meta=cite('.impact-contracts.json',1,min(40,len(files['.impact-contracts.json'].splitlines())),basis='Explicit scoped contract declaration; not runtime validation')
            node={'id':'contract:'+digest([c.protocol,c.role,c.resource,c.scope,c.environment,declaration.service,c.file])[:20],'label':c.protocol.upper()+' '+c.method+' '+c.resource,'path':c.file,'start':c.line,'end':c.line,'kind':'contract','module':name,'service':declaration.service,'owner':declaration.owner,'contract':c.model_dump(by_alias=True),'evidence':[eid,meta],'methods':[]}
            node['source_validation']='DECLARED_ONLY'
            if c.protocol=='http' and c.role=='provides':
                routes=[n for n in nodes if n['kind']=='route' and n['path']==c.file and n['properties'].get('role')=='server']
                matching=[n for n in routes if n['properties'].get('method','').upper()==c.method and n['properties'].get('path',n['label'])==c.resource]
                if matching:
                    node['source_validation']='SOURCE_CORROBORATED'; node['evidence']+=matching[0]['evidence']
                elif routes:
                    node['source_validation']='SOURCE_CONTRADICTION'
                    graph['unknown'].append({'path':c.file,'reason':'Declared HTTP provider contradicts parsed routes; cross-repository join withheld: '+c.method+' '+c.resource})
            nodes.append(node)
            edges.append({'source':file_nodes[c.file],'target':node['id'],'kind':'DECLARED_CONTRACT_ASSOCIATION','evidence':node['evidence'],'basis':'Owner-declared association to changed file; validate before approval','resolution':'DECLARED','direction':'changed file → associated contract'})
            # Inbound contracts affect implementation; outbound changes affect their consumers.
            if c.role in {'provides','subscribes','reads','consumes'}:
                edges.append({'source':node['id'],'target':file_nodes[c.file],'kind':'DECLARED_IMPLEMENTATION_ASSOCIATION','evidence':node['evidence'],'basis':'Owner-declared implementation association; conservative file scope','resolution':'DECLARED','direction':'contract impact → implementation file'})
    for node in nodes: node.setdefault('path',''); node.setdefault('methods',[]); node.setdefault('owner',graph['owners'].get(node['module'],'Unassigned'))
    languages=Counter(engine.LANGUAGES.get(PurePosixPath(p).suffix,'Other / configuration') for p in files)
    configuration={'.json','.yaml','.yml','.xml','.toml','.properties','.md','.feature','.gradle','.mod','.sum','.lock','.csproj','.fsproj','.vbproj','.sln','.slnx','.props','.targets','.gemspec','.sbt','.wsdl','.xsd','.config'}
    unsupported=[p for p in files if p not in parsed_files and PurePosixPath(p).suffix not in engine.LANGUAGES and PurePosixPath(p).suffix not in configuration]
    for path in unsupported:
        graph['unknown'].append({'path':path,'reason':'No source parser adapter for this format; internal dependencies unknown. Explicit scoped contracts can provide declared relationships.'})
    graph['coverage_ledger']={'captured_files':len(files),'files_with_parser_facts':len(parsed_files),'files_without_parser_facts':sorted(set(files)-parsed_files),'languages':dict(sorted(languages.items())),'unsupported_source_files':unsupported,'skipped_count':len(snapshot.get('skipped',[])),'note':'A fact in a file does not establish that every call was resolved. Missing facts and unsupported formats remain unknown.'}
    graph['limitations']=['Static and declared edges are evidence with different strengths; neither is complete runtime coverage.','Cross-repository discovery requires loaded consumers and deployment-scoped contracts. External consumers remain unknown.','Reflection, generated code, aliases, dynamic routing, runtime configuration and unsupported frameworks can leave gaps.','File fallback and declared associations are conservative review scope, not proven execution paths.','Unreached never means safe. No automatic release approval or repository code execution.']
    graph['repository_id']=repository_id; graph['repository_name']=name
    if repository_id:
        node_ids={n['id']:repository_id+'::'+n['id'] for n in nodes}
        evidence_ids={eid:'E-'+digest([repository_id,eid])[:20] for eid in evidence}
        graph['evidence']={evidence_ids[eid]:dict(e,id=evidence_ids[eid],repository_id=repository_id,repository=name) for eid,e in evidence.items()}
        for module in graph['modules'].values():
            module['evidence']=evidence_ids[module['evidence']]
            for downstream in module.get('downstreams',{}).values(): downstream['evidence']=evidence_ids[downstream['evidence']]
        graph['skipped']=[dict(item,repository_id=repository_id,repository=name) for item in graph['skipped']]
        for node in nodes:
            node['id']=node_ids[node['id']]; node['evidence']=[evidence_ids[eid] for eid in node['evidence']]; node['repository_id']=repository_id; node['repository']=name
        for edge in edges+graph['execution_edges']:
            edge['source']=node_ids[edge['source']]; edge['target']=node_ids[edge['target']]; edge['evidence']=[evidence_ids[eid] for eid in edge['evidence']]
        for item in graph['unknown']:
            item['repository_id']=repository_id
            if item.get('source_id') in node_ids: item['source_id']=node_ids[item['source_id']]
    else:
        for node in nodes: node['repository_id']=''; node['repository']=name
    graph['nodes']=list({n['id']:n for n in nodes}.values())
    graph['edges']=list({digest([e['source'],e['target'],e['kind']]):e for e in edges}.values())
    graph['stats'].update(nodes=len(nodes),edges=len(graph['edges']),languages=len(languages))
    graph['graph_version']=VERSION
    if store: store.put_graph_cache(key,graph)
    return graph

def combine(graphs):
    result={'nodes':[],'edges':[],'execution_edges':[],'evidence':{},'unknown':[],'skipped':[],'modules':{},'owners':{},'stats':{},'limitations':[],'repositories':[],'graph_version':VERSION}
    for graph in graphs:
        for key in ('nodes','edges','execution_edges','unknown','skipped'): result[key]+=graph.get(key,[])
        result['evidence'].update(graph['evidence']); result['owners'].update({graph['repository_id']+'::'+key:owner for key,owner in graph['owners'].items()})
        for mid,module in graph['modules'].items(): result['modules'][graph['repository_id']+'::'+mid]=module
        result['limitations']+=graph['limitations']
        result['repositories'].append({'id':graph['repository_id'],'name':graph['repository_name'],'coverage':graph['coverage_ledger'],'receipt':graph['parser_receipt']})
    contracts.join(result)
    result['limitations']=list(dict.fromkeys(result['limitations']))
    result['stats']={'nodes':len(result['nodes']),'edges':len(result['edges']),'files':sum(g['stats']['files'] for g in graphs),'http_edges':sum(g['stats']['http_edges'] for g in graphs),'cross_repository_edges':sum(bool(e.get('cross_repository')) for e in result['edges'])}
    result['coverage_ledger']={'repositories':len(graphs),'captured_files':result['stats']['files'],'unresolved_relationships':len(result['unknown']),'languages':dict(sum((Counter(g['coverage_ledger']['languages']) for g in graphs),Counter()))}
    return result

def delta(before,after):
    def key(edge): return digest([edge['source'],edge['target'],edge['kind']])
    b={key(e):e for e in before['edges']}; a={key(e):e for e in after['edges']}
    added=[a[k] for k in sorted(a.keys()-b.keys())]; removed=[b[k] for k in sorted(b.keys()-a.keys())]
    return {'added_edges':added[:200],'removed_edges':removed[:200],'added_count':len(added),'removed_count':len(removed),'truncated':len(added)>200 or len(removed)>200,'basis':'In-memory proposal under the same parser and join policy; source/declared relationships, not observed runtime','policy_fingerprint':engine.fingerprint()}
