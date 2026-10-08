# Review of the five supplied archives

The ZIPs were inspected as reference material. Relevant source and documentation were safely extracted; traversal entries and symlinks were excluded. No archive install script, repository hook, agent instruction or test command was followed or executed. Star counts and project-authored benchmarks were not treated as accuracy evidence for this tool.

| Archive | Reviewed material | Pattern adopted | Integration decision |
|---|---|---|---|
| ImpRec-master | README, license, `Logic/KnowlBase.cs`, artifacts/relations and impact search | Historical change → artifact → test traceability | Independent Python change memory; history is separate from current proof |
| repohelix-main | README/license, HTTP/event resolvers, confidence vocabulary, impact direction rules | Contract ontology, scoped joins, method/path precision | Independent matcher with origin/broker/database/environment scope and ambiguity refusal |
| axiomcodegraph-dev | README/license, graph bundle schema, resolution tiers and unresolved sites | Unresolved calls are not edges; stable identities and receipts | Design reference only; no implementation copied/installed; archive license FSL-1.1-Apache-2.0 |
| codexqa-main | README/license, evidence schema, review manifest and verification templates | Evidence packets, residual risk, proposed vs executed tests | Coverage ledger, evidence export and explicit test status; its skills were reference data |
| enola-main | README/license, CLI/config, fact schema, graph docs, linker and receipt engine | Local language extraction, JSONL facts and reproducible receipts | Official pinned `enola-cli 0.4.26` registry package behind a Python adapter; no archive scripts run |

The installed Windows wheel hash was verified against [published PyPI metadata and provenance](https://pypi.org/project/enola-cli/0.4.26/): `f977c42610c4444b23cdd4f757010147d6b1242fb76d3075b6a17701cee39295`. Runtime receipts record the binary hash. The reviewed main archive and pinned released package are not assumed identical.

## Implemented outcomes

- Namespaced evidence graph across loaded repositories, with explicit static and declared edge strengths.
- HTTP/event/database/gRPC/package identities; missing, duplicate or mismatched scope withholds a join.
- Before/proposal rehearsal that highlights lost consumers without deploying or editing source.
- Coverage ledger for captured/skipped files, facts by file, syntax errors, unsupported artifacts and unresolved relationships.
- Actual test references and narrow TestClient adapter; naming never proves coverage.
- Human planning lessons retrieved by intent/shared nodes without changing release/test authority.
- Pinned local parsing, validated receipts, policy-sensitive cache and SQL-indexed graph browsing.

## Limits of the review

The references do not make universal dependency discovery or zero errors possible. Reflection, dynamic dispatch, conditional builds, generated clients, unloaded consumers and deployment bindings can remain unknown. Static target resolution can differ from a deployed system. No reference benchmark is presented as this application's recall, precision or productivity gain.

Read-only indexing of safely extracted source subsets is recorded in `VERIFICATION.json`. These checks assess ingestion/parser compatibility, not complete checkouts or calibrated accuracy; repository code is not executed.

The deliverable contains platform code and authored fixtures, not redistributed source from the five archives. See `THIRD_PARTY_NOTICES.md`.

## Read-only parser checks

The bounded samples evaluated 997 source/manifest files with valid parser receipts:

| Archive | Evaluated files | Graph nodes | Cited edges | Unresolved relationships |
|---|---:|---:|---:|---:|
| ImpRec-master | 14 | 214 | 159 | 248 |
| repohelix-main | 255 | 4486 | 9153 | 4800 |
| axiomcodegraph-dev | 253 | 887 | 746 | 649 |
| codexqa-main | 224 | 4173 | 8351 | 6031 |
| enola-main | 251 | 2494 | 2842 | 4862 |

Each sample includes at most 250 language files plus root manifests from the safely extracted text subset. Counts include coarse file scope; unresolved entries include library boundaries and imports absent from the sample. These are compatibility/census results, not correctness, recall or precision measurements.
