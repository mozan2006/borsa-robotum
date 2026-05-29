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
st.set_page_config(page_title="Ultimate Quant Bot v4.0", page_icon="📈", layout="wide")

# --- 1. GÜVENLİK: ŞİFRE SİSTEMİ (İSTEDİĞİN GİBİ) ---
try:
    beklenen_sifre = st.secrets["sistem_sifresi"]
except KeyError:
    st.error("🚨 Sistem Hatası: Şifre ayarlanmamış! Lütfen Streamlit Cloud üzerinden 'Secrets' bölümüne 'sistem_sifresi' değerini ekleyin.")
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

# --- 4. TEKNİK ANALİZ ---
class TechnicalAnalyzer:
    @staticmethod
    def gostergeleri_hesapla(veri, periyot="gunluk"):
        df = veri.copy()
        kapanis = df['Close']; hacim = df['Volume']; yuksek = df['High']; dusuk = df['Low']
        
        if periyot == "haftalik":
            df['SMA_50'] = ta.trend.SMAIndicator(close=kapanis, window=50).sma_indicator()
        elif periyot == "gunluk":
            df['RSI'] = ta.momentum.RSIIndicator(close=kapanis, window=14).rsi()
            macd = ta.trend.MACD(close=kapanis)
            df['MACD_Line'] = macd.macd(); df['MACD_Signal'] = macd.macd_signal()
            df['SMA_200'] = ta.trend.SMAIndicator(close=kapanis, window=200).sma_indicator()
            df['SMA_50'] = ta.trend.SMAIndicator(close=kapanis, window=50).sma_indicator()
            atr_ind = ta.volatility.AverageTrueRange(high=yuksek, low=dusuk, close=kapanis, window=14)
            df['ATR'] = atr_ind.average_true_range()
            df['Hacim_Ort_20'] = hacim.rolling(window=20).mean()
            # Smart Money (VWAP)
            tipik_fiyat = (yuksek + dusuk + kapanis) / 3
            df['VWAP_20'] = (tipik_fiyat * hacim).rolling(window=20).sum() / hacim.rolling(window=20).sum()
            df['Highest_10'] = yuksek.rolling(window=10).max()
        
        df.dropna(inplace=True)
        return df

# --- 5. STRATEJİ VE RİSK YÖNETİMİ ---
class QuantStrategy:
    def __init__(self, config, piyasa_rejimi):
        self.config = config; self.piyasa_rejimi = piyasa_rejimi

    def pozisyon_buyuklugu_hesapla(self, fiyat, stop_loss):
        aktif_risk_orani = self.config.risk_orani / 2 if "AYI" in self.piyasa_rejimi else self.config.risk_orani
        hisse_basina_risk = fiyat - stop_loss
        return int((self.config.sermaye * aktif_risk_orani) / hisse_basina_risk) if hisse_basina_risk > 0 else 0

    def analiz_et(self, hisse_kodu):
        gunluk, haftalik, fk_orani = DataFetcher.veri_indir(hisse_kodu)
        if gunluk is None or haftalik is None: return None, None
        kapanis_fiyatlari = gunluk['Close'].copy()
        gunluk = TechnicalAnalyzer.gostergeleri_hesapla(gunluk, periyot="gunluk")
        haftalik = TechnicalAnalyzer.gostergeleri_hesapla(haftalik, periyot="haftalik")
        
        son_gunluk = gunluk.iloc[-1]; son_haftalik = haftalik.iloc[-1]
        fiyat = float(son_gunluk['Close']); atr = float(son_gunluk['ATR'])
        izleyen_stop = min(float(son_gunluk['Highest_10']) - (atr * self.config.atr_stop), fiyat - (atr * self.config.atr_stop))
        
        skor = 0; nedenler = []
        if "AYI" in self.piyasa_rejimi: skor -= 20; nedenler.append("BIST Ayı Piyasasında")
        if son_haftalik['Close'] > son_haftalik['SMA_50']: skor += 25; nedenler.append("Haftalık Trend Güçlü")
        if fiyat > son_gunluk['VWAP_20']: skor += 20; nedenler.append("Kurumsal Para Desteği")
        if fiyat > son_gunluk['SMA_200']: skor += 10; nedenler.append("200G Ort. Üzerinde")
        if son_gunluk['RSI'] < self.config.rsi_al: skor += 15; nedenler.append("RSI Ucuz")
        
        skor = max(0, min(skor, 100))
        karar = "🔥 KESİN AL" if skor >= 80 else "🟢 POTANSİYEL AL" if skor >= 60 else "🔴 SAT / RİSKLİ" if son_gunluk['RSI'] > self.config.rsi_sat else "⚪ İZLEMEDE"
        lot = self.pozisyon_buyuklugu_hesapla(fiyat, izleyen_stop) if "AL" in karar else 0
            
        return {"Hisse": hisse_kodu.replace(".IS", ""), "Fiyat (₺)": round(fiyat, 2), "Skor": f"%{skor}", "Karar": karar, "Önerilen Lot": lot, "Stop (₺)": round(izleyen_stop, 2), "Nedenler": " | ".join(nedenler)}, kapanis_fiyatlari

# --- 6. ARAYÜZ ---
def ui_olustur():
    st.title("🛡️ Quant Bot v4.0 (Güvenli Sistem)")
    girilen_sifre = st.sidebar.text_input("Sisteme Giriş Şifresi:", type="password")
    if girilen_sifre != beklenen_sifre:
        st.sidebar.warning("Doğru şifreyi giriniz.")
        st.stop()
        
    # [Buraya yukarıdaki UI mantığını ve diğer bileşenleri ekleyebilirsin]
    st.success("Giriş Başarılı. Analize hazırsınız.")
    # ... (Arayüzün geri kalanı önceki koddaki gibi)

if __name__ == "__main__":
    ui_olustur()
