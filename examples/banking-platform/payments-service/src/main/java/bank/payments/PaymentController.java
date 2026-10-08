package bank.payments;
import bank.contracts.Posting;
import java.math.BigDecimal;
import org.springframework.web.bind.annotation.*;
@RestController
public class PaymentController {
    private final PaymentService service;
    private final LedgerClient ledger;
    public PaymentController(PaymentService service, LedgerClient ledger) { this.service=service; this.ledger=ledger; }
    public record Request(String paymentId, BigDecimal amount, String currency) {}
    @PostMapping("/payments")
    public Posting pay(@RequestBody Request request) { return ledger.send(service.create(request.paymentId(), request.amount(), request.currency())); }
}
