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
st.set_page_config(page_title="Ultimate Quant Bot v11.3 - Çift Motorlu (Dip & Momentum)", page_icon="🎯", layout="wide")

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

# --- 0. GÜVENLİK ---
def sifre_kontrol():
    if "giris_basarili" not in st.session_state:
        st.session_state["giris_basarili"] = False

    if not st.session_state["giris_basarili"]:
        st.markdown("<h1 style='text-align: center;'>🔒 Sistem Erişimi</h1>", unsafe_allow_html=True)
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            with st.form("login_form"):
                girilen_sifre = st.text_input("Erişim Şifresi:", type="password")
                submit_button = st.form_submit_button("Giriş Yap", use_container_width=True)
                if submit_button:
                    st.session_state["giris_basarili"] = True
                    st.rerun()
        st.stop()

sifre_kontrol()

# --- 1. YAPILANDIRMA VE LİSTELER ---
class BotConfig:
    def __init__(self, sermaye, atr_stop_carpan, risk_odul_orani):
        self.sermaye = sermaye
        self.atr_stop_carpan = atr_stop_carpan
        self.risk_odul_orani = risk_odul_orani

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
    headers = {"User-Agent": "Mozilla/5.0"}
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
            zaman_etiketi = makale.find('time')
            zaman = zaman_etiketi.text if zaman_etiketi else "Yakın Zaman"
            makaleler.append({"baslik": baslik, "link": link, "kaynak": "Medya", "zaman": zaman})
        return makaleler
    except: return []

# --- 3. VERİ YÖNETİMİ ---
class DataFetcher:
    @staticmethod
    def is_yatirim_api_sorgula(sembol, periyot_gun=365):
        try:
            sembol = sembol.replace(".IS", "").upper()
            bitis_tarihi = datetime.datetime.now().strftime("%d-%m-%Y")
            baslangic_tarihi = (datetime.datetime.now() - datetime.timedelta(days=periyot_gun)).strftime("%d-%m-%Y")
            url = f"https://www.isyatirim.com.tr/_layouts/15/IsYatirim.Website/Common/Data.aspx/HisseTekil?hisse={sembol}&startdate={baslangic_tarihi}&enddate={bitis_tarihi}"
            response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=8)
            veri_json = response.json()
            if 'value' in veri_json and veri_json['value']:
                df = pd.DataFrame(veri_json['value'])
                df['Date'] = pd.to_datetime(df['HGDG_TARIH'], format='%d-%m-%Y')
                df.set_index('Date', inplace=True)
                df.rename(columns={'KAPANIS': 'Close', 'MAX': 'High', 'MIN': 'Low', 'ISLEM_MIKTARI': 'Volume'}, inplace=True)
                df['Open'] = df['Close'].shift(1).fillna(df['Close'])
                return df[['Open', 'High', 'Low', 'Close', 'Volume']].astype(float)
            return None
        except: return None

    @staticmethod
    def yfinance_api_sorgula(sembol):
        try:
            if not sembol.endswith(".IS"): sembol = f"{sembol}.IS"
            df = yf.Ticker(sembol).history(period="1y", interval="1d")
            if not df.empty and len(df) >= 60: return df[['Open', 'High', 'Low', 'Close', 'Volume']].astype(float)
            return None
        except: return None

    @staticmethod
    def veri_indir(hisse_kodu):
        veri = DataFetcher.is_yatirim_api_sorgula(hisse_kodu)
        if veri is not None and len(veri) > 60: return veri, "İş Yatırım API"
        veri = DataFetcher.yfinance_api_sorgula(hisse_kodu)
        if veri is not None: return veri, "Yedek API (Yahoo)"
        return None, "Bağlantı Hatası"

# --- 4. TEKNİK ANALİZ VE GÖSTERGELER ---
class QuantModel:
    @staticmethod
    def gostergeleri_hesapla(df):
        kapanis, yuksek, dusuk, hacim = df['Close'], df['High'], df['Low'], df['Volume']
        df['RSI'] = ta.momentum.RSIIndicator(close=kapanis).rsi()
        df['SMA_50'] = ta.trend.SMAIndicator(close=kapanis, window=50).sma_indicator()
        df['SMA_200'] = ta.trend.SMAIndicator(close=kapanis, window=200).sma_indicator()
        
        # Bollinger Bantları (Alt = Dip için, Üst = Momentum/Ralli için)
        bb = ta.volatility.BollingerBands(close=kapanis, window=20, window_dev=2)
        df['BB_Lower'] = bb.bollinger_lband()
        df['BB_Upper'] = bb.bollinger_hband()
        
        df['ATR'] = ta.volatility.AverageTrueRange(high=yuksek, low=dusuk, close=kapanis).average_true_range()
        
        macd = ta.trend.MACD(close=kapanis)
        df['MACD'] = macd.macd()
        df['MACD_Signal'] = macd.macd_signal()
        df['Hacim_Ort'] = hacim.rolling(window=20).mean()
        
        df.dropna(inplace=True)
        return df

# --- 5. STRATEJİ MOTORU (ÇİFT MOTOR: DİP VE MOMENTUM) ---
class QuantStrategy:
    def __init__(self, config):
        self.config = config

    def analiz_et(self, hisse_kodu):
        gunluk, kaynak = DataFetcher.veri_indir(hisse_kodu)
        if gunluk is None: return None
            
        gunluk = QuantModel.gostergeleri_hesapla(gunluk)
        if gunluk.empty: return None
            
        son_gun = gunluk.iloc[-1]
        fiyat, rsi, atr = float(son_gun['Close']), float(son_gun['RSI']), float(son_gun['ATR'])
        sma_50, sma_200 = float(son_gun['SMA_50']), float(son_gun['SMA_200'])
        bb_lower, bb_upper = float(son_gun['BB_Lower']), float(son_gun['BB_Upper'])
        mac_deger, mac_signal = float(son_gun['MACD']), float(son_gun['MACD_Signal'])
        hacim, hacim_ort = float(son_gun['Volume']), float(son_gun['Hacim_Ort'])
        
        # Likidite Koruması (Ölü tahtaları ele)
        if hacim < hacim_ort * 0.5: return None

        # --- MOTOR 1: GÜVENLİ DİP AVCISI ---
        dip_skor = 0
        dip_nedenler = []
        # MACD onayı yoksa dip skoru hesaplanmaz (Düşen bıçak engeli)
        if mac_deger > mac_signal and fiyat < sma_200 * 1.05:
            if fiyat < sma_200: dip_skor += 35; dip_nedenler.append("SMA200 İskontosu")
            if rsi < 45: dip_skor += 30; dip_nedenler.append(f"Dip RSI ({int(rsi)})")
            if fiyat <= bb_lower * 1.03: dip_skor += 20; dip_nedenler.append("Bollinger Dip Tepkisi")
            if hacim > hacim_ort: dip_skor += 15; dip_nedenler.append("Hacimli Dönüş")

        # --- MOTOR 2: MOMENTUM ROKETİ (Trend Takipçisi) ---
        mom_skor = 0
        mom_nedenler = []
        # Fiyat hareketli ortalamaların üzerinde olmalı ve MACD pozitif bölgede olmalı
        if fiyat > sma_50 and sma_50 > sma_200 and mac_deger > 0 and mac_deger > mac_signal:
            if rsi > 65 and rsi < 85: mom_skor += 30; mom_nedenler.append(f"Güçlü Trend (RSI: {int(rsi)})")
            if fiyat >= bb_upper * 0.98: mom_skor += 30; mom_nedenler.append("Bollinger Üst Bant Kırılımı 🚀")
            if hacim > hacim_ort * 1.3: mom_skor += 25; mom_nedenler.append("Hacim Patlaması")
            if rsi > 85: mom_skor -= 20; mom_nedenler.append("Aşırı Şişmiş Uyarısı") # Çok fırlamışsa puan kır

        # --- HAKEM: HANGİ MOTOR KAZANDI? ---
        nihai_skor = 0
        karar_metni = ""
        strateji_tipi = ""
        ozet = ""
        tema_renk = ""

        if mom_skor >= 70 and mom_skor >= dip_skor:
            nihai_skor = mom_skor
            karar_metni = "🚀 MOMENTUM RALLİSİ"
            strateji_tipi = "Momentum/Breakout"
            ozet = " | ".join(mom_nedenler[:3])
            tema_renk = "#004d40" # Koyu Mavi/Yeşil (Roket)
            
        elif dip_skor >= 70:
            nihai_skor = dip_skor
            karar_metni = "🔥 GÜVENLİ DİP"
            strateji_tipi = "Reversal/Değer"
            ozet = " | ".join(dip_nedenler[:3])
            tema_renk = "#1e4620" # Klasik Yeşil
            
        else:
            return None # İki stratejiye de uymayanlar elenir.

        # --- RİSK YÖNETİMİ SEVİYELERİ ---
        # Momentum hisselerinde ATR daha agresif hesaplanabilir ama standart koruyalım.
        stop_loss = round(fiyat - (atr * self.config.atr_stop_carpan), 2)
        risk_mesafesi = fiyat - stop_loss
        hedef_fiyat = round(fiyat + (risk_mesafesi * self.config.risk_odul_orani), 2)
            
        return {
            "Hisse": hisse_kodu.replace(".IS", ""), "Karar": karar_metni, "Skor": f"%{min(nihai_skor, 100)}",
            "Tip": strateji_tipi, "Renk": tema_renk,
            "Kaynak": kaynak, "Fiyat": round(fiyat, 2), "Stop Loss": stop_loss, "Hedef Fiyat": hedef_fiyat,
            "Fırsat Özeti": ozet,
            "Grafik_Verisi": gunluk[['Open', 'High', 'Low', 'Close', 'SMA_50', 'SMA_200', 'BB_Upper', 'BB_Lower']].tail(90)
        }

def cizgi_grafik_olustur(df, hisse, stop_seviyesi, hedef_seviyesi):
    fig = go.Figure()
    fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close']))
    if 'SMA_50' in df.columns: fig.add_trace(go.Scatter(x=df.index, y=df['SMA_50'], line=dict(color='#29b6f6', width=1.5), name='SMA 50'))
    if 'SMA_200' in df.columns: fig.add_trace(go.Scatter(x=df.index, y=df['SMA_200'], line=dict(color='#ffa726', width=2), name='SMA 200'))
    
    # Yeni eklenen BB Bantlarını grafikte gösterme
    if 'BB_Upper' in df.columns: fig.add_trace(go.Scatter(x=df.index, y=df['BB_Upper'], line=dict(color='rgba(255,255,255,0.2)', width=1, dash='dot'), name='BB Upper'))
    
    fig.add_hline(y=stop_seviyesi, line_dash="dash", line_color="#ff5252", annotation_text="Stop-Loss")
    fig.add_hline(y=hedef_seviyesi, line_dash="dash", line_color="#69f0ae", annotation_text="Hedef Fiyat")
    
    fig.update_layout(margin=dict(l=10, r=10, t=30, b=10), height=300, xaxis_rangeslider_visible=False, template="plotly_dark", showlegend=False)
    return fig

# --- 6. ARAYÜZ (UI) ---
def ui_olustur():
    st.title("🎯 Hibrit Quant Bot v11.3 (Dip & Momentum Çift Motor)")
    st.markdown("Algoritma artık hem dipten dönüş yapan iskontolu hisseleri, hem de direnç kırmış hacimli ralli (momentum) hisselerini avlar.")
    st.markdown("---")

    st.sidebar.markdown("### 🏦 Portföy & Risk Parametreleri")
    toplam_sermaye = st.sidebar.number_input("Yönetilen Bakiye (₺)", min_value=10000, value=100000)
    atr_carpan = st.sidebar.slider("Stop-Loss ATR Çarpanı", min_value=1.0, max_value=3.0, value=1.5, step=0.25)
    risk_odul = st.sidebar.slider("Risk / Ödül Oranı", min_value=1.5, max_value=4.0, value=2.0, step=0.5)
    
    config = BotConfig(sermaye=toplam_sermaye, atr_stop_carpan=atr_carpan, risk_odul_orani=risk_odul)
    strateji = QuantStrategy(config)

    st.sidebar.markdown("### 🔍 Hızlı Radar Testi")
    hisseler_metin = st.sidebar.text_area("Hızlı Tarama:", "GUNDG\nOZATD\nASELS\nTKNSA", height=120)

    # --- ANA RADAR (ÇİFT MOTOR) ---
    if st.button("🚀 Piyasayı Tara (Güvenli Dip & Momentum Roketleri)", use_container_width=True):
        st.info("Çift Motor aktif edildi. Piyasa taranıyor...")
        
        # İster hızlı listeyi, ister tüm katılım listesini taratabilirsiniz.
        # Şimdilik örnek olması için yan menüdeki hisseleri taratalım.
        hisse_listesi = [h.strip().upper() for h in hisseler_metin.split("\n") if h.strip()]
        # Veya tüm listeyi taramak için: hisse_listesi = KATILIM_LISTESI
        
        ilerleme_radar = st.progress(0)
        bulunan_firsatlar = []
        
        with ThreadPoolExecutor(max_workers=5) as executor:
            for idx, sonuc in enumerate(executor.map(strateji.analiz_et, hisse_listesi)):
                if sonuc:
                    bulunan_firsatlar.append(sonuc)
                ilerleme_radar.progress((idx + 1) / len(hisse_listesi))
        ilerleme_radar.empty()
        
        if bulunan_firsatlar:
            st.success(f"🚨 Tarama Tamamlandı! Kriterleri sağlayan {len(bulunan_firsatlar)} fırsat bulundu.")
            sutunlar = st.columns(min(len(bulunan_firsatlar), 3))
            
            for idx, firsat in enumerate(bulunan_firsatlar):
                with sutunlar[idx % 3]:
                    html_kart = f"""<div style="border: 2px solid {firsat['Renk']}; border-radius: 10px; padding: 15px; background-color: {firsat['Renk']}; color: white; margin-bottom: 15px;">
<h2 style="text-align: center; color: #a5d6a7; margin-bottom:0;">{firsat['Hisse']}</h2>
<h1 style="text-align: center; margin-top:0;">{firsat['Skor']}</h1>
<div style="text-align:center; margin-bottom:10px;"><span style="background-color: #00000050; padding: 3px 8px; border-radius: 8px; font-size: 13px; font-weight: bold;">{firsat['Karar']}</span></div>
<p style="text-align: center; font-size: 13px;"><b>{firsat['Fırsat Özeti']}</b></p>
<hr style="border-color: #ffffff50;">
<p style="font-size: 13px; margin:2px 0;"><b>Giriş Fiyatı:</b> {firsat['Fiyat']} ₺</p>
<p style="font-size: 13px; margin:2px 0; color: #ff8a80;"><b>🔴 Stop Loss:</b> {firsat['Stop Loss']} ₺</p>
<p style="font-size: 13px; margin:2px 0; color: #b9f6ca;"><b>🟢 Hedef Fiyat:</b> {firsat['Hedef Fiyat']} ₺</p>
<p style="font-size: 11px; text-align: right; color: #c8e6c9; margin-top:8px;">Veri: {firsat['Kaynak']}</p>
</div>"""
                    st.markdown(html_kart, unsafe_allow_html=True)
                    
                    with st.expander("📊 Teknik Görünüm & Risk Haritası"):
                        st.plotly_chart(cizgi_grafik_olustur(firsat['Grafik_Verisi'], firsat['Hisse'], firsat['Stop Loss'], firsat['Hedef Fiyat']), use_container_width=True, config={'displayModeBar': False})
                        
                    with st.expander("🕵️‍♂️ KAP & İstihbarat"):
                        kap_verileri = haberleri_kazi(f"{firsat['Hisse']} kap haberi", 2)
                        if kap_verileri:
                            for kap in kap_verileri:
                                st.markdown(f"[{kap['zaman']}] <a href='{kap['link']}' target='_blank' style='color:#29b6f6;'>{kap['baslik']}</a>", unsafe_allow_html=True)
                        else: st.caption("Haber yok.")
        else:
            st.warning("Ne bir dip dönüşü, ne de bir momentum rallisi tespit edilemedi.")

if __name__ == "__main__":
    ui_olustur()
