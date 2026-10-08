package bank.journey;
import bank.payments.PaymentService;
import bank.ledger.LedgerService;
import bank.reconciliation.ReconciliationService;
import bank.reporting.ReportingService;
import bank.contracts.*;
import java.math.BigDecimal;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;
class MoneyJourneyTest {
    @Test void amountIsConservedAcrossDownstreams() {
        var event = new PaymentService().create("p1", new BigDecimal("125.50"), "USD");
        var posting = new LedgerService().accept(event);
        var reconciliation = new ReconciliationService(); var reporting = new ReportingService();
        reporting.accept(reconciliation.accept(posting));
        assertEquals(0, new BigDecimal("125.50").compareTo(reporting.total()));
        assertEquals(0, reconciliation.total().compareTo(reporting.total()));
    }
    @Test void duplicatePaymentDoesNotDoubleCount() {
        var event = new PaymentService().create("p2", new BigDecimal("10.00"), "USD");
        var ledger = new LedgerService(); var reporting = new ReportingService();
        reporting.accept(ledger.accept(event)); reporting.accept(ledger.accept(event));
        assertEquals(0, new BigDecimal("10.00").compareTo(reporting.total()));
    }
    @Test void conflictingDuplicateIsRejected() {
        var payments = new PaymentService(); var ledger = new LedgerService();
        ledger.accept(payments.create("p3", new BigDecimal("1.00"), "USD"));
        assertThrows(IllegalArgumentException.class, () -> ledger.accept(payments.create("p3", new BigDecimal("2.00"), "USD")));
    }
    @Test void excessPrecisionIsRejected() {
        assertThrows(ArithmeticException.class, () -> new PaymentService().create("p4", new BigDecimal("1.001"), "USD"));
    }
    @Test void nonPositiveAmountIsRejected() {
        assertThrows(IllegalArgumentException.class, () -> new PaymentService().create("p5", BigDecimal.ZERO, "USD"));
    }
}
