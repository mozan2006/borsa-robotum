import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import ta
import warnings
import logging
import requests
import datetime
import xml.etree.ElementTree as ET
import plotly.graph_objects as go
from concurrent.futures import ThreadPoolExecutor
from sklearn.ensemble import RandomForestClassifier

# Gemini Kütüphane Kontrolü
try:
    import google.generativeai as genai
except ImportError:
    genai = None

warnings.filterwarnings('ignore')
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- SAYFA AYARLARI ---
st.set_page_config(page_title="Ultimate Quant Bot v9.0", page_icon="🤖", layout="wide")

# --- 0. GÜVENLİK ---
def sifre_kontrol():
    if "giris_basarili" not in st.session_state: st.session_state["giris_basarili"] = False
    if not st.session_state["giris_basarili"]:
        st.markdown("<h1 style='text-align: center;'>🔒 Sistem Erişimi</h1>", unsafe_allow_html=True)
        password = st.text_input("Şifre:", type="password")
        if st.button("Giriş"):
            if password == st.secrets.get("sistem_sifresi", "admin123"):
                st.session_state["giris_basarili"] = True
                st.rerun()
        st.stop()

sifre_kontrol()

# --- 1. YARDIMCI MODÜLLER ---
class DataFetcher:
    @staticmethod
    def haber_analizi_gemini(hisse_kodu):
        temiz_isim = hisse_kodu.replace(".IS", "")
        # RSS Haber Motoru
        try:
            url = f"https://news.google.com/rss/search?q={temiz_isim}+hisse+ihale+kap+temettü&hl=tr&gl=TR&ceid=TR:tr"
            yanit = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
            root = ET.fromstring(yanit.content)
            haberler = [item.find('title').text for item in root.findall('.//item')[:5]]
        except: haberler = []

        if not haberler or not genai: return 0, "Nötr / Haber Yok"
        
        try:
            model = genai.GenerativeModel('gemini-1.5-flash')
            prompt = f"Borsa İstanbul uzmanısın. {haberler} başlıklarının {temiz_isim} hissesine etkisi -100 ile +100 arası? Sadece tam sayı ver."
            response = model.generate_content(prompt)
            skor = int(''.join(c for c in response.text if c.isdigit() or c == '-'))
            durum = "🔥 Gemini: Pozitif" if skor > 15 else ("⚠️ Gemini: Negatif" if skor < -15 else "⚪ Gemini: Nötr")
            return skor, durum
        except: return 0, "Nötr"

    @staticmethod
    def veri_indir(hisse_kodu):
        try:
            ticker = yf.Ticker(hisse_kodu)
            df = ticker.history(period="2y", interval="1d")
            # Bollinger Bantları Ekleme
            bb = ta.volatility.BollingerBands(close=df['Close'], window=20, window_dev=2)
            df['BB_High'], df['BB_Low'] = bb.bollinger_hband(), bb.bollinger_lband()
            
            # API üzerinden haber analizi
            skor, durum = DataFetcher.haber_analizi_gemini(hisse_kodu)
            return df, skor, durum
        except: return None, 0, "Hata"

# --- 2. GRAFİK VE STRATEJİ ---
def cizgi_grafik_olustur(df, hisse, al, stop, kar):
    fig = go.Figure()
    fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='Fiyat'))
    # Bollinger Çizgileri
    fig.add_trace(go.Scatter(x=df.index, y=df['BB_High'], line=dict(color='gray', width=1, dash='dot'), name='BB Üst'))
    fig.add_trace(go.Scatter(x=df.index, y=df['BB_Low'], line=dict(color='gray', width=1, dash='dot'), name='BB Alt'))
    fig.add_hline(y=al, line_color="blue"); fig.add_hline(y=stop, line_color="red"); fig.add_hline(y=kar, line_color="green")
    fig.update_layout(template="plotly_dark", height=300, xaxis_rangeslider_visible=False)
    return fig

# --- 3. ANA MOTOR ---
def ui_olustur():
    st.title("🚀 Ultimate Quant Bot v9.0")
    hisseler_metin = st.sidebar.text_area("Hisseler:", "ASELS\nASTOR\nKRDMD", height=100)
    
    if st.sidebar.button("Analizi Başlat"):
        hisse_listesi = [h.strip().upper() + ".IS" for h in hisseler_metin.split("\n")]
        
        for h in hisse_listesi:
            df, skor, durum = DataFetcher.veri_indir(h)
            if df is not None:
                st.subheader(f"{h} Analizi")
                st.write(f"📰 **Gündem:** {durum}")
                fig = cizgi_grafik_olustur(df.tail(60), h, df['Close'].iloc[-1], df['BB_Low'].iloc[-1], df['BB_High'].iloc[-1])
                st.plotly_chart(fig, use_container_width=True)

if __name__ == "__main__":
    # Gemini API anahtarını tanımla (Google AI Studio'dan alın)
    if 'GEMINI_API_KEY' in st.secrets:
        genai.configure(api_key=st.secrets['GEMINI_API_KEY'])
    ui_olustur()
