package bank.contracts;
import java.math.BigDecimal;
public record Posting(String paymentId, BigDecimal amountMajor, String currency) {}
