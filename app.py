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
import xml.etree.ElementTree as ET

# --- GEMINI ENTEGRASYONU ---
try:
    import google.generativeai as genai
except ImportError:
    genai = None

warnings.filterwarnings('ignore')
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- SAYFA AYARLARI ---
st.set_page_config(page_title="Ultimate Quant Bot v8.5 (Gemini Mod)", page_icon="🤖", layout="wide")

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

# --- GRAFİK ÇİZİCİ MODÜL (YENİ) ---
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
    
    # Akıllı Emir Seviyeleri
    fig.add_hline(y=al_fiyati, line_dash="dot", line_color="#4fc3f7", annotation_text="Al", annotation_position="bottom left")
    fig.add_hline(y=stop, line_dash="dash", line_color="#ef5350", annotation_text="Stop", annotation_position="bottom right")
    fig.add_hline(y=kar_al, line_dash="dash", line_color="#66bb6a", annotation_text="Kar Al", annotation_position="top right")

    fig.update_layout(
        margin=dict(l=10, r=10, t=30, b=10),
        height=300,
        xaxis_rangeslider_visible=False,
        template="plotly_dark",
        title=dict(text=f"{hisse} - Teknik Görünüm (Son 3 Ay)", font=dict(size=14, color="#a5d6a7")),
        showlegend=False,
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)'
    )
    return fig

# --- 2. HAKİKİ QUANTAMENTAL VERİ VE DUYGU ANALİZİ (HABER DESTEKLİ) ---
class DataFetcher:
    @staticmethod
    @st.cache_data(ttl=1200, show_spinner=False)
    def veri_indir(hisse_kodu):
        try:
            ticker = yf.Ticker(hisse_kodu)
            gunluk_veri = ticker.history(period="2y", interval="1d")
            
            if not gunluk_veri.empty and len(gunluk_veri) >= 60:
                haftalik_veri = ticker.history(period="5y", interval="1wk")
                info = ticker.info
                temel_veriler = {
                    'fk': info.get('trailingPE', None),
                    'pd_dd': info.get('priceToBook', None),
                    'roe': info.get('returnOnEquity', None)
                }
                
                # DEĞİŞİKLİK BURADA: Yeni sistem ticker nesnesi değil hisse adını istiyor
                haber_skoru, haber_durumu = DataFetcher.haber_duygu_analizi(hisse_kodu)
                return gunluk_veri, haftalik_veri, temel_veriler, 0, haber_skoru, haber_durumu
        except Exception as e:
            logging.warning(f"YFinance hatası ({hisse_kodu}). Yedek sisteme geçiliyor...")

        # --- İKİNCİL DENEME (FALLBACK): İŞ YATIRIM API ---
        try:
            sembol = hisse_kodu.replace(".IS", "")
            bitis_tarihi = datetime.datetime.now().strftime("%d-%m-%Y")
            baslangic_tarihi = (datetime.datetime.now() - datetime.timedelta(days=730)).strftime("%d-%m-%Y")
            
            url = f"https://www.isyatirim.com.tr/_layouts/15/IsYatirim.Website/Common/Data.aspx/HisseTekil?hisse={sembol}&startdate={baslangic_tarihi}&enddate={bitis_tarihi}"
            headers = {'User-Agent': 'Mozilla/5.0'}
            
            response = requests.get(url, headers=headers, timeout=10)
            veri_json = response.json()
            
            if 'value' in veri_json and veri_json['value']:
                df = pd.DataFrame(veri_json['value'])
                df['Date'] = pd.to_datetime(df['HGDG_TARIH'], format='%d-%m-%Y')
                df.set_index('Date', inplace=True)
                
                df.rename(columns={'KAPANIS': 'Close', 'MAX': 'High', 'MIN': 'Low', 'ISLEM_MIKTARI': 'Volume'}, inplace=True)
                df['Open'] = df['Close'].shift(1).fillna(df['Close'])
                
                gunluk_veri = df[['Open', 'High', 'Low', 'Close', 'Volume']].astype(float)
                
                if len(gunluk_veri) < 60:
                    return None, None, None, None, None, None
                    
                haftalik_veri = gunluk_veri.resample('W').agg({
                    'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'
                })
                
                temel_veriler = {'fk': None, 'pd_dd': None, 'roe': None}
                return gunluk_veri, haftalik_veri, temel_veriler, 0, 0, "Yedek Motor (Haber Yok)"
                
        except Exception as e:
            logging.error(f"Tüm veri kaynakları başarısız oldu ({hisse_kodu}): {e}")
            
        return None, None, None, None, None, None

    @staticmethod
    def haber_duygu_analizi(hisse_kodu):
        temiz_isim = hisse_kodu.replace(".IS", "")
        try:
            # 1. Google News RSS üzerinden Türkçe haberleri çek
            url = f"https://news.google.com/rss/search?q={temiz_isim}+hisse+ihale+kap+temettü+sözleşme&hl=tr&gl=TR&ceid=TR:tr"
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
            yanit = requests.get(url, headers=headers, timeout=5)
            root = ET.fromstring(yanit.content)

            basliklar = []
            for item in root.findall('.//item')[:5]:
                baslik = item.find('title').text
                if baslik: basliklar.append(baslik)

            if not basliklar:
                return 0, "Nötr / Haber Yok"

            # 2. Gemini Yapay Zeka ile Analiz
            if genai:
                try:
                    haber_metni = " | ".join(basliklar)
                    model = genai.GenerativeModel('gemini-1.5-flash')
                    prompt = (
                        f"Sen Borsa İstanbul uzmanısın. Şu Türkçe haber başlıklarının "
                        f"{temiz_isim} hissesine kısa vadeli etkisini -100 ile +100 arasında "
                        f"tek bir tam sayı olarak puanla. Sadece sayıyı yaz.\nHaberler: {haber_metni}"
                    )

                    response = model.generate_content(prompt)
                    skor_text = response.text.strip()
                    temiz_skor_str = ''.join(c for c in skor_text if c.isdigit() or c == '-')
                    skor = int(temiz_skor_str)

                    if skor > 15: durum = "🔥 Gemini: Pozitif Beklenti"
                    elif skor < -15: durum = "⚠️ Gemini: Negatif Beklenti"
                    else: durum = "⚪ Gemini: Nötr"
                    return skor, durum
                except Exception as e:
                    pass # Gemini hatası olursa klasik sisteme geç

            # 3. Gemini Yoksa veya Hata Verirse: Klasik Kelime Analizi (Yedek)
            pozitif_kelimeler = ['kar', 'kâr', 'kazanc', 'kazanç', 'buyume', 'büyüme', 'rekor', 'ihracat', 'anlasma', 'anlaşma', 'ortaklik', 'ortaklık', 'pozitif', 'kap', 'buy', 'temettu']
            negatif_kelimeler = ['zarar', 'kayip', 'kayıp', 'dusus', 'düşüş', 'risk', 'iptal', 'ceza', 'dava', 'sorusturma', 'soruşturma', 'negatif', 'sell']

            toplam_skor = 0
            for baslik in basliklar:
                baslik = baslik.lower()
                pos_puan = sum(1 for kelime in pozitif_kelimeler if kelime in baslik)
                neg_puan = sum(1 for kelime in negatif_kelimeler if kelime in baslik)
                toplam_skor += (pos_puan - neg_puan) * 25

            net_duygu = np.clip(toplam_skor / len(basliklar), -100, 100)

            if net_duygu > 15: return round(net_duygu, 1), "🔥 Pozitif Gündem"
            elif net_duygu < -15: return round(net_duygu, 1), "⚠️ Olumsuz Gündem"
            else: return 0, "⚪ Dengeli / Nötr"

        except Exception as e:
            return 0, "Haber Filtresi Devre Dışı"

    @staticmethod
    @st.cache_data(ttl=3600, show_spinner=False)
    def piyasa_rejimi_kontrol():
        try:
            bist = yf.Ticker("XU100.IS")
            df = bist.history(period="1y", interval="1d")
            if not df.empty and len(df) > 200:
                sma_200 = ta.trend.SMAIndicator(close=df['Close'], window=200).sma_indicator()
                son_kapanis = df['Close'].iloc[-1]
                son_sma200 = sma_200.iloc[-1]
                return "BULL" if son_kapanis > son_sma200 else "BEAR"
        except:
            pass
        return "BULL"

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
        
        df['SMA_100'] = kapanis.rolling(window=100, min_periods=1).mean()
        df['SMA_200'] = kapanis.rolling(window=200, min_periods=1).mean()
        
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
            
            ozellikler = ['RSI', 'MACD_Line', 'ADX', 'Z_Score', 'Vol_Pct', 'Return']
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

    def kelly_kriteri_hesapla(self, win_rate, risk_odul):
        p = win_rate / 100
        b = risk_odul
        if b <= 0 or p <= 0: return 0
        kelly_yuzdesi = (p * (b + 1) - 1) / b
        return min(max(0, kelly_yuzdesi / 2), 0.10) 

    def analiz_et(self, hisse_kodu):
        gunluk, haftalik, temel, duygu_skoru, haber_skoru, haber_durumu = DataFetcher.veri_indir(hisse_kodu)
        if gunluk is None: return None
            
        gunluk = QuantModel.gostergeleri_hesapla(gunluk)
        if gunluk.empty: return None
            
        win_rate, getiri, islem_sayisi, risk_odul = Backtester.gercekci_test(gunluk, self.config.komisyon, self.config.slippage, self.config)
        ml_olasilik = QuantModel.ml_tahmin_et(gunluk)
        
        son_gun = gunluk.iloc[-1]
        fiyat = float(son_gun['Close'])
        rsi = float(son_gun['RSI'])
        sma_200 = float(son_gun['SMA_200'])
        sma_100 = float(son_gun['SMA_100'])
        atr = float(son_gun['ATR'])
        
        # Dinamik Hesaplamalar
        al_fiyati = fiyat 
        stop_fiyati = al_fiyati - (atr * self.config.atr_stop)
        kar_fiyati = al_fiyati + (atr * self.config.atr_kar)
        
        skor = 50 
        nedenler = []
        
        if fiyat < sma_200:
            fark_yuzde = ((sma_200 - fiyat) / sma_200) * 100
            if fark_yuzde > 20: 
                skor -= 40 
                nedenler.append("KRONİK DÜŞÜŞ (Zehirli)")
            else:
                skor -= 15
                nedenler.append("Ayı Trendi (SMA200 Altı)")
        elif fiyat > sma_200 and fiyat > sma_100:
            skor += 15
            nedenler.append("Güçlü Trend (SMA200 Üstü)")

        if ml_olasilik > 65: 
            skor += 10; nedenler.append(f"AI Boğa (%{ml_olasilik})")
        elif ml_olasilik < 40: 
            skor -= 10
            
        if son_gun['MACD_Line'] > son_gun['MACD_Signal']: 
            skor += 10
        else:
            skor -= 10
            
        if rsi < 40 and fiyat > sma_200: 
            skor += 10; nedenler.append("Trend İçi Dip Fırsatı")
            
        if win_rate > 55: skor += 10
        if son_gun['Z_Score'] > 2.0: 
            skor -= 15; nedenler.append("Aşırı Şişkinlik (Z)")
            
        if haber_skoru > 15:
            skor += 15; nedenler.append("Güçlü KAP/Haber")
        elif haber_skoru < -15:
            skor -= 20; nedenler.append("Riskli Gündem")
        
        piyasa = DataFetcher.piyasa_rejimi_kontrol()
        if piyasa == "BEAR":
            skor -= 10; nedenler.append("BIST Endeks Baskısı")
        
        skor = max(0, min(skor, 100))
        
        if skor >= 75: karar = "🔥 KESİN AL"
        elif skor >= 60: karar = "🟢 POTANSİYEL AL"
        elif skor <= 40 or rsi > self.config.rsi_sat: karar = "🔴 SAT / RİSKLİ"
        else: karar = "⚪ İZLEMEDE / NÖTR"
            
        kelly_orani = self.kelly_kriteri_hesapla(win_rate, risk_odul)
        if piyasa == "BEAR" or haber_skoru < -15 or fiyat < sma_200: 
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
            "Grafik_Verisi": gunluk[['Open', 'High', 'Low', 'Close', 'SMA_50', 'SMA_200']].tail(65) # Son 3 aylık veriyi grafiğe gönder
        }

# --- 6. ARAYÜZ (UI) ---
def ui_olustur():
    st.title("🧠 YZ Destekli Katılım Fonu Botu v8.5")
    st.markdown("İnteraktif Çizim Grafikleri (Plotly), Trend Haritaları ve Gemini RSS Haber Okuyucu Sisteme Entegre Edildi.")
    st.markdown("---")

    # API KEY YAPILANDIRMASI
    if 'GEMINI_API_KEY' in st.secrets and genai:
        genai.configure(api_key=st.secrets['GEMINI_API_KEY'])

    # --- YAN MENÜ ---
    st.sidebar.markdown("### 🏦 Kurumsal Parametreler")
    toplam_sermaye = st.sidebar.number_input("Yönetilen Bakiye (₺)", min_value=10000, value=100000)
    komisyon = st.sidebar.number_input("Komisyon Oranı (%)", value=0.1, step=0.05) / 100
    slippage = st.sidebar.number_input("Tahmini Kayma (%)", value=0.2, step=0.1) / 100

    config = BotConfig(60, 75, 1.5, 3.0, toplam_sermaye, komisyon, slippage)
    strateji = QuantStrategy(config)

    # Piyasa Rejimi Durum Çubuğu
    piyasa_durumu = DataFetcher.piyasa_rejimi_kontrol()
    if piyasa_durumu == "BULL":
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
            # Sadece görüntüleme tablosu için gereksiz kolonu (grafik verisini) uçur
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

    # --- 2. OTOMATİK FIRSAT RADARI ---
    st.markdown("### 📡 Otomatik Fırsat Radarı (Sadece Katılım Endeksi)")
    st.markdown("Sistem BIST 100 Katılım (XK100) tahtalarını eşzamanlı tarar. İnteraktif Plotly Grafikleriyle birlikte sunar.")

    if st.button("🔍 Katılım Endeksi Eşzamanlı Radarını Çalıştır", use_container_width=True):
        bist_katilim_hisseler = [
            "ALBRK.IS", "ALFAS.IS", "ASELS.IS", "ASTOR.IS", "BIMAS.IS", "BRSAN.IS", 
            "CANTE.IS", "CIMSA.IS", "CWENE.IS", "DOAS.IS", "EGEEN.IS", "EKGYO.IS", 
            "ENJSA.IS", "ENKAI.IS", "EUPWR.IS", "FROTO.IS", "GESAN.IS", "GWIND.IS", 
            "HEKTS.IS", "IPEKE.IS", "JANTS.IS", "KCAER.IS", "KMPUR.IS", "KONTR.IS", 
            "KORDS.IS", "KOZAA.IS", "KOZAL.IS", "KRDMD.IS", "MIATK.IS", "MPARK.IS", 
            "OTKAR.IS", "OYAKC.IS", "QUAGR.IS", "SASA.IS", "SMRTG.IS", "TTRAK.IS", 
            "TUKAS.IS", "VESBE.IS", "YEOTK.IS", "YUNSA.IS"
        ]
        
        st.info("Eşzamanlı Tarama Aktif. Grafik Çizgileri ve Akıllı Emir Seviyeleri Hesaplanıyor...")
        
        bulunan_firsatlar = []
        
        with ThreadPoolExecutor(max_workers=8) as executor:
            radar_sonuclari = executor.map(strateji.analiz_et, bist_katilim_hisseler)
            for sonuc in radar_sonuclari:
                if sonuc and ("AL" in sonuc["Karar"]):
                    bulunan_firsatlar.append(sonuc)
        
        if bulunan_firsatlar:
            st.success(f"🚨 Tarama Tamamlandı: Sağlıklı Kriterlere Uyan {len(bulunan_firsatlar)} Adet Sinyal Yakalandı!")
            
            # Grafikler daha rahat görünsün diye 4'lü sütundan 3'lü sütun yapısına geçtik
            sutunlar = st.columns(min(len(bulunan_firsatlar), 3))
            for idx, firsat in enumerate(bulunan_firsatlar):
                with sutunlar[idx % 3]:
                    renk_kodu = "#1e4620" if "KESİN" in firsat["Karar"] else "#2e7d32"
                    
                    # Kart Tasarımı
                    st.markdown(f"""
                    <div style="border: 2px solid #2e7d32; border-top-left-radius: 10px; border-top-right-radius: 10px; padding: 15px; background-color: {renk_kodu}; color: white; margin-bottom: 0px;">
                        <h2 style="text-align: center; color: #4caf50; margin-top: 0;">{firsat['Hisse']}</h2>
                        <h1 style="text-align: center; margin: 0;">{firsat['Skor']}</h1>
                        <p style="text-align: center; font-size: 15px; background-color: #1b5e20; border-radius: 5px; padding: 3px;"><b>{firsat['Karar']}</b></p>
                        <hr style="border-color: #4caf50; margin-bottom: 8px; margin-top: 8px;">
                        <p style="font-size: 14px; margin: 3px 0;"><b>🔵 Dinamik Al:</b> {firsat['Dinamik Al (₺)']} ₺</p>
                        <p style="font-size: 14px; margin: 3px 0; color: #ff8a80;"><b>🔴 Stop-Loss:</b> {firsat['Stop-Loss (₺)']} ₺</p>
                        <p style="font-size: 14px; margin: 3px 0; color: #b9f6ca;"><b>🟢 Kâr Al Target:</b> {firsat['Kar Al (₺)']} ₺</p>
                        <hr style="border-color: #4caf50; margin-bottom: 8px; margin-top: 8px;">
                        <p style="font-size: 13px; margin: 2px 0;"><b>Gündem:</b> {firsat['Gündem']}</p>
                        <p style="font-size: 13px; margin: 2px 0;"><b>Yapay Zeka:</b> {firsat['AI Tahmini']}</p>
                        <p style="font-size: 13px; margin: 2px 0;"><b>Kelly Lotu:</b> {firsat['Kelly Lotu']} Lot</p>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    # Grafiği İncele (Genişletilebilir Panel)
                    with st.expander("📊 Grafiği İncele"):
                        fig = cizgi_grafik_olustur(
                            firsat['Grafik_Verisi'], 
                            firsat['Hisse'], 
                            firsat['Dinamik Al (₺)'], 
                            firsat['Stop-Loss (₺)'], 
                            firsat['Kar Al (₺)']
                        )
                        st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})
                    
                    st.markdown("<br>", unsafe_allow_html=True) # Kartlar arasına boşluk
        else:
            st.warning("Kurumsal risk filtrelerinden ve uzun vadeli trend (SMA200) korumasından geçebilen bir fırsat bulunamadı.")

if __name__ == "__main__":
    ui_olustur()
