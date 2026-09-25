import asyncio
import sys
import json
import warnings
import nodriver as uc

warnings.simplefilter("ignore", DeprecationWarning)

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

async def main():
    print("=======================================================")
    print("  MEMULAI PIPELINE SCRAPER (HYBRID PAGINATION) ")
    print("=======================================================")
    
    try:
        browser = await uc.start(
            headless=False, 
            browser_args=["--start-maximized", "--disable-dev-shm-usage", "--mute-audio"]
        )
        
        tahun_target = "2021"
        url_halaman_pertama = f"https://putusan3.mahkamahagung.go.id/direktori/index/tahunjenis/putus/tahun/{tahun_target}.html"
        
        daftar_putusan_global = []
        page = browser.main_tab
        
        # ==========================================
        # FASE 0: DETEKSI TOTAL HALAMAN (LAST PAGE) DENGAN FALLBACK
        # ==========================================
        print(f"\n[FASE 0] Mengakses halaman pertama untuk mendeteksi metode paginasi: {url_halaman_pertama}")
        await page.get(url_halaman_pertama)
        print("  -> Menunggu render awal (5 detik)...")
        await asyncio.sleep(5)
        
        js_deteksi_total_halaman = """
        (() => {
            let links = document.querySelectorAll("ul.pagination a, div.pagination a");
            let totalHalaman = 1;
            
            for (let a of links) {
                let text = (a.innerText || "").trim().toLowerCase();
                let dataPage = a.getAttribute("data-ci-pagination-page");
                
                if (text === "last" && dataPage) {
                    totalHalaman = parseInt(dataPage, 10);
                    break;
                }
            }
            return totalHalaman;
        })()
        """
        
        total_halaman_situs = await page.evaluate(js_deteksi_total_halaman)
        
        # Tentukan mode paginasi berdasarkan hasil deteksi
        gunakan_prediktif = total_halaman_situs > 1
        
        if gunakan_prediktif:
            print(f"  -> [INFO] Tombol 'Last' ditemukan! Total halaman terdeteksi: {total_halaman_situs}.")
            print(f"  -> [MODE] Menggunakan Pre-calculated Pagination (Loncat URL langsung).")
        else:
            print(f"  -> [WARNING] Tombol 'Last' tidak ditemukan.")
            print(f"  -> [MODE] Beralih ke Sequential Fallback (Mencari tombol 'Next' di tiap halaman).")
        
        # Batasi maksimal halaman tes agar tidak berjalan berjam-jam saat uji coba lokal
        maksimal_halaman_tes = 2 
        batas_akhir_eksekusi = min(total_halaman_situs, maksimal_halaman_tes) if gunakan_prediktif else maksimal_halaman_tes
        
        print(f"  -> [TEST MODE] Sesi ini akan memproses maksimal {batas_akhir_eksekusi} halaman.")

        # ==========================================
        # FASE 1: EKSTRAKSI DAFTAR (SUPORT HYBRID)
        # ==========================================
        print("\n>>> MEMULAI FASE 1: PENGUMPULAN TAUTAN DETAIL <<<")
        
        halaman_saat_ini = 1
        url_list_page = url_halaman_pertama
        
        while halaman_saat_ini <= batas_akhir_eksekusi:
            
            # Jika menggunakan mode prediktif dan bukan halaman pertama, bentuk URL langsung
            if gunakan_prediktif and halaman_saat_ini > 1:
                url_list_page = f"https://putusan3.mahkamahagung.go.id/direktori/index/tahunjenis/putus/tahun/{tahun_target}/page/{halaman_saat_ini}.html"
            
            print(f"\n[HALAMAN {halaman_saat_ini}/{batas_akhir_eksekusi}] Mengakses URL: {url_list_page}")
            
            # Jika di mode sequential (fallback), halaman 1 sudah diakses di Fase 0, jadi lewati get() jika halaman 1
            if not (not gunakan_prediktif and halaman_saat_ini == 1):
                await page.get(url_list_page)
                await asyncio.sleep(4)
            
            # --- JAVASCRIPT SCOUTING (CLASS-AGNOSTIC + UNPUBLISH CHECK) ---
            js_ekstraksi_list = """
            (() => {
                let mainWrapper = document.querySelector("#popular-post-list-sidebar") || 
                                  document.querySelector("#kolom-kiri") || 
                                  document;
                
                let links = mainWrapper.querySelectorAll("a[href*='/direktori/putusan/']");
                let results = [];
                let seenUrls = new Set();
                
                links.forEach(a => {
                    let text = (a.innerText || "").toLowerCase();
                    if (text.length < 10 || (!text.includes("putusan") && !text.includes("nomor"))) {
                        return; 
                    }
                    
                    let href = a.getAttribute("href");
                    if (seenUrls.has(href)) return;
                    seenUrls.add(href);
                    
                    let judul = a.innerText ? a.innerText.trim() : "";
                    
                    let is_unpublish = false;
                    let currentNode = a;
                    
                    for(let i = 0; i < 4; i++) {
                        if (!currentNode) break;
                        if (currentNode.id === "popular-post-list-sidebar") break;
                        
                        let blockText = (currentNode.innerText || "").toLowerCase();
                        if (blockText.includes("unpublish")) {
                            is_unpublish = true;
                            break;
                        }
                        currentNode = currentNode.parentElement;
                    }
                    
                    results.push({judul: judul, href: href, is_unpublish: is_unpublish});
                });
                
                return JSON.stringify(results);
            })()
            """
            
            data_mentah_str = await page.evaluate(js_ekstraksi_list)
            data_mentah = json.loads(data_mentah_str)
            
            total_halaman_ini = len(data_mentah)
            unpublish_halaman_ini = sum(1 for item in data_mentah if item['is_unpublish'])
            valid_halaman_ini = total_halaman_ini - unpublish_halaman_ini
            
            print(f"  -> Data aktual di Halaman {halaman_saat_ini}: {total_halaman_ini} dokumen (Valid: {valid_halaman_ini}, Unpublish: {unpublish_halaman_ini}).")
            
            for item in data_mentah:
                status = "UNPUBLISHED" if item['is_unpublish'] else "PENDING_PDF"
                daftar_putusan_global.append({
                    "judul": item['judul'], 
                    "url_detail": item['href'],
                    "status_scraping": status
                })
            
            # Jika kita menggunakan mode Sequential Fallback, cari tombol Next secara manual untuk iterasi berikutnya
            if not gunakan_prediktif:
                js_next = """
                (() => {
                    let btns = document.querySelectorAll("ul.pagination a, div.pagination a, a[rel='next']");
                    for (let btn of btns) {
                        let text = btn.innerText ? btn.innerText.toLowerCase() : "";
                        if (text.includes('>') || text.includes('selanjutnya') || text.includes('next')) {
                            return btn.getAttribute('href');
                        }
                    }
                    return null;
                })()
                """
                url_berikutnya = await page.evaluate(js_next)
                if url_berikutnya:
                    if url_berikutnya.startswith("/"):
                        url_berikutnya = f"https://putusan3.mahkamahagung.go.id{url_berikutnya}"
                    url_list_page = url_berikutnya
                else:
                    print("  -> [!] Tombol 'Next' tidak ditemukan. Menghentikan perulangan paginasi.")
                    break
            
            halaman_saat_ini += 1

        # ==========================================
        # FASE 2: EKSTRAKSI TAUTAN PDF
        # ==========================================
        total_data = len(daftar_putusan_global)
        print(f"\n=======================================================")
        print(f">>> MEMULAI FASE 2: EKSTRAKSI {total_data} URL PDF <<<")
        print("=======================================================")
        
        for idx, item in enumerate(daftar_putusan_global):
            print(f"\n[PROSES {idx+1}/{total_data}]")
            print(f"  -> Judul  : {item['judul'][:60]}...")
            
            if item['status_scraping'] == "UNPUBLISHED":
                print("  -> [SKIP] Dokumen ditandai 'Unpublish'.")
                item['url_pdf'] = None
                continue
            
            print(f"  -> URL    : {item['url_detail']}")
            await page.get(item['url_detail'])
            await asyncio.sleep(4) 
            
            teks_halaman = await page.evaluate("document.body.innerText")
            if teks_halaman and ("500 - Exception Error" in teks_halaman or "terjadi kesalahan pada aplikasi" in teks_halaman):
                item['url_pdf'] = None
                item['status_scraping'] = "ERROR_SERVER_MA_500"
                print("  -> [ERROR MA] Server Mahkamah Agung gagal memuat halaman ini (Exception Error).")
                continue
            
            js_pdf = """
            (() => {
                let el = document.querySelector("a[href*='/direktori/download_file/'][href*='/pdf/']");
                return el ? el.getAttribute('href') : null;
            })()
            """
            pdf_raw = await page.evaluate(js_pdf)
            
            if pdf_raw:
                if pdf_raw.startswith("/"):
                    pdf_raw = f"https://putusan3.mahkamahagung.go.id{pdf_raw}"
                
                item['url_pdf'] = pdf_raw
                item['status_scraping'] = "SUCCESS"
                print(f"  -> [SUKSES] URL PDF Diekstrak: {pdf_raw}")
            else:
                item['url_pdf'] = None
                item['status_scraping'] = "PDF_TIDAK_DITEMUKAN"
                print(f"  -> [GAGAL] Tautan PDF tidak ditemukan.")

        # ==========================================
        # REKAP HASIL AKHIR
        # ==========================================
        print("\n\n*******************************************************")
        print("                 REKAP HASIL PIPELINE                  ")
        print("*******************************************************")
        print(f"Total halaman diproses : {halaman_saat_ini - 1}")
        print(f"Total dokumen aktual   : {total_data}")
        
        sukses_pdf = sum(1 for d in daftar_putusan_global if d.get('url_pdf'))
        unpublish = sum(1 for d in daftar_putusan_global if d.get('status_scraping') == 'UNPUBLISHED')
        
        print(f"Total PDF ditemukan    : {sukses_pdf}")
        print(f"Total data di-skip     : {unpublish} (Unpublish)")
        
        print("\n3 Sampel Data Terakhir:")
        for i, data in enumerate(daftar_putusan_global[-3:]):
            print(f"  {i+1}. {data['judul'][:70]}...")
            print(f"     Status : {data.get('status_scraping')}")
        print("*******************************************************\n")
        
    except Exception as e:
        print(f"\n[ERROR FATAL] Skrip terhenti karena: {e}")
    
    finally:
        print("Membersihkan memori & Menutup browser...")
        if 'browser' in locals():
            browser.stop()

if __name__ == "__main__":
    asyncio.run(main())