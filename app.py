import streamlit as st
import yfinance as yf
import pandas as pd
import ta
import warnings
import logging
import plotly.graph_objects as go
import itertools

warnings.filterwarnings('ignore')
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- SAYFA AYARLARI ---
st.set_page_config(page_title="Ultimate Quant Bot v4.0", page_icon="📈", layout="wide")

# --- 1. YAPILANDIRMA ---
class BotConfig:
    def __init__(self, rsi_al, rsi_sat, atr_stop, atr_kar, sermaye, risk_orani):
        self.rsi_al = rsi_al
        self.rsi_sat = rsi_sat
        self.atr_stop = atr_stop
        self.atr_kar = atr_kar
        self.sermaye = sermaye
        self.risk_orani = risk_orani

# --- 2. VERİ YÖNETİMİ ---
class DataFetcher:
    @staticmethod
    def veri_indir(hisse_kodu):
        try:
            ticker = yf.Ticker(hisse_kodu)
            gunluk_veri = ticker.history(period="2y", interval="1d")
            haftalik_veri = ticker.history(period="5y", interval="1wk")
            
            if gunluk_veri.empty or haftalik_veri.empty or len(haftalik_veri) < 50: 
                return None, None, None
            
            info = ticker.info
            fk = info.get('trailingPE', None)
            
            return gunluk_veri, haftalik_veri, fk
        except Exception as e:
            logging.error(f"Veri çekme hatası ({hisse_kodu}): {e}")
            return None, None, None
            
    @staticmethod
    def endeks_durumu_getir():
        try:
            xu100 = yf.Ticker("XU100.IS").history(period="1y", interval="1d")
            if not xu100.empty:
                kapanis = xu100['Close']
                sma_50 = ta.trend.SMAIndicator(close=kapanis, window=50).sma_indicator().iloc[-1]
                son_fiyat = kapanis.iloc[-1]
                
                durum = "BOĞA 🟢" if son_fiyat > sma_50 else "AYI 🔴"
                return durum, son_fiyat, sma_50
            return "BİLİNMİYOR ⚪", 0, 0
        except:
            return "BİLİNMİYOR ⚪", 0, 0

# --- 3. TEKNİK ANALİZ (VWAP Eklendi) ---
class TechnicalAnalyzer:
    @staticmethod
    def gostergeleri_hesapla(veri, periyot="gunluk"):
        df = veri.copy()
        kapanis = df['Close']
        hacim = df['Volume']
        yuksek = df['High']
        dusuk = df['Low']
        
        if periyot == "haftalik":
            df['SMA_50'] = ta.trend.SMAIndicator(close=kapanis, window=50).sma_indicator()
            
        elif periyot == "gunluk":
            df['RSI'] = ta.momentum.RSIIndicator(close=kapanis, window=14).rsi()
            macd = ta.trend.MACD(close=kapanis)
            df['MACD_Line'] = macd.macd()
            df['MACD_Signal'] = macd.macd_signal()
            df['SMA_200'] = ta.trend.SMAIndicator(close=kapanis, window=200).sma_indicator()
            df['SMA_50'] = ta.trend.SMAIndicator(close=kapanis, window=50).sma_indicator()
            df['SMA_20'] = ta.trend.SMAIndicator(close=kapanis, window=20).sma_indicator()
            
            atr_ind = ta.volatility.AverageTrueRange(high=yuksek, low=dusuk, close=kapanis, window=14)
            df['ATR'] = atr_ind.average_true_range()
            df['Hacim_Ort_20'] = hacim.rolling(window=20).mean()
            
            bollinger = ta.volatility.BollingerBands(close=kapanis, window=20, window_dev=2)
            df['BB_Alt'] = bollinger.bollinger_lband()
            
            # Smart Money / Kurumsal Para Takibi (20 Günlük Rolling VWAP)
            tipik_fiyat = (yuksek + dusuk + kapanis) / 3
            df['VWAP_20'] = (tipik_fiyat * hacim).rolling(window=20).sum() / hacim.rolling(window=20).sum()
            
            # İzleyen Stop için Son 10 Günün Zirvesi
            df['Highest_10'] = yuksek.rolling(window=10).max()
        
        df.dropna(inplace=True)
        return df

# --- 4. STRATEJİ VE RİSK YÖNETİMİ ---
class QuantStrategy:
    def __init__(self, config, piyasa_rejimi):
        self.config = config
        self.piyasa_rejimi = piyasa_rejimi

    def pozisyon_buyuklugu_hesapla(self, fiyat, stop_loss):
        # Piyasa AYI ise alınan riski otomatik olarak yarıya düşür (Risk Optimizasyonu)
        aktif_risk_orani = self.config.risk_orani / 2 if "AYI" in self.piyasa_rejimi else self.config.risk_orani
        risk_miktari = self.config.sermaye * aktif_risk_orani
        hisse_basina_risk = fiyat - stop_loss
        
        if hisse_basina_risk <= 0: return 0
        alinacak_lot = int(risk_miktari / hisse_basina_risk)
        return alinacak_lot

    def analiz_et(self, hisse_kodu):
        gunluk, haftalik, fk_orani = DataFetcher.veri_indir(hisse_kodu)
        if gunluk is None or haftalik is None: return None, None
            
        kapanis_fiyatlari = gunluk['Close'].copy() # Korelasyon için ham kapanışları sakla
        
        gunluk = TechnicalAnalyzer.gostergeleri_hesapla(gunluk, periyot="gunluk")
        haftalik = TechnicalAnalyzer.gostergeleri_hesapla(haftalik, periyot="haftalik")
        
        if gunluk.empty or haftalik.empty: return None, None
            
        son_gunluk = gunluk.iloc[-1]
        son_haftalik = haftalik.iloc[-1]
        
        fiyat = float(son_gunluk['Close'])
        rsi = float(son_gunluk['RSI'])
        atr = float(son_gunluk['ATR'])
        
        # Statik yerine İzleyen Stop (Trailing Stop)
        zirve_10 = float(son_gunluk['Highest_10'])
        izleyen_stop = zirve_10 - (atr * self.config.atr_stop)
        # Eğer hesaplanan stop fiyatın üzerindeyse (ani düşüş vb.), fiyatın kendisinden ATR çıkar
        izleyen_stop = izleyen_stop if izleyen_stop < fiyat else fiyat - (atr * self.config.atr_stop)
        
        kar_al = fiyat + (atr * self.config.atr_kar)
        
        skor = 0
        nedenler = []
        
        # Piyasa Rejimi (XU100) Filtresi
        if "AYI" in self.piyasa_rejimi:
            skor -= 20
            nedenler.append("BIST Ayı Piyasasında")
        
        # Haftalık Trend
        if son_haftalik['Close'] > son_haftalik['SMA_50']:
            skor += 25; nedenler.append("Haftalık Trend Güçlü")
        else:
            nedenler.append("Haftalık Trend Zayıf")

        # Smart Money (VWAP) Onayı
        if fiyat > son_gunluk['VWAP_20']:
            skor += 20; nedenler.append("Kurumsal Para Desteği (VWAP)")
            
        # Günlük Momentum ve Trend
        if fiyat > son_gunluk['SMA_200']: skor += 10; nedenler.append("200G Ort. Üzerinde")
        if rsi < self.config.rsi_al: skor += 15; nedenler.append("RSI Aşırı Satım")
        if son_gunluk['MACD_Line'] > son_gunluk['MACD_Signal']: skor += 15; nedenler.append("MACD Alımda")
        if son_gunluk['Volume'] > son_gunluk['Hacim_Ort_20']: skor += 10; nedenler.append("Hacim Onayı")
