# Test Suite

Folder ini berisi **manual/integration regression scripts**, bukan suite pytest
konvensional. Pada Phase 2, test dikelompokkan berdasarkan concern arsitektur,
bukan berdasarkan urutan historis phase development.

## Struktur

```text
tests/
├── persistence/
│   ├── claim_test.py
│   ├── claim_by_id_test.py
│   ├── claim_concurrency_test.py
│   ├── processing_token_test.py
│   ├── putusan_claim_idempotency_test.py
│   ├── discovery_page_job_repository_test.py
│   ├── discovery_page_job_repository_idempotency_test.py
│   └── discovery_page_job_repository_concurrency_test.py
├── services/
│   ├── lifecycle_service_test.py
│   ├── discovery_page_job_service_test.py
│   ├── putusan_retry_lifecycle_test.py
│   └── putusan_retry_recovery_test.py
├── workers/
│   ├── discovery_page_worker_test.py
│   ├── detail_worker_lifecycle_test.py
│   └── putusan_worker_retry_lifecycle_test.py
├── orchestration/
│   ├── multi_worker_concurrency_test.py
│   ├── run_finalizer_test.py
│   ├── discovery_worker_finalizer_test.py
│   ├── dispatch_idempotency_test.py
│   └── run_retry_lifecycle_test.py
├── scraper/
│   └── pagination_template_test.py
└── live/
    └── sequential_fallback_test_v2.py
```

## Execution

Test yang menyentuh PostgreSQL menggunakan `.env.test` dan database test
terisolasi. Test tersebut tidak membutuhkan Celery worker/Beat kecuali disebut
sebaliknya.

Contoh:

```bash
python -m tests.persistence.claim_by_id_test
python -m tests.services.putusan_retry_lifecycle_test
python -m tests.workers.detail_worker_lifecycle_test
python -m tests.orchestration.run_finalizer_test
python -m tests.scraper.pagination_template_test
```

Test live website hanya dijalankan secara eksplisit:

```bash
python -m tests.live.sequential_fallback_test_v2
```

Test live bersifat environment-dependent karena Cloudflare dan kondisi layanan
dapat berbeda antar-run.

## Canonical acceptance

```bash
python -m scripts.phase13_acceptance
python -m scripts.phase13_acceptance --run-id "$RUN_ID"
```

## Semantik failure

`FAILED_RETRY` berarti row/run masih eligible untuk retry. `FAILED_PERMANENT`
berarti retry untuk crawl tersebut sudah exhausted; status itu bukan jaminan
bahwa dokumen di website selalu tidak tersedia.
