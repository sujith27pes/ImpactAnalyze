"""Execute only our authored fixture in disposable copies; never run a registered repository."""
import shutil, subprocess, json, sys, tempfile
from pathlib import Path
from xml.etree import ElementTree as ET
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from studio.config import ROOT
from studio.indexer import apply_patch, capture
from studio.db import digest
import time

fixture=ROOT/'examples/banking-platform'
work=ROOT/'data/verification'; work.mkdir(parents=True,exist_ok=True)
repo=next((arg.split('=',1)[1] for arg in sys.argv if arg.startswith('--maven-repo=')),None)
mvn=shutil.which('mvn')
if not mvn: raise SystemExit('Maven is required to verify this authored fixture.')
results=[]
for label,patches,expected in [('baseline',[],True),('producer-only-change',['major-unit.patch'],False),('producer-and-consumer-fix',['major-unit.patch','ledger-unit-fix.patch'],True)]:
    directory=Path(tempfile.mkdtemp(prefix=label+'-',dir=work))
    shutil.copytree(fixture,directory,dirs_exist_ok=True,ignore=shutil.ignore_patterns('target'))
    files={p.relative_to(directory).as_posix():p.read_text(encoding='utf-8') for p in directory.rglob('*.java')}
    for patch in patches: files,_=apply_patch(files,(fixture/'changes'/patch).read_text(encoding='utf-8'))
    for path,text in files.items(): (directory/path).write_text(text,encoding='utf-8',newline='\n')
    command=[mvn,'-B','test']
    if repo: command+=['-o','-Dmaven.repo.local='+str(Path(repo).resolve())]
    process=subprocess.run(command,cwd=directory,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace')
    (work/(label+'.log')).write_text(process.stdout,encoding='utf-8')
    suites=[ET.parse(p).getroot() for p in directory.rglob('TEST-*.xml')]
    tests=sum(int(s.get('tests','0')) for s in suites); failures=sum(int(s.get('failures','0')) for s in suites); errors=sum(int(s.get('errors','0')) for s in suites)
    verified=tests>=5 and errors==0 and ((process.returncode==0 and failures==0) if expected else (process.returncode!=0 and failures>0))
    result={'scenario':label,'passed':process.returncode==0,'tests':tests,'failures':failures,'errors':errors,'expectation_verified':verified,'suite':'MoneyJourneyTest','patches':patches,'disposable_copy':str(directory)}
    results.append(result); print(json.dumps(result),flush=True)
(work/'results.json').write_text(json.dumps({'created':time.time(),'fixture_fingerprint':digest(capture(fixture)['file_hashes']),'patch_fingerprints':{p.name:digest(p.read_text(encoding='utf-8')) for p in (fixture/'changes').glob('*.patch')},'results':results},indent=2),encoding='utf-8')
if not all(r['expectation_verified'] for r in results): raise SystemExit('Fixture verification did not meet expectations; inspect data/verification/*.log')
