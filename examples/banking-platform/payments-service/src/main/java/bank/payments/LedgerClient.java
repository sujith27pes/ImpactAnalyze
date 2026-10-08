package bank.payments;
import bank.contracts.PaymentEvent;
import bank.contracts.Posting;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;
@Component
public class LedgerClient {
    private final RestClient http;
    public LedgerClient(@Value("${downstream.ledger-service.url}") String url) { this.http = RestClient.create(url); }
    public Posting send(PaymentEvent event) { return http.post().uri("/ledger/postings").body(event).retrieve().body(Posting.class); }
}
