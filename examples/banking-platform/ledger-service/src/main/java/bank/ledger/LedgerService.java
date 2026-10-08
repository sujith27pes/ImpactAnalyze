package bank.ledger;
import bank.contracts.PaymentEvent;
import bank.contracts.Posting;
import java.math.BigDecimal;
import java.util.LinkedHashMap;
import java.util.Map;
import org.springframework.stereotype.Service;
@Service
public class LedgerService {
    private final Map<String, Posting> postings = new LinkedHashMap<>();
    public synchronized Posting accept(PaymentEvent event) {
        BigDecimal amountMajor = event.amount().movePointLeft(2);
        Posting candidate = new Posting(event.paymentId(), amountMajor, event.currency());
        Posting existing = postings.get(event.paymentId());
        if (existing != null && !existing.equals(candidate)) throw new IllegalArgumentException("Conflicting duplicate");
        if (existing != null) return existing;
        postings.put(event.paymentId(), candidate);
        return candidate;
    }
}
