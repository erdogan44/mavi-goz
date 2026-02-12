import json, io, os, base64, threading, time, sys
import flet as ft
from google import genai
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from PIL import Image
import warnings
import firebase_admin
from firebase_admin import credentials, firestore

warnings.filterwarnings('ignore', category=DeprecationWarning)

# --- 1. DOSYA YOLLARI VE AYARLAR ---
def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

SETTINGS_FILE = "mavi_goz_ayarlar.json"
VARSAYILAN_TALIMAT = "Görseldeki öğrenci yazılarını piksel bazlı büyüterek ve odaklanarak oku. Öğrencinin karakteristik el yazısını referans alarak karakter eşleştirmesi yap. Okuduğun bu yazıları Cevap anahtarındaki kısmi puanlamalara göre puanla. Öğrencinin çözüm yolunu incele, hatasını bul ve pedagojik bir dilde detaylı şekilde açıkla."

def ayarları_kaydet(anahtar, talimat):
    data = {"anahtar": anahtar, "talimat": talimat}
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except: pass

def ayarları_yukle():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except: pass
    return {"anahtar": "", "talimat": VARSAYILAN_TALIMAT}

# --- 2. GÖRSEL İŞLEME (WEB OPTİMİZE) ---
def gorsel_islem(image_data, is_thumb=True):
    try:
        img = Image.open(io.BytesIO(image_data))
        if is_thumb:
            img.thumbnail((100, 120), Image.Resampling.LANCZOS)
        else:
            img.thumbnail((1400, 1000), Image.Resampling.LANCZOS)
        
        if img.mode in ('RGBA', 'LA', 'P'): img = img.convert('RGB')
        buffer = io.BytesIO()
        img.save(buffer, format='JPEG', quality=85)
        return buffer.getvalue()
    except: return image_data

def main(page: ft.Page):
    page.title = "MAVi-GÖZ Sınav Okuma (Web V4)"
    page.theme_mode = ft.ThemeMode.LIGHT
    # Web'de pencere boyutu tarayıcıya göre değişir ama başlangıç değerlerini veriyoruz
    page.padding = 10
    
    # Değişkenler
    API_ANAHTARIN = ""
    client = None
    db = None
    anahtar_depo, ogrenci_depo = {}, {}
    kayitli_ayarlar = ayarları_yukle()

    # Firebase Bağlantısı (Web'de hata vermemesi için güvenli blok)
    try:
        if not firebase_admin._apps:
            cred = credentials.Certificate(resource_path("servis_anahtari.json"))
            firebase_admin.initialize_app(cred)
        db = firestore.client()
    except Exception as e:
        print(f"Firebase Hatası: {e}")

    # --- UI BİLEŞENLERİ ---
    anahtar_metin = ft.TextField(label="Cevap Anahtarı Metni", value=kayitli_ayarlar["anahtar"], multiline=True, min_lines=15, expand=True, text_size=13)
    talimat_metin = ft.TextField(label="Ana Talimat", value=kayitli_ayarlar["talimat"], multiline=True, min_lines=8, expand=True, text_size=13)
    onizleme_alani = ft.Container(content=ft.Text("Büyük Önizleme İçin Resme Tıklayın", color="grey"), expand=True, alignment=ft.alignment.center)
    anahtar_galeri = ft.Row(wrap=True, scroll="auto", spacing=5)
    ogrenci_galeri = ft.Row(wrap=True, scroll="auto", spacing=5)
    progress_bar = ft.ProgressBar(width=400, color="blue", visible=False)
    durum_label = ft.Text("Hazır Hocam.", size=14, weight="bold")
    mesaj_alani = ft.Text("Sistem Kilitli 🔒", size=12, weight="bold", color="red")

    # --- WEB UYUMLU DOSYA SEÇME (FILEPICKER) ---
    def dosya_sonuc(e: ft.FilePickerResultEvent):
        if not e.files: return
        
        is_anahtar = e.control.id == "a_picker"
        target_depo = anahtar_depo if is_anahtar else ogrenci_depo
        target_galeri = anahtar_galeri if is_anahtar else ogrenci_galeri
        
        for f in e.files:
            # Web'de tek güvenli yol: f.bytes
            content = getattr(f, "bytes", None)
            if content:
                target_depo[f.name] = content
                thumb_bytes = gorsel_islem(content, True)
                b64 = base64.b64encode(thumb_bytes).decode()
                
                # Galeri Kartı
                card = ft.Container(
                    content=ft.Stack([
                        ft.Image(src_base64=b64, width=100, height=120, fit="cover"),
                        ft.Container(content=ft.Text(f.name[:10], size=8, color="white"), bgcolor="black54", bottom=0, left=0, right=0)
                    ]),
                    border=ft.border.all(2, "blue300"),
                    border_radius=5,
                    on_click=lambda _, d=content, n=f.name: onizleme_goster(d, n)
                )
                target_galeri.controls.append(card)
        
        durum_label.value = f"{len(target_depo)} dosya hazır."
        page.update()

    a_picker = ft.FilePicker(on_result=dosya_sonuc); a_picker.id = "a_picker"
    o_picker = ft.FilePicker(on_result=dosya_sonuc); o_picker.id = "o_picker"
    page.overlay.extend([a_picker, o_picker])

    def onizleme_goster(data, name):
        preview_bytes = gorsel_islem(data, False)
        b64 = base64.b64encode(preview_bytes).decode()
        onizleme_alani.content = ft.Image(src_base64=b64, fit="contain")
        page.update()

    # --- AYAR AKSİYONLARI ---
    def ayar_kaydet_aksiyon(e):
        ayarları_kaydet(anahtar_metin.value, talimat_metin.value)
        page.snack_bar = ft.SnackBar(ft.Text("Ayarlar Kaydedildi! ✅"))
        page.snack_bar.open = True
        page.update()

    def varsayilana_don_aksiyon(e):
        talimat_metin.value = VARSAYILAN_TALIMAT
        page.update()

    # --- ANALİZ MOTORU ---
    def analiz_baslat(e):
        if not ogrenci_depo or not client:
            durum_label.value = "Eksik bilgi veya Giriş yapılmadı!"; page.update(); return
        
        progress_bar.visible = True; durum_label.value = "Sınavlar okunuyor..."; page.update()
        
        def islem():
            tum_sonuclar = []; toplam = len(ogrenci_depo)
            for i, (n, d) in enumerate(ogrenci_depo.items()):
                try:
                    f = client.files.upload(file=io.BytesIO(d), config={'mime_type': 'image/jpeg'})
                    p = f"Talimat: {talimat_metin.value}\nAnahtar: {anahtar_metin.value}\nYanıtı JSON: {{\"ad_soyadi\":\"\", \"okul_no\":\"\", \"sinif\":\"\", \"puanlar\":{{\"s1\":0}}, \"nedenler\":{{\"s1\":\"\"}}}}"
                    r = client.models.generate_content(model="gemini-2.0-flash", contents=[f, p])
                    client.files.delete(name=f.name)
                    
                    raw_text = r.text.strip().replace("```json","").replace("```","")
                    res_data = json.loads(raw_text)
                    
                    row = {"No": str(res_data.get("okul_no", "")), "Ad Soyad": res_data.get("ad_soyadi", ""), "Sınıf": res_data.get("sinif", ""), "Dosya": n}
                    for k, v in res_data.get("puanlar", {}).items(): row[f"Soru {k[1:]} Puan"] = v
                    for k, v in res_data.get("nedenler", {}).items(): row[f"Soru {k[1:]} Açıklama"] = v
                    tum_sonuclar.append(row)
                except: pass
                durum_label.value = f"Okunan: {i+1}/{toplam}"; progress_bar.value = (i+1)/toplam; page.update()
            
            if tum_sonuclar:
                # Web'de excel dosyası sadece bellekte oluşturulabilir
                pd.DataFrame(tum_sonuclar).to_excel("Analiz_Sonuclari.xlsx", index=False)
                durum_label.value = "Analiz Bitti! ✅ (Excel oluşturuldu)"; page.update()
            progress_bar.visible = False; page.update()

        threading.Thread(target=islem, daemon=True).start()

    # --- GİRİŞ AKSİYONU ---
    def giris_yap_aksiyon(e):
        nonlocal client
        if not db: mesaj_alani.value = "Firebase Hatası!"; page.update(); return
        try:
            doc = db.collection("users").document(user_input.value).get()
            if doc.exists:
                ud = doc.to_dict()
                if str(ud.get("sifre")) == pass_input.value and ud.get("aktif"):
                    client = genai.Client(api_key=ud.get("api_key"))
                    ana_tas_motoru.disabled = False
                    login_row.visible = False
                    mesaj_alani.value = "Hoş geldin Hocam! ✅"; mesaj_alani.color = "green"
                else: mesaj_alani.value = "Hatalı Şifre!"; mesaj_alani.color = "red"
            else: mesaj_alani.value = "Kullanıcı Yok!"; mesaj_alani.color = "red"
        except: mesaj_alani.value = "Bağlantı Hatası!"
        page.update()

    # --- TASARIM ---
    user_input = ft.TextField(label="Öğretmen ID", width=150, height=40, text_size=12)
    pass_input = ft.TextField(label="Şifre", password=True, width=150, height=40, text_size=12)
    login_row = ft.Row([user_input, pass_input, ft.FilledButton("Giriş Yap", on_click=giris_yap_aksiyon)])

    ana_tas_motoru = ft.Row([
        ft.Column([
            ft.Text("📁 GALERİ", weight="bold"),
            ft.FilledButton("🔑 Cevap Anahtarı", on_click=lambda _: a_picker.pick_files(allow_multiple=True)),
            ft.Container(anahtar_galeri, height=150, border=ft.border.all(1, "grey400"), border_radius=5),
            ft.Divider(),
            ft.FilledButton("📂 Sınav Kağıtları", on_click=lambda _: o_picker.pick_files(allow_multiple=True)),
            ft.Container(ogrenci_galeri, height=450, border=ft.border.all(1, "grey400"), border_radius=5),
        ], width=335),
        ft.VerticalDivider(),
        ft.Column([ft.Text("🖼️ ÖNİZLEME", weight="bold"), onizleme_alani], expand=True),
        ft.VerticalDivider(),
        ft.Column([
            anahtar_metin,
            talimat_metin,
            ft.Row([
                ft.FilledButton("💾 KAYDET", on_click=ayar_kaydet_aksiyon),
                ft.FilledButton("🔄 SIFIRLA", on_click=varsayilana_don_aksiyon),
            ], alignment="center"),
            progress_bar, durum_label,
            ft.FilledButton("🚀 ANALİZİ BAŞLAT", bgcolor="red", color="white", width=350, height=45, on_click=analiz_baslat)
        ], width=350)
    ], expand=True, disabled=True)

    page.add(
        ft.Row([ft.Text("MAVi-GÖZ V4", size=22, weight="bold"), login_row, mesaj_alani], alignment="spaceBetween"),
        ft.Divider(),
        ana_tas_motoru
    )

if __name__ == "__main__":
    ft.app(target=main)