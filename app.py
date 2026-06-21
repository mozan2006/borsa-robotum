import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import ta
import warnings
import logging
import requests
import datetime
from concurrent.futures import ThreadPoolExecutor

warnings.filterwarnings('ignore')
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- SAYFA AYARLARI ---
st.set_page_config(page_title="Ultimate Quant Bot v7.0", page_icon="🤖", layout="wide")

# --- 0. GÜVENLİK VE OTURUM YÖNETİMİ ---
def sifre_kontrol():
    if "giris_basarili" not in st.session_state:
        st.session_state["giris_basarili"] = False

    if not st.session_state["giris_basarili"]:
        st.markdown("<h1 style='text-align: center;'>🔒 Sistem Erişimi</h1>", unsafe_allow_html=True)
        st.markdown("<p style='text-align: center;'>Bu, kapalı devre bir Quant Fon arayüzüdür. Lütfen erişim şifrenizi girin.</p>", unsafe_allow_html=True)
        
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            with st.form("login_form"):
                girilen_sifre = st.text_input("Erişim Şifresi:", type="password")
                submit_button = st.form_submit_button("Sisteme Giriş Yap", use_container_width=True)
                
                if submit_button:
                    try:
                        dogru_sifre = st.secrets["sistem_sifresi"]
                    except:
                        dogru_sifre = "admin123"
                        
                    if girilen_sifre == dogru_sifre:
                        st.session_state["giris_basarili"] = True
                        st.success("Giriş Başarılı! Sistem Yükleniyor...")
                        st.rerun()
                    else:
                        st.error("🚨 Hatalı Şifre! Lütfen tekrar deneyin.")
        st.stop()

sifre_kontrol()

if st.sidebar.button("🚪 Çıkış Yap", use_container_width=True):
    st.session_state["giris_basarili"] = False
    st.rerun()

# --- 1. YAPILANDIRMA ---
class BotConfig:
    def __init__(self, rsi_al, rsi_sat, atr_stop, atr_kar, sermaye, komisyon, slippage):
        self.rsi_al = rsi_al
        self.rsi_sat = rsi_sat
        self.atr_stop = atr_stop
        self.atr_kar = atr_kar
        self.sermaye = sermaye
        self.komisyon = komisyon
        self.slippage = slippage

# --- 2. ÇİFT MOTORLU VERİ VE DUYGU ANALİZİ (YF + İŞ YATIRIM YEDEKLİ) ---
class DataFetcher:
    @staticmethod
    @st.cache_data(ttl=1800, show_spinner=False)
    def veri_indir(hisse_kodu):
        # --- BİRİNCİL DENEME: YAHOO FINANCE ---
        try:
            ticker = yf.Ticker(hisse_kodu)
            gunluk_veri = ticker.history(period="2y", interval="1d")
            
            if not gunluk_veri.empty and len(gunluk_veri) >= 60:
                haftalik_veri = ticker.history(period="5y", interval="1wk")
                info = ticker.info
                temel_veriler = {
                    'fk': info.get('trailingPE', None),
                    'pd_dd': info.get('priceToBook', None),
                    'roe': info.get('returnOnEquity', None)
                }
                son_hacim_degisimi = gunluk_veri['Volume'].pct_change().iloc[-1]
                duygu_skoru = np.clip(son_hacim_degisimi * 100, -100, 100)
                
                return gunluk_veri, haftalik_veri, temel_veriler, duygu_skoru
        except Exception as e:
            logging.warning(f"YFinance hatası ({hisse_kodu}). Yedek sisteme geçiliyor...")

        # --- İKİNCİL DENEME (FALLBACK): İŞ YATIRIM API ---
        try:
            sembol = hisse_kodu.replace(".IS", "")
            bitis_tarihi = datetime.datetime.now().strftime("%d-%m-%Y")
            baslangic_tarihi = (datetime.datetime.now() - datetime.timedelta(days=730)).strftime("%d-%m-%Y")
            
            url = f"https://www.isyatirim.com.tr/_layouts/15/IsYatirim.Website/Common/Data.aspx/HisseTekil?hisse={sembol}&startdate={baslangic_tarihi}&enddate={bitis_tarihi}"
            headers = {'User-Agent': 'Mozilla/5.0'}
            
            response = requests.get(url, headers=headers, timeout=10)
            veri_json = response.json()
            
            if 'value' in veri_json and veri_json['value']:
                df = pd.DataFrame(veri_json['value'])
                df['Date'] = pd.to_datetime(df['HGDG_TARIH'], format='%d-%m-%Y')
                df.set_index('Date', inplace=True)
                
                df.rename(columns={'KAPANIS': 'Close', 'MAX': 'High', 'MIN': 'Low', 'ISLEM_MIKTARI': 'Volume'}, inplace=True)
                df['Open'] = df['Close'].shift(1).fillna(df['Close'])
                
                gunluk_veri = df[['Open', 'High', 'Low', 'Close', 'Volume']].astype(float)
                
                if len(gunluk_
