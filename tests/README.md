# Test Suite

Folder ini berisi **manual/integration regression scripts**, bukan suite pytest
konvensional. File tetap flat pada fase ini; grouping berdasarkan layer/domain
akan dilakukan pada fase berikutnya.

## Test yang dipertahankan

### Claim, ownership, dan concurrency

```text
manual_claim_test.py
manual_claim_by_id_test.py
manual_concurrency_test.py
manual_processing_token_test.py
manual_putusan_6c_claim_idempotency_test.py
```

Memvalidasi claim, duplicate claim, ownership, processing token, dan concurrent
access terhadap PostgreSQL.

### Discovery page dan persistence

```text
manual_discovery_page_job_repository_test.py
manual_discovery_page_job_repository_idempotency_test.py
manual_discovery_page_job_repository_concurrency_test.py
manual_discovery_page_job_service_test.py
manual_discovery_page_worker_test.py
```

Memvalidasi page-job repository/service, idempotency, stale recovery, ownership,
dan integrasi worker discovery.

### Putusan lifecycle dan retry

```text
manual_lifecycle_service_test.py
manual_phase9_putusan_retry_recovery_test.py
manual_putusan_6e_retry_lifecycle_test.py
manual_putusan_worker_12_4_retry_lifecycle_test.py
```

Memvalidasi lifecycle Putusan, retry scheduling, stale recovery, dan propagation
retry melalui worker.

### Run/orchestration

```text
manual_phase10_multi_worker_concurrency_test.py
manual_phase11b_run_finalizer_test.py
manual_phase12_discovery_worker_finalizer_test.py
manual_phase13_dispatch_idempotency_test.py
manual_phase13_run_retry_lifecycle_test.py
```

Memvalidasi concurrency lintas worker, run finalization, dispatch fencing,
child-task ownership, dan lifecycle retry pada `ScrapingRun`.

### Pagination

```text
manual_pagination_template_test.py
manual_phase13_live_sequential_fallback_test_v2.py
```

Test pertama memvalidasi predictive URL template dan descriptor generation.
Test Phase 13 v2 menjalankan sequential fallback pada website Mahkamah Agung
secara live dengan browser visible dan checkpoint Cloudflare manual.

## Canonical final acceptance

Untuk verifikasi static/runtime contract:

```bash
python -m scripts.phase13_acceptance
```

Untuk verifikasi run E2E yang sudah selesai:

```bash
python -m scripts.phase13_acceptance --run-id "$RUN_ID"
```

## Operational notes

Sebagian test manual menggunakan PostgreSQL dan dapat membuat/mengubah row test.
Gunakan database test khusus dan `ENV_FILE` yang sesuai.

Test live website bersifat nondeterministic terhadap kondisi eksternal seperti
Cloudflare. Perbedaan hasil antar-run tidak otomatis berarti regression selama
state, retry, ownership, dan invariant database tetap benar.

`FAILED_PERMANENT` pada Putusan berarti retry untuk crawl tersebut exhausted,
bukan jaminan bahwa dokumen di website selalu tidak tersedia.
