import streamlit as st
import yfinance as yf
import pandas as pd
import ta
import warnings
import plotly.graph_objects as go

warnings.filterwarnings('ignore')

# --- SAYFA AYARLARI ---
st.set_page_config(page_title="Ultimate Quant Bot v4.0", page_icon="🛡️", layout="wide")

# --- 1. GÜVENLİK ---
try:
    beklenen_sifre = st.secrets["sistem_sifresi"]
except KeyError:
    st.error("🚨 Sistem Hatası: Streamlit Secrets ayarlanmamış!")
    st.stop()

# --- 2. VERİ VE ANALİZ SINIFLARI ---
class DataFetcher:
    @staticmethod
    def veri_indir(hisse_kodu):
        try:
            t = yf.Ticker(hisse_kodu)
            df = t.history(period="2y", interval="1d")
            return df if not df.empty else None
        except: return None

class QuantStrategy:
    @staticmethod
    def analiz(hisse_kodu):
        df = DataFetcher.veri_indir(hisse_kodu)
        if df is None or len(df) < 200: return None
        
        # Göstergeler
        df['RSI'] = ta.momentum.RSIIndicator(close=df['Close'], window=14).rsi()
        df['SMA_200'] = ta.trend.SMAIndicator(close=df['Close'], window=200).sma_indicator()
        df['ATR'] = ta.volatility.AverageTrueRange(high=df['High'], low=df['Low'], close=df['Close'], window=14).average_true_range()
        
        s = df.iloc[-1]
        fiyat = s['Close']
        stop = fiyat - (s['ATR'] * 1.5)
        
        skor = 0
        if fiyat > s['SMA_200']: skor += 40
        if s['RSI'] < 40: skor += 30
        
        karar = "🔥 AL" if skor >= 60 else "⚪ İZLE"
        return {"Hisse": hisse_kodu.replace(".IS", ""), "Fiyat": round(fiyat, 2), "Karar": karar, "Stop": round(stop, 2)}, df['Close']

# --- 3. ARAYÜZ ---
def ui_olustur():
    st.title("🛡️ Hedge Fon Modu: Quant Bot v4.0")
    
    # Giriş
    sifre = st.sidebar.text_input("Şifre:", type="password")
    if sifre != beklenen_sifre:
        st.warning("Şifre hatalı.")
        st.stop()

    hisseler = st.sidebar.text_area("Hisseler (Alt alta):", "THYAO\nASELS\nTUPRS\nISCTR", height=150)
    
    if st.sidebar.button("🚀 Analizi Başlat"):
        hisse_listesi = [h.strip().upper() + ".IS" for h in hisseler.split("\n") if h.strip()]
        sonuclar = []
        kapanislar = {}
        
        for h in hisse_listesi:
            res, close_data = QuantStrategy.analiz(h)
            if res:
                sonuclar.append(res)
                kapanislar[res['Hisse']] = close_data
        
        if sonuclar:
            df = pd.DataFrame(sonuclar)
            st.dataframe(df, use_container_width=True)
            
            # Korelasyon Analizi
            st.markdown("### 🕸️ Portföy Korelasyon Risk Analizi")
            fiyat_df = pd.DataFrame(kapanislar).dropna()
            corr = fiyat_df.pct_change().corr()
            st.write("Hisseler arası benzerlik matrisi:")
            st.dataframe(corr.style.background_gradient(cmap='RdYlGn'), use_container_width=True)
            
        else:
            st.error("Veri çekilemedi. Hata oluştu.")

if __name__ == "__main__":
    ui_olustur()
        
