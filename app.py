import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import ta
import warnings
import logging
import requests
from bs4 import BeautifulSoup
import datetime
import plotly.graph_objects as go
from concurrent.futures import ThreadPoolExecutor

warnings.filterwarnings('ignore')
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- SAYFA AYARLARI ---
st.set_page_config(page_title="Ultimate Quant Bot v11.1 - Risk Optimizasyonlu", page_icon="🎯", layout="wide")

# --- CSS VE TASARIM ---
st.markdown("""
    <style>
    .haber-satiri { background-color: #121212; padding: 10px; border-radius: 5px; border-left: 3px solid #29b6f6; margin-bottom: 8px; }
    .kap-satiri { background-color: #121212; padding: 10px; border-radius: 5px; border-left: 3px solid #ffa726; margin-bottom: 8px; }
    .haber-baslik { color: #ffffff; font-size: 14px; font-weight: bold; text-decoration: none; }
    .haber-baslik:hover { color: #29b6f6; }
    .haber-detay { color: #9e9e9e; font-size: 11px; margin-bottom: 3px; }
    </style>
""", unsafe_allow_html=True)

# --- 0. GÜVENLİK VE OTURUM YÖNETİMİ ---
def sifre_kontrol():
    if "giris_basarili" not in st.session_state:
        st.session_state["giris_basarili"] = False

    if not st.session_state["giris_basarili"]:
        st.markdown("<h1 style='text-align: center;'>🔒 Sistem Erişimi</h1>", unsafe_allow_html=True)
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

# --- 1. YAPILANDIRMA VE LİSTELER ---
class BotConfig:
    def __init__(self, rsi_asiri_satim, rsi_asiri_alim, sermaye, atr_stop_carpan, risk_odul_orani):
        self.rsi_asiri_satim = rsi_asiri_satim
        self.rsi_asiri_alim = rsi_asiri_alim
        self.sermaye = sermaye
        self.atr_stop_carpan = atr_stop_carpan  # Risk yönetimi için ATR çarpanı (Örn: 1.5)
        self.risk_odul_orani = risk_odul_orani  # En az 2.0 (Alınan riskin 2 katı ödül)

KATILIM_LISTESI = [
    "AKFYE", "ALBRK", "ALFAS", "ALKLC", "ALTNY", "ALVES", "ARDYZ", "ASELS",
    "ATATP", "BEGYO", "BERA", "BIENY", "BIMAS", "BINBN", "BINHO", "BMSTL",
    "BRISA", "BSOKE", "CANTE", "CEMTS", "CEMZY", "CIMSA", "CVKMD", "CWENE",
    "DAPGM", "DCTTR", "DOFRB", "EFOR", "EGGUB", "EKGYO", "ENJSA", "EREGL",
    "EUPWR", "FONET", "FORMT", "FZLGY", "GENIL", "GENTS", "GEREL", "GESAN",
    "GLRMK", "GOKNR", "GRSEL", "GRTHO", "GUBRF", "GUNDG", "HRKET", "IHLAS",
    "IHLGM", "IMASM", "ISDMR", "IZFAS", "JANTS", "KARSN", "KATMR", "KBORU",
    "KCAER", "KLSER", "KMPUR", "KOPOL", "KRDMD", "KTLEV", "KZBGY", "LMKDC",
    "LOGO", "MAGEN", "MAREN", "MAVI", "MEGMT", "MERCN", "MEYSU", "MOPAS",
    "MPARK", "NETCD", "NTGAZ", "OBAMS", "ORGE", "OZATD", "PASEU", "PETKM",
    "POLHO", "QUAGR", "RALYH", "RGYAS", "SAFKR", "SARKY", "SAYAS", "SDTTR",
    "SELEC", "SNGYO", "SRVGY", "SUNTK", "SURGY", "TARKM", "TEZOL", "TKFEN",
    "TKNSA", "TUKAS", "TUPRS", "TUREX", "USAK", "YEOTK", "YIGIT", "YUNSA",
    "ZERGY"
]

# --- 2. İSTİHBARAT MOTORU ---
@st.cache_data(ttl=900, show_spinner=False)
def haberleri_kazi(sorgu, limit=3):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    url = f"https://news.google.com/search?q={sorgu}&hl=tr&gl=TR&ceid=TR:tr"
    try:
        res = requests.get(url, headers=headers, timeout=5)
        soup = BeautifulSoup(res.text, 'lxml')
        makaleler = []
        for makale in soup.find_all('article', limit=limit):
            baslik_etiketi = makale.find('a', class_='JtKRv')
            if not baslik_etiketi: continue
            baslik = baslik_etiketi.text
            link = "https://news.google.com" + baslik_etiketi['href'][1:]
            kaynak_etiketi = makale.find('div', class_='vr1ype')
            kaynak = kaynak_etiketi.text if kaynak_etiketi else "Medya"
            zaman_etiketi = makale.find('time')
            zaman = zaman_etiketi.text if zaman_etiketi else "Yakın Zaman"
            makaleler.append({"baslik": baslik, "link": link, "kaynak": kaynak, "zaman": zaman})
        return makaleler
    except: return []

# --- 3. VERİ YÖNETİMİ ---
class DataFetcher:
    @staticmethod
    def is_yatirim_api_sorgula(sembol, periyot_gun=730):
        try:
            sembol = sembol.replace(".IS", "").upper()
            bitis_tarihi = datetime.datetime.now().strftime("%d-%m-%Y")
            baslangic_tarihi = (datetime.datetime.now() - datetime.timedelta(days=periyot_gun)).strftime("%d-%m-%Y")
            url = f"https://www.isyatirim.com.tr/_layouts/15/IsYatirim.Website/Common/Data.aspx/HisseTekil?hisse={sembol}&startdate={baslangic_tarihi}&enddate={bitis_tarihi}"
            headers = {'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'}
            response = requests.get(url, headers=headers, timeout=8)
            if response.status_code != 200: return None
            veri_json = response.json()
            if 'value' in veri_json and veri_json['value']:
                df = pd.DataFrame(veri_json['value'])
                df['Date'] = pd.to_datetime(df['HGDG_TARIH'], format='%d-%m-%Y')
                df.set_index('Date', inplace=True)
                df.rename(columns={'KAPANIS': 'Close', 'MAX': 'High', 'MIN': 'Low', 'ISLEM_MIKTARI': 'Volume'}, inplace=True)
                df['Open'] = df['Close'].shift(1).fillna(df['Close'])
                gunluk_veri = df[['Open', 'High', 'Low', 'Close', 'Volume']].astype(float)
                if len(gunluk_veri) < 60: return None
                return gunluk_veri
            return None
        except: return None

    @staticmethod
    def yfinance_api_sorgula(sembol):
        try:
            if not sembol.endswith(".IS"): sembol = f"{sembol}.IS"
            df = yf.Ticker(sembol).history(period="2y", interval="1d")
            if not df.empty and len(df) >= 60:
                gunluk_veri = df[['Open', 'High', 'Low', 'Close', 'Volume']].astype(float)
                gunluk_veri.index = gunluk_veri.index.tz_localize(None).normalize()
                return gunluk_veri
            return None
        except: return None

    @staticmethod
    def veri_indir(hisse_kodu):
        gunluk_veri = DataFetcher.is_yatirim_api_sorgula(hisse_kodu)
        if gunluk_veri is not None: return gunluk_veri, "İş Yatırım API"
        gunluk_veri = DataFetcher.yfinance_api_sorgula(hisse_kodu)
        if gunluk_veri is not None: return gunluk_veri, "Yedek API (Yahoo)"
        return None, "Bağlantı Hatası"

    @staticmethod
    @st.cache_data(ttl=3600, show_spinner=False)
    def endeks_verisi_getir():
        veri = DataFetcher.is_yatirim_api_sorgula("XU100", 365)
        if veri is None: veri = DataFetcher.yfinance_api_sorgula("XU100.IS")
        return veri

    @staticmethod
    @st.cache_data(ttl=3600, show_spinner=False)
    def piyasa_rejimi_kontrol():
        df = DataFetcher.endeks_verisi_getir()
        if df is not None and not df.empty and len(df) > 200:
            sma_200 = ta.trend.SMAIndicator(close=df['Close'], window=200).sma_indicator()
            return "BULL" if df['Close'].iloc[-1] > sma_200.iloc[-1] else "BEAR"
        return "BULL"

# --- 4. TEKNİK ANALİZ VE RİSK YÖNETİMİ ---
class QuantModel:
    @staticmethod
    def gostergeleri_hesapla(df):
        kapanis, yuksek, dusuk, hacim = df['Close'], df['High'], df['Low'], df['Volume']
        df['RSI'] = ta.momentum.RSIIndicator(close=kapanis).rsi()
        df['SMA_50'] = ta.trend.SMAIndicator(close=kapanis, window=50).sma_indicator()
        df['SMA_200'] = ta.trend.SMAIndicator(close=kapanis, window=200).sma_indicator()
        df['BB_Lower'] = ta.volatility.BollingerBands(close=kapanis, window=20, window_dev=2).bollinger_lband()
        df['ATR'] = ta.volatility.AverageTrueRange(high=yuksek, low=dusuk, close=kapanis).average_true_range()
        df['Hacim_Ort'] = hacim.rolling(window=20).mean()
        df.dropna(inplace=True)
        return df

class Backtester:
    @staticmethod
    def vektor_gercekci_test(df):
        if df is None or len(df) < 50: return 0
        alis_sinyalleri = (df['Close'] < df['SMA_200']) & (df['RSI'] < 40)
        df['Sinyal'] = np.where(alis_sinyalleri, 1, 0)
        df['Gelecek_Getiri'] = df['Close'].shift(-20) / df['Close'] - 1
        basarili_islemler = df[df['Sinyal'] == 1]['Gelecek_Getiri'] > 0
        return round(basarili_islemler.mean() * 100 if not basarili_islemler.empty else 50.0, 1)

# --- 5. STRATEJİ MOTORU (RİSK KONTROLLÜ) ---
class QuantStrategy:
    def __init__(self, config):
        self.config = config

    def analiz_et(self, hisse_kodu):
        gunluk, kaynak = DataFetcher.veri_indir(hisse_kodu)
        if gunluk is None: return None
            
        gunluk = QuantModel.gostergeleri_hesapla(gunluk)
        if gunluk.empty: return None
            
        win_rate = Backtester.vektor_gercekci_test(gunluk)
        son_gun = gunluk.iloc[-1]
        fiyat, rsi, atr = float(son_gun['Close']), float(son_gun['RSI']), float(son_gun['ATR'])
        sma_200, bb_lower, hacim, hacim_ort = float(son_gun['SMA_200']), float(son_gun['BB_Lower']), float(son_gun['Volume']), float(son_gun['Hacim_Ort'])
        
        # --- LİKİDİTE FİLTRESİ ---
        if hacim < hacim_ort * 0.5: return None  # Çok sığ tahtaları direkt ele
        
        skor, nedenler = 0, []
        if fiyat < sma_200:
            fark = ((sma_200 - fiyat) / sma_200) * 100
            if fark > 15: skor += 40; nedenler.append(f"SMA200 altı %{int(fark)} İskonto")
            elif fark > 5: skor += 20; nedenler.append("Kısmi İskonto")
        if rsi < 35: skor += 30; nedenler.append(f"Aşırı Satım (RSI: {int(rsi)})")
        if fiyat <= bb_lower * 1.02: skor += 15; nedenler.append("Bollinger Dip")
        
        xu100 = DataFetcher.endeks_verisi_getir()
        if xu100 is not None and len(gunluk) >= 60 and len(xu100) >= 60:
            if ((fiyat / gunluk['Close'].iloc[-60]) - 1) > ((xu100['Close'].iloc[-1] / xu100['Close'].iloc[-60]) - 1):
                skor += 15; nedenler.append("Endeksten Ayrışma")

        if rsi > self.config.rsi_asiri_alim: skor -= 40
        if fiyat > sma_200 * 1.20: skor -= 30
                
        skor = max(0, min(skor, 100))
        if skor >= 80: karar = "🔥 KESİN TOPLA"
        elif skor >= 60: karar = "🟢 KADEMELİ AL"
        elif skor <= 30: karar = "🔴 UZAK DUR"
        else: karar = "⚪ NÖTR"
            
        # --- RİSK YÖNETİMİ SEVİYELERİ ---
        stop_loss = round(fiyat - (atr * self.config.atr_stop_carpan), 2)
        risk_mesafesi = fiyat - stop_loss
        hedef_fiyat = round(fiyat + (risk_mesafesi * self.config.risk_odul_orani), 2)
            
        return {
            "Hisse": hisse_kodu.replace(".IS", ""), "Karar": karar, "Skor": f"%{skor}",
            "Kaynak": kaynak, "Fiyat": round(fiyat, 2), "Stop Loss": stop_loss, "Hedef Fiyat": hedef_fiyat,
            "Win Rate": f"%{win_rate}", "Fırsat Özeti": " | ".join(nedenler[:3]) if nedenler else "Yatay",
            "Grafik_Verisi": gunluk[['Open', 'High', 'Low', 'Close', 'SMA_50', 'SMA_200']].tail(90)
        }

def cizgi_grafik_olustur(df, hisse, stop_seviyesi, hedef_seviyesi):
    fig = go.Figure()
    fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close']))
    if 'SMA_50' in df.columns: fig.add_trace(go.Scatter(x=df.index, y=df['SMA_50'], line=dict(color='#29b6f6', width=1.5), name='SMA 50'))
    if 'SMA_200' in df.columns: fig.add_trace(go.Scatter(x=df.index, y=df['SMA_200'], line=dict(color='#ffa726', width=2), name='SMA 200'))
    
    # Risk Çizgileri
    fig.add_hline(y=stop_seviyesi, line_dash="dash", line_color="#ff5252", annotation_text="Stop-Loss", annotation_position="bottom right")
    fig.add_hline(y=hedef_seviyesi, line_dash="dash", line_color="#69f0ae", annotation_text="Hedef Fiyat", annotation_position="top right")
    
    fig.update_layout(margin=dict(l=10, r=10, t=30, b=10), height=300, xaxis_rangeslider_visible=False, template="plotly_dark", showlegend=False)
    return fig

# --- 6. ARAYÜZ (UI) ---
def ui_olustur():
    st.title("🎯 Hibrit Quant & İstihbarat Botu v11.1 (Risk Optimizasyonlu)")
    st.markdown("Katılım Endeksi üzerinde matematiksel analiz yapar. Her sinyal için **Stop-Loss** ve **Hedef Fiyat** üretir.")
    st.markdown("---")

    st.sidebar.markdown("### 🏦 Portföy & Risk Parametreleri")
    toplam_sermaye = st.sidebar.number_input("Yönetilen Bakiye (₺)", min_value=10000, value=100000)
    atr_carpan = st.sidebar.slider("Stop-Loss ATR Çarpanı", min_value=1.0, max_value=3.0, value=1.5, step=0.25)
    risk_odul = st.sidebar.slider("Risk / Ödül Oranı", min_value=1.5, max_value=4.0, value=2.0, step=0.5)
    
    config = BotConfig(rsi_asiri_satim=35, rsi_asiri_alim=70, sermaye=toplam_sermaye, atr_stop_carpan=atr_carpan, risk_odul_orani=risk_odul)
    strateji = QuantStrategy(config)

    piyasa_durumu = DataFetcher.piyasa_rejimi_kontrol()
    if piyasa_durumu == "BULL": st.sidebar.success("📊 BIST Genel Trendi: BOĞA")
    else: st.sidebar.warning("⚠️ BIST Genel Trendi: AYI (Toplama Fırsatı)")

    st.sidebar.markdown("### 🔍 Özel İzleme Listesi")
    hisseler_metin = st.sidebar.text_area("Hızlı Tarama:", "MPARK\nBIMAS\nASELS\nLOGO", height=120)

    # --- HIZLI TARAMA BÖLÜMÜ ---
    if st.sidebar.button("🚀 Listeyi Tara", use_container_width=True):
        hisse_listesi = [h.strip().upper() for h in hisseler_metin.split("\n") if h.strip()]
        ilerleme = st.progress(0)
        sonuclar = []
        with ThreadPoolExecutor(max_workers=3) as executor:
            for idx, sonuc in enumerate(executor.map(strateji.analiz_et, hisse_listesi)):
                if sonuc: sonuclar.append(sonuc)
                ilerleme.progress((idx + 1) / len(hisse_listesi))
        ilerleme.empty()
        
        if sonuclar:
            df = pd.DataFrame(sonuclar).drop(columns=['Grafik_Verisi'])
            def tablo_renk(val):
                if "🔥" in str(val): return 'background-color: #1e4620; color: white;'
                elif "🟢" in str(val): return 'background-color: #388e3c; color: white;'
                elif "🔴" in str(val): return 'background-color: #b71c1c; color: white;'
                return ''
            st.markdown("### 📋 Hızlı Tarama Sonuçları")
            st.dataframe(df.style.map(tablo_renk, subset=['Karar']), use_container_width=True)

    # --- ANA RADAR: KATILIM ENDEKSİ VE İSTİHBARAT ---
    st.markdown("### 📡 Katılım Endeksi Fırsat Radarı (105 Hisse)")
    if st.button("🔍 Katılım Listesinde Dipteki Hisseleri Bul ve İstihbarat Topla", use_container_width=True):
        st.info("Algoritma devrede. Katılım Listesi sessizce taranıyor...")
        ilerleme_radar = st.progress(0)
        bulunan_firsatlar = []
        
        with ThreadPoolExecutor(max_workers=5) as executor:
            for idx, sonuc in enumerate(executor.map(strateji.analiz_et, KATILIM_LISTESI)):
                if sonuc and ("🔥" in sonuc["Karar"] or "🟢" in sonuc["Karar"]):
                    bulunan_firsatlar.append(sonuc)
                ilerleme_radar.progress((idx + 1) / len(KATILIM_LISTESI))
        ilerleme_radar.empty()
        
        if bulunan_firsatlar:
            st.success(f"🚨 Tarama Tamamlandı! Risk kontrollü toplanabilecek {len(bulunan_firsatlar)} fırsat bulundu.")
            sutunlar = st.columns(min(len(bulunan_firsatlar), 3))
            
            for idx, firsat in enumerate(bulunan_firsatlar):
                with sutunlar[idx % 3]:
                    arkaplan = "#1e4620" if "🔥" in firsat['Karar'] else "#2e7d32"
                    
                    html_kart = f"""<div style="border: 2px solid #2e7d32; border-radius: 10px; padding: 15px; background-color: {arkaplan}; color: white;">
<h2 style="text-align: center; color: #a5d6a7; margin-bottom:0;">{firsat['Hisse']}</h2>
<h1 style="text-align: center; margin-top:0;">{firsat['Skor']}</h1>
<div style="text-align:center; margin-bottom:10px;"><span style="background-color: #198754; padding: 3px 8px; border-radius: 8px; font-size: 12px; font-weight: bold;">✅ Katılım Endeksi</span></div>
<p style="text-align: center; font-size: 13px;"><b>{firsat['Fırsat Özeti']}</b></p>
<hr style="border-color: #4caf50;">
<p style="font-size: 13px; margin:2px 0;"><b>Giriş Fiyatı:</b> {firsat['Fiyat']} ₺</p>
<p style="font-size: 13px; margin:2px 0; color: #ff8a80;"><b>🔴 Stop Loss:</b> {firsat['Stop Loss']} ₺</p>
<p style="font-size: 13px; margin:2px 0; color: #b9f6ca;"><b>🟢 Hedef Fiyat:</b> {firsat['Hedef Fiyat']} ₺</p>
<p style="font-size: 11px; text-align: right; color: #c8e6c9; margin-top:8px;">Başarı: {firsat['Win Rate']} | Veri: {firsat['Kaynak']}</p>
</div>"""
                    st.markdown(html_kart, unsafe_allow_html=True)
                    
                    # TEKNİK GRAFİK
                    with st.expander("📊 Teknik Görünüm & Risk Haritası"):
                        st.plotly_chart(cizgi_grafik_olustur(firsat['Grafik_Verisi'], firsat['Hisse'], firsat['Stop Loss'], firsat['Hedef Fiyat']), use_container_width=True, config={'displayModeBar': False})
                    
                    # İSTİHBARAT KISMI (WEB SCRAPING)
                    with st.expander("🕵️‍♂️ KAP ve Haber İstihbaratı", expanded=True):
                        hisse = firsat['Hisse']
                        
                        kap_verileri = haberleri_kazi(f"{hisse} kap haberi", 2)
                        st.markdown("**🏛️ Son KAP Bildirimleri**")
                        if kap_verileri:
                            for kap in kap_verileri:
                                st.markdown(f"""<div class="kap-satiri">
                                <div class="haber-detay">{kap['zaman']} | {kap['kaynak']}</div>
                                <a href="{kap['link']}" target="_blank" class="haber-baslik">{kap['baslik']}</a>
                                </div>""", unsafe_allow_html=True)
                        else: st.caption("Önemli bir KAP bildirimi yok.")
                        
                        genel_veriler = haberleri_kazi(f"{hisse} hisse analiz", 2)
                        st.markdown("**📰 Medya ve Analizler**")
                        if genel_veriler:
                            for haber in genel_veriler:
                                st.markdown(f"""<div class="haber-satiri">
                                <div class="haber-detay">{haber['zaman']} | {haber['kaynak']}</div>
                                <a href="{haber['link']}" target="_blank" class="haber-baslik">{haber['baslik']}</a>
                                </div>""", unsafe_allow_html=True)
                        else: st.caption("Medyada güncel haber bulunamadı.")
                    st.markdown("<br>", unsafe_allow_html=True)
        else:
            st.warning("Şu an için risk/ödül kriterlerine uyan, likit ve dip bölgede bir katılım hissesi bulunamadı.")

if __name__ == "__main__":
    ui_olustur()
