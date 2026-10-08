# Synthetic polyglot banking workspace

Four independent source repositories: Python payment API, TypeScript web consumer,
Go audit worker, SQL reporting. These are inference fixtures, not deployed systems.

Scoped owner declarations join HTTP, Kafka event and database relationships. They
are explicit reviewable assumptions, not execution evidence. SQL-only source can
be captured and connected through declarations even when the parser emits no facts.

The proposal renames the payment endpoint. The web consumer loses its HTTP contract
match while the audit and reporting paths remain in review scope. The independent
authored Python test runner demonstrates the HTTP compatibility regression.

Run `python scripts/verify_polyglot.py` from the platform root to execute only this
authored fixture in disposable copies. The platform never executes analyzed code.
