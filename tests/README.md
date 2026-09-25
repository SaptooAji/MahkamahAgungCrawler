# Test Cases --- Database, Repository, dan Lifecycle

Dokumen ini mendokumentasikan test manual yang saat ini digunakan untuk
memvalidasi fondasi database, repository, discovery, processing
lifecycle, concurrency, dan ownership pada project
**MahkamahAgungCrawler**.

> Scope dokumen ini adalah layer database/domain/service sebelum
> integrasi Nodriver dan Celery. Test-test ini menjadi regression
> checkpoint sebelum scraper di-refactor untuk menggunakan repository
> dan lifecycle service.

------------------------------------------------------------------------

## 1. Lokasi README dalam Clean Architecture

README ini sebaiknya ditempatkan di:

``` text
tests/README.md
```

Alasannya:

-   Isinya khusus dokumentasi test.
-   Menjelaskan tujuan, skenario, cara menjalankan, dan expected result
    test.
-   Tidak termasuk business logic.
-   Tidak termasuk dokumentasi deployment atau database production.
-   Dekat dengan source test sehingga developer yang mengubah test dapat
    langsung menemukan dokumentasinya.

Struktur project yang direkomendasikan:

``` text
MahkamahAgungCrawler/
├── README.md
├── .env
├── docker-compose.yml
├── requirements.txt
├── alembic.ini
│
├── alembic/
│   └── versions/
│
├── models/
├── database/
├── repositories/
├── services/
├── scraper/
├── tasks/
├── celery_app/
│
└── tests/
    ├── README.md
    ├── __init__.py
    ├── manual_claim_test.py
    ├── manual_claim_by_id_test.py
    ├── manual_concurrency_test.py
    ├── manual_discovery_concurrency_test.py
    ├── manual_discovery_service_test.py
    ├── manual_processing_token_test.py
    ├── manual_lifecycle_test.py
    └── manual_lifecycle_service_test.py
```

README root (`README.md`) tetap digunakan untuk dokumentasi project
secara keseluruhan. `tests/README.md` digunakan untuk detail testing.

------------------------------------------------------------------------

# 2. Tujuan Test Suite

Test suite ini memvalidasi beberapa invariant penting:

1.  Putusan dapat di-claim secara aman.
2.  Dua worker tidak mengambil row yang sama.
3.  Discovery bersifat idempotent.
4.  Claim berdasarkan ID bersifat deterministik.
5.  Processing memiliki ownership melalui `processing_worker_id`.
6.  Processing memiliki fencing mechanism melalui `processing_token`.
7.  Lifecycle dapat berpindah dari `PROCESSING` ke state akhir yang
    sesuai.
8.  Processing yang stale dapat direcover.
9.  Service layer meneruskan operasi lifecycle ke repository dengan
    benar.
10. Database tetap menjadi source of truth.

Arsitektur yang sedang divalidasi:

``` text
                 PostgreSQL
                     │
                     ▼
              ┌──────────────┐
              │    Models    │
              └──────┬───────┘
                     │
                     ▼
              ┌──────────────┐
              │ Repository   │
              └──────┬───────┘
                     │
                     ▼
              ┌──────────────┐
              │   Services   │
              └──────┬───────┘
                     │
          ┌──────────┴──────────┐
          ▼                     ▼
     Discovery flow       Processing flow
                                │
                    ┌───────────┼───────────┐
                    ▼           ▼           ▼
                 SUCCESS   FAILED_RETRY  UNPUBLISHED
                                │
                                ▼
                       Stale Recovery
```

------------------------------------------------------------------------

# 3. Status Lifecycle

Status utama pada `Putusan`:

``` text
PENDING
   │
   ▼
PROCESSING
   │
   ├──────────────► SUCCESS
   │
   ├──────────────► UNPUBLISHED
   │
   └──────────────► FAILED_RETRY
                         │
                         ▼
                    PROCESSING
```

Untuk worker yang mati atau processing yang tidak selesai:

``` text
PROCESSING
    │
    │ lease expired
    ▼
FAILED_RETRY
    │
    │ next_retry_at reached
    ▼
PROCESSING
```

------------------------------------------------------------------------

# 4. Test Case

## 4.1 `manual_claim_test.py`

### Tujuan

Memvalidasi mekanisme batch claim dari database.

### Yang diuji

-   Row dengan status `PENDING` dapat di-claim.
-   Row hasil claim berubah menjadi `PROCESSING`.
-   Claim menggunakan batch size.
-   Informasi worker disimpan pada row.

### Konsep penting

Repository menggunakan:

``` text
SELECT ... FOR UPDATE SKIP LOCKED
```

sehingga worker dapat mengambil row yang belum sedang dikunci worker
lain.

### Command

``` bash
python -m tests.manual_claim_test
```

### Expected

Test selesai tanpa exception dan menghasilkan daftar row yang berhasil
di-claim.

------------------------------------------------------------------------

## 4.2 `manual_claim_by_id_test.py`

### Tujuan

Memvalidasi claim terhadap satu `Putusan` berdasarkan `id`.

### Skenario

  Skenario                           Expected
  ---------------------------------- -------------------
  ID valid dan `PENDING`             berhasil di-claim
  ID yang sama di-claim kedua kali   ditolak / `None`
  ID tidak ada                       `None`

### Command

``` bash
python -m tests.manual_claim_by_id_test
```

### Expected output

``` text
CLAIM EXACT ID: PASS
CANNOT CLAIM TWICE: PASS
UNKNOWN ID: PASS

================================
ALL CLAIM BY ID TESTS: PASS
================================
```

------------------------------------------------------------------------

## 4.3 `manual_concurrency_test.py`

### Tujuan

Memvalidasi bahwa dua worker concurrent tidak mengambil row yang sama.

### Skenario

Empat row disiapkan:

``` text
1
2
3
4
```

Dua worker melakukan claim secara bersamaan.

### Expected behavior

Contoh hasil:

``` text
Worker B: claimed IDs = [110, 111]
Worker A: claimed IDs = [112, 113]
```

Tidak boleh terjadi:

``` text
Worker A: [110, 111]
Worker B: [110, 111]
```

### Command

``` bash
python -m tests.manual_concurrency_test
```

### Invariant

``` text
claimed_by_worker_A ∩ claimed_by_worker_B = ∅
```

Dengan kata lain, tidak boleh ada overlap.

------------------------------------------------------------------------

## 4.4 `manual_discovery_concurrency_test.py`

### Tujuan

Memvalidasi idempotensi discovery ketika URL yang sama ditemukan oleh
dua worker.

### Skenario

Dua worker menemukan:

``` text
https://example.com/discovery-concurrent/1
```

secara bersamaan.

### Expected

Hanya satu row dibuat.

Contoh:

``` text
Worker B: id=114, created=True
Worker A: id=114, created=False

Total rows: 1
```

### Mekanisme

Database menggunakan:

``` text
UNIQUE(url_detail)
```

dan PostgreSQL:

``` text
ON CONFLICT DO NOTHING
```

### Command

``` bash
python -m tests.manual_discovery_concurrency_test
```

### Invariant

``` text
jumlah row untuk url_detail yang sama = 1
```

------------------------------------------------------------------------

## 4.5 `manual_discovery_service_test.py`

### Tujuan

Memvalidasi bahwa `DiscoveryService` menggunakan repository untuk
menyimpan hasil discovery.

### Yang diuji

-   Discovery service dapat menyimpan `DiscoveredPutusan`.
-   ID database dikembalikan.
-   Operasi discovery tetap idempotent.
-   Row yang sudah ada tidak dibuat ulang.

### Command

``` bash
python -m tests.manual_discovery_service_test
```

Contoh hasil:

``` text
Putusan ID: 61
Created: False
```

`Created: False` dapat menjadi hasil yang benar apabila URL tersebut
memang sudah ada dari test sebelumnya.

------------------------------------------------------------------------

## 4.6 `manual_processing_token_test.py`

### Tujuan

Memvalidasi ownership dan fencing mechanism untuk processing.

### Mengapa `processing_token` diperlukan?

`processing_worker_id` saja belum cukup untuk menjamin bahwa worker lama
tidak dapat menulis hasil setelah lease-nya diambil alih worker lain.

Karena itu setiap claim menghasilkan token baru:

``` text
processing_token = UUID
```

Worker harus menyertakan token tersebut ketika menyelesaikan atau
menggagalkan processing.

### Skenario

1.  Worker A claim row.
2.  Worker A memperoleh token A.
3.  Processing menjadi stale.
4.  Recovery membersihkan token A.
5.  Worker B claim row.
6.  Worker B memperoleh token B.
7.  Token A tidak boleh digunakan untuk mengubah hasil.
8.  Worker B tetap memiliki ownership.
9.  Worker B dapat menyelesaikan processing.

### Expected output

``` text
WORKER A CLAIM: PASS
STALE RECOVERY: PASS
OLD TOKEN CLEARED: PASS
WORKER B CLAIM: PASS
TOKEN ROTATION: PASS
STALE WORKER REJECTED: PASS
WORKER B OWNERSHIP PRESERVED: PASS
NEW WORKER SUCCESS: PASS
OWNERSHIP CLEARED: PASS
```

### Command

``` bash
python -m tests.manual_processing_token_test
```

------------------------------------------------------------------------

## 4.7 `manual_lifecycle_test.py`

### Tujuan

Memvalidasi lifecycle repository secara langsung.

### Skenario

#### SUCCESS

``` text
PENDING
   ↓
PROCESSING
   ↓
SUCCESS
```

#### FAILED_RETRY

``` text
PENDING
   ↓
PROCESSING
   ↓
FAILED_RETRY
   ↓
PROCESSING
```

Claim ulang hanya boleh dilakukan ketika:

``` text
next_retry_at <= current_time
```

#### Stale Recovery

``` text
PROCESSING
   ↓
lease expired
   ↓
FAILED_RETRY
```

### Command

``` bash
python -m tests.manual_lifecycle_test
```

### Expected

``` text
SUCCESS lifecycle: PASS
FAILED_RETRY lifecycle: PASS
STALE PROCESSING recovery: PASS

====================================
ALL LIFECYCLE TESTS: PASS
====================================
```

------------------------------------------------------------------------

## 4.8 `manual_lifecycle_service_test.py`

### Tujuan

Memvalidasi service layer lifecycle.

Test ini sengaja menggunakan `claim_by_id()` agar setiap skenario
deterministic dan tidak tergantung pada row lain yang mungkin sedang
`PENDING`.

### Skenario

``` text
claim_by_id()
    ↓
PROCESSING
    ├── mark_success()
    ├── mark_failed_retry()
    └── mark_unpublished()
```

Selain itu:

``` text
PROCESSING
    ↓
recover_stale()
    ↓
FAILED_RETRY
```

### Command

``` bash
python -m tests.manual_lifecycle_service_test
```

### Expected

``` text
SERVICE SUCCESS: PASS
SERVICE RETRY: PASS
SERVICE UNPUBLISHED: PASS
SERVICE STALE RECOVERY: PASS

========================================
ALL LIFECYCLE SERVICE TESTS: PASS
========================================
```

### Catatan `RECOVERED COUNT`

`recover_stale()` bekerja secara global terhadap seluruh `Putusan` yang
stale.

Karena itu output seperti:

``` text
RECOVERED COUNT: 2
```

tetap valid.

Test tidak seharusnya mengasumsikan:

``` text
recovered == 1
```

karena database dapat memiliki stale `PROCESSING` row dari test atau
eksperimen sebelumnya.

Yang harus dipastikan adalah **row milik test tersebut benar-benar
berubah**:

``` text
PROCESSING
    ↓
FAILED_RETRY
```

dan:

``` text
processing_worker_id = NULL
processing_started_at = NULL
processing_token = NULL
next_retry_at != NULL
```

------------------------------------------------------------------------

# 5. Urutan Regression Test

Jalankan test dalam urutan berikut:

``` bash
python -m tests.manual_claim_test
python -m tests.manual_claim_by_id_test
python -m tests.manual_concurrency_test
python -m tests.manual_discovery_concurrency_test
python -m tests.manual_discovery_service_test
python -m tests.manual_processing_token_test
python -m tests.manual_lifecycle_test
python -m tests.manual_lifecycle_service_test
```

Atau satu per satu jika ingin mengetahui test mana yang gagal.

------------------------------------------------------------------------

# 6. Regression Checkpoint Saat Ini

Pada checkpoint saat dokumentasi ini dibuat, seluruh test berikut telah
berhasil:

``` text
manual_claim_test.py                  PASS
manual_claim_by_id_test.py            PASS
manual_concurrency_test.py            PASS
manual_discovery_concurrency_test.py  PASS
manual_discovery_service_test.py      PASS
manual_processing_token_test.py       PASS
manual_lifecycle_test.py              PASS
manual_lifecycle_service_test.py      PASS
```

Kesimpulan checkpoint:

``` text
Database
   ↓
Models
   ↓
Repository
   ↓
Discovery Service
   ↓
Lifecycle Service
```

telah melewati regression test yang tersedia saat ini.

------------------------------------------------------------------------

# 7. Boundary Test Suite

Test ini **belum** memvalidasi:

-   Nodriver browser automation.
-   Pagination website Mahkamah Agung.
-   Deteksi tombol `Last`.
-   Fallback pagination `Next`.
-   Ekstraksi URL PDF.
-   Download PDF.
-   Penanganan halaman `500 - Exception Error` pada website.
-   Celery broker.
-   Celery worker.
-   Celery retry.
-   Redis.
-   End-to-end scraping.

Komponen tersebut menjadi tahap berikutnya.

------------------------------------------------------------------------

# 8. Prinsip Clean Architecture

Test tidak boleh menjadi tempat business logic.

Pembagian tanggung jawab:

``` text
tests/
    └── verifies behavior

services/
    └── application/use-case orchestration

repositories/
    └── database access

models/
    └── persistence/domain representation

database/
    └── connection/session

scraper/
    └── external website/browser interaction

tasks/
    └── background job orchestration

celery_app/
    └── Celery configuration
```

Dengan demikian test hanya memanggil public interface dari layer yang
sedang diuji.

Contoh:

``` python
putusan_lifecycle_service.claim_by_id(...)
```

bukan:

``` python
session.execute(...)
```

untuk menguji service layer.

------------------------------------------------------------------------

# 9. Aturan Saat Menambah Test Baru

Untuk test baru:

1.  Gunakan prefix URL khusus test.
2.  Buat cleanup yang hanya menghapus data milik test.
3.  Jangan menghapus seluruh tabel production/domain.
4.  Gunakan `python -m tests.<module>` saat menjalankan test.
5.  Gunakan `claim_by_id()` untuk skenario yang membutuhkan row
    tertentu.
6.  Gunakan `claim()` untuk menguji batch worker behavior.
7.  Jangan membuat assertion yang bergantung pada urutan ID global
    database kecuali memang bagian dari test.
8.  Jangan menganggap jumlah global stale recovery selalu `1`.
9.  Test concurrency harus memverifikasi tidak ada overlap.
10. Test idempotency harus memverifikasi jumlah row tidak bertambah
    secara tidak semestinya.

------------------------------------------------------------------------

# 10. Next Step

Setelah regression checkpoint ini, tahap berikutnya adalah
mengintegrasikan **Nodriver discovery flow** dengan:

``` text
Nodriver
   ↓
DiscoveryService
   ↓
PutusanRepository
   ↓
PostgreSQL
```

Celery belum menjadi fokus pada tahap tersebut.

Setelah integrasi Nodriver berhasil dan test discovery-to-database
stabil, barulah Celery dapat ditempatkan di atas application/service
layer:

``` text
Celery Task
    ↓
Application/Service
    ↓
Repository
    ↓
PostgreSQL
```

Dengan desain tersebut, Celery tidak menjadi pemilik state scraping.
PostgreSQL tetap menjadi source of truth.
