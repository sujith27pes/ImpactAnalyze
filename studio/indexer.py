"""Bounded read-only text capture, native Java adapter and safe in-memory diff validation."""
import hashlib, re, json, os, xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath
from tree_sitter import Language, Parser
import tree_sitter_java
from .db import digest

SKIP = {'.git', '.venv', 'venv', 'node_modules', 'vendor', 'target', 'build', 'dist', 'data', 'changes', '__pycache__', '.enola', '.impact-engine', '.gradle', '.next', '.tox', '.pytest_cache', 'obj', 'site-packages'}
INGEST_VERSION = 'polyglot-v4-any-text'
SECRET = re.compile(r'(?i)((?:api[_-]?key|password|secret|access[_-]?token)\s*[=:]\s*)[^\s,;]+')
def redact(text):
    # Preserve valid JSON while redacting quoted credential values.
    text=re.sub(r'(?i)("(?:api[_-]?key|password|secret|access[_-]?token)"\s*:\s*")[^"\n]*(")',r'\1[REDACTED]\2',text)
    text = SECRET.sub(r'\1[REDACTED]', text)
    text = re.sub(r'\b(?:nvapi-|sk-)[A-Za-z0-9_-]{12,}', '[REDACTED]', text)
    return re.sub(r'-----BEGIN [^-]*PRIVATE KEY-----[\s\S]*?-----END [^-]*PRIVATE KEY-----', '[REDACTED PRIVATE KEY]', text)

def capture(root):
    root = Path(root).resolve(strict=True)
    files, hashes, skipped, total = {}, {}, [], 0
    if not root.is_dir(): raise ValueError('Select a repository directory')
    paths=[]
    for directory, dirs, names in os.walk(root, followlinks=False):
        kept=[]
        for name in sorted(dirs):
            p=Path(directory)/name
            if name in SKIP or p.is_symlink():
                skipped.append({'path':p.relative_to(root).as_posix()+'/', 'reason':'symlink directory excluded' if p.is_symlink() else 'dependency / build / tool directory excluded'} )
            else: kept.append(name)
        dirs[:]=kept
        paths.extend(Path(directory)/name for name in sorted(names))
        if len(paths)>30000: raise ValueError('Repository exceeds traversal limit (30,000 files)')
    for path in sorted(paths):
        relative = path.relative_to(root)
        if any(part in SKIP for part in relative.parts): continue
        if path.is_symlink():
            skipped.append({'path': relative.as_posix(), 'reason': 'symlink excluded'}); continue
        if not path.is_file(): continue
        if re.search(r'(?i)(credential|secret|\.env|id_rsa)', path.name):
            skipped.append({'path':relative.as_posix(),'reason':'sensitive filename excluded'}); continue
        if not path.resolve().is_relative_to(root): raise ValueError('Repository path escapes root')
        if path.stat().st_size > 200_000:
            skipped.append({'path': relative.as_posix(), 'reason': 'file exceeds 200 KB'}); continue
        raw = path.read_bytes()
        if b'\x00' in raw:
            skipped.append({'path':relative.as_posix(),'reason':'binary content excluded'}); continue
        try: text = raw.decode('utf-8-sig').replace('\r\n','\n')
        except UnicodeDecodeError:
            skipped.append({'path': relative.as_posix(), 'reason': 'not UTF-8'}); continue
        total += len(raw)
        if total > 25_000_000 or len(files) >= 10000: raise ValueError('Repository exceeds configured index limit (25 MB / 10,000 captured files)')
        files[relative.as_posix()] = redact(text)
        hashes[relative.as_posix()] = hashlib.sha256(raw).hexdigest()
    # Refuse a hybrid snapshot when captured source changes during ingestion.
    for relative,expected in hashes.items():
        path=root/relative
        if path.is_symlink() or not path.resolve().is_relative_to(root) or hashlib.sha256(path.read_bytes()).hexdigest()!=expected:
            raise ValueError('Repository changed during capture; retry when source is stable')
    final_paths=[]
    for directory,dirs,names in os.walk(root,followlinks=False):
        dirs[:]=sorted(n for n in dirs if n not in SKIP and not (Path(directory)/n).is_symlink())
        final_paths.extend((Path(directory)/name).relative_to(root).as_posix() for name in names)
        if len(final_paths)>30000: raise ValueError('Repository changed beyond traversal limit during capture')
    if sorted(final_paths)!=sorted(p.relative_to(root).as_posix() for p in paths):
        raise ValueError('Repository file set changed during capture; retry when source is stable')
    return {'files': files, 'file_hashes': hashes, 'skipped': skipped, 'bytes': total, 'ingest_version':INGEST_VERSION}

def walk(node):
    yield node
    for child in node.named_children: yield from walk(child)

def build_java_index(snapshot):
    files = snapshot['files']; nodes, edges, evidence, unknown = [], [], {}, []
    modules = {}; ns = {'m':'http://maven.apache.org/POM/4.0.0'}
    def cite(path, start=1, end=None, basis='source'):
        lines = files[path].splitlines(); end = min(end or len(lines), len(lines)); start = max(1,start)
        id = 'E-' + digest([path,start,end,snapshot['file_hashes'].get(path),basis])[:14]
        evidence[id] = {'id':id,'path':path,'start':start,'end':end,'sha256':snapshot['file_hashes'].get(path),'basis':basis,'snippet':'\n'.join(lines[start-1:end])}
        return id
    for path, content in files.items():
        if not path.endswith('pom.xml'): continue
        if '<!DOCTYPE' in content or '<!ENTITY' in content:
            unknown.append({'path':path,'reason':'Maven XML DTD / entity declarations excluded; dependency parsing withheld'}); continue
        try: xml = ET.fromstring(content)
        except ET.ParseError:
            unknown.append({'path':path,'reason':'Invalid Maven XML'}); continue
        def value(tag): return xml.findtext('m:'+tag, namespaces=ns) or xml.findtext(tag) or ''
        module = value('artifactId')
        if not module: continue
        directory = str(PurePosixPath(path).parent)
        dependencies = [d.findtext('m:artifactId',namespaces=ns) or d.findtext('artifactId') for d in list(xml.findall('m:dependencies/m:dependency',ns))+list(xml.findall('dependencies/dependency'))]
        modules[module] = {'id':module,'directory':'' if directory=='.' else directory,'dependencies':dependencies,'evidence':cite(path,basis='Maven dependency declaration'),'port':None,'downstreams':{}}
    def module_for(path):
        matches = [m for m in modules.values() if not m['directory'] or path.startswith(m['directory']+'/')]
        return max(matches,key=lambda m:len(m['directory']))['id'] if matches else 'unassigned'
    for path, content in files.items():
        if path.endswith('.schema.json'):
            try:
                schema=json.loads(content)
                if isinstance(schema,dict): cite(path,basis='Declared JSON schema; not runtime validation evidence')
            except ValueError: unknown.append({'path':path,'reason':'Invalid JSON schema'})
        if path.endswith('.properties'):
            mod = modules.get(module_for(path))
            if not mod: continue
            for line in content.splitlines():
                if '=' not in line: continue
                key,val = [s.strip() for s in line.split('=',1)]
                if key=='server.port': mod['port']=val
                match = re.fullmatch(r'downstream\.(.+)\.url',key)
                if match: mod['downstreams'][match[1]]={'url':val,'evidence':cite(path,basis='HTTP endpoint configuration')}
    owners = {}
    if '.impact-owners.json' in files:
        try: owners=json.loads(files['.impact-owners.json'])
        except ValueError: pass
    for mod in modules.values():
        nodes.append({'id':'module:'+mod['id'],'label':mod['id'],'module':mod['id'],'kind':'module','evidence':[mod['evidence']],'owner':owners.get(mod['id'],'Unassigned')})
        for dependency in mod['dependencies']:
            if dependency in modules:
                edges.append({'source':'module:'+dependency,'target':'module:'+mod['id'],'kind':'BUILD_DEPENDENCY','evidence':[mod['evidence']],'basis':'Declared reactor dependency; coarse build impact'})
    parser = Parser(Language(tree_sitter_java.language())); classes=[]
    for path, text in files.items():
        if not path.endswith('.java'): continue
        raw=text.encode(); tree=parser.parse(raw); root=tree.root_node
        if root.has_error: unknown.append({'path':path,'reason':'Java parse errors: source edges may be incomplete'})
        def get(node): return raw[node.start_byte:node.end_byte].decode() if node else ''
        package_match=re.search(r'\bpackage\s+([\w.]+)\s*;',text); package=package_match[1] if package_match else ''
        imports=re.findall(r'\bimport\s+(?:static\s+)?([\w.*]+)\s*;',text)
        for cls in root.named_children:
            if cls.type not in {'class_declaration','record_declaration','interface_declaration','enum_declaration'}: continue
            name=get(cls.child_by_field_name('name')); id='class:'+package+'.'+name
            eid=cite(path,cls.start_point.row+1,cls.end_point.row+1,'Java syntax tree declaration')
            method_nodes=[n for n in walk(cls) if n.type=='method_declaration']
            methods=[{'name':get(n.child_by_field_name('name')),'start':n.start_point.row+1,'end':n.end_point.row+1,'test':bool(re.search(r'@Test\b',get(n)))} for n in method_nodes]
            node={'id':id,'label':name,'qualified_name':package+'.'+name,'module':module_for(path),'kind':'test' if '/src/test/' in path else 'class','path':path,'start':cls.start_point.row+1,'end':cls.end_point.row+1,'evidence':[eid],'owner':owners.get(module_for(path),'Unassigned'),'methods':methods}
            nodes.append(node)
            types={get(n).split('.')[-1] for n in walk(cls) if n.type=='type_identifier'}
            variables={}
            for n in walk(cls):
                if n.type in {'field_declaration','local_variable_declaration','formal_parameter'}:
                    typ=get(n.child_by_field_name('type')).split('<')[0].split('.')[-1]
                    name_node=n.child_by_field_name('name')
                    if name_node: variables[get(name_node)]=typ
                    for d in n.named_children:
                        if d.type=='variable_declarator': variables[get(d.child_by_field_name('name'))]=typ
            calls=[]
            for n in walk(cls):
                if n.type=='method_invocation':
                    obj=get(n.child_by_field_name('object')); method=get(n.child_by_field_name('name'))
                    if obj in variables: calls.append((variables[obj],method,n.start_point.row+1))
            routes = re.findall(r'@(Post|Get|Put|Delete|Patch)Mapping\s*\(\s*"([^"\n]+)"',get(cls))
            uris = [(verb.capitalize(),uri) for verb,uri in re.findall(r'\.(get|post|put|delete|patch|head|options)\s*\(\s*\)\s*\.uri\(\s*"([^"\n]+)"\s*\)',get(cls))]
            for literal in re.findall(r'\.uri\(\s*"([^"\n]+)"\s*\)',get(cls)):
                if literal not in [uri for _,uri in uris]: unknown.append({'path':path,'reason':'HTTP URI has no resolved literal verb: '+literal})
            classes.append({'node':node,'types':types,'package':package,'imports':imports,'calls':calls,'routes':routes,'uris':uris,'text':get(cls)})
    by_name={}
    for cls in classes: by_name.setdefault(cls['node']['label'],[]).append(cls)
    def resolve(typ, cls):
        matches=by_name.get(typ,[])
        explicit=[m for m in matches if m['node']['qualified_name'] in cls['imports'] or m['package']==cls['package'] or m['package']+'.*' in cls['imports']]
        return explicit[0] if len(explicit)==1 else None
    def edge(source,target,kind,eids,basis):
        if source!=target: edges.append({'source':source,'target':target,'kind':kind,'evidence':eids,'basis':basis})
    for cls in classes:
        node=cls['node']
        for typ in cls['types']:
            target=resolve(typ,cls)
            if target: edge(target['node']['id'],node['id'],'TYPE_USAGE',node['evidence']+target['node']['evidence'],'Imported / same-package Java type used in syntax tree; dependency → consumer')
            elif typ in by_name: unknown.append({'path':node['path'],'reason':'Ambiguous type resolution: '+typ})
        for typ,method,line in cls['calls']:
            target=resolve(typ,cls)
            if target:
                eid=cite(node['path'],line,line,'Receiver type resolved method call')
                edge(target['node']['id'],node['id'],'CALL_DEPENDENCY',[eid]+target['node']['evidence'],'Typed receiver call; callee change can affect caller')
                if node['label'].endswith('Controller'):
                    edge(node['id'],target['node']['id'],'REQUEST_DISPATCH',[eid]+target['node']['evidence'],'Controller forwards request to typed collaborator')
        for client_verb,uri in cls['uris']:
            mod=modules.get(node['module'],{}); downstreams=mod.get('downstreams',{})
            declared=re.findall(r'\$\{downstream\.(.+?)\.url\}',cls['text'])
            destinations=[]
            for target in classes:
                if any(route==uri and verb==client_verb for verb,route in target['routes']) and target['node']['module'] in declared and target['node']['module'] in downstreams:
                    url=downstreams[target['node']['module']]['url']; target_mod=modules[target['node']['module']]
                    if url.endswith(':'+str(target_mod['port'])): destinations.append(target)
            if len(destinations)==1:
                target=destinations[0]; config=downstreams[target['node']['module']]['evidence']
                edge(node['id'],target['node']['id'],'HTTP_ROUTE',node['evidence']+target['node']['evidence']+[config],'Literal '+client_verb.upper()+' URI + injected configured service + matching controller route / port')
            else: unknown.append({'path':node['path'],'reason':'Unresolved or ambiguous HTTP route: '+uri})
    unique={digest(e):e for e in edges}
    return {'nodes':nodes,'edges':list(unique.values()),'evidence':evidence,'modules':modules,'unknown':unknown,'skipped':snapshot.get('skipped',[]),'owners':owners,'stats':{'java_files':sum(p.endswith('.java') for p in files),'files':len(files),'classes':len(classes),'http_edges':sum(e['kind']=='HTTP_ROUTE' for e in unique.values())},'limitations':['Static evidence is not a complete runtime call graph. Reflection, profiles, generated code, event brokers and dynamic URIs need additional adapters.','Build dependencies are coarse and are shown separately from source impact.','Unreached means no path in captured evidence; it does not prove a system is unaffected.']}

def build_index(snapshot):
    from .graph import build
    return build(snapshot)

def apply_patch(files, patch):
    """Validate unified diff against captured content; apply only in memory."""
    if not patch.strip(): return dict(files), []
    if len(patch)>100_000: raise ValueError('Patch exceeds 100 KB')
    result=dict(files); changes=[]; lines=patch.replace('\r\n','\n').splitlines(True); i=0
    while i<len(lines):
        if not lines[i].startswith('--- '):
            if lines[i].startswith(('diff --git ','index ')) or not lines[i].strip(): i+=1; continue
            raise ValueError('Only existing-file textual unified diffs are supported')
        old=lines[i][4:].strip().split('\t')[0]; i+=1
        if i>=len(lines) or not lines[i].startswith('+++ '): raise ValueError('Missing new file header')
        new=lines[i][4:].strip().split('\t')[0]; i+=1
        old=old.removeprefix('a/'); new=new.removeprefix('b/')
        if old!=new or old not in result or '..' in PurePosixPath(old).parts or PurePosixPath(old).is_absolute(): raise ValueError('Patch must reference an existing safe snapshot path')
        source=result[old].splitlines(True); output=[]; cursor=0; hunks=0
        while i<len(lines) and not lines[i].startswith(('--- ','diff --git ','index ')):
            match=re.match(r'@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@',lines[i])
            if not match: raise ValueError('Malformed patch hunk')
            before_count=int(match[2] or 1); after_count=int(match[4] or 1)
            start=int(match[1])-(1 if before_count else 0); new_start=int(match[3])-(1 if after_count else 0); i+=1
            if start<cursor or start>len(source): raise ValueError('Patch hunks overlap or exceed source')
            output.extend(source[cursor:start]); cursor=start; removed=added=0; touched=[]
            if len(output)!=new_start: raise ValueError('Patch new-file offsets do not match prior hunks')
            while i<len(lines) and not lines[i].startswith(('@@ ','--- ','diff --git ','index ')):
                line=lines[i]; i+=1
                if line.startswith('\\ No newline'): raise ValueError('No-newline markers are not supported')
                if not line or line[0] not in ' +-': raise ValueError('Invalid patch line')
                content=line[1:]
                if line[0] in ' -':
                    if cursor>=len(source) or source[cursor]!=content: raise ValueError('Patch context does not match immutable snapshot')
                    if line[0]=='-': touched.append(cursor+1)
                    cursor+=1; removed+=1
                if line[0] in ' +':
                    if line[0]=='+': touched.append(max(1,cursor))
                    output.append(content); added+=1
            if (removed,added)!=(before_count,after_count): raise ValueError('Patch hunk counts do not match')
            changes.append({'path':old,'lines':sorted(set(touched)),'old_start':start+1,'new_start':new_start+1,'old_count':before_count,'new_count':after_count}); hunks+=1
        if not hunks: raise ValueError('Patch contains no hunks')
        output.extend(source[cursor:]); result[old]=''.join(output)
    if not changes: raise ValueError('Patch contains no supported changes')
    return result,changes
