package bank.payments;
import bank.contracts.AmountUnit;
import bank.contracts.PaymentEvent;
import java.math.BigDecimal;
import org.springframework.stereotype.Service;
@Service
public class PaymentService {
    public PaymentEvent create(String id, BigDecimal amountMajor, String currency) {
        if (id == null || id.isBlank() || amountMajor == null || amountMajor.signum() <= 0) throw new IllegalArgumentException("Invalid payment");
        if (!"USD".equals(currency)) throw new IllegalArgumentException("Demo accepts USD only");
        amountMajor = amountMajor.setScale(2, java.math.RoundingMode.UNNECESSARY);
        return new PaymentEvent(id, amountMajor.movePointRight(2), AmountUnit.MINOR, currency);
    }
}
