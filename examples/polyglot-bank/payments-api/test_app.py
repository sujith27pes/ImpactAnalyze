from decimal import Decimal
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
