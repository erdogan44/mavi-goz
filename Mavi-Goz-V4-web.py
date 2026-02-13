import streamlit as st
import pandas as pd
import base64, io, asyncio, httpx
import firebase_admin
from firebase_admin import credentials, firestore

# --- SAYFA AYARLARI ---
st.set_page_config(page_title="MAVi-GÖZ V4", layout="wide")

# --- FIREBASE BAĞLANTISI ---
if not firebase_admin._apps:
    try:
        cred = credentials.Certificate("servis_anahtari.json")
        firebase_admin.initialize_app(cred)
    except: pass
db = firestore.client()

# --- GEMINI ANALİZ MOTORU ---
async def gemi_analiz_yap(image_bytes, prompt, api_key):
    model_name = "gemini-3-flash-preview" 
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
    b64_image = base64.b64encode(image_bytes).decode('utf-8')
    
    payload = {
        "contents": [{
            "parts": [
                {"text": prompt},
                {"inline_data": {"mime_type": "image/jpeg", "data": b64_image}}
            ]
        }]
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload, timeout=90.0)
        res_json = response.json()
        try:
            return res_json['candidates'][0]['content']['parts'][0]['text']
        except:
            return f"Hata: {res_json.get('error', {}).get('message', 'Okunamadı')}"

async def tum_sinavlari_oku(anahtar, ogrenciler, talimat, api_key):
    sonuclar = []
    bar = st.progress(0)
    durum = st.empty()
    toplam = len(ogrenciler)
    
    for i, (name, data) in enumerate(ogrenciler.items()):
        durum.info(f"Okunuyor: {name} ({i+1}/{toplam})")
        prompt = f"Cevap Anahtarı: {anahtar}\nTalimat: {talimat}\n\nLütfen öğrenciyi puanla. Yanıtı 'Ad Soyad: [İsim], Puan: [Puan], Not: [Detay]' formatında ver."
        res = await gemi_analiz_yap(data, prompt, api_key)
        sonuclar.append({"Dosya": name, "Analiz": res})
        bar.progress((i + 1) / toplam)
    
    durum.success("✅ Tüm sınavlar analiz edildi!")
    return sonuclar

# --- HAFIZA ---
if "auth" not in st.session_state: st.session_state.auth = False
if "anahtar_depo" not in st.session_state: st.session_state.anahtar_depo = {}
if "ogrenci_depo" not in st.session_state: st.session_state.ogrenci_depo = {}
if "secili_img" not in st.session_state: st.session_state.secili_img = None
if "anahtar_metin_sonuc" not in st.session_state: st.session_state.anahtar_metin_sonuc = ""

# --- GİRİŞ ---
if not st.session_state.auth:
    st.markdown("### 👁️ MAVi-GÖZ V4 GİRİŞ")
    c1, c2, c3 = st.columns([3, 3, 2])
    uid = c1.text_input("ID")
    upass = c2.text_input("Şifre", type="password")
    if c3.button("Sistemi Aç", use_container_width=True):
        doc = db.collection("users").document(uid).get()
        if doc.exists and str(doc.to_dict().get("sifre")) == upass:
            st.session_state.auth = True
            st.session_state.api_key = doc.to_dict().get("api_key")
            st.rerun()
        else: st.error("Hatalı Giriş!")
    st.stop()

# --- ANA EKRAN (Sütunlar Burada Tanımlanıyor) ---
col_sol, col_orta, col_sag = st.columns([0.25, 0.45, 0.3])

with col_sol:
    st.subheader("📁 Galeri")
    st.info("🔑 Anahtar")
    u1 = st.file_uploader("A", type=['jpg','png','jpeg'], accept_multiple_files=True, key="ua", label_visibility="collapsed")
    if u1:
        for f in u1: st.session_state.anahtar_depo[f.name] = f.getvalue()
    for n, d in list(st.session_state.anahtar_depo.items()):
        ci, cv, cd = st.columns([0.6, 0.2, 0.2])
        ci.image(d); 
        if cv.button("👁️", key=f"va_{n}"): st.session_state.secili_img = d
        if cd.button("❌", key=f"da_{n}"): del st.session_state.anahtar_depo[n]; st.rerun()
    
    st.divider()
    st.info("📂 Sınavlar")
    u2 = st.file_uploader("S", type=['jpg','png','jpeg'], accept_multiple_files=True, key="us", label_visibility="collapsed")
    if u2:
        for f in u2: st.session_state.ogrenci_depo[f.name] = f.getvalue()
    for n, d in list(st.session_state.ogrenci_depo.items()):
        ci, cv, cd = st.columns([0.6, 0.2, 0.2])
        ci.image(d); 
        if cv.button("👁️", key=f"vs_{n}"): st.session_state.secili_img = d
        if cd.button("❌", key=f"ds_{n}"): del st.session_state.ogrenci_depo[n]; st.rerun()

with col_orta:
    st.subheader("🖼️ Önizleme")
    if st.session_state.secili_img:
        st.image(st.session_state.secili_img, width='stretch')
    else: st.write("Büyütmek için 👁️ butonuna basın.")

with col_sag:
    st.subheader("📝 Analiz")
    anahtar_metin = st.text_area("Cevap Anahtarı", value=st.session_state.anahtar_metin_sonuc, height=250)
    if st.button("📖 ANAHTARI OKU", use_container_width=True):
        if st.session_state.anahtar_depo:
            with st.spinner("Gemini okuyor..."):
                img_data = list(st.session_state.anahtar_depo.values())[0]
                sonuc = asyncio.run(gemi_analiz_yap(img_data, "Cevap anahtarını çıkar.", st.session_state.api_key))
                st.session_state.anahtar_metin_sonuc = sonuc
                st.rerun()

    st.divider()
    talimat = st.text_area("Talimat", value="Öğrenci yazılarını puanla...", height=100)
    
    if st.button("🚀 ANALİZİ BAŞLAT", type="primary", use_container_width=True):
        if st.session_state.anahtar_metin_sonuc and st.session_state.ogrenci_depo:
            with st.spinner("Analiz yapılıyor..."):
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                veriler = loop.run_until_complete(tum_sinavlari_oku(st.session_state.anahtar_metin_sonuc, st.session_state.ogrenci_depo, talimat, st.session_state.api_key))
                st.session_state.analiz_df = pd.DataFrame(veriler)
                st.success("Bitti!")

    if "analiz_df" in st.session_state:
        st.dataframe(st.session_state.analiz_df, use_container_width=True)
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            st.session_state.analiz_df.to_excel(writer, index=False)
        st.download_button("📥 Excel İndir", data=output.getvalue(), file_name="analiz.xlsx")