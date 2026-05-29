import streamlit as st
import yfinance as yf
import pandas as pd
import ta
import warnings
import logging
import plotly.graph_objects as go
import numpy as np

warnings.filterwarnings('ignore')
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- SAYFA AYARLARI ---
st.set_page_config(page_title="Ultimate Quant Bot v5.0", page_icon="📈", layout="wide")

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
            
            # YENİ: Genişletilmiş Temel Analiz Verileri
            info = ticker.info
            temel_veriler = {
                'fk': info.get('trailingPE', None),
                'pd_dd': info.get('priceToBook', None),
                'roe': info.get('returnOnEquity', None)
            }
            
            return gunluk_veri, haftalik_veri, temel_veriler
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

# --- 3. TEKNİK ANALİZ ---
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
            # Temel Göstergeler
            df['RSI'] = ta.momentum.RSIIndicator(close=kapanis, window=14).rsi()
            macd = ta.trend.MACD(close=kapanis)
            df['MACD_Line'] = macd.macd()
            df['MACD_Signal'] = macd.macd_signal()
            df['SMA_200'] = ta.trend.SMAIndicator(close=kapanis, window=200).sma_indicator()
            df['SMA_50'] = ta.trend.SMAIndicator(close=kapanis, window=50).sma_indicator()
            df['SMA_20'] = ta.trend.SMAIndicator(close=kapanis, window=20).sma_indicator()
            
            # Volatilite ve Hacim
            df['ATR'] = ta.volatility.AverageTrueRange(high=yuksek, low=dusuk, close=kapanis, window=14).average_true_range()
            df['Hacim_Ort_20'] = hacim.rolling(window=20).mean()
            
            # Smart Money Takibi: VWAP ve CMF (Chaikin Money Flow)
            tipik_fiyat = (yuksek + dusuk + kapanis) / 3
            df['VWAP_20'] = (tipik_fiyat * hacim).rolling(window=20).sum() / hacim.rolling(window=20).sum()
            df['CMF'] = ta.volume.ChaikinMoneyFlowIndicator(high=yuksek, low=dusuk, close=kapanis, volume=hacim, window=20).chaikin_money_flow()
            
            # Trend Gücü: ADX
            df['ADX'] = ta.trend.ADXIndicator(high=yuksek, low=dusuk, close=kapanis, window=14).adx()
            
            # İstatistiksel Aşırılık: Z-Skoru (Mean Reversion)
            df['Standart_Sapma'] = kapanis.rolling(window=20).std()
            df['Z_Score'] = (kapanis - df['SMA_20']) / df['Standart_Sapma']
            
            # İzleyen Stop
            df['Highest_10'] = yuksek.rolling(window=10).max()
        
        df.dropna(inplace=True)
        return df

# --- 4. BACKTEST MODÜLÜ ---
class Backtester:
    @staticmethod
    def hizli_test(df):
        """Son 2 yıllık veride sistemin al-sat mantığını simüle eder."""
        if df is None or len(df) < 50: return 0, 0, 0
        
        baslangic_sermaye = 100000
        sermaye = baslangic_sermaye
        pozisyon_acik = False
        alinan_fiyat = 0
        basarili_islem = 0
        toplam_islem = 0
        
        for i in range(50, len(df)):
            row = df.iloc[i]
            
            # Strateji Alım Şartları
            al_sinyali = (row['Close'] > row['SMA_50']) and (row['MACD_Line'] > row['MACD_Signal']) and (row['ADX'] > 20) and (row['Z_Score'] < 2)
            # Strateji Satım Şartları
            sat_sinyali = (row['RSI'] > 70) or (row['MACD_Line'] < row['MACD_Signal']) or (row['Z_Score'] > 2.5)
            
            if not pozisyon_acik and al_sinyali:
                alinan_fiyat = row['Close']
                alinan_lot = sermaye / alinan_fiyat
                pozisyon_acik = True
                
            elif pozisyon_acik and sat_sinyali:
                satilan_fiyat = row['Close']
                sermaye = alinan_lot * satilan_fiyat
                toplam_islem += 1
                if (satilan_fiyat > alinan_fiyat): basarili_islem += 1
                pozisyon_acik = False
                
        # Açık pozisyon varsa son gün fiyatından kapat
        if pozisyon_acik:
            satilan_fiyat = df.iloc[-1]['Close']
            sermaye = alinan_lot * satilan_fiyat
            toplam_islem += 1
            if (satilan_fiyat > alinan_fiyat): basarili_islem += 1
                
        getiri_yuzdesi = ((sermaye - baslangic_sermaye) / baslangic_sermaye) * 100
        win_rate = (basarili_islem / toplam_islem * 100) if toplam_islem > 0 else 0
        
        return round(win_rate, 1), round(getiri_yuzdesi, 1), toplam_islem

# --- 5. STRATEJİ VE RİSK YÖNETİMİ ---
class QuantStrategy:
    def __init__(self, config, piyasa_rejimi):
        self.config = config
        self.piyasa_rejimi = piyasa_rejimi

    def pozisyon_buyuklugu_hesapla(self, fiyat, stop_loss):
        aktif_risk_orani = self.config.risk_orani / 2 if "AYI" in self.piyasa_rejimi else self.config.risk_orani
        risk_miktari = self.config.sermaye * aktif_risk_orani
        hisse_basina_risk = fiyat - stop_loss
        if hisse_basina_risk <= 0: return 0
        return int(risk_miktari / hisse_basina_risk)

    def analiz_et(self, hisse_kodu):
        gunluk, haftalik, temel_veriler = DataFetcher.veri_indir(hisse_kodu)
        if gunluk is None or haftalik is None: return None, None
            
        kapanis_fiyatlari = gunluk['Close'].copy()
        gunluk = TechnicalAnalyzer.gostergeleri_hesapla(gunluk, periyot="gunluk")
        haftalik = TechnicalAnalyzer.gostergeleri_hesapla(haftalik, periyot="haftalik")
        
        if gunluk.empty or haftalik.empty: return None, None
            
        # Backtest'i çalıştır
        win_rate, tarihsel_getiri, islem_sayisi = Backtester.hizli_test(gunluk)
        
        son_gunluk = gunluk.iloc[-1]
        son_haftalik = haftalik.iloc[-1]
        
        fiyat = float(son_gunluk['Close'])
        rsi = float(son_gunluk['RSI'])
        atr = float(son_gunluk['ATR'])
        
        izleyen_stop = float(son_gunluk['Highest_10']) - (atr * self.config.atr_stop)
        izleyen_stop = izleyen_stop if izleyen_stop < fiyat else fiyat - (atr * self.config.atr_stop)
        kar_al = fiyat + (atr * self.config.atr_kar)
        
        skor = 0
        nedenler = []
        
        # Piyasa Rejimi (Makro Filtre)
        if "AYI" in self.piyasa_rejimi:
            skor -= 20; nedenler.append("Endeks Ayı Piyasasında")
        
        # Temel Analiz Değerlemeleri (F/K, PD/DD, ROE)
        fk = temel_veriler.get('fk')
        pd_dd = temel_veriler.get('pd_dd')
        roe = temel_veriler.get('roe')
        
        if fk is not None:
            if 0 < fk < 15: skor += 10; nedenler.append("F/K Uygun")
            elif fk > 50 or fk < 0: skor -= 15; nedenler.append("F/K Pahalı/Negatif")
        if pd_dd is not None and pd_dd < 2: skor += 10; nedenler.append("Ucuz (PD/DD<2)")
        if roe is not None and roe > 0.20: skor += 10; nedenler.append("Kârlı Şirket (ROE>%20)")

        # Trend ve Momentum
        if son_haftalik['Close'] > son_haftalik['SMA_50']: skor += 15
        if fiyat > son_gunluk['SMA_200']: skor += 10
        if son_gunluk['MACD_Line'] > son_gunluk['MACD_Signal']: skor += 10; nedenler.append("MACD Alımda")
        
        # Trend Gücü (ADX)
        if son_gunluk['ADX'] < 20: skor -= 15; nedenler.append("Trend Zayıf (Yatay)")
        elif son_gunluk['ADX'] > 25: skor += 10; nedenler.append("Trend Güçlü")
        
        # Smart Money (VWAP & CMF)
        if fiyat > son_gunluk['VWAP_20']: skor += 10; nedenler.append("VWAP Desteği")
        if son_gunluk['CMF'] > 0.05: skor += 10; nedenler.append("Para Girişi (CMF)")
        elif son_gunluk['CMF'] < -0.05: skor -= 15; nedenler.append("Para Çıkışı Var")
        
        # İstatistiksel Aşırılık (Z-Score)
        if son_gunluk['Z_Score'] > 2.5: skor -= 30; nedenler.append("Aşırı Şişmiş (Balon)")
        elif son_gunluk['Z_Score'] < -2.0: skor += 15; nedenler.append("Aşırı Ucuzlamış")
        
        skor = max(0, min(skor, 100))
        
        if skor >= 80: karar = "🔥 KESİN AL"
        elif skor >= 60: karar = "🟢 POTANSİYEL AL"
        elif son_gunluk['Z_Score'] > 2 or rsi > self.config.rsi_sat: karar = "🔴 SAT / RİSKLİ"
        else: karar = "⚪ İZLEMEDE"
            
        lot_sayisi = self.pozisyon_buyuklugu_hesapla(fiyat, izleyen_stop) if "AL" in karar else 0
            
        sonuc_dict = {
            "Hisse": hisse_kodu.replace(".IS", ""), 
            "Karar": karar, 
            "Skor": f"%{skor}",
            "Win Rate (2Y)": f"%{win_rate}" if islem_sayisi > 0 else "N/A",
            "Tarihsel Getiri": f"%{tarihsel_getiri}" if islem_sayisi > 0 else "N/A",
            "Fiyat (₺)": round(fiyat, 2), 
            "Önerilen Lot": lot_sayisi,
            "İzleyen Stop (₺)": round(izleyen_stop, 2),
            "Nedenler": " | ".join(nedenler[:4]) # Arayüz şişmesin diye en önemli 4 nedeni göster
        }
        
        return sonuc_dict, kapanis_fiyatlari

# --- 6. ARAYÜZ VE ORKESTRASYON ---
def ui_olustur():
    st.title("🛡️ Hedge Fon Modu: Quant Bot v5.0")
    st.markdown("Piyasa filtresi, Smart Money (CMF/VWAP), Z-Skoru, ADX, Temel Analiz ve Tarihsel Backtest entegreli sistem.")

    # ŞİFRE KONTROLÜ (Geliştirme için geçici kapalı/açık)
    try:
        beklenen_sifre = st.secrets.get("sistem_sifresi", "admin123")
    except:
        beklenen_sifre = "admin123"

    girilen_sifre = st.sidebar.text_input("Sisteme Giriş Şifresi:", type="password")
    if girilen_sifre != beklenen_sifre:
        st.sidebar.warning("Sistemi kullanmak için doğru şifreyi girmelisiniz. (Varsayılan: admin123)")
        st.stop()
    st.sidebar.success("Giriş Başarılı! ✅")

    st.sidebar.markdown("### ⚙️ Portföy Ayarları")
    toplam_sermaye = st.sidebar.number_input("Toplam Sermaye (₺)", min_value=10000, value=100000, step=10000)
    risk_yuzdesi = st.sidebar.slider("İşlem Başına Risk (%)", 0.5, 5.0, 1.0, step=0.1) / 100

    st.sidebar.markdown("### 📊 Strateji Çarpanları")
    rsi_al = st.sidebar.slider("RSI Alım Sınırı", 20, 50, 40)
    rsi_sat = st.sidebar.slider("RSI Satım Sınırı", 60, 90, 75)
    atr_stop = st.sidebar.slider("İzleyen Stop ATR", 1.0, 5.0, 1.5, step=0.1)
    atr_kar = st.sidebar.slider("Kar-Al ATR", 1.0, 10.0, 3.0, step=0.1)

    endeks_durumu, xu_fiyat, xu_sma = DataFetcher.endeks_durumu_getir()
    
    col1, col2, col3 = st.columns(3)
    col1.metric("BIST 100 Rejimi", endeks_durumu)
    col2.metric("BIST 100 Fiyat", f"{round(xu_fiyat, 2)}")
    col3.metric("BIST 100 SMA(50)", f"{round(xu_sma, 2)}")
    
    if "AYI" in endeks_durumu:
        st.warning("⚠️ BIST 100 şu an düşüş trendinde. Sistem savunma moduna geçerek alım şartlarını zorlaştırdı ve risk limitlerini yarıya indirdi.")

    config = BotConfig(rsi_al, rsi_sat, atr_stop, atr_kar, toplam_sermaye, risk_yuzdesi)
    strateji = QuantStrategy(config, endeks_durumu)

    varsayilan_hisseler = "THYAO\nASELS\nTUPRS\nISCTR\nKCHOL\nSISE\nBIMAS\nAKSA\nENKAI\nFROTO"
    st.sidebar.markdown("---")
    hisseler_metin = st.sidebar.text_area("Taranacak Hisseler:", varsayilan_hisseler, height=150)

    if st.sidebar.button("🚀 Akıllı Tarama ve Backtest Başlat"):
        hisse_listesi = [h.strip().upper() + ".IS" for h in hisseler_metin.split("\n") if h.strip()]
        
        st.info("Algoritmalar çalıştırılıyor, geçmiş veriler test ediliyor. Lütfen bekleyin...")
        ilerleme_cubugu = st.progress(0)
        durum_metni = st.empty()
        
        sonuclar = []
        kapanis_sozlugu = {}
        toplam_hisse = len(hisse_listesi)
        
        for i, hisse in enumerate(hisse_listesi):
            durum_metni.text(f"Analiz ve Backtest: {hisse} ({i+1}/{toplam_hisse})")
            analiz_sonucu, kapanis_verisi = strateji.analiz_et(hisse)
            if analiz_sonucu:
                sonuclar.append(analiz_sonucu)
                kapanis_sozlugu[hisse.replace(".IS", "")] = kapanis_verisi
                
            ilerleme_cubugu.progress((i + 1) / toplam_hisse)
        
        durum_metni.empty()
        
        if sonuclar:
            df = pd.DataFrame(sonuclar)
            df['Saf Skor'] = df['Skor'].apply(lambda x: int(x.replace('%', '')))
            df = df.sort_values(by='Saf Skor', ascending=False).drop(columns=['Saf Skor'])
            
            st.success("✅ Tüm tarama, backtest ve risk katsayısı hesaplamaları tamamlandı!")
            
            def tabloyu_renklendir(val):
                if "🔥 KESİN AL" in str(val): return 'background-color: #1e4620; color: white; font-weight: bold;'
                elif "🟢 POTANSİYEL AL" in str(val): return 'background-color: #2e7d32; color: white;'
                elif "🔴 SAT" in str(val): return 'background-color: #b71c1c; color: white;'
                return ''
                
            st.dataframe(df.style.map(tabloyu_renklendir, subset=['Karar']), use_container_width=True)
            
            st.markdown("---")
            st.markdown("### 🕸️ Portföy Korelasyon Risk Analizi")
            if kapanis_sozlugu:
                fiyat_df = pd.DataFrame(kapanis_sozlugu).dropna()
                korelasyon_matrisi = fiyat_df.pct_change().corr()
                
                yuksek_korelasyonlu_ciftler = []
                for i in range(len(korelasyon_matrisi.columns)):
                    for j in range(i+1, len(korelasyon_matrisi.columns)):
                        hisse1 = korelasyon_matrisi.columns[i]
                        hisse2 = korelasyon_matrisi.columns[j]
                        korelasyon_degeri = korelasyon_matrisi.iloc[i, j]
                        if korelasyon_degeri > 0.85:
                            yuksek_korelasyonlu_ciftler.append(f"**{hisse1}** ve **{hisse2}** (Benzerlik: %{round(korelasyon_degeri*100, 1)})")
                
                if yuksek_korelasyonlu_ciftler:
                    st.error("🚨 **Yüksek Korelasyon Uyarısı:** Aşağıdaki hisseler çok benzer hareket ediyor. Çeşitliliği korumak için gruptan sadece birini seçin.")
                    for cift in yuksek_korelasyonlu_ciftler:
                        st.markdown(f"- {cift}")
                else:
                    st.success("✅ İncelenen hisseler arasında tehlikeli bir korelasyon bulunamadı.")
            
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
            st.error("Veri çekilemedi. Bağlantı sorunu olabilir.")

if __name__ == "__main__":
    ui_olustur()
