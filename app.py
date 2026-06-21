import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import ta
import warnings
import logging
from sklearn.ensemble import RandomForestClassifier

warnings.filterwarnings('ignore')
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- SAYFA AYARLARI ---
st.set_page_config(page_title="Ultimate Quant Bot v6.3", page_icon="🤖", layout="wide")

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

# --- 2. VERİ VE DUYGU ANALİZİ ---
class DataFetcher:
    @staticmethod
    @st.cache_data(ttl=3600, show_spinner=False) # Verileri 1 saat önbellekte tutar
    def veri_indir(hisse_kodu):
        try:
            ticker = yf.Ticker(hisse_kodu)
            gunluk_veri = ticker.history(period="2y", interval="1d")
            
            # Günlük veri yetersizse hiç başlama
            if gunluk_veri.empty or len(gunluk_veri) < 60: 
                return None, None, None, None
                
            # Haftalık veriyi al, yoksa veya eksikse sistemi durdurma
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
            logging.error(f"Veri çekme hatası ({hisse_kodu}): {e}")
            return None, None, None, None

# --- 3. TEKNİK VE MAKİNE ÖĞRENMESİ ---
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
        
        df['Std_Dev'] = kapanis.rolling(window=20).std()
        df['Z_Score'] = (kapanis - df['SMA_20']) / df['Std_Dev']
        df['Highest_10'] = yuksek.rolling(window=10).max()
        
        # 50 günlük ortalama hesabı nedeniyle ilk 50 gün NaN olur, siliyoruz.
        df.dropna(inplace=True)
        return df

    @staticmethod
    def ml_tahmin_et(df):
        try:
            veri = df.copy()
            veri['Hedef'] = np.where(veri['Close'].shift(-1) > veri['Close'], 1, 0)
            veri.dropna(inplace=True)
            
            ozellikler = ['RSI', 'MACD_Line', 'ADX', 'Z_Score', 'Volume']
            X = veri[ozellikler]
            y = veri['Hedef']
            
            model = RandomForestClassifier(n_estimators=100, random_state=42, max_depth=5)
            model.fit(X, y)
            
            son_veri = df[ozellikler].iloc[-1:]
            yukselis_olasiligi = model.predict_proba(son_veri)[0][1] * 100
            return round(yukselis_olasiligi, 1)
        except:
            return 50.0

# --- 4. BACKTEST (ATR, Slippage & Komisyon) ---
class Backtester:
    @staticmethod
    def gercekci_test(df, komisyon_orani, slippage_orani, config):
        # Dropna yapıldığı için df uzunluğu üzerinden direkt kontrole geçiyoruz
        if df is None or len(df) < 10: return 0, 0, 0, 0
        
        baslangic = 100000
        sermaye = baslangic
        pozisyon_acik = False
        alinan_fiyat = 0
        stop_fiyati = 0
        kar_al_fiyati = 0
        alinan_lot = 0
        
        basarili_islem = 0
        kazanc_toplami = 0
        kayip_toplami = 0
        toplam_islem = 0
        
        # DataFrame baştan temizlendiği için 1. indexten başlıyoruz
        for i in range(1, len(df)):
            row = df.iloc[i]
            
            al_sinyali = (row['Close'] > row['SMA_50']) and (row['MACD_Line'] > row['MACD_Signal'])
            
            # Dinamik Stop ve Kar-Al Yönetimi
            if pozisyon_acik:
                if row['Low'] <= stop_fiyati or row['High'] >= kar_al_fiyati or row['RSI'] > config.rsi_sat or (row['MACD_Line'] < row['MACD_Signal']):
                    satis_fiyati = kar_al_fiyati if row['High'] >= kar_al_fiyati else (stop_fiyati if row['Low'] <= stop_fiyati else row['Close'])
                    gercek_satim_fiyati = satis_fiyati * (1 - slippage_orani)
                    
                    brut_sermaye = alinan_lot * gercek_satim_fiyati
                    sermaye = brut_sermaye - (brut_sermaye * komisyon_orani)
                    toplam_islem += 1
                    
                    if sermaye > (alinan_lot * alinan_fiyat): 
                        basarili_islem += 1
                        kazanc_toplami += (gercek_satim_fiyati - alinan_fiyat)
                    else:
                        kayip_toplami += (alinan_fiyat - gercek_satim_fiyati)
                    pozisyon_acik = False
                    
            elif not pozisyon_acik and al_sinyali and row['RSI'] < config.rsi_al:
                gercek_alim_fiyati = row['Close'] * (1 + slippage_orani)
                sermaye -= (sermaye * komisyon_orani)
                alinan_lot = sermaye / gercek_alim_fiyati
                alinan_fiyat = gercek_alim_fiyati
                
                # ATR Çarpanları ile Stop/Kar Belirleme
                stop_fiyati = gercek_alim_fiyati - (row['ATR'] * config.atr_stop)
                kar_al_fiyati = gercek_alim_fiyati + (row['ATR'] * config.atr_kar)
                pozisyon_acik = True
                
        getiri_yuzdesi = ((sermaye - baslangic) / baslangic) * 100
        win_rate = (basarili_islem / toplam_islem) if toplam_islem > 0 else 0
        ortalama_kazanc = (kazanc_toplami / basarili_islem) if basarili_islem > 0 else 1
        ortalama_kayip = (kayip_toplami / (toplam_islem - basarili_islem)) if (toplam_islem - basarili_islem) > 0 else 1
        
        return round(win_rate * 100, 1), round(getiri_yuzdesi, 1), toplam_islem, ortalama_kazanc / ortalama_kayip

# --- 5. STRATEJİ MOTORU ---
class QuantStrategy:
    def __init__(self, config):
        self.config = config

    def kelly_kriteri_hesapla(self, win_rate, risk_odul):
        p = win_rate / 100
        b = risk_odul
        if b <= 0 or p <= 0: return 0
        kelly_yuzdesi = (p * (b + 1) - 1) / b
        return min(max(0, kelly_yuzdesi / 2), 0.10) 

    def analiz_et(self, hisse_kodu):
        gunluk, haftalik, temel, duygu_skoru = DataFetcher.veri_indir(hisse_kodu)
        if gunluk is None: return None
            
        gunluk = QuantModel.gostergeleri_hesapla(gunluk)
        if gunluk.empty: return None
            
        win_rate, getiri, islem_sayisi, risk_odul = Backtester.gercekci_test(gunluk, self.config.komisyon, self.config.slippage, self.config)
        ml_olasilik = QuantModel.ml_tahmin_et(gunluk)
        
        son_gun = gunluk.iloc[-1]
        fiyat = float(son_gun['Close'])
        rsi = float(son_gun['RSI'])
        
        skor = 0
        nedenler = []
        
        if ml_olasilik > 65: skor += 25; nedenler.append(f"AI: %{ml_olasilik} Yükseliş")
        elif ml_olasilik < 40: skor -= 25
            
        if duygu_skoru > 20: skor += 10
        if son_gun['MACD_Line'] > son_gun['MACD_Signal']: skor += 15
        if son_gun['Z_Score'] > 2.5: skor -= 30; nedenler.append("Matematiksel Şişmiş")
        
        if temel.get('fk') and 0 < temel.get('fk') < 15: skor += 10
        if win_rate > 55: skor += 15
        
        skor = max(0, min(skor, 100))
        
        # Skor kararları 
        if skor >= 80: karar = "🔥 KESİN AL"
        elif skor >= 60: karar = "🟢 POTANSİYEL AL"
        elif skor <= 30 or rsi > self.config.rsi_sat: karar = "🔴 SAT / RİSKLİ"
        else: karar = "⚪ İZLEMEDE"
            
        kelly_orani = self.kelly_kriteri_hesapla(win_rate, risk_odul)
        lot_sayisi = int((self.config.sermaye * kelly_orani) / fiyat) if "AL" in karar else 0
            
        return {
            "Hisse": hisse_kodu.replace(".IS", ""), 
            "Karar": karar, 
            "AI Tahmini": f"%{ml_olasilik}",
            "Skor": f"%{skor}",
            "Net Getiri (2Y)": f"%{getiri}",
            "Win Rate": f"%{win_rate}",
            "Fiyat (₺)": round(fiyat, 2), 
            "Kelly Lotu": lot_sayisi,
            "Nedenler": " | ".join(nedenler[:3]) if nedenler else "Standart Görünüm"
        }

# --- 6. ARAYÜZ (UI) ---
def ui_olustur():
    st.title("🧠 YZ Destekli Hedge Fon Botu v6.3")
    st.markdown("BIST 100 Katılım Radarı, AI Tahmini ve Kelly Optimizasyonu entegreli.")
    st.markdown("---")

    # --- YAN MENÜ ---
    st.sidebar.markdown("### 🏦 Kurumsal Parametreler")
    toplam_sermaye = st.sidebar.number_input("Yönetilen Bakiye (₺)", min_value=10000, value=100000)
    komisyon = st.sidebar.number_input("Komisyon Oranı (%)", value=0.1, step=0.05) / 100
    slippage = st.sidebar.number_input("Tahmini Kayma (%)", value=0.2, step=0.1) / 100

    config = BotConfig(60, 75, 1.5, 3.0, toplam_sermaye, komisyon, slippage)
    strateji = QuantStrategy(config)

    # --- 1. MANUEL TARAMA BÖLÜMÜ ---
    st.sidebar.markdown("### 🔍 Manuel Tarama")
    varsayilan_hisseler = "THYAO\nASELS\nTUPRS\nMPARK\nYUNSA\nBIMAS\nDOAS"
    hisseler_metin = st.sidebar.text_area("Taranacak Hisseler:", varsayilan_hisseler, height=140)

    if st.sidebar.button("🚀 Manuel Analizi Başlat", use_container_width=True):
        hisse_listesi = [h.strip().upper() + ".IS" for h in hisseler_metin.split("\n") if h.strip()]
        
        ilerleme = st.progress(0)
        durum = st.empty()
        sonuclar = []
        
        for i, hisse in enumerate(hisse_listesi):
            durum.text(f"Analiz ediliyor: {hisse}")
            analiz = strateji.analiz_et(hisse)
            if analiz: sonuclar.append(analiz)
            ilerleme.progress((i + 1) / len(hisse_listesi))
            
        durum.empty()
        
        if sonuclar:
            df = pd.DataFrame(sonuclar)
            def tablo_renk(val):
                if "🔥 KESİN AL" in str(val): return 'background-color: #1e4620; color: white; font-weight: bold;'
                elif "🟢 POTANSİYEL AL" in str(val): return 'background-color: #388e3c; color: white;'
                elif "🔴 SAT" in str(val): return 'background-color: #b71c1c; color: white;'
                return ''
                
            st.dataframe(df.style.map(tablo_renk, subset=['Karar']), use_container_width=True)
        else:
            st.error("Veri işlenemedi. Yahoo Finance geçici olarak yanıt vermiyor olabilir.")

    # --- 2. OTOMATİK FIRSAT RADARI ---
    st.markdown("### 📡 Otomatik Fırsat Radarı (BIST 100 Katılım Endeksi)")
    st.markdown("Sistem arka planda katılım endeksindeki tahtaları tarar ve **AL (Skor $\geq$ %60)** seviyesine ulaşanları yakalar.")

    if st.button("🔍 Katılım Radarını Çalıştır", use_container_width=True):
        # BIST 100 Katılım Endeksi Temsili Hisseleri
        bist_katilim_hisseler = [
            "ALBRK.IS", "ASELS.IS", "BIMAS.IS", "CANTE.IS", "CIMSA.IS", "DOAS.IS", 
            "EGEEN.IS", "EKGYO.IS", "ENJSA.IS", "ENKAI.IS", "EUPWR.IS", "FROTO.IS", 
            "GWIND.IS", "HEKTS.IS", "KCAER.IS", "KMPUR.IS", "KONTR.IS", "KORDS.IS", 
            "KOZAA.IS", "KOZAL.IS", "KRDMD.IS", "MIATK.IS", "MPARK.IS", "OTKAR.IS", 
            "OYAKC.IS", "PGSUS.IS", "SASA.IS", "SMARTG.IS", "SMRTG.IS", "THYAO.IS", 
            "TOASO.IS", "TUKAS.IS", "TUPRS.IS", "ULKER.IS", "VESBE.IS", "VESTL.IS", 
            "YEOTK.IS", "YUNSA.IS"
        ]
        
        st.info("BIST 100 Katılım hisseleri taranıyor. Cache sistemi sayesinde ikinci taramalar anında gerçekleşecektir...")
        radar_ilerleme = st.progress(0)
        bulunan_firsatlar = []
        
        for i, hisse in enumerate(bist_katilim_hisseler):
            sonuc = strateji.analiz_et(hisse)
            # AL sinyali içerenleri (Kesin Al & Potansiyel Al) yakalıyoruz (Skor >= 60 şartını Karar metni sağlıyor)
            if sonuc and ("AL" in sonuc["Karar"]):
                bulunan_firsatlar.append(sonuc)
            radar_ilerleme.progress((i + 1) / len(bist_katilim_hisseler))
            
        radar_ilerleme.empty()
        
        if bulunan_firsatlar:
            st.success(f"🚨 Ekrana Düşen Fırsatlar: Katılım Endeksinde {len(bulunan_firsatlar)} Adet 'AL' Sinyali Yakalandı!")
            
            sutunlar = st.columns(min(len(bulunan_firsatlar), 4))
            for idx, firsat in enumerate(bulunan_firsatlar):
                with sutunlar[idx % 4]:
                    
                    renk_kodu = "#1e4620" if "KESİN" in firsat["Karar"] else "#2e7d32"
                    
                    st.markdown(f"""
                    <div style="border: 2px solid #2e7d32; border-radius: 10px; padding: 15px; background-color: {renk_kodu}; color: white; margin-bottom: 10px;">
                        <h2 style="text-align: center; color: #4caf50; margin-top: 0;">{firsat['Hisse']}</h2>
                        <h1 style="text-align: center; margin: 0;">{firsat['Skor']}</h1>
                        <p style="text-align: center; font-size: 18px;"><b>{firsat['Fiyat (₺)']} ₺</b></p>
                        <p style="text-align: center; font-size: 14px; background-color: #1b5e20; border-radius: 5px; padding: 3px;">{firsat['Karar']}</p>
                        <hr style="border-color: #4caf50;">
                        <p style="font-size: 14px;"><b>Yapay Zeka:</b> {firsat['AI Tahmini']}</p>
                        <p style="font-size: 14px;"><b>Win Rate:</b> {firsat['Win Rate']}</p>
                        <p style="font-size: 12px; color: #a5d6a7;"><i>{firsat['Nedenler']}</i></p>
                    </div>
                    """, unsafe_allow_html=True)
        else:
            st.warning("Şu anki piyasa koşullarında BIST 100 Katılım Endeksi içinde radara takılan bir fırsat bulunamadı.")

if __name__ == "__main__":
    ui_olustur()
