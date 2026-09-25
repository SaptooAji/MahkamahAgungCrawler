import asyncio
import logging
from datetime import datetime
from playwright.async_api import async_playwright

class MACrawlerEngine:
    def __init__(self, job_id: str, tahun: str):
        self.job_id = job_id
        self.tahun = tahun
        # Inject Repository (SOLID) untuk update database
        # self.db_repo = PostgresRepository() 

    async def run(self):
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            
            start_url = f"https://putusan3.mahkamahagung.go.id/search.html?tahun={self.tahun}"
            await page.goto(start_url)
            
            # Misal hasil scraping mendeteksi ada 10.000 halaman
            total_pages = 10000 
            # await self.db_repo.update_job_total(self.job_id, total_pages)

            current_page = 1
            while current_page <= total_pages:
                logging.info(f"Scraping halaman {current_page}...")
                
                # 1. Ekstrak Metadata & Tautan
                # list_dokumen = await self._extract_data(page)
                
                # 2. Simpan list_dokumen ke PostgreSQL
                # await self.db_repo.save_documents(list_dokumen)
                
                # 3. Update Progress ke DB agar Web UI bisa membacanya
                # await self.db_repo.update_job_progress(self.job_id, current_page)

                # Klik next page
                current_page += 1
                await asyncio.sleep(5) # Delay anti-blokir

            await browser.close()
            # await self.db_repo.mark_job_completed(self.job_id)