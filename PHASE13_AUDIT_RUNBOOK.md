# Phase 13 Audit-Fix Candidate

This package is based on the latest `audit-phase-13.zip` source plus the audited fixes.
The old `tests/` directory is intentionally not treated as the acceptance source of truth.

## 1. Install / syntax check

From the project root:

```powershell
python -m py_compile $(Get-ChildItem -Recurse -Filter *.py | Where-Object { $_.FullName -notmatch '\\tests\\' -and $_.FullName -notmatch '__pycache__' } | ForEach-Object { $_.FullName })
```

On Windows PowerShell, if command substitution is inconvenient, use the project's normal compile command or run:

```powershell
python scripts/phase13_acceptance.py
```

## 2. Run static/runtime acceptance

```powershell
$env:ENV_FILE='.env.test'
python scripts/phase13_acceptance.py
```

Expected:

```text
PASS sequential pagination: 1 -> 2 -> 3 -> stop
PASS Celery Beat maintenance schedule: 30s
PHASE 13 ACCEPTANCE: PASS
```

## 3. Start Redis/PostgreSQL

Use the existing local Docker setup. Do not use `docker compose down -v`.

## 4. Start Celery worker

```powershell
$env:ENV_FILE='.env.test'
$env:DATABASE_URL='postgresql+psycopg://ma_admin:ma_rahasia_123@localhost:15432/ma_e2e_1997'
celery -A celery_app.celery worker --pool=solo --loglevel=INFO
```

## 5. Start Celery Beat in a second terminal

```powershell
$env:ENV_FILE='.env.test'
$env:DATABASE_URL='postgresql+psycopg://ma_admin:ma_rahasia_123@localhost:15432/ma_e2e_1997'
celery -A celery_app.celery beat --loglevel=INFO
```

Beat must emit `maintenance.tick` every 30 seconds.

## 6. Run an E2E run

Use the project's current run creation / processing command as before.
The important invariant is that the run is created first and `scraping_run.process` is started with its `run_id`.

After discovery creates PageJobs, Beat will automatically wake the discovery dispatcher.
After discovery is terminal, Beat will automatically wake the Putusan dispatcher.
Retries are also picked up after `next_retry_at`.

## 7. Verify DB invariants

For example, for run 3:

```powershell
$env:ENV_FILE='.env.test'
$env:DATABASE_URL='postgresql+psycopg://ma_admin:ma_rahasia_123@localhost:15432/ma_e2e_1997'
python scripts/phase13_acceptance.py --run-id 3
```

Expected DB invariants:

- no PROCESSING Putusan
- no PROCESSING DiscoveryPageJob
- no retry_count > 3
- SUCCESS always has url_pdf
- non-SUCCESS never has url_pdf
- FAILED_PERMANENT has retry_count=3 and next_retry_at=NULL

## 8. Retry acceptance

Create or use a Putusan that produces a retryable result.
Confirm:

1. first failure -> FAILED_RETRY;
2. next_retry_at is in the future;
3. immediate maintenance tick does not process it;
4. after next_retry_at, Beat schedules it;
5. final third failure -> FAILED_PERMANENT;
6. no fourth attempt.

## 9. Stale recovery acceptance

For a controlled test database only, create a PROCESSING Putusan/PageJob whose processing timestamp is older than its lease.
Run `maintenance.tick` and verify it returns to FAILED_RETRY, or FAILED_PERMANENT when retry_count reaches 3.

## 10. Sequential pagination acceptance

The included acceptance script verifies the actual fallback traversal logic:

```text
page 1 -> Next -> page 2 -> Next -> page 3 -> no Next -> stop
```

The live scraper should additionally be exercised against a known directory where predictive pagination is deliberately unavailable.

## 11. Production sign-off gate

Do not mark Phase 13 complete until:

- sequential fallback passes;
- Beat is running;
- delayed retry passes;
- stale recovery passes;
- run isolation passes;
- finalizer reaches COMPLETED/FAILED correctly;
- no PROCESSING rows remain after normal completion;
- DB acceptance script passes;
- one full E2E run completes without manual dispatcher intervention.
