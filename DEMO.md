# Five-minute demo

1. Select **Try endpoint-change example**: Python payment API, TypeScript web consumer, Go audit worker and SQL reporting. Show the diff renaming `/payments` to `/payments/v2`.
2. Analyze and open **System connections**. Inspect the four scoped connections: HTTP consumer, audit subscriber, ledger-table reader and audit-table reader. Click a readable file reference to open the source lines; hashes are under technical details.
3. Show **dependency rehearsal**: the web consumer loses its HTTP match, while audit/reporting remain in conservative review scope. Nothing is edited or deployed.
4. Show independently executed fixture tests: **3 pass → 1 failure → 3 pass**. They are source-hash checked and separate from the analysis job; other language execution is not claimed.
5. Show the **coverage ledger**: SQL has zero parser-fact coverage; unresolved calls stay visible. Explain why no path does not mean safe.
6. With the backend key configured, show **Nemotron** cited risk hypotheses, BA clarification and BDD. Repeat unchanged context to demonstrate cache/provider counters. Without the key, AI stays visibly unavailable.
7. Save a human **reviewed lesson**, rerun a related change and show graph/intent overlap retrieval. The lesson does not approve release or certify test execution.
8. Select **Try payment-value example**. A schema-valid event change makes 125.50 become 1.255 downstream. Inspect the real source path and independent **5 pass → 2 fail → 5 pass** experiment.
9. Finish the BA/developer/QA handoff: existing selected tests, coverage gaps, workspace drift check and downloadable evidence/Jira/Gherkin packet.

The differentiator is a cited and uncertainty-aware chain from BA intent through cross-language consumers to a safe dependency rehearsal, targeted verification and retained review knowledge. Do not claim zero errors, automatic safety, full runtime discovery or measured productivity gains without evaluation.
