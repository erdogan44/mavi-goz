# --- EN ÜST SATIR: KÜTÜPHANELERDEN BİLE ÖNCE ---
import threading
import tkinter as tk
from tkinter import ttk
import json, io, os, base64, threading, time
import socket
import sys
from tkinter import messagebox


# --- 2. ADIM: AKILLI SPLASH ---
splash_penceresi = None
def tkinter_splash():
    global splash_penceresi
    try:
        splash_penceresi = tk.Tk()
        splash_penceresi.overrideredirect(True)
        w, h = 400, 200
        sw, sh = splash_penceresi.winfo_screenwidth(), splash_penceresi.winfo_screenheight()
        splash_penceresi.geometry(f"{w}x{h}+{int((sw-w)/2)}+{int((sh-h)/2)}")
        splash_penceresi.configure(bg='white', highlightbackground="#1565C0", highlightthickness=2)
        tk.Label(splash_penceresi, text="MAVi-GÖZ", font=("Arial", 24, "bold"), fg="#1565C0", bg="white").pack(pady=(30, 10))
        tk.Label(splash_penceresi, text="Sistem Başlatılıyor...", font=("Arial", 10, "italic"), bg="white").pack()
        pb = ttk.Progressbar(splash_penceresi, orient='horizontal', mode='determinate', length=280)
        pb.pack(pady=20)
        pb.start(10)
        splash_penceresi.mainloop()
    except: pass

threading.Thread(target=tkinter_splash, daemon=True).start()

# --- TEK ÇALIŞMA KONTROLÜ (SOKET YÖNTEMİ) ---
try:
    tek_calisma_soketi = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tek_calisma_soketi.bind(("127.0.0.1", 65432))
except socket.error:
    messagebox.showwarning("MAVi-GÖZ", "Uygulama zaten çalışıyor")
    sys.exit(0)

def resource_path(relative_path):
    """ EXE içindeki geçici dosya yolunu bulur """
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

# --- GEMO GÜVENLİK: FIREBASE KÜTÜPHANELERİ ---
import firebase_admin
from firebase_admin import credentials, firestore

# --- GEMO GÜVENLİK: FIREBASE BAĞLANTISI ---
db = None
try:
    # servis_anahtari.json dosyasının exe yanında olması gerekir
    cred = credentials.Certificate(resource_path("servis_anahtari.json"))
    firebase_admin.initialize_app(cred)
    db = firestore.client()
except Exception as e:
    messagebox.showerror("Hata", f"Firebase anahtar dosyası bulunamadı!\n{e}")

# --- AYAR DOSYASI AYARLARI ---
SETTINGS_FILE = "mavi_goz_ayarlar.json"
VARSAYILAN_TALIMAT = "Görseldeki öğrenci yazılarını piksel bazlı büyüterek ve odaklanarak oku. Öğrencinin karakteristik el yazısını (diğer rakamlarını) referans alarak karakter eşleştirmesi yap. Okuduğun bu yazıları Cevap anahtarındaki kısmi puanlamalara göre puanla. Öğrencinin çözüm yolunu incele, hatasını bul ve pedagojik bir dilde detaylı şekilde açıkla."

def ayarları_kaydet(anahtar, talimat):
    data = {"anahtar": anahtar, "talimat": talimat}
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)

def ayarları_yukle():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except: pass
    return {"anahtar": "", "talimat": VARSAYILAN_TALIMAT}

import flet as ft
from google import genai
import pandas as pd
from tkinter import filedialog
from concurrent.futures import ThreadPoolExecutor, as_completed
import subprocess
from PIL import Image

import warnings
warnings.filterwarnings('ignore', category=DeprecationWarning)

# --- API AYARI (Gemo: Artık Giriş Yapınca Dolacak) ---
API_ANAHTARIN = ""
client = None
thumbnail_cache = {}

# --- YARDIMCI FONKSİYONLAR ---
def gorsel_kucult(image_data, max_width=100, max_height=120, quality=85):
    try:
        img = Image.open(io.BytesIO(image_data))
        img.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
        if img.mode in ('RGBA', 'LA', 'P'): img = img.convert('RGB')
        buffer = io.BytesIO()
        img.save(buffer, format='JPEG', quality=quality, optimize=True)
        return buffer.getvalue()
    except: return image_data[:50000]

def gorsel_onizleme_olustur(image_data, max_width=1400, max_height=1000, quality=95):
    try:
        img = Image.open(io.BytesIO(image_data))
        img.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
        if img.mode in ('RGBA', 'LA', 'P'): img = img.convert('RGB')
        buffer = io.BytesIO()
        img.save(buffer, format='JPEG', quality=quality, optimize=True)
        return buffer.getvalue()
    except: return image_data

def main(page: ft.Page):
    global API_ANAHTARIN, client
    page.title = "MAVi-GÖZ Sınav Okuma (V4 Firebase)"
    page.window_width = 1600
    page.window_height = 1200
    kayitli_ayarlar = ayarları_yukle()

    anahtar_depo, ogrenci_depo = {}, {}
    anahtar_metin = ft.TextField(label="Cevap Anahtarı Metni", value=kayitli_ayarlar["anahtar"], multiline=True, min_lines=20, expand=True, text_size=13)
    talimat_metin = ft.TextField(label="Ana Talimat", value=kayitli_ayarlar["talimat"], multiline=True, min_lines=10, expand=True, text_size=13)
    onizleme_html = ft.Container(content=ft.Text("Büyük Önizleme İçin Resme Tıklayın", color="grey"), expand=True)
    anahtar_galeri = ft.Row(wrap=True, scroll="auto", spacing=5)
    ogrenci_galeri = ft.Row(wrap=True, scroll="auto", spacing=5)
    progress_bar = ft.ProgressBar(width=400, color="blue", visible=False)
    durum_label = ft.Text("Hazır Hocam.", size=14, weight="bold")
    mesaj_alani = ft.Text("Sistem Kilitli 🔒", size=12, weight="bold", color="red")

    def ayar_kaydet_aksiyon(e):
        ayarları_kaydet(anahtar_metin.value, talimat_metin.value)
        page.snack_bar = ft.SnackBar(ft.Text("Ayarlar Kaydedildi! ✅"))
        page.snack_bar.open = True
        page.update()

    def varsayilana_don_aksiyon(e):
        talimat_metin.value = VARSAYILAN_TALIMAT
        page.update()
        page.snack_bar = ft.SnackBar(ft.Text("Fabrika Ayarlarına Dönüldü!"))
        page.snack_bar.open = True
        page.update()

    def thumbnail_olustur(image_data, name, depo, galeri_ref):
        thumb_data = gorsel_kucult(image_data)
        b64_str = base64.b64encode(thumb_data).decode("utf-8")
        img = ft.Image(src=f"data:image/jpeg;base64,{b64_str}", width=100, height=120, fit="cover")
        delete_btn = ft.Container(content=ft.Text("❌", size=10, color="white"), bgcolor="red", width=20, height=20, border_radius=10, top=2, right=2, on_click=lambda e: sil_ve_guncelle(name, depo, galeri_ref))
        label = ft.Container(content=ft.Text(name[:10], size=8, color="white"), bgcolor="rgba(0,0,0,0.6)", padding=2, bottom=0, left=0, right=0)
        return ft.Container(content=ft.Stack([img, label, delete_btn]), border_radius=5, border=ft.border.all(2, "blue300"), on_click=lambda e: gorsel_goster(image_data, name))

    def sil_ve_guncelle(name, depo, galeri_ref):
        depo.pop(name, None)
        guncelle_galeri(depo, galeri_ref)

    def guncelle_galeri(depo, galeri_ref):
        galeri_ref.controls.clear()
        galeri_ref.controls.extend([thumbnail_olustur(data, name, depo, galeri_ref) for name, data in depo.items()])
        page.update()

    def gorsel_goster(image_data, name):
        cache_key = f"preview_{name}"
        preview_data = thumbnail_cache.get(cache_key) or gorsel_onizleme_olustur(image_data)
        thumbnail_cache[cache_key] = preview_data
        b64_str = base64.b64encode(preview_data).decode("utf-8")
        onizleme_html.content = ft.Column([ft.Text(name, weight="bold"), ft.Image(src=f"data:image/jpeg;base64,{b64_str}", fit="contain")], horizontal_alignment="center", scroll="auto")
        page.update()

    def anahtar_btn_click(e):
        root = tk.Tk(); root.withdraw(); root.attributes('-topmost', True)
        files = filedialog.askopenfilenames(); root.destroy()
        if files:
            for f in files:
                with open(f, "rb") as file: anahtar_depo[os.path.basename(f)] = file.read()
            guncelle_galeri(anahtar_depo, anahtar_galeri)

    def ogrenci_btn_click(e):
        root = tk.Tk(); root.withdraw(); root.attributes('-topmost', True)
        folder = filedialog.askdirectory(); root.destroy()
        if folder:
            durum_label.value = "Dosyalar yükleniyor..."; page.update()
            for f in os.listdir(folder):
                if f.lower().endswith(('.jpg', '.jpeg', '.png')):
                    with open(os.path.join(folder, f), "rb") as file: ogrenci_depo[f] = file.read()
            durum_label.value = f"{len(ogrenci_depo)} dosya yüklendi."; guncelle_galeri(ogrenci_depo, ogrenci_galeri)

    def anahtar_oku_logic():
        if not anahtar_depo: 
            durum_label.value = "Önce dosya yükleyin!"; page.update(); return
        progress_bar.visible = True; durum_label.value = "Okunuyor..."; page.update()
        def tek_oku(item):
            n, d = item
            f = client.files.upload(file=io.BytesIO(d), config={'mime_type': 'image/jpeg'})
            r = client.models.generate_content(model="gemini-3-flash-preview", contents=[f, "Cevap anahtarını özetle. Tuhaf karakter kullanma."])
            client.files.delete(name=f.name)
            return f"\n--- {n} ---\n{r.text}\n"
        with ThreadPoolExecutor(max_workers=3) as ex:
            birlesik = "".join(ex.map(tek_oku, anahtar_depo.items()))
        anahtar_metin.value = birlesik.strip()
        progress_bar.visible = False; durum_label.value = "Aktarıldı."; page.update()

    def analiz_baslat():
        if not ogrenci_depo or not anahtar_metin.value:
            durum_label.value = "Eksik bilgi!"; page.update(); return
        progress_bar.visible = True; durum_label.value = "Sınavlar okunuyor..."; page.update()
        tum_sonuclar = []; toplam = len(ogrenci_depo)
        def analiz_et(item):
            n, d = item
            f = client.files.upload(file=io.BytesIO(d), config={'mime_type': 'image/jpeg'})
            p = f"Talimat: {talimat_metin.value}\nAnahtar: {anahtar_metin.value}\nYanıtı JSON ver: {{\"ad_soyadi\":\"\", \"okul_no\":\"\", \"sinif\":\"\", \"puanlar\":{{\"s1\":0}}, \"nedenler\":{{\"s1\":\"\"}}}}"
            r = client.models.generate_content(model="gemini-3-flash-preview", contents=[f, p])
            client.files.delete(name=f.name)
            res_data = json.loads(r.text.strip().replace("```json","").replace("```",""))
            return {"No": str(res_data.get("okul_no", "")), "Ad Soyad": res_data.get("ad_soyadi", ""), "Sınıf": res_data.get("sinif", ""), "Dosya": n, "puanlar": res_data.get("puanlar", {}), "nedenler": res_data.get("nedenler", {})}

        with ThreadPoolExecutor(max_workers=5) as ex:
            futures = {ex.submit(analiz_et, item): item for item in ogrenci_depo.items()}
            for i, f in enumerate(as_completed(futures)):
                res = f.result()
                if res:
                    row = {"No": res["No"], "Ad Soyad": res["Ad Soyad"], "Sınıf": res["Sınıf"], "Dosya": res["Dosya"]}
                    for k, v in res["puanlar"].items(): row[f"Soru {k[1:]} Puan"] = v
                    for k, v in res["nedenler"].items(): row[f"Soru {k[1:]} Açıklama"] = v
                    tum_sonuclar.append(row)
                durum_label.value = f"Okunan: {i+1}/{toplam}"; progress_bar.value = (i+1)/toplam; page.update()

        if tum_sonuclar:
            df_ham = pd.DataFrame(tum_sonuclar)
            agg_dict = {c: ("sum" if "Puan" in c else "first") for c in df_ham.columns if c not in ["No", "Dosya"]}
            df_ozet = df_ham.groupby("No", as_index=False).agg(agg_dict)
            p_cols = [c for c in df_ozet.columns if "Puan" in c]; df_ozet["Toplam Puan"] = df_ozet[p_cols].sum(axis=1)
            with pd.ExcelWriter("Sınav sonuçları ve Analizi.xlsx", engine='xlsxwriter') as writer:
                df_ozet.to_excel(writer, sheet_name='Analiz 1', index=False)
                df_ham.to_excel(writer, sheet_name='Analiz 2', index=False)
                df_ozet[["Sınıf", "No", "Ad Soyad", "Toplam Puan"]].to_excel(writer, sheet_name='Not Listesi', index=False)
                workbook = writer.book
                fmt_center = workbook.add_format({'align': 'center', 'valign': 'vcenter', 'border': 1})
                fmt_wrap = workbook.add_format({'align': 'left', 'valign': 'vcenter', 'border': 1, 'text_wrap': True})
                fmt_total = workbook.add_format({'align': 'center', 'valign': 'vcenter', 'border': 1, 'bold': True, 'font_color': 'red'})
                for sheet_name, sheet in writer.sheets.items():
                    sheet.set_column('A:Z', 15, fmt_center)
                    cur_cols = df_ham.columns if sheet_name == 'Analiz 2' else df_ozet.columns
                    for idx, col in enumerate(cur_cols):
                        if "Açıklama" in col: sheet.set_column(idx, idx, 40, fmt_wrap)
                        if col == "Toplam Puan": sheet.set_column(idx, idx, 15, fmt_total)
            subprocess.Popen(['start', 'excel', os.path.abspath("Sınav sonuçları ve Analizi.xlsx")], shell=True)
        progress_bar.visible = False; durum_label.value = "TAMAMLANDI! ✅"; page.update()

    # --- GEMO GÜVENLİK: GİRİŞ AKSİYONU ---
    def giris_yap_aksiyon(e):
        global API_ANAHTARIN, client
        if not db:
            mesaj_alani.value = "Server Hatası!"; page.update(); return
        
        durum_label.value = "Giriş yapılıyor..."; page.update()
        try:
            # Firebase Users koleksiyonundan ID ile çekme
            doc_ref = db.collection("users").document(user_input.value).get()
            if doc_ref.exists:
                user_data = doc_ref.to_dict()
                if str(user_data.get("sifre")) == pass_input.value and user_data.get("aktif") == True:
                    # BAŞARILI
                    API_ANAHTARIN = user_data.get("api_key")
                    client = genai.Client(api_key=API_ANAHTARIN)
                    ana_tas_motoru.disabled = False
                    login_bar_row.visible = False
                    mesaj_alani.value = f"Hoş geldin Hocam! ✅"; mesaj_alani.color = "green"
                    durum_label.value = "Sistem Aktif."
                else:
                    mesaj_alani.value = "Şifre Yanlış veya Yetki Yok!"; mesaj_alani.color = "red"
            else:
                mesaj_alani.value = "Kullanıcı Bulunamadı!"; mesaj_alani.color = "red"
        except Exception as err:
            mesaj_alani.value = "Bağlantı Hatası!"; print(err)
        page.update()

    # --- TASARIM ---
    ana_tas_motoru = ft.Row([
        ft.Column([
            ft.Text("📁 GALERİ", weight="bold"),
            ft.FilledButton("🔑 Cevap Anahtarı", on_click=anahtar_btn_click),
            ft.Container(content=anahtar_galeri, height=150, border=ft.Border.all(1, "grey400"), border_radius=5),
            ft.Divider(),
            ft.FilledButton("📂 Sınav Kağıtları", on_click=ogrenci_btn_click),
            ft.Container(content=ogrenci_galeri, height=450, border=ft.Border.all(1, "grey400"), border_radius=5),
        ], width=335, scroll="auto"),
        ft.VerticalDivider(),
        ft.Column([ft.Text("🖼️ ÖNİZLEME", weight="bold"), onizleme_html], expand=True),
        ft.VerticalDivider(),
        ft.Column([
            anahtar_metin,
            ft.FilledButton("📖 CEVAP ANAHTARINI OKU", bgcolor="blue800", color="white", width=350, on_click=lambda _: threading.Thread(target=anahtar_oku_logic, daemon=True).start()),
            ft.Divider(),
            talimat_metin,
            ft.Row([
                ft.FilledButton("💾 KAYDET", bgcolor="blue700", color="white", width=150, height=35, on_click=ayar_kaydet_aksiyon),
                ft.FilledButton("🔄 SIFIRLA", bgcolor="red700", color="white", width=150, height=35, on_click=varsayilana_don_aksiyon),
            ], alignment="center", spacing=10),
            progress_bar, durum_label,
            ft.FilledButton("🚀 SINAV KAĞITLARINI OKU", bgcolor="red", color="white", width=350, height=45, on_click=lambda _: threading.Thread(target=analiz_baslat, daemon=True).start())
        ], width=350)
    ], expand=True, disabled=True)

    user_input = ft.TextField(label="Öğretmen ID", width=150, height=40, text_size=12)
    pass_input = ft.TextField(label="Şifre", password=True, width=150, height=40, text_size=12)
    login_bar_row = ft.Row([user_input, pass_input, ft.FilledButton("Giriş Yap", on_click=giris_yap_aksiyon)])
    ust_serit = ft.Container(content=ft.Row([ft.Text("MAVi-GÖZ", size=22, weight="bold", color="blue800"), login_bar_row, mesaj_alani], alignment="spaceBetween"), padding=10, bgcolor="white")
    page.add(ft.Column([ust_serit, ft.Divider(height=1), ana_tas_motoru], expand=True))

    def splash_kapat():
        global splash_penceresi
        if splash_penceresi:
            splash_penceresi.after(0, splash_penceresi.destroy)
            splash_penceresi = None

    page.update() 
    time.sleep(1)
    splash_kapat()

if __name__ == "__main__":
    ft.app(target=main)
