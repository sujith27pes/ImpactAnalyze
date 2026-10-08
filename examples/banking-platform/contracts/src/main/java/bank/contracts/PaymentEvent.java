package bank.contracts;
import java.math.BigDecimal;
// Wire schema allows both units; consumers must interpret the unit explicitly.
public record PaymentEvent(String paymentId, BigDecimal amount, AmountUnit amountUnit, String currency) {}
