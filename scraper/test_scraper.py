import asyncio
from playwright.async_api import async_playwright

async def main():
    print("Memulai pengujian Playwright (Pembaruan Strategi Menunggu/Wait)...")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process"
            ]
        )
        
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1366, "height": 768}
        )
        
        page = await context.new_page()
        
        tahun_target = "2021"
        url_list_page = f"https://putusan3.mahkamahagung.go.id/direktori/index/tahunjenis/putus/tahun/{tahun_target}.html"
        
        print(f"\n[STEP 1] Mengakses Halaman Daftar: {url_list_page}")
        
        try:
            # UBAH 1: Gunakan domcontentloaded agar tidak terjebak networkidle
            await page.goto(url_list_page, wait_until="domcontentloaded", timeout=60000)
            
            print("Halaman dimuat. Menunggu elemen daftar putusan muncul...")
            # UBAH 2: Explicit wait - Tunggu persis sampai elemen <a> direktori muncul (maksimal 20 detik)
            try:
                await page.wait_for_selector("a[href*='/direktori/putusan/']", timeout=20000)
            except Exception:
                print("[WARNING] Elemen putusan tidak muncul! Mengambil screenshot untuk melihat apa yang memblokir...")
                await page.screenshot(path="debug_blocked_list.png")
                return # Hentikan proses agar kita bisa mengecek screenshot

            # Jika lolos pengecekan di atas, berarti list berhasil dimuat
            link_locator = page.locator("a[href*='/direktori/putusan/']")
            jumlah_ditemukan = await link_locator.count()
            print(f"Ditemukan {jumlah_ditemukan} tautan putusan di halaman ini.")

            limit_tes = min(2, jumlah_ditemukan)
            daftar_putusan = []
            
            for i in range(limit_tes):
                elemen = link_locator.nth(i)
                judul = await elemen.inner_text()
                href = await elemen.get_attribute("href")
                
                if href and href.startswith("/"):
                    href = f"https://putusan3.mahkamahagung.go.id{href}"
                    
                daftar_putusan.append({"judul": judul.strip(), "url_detail": href})
                print(f"-> Disimpan ke memori: {judul.strip()[:60]}...")

            print("\n[STEP 2] Memulai Ekstraksi URL PDF dari Halaman Detail...")
            
            for index, data in enumerate(daftar_putusan):
                print(f"\nProses {index+1}/{limit_tes} - Mengakses: {data['url_detail']}")
                
                # UBAH 3: Gunakan domcontentloaded untuk halaman detail juga
                await page.goto(data['url_detail'], wait_until="domcontentloaded", timeout=60000)
                await asyncio.sleep(3) # Jeda natural agar web merespons
                
                if index == 0:
                    await page.screenshot(path="bukti_halaman_detail.png", full_page=True)
                
                pdf_locator = page.locator("a[href$='.pdf']")
                jumlah_pdf = await pdf_locator.count()
                
                if jumlah_pdf > 0:
                    pdf_url = await pdf_locator.first.get_attribute("href")
                    if pdf_url and pdf_url.startswith("/"):
                         pdf_url = f"https://putusan3.mahkamahagung.go.id{pdf_url}"
                         
                    print(f"[BERHASIL] Tautan Download PDF ditemukan:\n>> {pdf_url}")
                else:
                    print(f"[GAGAL] Tidak menemukan tautan berakhiran .pdf di halaman detail.")
                    fallback_locator = page.locator("a:has-text('Download'), a:has-text('PDF')")
                    if await fallback_locator.count() > 0:
                         fallback_url = await fallback_locator.first.get_attribute("href")
                         print(f"   [Alternatif] Ditemukan tombol dengan kata PDF/Download: {fallback_url}")
            
        except Exception as e:
            print(f"\n[ERROR] Skrip terhenti karena masalah teknis: {e}")
            await page.screenshot(path="debug_error_fatal.png")
        
        finally:
            await browser.close()
            print("\nPengujian selesai dan browser ditutup.")

if __name__ == "__main__":
    asyncio.run(main())