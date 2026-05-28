import streamlit as st
import yfinance as yf
import pandas as pd
import ta
import warnings
import logging
import plotly.graph_objects as go
from concurrent.futures import ThreadPoolExecutor, as_completed

warnings.filterwarnings('ignore')
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- SAYFA AYARLARI ---
st.set_page_config(page_title="Ultimate Quant Bot v3.0", page_icon="📈", layout="wide")

# --- 1. YAPILANDIRMA SINIFI (CONFIG) ---
class BotConfig:
    def __init__(self, rsi_al, rsi_sat, atr_stop, atr_kar, sermaye, risk_orani):
        self.rsi_al = rsi_al
        self.rsi_sat = rsi_sat
        self.atr_stop = atr_stop
        self.atr_kar = atr_kar
        self.sermaye = sermaye
        self.risk_orani = risk_orani

# --- 2. VERİ YÖNETİMİ SINIFI ---
class DataFetcher:
    @staticmethod
    def veri_indir(hisse_kodu):
        try:
            # Çoklu Zaman Dilimi: Hem günlük hem haftalık veri çekiyoruz
            gunluk_veri = yf.download(hisse_kodu, period="2y", interval="1d", progress=False)
            haftalik_veri = yf.download(hisse_kodu, period="2y", interval="1wk", progress=False)
            
            if gunluk_veri.empty or len(gunluk_veri) < 50: 
                return None, None, None
                
            if isinstance(gunluk_veri.columns, pd.MultiIndex): 
                gunluk_veri.columns = gunluk_veri.columns.droplevel(1)
                haftalik_veri.columns = haftalik_veri.columns.droplevel(1)
            
            info = yf.Ticker(hisse_kodu).info
            fk = info.get('trailingPE', None)
            
            return gunluk_veri, haftalik_veri, fk
        except Exception as e:
            logging.error(f"Veri çekme hatası ({hisse_kodu}): {e}")
            return None, None, None

# --- 3. TEKNİK ANALİZ SINIFI ---
class TechnicalAnalyzer:
    @staticmethod
    def gostergeleri_hesapla(veri):
        df = veri.copy()
        kapanis = df['Close']
        hacim = df['Volume']
        yuksek = df['High']
        dusuk = df['Low']
        
        df['RSI'] = ta.momentum.RSIIndicator(close=kapanis, window=14).rsi()
        macd = ta.trend.MACD(close=kapanis)
        df['MACD_Line'] = macd.macd()
        df['MACD_Signal'] = macd.macd
