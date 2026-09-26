MAHKAMAH AGUNG CRAWLER — MVP TRACKING
======================================

FOUNDATION
[x] Phase 0  Environment isolation
[x] Phase 1  PostgreSQL + Alembic
[x] Phase 2  Application connectivity

PAGINATION
[x] Phase 3  Pagination discovery
    [x] Predictive pagination
    [x] Sequential fallback
    [x] Canonical page 1
    [x] Last page detection

DISCOVERY
[x] Phase 4  Discovery page jobs
[x] Phase 5  Automatic batching
    [x] Job creation idempotent
    [x] PostgreSQL locking
    [x] Processing token
    [x] Automatic batching
    [x] Batch completion
    [x] Discovery → Putusan upsert

PUTUSAN PROCESSING
[x] Phase 6A Detail/PDF/500/Unpublished
[x] Phase 6B Putusan dispatcher
[x] Phase 6C Claim/idempotency
[ ] Phase 6D SUCCESS/UNPUBLISHED lifecycle   ← CURRENT
[ ] Phase 6E Detail server-error/retry
[ ] Phase 6F Putusan batch E2E

RELIABILITY
[ ] Phase 7  Discovery validation
[ ] Phase 8  Putusan processing validation
[ ] Phase 9  Retry testing
    [ ] Automatic retry
    [ ] FAILED_RETRY scheduling
    [ ] Stale PROCESSING recovery
    [ ] Retry after worker failure

CONCURRENCY
[ ] Phase 10 Multi-worker validation
    [ ] Multiple discovery workers
    [ ] Multiple Putusan workers
    [ ] Duplicate task
    [ ] No double processing
    [ ] No stuck PROCESSING

RUN LIFECYCLE
[ ] Phase 11 Automatic run lifecycle
    [ ] Run starts
    [ ] Discovery completion
    [ ] Putusan completion
    [ ] Counters
    [ ] Final run state

[ ] Phase 12 Run finalizer

END-TO-END
[ ] Phase 13 Clean E2E
    [ ] Fresh run
    [ ] Pagination
    [ ] Discovery
    [ ] Putusan
    [ ] PDF URL
    [ ] Retry
    [ ] Final status

AUDIT
[ ] Phase 14 Final DB audit
    [ ] No unexpected PENDING
    [ ] No PROCESSING left behind
    [ ] No orphan jobs
    [ ] URL uniqueness
    [ ] State consistency

PRODUCTION
[ ] Phase 15 Production readiness
    [ ] Structured logging
    [ ] Monitoring
    [ ] Production config
    [ ] Secrets
    [ ] Backup
    [ ] Resource limits