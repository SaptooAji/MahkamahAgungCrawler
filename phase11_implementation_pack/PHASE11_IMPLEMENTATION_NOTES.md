# Phase 11 implementation notes

## 1. `models/scraping_run.py`

Add:

```python
DISCOVERY_COMPLETED = "DISCOVERY_COMPLETED"
```

to `ScrapingRunStatus`.

Keep the existing `COMPLETED` value.

## 2. `models/putusan.py`

Add:

```python
run_id: Mapped[int | None] = mapped_column(
    ForeignKey("scraping_runs.id", ondelete="SET NULL"),
    nullable=True,
)
```

Import `ForeignKey`.

`run_id` is metadata/ownership for a scraping run. It is NOT part of Putusan identity. Keep:

```python
url_detail = mapped_column(..., unique=True)
```

## 3. `repositories/putusan_repository.py`

Extend `upsert_discovered_putusan()` with:

```python
run_id: int | None = None
```

For INSERT:

```python
run_id=run_id,
```

For an existing row, assign `run_id` only when a concrete run is supplied and the row is not currently owned by another active processing run. For the initial Phase 11 rollout, the safest rule is:

```python
if run_id is not None and putusan.run_id is None:
    putusan.run_id = run_id
```

Do NOT overwrite another run's ownership automatically.

## 4. `services/discovery_service.py`

Extend `DiscoveredPutusan`:

```python
run_id: int | None = None
```

Extend `save_discovered_putusan()`:

```python
run_id=data.run_id,
```

## 5. `services/discovery_page_worker.py`

When constructing `DiscoveredPutusanData`, pass:

```python
run_id=claimed.run_id,
```

Therefore `ClaimedDiscoveryPage` should contain `run_id`.

Populate it from:

```python
page_job.run_id
```

when claiming the page job.

## 6. `services/discovery_run_service.py`

Keep the existing `mark_discovery_completed()` method temporarily for Phase 7A backward compatibility.

Add/use:

```python
run_lifecycle_service.mark_discovery_phase_completed(...)
```

for the new production orchestration.

Do not set `finished_at` at discovery completion.

## 7. Finalizer

Use the generated:

`run_lifecycle_service.py`

The finalizer is intentionally global to a run but scoped by:

```python
DiscoveryPageJob.run_id == run.id
Putusan.run_id == run.id
```

It must never use `tahun` alone to determine run ownership.

## 8. Alembic

Install the generated migration:

`phase11_run_lifecycle_migration.py`

Rename it to the project's normal Alembic filename convention.

Before upgrade:

```bash
ENV_FILE=.env.test alembic current
```

Then:

```bash
ENV_FILE=.env.test alembic upgrade head
```

Verify:

```bash
ENV_FILE=.env.test alembic current
```

## Important

Do not run the Phase 11 test until the model/repository/worker changes above are applied. The test is intentionally designed around explicit `run_id` ownership so it cannot accidentally pass by mixing Putusan from another run.
