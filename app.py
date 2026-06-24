import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import ta
import requests
import xml.etree.ElementTree as ET

# Gemini Kütüphane Kontrolü
try: import google.generativeai as genai
except ImportError: genai = None

st.set_page_config(page_title="Ultimate Quant Bot v9.2", layout="wide")

# --- 1. FONKSİYONLAR ---
def haber_analizi_gemini(hisse_kodu):
    temiz_isim = hisse_kodu.replace(".IS", "")
    try:
        url = f"https://news.google.com/rss/search?q={temiz_isim}+hisse+ihale+kap+temettü&hl=tr&gl=TR&ceid=TR:tr"
        yanit = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
        root = ET.fromstring(yanit.content)
        haberler = [item.find('title').text for item in root.findall('.//item')[:3]]
        if not haberler or not genai: return 0, "Nötr"
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content(f"{haberler} hisse etkisini -100/+100 arası puanla. Sadece sayı.")
        skor = int(''.join(c for c in response.text if c.isdigit() or c == '-'))
        return skor, ("Pozitif" if skor > 10 else "Negatif" if skor < -10 else "Nötr")
    except: return 0, "Nötr"

def analiz_et(hisse_kodu):
    try:
        ticker = yf.Ticker(hisse_kodu)
        df = ticker.history(period="1mo", interval="1d")
        if df.empty: return None
        bb = ta.volatility.BollingerBands(close=df['Close'], window=20)
        df['BB_Low'] = bb.bollinger_lband()
        
        skor, durum = haber_analizi_gemini(hisse_kodu)
        
        # Sinyal mantığı: Fiyat alt banda yakınsa ve haber nötr/pozitifse
        if df['Close'].iloc[-1] <= df['BB_Low'].iloc[-1]:
            return {"Hisse": hisse_kodu.replace(".IS", ""), "Fiyat": round(df['Close'].iloc[-1], 2), "Gündem": durum}
        return None
    except: return None

# --- 2. ARAYÜZ ---
st.title("🚀 Ultimate Quant Bot v9.2")

if st.button("🔍 Katılım Endeksi Eşzamanlı Radarını Çalıştır"):
    with st.spinner('Analiz başlatılıyor, lütfen bekleyin...'):
        katilim_hisseler = ["ASELS.IS", "ASTOR.IS", "BIMAS.IS", "CIMSA.IS", "ENJSA.IS", "FROTO.IS", "KRDMD.IS", "MPARK.IS", "OTKAR.IS", "SASA.IS", "YUNSA.IS"]
        bulunanlar = []
        
        for h in katilim_hisseler:
            sonuc = analiz_et(h)
            if sonuc:
                bulunanlar.append(sonuc)
        
        if bulunanlar:
            st.success("Tarama tamamlandı!")
            for s in bulunanlar:
                st.write(f"✅ **{s['Hisse']}** - Fiyat: {s['Fiyat']} ₺ | Haber: {s['Gündem']}")
        else:
            st.warning("Şu an Bollinger alt bandına değen katılım hissesi bulunamadı.")

if 'GEMINI_API_KEY' in st.secrets:
    genai.configure(api_key=st.secrets['GEMINI_API_KEY'])
