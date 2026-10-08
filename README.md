# Impact Studio

Python AI change impact and testing platform with an evidence knowledge graph across repositories. The API, workers, inference controls, graph normalization and review workflow are Python. A pinned local Enola parser provides broader language extraction. The **separate Maven/Spring Boot project remains an inference fixture**.

Two demo stories: an endpoint change disconnects a TypeScript consumer from a Python API while Go audit and SQL reporting remain in review scope; a schema-valid Java event change silently understates downstream money by 100x. The platform finds the source path, exposes the violated invariant, selects existing regression suites and asks Nemotron for cited risk reasoning and BA-ready test proposals. It prepares an evidence package for the BA → developer → QA / Defender workflow.

## Run locally

Requires Python 3.12+; Maven and Java 17+ are needed only to build / verify the authored Java fixture.

```powershell
Copy-Item .env.example .env
# Edit .env locally: set NVIDIA_API_KEY. Do not put this key in the UI or source control.
.\run.ps1
```

Open http://127.0.0.1:8080, choose **Try endpoint-change example**, then **Analyze change** and **System connections**. Use **Try payment-value example** for the separate monetary conservation scenario. The local launcher binds only to loopback. Without a key, the source analyzer works and clearly reports **AI not connected**; it does not simulate model output.

If PowerShell blocks `.ps1` scripts, use the Python launcher instead. It starts the API and a hidden background worker without changing execution policy:

```powershell
python run.py
# Existing interpreter in this workspace, if python is not on PATH:
& "..\..\.venv-impact\Scripts\python.exe" run.py
```

Use an interpreter with `requirements.txt` installed. `run.py --check` verifies dependencies and the pinned parser without starting services. Ctrl+C stops the API and its worker. An occupied port is reported without terminating other programs; `--port 8081` is available.

For the background demo already running in this workspace, stop it with `.\stop.ps1` before starting `.\run.ps1`. After editing .env, restart both API and worker so they load the new key. With the interactive launcher, Ctrl+C stops the API and its worker.

Manual launch:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m uvicorn studio.api:app --host 127.0.0.1 --port 8080
# Second terminal, same directory:
.venv\Scripts\python -m studio.worker
```

For a real repository, set `REPOSITORY_ROOTS` to approved server directories separated by semicolons, restart, and register the repository path through the UI. Source capture accepts bounded UTF-8 text from any repository, including unfamiliar extensions. It excludes binary content, dependency/build directories, .env, credential-named files, files over 200 KB and symlinks. Unsupported source gets a file anchor and an explicit unknown; it is not silently interpreted as isolated. Pattern redaction is a precaution, not a complete data-loss-prevention system. Repository evidence is sent to NVIDIA when the configured worker performs inference; use approved code only. The analysis API never executes repository builds, source code, hooks or external fact providers. The parser reads a disposable, redacted snapshot with platform-owned configuration; parser update checks and history are disabled.

## Guided review

The interface guides the team through **Describe → Review impact → Check sources → Plan tests**. Start with a sample, or add a local project and describe the request. Include relevant downstream projects. Exact code changes are optional developer input.

Results begin with the main compatibility alert. Count cards explain the review scope; they are not accuracy scores or passed-test counts. Source buttons show the project, file and relevant lines, opening the captured excerpt. Internal `E-…` references and hashes remain available in expandable technical details and exports.

AI failures show their reported cause and next action while retaining source results. An unavailable AI response cannot appear as accepted advice. Existing tests remain labelled **Suggested · not run**. The built-in **How to use this tool** guide explains the workflow and terminology. **AI status & history** opens saved reports without submitting new inference requests.

Run the presentation checks with `node --test tests/test_experience.cjs` and the backend suite with `python -m pytest -q`.

## Working features

| Feature | What is implemented | Evidence / limit |
|---|---|---|
| Polyglot source graph | Enola 0.4.26 static facts, native Java/Maven adapter, Python AST checks, namespaced source nodes | Parser target IDs are required for source edges; resolution is static, not runtime proof |
| Cross-repository contracts | Scoped HTTP, event, database, gRPC and package declarations join loaded repositories | HTTP method + origin + environment + route; events require broker identity; databases require database identity. Ambiguity withholds joins |
| Dependency rehearsal | Parse the validated proposal in a disposable copy and compare graph edges | Lost consumer matches become review alerts. No deployment or source edit occurs |
| Graph explorer | Interactive repository topology, clickable contracts, indexed and paginated source node queries | Source citations and edge strength are visible; complete raw graph can be exported |
| Coverage ledger | Captured/skipped files, languages, facts by file, syntax errors and unresolved relationships | No invented confidence or accuracy percentage; missing facts remain unknown |
| Change memory | Persist human planning lessons and retrieve by intent / shared source nodes | Historical suggestions are separate from dependency and test proof |
| Request or diff analysis | BA intent candidates, strict diff validation and in-memory application | Intent anchors are hypotheses; diff anchors refer to actual captured declarations |
| Semantic contract trap | Narrow, inspectable producer-unit / consumer-conversion rule with Decimal arithmetic | Source pattern rule is intentionally specific; it is not a general financial oracle |
| Executable counterfactual | Baseline, producer-only failure, coordinated fix tested in disposable Maven copies | `scripts/verify_fixture.py`; source hash ties display to the authored fixture |
| Nemotron reasoning | Cited risks, BA clarifications and tailored Given / When / Then proposals | Pydantic schema + evidence-ID validation; all accepted model content stays a review draft |
| Targeted regression plan | Greedy selection from static test calls, Java test references and a narrow Python TestClient endpoint adapter | Test filenames identify candidates, not coverage; selected means not run |
| Source drift check | Compare every selected repository against its immutable snapshot | Reanalysis is required after drift; there is no automatic approval |
| Role handoff | Owner metadata, BA / developer / QA action lists, Jira brief and Gherkin export | Jira brief includes lost-consumer contract alerts, provider failure reasons and unresolved scope; external Jira and Defender connections are not implemented |
| Trial API control | Shared database semaphore, RPM / estimated TPM / daily budgets, cache, cooldown, circuit breaker | Application policy limits, independent of actual account entitlement |
| Durable workflow | Bounded queue, idempotent admission, leases, crash recovery, cancellation and owner-checked result commit | PostgreSQL deployment supplied; local run uses SQLite |

## What “any repository” means

Registration and file-level impact work without requiring Maven, a batch layout or a particular language. Semantic extraction depends on the installed language/framework adapters. The bundled parser offers broad language support; this workspace verifies source extraction on Python, Java, TypeScript, Go, C#, Rust and Terraform/HCL inputs. That is not a claim that every framework, language feature or downstream system is discovered.

Downstream consumers outside the selected workspace cannot be inferred with certainty from one repository. Load their source and provide deployment bindings through `.impact-contracts.json`. The default adapters do not ingest production traces, discover brokers at runtime or inspect arbitrary deployed configuration. SQL/COBOL/custom formats can be represented by explicit contracts while their internal calls remain unknown.

An example contract file:

```json
{
  "version": 1,
  "service": "payment-api",
  "owner": "Payments engineering",
  "contracts": [
    {
      "protocol": "http", "role": "provides",
      "file": "app.py", "line": 10,
      "method": "POST", "resource": "/payments",
      "scope": "https://payments.internal", "environment": "uat"
    }
  ]
}
```

The consumer declares `role: consumes` with the same origin/environment and its literal method/path. `event` uses `publishes/subscribes` and a broker scope; `database` uses `writes/reads` and a database scope; `grpc` and `package` use `provides/consumes` and an explicit service/package identity. Owner declarations are reviewable assumptions. Where parsed HTTP routes contradict a provider declaration, the join is withheld.

Each analysis currently supports **8 repositories**, **25 MB / 10,000 captured text files per repository**, a **30,000 file traversal limit**, and **90 seconds per native parser invocation**. Impact review traversal is capped at **2,000 nodes / 12 hops**; truncation is explicit. Node browsing uses indexed SQL pages of at most 200 nodes. These are prototype capacity controls, not production capacity claims.

The parser is pinned rather than upgraded during analysis. Its binary digest, version, extractor policy, fact-file hash and source fingerprint are recorded; its receipt is validated before facts are accepted. Parser/version failure falls back to file evidence with explicit unknowns.

See [the five-project review](REFERENCE_REVIEW.md) and [architecture](ARCHITECTURE.md).

## NVIDIA configuration

The default model is `nvidia/nemotron-3-super-120b-a12b`, configurable through `NVIDIA_MODEL`. NVIDIA advertises a free prototype endpoint in its [model catalog](https://build.nvidia.com/nvidia/nemotron-3-super-120b-a12b/build). Account availability, credits and limits must be checked for your key; the application does not promise unlimited or permanently free inference.

The adapter uses the documented [chat completions endpoint](https://docs.api.nvidia.com/nim/reference/nvidia-nemotron-3-super-120b-a12b-infer). It handles HTTP 202 with up to three budgeted [invocation status GETs](https://docs.api.nvidia.com/cloud-functions/reference/getfunctioninvocationresult), retaining unresolved request IDs without duplicating the inference POST. It does not follow redirects that could disclose credentials.

Defaults are **one concurrent inference, six requests per minute, 24,000 conservatively estimated token units per minute and 100 daily requests**. These are adjustable application guardrails, not NVIDIA published quotas. Reservations use UTF-8 bytes plus the output allowance; this intentionally overestimates normal English input and is not the provider tokenizer. Actual reported token usage is attached to accepted model responses.

NVIDIA [documents hosted-service rate limits](https://docs.nvidia.com/rag/latest/troubleshooting.html); the platform respects Retry-After, shares cooldown across workers and opens a circuit after three failures. It preserves source findings when AI is unavailable. Transport / provider failures are not automatically resubmitted because an accepted-but-lost response can consume trial credits. An explicit new analysis can retry after cooldown; successful repeated contexts use the validated cache.

Context is scoped to affected evidence and capped; credentials remain backend environment variables. Repository text is treated as untrusted prompt data. AI outputs cannot modify repositories, execute code, send messages, merge, deploy or clear the review gate. Provenance validation does **not** prove an AI statement is semantically correct.

## Verify

Current validation: **49 passing platform tests**, JavaScript syntax checks, five archive source samples (997 evaluated files), and independent authored Python/Java failure experiments. `VERIFICATION.json` records scope and limitations.

```powershell
python -m pytest -q
python scripts/verify_polyglot.py
python scripts/verify_fixture.py
```

For an already downloaded Maven cache, use `--maven-repo=C:/path/to/repository` on the verification script; this enables offline builds. The script authors temporary copies only of the bundled fixture. Expected outcomes: baseline **5 / 5 pass**; producer-only change **2 of 5 fail**; producer + consumer fix **5 / 5 pass**. The failing tests verify monetary conservation and replay totals. Gherkin is a draft handoff; this fixture's executable suite is JUnit, not a claimed Defender execution.

To exercise actual HTTP downstreams:

```powershell
cd examples/banking-platform
mvn package
# Four terminals:
java -jar reporting-service/target/reporting-service-1.0.0-exec.jar
java -jar reconciliation-service/target/reconciliation-service-1.0.0-exec.jar
java -jar ledger-service/target/ledger-service-1.0.0-exec.jar
java -jar payments-service/target/payments-service-1.0.0-exec.jar
```

Service ports are 9101–9104. POST a synthetic USD payment to `http://localhost:9101/payments`, with `{"paymentId":"demo-1","amount":125.50,"currency":"USD"}`. Reporting total is exposed at `http://localhost:9104/reporting/total`. These services deliberately use in-memory storage; production outbox delivery, durable financial posting and reconciliation are outside the authored fixture's scope.

For an automated HTTP check which binds all four services to loopback and stops its own processes afterward, run `scripts/verify_http.ps1` from the project root after packaging the Maven fixture.

## PostgreSQL deployment

Set strong local `POSTGRES_PASSWORD` and `IMPACT_API_TOKEN` values in .env (URL-safe hex values are convenient), then:

```shell
docker compose up --build -d
docker compose up -d --scale worker=2
```

The API runs two processes. Workers share PostgreSQL queue leases, provider budgets and cached responses. The init service performs schema bootstrap once before replicas start. Provider concurrency stays at one despite adding workers; scaling source analysis does not pretend to increase free provider capacity. Use **API connection** in the UI to supply IMPACT_API_TOKEN, never NVIDIA_API_KEY.

This is a tested hackathon prototype, not a production banking certification. PostgreSQL/Docker orchestration has not been executed in this workspace because Docker is unavailable. For an institutional deployment, add versioned schema migrations, SSO / RBAC and tenant isolation, approved provider data policy, retention and encrypted storage, runtime trace / broker adapters, isolated test runners and a governed release evidence store. See [the architecture](ARCHITECTURE.md) for the implemented boundaries and scale path.
