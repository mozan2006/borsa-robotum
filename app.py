import streamlit as st
import yfinance as yf
import pandas as pd
import ta
import plotly.graph_objects as go
import logging
import warnings
import concurrent.futures
from typing import Tuple, Optional, List, Dict, Any

# Uyarıları gizle
warnings.filterwarnings('ignore')
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- SAYFA AYARLARI ---
st.set_page_config(page_title="Ultimate Quant Bot v3.2", page_icon="📈", layout="wide")

# --- 1. YAPILANDIRMA SINIFI ---
class BotConfig:
    def __init__(self, rsi_al: int, rsi_sat: int, atr_stop: float, atr_kar: float, sermaye: float, risk_orani: float):
        self.rsi_al = rsi_al
        self.rsi_sat = rsi_sat
        self.atr_stop = atr_stop
        self.atr_kar = atr_kar
        self.sermaye = sermaye
        self.risk_orani = risk_orani

# --- ÖNBELLEKLENMİŞ VERİ ÇEKME FONKSİYONU (YENİ) ---
# Streamlit'in her tıklamada verileri baştan indirmesini önlemek için eklendi. (TTL: 1 Saat)
@st.cache_data(ttl=3600, show_spinner=False)
def cache_veri_indir(hisse_kodu: str) -> Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame], Optional[float]]:
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
        logging.error(f"Veri Çekme Hatası ({hisse_kodu}): {e}")
        return None, None, None

# --- 2. VERİ YÖNETİMİ SINIFI ---
class DataFetcher:
    @staticmethod
    def veri_indir(hisse_kodu: str) -> Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame], Optional[float]]:
        # Doğrudan cache'li fonksiyonu çağırıyoruz
        return cache_veri_indir(hisse_kodu)

# --- 3. TEKNİK ANALİZ SINIFI ---
class TeknikAnalizci:
    @staticmethod
    def gostergeleri_hesapla(veri: pd.DataFrame, periyot: str = "gunluk") -> pd.DataFrame:
        df = veri.copy()
        kapanis = df['Close']
        yuksek = df['High']
        dusuk = df['Low']
        hacim = df['Volume']

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
        
        return df.dropna()

# --- GRAFİK ÇİZİCİ SINIFI (YENİ) ---
# Plotly ile etkileşimli mum grafikleri oluşturmak için eklendi.
class GrafikCizici:
    @staticmethod
    def ciz_plotly(df: pd.DataFrame, hisse_ismi: str) -> go.Figure:
        son_veri = df.tail(100) # Sadece son 100 mumu göstererek grafiği okunabilir kılarız
        
        fig = go.Figure(data=[go.Candlestick(
            x=son_veri.index,
            open=son_veri['Open'], high=son_veri['High'],
            low=son_veri['Low'], close=son_veri['Close'],
            name='Fiyat'
        )])
        
        if 'SMA_50' in son_veri.columns:
            fig.add_trace(go.Scatter(x=son_veri.index, y=son_veri['SMA_50'], line=dict(color='blue', width=1.5), name='SMA 50'))
        if 'SMA_200' in son_veri.columns:
            fig.add_trace(go.Scatter(x=son_veri.index, y=son_veri['SMA_200'], line=dict(color='red', width=1.5), name='SMA 200'))
            
        fig.update_layout(
            title=f"{hisse_ismi} Detaylı Teknik Görünüm (Son 100 Gün)",
            xaxis_rangeslider_visible=False,
            template='plotly_dark',
            height=500,
            margin=dict(l=0, r=0, t=40, b=0)
        )
        return fig

# --- 4. STRATEJİ SINIFI ---
class QuantStrategy:
    def __init__(self, config: BotConfig):
        self.config = config

    def pozisyon_buyuklugu_hesapla(self, fiyat: float, stop_loss: float) -> int:
        risk_miktari = self.config.sermaye * self.config.risk_orani
        his_basina_risk = fiyat - stop_loss
        if his_basina_risk <= 0: return 0
        return int(risk_miktari / his_basina_risk)

    def analiz_et(self, his_kodu: str) -> Optional[Dict[str, Any]]:
        # Ana analiz mantığınız birebir korundu
        gunluk, haftalik, fk_orani = DataFetcher.veri_indir(his_kodu)
        if gunluk is None or haftalik is None: return None
        
        gunluk = TeknikAnalizci.gostergeleri_hesapla(gunluk, periyot="gunluk")
        haftalik = TeknikAnalizci.gostergeleri_hesapla(haftalik, periyot="haftalik")
        
        if gunluk.empty or haftalik.empty: return None

        son_gunluk = gunluk.iloc[-1]
        son_haftalik = haftalik.iloc[-1]
        fiyat = float(son_gunluk['Close'])
        atr = float(son_gunluk['ATR'])
        
        skor = 0
        nedenler = []
        
        if son_haftalik['Close'] > son_haftalik['SMA_50']:
            skor += 25; nedenler.append("Haftalık Trend Yükselişte")
        
        if fiyat > son_gunluk['SMA_200']: skor += 15; nedenler.append("200G Ort. Üstünde")
        if son_gunluk['RSI'] < self.config.rsi_al: skor += 20; nedenler.append("RSI Alım Bölgesi")
        if son_gunluk['MACD_Line'] > son_gunluk['MACD_Signal']: skor += 15; nedenler.append("MACD Alımda")
        if son_gunluk['Volume'] > son_gunluk['Hacim_Ort_20']: skor += 15; nedenler.append("Hacim Artışı")
        
        karar = "⚪ İZLEMEDE"
        if skor >= 80: karar = "🔥 KESİN AL"
        elif skor >= 60: karar = "🟢 POTANSİYEL AL"
        elif son_gunluk['RSI'] > self.config.rsi_sat: karar = "🔴 SAT / RİSKLİ"

        stop_loss = fiyat - (atr * self.config.atr_stop)
        lot_sayisi = self.pozisyon_buyuklugu_hesapla(fiyat, stop_loss) if "AL" in karar else 0
        
        return {
            "Hisse": his_kodu.replace(".IS", ""),
            "Fiyat (₺)": round(fiyat, 2),
            "Skor": f"%{skor}",
            "Karar": karar,
            "Önerilen Lot": lot_sayisi,
            "Nedenler": " | ".join(nedenler)
        }

    # --- TOPLU ANALİZ FONKSİYONU (YENİ) ---
    # Çoklu işlem (Multithreading) ile hisseleri eşzamanlı olarak saniyeler içinde analiz eder.
    def toplu_analiz(self, hisse_listesi: List[str]) -> List[Dict[str, Any]]:
        sonuclar = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            gelecek_sonuclar = {executor.submit(self.analiz_et, hisse): hisse for hisse in hisse_listesi}
            for future in concurrent.futures.as_completed(gelecek_sonuclar):
                sonuc = future.result()
                if sonuc:
                    sonuclar.append(sonuc)
        return sonuclar

# --- 5. ARAYÜZ (UI) ---
def ui_olustur():
    st.title("🤖 Profesyonel Quant Bot v3.2")
    
    st.sidebar.markdown("### ⚙️ Ayarlar")
    toplam_sermaye = st.sidebar.number_input("Toplam Sermaye (₺)", value=100000, step=10000)
    risk_yuzdesi = st.sidebar.slider("Risk (%)", 0.5, 5.0, 1.0) / 100
    
    hisler_metin = st.sidebar.text_area("Hisse Kodları (Alt Alta):", "THYAO\nASELS\nTUPRS\nFROTO\nSISE\nKCHOL")
    
    if st.sidebar.button("🚀 Analizi Başlat"):
        hisse_listesi = [h.strip().upper() + ".IS" for h in hisler_metin.split("\n") if h.strip()]
        config = BotConfig(40, 75, 1.5, 3.0, toplam_sermaye, risk_yuzdesi)
        strateji = QuantStrategy(config)
        
        # Analizi çalıştır (YENİ: Multithreading ve Spinner kullanılarak)
        with st.spinner(f"Veriler Çekiliyor ve {len(hisse_listesi)} Hisse Eşzamanlı Analiz Ediliyor..."):
            sonuclar = strateji.toplu_analiz(hisse_listesi)
        
        if sonuclar:
            st.success("Analiz Tamamlandı!")
            # Skora göre büyükten küçüğe sıralama
            df = pd.DataFrame(sonuclar).sort_values(by="Skor", ascending=False).reset_index(drop=True)
            st.dataframe(df, use_container_width=True)
            
            st.markdown("---")
            st.markdown("### 📊 Teknik Grafik İnceleme")
            
            # --- PLOTLY GRAFİK ARAYÜZÜ (YENİ) ---
            secilen_hisse = st.selectbox("Grafiğini incelemek istediğiniz hisseyi seçin:", df["Hisse"])
            if secilen_hisse:
                tam_kod = secilen_hisse + ".IS"
                gunluk_veri, _, _ = DataFetcher.veri_indir(tam_kod)
                if gunluk_veri is not None:
                    gunluk_ind = TeknikAnalizci.gostergeleri_hesapla(gunluk_veri, periyot="gunluk")
                    fig = GrafikCizici.ciz_plotly(gunluk_ind, secilen_hisse)
                    st.plotly_chart(fig, use_container_width=True)
        else:
            st.warning("Analiz edilebilir veri bulunamadı. Lütfen hisse kodlarını kontrol edin.")

if __name__ == "__main__":
    ui_olustur()
