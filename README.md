# MahkamahAgungCrawler

Crawler untuk mengambil daftar putusan Mahkamah Agung dari
`putusan3.mahkamahagung.go.id`, memproses halaman detail secara asynchronous,
dan menyimpan state crawling di PostgreSQL. Celery + Redis digunakan untuk
menjalankan pekerjaan di background dan maintenance berkala.

Project ini berfokus pada **scraper MVP**. API/FastAPI bukan bagian dari runtime
MVP.

## Architecture

```text
                     ┌──────────────────────┐
                     │  scripts/create_mvp  │
                     │  scripts/enqueue     │
                     └──────────┬───────────┘
                                │
                                ▼
                     ┌──────────────────────┐
                     │   Celery + Redis     │
                     │ process / maintenance│
                     └──────────┬───────────┘
                                │
             ┌──────────────────┴──────────────────┐
             ▼                                     ▼
     ScrapingRun discovery                 Maintenance tick
             │                                     │
             ▼                                     ▼
     scraper/pagination                recovery + DB fenced dispatch
             │
             ▼
     DiscoveryPageJob
             │
             ▼
     scraper/discovery_page
             │
             ▼
     Putusan rows
             │
             ▼
     scraper/detail_page
             │
             ▼
     PDF / terminal status

PostgreSQL adalah source of truth untuk ownership, state, retry, dan
idempotency. Repository menangani persistence/claim, service menangani
business lifecycle, dan Celery menangani orchestration.
```

### Main layers

- `scraper/` — browser-facing scraping logic: pagination, discovery page,
  dan detail page.
- `repositories/` — claim, persistence, status transition, dan stale recovery.
- `services/` — orchestration domain: discovery run, page job, Putusan worker,
  dispatching, dan run finalization.
- `models/` — SQLAlchemy domain/persistence models.
- `celery_app/` — background task orchestration dan maintenance scheduler.
- `alembic/` — schema migrations.
- `scripts/` — operational CLI entry points yang masih menjadi jalur resmi.
- `tests/` — manual/integration regression scripts yang relevan dengan runtime
  final. Folder ini sengaja masih flat; pengelompokan dilakukan pada fase
  berikutnya.

## Runtime flow

1. Buat `ScrapingRun` dengan `scripts.create_mvp_run`.
2. Enqueue run dengan `scripts.enqueue_scraping_run`.
3. Celery menjalankan discovery pagination.
4. Pagination menggunakan mode `PREDICTIVE` bila template + total page dapat
   ditentukan, dan fallback ke `SEQUENTIAL` bila tidak tersedia.
5. Discovery page jobs di-claim dan diproses secara fenced.
6. Putusan diproses dari halaman detail dan PDF dicari.
7. Transient error masuk ke `FAILED_RETRY`; retry yang habis menjadi
   `FAILED_PERMANENT`.
8. Maintenance Beat berjalan setiap 30 detik untuk stale recovery dan
   dispatch yang dilindungi DB fence.
9. Run difinalisasi ketika seluruh pekerjaan berada pada state terminal.

## Failure semantics

`FAILED_RETRY` berarti pekerjaan masih dapat dicoba kembali.

`FAILED_PERMANENT` berarti retry untuk **crawl tersebut** sudah habis dan state
menjadi terminal. Status ini tidak berarti resource di website secara absolut
pasti tidak tersedia. Website eksternal dapat memberikan respons berbeda antar
crawl, termasuk Cloudflare challenge yang bersifat transient.

Run juga memiliki retry lifecycle sendiri untuk kegagalan discovery/pagination
yang bersifat transient.

## Database

PostgreSQL adalah source of truth. Schema dikelola dengan Alembic.
Migration head saat ini adalah migration Phase 13 run retry.

```bash
alembic upgrade head
alembic current
```

Jangan melewati migration chain atau menghapus migration lama; semuanya bagian
dari sejarah schema yang dibutuhkan untuk upgrade database.

## Local infrastructure

`docker-compose.yml` menyediakan PostgreSQL dan Redis serta tooling opsional
pgAdmin dan RedisInsight.

```bash
docker compose up -d postgres redis
```

Jangan menggunakan `docker compose down -v` untuk database test yang masih
dibutuhkan.

## Environment

Aplikasi membaca `ENV_FILE`, lalu koneksi database dapat diberikan melalui
`DATABASE_URL`. Untuk Celery, gunakan `REDIS_HOST`, `REDIS_PORT`, dan `REDIS_DB`.

Contoh konfigurasi test yang umum:

```bash
export ENV_FILE='.env.test'
export DATABASE_URL='postgresql+psycopg://<user>:<password>@localhost:15432/<test_db>'
export REDIS_HOST='localhost'
export REDIS_PORT='6379'
export REDIS_DB='3'
export SCRAPING_RUN_RETRY_DELAY_SECONDS='10'
```

Nilai koneksi di atas adalah contoh environment lokal/test, bukan secret
production.

## Running the crawler

Start worker:

```bash
celery -A celery_app.celery worker --pool=solo --loglevel=INFO
```

Start Beat:

```bash
celery -A celery_app.celery beat --loglevel=INFO
```

Create a run:

```bash
python -m scripts.create_mvp_run \
  --year 1997 \
  --url 'https://putusan3.mahkamahagung.go.id/direktori/index/tahunjenis/putus/tahun/1997.html'
```

Enqueue a run:

```bash
python -m scripts.enqueue_scraping_run --run-id "$RUN_ID"
```

Monitor state:

```bash
python -m scripts.show_run_state --run-id "$RUN_ID"
```

Tidak perlu menjalankan dispatcher discovery/Putusan secara manual pada jalur
normal. Scheduler + DB dispatch fence adalah mekanisme resmi orchestration.

## Acceptance

Acceptance Phase 13 menggabungkan pemeriksaan pagination fallback, Beat schedule,
orchestration contract, dan invariant database untuk run yang sudah selesai.

```bash
python -m scripts.phase13_acceptance --run-id "$RUN_ID"
```

Pengujian live terhadap website eksternal bersifat environment-dependent karena
Cloudflare dan kondisi layanan dapat berbeda antar-run.

## Testing

Test manual/integration regression dikelompokkan berdasarkan concern di dalam
`tests/`: persistence, services, workers, orchestration, scraper, dan live.
Nama file tidak lagi mengikuti nomor phase historis.

Daftar struktur dan cara menjalankan test ada di [`tests/README.md`](tests/README.md).

## Logging

`logging_config.py` mengonfigurasi logging aplikasi dan Celery serta rotating
file handler. Konfigurasi logging dapat dipanggil berulang kali tanpa membuat
handler duplikat.

## Current scope

Project saat ini sengaja tidak membawa layer API/FastAPI sebagai capability
runtime. Fokusnya adalah crawler, persistence, background orchestration,
recovery, retry, idempotency, dan observability dasar.
