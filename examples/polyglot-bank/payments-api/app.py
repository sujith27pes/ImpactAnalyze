from decimal import Decimal
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
