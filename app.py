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
        df['MACD_Signal'] = macd.macd_signal()
        df['SMA_200'] = ta.trend.SMAIndicator(close=kapanis, window=200).sma_indicator()
        df['SMA_50'] = ta.trend.SMAIndicator(close=kapanis, window=50).sma_indicator()
        df['SMA_20'] = ta.trend.SMAIndicator(close=kapanis, window=20).sma_indicator()
        
        atr_ind = ta.volatility.AverageTrueRange(high=yuksek, low=dusuk, close=kapanis, window=14)
        df['ATR'] = atr_ind.average_true_range()
        df['Hacim_Ort_20'] = hacim.rolling(window=20).mean()
        
        bollinger = ta.volatility.BollingerBands(close=kapanis, window=20, window_dev=2)
        df['BB_Alt'] = bollinger.bollinger_lband()
        
        df.dropna(inplace=True)
        return df

# --- 4. STRATEJİ VE RİSK YÖNETİMİ SINIFI ---
class QuantStrategy:
    def __init__(self, config):
        self.config = config

    def pozisyon_buyuklugu_hesapla(self, fiyat, stop_loss):
        # Risk = Sermaye * Risk Oranı
        risk_miktari = self.config.sermaye * self.config.risk_orani
        hisse_basina_risk = fiyat - stop_loss
        
        if hisse_basina_risk <= 0: return 0
        alinacak_lot = int(risk_miktari / hisse_basina_risk)
        return alinacak_lot

    def analiz_et(self, hisse_kodu):
        gunluk, haftalik, fk_orani = DataFetcher.veri_indir(hisse_kodu)
        if gunluk is None: return None
            
        gunluk = TechnicalAnalyzer.gostergeleri_hesapla(gunluk)
        haftalik = TechnicalAnalyzer.gostergeleri_hesapla(haftalik)
        
        if gunluk.empty or haftalik.empty: return None 
            
        son_gunluk = gunluk.iloc[-1]
        son_haftalik = haftalik.iloc[-1]
        
        fiyat = float(son_gunluk['Close'])
        rsi = float(son_gunluk['RSI'])
        atr = float(son_gunluk['ATR'])
        
        stop_loss = fiyat - (atr * self.config.atr_stop)
        kar_al = fiyat + (atr * self.config.atr_kar)
        
        skor = 0
        nedenler = []
        
        # Çoklu Zaman Dilimi Kontrolü (Haftalık Trend)
        if son_haftalik['Close'] > son_haftalik['SMA_50']:
            skor += 25
            nedenler.append("Haftalık Ana Trend Yükselişte")
        else:
            nedenler.append("Haftalık Trend Düşüşte (Zayıf)")

        # Günlük Kriterler
        if fiyat > son_gunluk['SMA_200']: skor += 15; nedenler.append("200G Ort. Üzerinde")
        if rsi < self.config.rsi_al: skor += 20; nedenler.append("RSI Aşırı Satım (Ucuz)")
        if son_gunluk['MACD_Line'] > son_gunluk['MACD_Signal']: skor += 15; nedenler.append("MACD Alımda")
        if son_gunluk['Volume'] > son_gunluk['Hacim_Ort_20']: skor += 15; nedenler.append("Hacim Artışı")
        if fiyat <= son_gunluk['BB_Alt'] * 1.02: skor += 10; nedenler.append("Bollinger Alt Bant")
        
        # Temel Analiz Filtresi
        if fk_orani:
            if fk_orani > 50: skor -= 15; nedenler.append("Pahalı (Yüksek F/K)")
            elif fk_orani < 0: skor -= 25; nedenler.append("Zarar Ediyor")
                
        skor = max(0, skor)
        
        if skor >= 80: karar = "🔥 KESİN AL"
        elif skor >= 60: karar = "🟢 POTANSİYEL AL"
        elif rsi > self.config.rsi_sat: karar = "🔴 SAT / RİSKLİ"
        else: karar = "⚪ İZLEMEDE"
            
        lot_sayisi = self.pozisyon_buyuklugu_hesapla(fiyat, stop_loss) if "AL" in karar else 0
        sermaye_kullanimi = round((lot_sayisi * fiyat), 2)
            
        return {
            "Hisse": hisse_kodu.replace(".IS", ""), 
            "Fiyat (₺)": round(fiyat, 2), 
            "Skor": f"%{skor}", 
            "Karar": karar, 
            "Önerilen Lot": lot_sayisi,
            "Sermaye Gerekli (₺)": sermaye_kullanimi,
            "Stop-Loss (₺)": round(stop_loss, 2), 
            "Hedef (₺)": round(kar_al, 2), 
            "Nedenler": " | ".join(nedenler)
        }

# --- 5. ARAYÜZ (UI) MANTIK ---
def ui_olustur():
    st.title("🤖 Profesyonel Quant Bot v3.0")
    st.markdown("Çoklu zaman dilimi, nesne yönelimli mimari ve dinamik risk yönetimi ile güçlendirilmiş versiyon.")

    try:
        beklenen_sifre = st.secrets["sistem_sifresi"]
    except KeyError:
        st.error("🚨 Sistem Hatası: Şifre ayarlanmamış! (Streamlit Secrets)")
        st.stop()

    girilen_sifre = st.sidebar.text_input("Sisteme Giriş Şifresi:", type="password")
    if girilen_sifre != beklenen_sifre:
        st.sidebar.warning("Sistemi kullanmak için doğru şifreyi girmelisiniz.")
        st.stop()
    st.sidebar.success("Giriş Başarılı! ✅")

    st.sidebar.markdown("### ⚙️ Portföy ve Risk Ayarları")
    toplam_sermaye = st.sidebar.number_input("Toplam Sermaye (₺)", min_value=10000, value=100000, step=10000)
    risk_yuzdesi = st.sidebar.slider("İşlem Başına Risk (%)", 0.5, 5.0, 1.0, step=0.1) / 100

    st.sidebar.markdown("### 📊 Teknik Strateji Ayarları")
    rsi_al = st.sidebar.slider("RSI Alım Sınırı", 20, 50, 40)
    rsi_sat = st.sidebar.slider("RSI Satım Sınırı", 60, 90, 75)
    atr_stop = st.sidebar.slider("Stop-Loss ATR Çarpanı", 1.0, 5.0, 1.5, step=0.1)
    atr_kar = st.sidebar.slider("Kar-Al ATR Çarpanı", 1.0, 10.0, 3.0, step=0.1)

    config = BotConfig(rsi_al, rsi_sat, atr_stop, atr_kar, toplam_sermaye, risk_yuzdesi)
    strateji = QuantStrategy(config)

    varsayilan_hisseler = "THYAO\nASELS\nTUPRS\nISCTR\nKCHOL\nSISE\nBIMAS\nAKSA\nENKAI"
    st.sidebar.markdown("---")
    hisseler_metin = st.sidebar.text_area("Hisse Kodları (Alt Alta):", varsayilan_hisseler, height=150)

    if st.sidebar.button("🚀 Analizi Başlat"):
        hisse_listesi = [h.strip().upper() + ".IS" for h in hisseler_metin.split("\n") if h.strip()]
        
        with st.spinner('Piyasa verileri asenkron olarak çekiliyor (Günlük & Haftalık)...'):
            sonuclar = []
            with ThreadPoolExecutor(max_workers=10) as executor:
                gelecek_sonuclar = {executor.submit(strateji.analiz_et, hisse): hisse for hisse in hisse_listesi}
                for future in as_completed(gelecek_sonuclar):
                    analiz = future.result()
                    if analiz: sonuclar.append(analiz)
            
            if sonuclar:
                df = pd.DataFrame(sonuclar)
                df['Saf Skor'] = df['Skor'].apply(lambda x: int(x.replace('%', '')))
                df = df.sort_values(by='Saf Skor', ascending=False).drop(columns=['Saf Skor'])
                
                st.success("✅ Analiz ve Risk Hesaplamaları Tamamlandı!")
                
                def tabloyu_renklendir(val):
                    if "🔥 KESİN AL" in str(val): return 'background-color: #1e4620; color: white; font-weight: bold;'
                    elif "🟢 POTANSİYEL AL" in str(val): return 'background-color: #2e7d32; color: white;'
                    elif "🔴 SAT" in str(val): return 'background-color: #b71c1c; color: white;'
                    return ''
                    
                st.dataframe(df.style.map(tabloyu_renklendir, subset=['Karar']), use_container_width=True)
                
                st.markdown("---")
                st.markdown("### 📈 Hızlı Grafik İzleme")
                secilen_hisse = st.selectbox("Detayını görmek istediğiniz hisseyi seçin:", df["Hisse"].tolist())
                if secilen_hisse:
                    veri, _, _ = DataFetcher.veri_indir(secilen_hisse + ".IS")
                    if veri is not None:
                        veri = veri.tail(120)
                        fig = go.Figure(data=[go.Candlestick(x=veri.index, open=veri['Open'], high=veri['High'], low=veri['Low'], close=veri['Close'], name="Fiyat")])
                        fig.update_layout(title=f"{secilen_hisse} - Son 120 Gün", template="plotly_dark", margin=dict(l=0, r=0, t=40, b=0))
                        st.plotly_chart(fig, use_container_width=True)
            else:
                st.error("Veri çekilemedi veya API limitine takılındı.")

if __name__ == "__main__":
    ui_olustur()
