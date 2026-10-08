package bank.reconciliation;
import bank.contracts.Posting;
import org.springframework.web.bind.annotation.*;
@RestController
public class ReconciliationController {
    private final ReconciliationService service;
    private final ReportingClient downstream;
    public ReconciliationController(ReconciliationService service, ReportingClient downstream) { this.service=service; this.downstream=downstream; }
    @PostMapping("/reconciliation/postings")
    public Posting accept(@RequestBody Posting event) { return downstream.send(service.accept(event)); }
    @GetMapping("/reconciliation/total") public java.math.BigDecimal total() { return service.total(); }
}
