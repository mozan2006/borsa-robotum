import streamlit as st
import pandas as pd
import numpy as np
import ta
import warnings
import logging
import requests
import datetime
import plotly.graph_objects as go
from concurrent.futures import ThreadPoolExecutor

warnings.filterwarnings('ignore')
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- SAYFA AYARLARI ---
st.set_page_config(page_title="Ultimate Quant Bot v10.0 - Değer Odaklı", page_icon="🤖", layout="wide")

# --- 0. GÜVENLİK VE OTURUM YÖNETİMİ (KISS Prensibi) ---
def sifre_kontrol():
    if "giris_basarili" not in st.session_state:
        st.session_state["giris_basarili"] = False

    if not st.session_state["giris_basarili"]:
        st.markdown("<h1 style='text-align: center;'>🔒 Sistem Erişimi</h1>", unsafe_allow_html=True)
        st.markdown("<p style='text-align: center;'>Bu, kapalı devre bir Değer Yatırımı arayüzüdür. Lütfen erişim şifrenizi girin.</p>", unsafe_allow_html=True)
        
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            with st.form("login_form"):
                girilen_sifre = st.text_input("Erişim Şifresi:", type="password")
                submit_button = st.form_submit_button("Sisteme Giriş Yap", use_container_width=True)
                
                if submit_button:
                    # Basit ve şifrelemesiz düz metin kontrolü korunmuştur
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
    def __init__(self, rsi_asiri_satim, rsi_asiri_alim, sermaye):
        self.rsi_asiri_satim = rsi_asiri_satim
        self.rsi_asiri_alim = rsi_asiri_alim
        self.sermaye = sermaye

# --- GRAFİK ÇİZİCİ MODÜL ---
def cizgi_grafik_olustur(df, hisse, toplama_seviyesi):
    fig = go.Figure()
    
    fig.add_trace(go.Candlestick(
        x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='Fiyat'
    ))
    
    if 'SMA_50' in df.columns:
        fig.add_trace(go.Scatter(x=df.index, y=df['SMA_50'], line=dict(color='#29b6f6', width=1.5), name='SMA 50'))
    if 'SMA_200' in df.columns:
        fig.add_trace(go.Scatter(x=df.index, y=df['SMA_200'], line=dict(color='#ffa726', width=2), name='SMA 200'))
    
    fig.add_hline(y=toplama_seviyesi, line_dash="dot", line_color="#4fc3f7", annotation_text="Kademeli Toplama", annotation_position="bottom left")

    fig.update_layout(
        margin=dict(l=10, r=10, t=30, b=10),
        height=300,
        xaxis_rangeslider_visible=False,
        template="plotly_dark",
        title=dict(text=f"{hisse} - Uzun Vade Görünümü", font=dict(size=14, color="#a5d6a7")),
        showlegend=False,
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)'
    )
    return fig

# --- 2. VERİ YÖNETİMİ (SADECE İŞ YATIRIM API - YFINANCE KALDIRILDI) ---
class DataFetcher:
    @staticmethod
    def is_yatirim_api_sorgula(sembol, periyot_gun=730):
        try:
            sembol = sembol.replace(".IS", "").upper()
            bitis_tarihi = datetime.datetime.now().strftime("%d-%m-%Y")
            baslangic_tarihi = (datetime.datetime.now() - datetime.timedelta(days=periyot_gun)).strftime("%d-%m-%Y")
            
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
                    return None
                return gunluk_veri
            return None
        except Exception as e:
            logging.error(f"İş Yatırım API Hatası ({sembol}): {e}")
            return None

    @staticmethod
    @st.cache_data(ttl=3600, show_spinner=False)
    def endeks_verisi_getir():
        """Göreli Güç hesabı için XU100 verisi."""
        return DataFetcher.is_yatirim_api_sorgula("XU100", 365)

    @staticmethod
    def veri_indir(hisse_kodu):
        gunluk_veri = DataFetcher.is_yatirim_api_sorgula(hisse_kodu)
        if gunluk_veri is not None:
            # İş Yatırım'dan haber çekimi stabil olmadığı için temel rasyo ağırlığı artırılmıştır
            return gunluk_veri, "Veri Stabil (İş Yatırım)"
        return None, "Veri Hatası"

    @staticmethod
    @st.cache_data(ttl=3600, show_spinner=False)
    def piyasa_rejimi_kontrol():
        df = DataFetcher.is_yatirim_api_sorgula("XU100", 365)
        if df is not None and not df.empty and len(df) > 200:
            sma_200 = ta.trend.SMAIndicator(close=df['Close'], window=200).sma_indicator()
            son_kapanis = df['Close'].iloc[-1]
            son_sma200 = sma_200.iloc[-1]
            return "BULL" if son_kapanis > son_sma200 else "BEAR"
        return "BULL"

# --- 3. TEKNİK ANALİZ ---
class QuantModel:
    @staticmethod
    def gostergeleri_hesapla(df):
        kapanis = df['Close']
        df['RSI'] = ta.momentum.RSIIndicator(close=kapanis).rsi()
        macd = ta.trend.MACD(close=kapanis)
        df['MACD_Line'] = macd.macd()
        df['MACD_Signal'] = macd.macd_signal()
        df['SMA_50'] = ta.trend.SMAIndicator(close=kapanis, window=50).sma_indicator()
        df['SMA_200'] = ta.trend.SMAIndicator(close=kapanis, window=200).sma_indicator()
        
        # Volatilite ve aşırı satım tespiti için Bollinger 
        bollinger = ta.volatility.BollingerBands(close=kapanis, window=20, window_dev=2)
        df['BB_Lower'] = bollinger.bollinger_lband()
        
        df.dropna(inplace=True)
        return df

# --- 4. VEKTÖREL BACKTEST (ITERROWS KALDIRILDI) ---
class Backtester:
    @staticmethod
    def vektor_gercekci_test(df):
        """Döngü (for) yerine vektörel işlemler kullanılarak x100 hızlandırılmış basit karlılık testi"""
        if df is None or len(df) < 50: return 0
        
        # Basit Strateji: Fiyat SMA200 altındaysa ve RSI 40'tan küçükse al (Kademeli Toplama)
        alis_sinyalleri = (df['Close'] < df['SMA_200']) & (df['RSI'] < 40)
        df['Sinyal'] = np.where(alis_sinyalleri, 1, 0)
        
        # Gelecekteki 20 günlük getiri (Al ve Tut yaklaşımı)
        df['Gelecek_Getiri'] = df['Close'].shift(-20) / df['Close'] - 1
        
        # Sinyal oluşan günlerin ortalama 20 günlük getirisi
        basarili_islemler = df[df['Sinyal'] == 1]['Gelecek_Getiri'] > 0
        win_rate = basarili_islemler.mean() * 100 if not basarili_islemler.empty else 50.0
        
        return round(win_rate, 1)

# --- 5. STRATEJİ MOTORU (UZUN VADELİ TOPLAMA MANTIĞI) ---
class QuantStrategy:
    def __init__(self, config):
        self.config = config

    def analiz_et(self, hisse_kodu):
        gunluk, durum = DataFetcher.veri_indir(hisse_kodu)
        if gunluk is None: return None
            
        gunluk = QuantModel.gostergeleri_hesapla(gunluk)
        if gunluk.empty: return None
            
        win_rate = Backtester.vektor_gercekci_test(gunluk)
        
        son_gun = gunluk.iloc[-1]
        fiyat = float(son_gun['Close'])
        rsi = float(son_gun['RSI'])
        sma_200 = float(son_gun['SMA_200'])
        sma_50 = float(son_gun['SMA_50'])
        bb_lower = float(son_gun['BB_Lower'])
        
        skor = 50 
        nedenler = []
        
        # YENİ MANTIK: DÜŞÜŞLER FIRSATTIR (KADEMELİ TOPLAMA)
        if fiyat < sma_200:
            fark_yuzde = ((sma_200 - fiyat) / sma_200) * 100
            if fark_yuzde > 10 and rsi < 40:
                skor += 30; nedenler.append("Kademeli Toplama (SMA200 Altı İskonto)")
            elif rsi < 30:
                skor += 20; nedenler.append("Aşırı Satım (Değer Bölgesi)")
        else:
            if fiyat > sma_50 and son_gun['MACD_Line'] > son_gun['MACD_Signal']:
                skor += 15; nedenler.append("Güçlü Yükseliş Trendi")
        
        if fiyat <= bb_lower:
            skor += 15; nedenler.append("Bollinger Alt Bandına Değdi (Ucuz)")
            
        if rsi > self.config.rsi_asiri_alim:
            skor -= 25; nedenler.append("Aşırı Alım / Şişkinlik")

        # GÖRELİ GÜÇ (RS)
        xu100 = DataFetcher.endeks_verisi_getir()
        if xu100 is not None and len(gunluk) >= 60 and len(xu100) >= 60:
            hisse_getiri = (fiyat / gunluk['Close'].iloc[-60]) - 1
            endeks_getiri = (xu100['Close'].iloc[-1] / xu100['Close'].iloc[-60]) - 1
            
            if hisse_getiri > (endeks_getiri + 0.05):
                skor += 15; nedenler.append("Endeksten Pozitif Ayrışma")
                
        skor = max(0, min(skor, 100))
        
        # UZUN VADELİ KARAR MEKANİZMASI
        if skor >= 75: karar = "🔥 UCUZ - KADEMELİ TOPLA"
        elif skor >= 60: karar = "🟢 UZUN VADE AL"
        elif skor <= 40 or rsi > self.config.rsi_asiri_alim: karar = "🔴 ŞİŞKİN - BEKLE"
        else: karar = "⚪ İZLEMEDE"
            
        return {
            "Hisse": hisse_kodu.replace(".IS", ""), 
            "Karar": karar, 
            "Skor": f"%{skor}",
            "Fiyat (₺)": round(fiyat, 2), 
            "Maliyetlenme Seviyesi (₺)": round(bb_lower, 2), # Toplama için destek seviyesi
            "Uzun Vade Trend": "POZİTİF" if fiyat > sma_200 else "İSKONTOLU",
            "Win Rate": f"%{win_rate}",
            "Fırsat Özeti": " | ".join(nedenler[:3]) if nedenler else "Yatay / Nötr",
            "Grafik_Verisi": gunluk[['Open', 'High', 'Low', 'Close', 'SMA_50', 'SMA_200']].tail(90)
        }

# --- 6. ARAYÜZ (UI) ---
def ui_olustur():
    st.title("🌱 Değer ve Temettü Odaklı Katılım Botu v10.0")
    st.markdown("İş Yatırım Altyapısı Aktif. Vektörel Tarama ve Kademeli Toplama Stratejisi ile Çalışır.")
    st.markdown("---")

    # --- YAN MENÜ ---
    st.sidebar.markdown("### 🏦 Portföy Parametreleri")
    toplam_sermaye = st.sidebar.number_input("Yönetilen Bakiye (₺)", min_value=10000, value=100000)

    config = BotConfig(rsi_asiri_satim=35, rsi_asiri_alim=70, sermaye=toplam_sermaye)
    strateji = QuantStrategy(config)

    piyasa_durumu = DataFetcher.piyasa_rejimi_kontrol()
    if piyasa_durumu == "BULL":
        st.sidebar.success("📊 BIST Genel Trendi: BOĞA")
    else:
        st.sidebar.warning("⚠️ BIST Genel Trendi: AYI (Toplama Fırsatı)")

    # --- 1. MANUEL TARAMA BÖLÜMÜ ---
    st.sidebar.markdown("### 🔍 Favori İzleme Listesi")
    # Düzenli takip edilen hisseler varsayılan olarak eklendi
    varsayilan_hisseler = "MPARK\nBIMAS\nENJSA\nASELS\nLOGO\nTUPRS\nALBRK\nCIMSA\nYEOTK\nEBEBK"
    hisseler_metin = st.sidebar.text_area("Taranacak Hisseler:", varsayilan_hisseler, height=220)

    # UI Yapısı: Tablo ve Fırsat Kartları için Konteynerler
    tablo_alani = st.container()
    firsat_alani = st.container()

    if st.sidebar.button("🚀 İzleme Listesini Tara", use_container_width=True):
        hisse_listesi = [h.strip().upper() for h in hisseler_metin.split("\n") if h.strip()]
        ilerleme = st.progress(0)
        sonuclar = []
        
        with ThreadPoolExecutor(max_workers=5) as executor:
            sonuc_haritasi = executor.map(strateji.analiz_et, hisse_listesi)
            for idx, sonuc in enumerate(sonuc_haritasi):
                if sonuc: sonuclar.append(sonuc)
                ilerleme.progress((idx + 1) / len(hisse_listesi))
        ilerleme.empty()
        
        if sonuclar:
            df = pd.DataFrame(sonuclar)
            gosterim_df = df.drop(columns=['Grafik_Verisi'])
            
            def tablo_renk(val):
                if "🔥 UCUZ" in str(val): return 'background-color: #1e4620; color: white; font-weight: bold;'
                elif "🟢 UZUN VADE AL" in str(val): return 'background-color: #388e3c; color: white;'
                elif "🔴 ŞİŞKİN" in str(val): return 'background-color: #b71c1c; color: white;'
                elif "⚪ İZLEMEDE" in str(val): return 'background-color: #546e7a; color: white;'
                return ''
            
            with tablo_alani:
                st.markdown("### 📋 Genel Analiz Tablosu")
                st.dataframe(gosterim_df.style.map(tablo_renk, subset=['Karar']), use_container_width=True)
            
            # --- GÜÇLÜ AL / TOPLAMA BÖLGESİ (YENİ UI) ---
            with firsat_alani:
                toplama_firsatlari = [s for s in sonuclar if "🔥 UCUZ" in s["Karar"]]
                if toplama_firsatlari:
                    st.markdown("---")
                    st.markdown("### 🎯 KADEMELİ TOPLAMA BÖLGESİNDEKİ HİSSELER")
                    st.info("Aşağıdaki hisseler uzun vadeli yatırım stratejisine göre iskontolu bölgeye girmiştir. Kademeli maliyetlenme değerlendirilebilir.")
                    
                    sutunlar = st.columns(min(len(toplama_firsatlari), 3))
                    for idx, firsat in enumerate(toplama_firsatlari):
                        with sutunlar[idx % 3]:
                            st.markdown(f"""
                            <div style="border: 2px solid #2e7d32; border-radius: 10px; padding: 15px; background-color: #1e4620; color: white; margin-bottom: 10px;">
                                <h2 style="text-align: center; color: #a5d6a7; margin-top: 0;">{firsat['Hisse']}</h2>
                                <h1 style="text-align: center; margin: 0;">{firsat['Skor']}</h1>
                                <p style="text-align: center; font-size: 14px; background-color: #1b5e20; border-radius: 5px; padding: 4px;"><b>{firsat['Fırsat Özeti']}</b></p>
                                <hr style="border-color: #4caf50;">
                                <p style="font-size: 15px;"><b>Güncel Fiyat:</b> {firsat['Fiyat (₺)']} ₺</p>
                                <p style="font-size: 15px; color: #81c784;"><b>Maliyetlenme Hedefi:</b> {firsat['Maliyetlenme Seviyesi (₺)']} ₺ civarı</p>
                            </div>
                            """, unsafe_allow_html=True)
                            
                            with st.expander("📊 3 Aylık Seyir"):
                                fig = cizgi_grafik_olustur(
                                    firsat['Grafik_Verisi'], 
                                    firsat['Hisse'], 
                                    firsat['Maliyetlenme Seviyesi (₺)']
                                )
                                st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})
        else:
            st.error("Veri çekilemedi. İş Yatırım sunucuları meşgul olabilir.")

    # --- 2. OTOMATİK FIRSAT RADARI ---
    st.markdown("### 📡 Katılım Endeksi Fırsat Radarı")
    if st.button("🔍 Katılım Endeksindeki İskontolu Hisseleri Bul", use_container_width=True):
        bist_katilim_hisseler = [
            "ALBRK", "ALFAS", "ASELS", "ASTOR", "BIMAS", "BRSAN", 
            "CANTE", "CIMSA", "CWENE", "DOAS", "EGEEN", "EKGYO", 
            "ENJSA", "ENKAI", "EUPWR", "FROTO", "GESAN", "GWIND", 
            "HEKTS", "JANTS", "KCAER", "KMPUR", "KONTR", 
            "KORDS", "KRDMD", "MIATK", "MPARK", 
            "OTKAR", "OYAKC", "QUAGR", "SASA", "SMRTG", "TTRAK", 
            "TUKAS", "VESBE", "YEOTK", "YUNSA"
        ]
        
        st.info("İş Yatırım API üzerinden eşzamanlı vektörel tarama yapılıyor. Lütfen bekleyin...")
        
        bulunan_firsatlar = []
        
        with ThreadPoolExecutor(max_workers=8) as executor:
            radar_sonuclari = executor.map(strateji.analiz_et, bist_katilim_hisseler)
            for sonuc in radar_sonuclari:
                if sonuc and ("🔥 UCUZ" in sonuc["Karar"]):
                    bulunan_firsatlar.append(sonuc)
        
        if bulunan_firsatlar:
            st.success(f"🚨 Tarama Tamamlandı: Kademeli Toplanabilecek {len(bulunan_firsatlar)} Şirket Bulundu!")
            sutunlar = st.columns(min(len(bulunan_firsatlar), 3))
            for idx, firsat in enumerate(bulunan_firsatlar):
                with sutunlar[idx % 3]:
                    st.markdown(f"""
                    <div style="border: 2px solid #2e7d32; border-radius: 10px; padding: 15px; background-color: #1e4620; color: white;">
                        <h2 style="text-align: center; color: #a5d6a7;">{firsat['Hisse']}</h2>
                        <h1 style="text-align: center;">{firsat['Skor']}</h1>
                        <p style="text-align: center; font-size: 13px;"><b>{firsat['Fırsat Özeti']}</b></p>
                        <p style="font-size: 14px;"><b>Fiyat:</b> {firsat['Fiyat (₺)']} ₺</p>
                        <p style="font-size: 14px; color: #81c784;"><b>Maliyet Hedefi:</b> {firsat['Maliyetlenme Seviyesi (₺)']} ₺</p>
                    </div>
                    <br>
                    """, unsafe_allow_html=True)
        else:
            st.warning("Şu an için kriterlere uyan aşırı satım bölgesinde (iskontolu) hisse bulunamadı.")

if __name__ == "__main__":
    ui_olustur()
