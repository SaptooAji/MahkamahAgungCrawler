import os
import uuid
from datetime import datetime
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

# Impor task Celery (Pastikan file workers/tasks.py sudah ada sesuai struktur sebelumnya)
# Jika terjadi error impor saat demo, Anda bisa memberi comment pada baris ini sementara
from workers.tasks import start_crawling_task

app = FastAPI(title="MA Crawler API")

# MOCK DATABASE (Untuk kebutuhan Demo UI)
# Di versi produksi, data ini disimpan dan dibaca dari tabel PostgreSQL
fake_job_db = {}

@app.get("/", response_class=HTMLResponse)
async def read_root():
    """
    Endpoint untuk menampilkan UI Dashboard (index.html)
    """
    # Membaca file HTML dari folder web/templates
    base_dir = os.path.dirname(os.path.abspath(__file__))
    template_path = os.path.join(base_dir, "templates", "index.html")
    
    try:
        with open(template_path, "r", encoding="utf-8") as f:
            html_content = f.read()
        return HTMLResponse(content=html_content)
    except FileNotFoundError:
        return HTMLResponse(
            content="<h1>Error: File web/templates/index.html tidak ditemukan!</h1>", 
            status_code=404
        )

@app.post("/api/start-scraping")
def trigger_scraping(tahun: str = "2021"):
    """
    Endpoint yang dipicu saat tombol 'Mulai Ekstraksi' ditekan
    """
    job_id = str(uuid.uuid4())
    
    # 1. Simpan status awal ke "Database"
    fake_job_db[job_id] = {
        "total_pages": 500,  # Simulasi total halaman
        "processed_pages": 0,
        "start_time": datetime.utcnow().timestamp(),
        "status": "running"
    }
    
    # 2. Kirim perintah ke antrean Celery & Redis
    try:
        start_crawling_task.delay(job_id, tahun)
    except Exception as e:
        print(f"Peringatan Celery (Bisa diabaikan saat demo UI): {e}")
    
    # Langsung kembalikan respons agar UI tidak hang/menunggu
    return {"message": "Scraping dimulai di latar belakang", "job_id": job_id}

@app.get("/api/job-status/{job_id}")
def get_status(job_id: str):
    """
    Endpoint yang di-ping oleh UI setiap 2 detik untuk update Progress Bar
    """
    job = fake_job_db.get(job_id)
    if not job:
        return {"status": "Job tidak ditemukan"}
        
    # --- SIMULASI PROGRESS DEMO ---
    # Di versi asli, kita cukup me-return `job["processed_pages"]` dari PostgreSQL
    # Di sini kita simulasikan seolah bot sedang bergerak 2 halaman per detik
    elapsed = datetime.utcnow().timestamp() - job["start_time"]
    simulated_processed = int(elapsed * 2) 
    
    if simulated_processed > job["total_pages"]:
        simulated_processed = job["total_pages"]
        
    job["processed_pages"] = simulated_processed
    # ------------------------------

    if job["processed_pages"] == 0:
        return {"status": "Menghitung ETA..."}

    waktu_berjalan = elapsed
    kecepatan_per_halaman = waktu_berjalan / job["processed_pages"]
    sisa_halaman = job["total_pages"] - job["processed_pages"]
    
    estimasi_sisa_waktu_detik = kecepatan_per_halaman * sisa_halaman
    
    # Konversi detik ke Jam & Menit
    jam, sisa = divmod(estimasi_sisa_waktu_detik, 3600)
    menit, detik = divmod(sisa, 60)
    
    eta_text = f"Sekitar {int(jam)} Jam {int(menit)} Menit tersisa"
    if sisa_halaman <= 0:
        eta_text = "Tugas Selesai"
    
    progress_persen = round((job["processed_pages"] / job["total_pages"]) * 100, 2)
    
    return {
        "progress_persen": progress_persen,
        "halaman_selesai": f"{job['processed_pages']} / {job['total_pages']}",
        "eta_text": eta_text,
        "status": "completed" if progress_persen >= 100 else "running"
    }