import streamlit as st
import yfinance as yf
import pandas as pd
import ta
import warnings
import logging
import plotly.graph_objects as go

warnings.filterwarnings('ignore')
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- SAYFA AYARLARI ---
st.set_page_config(page_title="Ultimate Quant Bot v4.0", page_icon="🛡️", layout="wide")

# --- 1. GÜVENLİK: ŞİFRE SİSTEMİ (Sabit) ---
try:
    beklenen_sifre = st.secrets["sistem_sifresi"]
except KeyError:
    st.error("🚨 Sistem Hatası: Streamlit 'Secrets' bölümüne 'sistem_sifresi' ekleyin.")
    st.stop()

# --- 2. YAPILANDIRMA ---
class BotConfig:
    def __init__(self, rsi_al, rsi_sat, atr_stop, atr_kar, sermaye, risk_orani):
        self.rsi_al = rsi_al
        self.rsi_sat = rsi_sat
        self.atr_stop = atr_stop
        self.atr_kar = atr_kar
        self.sermaye = sermaye
        self.risk_orani = risk_orani

# --- 3. VERİ YÖNETİMİ ---
class DataFetcher:
    @staticmethod
    def veri_indir(hisse_kodu):
        try:
            ticker = yf.Ticker(hisse_kodu)
            gunluk_veri = ticker.history(period="2y", interval="1d")
            haftalik_veri = ticker.history(period="5y", interval="1wk")
            if gunluk_veri.empty or haftalik_veri.empty or len(haftalik_veri) < 50: return None, None, None
            info = ticker.info
            fk = info.get('trailingPE', None)
            return gunluk_veri, haftalik_veri, fk
        except: return None, None, None
            
    @staticmethod
    def endeks_durumu_getir():
        try:
            xu100 = yf.Ticker("XU100.IS").history(period="1y", interval="1d")
            kapanis = xu100['Close']
            sma_50 = ta.trend.SMAIndicator(close=kapanis, window=50).sma_indicator().iloc[-1]
            durum = "BOĞA 🟢" if kapanis.iloc[-1] > sma_50 else "AYI 🔴"
            return durum, kapanis.iloc[-1], sma_50
        except: return "BİLİNMİYOR ⚪", 0, 0

# --- 4. TEKNİK ANALİZ (VWAP + İzleyen Stop Verisi) ---
class TechnicalAnalyzer:
    @staticmethod
    def gostergeleri_hesapla(veri, periyot="gunluk"):
        df = veri.copy()
        kapanis = df['Close']; hacim = df['Volume']; yuksek = df['High']; dusuk = df['Low']
        
        if periyot == "haftalik":
            df['SMA_50'] = ta.trend.SMAIndicator(close=kapanis, window=50).sma_indicator()
        else:
            df['RSI'] = ta.momentum.RSIIndicator(close=kapanis, window=14).rsi()
            df['SMA_200'] = ta.trend.SMAIndicator(close=kapanis, window=200).sma_indicator()
            atr_ind = ta.volatility.AverageTrueRange(high=yuksek, low=dusuk, close=kapanis, window=14)
            df['ATR'] = atr_ind.average_true_range()
            # Smart Money: VWAP
            tipik = (yuksek + dusuk + kapanis) / 3
            df['VWAP'] = (tipik * hacim).cumsum() / hacim.cumsum()
            df['Highest_10'] = yuksek.rolling(window=10).max()
        df.dropna(inplace=True)
        return df

# --- 5. HEDGE FON STRATEJİSİ ---
class QuantStrategy:
    def __init__(self, config, piyasa_rejimi):
        self.config = config
        self.piyasa_rejimi = piyasa_rejimi

    def analiz_et(self, hisse_kodu):
        gunluk, haftalik, fk = DataFetcher.veri_indir(hisse_kodu)
        if gunluk is None: return None, None
        
        kapanis_ham = gunluk['Close'].copy()
        gunluk = TechnicalAnalyzer.gostergeleri_hesapla(gunluk, "gunluk")
        haftalik = TechnicalAnalyzer.gostergeleri_hesapla(haftalik, "haftalik")
        
        s = gunluk.iloc[-1]
        fiyat = s['Close']
        # Dinamik İzleyen Stop (Trailing Stop)
        stop = max(s['Highest_10'] - (s['ATR'] * self.config.atr_stop), fiyat - (s['ATR'] * self.config.atr_stop))
        
        # Risk Optimizasyonu
        risk = self.config.risk_orani / 2 if "AYI" in self.piyasa_rejimi else self.config.risk_orani
        lot = int((self.config.sermaye * risk) / (fiyat - stop)) if (fiyat - stop) > 0 else 0
        
        skor = 0
        if "BOĞA" in self.piyasa_rejimi: skor += 20
        if fiyat > s['VWAP']: skor += 20 # Kurumsal Destek
        if fiyat > s['SMA_200']: skor += 15
        
        karar = "🔥 KESİN AL" if skor >= 50 else "⚪ İZLEMEDE"
        
        return {"Hisse": hisse_kodu.replace(".IS", ""), "Fiyat": round(fiyat, 2), "Karar": karar, "Lot": lot, "İzleyen Stop": round(stop, 2)}, kapanis_ham

# --- 6. ARAYÜZ ---
def ui_olustur():
    st.title("🛡️ Hedge Fon Modu: Quant Bot v4.0")
    girilen_sifre = st.sidebar.text_input("Şifre:", type="password")
    if girilen_sifre != beklenen_sifre: st.stop()

    rejimi, _, _ = DataFetcher.endeks_durumu_getir()
    st.info(f"Piyasa Rejimi: {rejimi}")
    
    # [Analiz döngüsü ve korelasyon hesaplamaları burada çalışır...]
    # (Önceki kodun UI bloğunu buraya entegre edebilirsin)
    
if __name__ == "__main__":
    ui_olustur()
