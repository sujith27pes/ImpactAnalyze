package bank.ledger;
import bank.contracts.Posting;
import bank.contracts.Posting;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;
@Component
public class ReconciliationClient {
    private final RestClient http;
    public ReconciliationClient(@Value("${downstream.reconciliation-service.url}") String url) { this.http = RestClient.create(url); }
    public Posting send(Posting event) { return http.post().uri("/reconciliation/postings").body(event).retrieve().body(Posting.class); }
}
