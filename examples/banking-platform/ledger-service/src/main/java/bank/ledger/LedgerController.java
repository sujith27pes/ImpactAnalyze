package bank.ledger;
import bank.contracts.PaymentEvent;
import bank.contracts.Posting;
import org.springframework.web.bind.annotation.*;
@RestController
public class LedgerController {
    private final LedgerService service;
    private final ReconciliationClient downstream;
    public LedgerController(LedgerService service, ReconciliationClient downstream) { this.service=service; this.downstream=downstream; }
    @PostMapping("/ledger/postings")
    public Posting accept(@RequestBody PaymentEvent event) { return downstream.send(service.accept(event)); }
    
}
