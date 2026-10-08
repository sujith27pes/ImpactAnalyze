package bank.reporting;
import bank.contracts.Posting;
import org.springframework.web.bind.annotation.*;
@RestController
public class ReportingController {
    private final ReportingService service;
    
    public ReportingController(ReportingService service) { this.service=service;  }
    @PostMapping("/reports/postings")
    public Posting accept(@RequestBody Posting event) { return service.accept(event); }
    @GetMapping("/reporting/total") public java.math.BigDecimal total() { return service.total(); }
}
