package audit

type PaymentEvent struct { AmountMinor int64; Currency string }

func ConsumePayment(event PaymentEvent) int64 {
    // Deployment binding: demo-kafka / bank.payment.audit, synthetic-demo.
    return event.AmountMinor
}

func AuditSQL() string {
    return "INSERT INTO audit_rows (amount_minor) VALUES (?)"
}
