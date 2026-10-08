"""Execute ONLY the authored fixture, never an API-supplied repository."""
import json, shutil, subprocess, sys, tempfile, time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from studio.config import ROOT
from studio.indexer import capture, apply_patch
from studio.db import digest

def main():
    fixture=ROOT/'examples/polyglot-bank/payments-api'; snapshot=capture(fixture)
    patch=(fixture.parent/'endpoint-v2.patch').read_text(encoding='utf-8')
    modified,_=apply_patch(snapshot['files'],patch); results=[]
    fixed=dict(modified); fixed['test_app.py']=fixed['test_app.py'].replace('/payments?','/payments/v2?')
    for scenario,files,expected in [('Baseline',snapshot['files'],True),('Producer endpoint only',modified,False),('Consumer expectation migrated',fixed,True)]:
        with tempfile.TemporaryDirectory(prefix='authored-polyglot-test-') as folder:
            root=Path(folder)
            for name,text in files.items():
                target=root/name; target.parent.mkdir(parents=True,exist_ok=True); target.write_text(text,encoding='utf-8',newline='')
            result=subprocess.run([sys.executable,'-X','utf8','-m','pytest','-q','test_app.py','--junitxml=result.xml'],cwd=root,capture_output=True,text=True,timeout=60)
            import xml.etree.ElementTree as ET
            suite=ET.parse(root/'result.xml').getroot().find('testsuite')
            passed=result.returncode==0
            results.append({'scenario':scenario,'tests':int(suite.get('tests')),'failures':int(suite.get('failures')),'errors':int(suite.get('errors')),'passed':passed,'expectation_verified':passed==expected,'source_fingerprint':digest({p:text for p,text in files.items()})})
            print(scenario,results[-1])
    data={'created':time.time(),'fixture_fingerprint':digest(snapshot['file_hashes']),'patch_fingerprint':digest(patch),'scope':'Authored Python endpoint test in disposable copies; Go/TypeScript/SQL execution not claimed','results':results}
    out=ROOT/'data/polyglot-verification/results.json';out.parent.mkdir(exist_ok=True,parents=True);out.write_text(json.dumps(data,indent=2),encoding='utf-8')
    if not all(r['expectation_verified'] for r in results): raise SystemExit('Unexpected fixture outcome')

if __name__=='__main__':main()
