# Phase 13 Final Changelog

## Scope locked

- FastAPI remains deferred from the MVP.
- `scraper/engine.py`, `scraper/test_nodriver.py`, `scraper/test_scraper.py`, and `scraper/browser.py` remain historical files and are not architectural references.
- `logging_config.py` is included as the supplied source module required by `celery_app/celery.py`.

## Production orchestration changes

### Discovery

Old behavior:

```text
Beat / dispatcher
    -> process batch
    -> batch self-schedules next batch
```

New behavior:

```text
Beat
    -> discovery_page.dispatch_batch
    -> atomic PostgreSQL reservation
    -> discovery_page.process_batch
    -> terminal DB state
    -> next Beat tick
```

The historical Celery task name `discovery_page.dispatch_pending` is no longer registered.

### Putusan

Old behavior:

```text
dispatcher
    -> Celery chord
    -> callback dispatcher
    -> next chord
```

New behavior:

```text
Beat
    -> putusan.dispatch_pending
    -> atomic PostgreSQL reservation
    -> one child task per Putusan
    -> terminal DB state
    -> next Beat tick
```

No chord callback remains in the production dispatcher.

## Duplicate scheduling protection

PostgreSQL advisory transaction locks serialize scheduler decisions per `(run_id, domain)`.

A dispatcher also refuses to start another batch while rows for the same run are already `PROCESSING`.

## Duplicate child delivery protection

A dispatcher first reserves rows using a dispatch owner ID and a processing token.

A child task must atomically adopt that reservation before starting the browser. A duplicate child delivery therefore loses the fence and exits without browser work.

## New Phase 13 test

```text
python -m tests.manual_phase13_dispatch_idempotency_test
```

The test verifies:

- discovery dispatcher cannot create a second active batch;
- Putusan dispatcher cannot create a second active batch;
- dispatch ownership and tokens are persisted;
- duplicate child delivery cannot adopt the same reservation twice.
