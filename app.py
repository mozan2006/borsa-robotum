import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import ta
import requests
import xml.etree.ElementTree as ET
import plotly.graph_objects as go
from concurrent.futures import ThreadPoolExecutor

# Gemini Kütüphane Kontrolü
try: import google.generativeai as genai
except ImportError: genai = None

st.set_page_config(page_title="Ultimate Quant Bot v9.1", layout="wide")

# --- 0. GÜVENLİK ---
if "giris_basarili" not in st.session_state: st.session_state["giris_basarili"] = False
if not st.session_state["giris_basarili"]:
    st.title("🔒 Sistem Erişimi")
    pw = st.text_input("Şifre:", type="password")
    if st.button("Giriş"):
        if pw == st.secrets.get("sistem_sifresi", "admin123"):
            st.session_state["giris_basarili"] = True
            st.rerun()
    st.stop()

# --- 1. MODÜLLER ---
class DataFetcher:
    @staticmethod
    def haber_analizi_gemini(hisse_kodu):
        temiz_isim = hisse_kodu.replace(".IS", "")
        try:
            url = f"https://news.google.com/rss/search?q={temiz_isim}+hisse+ihale+kap+temettü&hl=tr&gl=TR&ceid=TR:tr"
            yanit = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
            root = ET.fromstring(yanit.content)
            haberler = [item.find('title').text for item in root.findall('.//item')[:5]]
            if not haberler or not genai: return 0, "Nötr / Haber Yok"
            model = genai.GenerativeModel('gemini-1.5-flash')
            prompt = f"{haberler} başlıklarının {temiz_isim} hissesine etkisi -100 ile +100 arası? Sadece tam sayı ver."
            response = model.generate_content(prompt)
            skor = int(''.join(c for c in response.text if c.isdigit() or c == '-'))
            durum = "🔥 Pozitif" if skor > 15 else ("⚠️ Negatif" if skor < -15 else "⚪ Nötr")
            return skor, durum
        except: return 0, "Nötr"

    @staticmethod
    def analiz_et(hisse_kodu):
        try:
            ticker = yf.Ticker(hisse_kodu)
            df = ticker.history(period="6mo", interval="1d")
            bb = ta.volatility.BollingerBands(close=df['Close'], window=20)
            df['BB_High'], df['BB_Low'] = bb.bollinger_hband(), bb.bollinger_lband()
            
            skor, durum = DataFetcher.haber_analizi_gemini(hisse_kodu)
            
            # Karar Mekanizması
            karar = "⚪ İZLEMEDE"
            if df['Close'].iloc[-1] <= df['BB_Low'].iloc[-1] and skor >= 0: karar = "🟢 POTANSİYEL AL"
            
            return {"Hisse": hisse_kodu.replace(".IS", ""), "Karar": karar, "Gündem": durum, "Fiyat": round(df['Close'].iloc[-1], 2), "Grafik": df}
        except: return None

# --- 2. UI MENÜLER ---
st.title("🚀 Ultimate Quant Bot v9.1")

# MANUEL TARAMA
st.sidebar.markdown("### 🔍 Manuel Tarama")
hisseler_metin = st.sidebar.text_area("Hisseler:", "ASELS\nASTOR\nKRDMD", height=100)
if st.sidebar.button("Manuel Analizi Başlat"):
    hisseler = [h.strip().upper() + ".IS" for h in hisseler_metin.split("\n")]
    for h in hisseler:
        sonuc = DataFetcher.analiz_et(h)
        if sonuc:
            st.write(f"### {sonuc['Hisse']} - {sonuc['Karar']}")
            st.write(f"Fiyat: {sonuc['Fiyat']} ₺ | Gündem: {sonuc['Gündem']}")

# OTOMATİK FIRSAT RADARI (KATILIM ENDEKSİ)
st.markdown("### 📡 Otomatik Fırsat Radarı (Katılım Endeksi)")
if st.button("🔍 Katılım Endeksi Eşzamanlı Radarını Çalıştır"):
    katilim_hisseler = ["ALBRK.IS", "ASELS.IS", "ASTOR.IS", "BIMAS.IS", "CIMSA.IS", "ENJSA.IS", "FROTO.IS", "KRDMD.IS", "MPARK.IS", "OTKAR.IS", "SASA.IS", "YUNSA.IS"]
    with ThreadPoolExecutor(max_workers=5) as executor:
        sonuclar = list(executor.map(DataFetcher.analiz_et, katilim_hisseler))
    
    for s in [x for x in sonuclar if x and x['Karar'] != "⚪ İZLEMEDE"]:
        st.success(f"🚨 {s['Hisse']} için alım sinyali: {s['Karar']} (Gündem: {s['Gündem']})")

if 'GEMINI_API_KEY' in st.secrets:
    genai.configure(api_key=st.secrets['GEMINI_API_KEY'])
