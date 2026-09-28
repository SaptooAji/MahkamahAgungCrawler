# Phase 13 Audit Scope / Source of Truth

## MVP scope

The current MVP is only the Mahkamah Agung scraping pipeline. FastAPI is intentionally deferred.

## Historical scraper files excluded from active architecture

```text
scraper/engine.py
scraper/test_nodriver.py
scraper/test_scraper.py
scraper/browser.py
```

They are retained as historical source but must not be used as the implementation reference for the current scraper architecture.

## Active scraper files

All other files under `scraper/` are in scope for Phase 13 audit, especially:

```text
scraper/pagination.py
scraper/discovery_page.py
scraper/detail_page.py
```

## Production scheduling contract

There is exactly one scheduler concept for each domain:

```text
Celery Beat / maintenance.tick
    -> discovery_page.dispatch_batch
    -> discovery_page.process_batch

Celery Beat / maintenance.tick
    -> putusan.dispatch_pending
    -> putusan.process
```

Batch processing does not self-chain anymore.

Dispatch is fenced in PostgreSQL before child tasks are enqueued. Child tasks atomically adopt the reservation before starting browser work, so duplicate Celery delivery cannot start duplicate processing.
