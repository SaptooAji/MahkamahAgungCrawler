# MahkamahAgungCrawler — Data Model & Future Architecture Notes

> **Purpose:** canonical project-context document for maintainers and AI tools.
>
> **Document status:** Reference / design note — **not an implementation specification for immediate changes**.
>
> **Current implementation:** Global `Putusan` identity with run-scoped processing state (`run_id`).
>
> **Future direction:** Separate global document identity from per-crawl-run result/state.
>
> **Last reviewed:** 2026-09-28

---

## 1. Executive Summary

MahkamahAgungCrawler is currently designed as an MVP crawler for the Indonesian Supreme Court decision website. The crawler discovers directory pages, discovers decision/detail URLs, scrapes detail pages, and attempts to locate the decision PDF.

The current data model deliberately keeps the domain model relatively compact. A `Putusan` row represents the globally identified decision URL while also carrying the current crawl/run state through `run_id`, scraping status, retry information, and processing ownership fields.

This is intentionally a **pragmatic MVP model**. It is good at global URL deduplication and keeping the current state easy to query. It is not intended to be a full historical crawl ledger.

A later version of the project is expected to evolve toward a model that separates:

- the **global identity of a decision/document**, and
- the **result/state of crawling that document in a particular `ScrapingRun`**.

In this document that future design is called **Model Versi Selanjutnya**.

It is important for maintainers and AI tools to understand the boundary:

> **Model Versi Selanjutnya is a future design direction. It is NOT the current implementation and must not be inferred as already implemented.**

---

## 2. Canonical Current State

### 2.1 Current production model

The current production model is approximately:

```text
ScrapingRun
    |
    +---- DiscoveryPageJob
    |
    +---- Putusan
              |
              +---- detail scraping state
              +---- retry state
              +---- processing ownership
```

Conceptually:

```text
ScrapingRun
-----------
id
status
tahun
total_pages
pagination_mode
total_discovered
total_success
total_failed
total_unpublished
retry_count
next_retry_at
...

DiscoveryPageJob
---------------
id
run_id
page_number
url
status
processing ownership
retry state
...

Putusan
-------
id
run_id
url_detail (globally unique)
url_pdf
status_scraping
retry_count
next_retry_at
processing token / lease
worker ownership
...
```

The exact field set belongs to the source code and migrations. This document intentionally focuses on **domain meaning and architecture**, not on replacing the schema definition.

### 2.2 Important current invariant

The current `Putusan` model has a global unique identity based on `url_detail`, while it also carries `run_id`.

Conceptually:

```text
UNIQUE(url_detail)
        +
run_id = run-scoped processing context
```

This combination is the main design characteristic to understand when working on the current system.

### 2.3 What `run_id` means today

`run_id` is used to scope crawler processing, selectors, finalization, retry handling, and run-level reporting.

However, because `url_detail` is globally unique, a single `Putusan` row cannot simultaneously represent multiple independent crawl observations for the same URL.

Also, a duplicate URL encountered by a later crawl run does not automatically imply that a new `Putusan` row is created. Current conflict/idempotency behavior must therefore be understood separately from the future per-run result model.

This distinction is important:

> `run_id` on the current `Putusan` row does **not** mean that the database already stores a complete historical crawl record for every run.

---

## 3. Why the Current Model Was Chosen

The current model was chosen intentionally for the MVP because the project's primary goals were:

1. reliably discover decision/detail URLs;
2. deduplicate decisions by their canonical detail URL;
3. process detail pages asynchronously with Celery;
4. persist retries and processing ownership;
5. isolate active work by `ScrapingRun` where required;
6. recover stale work safely;
7. keep the database model understandable while the crawler architecture was being stabilized.

The project was prioritizing **crawler correctness and operational reliability** over historical crawl analytics.

That trade-off was reasonable for the MVP because the major problems being solved were:

- pagination correctness;
- Cloudflare/transient failures;
- idempotent dispatch;
- processing ownership;
- retry scheduling;
- stale-worker recovery;
- run finalization;
- maintenance safety.

The current model lets those concerns be implemented without introducing another document/result abstraction prematurely.

---

## 4. Advantages of the Current Model

### 4.1 Simple global deduplication

A globally unique `url_detail` makes it straightforward to prevent the same decision URL from being stored repeatedly.

### 4.2 Simple current-state queries

The application can query the current `Putusan` row directly without resolving a second result/history table.

### 4.3 Lower storage overhead

Repeated crawls do not necessarily create another complete `Putusan` row for every observation of the same URL.

### 4.4 Good fit for the MVP lifecycle

The current model works well with the existing flow:

```text
Discovery
    -> Putusan creation/dedup
    -> Detail processing
    -> Retry/recovery
    -> Run finalization
```

### 4.5 Operational state is easy to access

The same record contains the processing information needed by workers and maintenance:

```text
status
retry_count
next_retry_at
processing token
processing lease / ownership
run scope
```

### 4.6 Less schema complexity

There is no additional document identity table plus per-run result table to maintain in the MVP.

---

## 5. Disadvantages / Limitations of the Current Model

### 5.1 Global document identity and crawl state are mixed

A `Putusan` row is simultaneously acting as:

```text
document identity
        +
current crawl state
```

Those are conceptually different responsibilities.

### 5.2 Historical crawl results are not first-class

The model does not naturally represent:

```text
Document X
    Run A -> SUCCESS
    Run B -> FAILED_RETRY
    Run C -> SUCCESS
```

as three independent historical observations.

### 5.3 Cross-run semantics require explicit decisions

When the same URL appears in a later run, maintainers must answer:

- Should the existing row be reused?
- Should `run_id` change?
- Should the old success remain authoritative?
- Should a newer failure replace the current state?
- What does `retry_count` mean after a new run sees the same URL?

These questions are signs that the global entity and run result are sharing one row.

### 5.4 Run history is not naturally reproducible

A future analysis such as:

> "What exactly happened to this decision in Run A versus Run B?"

cannot always be answered from one current row without a separate history mechanism.

### 5.5 Current-state semantics can become ambiguous

A future requirement may need to distinguish:

- latest crawl attempt;
- latest successful crawl;
- current known PDF;
- state of the document itself;
- state of a particular run.

The current model compresses these concepts.

### 5.6 Cross-run uniqueness is intentionally global

`UNIQUE(url_detail)` is excellent for deduplication but prevents a simple representation of one decision URL having independent rows for multiple runs.

---

## 6. Important Interpretation of Failure States

The project has two important levels of retry/failure state.

### Detail/Putusan-level

```text
FAILED_RETRY
    = transient failure; still eligible for retry

FAILED_PERMANENT
    = retry budget exhausted for that crawl processing path
```

`FAILED_PERMANENT` must **not** be interpreted as:

> "The document permanently does not exist on the source website."

The live E2E tests demonstrated that Cloudflare conditions can change between runs. The same URL can fail under one crawl condition and succeed under another.

### Run-level

`ScrapingRun` also has its own retry lifecycle. A transient run-level discovery/pagination problem can put the run into `FAILED_RETRY` and later be retried by maintenance; a terminal run failure is different from a transient processing state.

This distinction must remain intact in any future data-model redesign.

---

# 7. Model Versi Selanjutnya

## 7.1 Goal

The purpose of Model Versi Selanjutnya is to separate two concepts that are currently combined:

### Global document identity

> "Which legal decision/document is this URL referring to?"

### Crawl result for a run

> "What happened when Run X crawled this document?"

The conceptual model becomes:

```text
Document / Putusan
        |
        +---- CrawlResult / PutusanRun (Run A)
        |
        +---- CrawlResult / PutusanRun (Run B)
        |
        +---- CrawlResult / PutusanRun (Run C)
```

Together with:

```text
ScrapingRun
    |
    +---- DiscoveryPageJob
    |
    +---- PutusanRun
              |
              +---- Document
```

### 7.2 Conceptual schema

```text
Document
--------
id
url_detail (globally unique)
canonical/global metadata
current/global PDF reference where appropriate
...

PutusanRun / CrawlResult
------------------------
id
document_id
run_id
status_scraping
retry_count
next_retry_at
processing token / lease
worker ownership
run-specific observations
...

ScrapingRun
-----------
id
status
run metadata
run counters
retry state
...

DiscoveryPageJob
---------------
id
run_id
page information
processing state
retry state
...
```

The final names are intentionally not prescribed by this document. The architectural separation is the important part.

---

## 8. Behavior of Model Versi Selanjutnya

Suppose URL X appears in three crawl runs:

```text
Run A -> URL X
Run B -> URL X
Run C -> URL X
```

The intended representation becomes:

```text
Document X
    |
    +-- PutusanRun A -> SUCCESS
    +-- PutusanRun B -> FAILED_PERMANENT
    +-- PutusanRun C -> SUCCESS
```

The document identity remains one object.

The crawl observations are separate objects.

Therefore:

- a failed crawl in Run B does not overwrite a successful observation in Run A;
- retry state belongs to the run-specific result;
- finalization belongs to `ScrapingRun` through its run-specific results;
- historical results remain available;
- the same document can be re-crawled without destroying previous observations.

---

## 9. Advantages of Model Versi Selanjutnya

### 9.1 Clear domain separation

The model follows a cleaner semantic boundary:

```text
Document
= identity

PutusanRun
= crawl observation/state
```

### 9.2 Natural historical data

Each run has an explicit result record.

### 9.3 Strong run isolation

A retry, failure, or success belongs to one run-specific result instead of competing for ownership of one global row.

### 9.4 Better auditability

It becomes possible to answer:

- What happened in Run A?
- What happened in Run B?
- When did the PDF become available?
- Which run encountered Cloudflare?
- Did a later run recover a previous failure?

without reconstructing history indirectly.

### 9.5 Better crawler-version comparison

Different crawler implementations/configurations can be compared against the same document across runs.

### 9.6 Safer re-crawling

A new run can produce a new crawl result without destroying the previous result.

### 9.7 Retry state belongs to the correct abstraction

`retry_count`, `next_retry_at`, `processing_token`, and worker lease are properties of the crawl attempt/result, not the legal document itself.

### 9.8 Cleaner long-term Clean Architecture boundary

The design better separates business identity from infrastructure/process state.

---

## 10. Disadvantages of Model Versi Selanjutnya

### 10.1 More schema complexity

At least one additional relationship/table is required.

### 10.2 More joins and query concepts

Queries must distinguish between:

- the document;
- a specific run result;
- the latest result;
- the latest successful result;
- the current known document state.

### 10.3 More storage

Repeated crawls can create additional run-result records.

### 10.4 More repository/service surface

The codebase would likely need separate operations for:

```text
find/create Document
find/create PutusanRun
find current result
find latest successful result
create run result
update run-scoped state
```

### 10.5 More migration complexity

Existing `Putusan` rows must be decomposed into global document identity and run-specific result data.

### 10.6 Current-state semantics must become explicit

The application must define what "current" means:

- latest attempt;
- latest success;
- latest run;
- current known PDF;
- current source metadata.

This is a real domain decision, not merely a database query optimization.

---

# 11. Current Model vs Model Versi Selanjutnya

| Area | Current Model | Model Versi Selanjutnya |
|---|---|---|
| Global URL dedup | **Strong / simple** | Strong via `Document` |
| Current-state query | **Simple** | More explicit / potentially more complex |
| Per-run history | Limited | **Native** |
| Run isolation | Good with careful `run_id` scoping | **Natural** |
| Retry isolation | Requires careful semantics | **Native to run result** |
| Processing ownership | On `Putusan` | **On `PutusanRun`** |
| Finalizer scope | Run-scoped queries required | **Direct run-result ownership** |
| Historical audit | Limited without extra history | **Strong** |
| Re-crawl | Possible, but semantics require care | **Natural** |
| Storage usage | **Lower** | Higher |
| Schema complexity | **Lower** | Higher |
| Query complexity | **Lower** | Higher |
| Migration cost | Current state | Higher |
| Long-term extensibility | Moderate | **High** |
| MVP suitability | **High** | Over-engineered for MVP |
| Historical/reprocessing suitability | Moderate | **High** |

---

# 12. Why the Current Model Is Still Valid

The existence of Model Versi Selanjutnya does **not** mean the current MVP model is wrong.

The current model was a conscious scope decision:

```text
First stabilize crawler correctness.
Then evolve the domain model when history/re-crawl requirements justify it.
```

The project has already invested in the harder operational concerns:

- hybrid pagination;
- live sequential fallback;
- Celery background execution;
- DB-backed state;
- idempotent dispatch;
- processing ownership;
- stale recovery;
- Putusan retry lifecycle;
- run-level retry lifecycle;
- run finalization;
- run isolation;
- terminal scheduler safety.

That makes the current model a valid and understandable MVP boundary.

---

# 13. What Must NOT Be Assumed

AI tools and future maintainers should **not** infer any of the following:

1. `Putusan.run_id` means every historical crawl run is preserved. It is not a history table.
2. `FAILED_PERMANENT` means the source document permanently has no PDF. It means the crawler exhausted the retry policy for that processing path.
3. Model Versi Selanjutnya is already implemented. It is not.
4. Moving from the current model to the future model is only a unique-constraint change. It affects repositories, workers, finalization, reporting, and tests.
5. A successful prior run is automatically preserved as a separate database record when the same URL is seen again.

---

# 14. Future Migration Checklist

Model Versi Selanjutnya should be implemented only as a deliberate future architecture phase.

Before implementation, define:

### Domain

- [ ] What exactly is the global identity of a `Document`?
- [ ] Which fields belong to the document itself?
- [ ] Which fields belong only to a crawl result?
- [ ] What does "current document state" mean?

### Database

- [ ] `Document.url_detail` global uniqueness
- [ ] `PutusanRun` / `CrawlResult` relationship to `Document`
- [ ] `PutusanRun` relationship to `ScrapingRun`
- [ ] uniqueness of `(run_id, document_id)`
- [ ] indexes for run-scoped status/retry queries
- [ ] foreign-key behavior
- [ ] migration of existing MVP data

### Repositories

- [ ] document identity lookup
- [ ] run-result lookup
- [ ] create/get document idempotently
- [ ] create/get run result idempotently
- [ ] latest-result query
- [ ] latest-success query
- [ ] run-scoped selectors

### Workers

- [ ] discovery creates/resolves `Document`
- [ ] discovery creates `PutusanRun`
- [ ] detail worker claims `PutusanRun`, not global document identity
- [ ] retry state belongs to `PutusanRun`
- [ ] processing token belongs to `PutusanRun`

### Finalization

- [ ] `ScrapingRun` finalization only evaluates its own run results
- [ ] global document state cannot accidentally block run finalization
- [ ] terminal run states remain idempotent

### Concurrency

- [ ] same URL in same run cannot create duplicate run results
- [ ] same URL in different runs is allowed
- [ ] concurrent creation resolves to one global document
- [ ] concurrent run-result creation remains idempotent

### History / reporting

- [ ] historical run result remains immutable enough for audit
- [ ] current document state is explicitly defined
- [ ] latest successful crawl can be queried
- [ ] per-run metrics remain accurate
- [ ] crawler-version comparison is possible if required

### Tests

- [ ] document deduplication
- [ ] same URL / same run idempotency
- [ ] same URL / different run independence
- [ ] run isolation
- [ ] retry isolation
- [ ] finalizer isolation
- [ ] concurrent document creation
- [ ] concurrent run-result creation
- [ ] latest-result semantics
- [ ] historical-result preservation

---

# 15. Recommended Future Shape

The desired long-term conceptual shape is:

```text
                         +----------------+
                         |  ScrapingRun   |
                         +-------+--------+
                                 |
                                 | owns
                                 v
                         +----------------+
                         |   PutusanRun   |
                         | / CrawlResult  |
                         +-------+--------+
                                 |
                                 | references
                                 v
                         +----------------+
                         |    Document    |
                         +----------------+
                         | global URL     |
                         | global identity|
                         +----------------+
```

This should be viewed as an **evolution path**, not a requirement to implement immediately.

---

# 16. Context for AI Tools

When an AI tool is asked to modify or analyze this repository, use the following context as the default interpretation:

```text
CURRENT STATE
-------------
The MVP uses a globally unique Putusan.url_detail and stores run-scoped
processing information using Putusan.run_id. Putusan therefore combines
global document identity with current crawl state.

ScrapingRun owns the lifecycle of a crawl run.
DiscoveryPageJob is run-scoped and represents directory-page processing.
Putusan represents the discovered decision/detail URL and current processing state.
Celery handles asynchronous execution.
PostgreSQL is the durable state store.
Retries, processing ownership, stale recovery, dispatch fences, run finalization,
and run isolation are part of the current production architecture.

IMPORTANT
---------
The current model is intentionally an MVP trade-off.
It is NOT a full historical crawl ledger.

FUTURE DIRECTION
----------------
The intended next architecture separates:

1. Document / Putusan = global document identity
2. PutusanRun / CrawlResult = run-specific crawl observation and processing state

A future run should be able to produce a new crawl-result record for an
existing document without overwriting prior run history.

DO NOT ASSUME
-------------
Do not implement the future model unless the task explicitly asks for it.
Do not change the current UNIQUE(url_detail) semantics merely because the
future model is documented here.
Do not treat FAILED_PERMANENT as proof that the source document has no PDF.
Do not treat run_id on Putusan as a complete historical record.
```

This section exists specifically so future AI-assisted work can understand the project without confusing the **current implementation** with the **planned next architecture**.

---

# 17. Scope Boundary

This document does not authorize any immediate schema change.

The intended sequence is:

```text
Current MVP
    |
    +-- Legacy cleanup              DONE
    +-- Test reorganization         DONE
    +-- Runtime/retry validation    DONE
    |
    v
Documented future direction
    |
    v
Model Versi Selanjutnya
    |
    +-- Domain decision
    +-- Schema design
    +-- Migration strategy
    +-- Repository redesign
    +-- Worker redesign
    +-- Finalizer redesign
    +-- Regression tests
    +-- Data migration / validation
```

The future model should only be implemented when its historical/re-crawl/audit benefits justify the additional schema and application complexity.

---

# 18. Final Decision Record

**Decision for the current version:**

> Keep the existing global-`Putusan` model for the MVP.

**Reason:**

> It is simpler, supports the current crawler reliability requirements, provides global URL deduplication, and avoids introducing a second run-result abstraction before the project has a concrete historical/re-crawl requirement.

**Direction for the next version:**

> Separate global document identity from per-run crawl results so that multiple crawl runs can independently record the state of the same document without overwriting one another.

**Important:**

> The future model is a planned architecture evolution, not part of the current implementation.
