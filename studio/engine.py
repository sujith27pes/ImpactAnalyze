"""Pinned, local parser adapter. Never execute source, providers or repository hooks."""
import hashlib, json, os, subprocess, sys, tempfile
from functools import lru_cache
from pathlib import Path, PurePosixPath
from .db import digest

VERSION = '0.4.26'
POLICY = 'enola-safe-v3'
# Do not materialize configuration that can name commands, hooks or agent instructions.
CONTROL = {'mcp-arch.yaml', 'cluster.yaml', 'enola-intent.yaml', 'AGENTS.md', 'CLAUDE.md'}
LANGUAGES = {'.py':'Python','.pyi':'Python','.js':'JavaScript','.jsx':'JavaScript','.mjs':'JavaScript','.cjs':'JavaScript','.ts':'TypeScript','.tsx':'TypeScript','.java':'Java','.kt':'Kotlin','.kts':'Kotlin','.go':'Go','.rs':'Rust','.cs':'C#','.fs':'F#','.vb':'Visual Basic','.scala':'Scala','.swift':'Swift','.dart':'Dart','.rb':'Ruby','.php':'PHP','.c':'C','.h':'C/C++','.cpp':'C++','.cc':'C++','.hpp':'C++','.proto':'Protobuf/gRPC','.tf':'Terraform/HCL','.hcl':'Terraform/HCL','.graphql':'GraphQL','.gql':'GraphQL','.vue':'Vue','.svelte':'Svelte','.razor':'Razor'}

@lru_cache(maxsize=1)
def identity():
    binary = Path(sys.executable).parent / ('enola.exe' if os.name=='nt' else 'enola')
    if not binary.is_file(): return {'status':'UNAVAILABLE','policy':POLICY,'version':VERSION}
    fingerprint=hashlib.sha256(binary.read_bytes()).hexdigest()
    try:
        result=subprocess.run([str(binary),'--version'],env={**os.environ,'ENOLA_NO_UPDATE_CHECK':'1'},capture_output=True,text=True,timeout=10)
        if result.returncode or (result.stdout+result.stderr).strip()!='enola version '+VERSION:
            return {'status':'VERSION_MISMATCH','policy':POLICY,'version':VERSION,'binary_sha256':fingerprint}
    except (OSError,subprocess.TimeoutExpired): return {'status':'UNAVAILABLE','policy':POLICY,'version':VERSION}
    return {'status':'READY','policy':POLICY,'version':VERSION,'binary_sha256':fingerprint,'binary':str(binary)}

def fingerprint():
    return digest({k:v for k,v in identity().items() if k!='binary'})

def extract(snapshot):
    engine={k:v for k,v in identity().items() if k!='binary'}
    if engine['status']!='READY': return {'facts':[],'receipt':engine,'error':'Local parser unavailable; file evidence only. Install the pinned requirements.'}
    try:
        with tempfile.TemporaryDirectory(prefix='impact-parser-') as directory:
            base=Path(directory); root=base/'repo'; root.mkdir()
            materialized={}
            for path,text in snapshot['files'].items():
                relative=PurePosixPath(path)
                if relative.is_absolute() or '..' in relative.parts or '\\' in path or ':' in path: raise ValueError('Unsafe snapshot path')
                if relative.name in CONTROL or any(p in {'.git','.claude','.codex','.github','.cursor','.pi','.opencode'} for p in relative.parts): continue
                target=root/path; target.parent.mkdir(parents=True,exist_ok=True); target.write_text(text,encoding='utf-8',newline='')
                materialized[path]=hashlib.sha256(text.encode()).hexdigest()
            config={'repo':str(root),'ignore':[], 'providers':[], 'history':{'enabled':False}, 'incremental':False,'output':{'dir':'.impact-engine','max_context_tokens':1000}}
            config_path=base/'engine.yaml'; config_path.write_text(json.dumps(config),encoding='utf-8')
            # The engine sees only captured, redacted source. Absolute binary and argv avoid shells.
            with (base/'parser.log').open('wb') as log:
                result=subprocess.run([identity()['binary'],'--generate','--no-cluster',str(config_path)],cwd=base,env={**os.environ,'ENOLA_NO_UPDATE_CHECK':'1'},stdout=subprocess.DEVNULL,stderr=log,timeout=90)
            output=root/'.impact-engine'; facts_path=output/'facts.jsonl'; receipt_path=output/'receipt.json'
            if result.returncode or not facts_path.is_file() or not receipt_path.is_file():
                return {'facts':[],'receipt':dict(engine,status='NO_FACTS'),'error':'Parser produced no usable facts. This is an unknown result, not isolation.'}
            if facts_path.stat().st_size>40_000_000: raise ValueError('Parser output exceeds 40 MB limit')
            receipt=json.loads(receipt_path.read_text(encoding='utf-8')); raw=facts_path.read_bytes()
            actual='sha256:'+hashlib.sha256(raw).hexdigest()
            if receipt.get('enola_version')!=VERSION or receipt.get('output_hashes',{}).get('facts.jsonl')!=actual: raise ValueError('Parser receipt mismatch')
            facts=[json.loads(line) for line in raw.decode('utf-8').splitlines() if line.strip()]
            if len(facts)>100000 or receipt.get('fact_count')!=len(facts): raise ValueError('Parser fact count / limit mismatch')
            safe_receipt={k:receipt.get(k) for k in ('format_version','enola_version','extractor_version','extractors','quality','fact_count')}
            safe_receipt.update(engine,status='PARSED',facts_sha256=actual,source_fingerprint=digest(snapshot['file_hashes']),materialized_fingerprint=digest(materialized))
            return {'facts':facts,'receipt':safe_receipt,'error':None}
    except (subprocess.TimeoutExpired,OSError,ValueError,json.JSONDecodeError) as exc:
        return {'facts':[],'receipt':dict(engine,status='FAILED'),'error':'Parser '+type(exc).__name__+'; dependency completeness is unknown.'}
