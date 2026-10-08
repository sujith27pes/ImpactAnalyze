"""Rebuild the synthetic, authored Maven inference fixture. Never touches registered repos."""
from pathlib import Path
import json, difflib

ROOT = Path(__file__).resolve().parents[1] / 'examples/banking-platform'
def write(path, text):
    destination = ROOT / path
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(text.strip()+'\n', encoding='utf-8')

modules = ['contracts', 'payments-service', 'ledger-service', 'reconciliation-service', 'reporting-service', 'journey-tests']
write('pom.xml', '''<project xmlns="http://maven.apache.org/POM/4.0.0" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 https://maven.apache.org/xsd/maven-4.0.0.xsd">
<modelVersion>4.0.0</modelVersion><parent><groupId>org.springframework.boot</groupId><artifactId>spring-boot-starter-parent</artifactId><version>3.5.16</version></parent>
<groupId>hackathon.bank</groupId><artifactId>banking-platform</artifactId><version>1.0.0</version><packaging>pom</packaging>
<properties><java.version>17</java.version></properties><modules>''' + ''.join(f'<module>{m}</module>' for m in modules) + '</modules></project>')
for module in modules:
    deps = []
    if module != 'contracts': deps.append('<dependency><groupId>hackathon.bank</groupId><artifactId>contracts</artifactId><version>${project.version}</version></dependency>')
    if module.endswith('-service'): deps.append('<dependency><groupId>org.springframework.boot</groupId><artifactId>spring-boot-starter-web</artifactId></dependency>')
    if module == 'journey-tests':
        deps += [f'<dependency><groupId>hackathon.bank</groupId><artifactId>{m}</artifactId><version>${{project.version}}</version><scope>test</scope></dependency>' for m in modules if m.endswith('-service')]
        deps.append('<dependency><groupId>org.springframework.boot</groupId><artifactId>spring-boot-starter-test</artifactId><scope>test</scope></dependency>')
    plugin = '<build><plugins><plugin><groupId>org.springframework.boot</groupId><artifactId>spring-boot-maven-plugin</artifactId><configuration><classifier>exec</classifier></configuration></plugin></plugins></build>' if module.endswith('-service') else ''
    write(f'{module}/pom.xml', '<project xmlns="http://maven.apache.org/POM/4.0.0"><modelVersion>4.0.0</modelVersion><parent><groupId>hackathon.bank</groupId><artifactId>banking-platform</artifactId><version>1.0.0</version></parent>'+f'<artifactId>{module}</artifactId><dependencies>'+''.join(deps)+'</dependencies>'+plugin+'</project>')

def java(module, name, body):
    package = 'bank.contracts' if module == 'contracts' else 'bank.' + module.split('-')[0]
    write(f'{module}/src/main/java/{package.replace(".", "/")}/{name}.java', f'package {package};\n'+body)

java('contracts', 'AmountUnit', 'public enum AmountUnit { MINOR, MAJOR }')
java('contracts', 'PaymentEvent', '''import java.math.BigDecimal;
// Wire schema allows both units; consumers must interpret the unit explicitly.
public record PaymentEvent(String paymentId, BigDecimal amount, AmountUnit amountUnit, String currency) {}''')
java('contracts', 'Posting', '''import java.math.BigDecimal;
public record Posting(String paymentId, BigDecimal amountMajor, String currency) {}''')

for mod, port in [('payments-service',9101),('ledger-service',9102),('reconciliation-service',9103),('reporting-service',9104)]:
    name = mod.split('-')[0].capitalize()
    java(mod, name+'Application', f'''import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
@SpringBootApplication
public class {name}Application {{ public static void main(String[] args) {{ SpringApplication.run({name}Application.class, args); }} }}''')
    write(f'{mod}/src/main/resources/application.properties', f'server.port={port}\nspring.application.name={mod}')

java('payments-service', 'PaymentService', '''import bank.contracts.AmountUnit;
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
}''')
java('ledger-service', 'LedgerService', '''import bank.contracts.PaymentEvent;
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
}''')
for mod in ['reconciliation-service','reporting-service']:
    name = mod.split('-')[0].capitalize()
    java(mod, name+'Service', f'''import bank.contracts.Posting;
import java.math.BigDecimal;
import java.util.LinkedHashMap;
import java.util.Map;
import org.springframework.stereotype.Service;
@Service
public class {name}Service {{
    private final Map<String, Posting> postings = new LinkedHashMap<>();
    public synchronized Posting accept(Posting posting) {{
        Posting existing = postings.get(posting.paymentId());
        if (existing != null && !existing.equals(posting)) throw new IllegalArgumentException("Conflicting duplicate");
        postings.putIfAbsent(posting.paymentId(), posting);
        return posting;
    }}
    public synchronized BigDecimal total() {{ return postings.values().stream().map(Posting::amountMajor).reduce(BigDecimal.ZERO, BigDecimal::add); }}
}}''')

for mod, client, target, route in [('payments-service','Ledger','ledger-service','/ledger/postings'),('ledger-service','Reconciliation','reconciliation-service','/reconciliation/postings'),('reconciliation-service','Reporting','reporting-service','/reports/postings')]:
    target_port = {'ledger-service':9102,'reconciliation-service':9103,'reporting-service':9104}[target]
    kind = 'PaymentEvent' if mod=='payments-service' else 'Posting'
    java(mod, client+'Client', f'''import bank.contracts.{kind};
import bank.contracts.Posting;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;
@Component
public class {client}Client {{
    private final RestClient http;
    public {client}Client(@Value("${{downstream.{target}.url}}") String url) {{ this.http = RestClient.create(url); }}
    public Posting send({kind} event) {{ return http.post().uri("{route}").body(event).retrieve().body(Posting.class); }}
}}''')
    props = ROOT / f'{mod}/src/main/resources/application.properties'
    props.write_text(props.read_text()+f'downstream.{target}.url=http://localhost:{target_port}\n', encoding='utf-8')

java('payments-service','PaymentController','''import bank.contracts.Posting;
import java.math.BigDecimal;
import org.springframework.web.bind.annotation.*;
@RestController
public class PaymentController {
    private final PaymentService service;
    private final LedgerClient ledger;
    public PaymentController(PaymentService service, LedgerClient ledger) { this.service=service; this.ledger=ledger; }
    public record Request(String paymentId, BigDecimal amount, String currency) {}
    @PostMapping("/payments")
    public Posting pay(@RequestBody Request request) { return ledger.send(service.create(request.paymentId(), request.amount(), request.currency())); }
}''')
for mod, name, endpoint, kind, next_name in [('ledger-service','Ledger','/ledger/postings','PaymentEvent','Reconciliation'),('reconciliation-service','Reconciliation','/reconciliation/postings','Posting','Reporting'),('reporting-service','Reporting','/reports/postings','Posting',None)]:
    imports = f'import bank.contracts.{kind};\n'+('import bank.contracts.Posting;\n' if kind!='Posting' else '')
    downstream_field = f'private final {next_name}Client downstream;' if next_name else ''
    constructor_extra = f', {next_name}Client downstream' if next_name else ''
    assignment = 'this.downstream=downstream;' if next_name else ''
    forwarding = 'return downstream.send(service.accept(event));' if next_name else 'return service.accept(event);'
    total = f'@GetMapping("/{name.lower()}/total") public java.math.BigDecimal total() {{ return service.total(); }}' if name!='Ledger' else ''
    java(mod,name+'Controller',imports+f'''import org.springframework.web.bind.annotation.*;
@RestController
public class {name}Controller {{
    private final {name}Service service;
    {downstream_field}
    public {name}Controller({name}Service service{constructor_extra}) {{ this.service=service; {assignment} }}
    @PostMapping("{endpoint}")
    public Posting accept(@RequestBody {kind} event) {{ {forwarding} }}
    {total}
}}''')

write('journey-tests/src/test/java/bank/journey/MoneyJourneyTest.java', '''package bank.journey;
import bank.payments.PaymentService;
import bank.ledger.LedgerService;
import bank.reconciliation.ReconciliationService;
import bank.reporting.ReportingService;
import bank.contracts.*;
import java.math.BigDecimal;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;
class MoneyJourneyTest {
    @Test void amountIsConservedAcrossDownstreams() {
        var event = new PaymentService().create("p1", new BigDecimal("125.50"), "USD");
        var posting = new LedgerService().accept(event);
        var reconciliation = new ReconciliationService(); var reporting = new ReportingService();
        reporting.accept(reconciliation.accept(posting));
        assertEquals(0, new BigDecimal("125.50").compareTo(reporting.total()));
        assertEquals(0, reconciliation.total().compareTo(reporting.total()));
    }
    @Test void duplicatePaymentDoesNotDoubleCount() {
        var event = new PaymentService().create("p2", new BigDecimal("10.00"), "USD");
        var ledger = new LedgerService(); var reporting = new ReportingService();
        reporting.accept(ledger.accept(event)); reporting.accept(ledger.accept(event));
        assertEquals(0, new BigDecimal("10.00").compareTo(reporting.total()));
    }
    @Test void conflictingDuplicateIsRejected() {
        var payments = new PaymentService(); var ledger = new LedgerService();
        ledger.accept(payments.create("p3", new BigDecimal("1.00"), "USD"));
        assertThrows(IllegalArgumentException.class, () -> ledger.accept(payments.create("p3", new BigDecimal("2.00"), "USD")));
    }
    @Test void excessPrecisionIsRejected() {
        assertThrows(ArithmeticException.class, () -> new PaymentService().create("p4", new BigDecimal("1.001"), "USD"));
    }
    @Test void nonPositiveAmountIsRejected() {
        assertThrows(IllegalArgumentException.class, () -> new PaymentService().create("p5", BigDecimal.ZERO, "USD"));
    }
}''')
write('journey-tests/src/test/resources/features/payment-units.feature', '''@payments @ledger @reconciliation @reporting
Feature: Preserve payment value across the banking journey
  Scenario: BA verifies downstream amount conservation
    Given a synthetic USD payment of 125.50
    When payments publishes the event and all downstreams consume it
    Then the ledger posting is 125.50 USD
    And reconciliation and reporting each total 125.50 USD
  Scenario: Retry does not create a duplicate balance
    Given an accepted payment with a stable payment identifier
    When the identical payment is delivered twice
    Then reporting counts the payment once''')
write('contracts/src/main/resources/payment-event.schema.json', json.dumps({'$schema':'https://json-schema.org/draft/2020-12/schema','type':'object','required':['paymentId','amount','amountUnit','currency'],'properties':{'paymentId':{'type':'string'},'amount':{'type':'number'},'amountUnit':{'enum':['MINOR','MAJOR']},'currency':{'enum':['USD']}}},indent=2))
write('.impact-owners.json', json.dumps({'payments-service':'Payments engineering','ledger-service':'Ledger engineering','reconciliation-service':'Reconciliation QA','reporting-service':'Reporting BA','contracts':'Integration architecture','journey-tests':'Cross-system QA'},indent=2))
write('README.md', '''# Synthetic banking inference fixture
Four independent Spring Boot HTTP services plus a contracts library and JUnit journey tests.
The Python tool must discover dependencies from this source, Maven POMs and HTTP routes.
No real customer data. In-memory storage and HTTP forwarding deliberately omit production delivery guarantees.
Baseline publishes MINOR amounts. major-unit.patch changes only the producer to MAJOR;
the ledger's unconditional minor-to-major conversion causes a 100x understatement even though the schema is valid.
ledger-unit-fix.patch is an example repair to verify in a disposable copy, never auto-applied by the tool.
Run `mvn test` here. Execute service jars with `-exec.jar` classifier in dependency order.
The .feature file is a BDD handoff artifact; JUnit is the executable suite in this fixture.''')
payment_path = 'payments-service/src/main/java/bank/payments/PaymentService.java'
before = (ROOT/payment_path).read_text(); after = before.replace('amountMajor.movePointRight(2), AmountUnit.MINOR', 'amountMajor, AmountUnit.MAJOR')
write('changes/major-unit.patch', ''.join(difflib.unified_diff(before.splitlines(True),after.splitlines(True),fromfile='a/'+payment_path,tofile='b/'+payment_path)).rstrip())
ledger_path = 'ledger-service/src/main/java/bank/ledger/LedgerService.java'
before = (ROOT/ledger_path).read_text(); after = before.replace('event.amount().movePointLeft(2)', '(event.amountUnit() == bank.contracts.AmountUnit.MAJOR ? event.amount() : event.amount().movePointLeft(2))')
write('changes/ledger-unit-fix.patch', ''.join(difflib.unified_diff(before.splitlines(True),after.splitlines(True),fromfile='a/'+ledger_path,tofile='b/'+ledger_path)).rstrip())
print('Created synthetic Maven fixture:', ROOT)
