-- Deployment database: demo-bank-db; synthetic-demo only.
SELECT SUM(amount_minor) / 100.0 AS posted_major FROM ledger_postings;
SELECT SUM(amount_minor) / 100.0 AS audited_major FROM audit_rows;
