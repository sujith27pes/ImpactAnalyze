"""Create an authored, synthetic cross-language inference fixture; no customer data."""
import difflib, json
from pathlib import Path

BASE=Path(__file__).resolve().parents[1]/'examples/polyglot-bank'
sources={
'payments-api/app.py':'''from decimal import Decimal
from fastapi import FastAPI

app = FastAPI()
audit_events = []

def minor_units(amount: Decimal) -> int:
    return int(amount * 100)

@app.post("/payments")
def accept(amount: Decimal):
    event = {"amountMinor": minor_units(amount), "currency": "USD"}
    audit_events.append(event)
    return event

def posting_sql():
    return "INSERT INTO ledger_postings (amount_minor) VALUES (:amount)"
''',
'payments-api/test_app.py':'''from decimal import Decimal
from fastapi.testclient import TestClient
from app import app, minor_units, accept

def test_minor_units():
    assert minor_units(Decimal("125.50")) == 12550

def test_consumer_endpoint():
    response = TestClient(app).post("/payments?amount=125.50")
    assert response.status_code == 200
    assert response.json()["amountMinor"] == 12550

def test_audit_value():
    assert accept(Decimal("125.50"))["currency"] == "USD"
''',
'payments-api/requirements.txt':'fastapi\n',
'customer-web/client.ts':'''export async function submitPayment(amount: string) {
  const response = await fetch("http://payments.demo:9000/payments?amount=" + amount, { method: "POST" });
  if (!response.ok) throw new Error("Payment was rejected");
  return response.json();
}
''',
'customer-web/package.json':json.dumps({'name':'customer-web','private':True,'version':'1.0.0'},indent=2)+'\n',
'audit-worker/main.go':'''package audit

type PaymentEvent struct { AmountMinor int64; Currency string }

func ConsumePayment(event PaymentEvent) int64 {
    // Deployment binding: demo-kafka / bank.payment.audit, synthetic-demo.
    return event.AmountMinor
}

func AuditSQL() string {
    return "INSERT INTO audit_rows (amount_minor) VALUES (?)"
}
''',
'audit-worker/go.mod':'module synthetic.bank/audit\n\ngo 1.22\n',
'analytics/report.sql':'''-- Deployment database: demo-bank-db; synthetic-demo only.
SELECT SUM(amount_minor) / 100.0 AS posted_major FROM ledger_postings;
SELECT SUM(amount_minor) / 100.0 AS audited_major FROM audit_rows;
'''
}
def contract(protocol,role,file,resource,scope,line=1,**extra):
    return {'protocol':protocol,'role':role,'file':file,'line':line,'resource':resource,'scope':scope,'environment':'synthetic-demo',**extra}
declarations={
'payments-api':{'service':'payments','owner':'Payments engineering','contracts':[
contract('http','provides','app.py','/payments','http://payments.demo:9000',10,method='POST'),
contract('event','publishes','app.py','bank.payment.audit','demo-kafka',12,schema='payment-event-v1'),
contract('database','writes','app.py','ledger_postings','demo-bank-db',17)]},
'customer-web':{'service':'customer-web','owner':'Digital channels','contracts':[
contract('http','consumes','client.ts','/payments','http://payments.demo:9000',2,method='POST')]},
'audit-worker':{'service':'audit-worker','owner':'Audit engineering','contracts':[
contract('event','subscribes','main.go','bank.payment.audit','demo-kafka',5,schema='payment-event-v1'),
contract('database','writes','main.go','audit_rows','demo-bank-db',10)]},
'analytics':{'service':'analytics','owner':'Finance reporting','contracts':[
contract('database','reads','report.sql','ledger_postings','demo-bank-db',2),
contract('database','reads','report.sql','audit_rows','demo-bank-db',3)]}
}
for repo,decl in declarations.items(): sources[repo+'/.impact-contracts.json']=json.dumps({'version':1,**decl},indent=2)+'\n'
for path,text in sources.items():
    target=BASE/path; target.parent.mkdir(parents=True,exist_ok=True); target.write_text(text,encoding='utf-8',newline='')
patch=''
for path in ['payments-api/app.py','payments-api/.impact-contracts.json']:
    old=sources[path]; new=old.replace('"/payments"','"/payments/v2"')
    relative=path.removeprefix('payments-api/')
    patch+=''.join(difflib.unified_diff(old.splitlines(True),new.splitlines(True),fromfile='a/'+relative,tofile='b/'+relative))
(BASE/'endpoint-v2.patch').write_text(patch,encoding='utf-8',newline='')
(BASE/'README.md').write_text('''# Synthetic polyglot banking workspace

Four independent source repositories: Python payment API, TypeScript web consumer,
Go audit worker, SQL reporting. These are inference fixtures, not deployed systems.

Scoped owner declarations join HTTP, Kafka event and database relationships. They
are explicit reviewable assumptions, not execution evidence. SQL-only source can
be captured and connected through declarations even when the parser emits no facts.

The proposal renames the payment endpoint. The web consumer loses its HTTP contract
match while the audit and reporting paths remain in review scope. The independent
authored Python test runner demonstrates the HTTP compatibility regression.

Run `python scripts/verify_polyglot.py` from the platform root to execute only this
authored fixture in disposable copies. The platform never executes analyzed code.
''',encoding='utf-8')
print('Created four synthetic repositories and a validated endpoint-change proposal.')
