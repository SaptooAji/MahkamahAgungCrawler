# workers/tasks.py
from .celery_app import celery_app
from scraper.engine import MACrawlerEngine
import asyncio

@celery_app.task(bind=True)
def start_crawling_task(self, job_id: str, tahun: str):
    """
    Fungsi ini dieksekusi di background oleh Celery Worker.
    Karena Celery berjalan synchronous secara default, 
    kita membungkus async Playwright dengan asyncio.run
    """
    # Engine menerima job_id untuk mengupdate status di DB setiap pindah halaman
    engine = MACrawlerEngine(job_id=job_id, tahun=tahun)
    
    # Jalankan coroutine Playwright
    asyncio.run(engine.run())
    
    return f"Job {job_id} Selesai"