# Phase 13 Final Test Runbook

## Scope

MVP scope is the Mahkamah Agung scraper pipeline only:

```text
Mahkamah Agung
    -> Nodriver
    -> pagination
    -> DiscoveryPageJob
    -> Putusan
    -> PDF URL
    -> PostgreSQL
    -> Celery Worker / Beat
```

FastAPI is intentionally out of scope for this phase.

Historical scraper files are not part of the active scraper architecture:

```text
scraper/engine.py
scraper/test_nodriver.py
scraper/test_scraper.py
scraper/browser.py
```

## Test database

Use the already-created clean test database. Do not recreate the database or run `docker compose down -v`.

```powershell
$env:ENV_FILE='.env.test'
$env:DATABASE_URL='postgresql+psycopg://ma_admin:ma_rahasia_123@localhost:15432/ma_e2e_1997'
```

Services expected locally:

```text
PostgreSQL : localhost:15432
Redis      : localhost:6379/0
```

## 1. Verify the database is still clean

```powershell
python database/check_test_db.py
```

Do not continue to the full E2E run if unexpected test data is already present.

## 2. Static / architecture acceptance

```powershell
python scripts/phase13_acceptance.py
```

The acceptance checks include:

```text
- sequential pagination 1 -> 2 -> 3
- Celery Beat schedule = 30 seconds
- legacy discovery dispatcher is not registered
- new discovery dispatcher is registered
- Putusan dispatcher remains registered
- no Celery chord/self-chain remains in production orchestration
- PostgreSQL advisory dispatch fence exists
```

Expected:

```text
PHASE 13 ACCEPTANCE: PASS
```

## 3. Dispatch / queue idempotency test

This test uses the clean PostgreSQL database but does not require a live Redis worker because Celery child enqueue calls are mocked.

```powershell
python -m tests.manual_phase13_dispatch_idempotency_test
```

Expected:

```text
PASS discovery dispatch is DB-fenced and non-amplifying
PASS putusan dispatch is DB-fenced and non-amplifying
PASS child task fencing prevents duplicate processing ownership
PHASE 13 DISPATCH TEST: PASS
```

## 4. Start Redis/PostgreSQL

Use the existing Docker setup. Do not destroy volumes.

```powershell
docker compose up -d postgres redis
```

## 5. Start Celery worker

Terminal 1:

```powershell
$env:ENV_FILE='.env.test'
$env:DATABASE_URL='postgresql+psycopg://ma_admin:ma_rahasia_123@localhost:15432/ma_e2e_1997'
celery -A celery_app.celery worker --pool=solo --loglevel=INFO
```

## 6. Start Celery Beat

Terminal 2:

```powershell
$env:ENV_FILE='.env.test'
$env:DATABASE_URL='postgresql+psycopg://ma_admin:ma_rahasia_123@localhost:15432/ma_e2e_1997'
celery -A celery_app.celery beat --loglevel=INFO
```

Beat is the scheduler / safety net. Batch tasks do not self-chain anymore.

## 7. Create a fresh MVP run

Example for 2021:

```powershell
python scripts/create_mvp_run.py `
  --year 2021 `
  --url 'https://putusan3.mahkamahagung.go.id/direktori/index/tahunjenis/putus/tahun/2021.html'
```

Copy the printed `run_id`.

## 8. Enqueue that run

```powershell
python scripts/enqueue_scraping_run.py --run-id <RUN_ID>
```

## 9. Monitor the run

```powershell
python scripts/show_run_state.py --run-id <RUN_ID>
```

Repeat this command as needed.

The expected production sequence is:

```text
scraping_run.process
    -> discover pagination
    -> create DiscoveryPageJob rows
    -> DISCOVERY_COMPLETED

Beat maintenance.tick
    -> discovery.dispatch_batch
    -> discovery.process_batch

Beat maintenance.tick
    -> putusan.dispatch_pending
    -> putusan.process x N

terminal lifecycle
    -> RunFinalizerService
```

## 10. Final invariant check

After the run reaches a terminal state:

```powershell
python scripts/phase13_acceptance.py --run-id <RUN_ID>
```

No `PROCESSING` rows should remain. SUCCESS Putusan rows must have a PDF URL, and non-SUCCESS rows must not have one.

## 11. Failure / recovery verification

For the resilience test, stop the worker while one or more rows are PROCESSING, then start it again and allow Beat to continue running.

Expected behavior:

```text
PROCESSING
    -> stale lease recovery
    -> FAILED_RETRY
    -> next_retry_at eligible
    -> re-dispatch
    -> PROCESSING
    -> terminal state
```

The database remains the source of truth; Redis is the Celery transport/backend.
