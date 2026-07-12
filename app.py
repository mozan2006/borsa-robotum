import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import ta
import warnings
import logging
import requests
import datetime
import plotly.graph_objects as go
from concurrent.futures import ThreadPoolExecutor
from sklearn.ensemble import RandomForestClassifier
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
warnings.filterwarnings('ignore')
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# İş Yatırım kütüphanesi kontrolü
try:
    from isyatirimhisse import fetch_data
except ImportError:
    fetch_data = None

# --- SAYFA AYARLARI ---
st.set_page_config(page_title="Ultimate Quant Bot v9.5 PRO", page_icon="🤖", layout="wide")

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

# --- GRAFİK ÇİZİCİ MODÜL ---
def cizgi_grafik_olustur(df, hisse, al_fiyati, stop, kar_al):
    fig = go.Figure()
    
    fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='Fiyat'))
    if 'SMA_50' in df.columns: fig.add_trace(go.Scatter(x=df.index, y=df['SMA_50'], line=dict(color='#29b6f6', width=1.5), name='SMA 50'))
    if 'SMA_200' in df.columns: fig.add_trace(go.Scatter(x=df.index, y=df['SMA_200'], line=dict(color='#ffa726', width=2), name='SMA 200'))
    
    fig.add_hline(y=al_fiyati, line_dash="dot", line_color="#4fc3f7", annotation_text="Al")
    fig.add_hline(y=stop, line_dash="dash", line_color="#ef5350", annotation_text="Stop")
    fig.add_hline(y=kar_al, line_dash="dash", line_color="#66bb6a", annotation_text="Kar Al")

    fig.update_layout(margin=dict(l=10, r=10, t=30, b=10), height=300, xaxis_rangeslider_visible=False, template="plotly_dark", title=dict(text=f"{hisse} - Teknik Görünüm", font=dict(size=14, color="#a5d6a7")), showlegend=False, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
    return fig

# --- 2. HAKİKİ QUANTAMENTAL VERİ ---
class DataFetcher:
    @staticmethod
    @st.cache_data(ttl=1200, show_spinner=False)
    def veri_indir(hisse_kodu):
        try:
            ticker = yf.Ticker(hisse_kodu)
            gunluk_veri = ticker.history(period="2y", interval="1d")
            
            if not gunluk_veri.empty and len(gunluk_veri) >= 60:
                haftalik_veri = ticker.history(period="5y", interval="1wk")
                return gunluk_veri, haftalik_veri
        except Exception: pass

        # İş Yatırım Yedek Motoru
        try:
            sembol = hisse_kodu.replace(".IS", "")
            bitis = datetime.datetime.now().strftime("%d-%m-%Y")
            baslangic = (datetime.datetime.now() - datetime.timedelta(days=730)).strftime("%d-%m-%Y")
            url = f"https://www.isyatirim.com.tr/_layouts/15/IsYatirim.Website/Common/Data.aspx/HisseTekil?hisse={sembol}&startdate={baslangic}&enddate={bitis}"
            res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
            veri_json = res.json()
            
            if 'value' in veri_json and veri_json['value']:
                df = pd.DataFrame(veri_json['value'])
                df['Date'] = pd.to_datetime(df['HGDG_TARIH'], format='%d-%m-%Y')
                df.set_index('Date', inplace=True)
                df.rename(columns={'KAPANIS': 'Close', 'MAX': 'High', 'MIN': 'Low', 'ISLEM_MIKTARI': 'Volume'}, inplace=True)
                df['Open'] = df['Close'].shift(1).fillna(df['Close'])
                gunluk_veri = df[['Open', 'High', 'Low', 'Close', 'Volume']].astype(float)
                
                if len(gunluk_veri) >= 60:
                    haftalik_veri = gunluk_veri.resample('W').agg({'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'})
                    return gunluk_veri, haftalik_veri
        except Exception: pass
            
        return None, None

    @staticmethod
    @st.cache_data(ttl=3600, show_spinner=False)
    def piyasa_rejimi_kontrol():
        try:
            bist = yf.Ticker("XU100.IS")
            df = bist.history(period="1y", interval="1d")
            if not df.empty and len(df) > 200:
                sma_200 = ta.trend.SMAIndicator(close=df['Close'], window=200).sma_indicator()
                son_kapanis = df['Close'].iloc[-1]
                durum = "BULL" if son_kapanis > sma_200.iloc[-1] else "BEAR"
                return durum, df
        except: pass
        return "BULL", None

# --- 3. YENİ NESİL FİLTRELER VE TEKNİK ANALİZ ---
class QuantModel:
    @staticmethod
    def gostergeleri_hesapla(df, bist_df):
        kapanis, hacim, yuksek, dusuk = df['Close'], df['Volume'], df['High'], df['Low']
        
        df['RSI'] = ta.momentum.RSIIndicator(close=kapanis).rsi()
        macd = ta.trend.MACD(close=kapanis)
        df['MACD_Line'] = macd.macd()
        df['MACD_Signal'] = macd.macd_signal()
        df['SMA_20'] = ta.trend.SMAIndicator(close=kapanis, window=20).sma_indicator()
        df['SMA_50'] = ta.trend.SMAIndicator(close=kapanis, window=50).sma_indicator()
        df['SMA_100'] = kapanis.rolling(window=100, min_periods=1).mean()
        df['SMA_200'] = kapanis.rolling(window=200, min_periods=1).mean()
        df['ATR'] = ta.volatility.AverageTrueRange(high=yuksek, low=dusuk, close=kapanis).average_true_range()
        
        # 1. ADX (Yatay Piyasa Filtresi)
        df['ADX'] = ta.trend.ADXIndicator(high=yuksek, low=dusuk, close=kapanis, window=14).adx()
        
        # 2. Akıllı Hacim ve OBV Filtresi
        df['Volume_SMA_20'] = hacim.rolling(window=20).mean()
        obv = ta.volume.OnBalanceVolumeIndicator(close=kapanis, volume=hacim).on_balance_volume()
        df['OBV_Trend'] = np.where(obv > obv.rolling(window=10).mean(), 1, 0)
        
        # 3. Göreceli Güç (Relative Strength)
        if bist_df is not None and not bist_df.empty:
            ortak_index = df.index.intersection(bist_df.index)
            df.loc[ortak_index, 'BIST_Return'] = bist_df.loc[ortak_index, 'Close'].pct_change()
            df['Hisse_Return'] = df['Close'].pct_change()
            # BIST'e göre son 14 günlük ekstra performans
            df['Goreceli_Guc'] = (df['Hisse_Return'] - df['BIST_Return']).rolling(window=14).mean() * 100
        else:
            df['Goreceli_Guc'] = 0
        
        df['Z_Score'] = (kapanis - df['SMA_20']) / kapanis.rolling(window=20).std()
        df['Vol_Pct'] = df['Volume'].pct_change() 
        df['Return'] = df['Close'].pct_change()
        
        df.dropna(inplace=True)
        return df

    @staticmethod
    def ml_tahmin_et(df):
        try:
            veri = df.copy()
            veri['Hedef'] = np.where(veri['Close'].shift(-1) > veri['Close'], 1, 0)
            veri.dropna(inplace=True)
            
            ozellikler = ['RSI', 'MACD_Line', 'ADX', 'Z_Score', 'Vol_Pct', 'Return', 'Goreceli_Guc']
            X, y = veri[ozellikler], veri['Hedef']
            
            # RAM çökmesini engellemek için n_jobs=1 parametresi eklendi
            model = RandomForestClassifier(n_estimators=100, random_state=42, max_depth=5, n_jobs=1)
            model.fit(X, y)
            
            son_veri = df[ozellikler].iloc[-1:]
            return round(model.predict_proba(son_veri)[0][1] * 100, 1)
        except: return 50.0

class Backtester:
    @staticmethod
    def gercekci_test(df, komisyon_orani, slippage_orani, config):
        if df is None or len(df) < 10: return 0, 0, 0, 0
        
        baslangic = 100000
        sermaye, pozisyon_acik, alinan_fiyat, stop_fiyati, kar_al_fiyati, alinan_lot = baslangic, False, 0, 0, 0, 0
        basarili_islem, kazanc_toplami, kayip_toplami, toplam_islem = 0, 0, 0, 0
        
        for i in range(1, len(df)):
            row = df.iloc[i]
            al_sinyali = (row['Close'] > row['SMA_50']) and (row['MACD_Line'] > row['MACD_Signal'])
            
            if pozisyon_acik:
                if row['Low'] <= stop_fiyati or row['High'] >= kar_al_fiyati or row['RSI'] > config.rsi_sat or (row['MACD_Line'] < row['MACD_Signal']):
                    satis_fiyati = kar_al_fiyati if row['High'] >= kar_al_fiyati else (stop_fiyati if row['Low'] <= stop_fiyati else row['Close'])
                    gercek_satim_fiyati = satis_fiyati * (1 - slippage_orani)
                    brut_sermaye = alinan_lot * gercek_satim_fiyati
                    sermaye = brut_sermaye - (brut_sermaye * komisyon_orani)
                    toplam_islem += 1
                    
                    if sermaye > (alinan_lot * alinan_fiyat): 
                        basarili_islem += 1; kazanc_toplami += (gercek_satim_fiyati - alinan_fiyat)
                    else: kayip_toplami += (alinan_fiyat - gercek_satim_fiyati)
                    pozisyon_acik = False
                    
            elif not pozisyon_acik and al_sinyali and row['RSI'] < config.rsi_al:
                gercek_alim_fiyati = row['Close'] * (1 + slippage_orani)
                sermaye -= (sermaye * komisyon_orani)
                alinan_lot = sermaye / gercek_alim_fiyati
                alinan_fiyat = gercek_alim_fiyati
                stop_fiyati = gercek_alim_fiyati - (row['ATR'] * config.atr_stop)
                kar_al_fiyati = gercek_alim_fiyati + (row['ATR'] * config.atr_kar)
                pozisyon_acik = True
                
        getiri_yuzdesi = ((sermaye - baslangic) / baslangic) * 100
        win_rate = (basarili_islem / toplam_islem) if toplam_islem > 0 else 0
        ort_kazanc = (kazanc_toplami / basarili_islem) if basarili_islem > 0 else 1
        ort_kayip = (kayip_toplami / (toplam_islem - basarili_islem)) if (toplam_islem - basarili_islem) > 0 else 1
        
        return round(win_rate * 100, 1), round(getiri_yuzdesi, 1), toplam_islem, ort_kazanc / ort_kayip

# --- 5. STRATEJİ MOTORU ---
class QuantStrategy:
    def __init__(self, config):
        self.config = config
        self.piyasa_durumu, self.bist_df = DataFetcher.piyasa_rejimi_kontrol()

    def analiz_et(self, hisse_kodu):
        gunluk, haftalik = DataFetcher.veri_indir(hisse_kodu)
        if gunluk is None or haftalik is None: return None
            
        gunluk = QuantModel.gostergeleri_hesapla(gunluk, self.bist_df)
        if gunluk.empty: return None
            
        win_rate, getiri, islem_sayisi, risk_odul = Backtester.gercekci_test(gunluk, self.config.komisyon, self.config.slippage, self.config)
        ml_olasilik = QuantModel.ml_tahmin_et(gunluk)
        
        son_gun = gunluk.iloc[-1]
        fiyat = float(son_gun['Close'])
        atr = float(son_gun['ATR'])
        
        al_fiyati = fiyat 
        stop_fiyati = al_fiyati - (atr * self.config.atr_stop)
        kar_fiyati = al_fiyati + (atr * self.config.atr_kar)
        
        skor = 30 
        nedenler = []

        # 1. Çoklu Zaman Dilimi (Haftalık Trend) - Pasif Yatırımcı Koruması
        haftalik_sma_10 = haftalik['Close'].rolling(10).mean()
        if not haftalik_sma_10.empty and haftalik['Close'].iloc[-1] > haftalik_sma_10.iloc[-1]:
            skor += 20; nedenler.append("Haftalık Trend Pozitif")
        else:
            skor -= 20; nedenler.append("Haftalık Trend Negatif (Risk)")

        # 2. ADX (Yatay Piyasayı Eleme)
        if son_gun['ADX'] > 20:
            skor += 15; nedenler.append(f"Trend Güçlü (ADX:{int(son_gun['ADX'])})")
        else:
            skor -= 15; nedenler.append("Yatay Piyasada Testere")

        # 3. Akıllı Hacim ve OBV Onayı
        if son_gun['Volume'] > (son_gun['Volume_SMA_20'] * 1.2):
            skor += 10; nedenler.append("Hacim Patlaması")
        if son_gun['OBV_Trend'] == 1:
            skor += 10; nedenler.append("Para Girişi (OBV)")
        else:
            skor -= 10

        # 4. Göreceli Güç (BIST100'ü Yenenler)
        if son_gun['Goreceli_Guc'] > 0:
            skor += 15; nedenler.append("BIST'ten Daha Güçlü (Alfa)")
        else:
            skor -= 10; nedenler.append("Endeksten Zayıf")

        # MACD ve Hareketli Ortalama Destekleri
        if son_gun['MACD_Line'] > son_gun['MACD_Signal']: skor += 10
        if fiyat > son_gun['SMA_200']: skor += 10
        elif fiyat < son_gun['SMA_200']: skor -= 20; nedenler.append("SMA200 Altında")
        
        if self.piyasa_durumu == "BEAR": skor -= 15; nedenler.append("BIST Ayı Piyasası")
        
        skor = max(0, min(skor, 100))
        
        # Karar Mekanizması Daha Sıkı Hale Getirildi
        if skor >= 80 and son_gun['ADX'] > 20: karar = "🔥 KESİN AL"
        elif skor >= 60: karar = "🟢 POTANSİYEL AL"
        elif skor <= 40: karar = "🔴 SAT / UZAK DUR"
        else: karar = "⚪ İZLEMEDE / NÖTR"
            
        p = win_rate / 100; b = risk_odul
        kelly_yuzdesi = (p * (b + 1) - 1) / b if (b > 0 and p > 0) else 0
        kelly_orani = min(max(0, kelly_yuzdesi / 2), 0.10)
        lot_sayisi = int((self.config.sermaye * kelly_orani) / fiyat) if "AL" in karar else 0
            
        return {
            "Hisse": hisse_kodu.replace(".IS", ""), 
            "Karar": karar, 
            "Skor": f"%{skor}",
            "Fiyat (₺)": round(fiyat, 2), 
            "Stop-Loss (₺)": round(stop_fiyati, 2),
            "Kar Al (₺)": round(kar_fiyati, 2),
            "Kelly Lotu": lot_sayisi,
            "Win Rate": f"%{win_rate}",
            "Nedenler": " | ".join(nedenler[:3]) if nedenler else "Yatay / Stabil",
            "Grafik_Verisi": gunluk[['Open', 'High', 'Low', 'Close', 'SMA_50', 'SMA_200']].tail(65)
        }

# --- 6. ARAYÜZ (UI) ---
def ui_olustur():
    st.title("🧠 YZ Destekli Katılım Fonu Botu v9.5 PRO")
    st.markdown("Haftalık Trend (Multi-Timeframe), Hacim Patlaması, ADX Filtresi ve Göreceli Güç (Alfa) özellikleri entegre edildi.")
    st.markdown("---")

    st.sidebar.markdown("### 🏦 Kurumsal Parametreler")
    toplam_sermaye = st.sidebar.number_input("Yönetilen Bakiye (₺)", min_value=10000, value=100000)
    komisyon = st.sidebar.number_input("Komisyon Oranı (%)", value=0.1, step=0.05) / 100
    slippage = st.sidebar.number_input("Tahmini Kayma (%)", value=0.2, step=0.1) / 100

    config = BotConfig(60, 75, 1.5, 3.0, toplam_sermaye, komisyon, slippage)
    strateji = QuantStrategy(config)

    if strateji.piyasa_durumu == "BULL": st.sidebar.success("📊 BIST Genel Trendi: BOĞA (Güvenli)")
    else: st.sidebar.warning("⚠️ BIST Genel Trendi: AYI (Baskılı)")

    st.sidebar.markdown("### 🔍 Özel Portföy Taraması")
    
    # Kullanıcının düzenli takip ettiği hisseler varsayılan yapıldı
    varsayilan_hisseler = "MPARK\nBIMAS\nASELS\nENJSA\nTUPRS\nLOGO\nALBRK\nCIMSA\nEBEBK\nYEOTK"
    hisseler_metin = st.sidebar.text_area("Taranacak Hisseler:", varsayilan_hisseler, height=200)

    if st.sidebar.button("🚀 Portföyü Analiz Et", use_container_width=True):
        hisse_listesi = [h.strip().upper() + ".IS" for h in hisseler_metin.split("\n") if h.strip()]
        ilerleme = st.progress(0)
        sonuclar = []
        
        # CPU ve RAM çökmesini engellemek için thread sayısı 3'te tutuldu
        with ThreadPoolExecutor(max_workers=3) as executor:
            sonuc_haritasi = executor.map(strateji.analiz_et, hisse_listesi)
            for idx, sonuc in enumerate(sonuc_haritasi):
                if sonuc: sonuclar.append(sonuc)
                ilerleme.progress((idx + 1) / len(hisse_listesi))
        ilerleme.empty()
        
        if sonuclar:
            df = pd.DataFrame(sonuclar)
            gosterim_df = df.drop(columns=['Grafik_Verisi'])
            
            def tablo_renk(val):
                if "🔥 KESİN AL" in str(val): return 'background-color: #1e4620; color: white; font-weight: bold;'
                elif "🟢 POTANSİYEL AL" in str(val): return 'background-color: #388e3c; color: white;'
                elif "🔴 SAT" in str(val): return 'background-color: #b71c1c; color: white;'
                elif "⚪ İZLEMEDE" in str(val): return 'background-color: #546e7a; color: white;'
                return ''
            st.dataframe(gosterim_df.style.map(tablo_renk, subset=['Karar']), use_container_width=True)
        else:
            st.error("Veri işlenemedi.")

    st.markdown("### 📡 Otomatik Fırsat Radarı (Sadece Katılım Endeksi)")
    st.markdown("Bu radar günlük "AL" sinyallerini **Haftalık Trend**, **Hacim Patlaması**, **ADX** ve **Göreceli Güç (Alfa)** filtrelerinden geçirerek sahte sinyalleri eler.")

    if st.button("🔍 Gelişmiş Radarı Çalıştır", use_container_width=True):
        bist_katilim_hisseler = [
            "ALBRK.IS", "ALFAS.IS", "ASELS.IS", "ASTOR.IS", "BIMAS.IS", "BRSAN.IS", 
            "CANTE.IS", "CIMSA.IS", "CWENE.IS", "DOAS.IS", "EGEEN.IS", "EKGYO.IS", 
            "ENJSA.IS", "ENKAI.IS", "EUPWR.IS", "FROTO.IS", "GESAN.IS", "GWIND.IS", 
            "HEKTS.IS", "IPEKE.IS", "JANTS.IS", "KCAER.IS", "KMPUR.IS", "KONTR.IS", 
            "KORDS.IS", "KOZAA.IS", "KOZAL.IS", "KRDMD.IS", "MIATK.IS", "MPARK.IS", 
            "OTKAR.IS", "OYAKC.IS", "QUAGR.IS", "SASA.IS", "SMRTG.IS", "TTRAK.IS", 
            "TUKAS.IS", "VESBE.IS", "YEOTK.IS", "YUNSA.IS"
        ]
        
        st.info("Eşzamanlı Tarama Aktif. Çoklu zaman dilimi ve hacim analizi yapılıyor...")
        
        bulunan_firsatlar = []
        with ThreadPoolExecutor(max_workers=3) as executor:
            radar_sonuclari = executor.map(strateji.analiz_et, bist_katilim_hisseler)
            for sonuc in radar_sonuclari:
                if sonuc and ("AL" in sonuc["Karar"]):
                    bulunan_firsatlar.append(sonuc)
        
        if bulunan_firsatlar:
            st.success(f"🚨 Tarama Tamamlandı: Sağlıklı Kriterlere Uyan {len(bulunan_firsatlar)} Adet Sinyal Yakalandı!")
            
            sutunlar = st.columns(min(len(bulunan_firsatlar), 3))
            for idx, firsat in enumerate(bulunan_firsatlar):
                with sutunlar[idx % 3]:
                    renk_kodu = "#1e4620" if "KESİN" in firsat["Karar"] else "#2e7d32"
                    
                    st.markdown(f"""
                    <div style="border: 2px solid #2e7d32; border-top-left-radius: 10px; border-top-right-radius: 10px; padding: 15px; background-color: {renk_kodu}; color: white; margin-bottom: 0px;">
                        <h2 style="text-align: center; color: #4caf50; margin-top: 0;">{firsat['Hisse']}</h2>
                        <h1 style="text-align: center; margin: 0;">{firsat['Skor']}</h1>
                        <p style="text-align: center; font-size: 15px; background-color: #1b5e20; border-radius: 5px; padding: 3px;"><b>{firsat['Karar']}</b></p>
                        <hr style="border-color: #4caf50; margin-bottom: 8px; margin-top: 8px;">
                        <p style="font-size: 14px; margin: 3px 0;"><b>🔵 Dinamik Al:</b> {firsat['Fiyat (₺)']} ₺</p>
                        <p style="font-size: 14px; margin: 3px 0; color: #ff8a80;"><b>🔴 Stop-Loss:</b> {firsat['Stop-Loss (₺)']} ₺</p>
                        <p style="font-size: 14px; margin: 3px 0; color: #b9f6ca;"><b>🟢 Kâr Al Target:</b> {firsat['Kar Al (₺)']} ₺</p>
                        <hr style="border-color: #4caf50; margin-bottom: 8px; margin-top: 8px;">
                        <p style="font-size: 13px; margin: 2px 0;"><b>Neden:</b> {firsat['Nedenler']}</p>
                        <p style="font-size: 13px; margin: 2px 0;"><b>Kelly Lotu:</b> {firsat['Kelly Lotu']} Lot</p>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    with st.expander("📊 Grafiği İncele"):
                        fig = cizgi_grafik_olustur(firsat['Grafik_Verisi'], firsat['Hisse'], firsat['Fiyat (₺)'], firsat['Stop-Loss (₺)'], firsat['Kar Al (₺)'])
                        st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})
                    
                    st.markdown("<br>", unsafe_allow_html=True)
        else:
            st.warning("Trend ve hacim filtrelerinden geçebilen güvenli bir fırsat bulunamadı (Piyasa şu an yatay veya hacimsiz olabilir).")

if __name__ == "__main__":
    ui_olustur()
