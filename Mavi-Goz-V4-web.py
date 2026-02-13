import streamlit as st
import pandas as pd
from PIL import Image
import base64, io, json, httpx, asyncio
import firebase_admin
from firebase_admin import credentials, firestore

# --- 1. SAYFA AYARLARI ---
st.set_page_config(page_title="MAVi-GÖZ V4", layout="wide", initial_sidebar_state="collapsed")

# --- 2. FIREBASE BAĞLANTISI (SADECE YEREL) ---
if not firebase_admin._apps:
    try:
        cred = credentials.Certificate("servis_anahtari.json")
        firebase_admin.initialize_app(cred)
    except Exception as e:
        st.error(f"⚠️ 'servis_anahtari.json' dosyası bulunamadı veya hatalı! Hata: {e}")
        st.stop()

db = firestore.client()

# --- 3. GEMINI MOTORU ---
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
        try:
            response = await client.post(url, json=payload, timeout=90.0)
            res_json = response.json()
            return res_json['candidates'][0]['content']['parts'][0]['text']
        except:
            return "Hata: Okuma başarısız."

async def tum_sinavlari_oku(anahtar, ogrenciler, talimat, api_key):
    sonuclar = []
    bar = st.progress(0)
    durum = st.empty()
    toplam = len(ogrenciler)
    
    for i, (name, data) in enumerate(ogrenciler.items()):
        durum.info(f"Okunuyor: {name} ({i+1}/{toplam})")
        prompt = f"Cevap Anahtarı: {anahtar}\nTalimat: {talimat}\n\nLütfen öğrenciyi puanla. Yanıtı 'Öğrenci: [İsim], Puan: [Puan], Detay: [Kısa Not]' formatında ver."
        res = await gemi_analiz_yap(data, prompt, api_key)
        sonuclar.append({"Dosya": name, "Analiz": res})
        bar.progress((i + 1) / toplam)
    
    durum.success("✅ Analiz tamamlandı!")
    return sonuclar

# --- 4. CSS TASARIM ---
st.markdown("""
    <style>
    .header-box {
        background-color: white; padding: 15px; 
        border-bottom: 3px solid #1976D2; border-radius: 0 0 15px 15px;
        margin-bottom: 25px; box-shadow: 0px 4px 10px rgba(0,0,0,0.05);
    }
    .stButton>button { border-radius: 10px; font-weight: bold; }
    [data-testid="stFileUploaderDropzoneInstructions"] { display: none; }
    </style>
    """, unsafe_allow_html=True)

# --- 5. HAFIZA ---
if "auth" not in st.session_state: st.session_state.auth = False
if "anahtar_depo" not in st.session_state: st.session_state.anahtar_depo = {}
if "ogrenci_depo" not in st.session_state: st.session_state.ogrenci_depo = {}
if "secili_img" not in st.session_state: st.session_state.secili_img = None
if "anahtar_metin_sonuc" not in st.session_state: st.session_state.anahtar_metin_sonuc = ""

# --- 6. GİRİŞ PANELİ ---
st.markdown('<div class="header-box">', unsafe_allow_html=True)
h1, h2, h3 = st.columns([0.25, 0.55, 0.2])

with h1:
    st.markdown("<h2 style='color: #0D47A1; margin:0;'>MAVi-GÖZ V4</h2>", unsafe_allow_html=True)

with h2:
    if not st.session_state.auth:
        l1, l2, l3 = st.columns([0.35, 0.35, 0.3])
        uid = l1.text_input("ID", placeholder="ID", label_visibility="collapsed")
        upass = l2.text_input("Şifre", type="password", placeholder="Şifre", label_visibility="collapsed")
        if l3.button("Giriş", use_container_width=True):
            doc = db.collection("users").document(uid).get()
            if doc.exists and str(doc.to_dict().get("sifre")) == upass:
                st.session_state.auth = True
                st.session_state.api_key = doc.to_dict().get("api_key")
                st.rerun()
            else: st.toast("Hatalı Giriş!", icon="🔒")
    else:
        st.markdown("<p style='color:#1976D2; font-weight:bold; text-align:center; margin-top:10px;'>Hoş geldin Hocam! ✅</p>", unsafe_allow_html=True)

with h3:
    if st.session_state.auth:
        if st.button("Çıkış"):
            st.session_state.auth = False
            st.rerun()
    else:
        st.markdown("<p style='color:red; text-align:right; font-weight:bold; margin-top:10px;'>KİLİTLİ 🔒</p>", unsafe_allow_html=True)
st.markdown('</div>', unsafe_allow_html=True)

# --- 7. ANA EKRAN ---
if st.session_state.auth:
    c_gal, c_pre, c_ana = st.columns([0.25, 0.45, 0.3])

    with c_gal:
        st.subheader("📁 Galeri")
        ua = st.file_uploader("A", type=['jpg','png','jpeg'], accept_multiple_files=True, key="ua", label_visibility="collapsed")
        if ua:
            for f in ua: st.session_state.anahtar_depo[f.name] = f.getvalue()
        for n, d in list(st.session_state.anahtar_depo.items()):
            c1, c2, c3 = st.columns([0.6, 0.2, 0.2])
            c1.image(d)
            if c2.button("👁️", key=f"va_{n}"): st.session_state.secili_img = d
            if c3.button("❌", key=f"da_{n}"): del st.session_state.anahtar_depo[n]; st.rerun()

        st.divider()
        us = st.file_uploader("S", type=['jpg','png','jpeg'], accept_multiple_files=True, key="us", label_visibility="collapsed")
        if us:
            for f in us: st.session_state.ogrenci_depo[f.name] = f.getvalue()
        for n, d in list(st.session_state.ogrenci_depo.items()):
            c1, c2, c3 = st.columns([0.6, 0.2, 0.2])
            c1.image(d)
            if c2.button("👁️", key=f"vs_{n}"): st.session_state.secili_img = d
            if c3.button("❌", key=f"ds_{n}"): del st.session_state.ogrenci_depo[n]; st.rerun()

    with c_pre:
        st.subheader("🖼️ Önizleme")
        if st.session_state.secili_img:
            st.image(st.session_state.secili_img, use_container_width=True)

    with c_ana:
        st.subheader("📝 Analiz")
        st.text_area("Cevap Anahtarı", value=st.session_state.anahtar_metin_sonuc, height=200)
        if st.button("📖 OKUT", use_container_width=True):
            if st.session_state.anahtar_depo:
                with st.spinner("Okunuyor..."):
                    img = list(st.session_state.anahtar_depo.values())[0]
                    st.session_state.anahtar_metin_sonuc = asyncio.run(gemi_analiz_yap(img, "Anahtarı çıkar.", st.session_state.api_key))
                    st.rerun()

        st.divider()
        talimat = st.text_area("Talimat", value="Puanla.", height=100)
        if st.button("🚀 BAŞLAT", type="primary", use_container_width=True):
            if st.session_state.anahtar_metin_sonuc and st.session_state.ogrenci_depo:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                res = loop.run_until_complete(tum_sinavlari_oku(st.session_state.anahtar_metin_sonuc, st.session_state.ogrenci_depo, talimat, st.session_state.api_key))
                st.session_state.analiz_df = pd.DataFrame(res)
        
        if "analiz_df" in st.session_state:
            st.dataframe(st.session_state.analiz_df)
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                st.session_state.analiz_df.to_excel(writer, index=False)
            st.download_button("📥 Excel", data=output.getvalue(), file_name="analiz.xlsx")
else:
    st.info("Lütfen giriş yapın.")