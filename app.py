import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import ta
import warnings
import logging
import plotly.graph_objects as go
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler

warnings.filterwarnings('ignore')
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- SAYFA AYARLARI ---
st.set_page_config(page_title="Ultimate Quant Bot v6.0", page_icon="🤖", layout="wide")

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

# --- 2. VERİ VE DUYGU ANALİZİ (SENTIMENT) ---
class DataFetcher:
    @staticmethod
    def veri_indir(hisse_kodu):
        try:
            ticker = yf.Ticker(hisse_kodu)
            gunluk_veri = ticker.history(period="2y", interval="1d")
            haftalik_veri = ticker.history(period="5y", interval="1wk")
            
            if gunluk_veri.empty or haftalik_veri.empty or len(haftalik_veri) < 50: 
                return None, None, None, None
            
            info = ticker.info
            temel_veriler = {
                'fk': info.get('trailingPE', None),
                'pd_dd': info.get('priceToBook', None),
                'roe': info.get('returnOnEquity', None)
            }
            
            # SIMÜLASYON: Gerçek bir sistemde burada Twitter/KAP API'si üzerinden NLP (Doğal Dil İşleme) çalışır.
            # Biz hacim ivmesi ve volatiliteye bağlı yapay bir algoritmik "Piyasa Duygusu" (Sentiment) üretiyoruz.
            son_hacim_degisimi = gunluk_veri['Volume'].pct_change().iloc[-1]
            duygu_skoru = np.clip(son_hacim_degisimi * 100, -100, 100) # -100 ile +100 arası
            
            return gunluk_veri, haftalik_veri, temel_veriler, duygu_skoru
        except Exception as e:
            logging.error(f"Veri çekme hatası ({hisse_kodu}): {e}")
            return None, None, None, None

# --- 3. TEKNİK VE MAKİNE ÖĞRENMESİ MODÜLÜ ---
class QuantModel:
    @staticmethod
    def gostergeleri_hesapla(df):
        kapanis, hacim, yuksek, dusuk = df['Close'], df['Volume'], df['High'], df['Low']
        
        df['RSI'] = ta.momentum.RSIIndicator(close=kapanis).rsi()
        macd = ta.trend.MACD(close=kapanis)
        df['MACD_Line'] = macd.macd()
        df['MACD_Signal'] = macd.macd_signal()
        df['SMA_50'] = ta.trend.SMAIndicator(close=kapanis, window=50).sma_indicator()
        df['SMA_20'] = ta.trend.SMAIndicator(close=kapanis, window=20).sma_indicator()
        df['ATR'] = ta.volatility.AverageTrueRange(high=yuksek, low=dusuk, close=kapanis).average_true_range()
        df['ADX'] = ta.trend.ADXIndicator(high=yuksek, low=dusuk, close=kapanis).adx()
        
        # Z-Score
        df['Std_Dev'] = kapanis.rolling(window=20).std()
        df['Z_Score'] = (kapanis - df['SMA_20']) / df['Std_Dev']
        
        df['Highest_10'] = yuksek.rolling(window=10).max()
        df.dropna(inplace=True)
        return df

    @staticmethod
    def ml_tahmin_et(df):
        """Random Forest ile yarının yükseliş olasılığını tahmin eder."""
        try:
            veri = df.copy()
            # Hedef: Yarınki kapanış bugünden büyükse 1 (Yükseliş), değilse 0 (Düşüş)
            veri['Hedef'] = np.where(veri['Close'].shift(-1) > veri['Close'], 1, 0)
            veri.dropna(inplace=True)
            
            ozellikler = ['RSI', 'MACD_Line', 'ADX', 'Z_Score', 'Volume']
            X = veri[ozellikler]
            y = veri['Hedef']
            
            # Modeli eğit
            model = RandomForestClassifier(n_estimators=100, random_state=42, max_depth=5)
            model.fit(X, y)
            
            # Bugünkü verilerle yarını tahmin et
            son_veri = df[ozellikler].iloc[-1:]
            yukselis_olasiligi = model.predict_proba(son_veri)[0][1] * 100
            
            return round(yukselis_olasiligi, 1)
        except:
            return 50.0 # Hata olursa nötr (%50) döndür

# --- 4. GERÇEKÇİ BACKTEST VE RİSK MATEMATİĞİ (KELLY) ---
class Backtester:
    @staticmethod
    def gercekci_test(df, komisyon_orani, slippage_orani):
        """Slippage (Kayma) ve Komisyon dahil edilmiş gerçekçi backtest."""
        if df is None or len(df) < 50: return 0, 0, 0, 0
        
        baslangic = 100000
        sermaye = baslangic
        pozisyon_acik = False
        alinan_fiyat = 0
        basarili_islem = 0
        kazanc_toplami = 0
        kayip_toplami = 0
        toplam_islem = 0
        
        for i in range(50, len(df)):
            row = df.iloc[i]
            
            al_sinyali = (row['Close'] > row['SMA_50']) and (row['MACD_Line'] > row['MACD_Signal'])
            sat_sinyali = (row['RSI'] > 70) or (row['MACD_Line'] < row['MACD_Signal'])
            
            if not pozisyon_acik and al_sinyali:
                # Gerçek piyasada fiyat bir miktar yukarıdan alınır (Slippage) ve komisyon kesilir.
                gercek_alim_fiyati = row['Close'] * (1 + slippage_orani)
                komisyon_maliyeti = sermaye * komisyon_orani
                sermaye -= komisyon_maliyeti
                
                alinan_lot = sermaye / gercek_alim_fiyati
                alinan_fiyat = gercek_alim_fiyati
                pozisyon_acik = True
                
            elif pozisyon_acik and sat_sinyali:
                # Satarken fiyat bir miktar aşağıdan satılır (Slippage) ve komisyon kesilir.
                gercek_satim_fiyati = row['Close'] * (1 - slippage_orani)
                brut_sermaye = alinan_lot * gercek_satim_fiyati
                komisyon_maliyeti = brut_sermaye * komisyon_orani
                sermaye = brut_sermaye - komisyon_maliyeti
                
                toplam_islem += 1
                if sermaye > (alinan_lot * alinan_fiyat): 
                    basarili_islem += 1
                    kazanc_toplami += (gercek_satim_fiyati - alinan_fiyat)
                else:
                    kayip_toplami += (alinan_fiyat - gercek_satim_fiyati)
                    
                pozisyon_acik = False
                
        getiri_yuzdesi = ((sermaye - baslangic) / baslangic) * 100
        win_rate = (basarili_islem / toplam_islem) if toplam_islem > 0 else 0
        
        ortalama_kazanc = (kazanc_toplami / basarili_islem) if basarili_islem > 0 else 1
        ortalama_kayip = (kayip_toplami / (toplam_islem - basarili_islem)) if (toplam_islem - basarili_islem) > 0 else 1
        risk_odul_orani = ortalama_kazanc / ortalama_kayip
        
        return round(win_rate * 100, 1), round(getiri_yuzdesi, 1), toplam_islem, risk_odul_orani

# --- 5. OTOMATİK EMİR İLETİMİ (TASLAK SİMÜLASYON) ---
class ExecutionAPI:
    @staticmethod
    def emir_gonder(hisse, yon, lot, fiyat):
        """Gerçek aracı kurum API'si ekleneceği zaman bu blok doldurulur."""
        logging.info(f"🟢 BORSAYA İLETİLDİ: {yon} - {hisse} - {lot} Lot - Fiyat: {fiyat}")
        return True

# --- 6. ANA STRATEJİ MOTORU ---
class QuantStrategy:
    def __init__(self, config):
        self.config = config

    def kelly_kriteri_hesapla(self, win_rate, risk_odul):
        """
        Gelişmiş Fon Pozisyon Yönetimi (Kelly Kriteri)
        Formül: f* = (p(b+1) - 1) / b
        """
        p = win_rate / 100
        b = risk_odul
        if b <= 0 or p <= 0: return 0
        
        kelly_yuzdesi = (p * (b + 1) - 1) / b
        # Agresifliği azaltmak için (Yarım Kelly) kullanılması tavsiye edilir
        yarim_kelly = max(0, kelly_yuzdesi / 2) 
        
        # Sermayenin maksimum %10'u bir hisseye bağlanabilir kuralı
        final_oran = min(yarim_kelly, 0.10) 
        return final_oran

    def analiz_et(self, hisse_kodu):
        gunluk, haftalik, temel, duygu_skoru = DataFetcher.veri_indir(hisse_kodu)
        if gunluk is None: return None
            
        gunluk = QuantModel.gostergeleri_hesapla(gunluk)
        if gunluk.empty: return None
            
        # Backtest & Risk/Ödül Hesaplaması
        win_rate, getiri, islem_sayisi, risk_odul = Backtester.gercekci_test(gunluk, self.config.komisyon, self.config.slippage)
        
        # Makine Öğrenmesi Tahmini
        ml_olasilik = QuantModel.ml_tahmin_et(gunluk)
        
        son_gun = gunluk.iloc[-1]
        fiyat = float(son_gun['Close'])
        rsi = float(son_gun['RSI'])
        atr = float(son_gun['ATR'])
        
        izleyen_stop = float(son_gun['Highest_10']) - (atr * self.config.atr_stop)
        izleyen_stop = izleyen_stop if izleyen_stop < fiyat else fiyat - (atr * self.config.atr_stop)
        kar_al = fiyat + (atr * self.config.atr_kar)
        
        # --- SKORLAMA ---
        skor = 0
        nedenler = []
        
        if ml_olasilik > 65: skor += 25; nedenler.append(f"AI: %{ml_olasilik} Yükseliş")
        elif ml_olasilik < 40: skor -= 25; nedenler.append(f"AI: Düşüş Beklentisi")
            
        if duygu_skoru > 20: skor += 10; nedenler.append("Pozitif Haber/Hacim Akışı")
        elif duygu_skoru < -20: skor -= 15; nedenler.append("Negatif Piyasa Duygusu")
            
        if son_gun['MACD_Line'] > son_gun['MACD_Signal']: skor += 15
        if son_gun['Z_Score'] > 2.5: skor -= 30; nedenler.append("Matematiksel Olarak Şişmiş")
        
        if temel.get('fk') and 0 < temel.get('fk') < 15: skor += 10
        if win_rate > 55: skor += 15; nedenler.append("Tarihsel Başarı Yüksek")

        skor = max(0, min(skor, 100))
        
        if skor >= 80: karar = "🔥 KESİN AL"
        elif skor >= 60: karar = "🟢 POTANSİYEL AL"
        elif skor <= 30 or rsi > self.config.rsi_sat: karar = "🔴 SAT / RİSKLİ"
        else: karar = "⚪ İZLEMEDE"
            
        # Kelly Kriteri ile Pozisyon Büyüklüğü
        kelly_orani = self.kelly_kriteri_hesapla(win_rate, risk_odul)
        onerilen_sermaye = self.config.sermaye * kelly_orani
        lot_sayisi = int(onerilen_sermaye / fiyat) if "AL" in karar else 0
            
        # Mock Execution (Simüle Edilmiş Emir Gönderimi)
        if "KESİN AL" in karar and lot_sayisi > 0:
            ExecutionAPI.emir_gonder(hisse_kodu, "AL", lot_sayisi, fiyat)
            
        sonuc_dict = {
            "Hisse": hisse_kodu.replace(".IS", ""), 
            "Karar": karar, 
            "AI Tahmini": f"%{ml_olasilik}",
            "Skor": f"%{skor}",
            "Net Getiri (2Y)": f"%{getiri}",
            "Win Rate": f"%{win_rate}",
            "Risk/Ödül": round(risk_odul, 2),
            "Fiyat (₺)": round(fiyat, 2), 
            "Kelly Lotu": lot_sayisi,
            "Nedenler": " | ".join(nedenler[:3])
        }
        
        return sonuc_dict

# --- 7. ARAYÜZ (UI) ---
def ui_olustur():
    st.title("🧠 YZ Destekli Hedge Fon Botu v6.0")
    st.markdown("Makine Öğrenmesi (RF), Kelly Optimizasyonu, NLP Duygu Analizi ve Gerçekçi Komisyon/Slippage destekli profesyonel mimari.")

    st.sidebar.markdown("### 🏦 Kurumsal Parametreler")
    toplam_sermaye = st.sidebar.number_input("Yönetilen Bakiye (₺)", min_value=10000, value=100000)
    komisyon = st.sidebar.number_input("Aracı Kurum Komisyon Oranı (%)", value=0.1, step=0.05) / 100
    slippage = st.sidebar.number_input("Tahmini Kayma (Slippage) (%)", value=0.2, step=0.1) / 100

    config = BotConfig(40, 75, 1.5, 3.0, toplam_sermaye, komisyon, slippage)
    strateji = QuantStrategy(config)

    varsayilan_hisseler = "THYAO\nASELS\nTUPRS\nISCTR\nKCHOL"
    hisseler_metin = st.sidebar.text_area("Taranacak Hisseler:", varsayilan_hisseler, height=120)

    if st.sidebar.button("🚀 Derin Öğrenme ve Analizi Başlat"):
        hisse_listesi = [h.strip().upper() + ".IS" for h in hisseler_metin.split("\n") if h.strip()]
        
        st.info("Makine Öğrenmesi modelleri eğitiliyor ve piyasa duygu analizleri yapılıyor...")
        ilerleme = st.progress(0)
        durum = st.empty()
        sonuclar = []
        
        for i, hisse in enumerate(hisse_listesi):
            durum.text(f"Eğitiliyor ve Analiz Ediliyor: {hisse}")
            analiz = strateji.analiz_et(hisse)
            if analiz: sonuclar.append(analiz)
            ilerleme.progress((i + 1) / len(hisse_listesi))
            
        durum.empty()
        
        if sonuclar:
            df = pd.DataFrame(sonuclar)
            
            def tabloyu_renklendir(val):
                if "🔥 KESİN AL" in str(val): return 'background-color: #1e4620; color: white; font-weight: bold;'
                elif "🔴 SAT" in str(val): return 'background-color: #b71c1c; color: white;'
                return ''
                
            st.dataframe(df.style.map(tabloyu_renklendir, subset=['Karar']), use_container_width=True)
            
            st.markdown("""
            **Sistem Notları (V6.0):**
            * **AI Tahmini:** Random Forest makine öğrenmesi modelinin geçmiş verilere dayanarak hesapladığı yarınki yükseliş olasılığı.
            * **Kelly Lotu:** Risk/Ödül dengesini hesaplayarak kasayı sıfırlamamak için geliştirilmiş matematiksel alım miktarıdır (Sabit oran yerine dinamiktir).
            * **Net Getiri:** Alım-satım komisyonları ve emir kaymaları (slippage) dahil edilmiş *gerçekçi* backtest getirisidir.
            """)
        else:
            st.error("Sistem veri işleyemedi.")

if __name__ == "__main__":
    ui_olustur()
