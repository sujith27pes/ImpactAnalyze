# Synthetic banking inference fixture
Four independent Spring Boot HTTP services plus a contracts library and JUnit journey tests.
The Python tool must discover dependencies from this source, Maven POMs and HTTP routes.
No real customer data. In-memory storage and HTTP forwarding deliberately omit production delivery guarantees.
Baseline publishes MINOR amounts. major-unit.patch changes only the producer to MAJOR;
the ledger's unconditional minor-to-major conversion causes a 100x understatement even though the schema is valid.
ledger-unit-fix.patch is an example repair to verify in a disposable copy, never auto-applied by the tool.
Run `mvn test` here. Execute service jars with `-exec.jar` classifier in dependency order.
The .feature file is a BDD handoff artifact; JUnit is the executable suite in this fixture.
