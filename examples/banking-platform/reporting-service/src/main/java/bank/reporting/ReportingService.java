package bank.reporting;
import bank.contracts.Posting;
import java.math.BigDecimal;
import java.util.LinkedHashMap;
import java.util.Map;
import org.springframework.stereotype.Service;
@Service
public class ReportingService {
    private final Map<String, Posting> postings = new LinkedHashMap<>();
    public synchronized Posting accept(Posting posting) {
        Posting existing = postings.get(posting.paymentId());
        if (existing != null && !existing.equals(posting)) throw new IllegalArgumentException("Conflicting duplicate");
        postings.putIfAbsent(posting.paymentId(), posting);
        return posting;
    }
    public synchronized BigDecimal total() { return postings.values().stream().map(Posting::amountMajor).reduce(BigDecimal.ZERO, BigDecimal::add); }
}
