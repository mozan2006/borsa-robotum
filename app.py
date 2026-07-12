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
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from xgboost import XGBClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
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
st.set_page_config(page_title="Ultimate Quant Bot v9.0", page_icon="🤖", layout="wide")

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
    def __init__(self, rsi_al, rsi_sat, atr_stop, atr_kar, sermaye, komisyon, slippage, api_key):
        self.rsi_al = rsi_al
        self.rsi_sat = rsi_sat
        self.atr_stop = atr_stop
        self.atr_kar = atr_kar
        self.sermaye = sermaye
        self.komisyon = komisyon
        self.slippage = slippage
        self.api_key = api_key

# --- GRAFİK ÇİZİCİ MODÜL ---
def cizgi_grafik_olustur(df, hisse, al_fiyati, stop, kar_al):
    fig = go.Figure()
    
    # Mum Grafiği
    fig.add_trace(go.Candlestick(
        x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='Fiyat'
    ))
    
    # Hareketli Ortalamalar (Trend Çizgileri)
    if 'SMA_50' in df.columns:
        fig.add_trace(go.Scatter(x=df.index, y=df['SMA_50'], line=dict(color='#29b6f6', width=1.5), name='SMA 50'))
    if 'SMA_200' in df.columns:
        fig.add_trace(go.Scatter(x=df.index, y=df['SMA_200'], line=dict(color='#ffa726', width=2), name='SMA 200'))
    if 'VWAP' in df.columns:
        fig.add_trace(go.Scatter(x=df.index, y=df['VWAP'], line=dict(color='#ab47bc', width=1.5, dash='dot'), name='VWAP'))
    
    # Akıllı Emir Seviyeleri
    fig.add_hline(y=al_fiyati, line_dash="dot", line_color="#4fc3f7", annotation_text="Al", annotation_position="bottom left")
    fig.add_hline(y=stop, line_dash="dash", line_color="#ef5350", annotation_text="İzleyen Stop (Chandelier)", annotation_position="bottom right")
    fig.add_hline(y=kar_al, line_dash="dash", line_color="#66bb6a", annotation_text="Kar Al", annotation_position="top right")

    fig.update_layout(
        margin=dict(l=10, r=10, t=30, b=10),
        height=350,
        xaxis_rangeslider_visible=False,
        template="plotly_dark",
        title=dict(text=f"{hisse} - Gelişmiş Teknik Görünüm", font=dict(size=14, color="#a5d6a7")),
        showlegend=False,
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)'
    )
    return fig

# --- 2. HAKİKİ QUANTAMENTAL VERİ VE DUYGU ANALİZİ (YENİLENMİŞ MOTOR) ---
class DataFetcher:
    @staticmethod
    def veri_indir(hisse_kodu, api_key):
        temiz_isim = hisse_kodu.replace(".IS", "")
        bitis_tarihi = datetime.datetime.now()
        baslangic_tarihi = bitis_tarihi - datetime.timedelta(days=730)
        
        start_str = baslangic_tarihi.strftime("%d-%m-%Y")
        end_str = bitis_tarihi.strftime("%d-%m-%Y")
        
        df = None
        
        # 1. Öncelik: İş Yatırım
        if fetch_data is not None:
            try:
                df_is = fetch_data(symbol=temiz_isim, start_date=start_str, end_date=end_str)
                if df_is is not None and not df_is.empty:
                    df_is.columns = df_is.columns.str.upper()
                    col_map = {
                        'HACIM': 'Volume', 'HACİM': 'Volume', 'VOLUME': 'Volume', 'VOLUME_TL': 'Volume',
                        'KAPANIS': 'Close', 'KAPANIŞ': 'Close', 'CLOSING_TL': 'Close', 'CLOSING': 'Close',
                        'EN DUSUK': 'Low', 'EN DÜŞÜK': 'Low', 'MIN_TL': 'Low', 'MIN': 'Low',
                        'EN YUKSEK': 'High', 'EN YÜKSEK': 'High', 'MAX_TL': 'High', 'MAX': 'High',
                        'ACILIS': 'Open', 'AÇILIŞ': 'Open', 'OPENING': 'Open'
                    }
                    df_is.rename(columns=col_map, inplace=True)
                    date_col = 'TARIH' if 'TARIH' in df_is.columns else 'DATE' if 'DATE' in df_is.columns else None
                    if date_col:
                        df_is[date_col] = pd.to_datetime(df_is[date_col], errors='coerce')
                        df_is.set_index(date_col, inplace=True)
                    df_is.sort_index(inplace=True)
                    if all(col in df_is.columns for col in ['Close', 'High', 'Low', 'Volume']):
                        for col in ['Close', 'High', 'Low', 'Volume']:
                            df_is[col] = pd.to_numeric(df_is[col], errors='coerce')
                        df = df_is.dropna(subset=['Close'])
            except Exception: pass
            
        # 2. Öncelik: YFinance
        if df is None or len(df) < 60:
            try:
                df = yf.download(hisse_kodu, start=baslangic_tarihi, end=bitis_tarihi, progress=False)
                if df is not None and not df.empty:
                    if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.droplevel(1)
            except Exception: pass

        if df is None or len(df) < 60:
            return None, None, None, 0, "Veri Alınamadı"

        # Temel Veriler
        fk, pddd = 15.0, 2.0
        try:
            ticker = yf.Ticker(hisse_kodu)
            info = ticker.info
            fk = info.get('trailingPE', 15.0)
            pddd = info.get('priceToBook', 2.0)
        except: pass

        temel_veriler = {'fk': fk, 'pd_dd': pddd, 'roe': None}
        haber_skoru, haber_durumu = DataFetcher.haber_duygu_analizi(temiz_isim, api_key)
        
        return df, None, temel_veriler, haber_skoru, haber_durumu

    @staticmethod
    def haber_duygu_analizi(temiz_isim, api_key):
        basliklar = []
        headers = {"User-Agent": "Mozilla/5.0"}
        
        try:
            from bs4 import BeautifulSoup
            url_scraping = f"https://borsa.doviz.com/hisseler/{temiz_isim.lower()}/haberler"
            yanit_scraping = requests.get(url_scraping, headers=headers, timeout=5, verify=False)
            if yanit_scraping.status_code == 200:
                soup = BeautifulSoup(yanit_scraping.text, 'html.parser')
                for haber in soup.find_all(['h3', 'a']):
                    baslik = haber.text.strip()
                    if len(baslik) > 20 and (temiz_isim in baslik.upper() or "KAP" in baslik.upper()):
                        if baslik not in basliklar: basliklar.append(baslik)
        except Exception: pass

        if len(basliklar) < 3:
            try:
                gelismis_sorgu = f"{temiz_isim} (site:kap.org.tr OR site:bloomberght.com)"
                url_rss = f"https://news.google.com/rss/search?q={gelismis_sorgu}&hl=tr&gl=TR&ceid=TR:tr"
                yanit_rss = requests.get(url_rss, headers=headers, timeout=5, verify=False)
                root = ET.fromstring(yanit_rss.content)
                for item in root.findall('.//item')[:5]:
                    baslik = item.find('title').text.split(" - ")[0].strip()
                    if baslik not in basliklar: basliklar.append(baslik)
            except Exception: pass
            
        basliklar = list(set(basliklar))[:5]
        if not basliklar: return 0, "Nötr / KAP Bildirimi Yok"
            
        # Gemini API Kullanımı (Eğer anahtar girildiyse)
        if api_key and len(api_key) > 10:
            try:
                haber_metni = " | ".join(basliklar)
                prompt = f"Sana verilen Türkçe haber/KAP başlıklarının hisseye kısa vadeli etkisini -100 ile +100 arası puanla. Sadece sayıyı yaz.\nHaberler: {haber_metni}"
                api_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent?key={api_key}"
                response = requests.post(api_url, headers={'Content-Type': 'application/json'}, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=10, verify=False)
                if response.status_code == 200:
                    skor_text = response.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                    skor = int(''.join(c for c in skor_text if c.isdigit() or c == '-'))
                    return skor, "🔥 KAP Pozitif (AI)" if skor > 15 else "⚠️ KAP Negatif (AI)" if skor < -15 else "⚪ Nötr (AI)"
            except Exception: pass 
        
        # Kelime Bazlı Yedek Analiz
        pozitif = ['kar', 'kâr', 'kazanc', 'büyüme', 'rekor', 'ortaklik', 'ihale', 'pozitif', 'kap']
        negatif = ['zarar', 'kayip', 'düşüş', 'iptal', 'ceza', 'dava', 'negatif', 'satis']
        skor, sayi = 0, 0
        for b in basliklar:
            b = b.lower()
            skor += (sum(1 for k in pozitif if k in b) - sum(1 for k in negatif if k in b)) * 25
            sayi += 1
        if sayi == 0: return 0, "Nötr"
        net = np.clip(skor / sayi, -100, 100)
        return net, "🔥 Pozitif Gündem" if net > 15 else "⚠️ Olumsuz Gündem" if net < -15 else "⚪ Dengeli"

    @staticmethod
    def piyasa_rejimi_kontrol():
        try:
            bist = yf.download("XU100.IS", period="1y", interval="1d", progress=False)
            if isinstance(bist.columns, pd.MultiIndex): bist.columns = bist.columns.droplevel(1)
            if not bist.empty and len(bist) > 20:
                sma_20 = bist['Close'].rolling(window=20).mean()
                sma_200 = bist['Close'].rolling(window=200).mean()
                son_kapanis = bist['Close'].iloc[-1]
                
                bist_getiri = bist['Close'].pct_change()
                if son_kapanis > sma_20.iloc[-1]:
                    return "BULL", bist_getiri
                else:
                    return "BEAR", bist_getiri
        except: pass
        return "BULL", None

# --- 3. GELİŞMİŞ TEKNİK VE MAKİNE ÖĞRENMESİ (XGB + RF) ---
class QuantModel:
    @staticmethod
    def gostergeleri_hesapla(df, bist_getiri=None):
        kapanis, hacim, yuksek, dusuk = df['Close'], df['Volume'], df['High'], df['Low']
        
        df['RSI'] = ta.momentum.RSIIndicator(close=kapanis).rsi()
        macd = ta.trend.MACD(close=kapanis)
        df['MACD_Line'] = macd.macd()
        df['MACD_Signal'] = macd.macd_signal()
        df['SMA_50'] = ta.trend.SMAIndicator(close=kapanis, window=50).sma_indicator()
        df['SMA_20'] = ta.trend.SMAIndicator(close=kapanis, window=20).sma_indicator()
        df['SMA_100'] = kapanis.rolling(window=100, min_periods=1).mean()
        df['SMA_200'] = kapanis.rolling(window=200, min_periods=1).mean()
        
        df['ATR'] = ta.volatility.AverageTrueRange(high=yuksek, low=dusuk, close=kapanis).average_true_range()
        df['ADX'] = ta.trend.ADXIndicator(high=yuksek, low=dusuk, close=kapanis).adx()
        
        # Gelişmiş İndikatörler (YENİ)
        df['VWAP'] = ta.volume.VolumeWeightedAveragePrice(high=yuksek, low=dusuk, close=kapanis, volume=hacim, window=14).volume_weighted_average_price()
        df['Chandelier_Stop'] = yuksek.rolling(window=22).max() - (df['ATR'] * 3)
        obv = ta.volume.OnBalanceVolumeIndicator(close=kapanis, volume=hacim).on_balance_volume()
        df['Para_Girisi'] = np.where(obv > obv.rolling(window=10).mean(), 1, 0)
        
        ichimoku = ta.trend.IchimokuIndicator(high=yuksek, low=dusuk)
        df['Ichi_Bulut_Ustu'] = np.where((kapanis > ichimoku.ichimoku_a()) & (kapanis > ichimoku.ichimoku_b()), 1, 0)
        
        if bist_getiri is not None:
            # Endekse hizala
            ortak_index = df.index.intersection(bist_getiri.index)
            goreceli = df.loc[ortak_index, 'Close'].pct_change() - bist_getiri.loc[ortak_index]
            df['Alfa_Skoru'] = goreceli.rolling(window=14).mean() * 100
        else:
            df['Alfa_Skoru'] = 0

        df['Z_Score'] = (kapanis - df['SMA_20']) / kapanis.rolling(window=20).std()
        df['Vol_Pct'] = df['Volume'].pct_change() 
        df['Return'] = df['Close'].pct_change()
        
        df.dropna(inplace=True)
        return df

    @staticmethod
    def ml_tahmin_et(df):
        try:
            veri = df.copy()
            # Yüzde 3 yükseliş arıyoruz
            veri['Hedef'] = np.where(veri['Close'].shift(-5) > (veri['Close'] * 1.03), 1, 0)
            veri.dropna(inplace=True)
            
            ozellikler = ['Close', 'RSI', 'MACD_Line', 'ADX', 'Z_Score', 'Vol_Pct', 'VWAP', 'Ichi_Bulut_Ustu', 'Alfa_Skoru', 'Para_Girisi']
            
            # Sızıntıyı önlemek için son 20 veriyi kırp
            guvenli_kesim = len(veri) - 20 
            if guvenli_kesim < 50: return 50.0
            
            X_train = veri.iloc[:guvenli_kesim][ozellikler]
            y_train = veri.iloc[:guvenli_kesim]['Hedef']
            bugunun_verisi = df[ozellikler].iloc[-1:]
            
            # Veri Ölçeklendirme
            scaler = StandardScaler()
            X_train_scaled = scaler.fit_transform(X_train)
            X_latest_scaled = scaler.transform(bugunun_verisi)
            
            # Çift Motor (RF + XGB)
            rf_model = RandomForestClassifier(n_estimators=100, random_state=42, max_depth=5)
            xgb_model = XGBClassifier(n_estimators=100, random_state=42, max_depth=3, eval_metric='logloss')
            
            rf_model.fit(X_train_scaled, y_train)
            xgb_model.fit(X_train_scaled, y_train)
            
            rf_prob = rf_model.predict_proba(X_latest_scaled)[0][1]
            xgb_prob = xgb_model.predict_proba(X_latest_scaled)[0][1]
            
            yukselis_olasiligi = ((rf_prob + xgb_prob) / 2) * 100
            return round(yukselis_olasiligi, 1)
        except Exception as e:
            return 50.0

# --- 4. BACKTEST (ATR, Slippage & Komisyon) ---
class Backtester:
    @staticmethod
    def gercekci_test(df, komisyon_orani, slippage_orani, config):
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
                
                stop_fiyati = gercek_alim_fiyati - (row['ATR'] * config.atr_stop)
                kar_al_fiyati = gercek_alim_fiyati + (row['ATR'] * config.atr_kar)
                pozisyon_acik = True
                
        getiri_yuzdesi = ((sermaye - baslangic) / baslangic) * 100
        win_rate = (basarili_islem / toplam_islem) if toplam_islem > 0 else 0
        ortalama_kazanc = (kazanc_toplami / basarili_islem) if basarili_islem > 0 else 1
        ortalama_kayip = (kayip_toplami / (toplam_islem - basarili_islem)) if (toplam_islem - basarili_islem) > 0 else 1
        
        return round(win_rate * 100, 1), round(getiri_yuzdesi, 1), toplam_islem, ortalama_kazanc / ortalama_kayip

# --- 5. STRATEJİ MOTORU (DÜŞEN BIÇAK KORUMALI & DİNAMİK FİYAT SEVİYELİ) ---
class QuantStrategy:
    def __init__(self, config):
        self.config = config
        self.piyasa_durumu, self.bist_getiri = DataFetcher.piyasa_rejimi_kontrol()

    def kelly_kriteri_hesapla(self, win_rate, risk_odul):
        p = win_rate / 100
        b = risk_odul
        if b <= 0 or p <= 0: return 0
        kelly_yuzdesi = (p * (b + 1) - 1) / b
        return min(max(0, kelly_yuzdesi / 2), 0.10) 

    def analiz_et(self, hisse_kodu):
        gunluk, _, temel, haber_skoru, haber_durumu = DataFetcher.veri_indir(hisse_kodu, self.config.api_key)
        if gunluk is None: return None
            
        gunluk = QuantModel.gostergeleri_hesapla(gunluk, self.bist_getiri)
        if gunluk.empty: return None
            
        win_rate, getiri, islem_sayisi, risk_odul = Backtester.gercekci_test(gunluk, self.config.komisyon, self.config.slippage, self.config)
        ml_olasilik = QuantModel.ml_tahmin_et(gunluk)
        
        son_gun = gunluk.iloc[-1]
        fiyat = float(son_gun['Close'])
        rsi = float(son_gun['RSI'])
        sma_200 = float(son_gun['SMA_200'])
        sma_100 = float(son_gun['SMA_100'])
        vwap = float(son_gun['VWAP'])
        atr = float(son_gun['ATR'])
        
        # Dinamik Hesaplamalar (Chandelier tabanlı İzleyen Stop)
        al_fiyati = fiyat 
        stop_fiyati = float(son_gun['Chandelier_Stop'])
        if stop_fiyati >= fiyat: stop_fiyati = fiyat - (atr * 1.5)
        kar_fiyati = fiyat + (atr * self.config.atr_kar)
        
        skor = 50 
        nedenler = []
        
        if fiyat < sma_200:
            fark_yuzde = ((sma_200 - fiyat) / sma_200) * 100
            if fark_yuzde > 20: 
                skor -= 40; nedenler.append("KRONİK DÜŞÜŞ")
            else:
                skor -= 15; nedenler.append("Ayı Trendi")
        elif fiyat > sma_200 and fiyat > sma_100:
            skor += 10; nedenler.append("Güçlü Trend")

        if fiyat > vwap:
            skor += 10; nedenler.append("VWAP Üstü Güç")
            
        if son_gun['Para_Girisi'] == 1:
            skor += 5; nedenler.append("Para Girişi (OBV)")
            
        if son_gun['Ichi_Bulut_Ustu'] == 1:
            skor += 10; nedenler.append("Bulut Üstü (Ichi)")

        if ml_olasilik > 60: 
            skor += 15; nedenler.append(f"AI Boğa (%{ml_olasilik})")
        elif ml_olasilik < 40: 
            skor -= 10
            
        if son_gun['MACD_Line'] > son_gun['MACD_Signal']: skor += 5
        else: skor -= 10
            
        if win_rate > 55: skor += 10
        if son_gun['Z_Score'] > 2.0: 
            skor -= 15; nedenler.append("Aşırı Şişkin (Z)")
            
        if haber_skoru > 15:
            skor += 15; nedenler.append("Güçlü Gündem/KAP")
        elif haber_skoru < -15:
            skor -= 20; nedenler.append("Riskli Gündem")
        
        if self.piyasa_durumu == "BEAR":
            skor -= 10; nedenler.append("Endeks Baskısı")
        
        skor = max(0, min(skor, 100))
        
        if skor >= 75: karar = "🔥 KESİN AL"
        elif skor >= 60: karar = "🟢 POTANSİYEL AL"
        elif skor <= 40 or rsi > self.config.rsi_sat: karar = "🔴 SAT / RİSKLİ"
        else: karar = "⚪ İZLEMEDE / NÖTR"
            
        kelly_orani = self.kelly_kriteri_hesapla(win_rate, risk_odul)
        if self.piyasa_durumu == "BEAR" or haber_skoru < -15 or fiyat < sma_200: 
            kelly_orani = kelly_orani / 2 
            
        lot_sayisi = int((self.config.sermaye * kelly_orani) / fiyat) if "AL" in karar else 0
            
        return {
            "Hisse": hisse_kodu.replace(".IS", ""), 
            "Karar": karar, 
            "AI Tahmini": f"%{ml_olasilik}",
            "Skor": f"%{skor}",
            "Gündem": haber_durumu,
            "Fiyat (₺)": round(fiyat, 2), 
            "Dinamik Al (₺)": round(al_fiyati, 2),
            "Stop-Loss (₺)": round(stop_fiyati, 2),
            "Kar Al (₺)": round(kar_fiyati, 2),
            "Kelly Lotu": lot_sayisi,
            "Win Rate": f"%{win_rate}",
            "Nedenler": " | ".join(nedenler[:3]) if nedenler else "Yatay / Stabil",
            "Grafik_Verisi": gunluk[['Open', 'High', 'Low', 'Close', 'SMA_50', 'SMA_200', 'VWAP']].tail(65)
        }

# --- 6. ARAYÜZ (UI) ---
def ui_olustur():
    st.title("🧠 YZ Destekli Katılım Fonu Botu v9.0 PRO")
    st.markdown("XGBoost + Random Forest Motorları, Gemini Haber Analizi, Chandelier İzleyen Stop ve VWAP Entegre Edildi.")
    st.markdown("---")

    # --- YAN MENÜ ---
    st.sidebar.markdown("### 🏦 Kurumsal Parametreler")
    toplam_sermaye = st.sidebar.number_input("Yönetilen Bakiye (₺)", min_value=10000, value=100000)
    komisyon = st.sidebar.number_input("Komisyon Oranı (%)", value=0.1, step=0.05) / 100
    slippage = st.sidebar.number_input("Tahmini Kayma (%)", value=0.2, step=0.1) / 100
    
    st.sidebar.markdown("### 🤖 Yapay Zeka Anahtarı")
    api_key_input = st.sidebar.text_input("Gemini API Key (Haber Analizi İçin)", type="password", help="KAP bildirimlerini ve haberleri analiz etmek için kullanılır. Boş bırakılabilir.")

    config = BotConfig(60, 75, 1.5, 3.0, toplam_sermaye, komisyon, slippage, api_key_input)
    strateji = QuantStrategy(config)

    # Piyasa Rejimi Durum Çubuğu
    if strateji.piyasa_durumu == "BULL":
        st.sidebar.success("📊 BIST Genel Trendi: BOĞA (Güvenli)")
    else:
        st.sidebar.warning("⚠️ BIST Genel Trendi: AYI (Baskılı)")

    # --- 1. MANUEL TARAMA BÖLÜMÜ ---
    st.sidebar.markdown("### 🔍 Manuel Tarama (Katılım Uyumlu)")
    varsayilan_hisseler = "ASELS\nMPARK\nYUNSA\nBIMAS\nDOAS\nFROTO"
    hisseler_metin = st.sidebar.text_area("Taranacak Hisseler:", varsayilan_hisseler, height=140)

    if st.sidebar.button("🚀 Manuel Analizi Başlat", use_container_width=True):
        hisse_listesi = [h.strip().upper() + ".IS" for h in hisseler_metin.split("\n") if h.strip()]
        
        ilerleme = st.progress(0)
        sonuclar = []
        
        with ThreadPoolExecutor(max_workers=4) as executor:
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
            st.error("Veri işlenemedi veya internet bağlantısı yok.")

    # --- 2. OTOMATİK FIRSAT RADARI ---
    st.markdown("### 📡 Otomatik Fırsat Radarı (Sadece Katılım Endeksi)")
    st.markdown("Çift Motorlu Yapay Zeka (XGB+RF), VWAP ve Ichimoku bulutları üzerinden eşzamanlı BIST Katılım (XK100) taraması yapar.")

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
        
        st.info("Eşzamanlı YZ Taraması Aktif. Modeller eğitiliyor ve haberler taranıyor, lütfen bekleyin...")
        
        bulunan_firsatlar = []
        
        # CPU çekirdeklerine çok yüklenmemek için max_workers 6 yapıldı
        with ThreadPoolExecutor(max_workers=6) as executor:
            radar_sonuclari = executor.map(strateji.analiz_et, bist_katilim_hisseler)
            for sonuc in radar_sonuclari:
                if sonuc and ("AL" in sonuc["Karar"]):
                    bulunan_firsatlar.append(sonuc)
        
        if bulunan_firsatlar:
            st.success(f"🚨 Tarama Tamamlandı: YZ ve Temel Analiz Kriterlerine Uyan {len(bulunan_firsatlar)} Adet Sinyal Yakalandı!")
            
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
                        <p style="font-size: 14px; margin: 3px 0;"><b>🔵 Fiyat:</b> {firsat['Fiyat (₺)']} ₺</p>
                        <p style="font-size: 14px; margin: 3px 0; color: #ff8a80;"><b>🔴 İzleyen Stop:</b> {firsat['Stop-Loss (₺)']} ₺</p>
                        <p style="font-size: 14px; margin: 3px 0; color: #b9f6ca;"><b>🟢 Kâr Al Target:</b> {firsat['Kar Al (₺)']} ₺</p>
                        <hr style="border-color: #4caf50; margin-bottom: 8px; margin-top: 8px;">
                        <p style="font-size: 13px; margin: 2px 0;"><b>Gündem:</b> {firsat['Gündem']}</p>
                        <p style="font-size: 13px; margin: 2px 0;"><b>AI (RF+XGB):</b> {firsat['AI Tahmini']}</p>
                        <p style="font-size: 13px; margin: 2px 0;"><b>Neden:</b> {firsat['Nedenler']}</p>
                        <p style="font-size: 13px; margin: 2px 0;"><b>Kelly Lotu:</b> {firsat['Kelly Lotu']} Lot</p>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    with st.expander("📊 Gelişmiş Grafiği İncele"):
                        fig = cizgi_grafik_olustur(
                            firsat['Grafik_Verisi'], 
                            firsat['Hisse'], 
                            firsat['Dinamik Al (₺)'], 
                            firsat['Stop-Loss (₺)'], 
                            firsat['Kar Al (₺)']
                        )
                        st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})
                    
                    st.markdown("<br>", unsafe_allow_html=True)
        else:
            st.warning("YZ Modelleri, VWAP veya uzun vadeli trend korumasından (SMA200) geçebilen güvenli bir fırsat bulunamadı.")

if __name__ == "__main__":
    ui_olustur()
