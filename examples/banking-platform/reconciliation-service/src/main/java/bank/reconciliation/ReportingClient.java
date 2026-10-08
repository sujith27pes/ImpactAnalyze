package bank.reconciliation;
import bank.contracts.Posting;
import bank.contracts.Posting;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;
@Component
public class ReportingClient {
    private final RestClient http;
    public ReportingClient(@Value("${downstream.reporting-service.url}") String url) { this.http = RestClient.create(url); }
    public Posting send(Posting event) { return http.post().uri("/reports/postings").body(event).retrieve().body(Posting.class); }
}
