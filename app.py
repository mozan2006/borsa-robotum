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

warnings.filterwarnings('ignore')
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- SAYFA AYARLARI ---
st.set_page_config(page_title="Ultimate Quant Bot v10.1 - Keskin Nişancı", page_icon="🎯", layout="wide")

# --- 0. GÜVENLİK VE OTURUM YÖNETİMİ ---
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

# --- 2. VERİ YÖNETİMİ (ÇİFT MOTOR: İŞ YATIRIM + YAHOO YEDEĞİ) ---
class DataFetcher:
    @staticmethod
    def is_yatirim_api_sorgula(sembol, periyot_gun=730):
        try:
            sembol = sembol.replace(".IS", "").upper()
            bitis_tarihi = datetime.datetime.now().strftime("%d-%m-%Y")
            baslangic_tarihi = (datetime.datetime.now() - datetime.timedelta(days=periyot_gun)).strftime("%d-%m-%Y")
            
            url = f"https://www.isyatirim.com.tr/_layouts/15/IsYatirim.Website/Common/Data.aspx/HisseTekil?hisse={sembol}&startdate={baslangic_tarihi}&enddate={bitis_tarihi}"
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36',
                'Accept': 'application/json, text/javascript, */*; q=0.01',
                'Accept-Language': 'tr-TR,tr;q=0.9,en-US;q=0.8',
                'Connection': 'keep-alive',
                'Referer': 'https://www.isyatirim.com.tr/'
            }
            
            response = requests.get(url, headers=headers, timeout=8)
            if response.status_code != 200:
                return None
                
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
            logging.warning(f"İş Yatırım API engellendi ({sembol}). Yedek motora geçiliyor...")
            return None

    @staticmethod
    def yfinance_api_sorgula(sembol):
        try:
            if not sembol.endswith(".IS"):
                sembol = f"{sembol}.IS"
            ticker = yf.Ticker(sembol)
            df = ticker.history(period="2y", interval="1d")
            
            if not df.empty and len(df) >= 60:
                gunluk_veri = df[['Open', 'High', 'Low', 'Close', 'Volume']].astype(float)
                gunluk_veri.index = gunluk_veri.index.tz_localize(None).normalize()
                return gunluk_veri
            return None
        except Exception as e:
            logging.error(f"YFinance Yedek Hatası ({sembol}): {e}")
            return None

    @staticmethod
    @st.cache_data(ttl=3600, show_spinner=False)
    def endeks_verisi_getir():
        veri = DataFetcher.is_yatirim_api_sorgula("XU100", 365)
        if veri is None:
            veri = DataFetcher.yfinance_api_sorgula("XU100.IS")
        return veri

    @staticmethod
    def veri_indir(hisse_kodu):
        gunluk_veri = DataFetcher.is_yatirim_api_sorgula(hisse_kodu)
        if gunluk_veri is not None:
            return gunluk_veri, "İş Yatırım API"
        
        gunluk_veri = DataFetcher.yfinance_api_sorgula(hisse_kodu)
        if gunluk_veri is not None:
            return gunluk_veri, "Yedek API (Yahoo)"
            
        return None, "Bağlantı Hatası"

    @staticmethod
    @st.cache_data(ttl=3600, show_spinner=False)
    def piyasa_rejimi_kontrol():
        df = DataFetcher.endeks_verisi_getir()
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
        
        bollinger = ta.volatility.BollingerBands(close=kapanis, window=20, window_dev=2)
        df['BB_Lower'] = bollinger.bollinger_lband()
        
        df.dropna(inplace=True)
        return df

# --- 4. VEKTÖREL BACKTEST ---
class Backtester:
    @staticmethod
    def vektor_gercekci_test(df):
        if df is None or len(df) < 50: return 0
        
        alis_sinyalleri = (df['Close'] < df['SMA_200']) & (df['RSI'] < 40)
        df['Sinyal'] = np.where(alis_sinyalleri, 1, 0)
        
        df['Gelecek_Getiri'] = df['Close'].shift(-20) / df['Close'] - 1
        
        basarili_islemler = df[df['Sinyal'] == 1]['Gelecek_Getiri'] > 0
        win_rate = basarili_islemler.mean() * 100 if not basarili_islemler.empty else 50.0
        
        return round(win_rate, 1)

# --- 5. STRATEJİ MOTORU (KESKİN NİŞANCI MANTIĞI) ---
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
        fiyat = float(son_gun['Close'])
        rsi = float(son_gun['RSI'])
        sma_200 = float(son_gun['SMA_200'])
        sma_50 = float(son_gun['SMA_50'])
        bb_lower = float(son_gun['BB_Lower'])
        
        # SIFIRDAN BAŞLAYAN KATI SKORLAMA
        skor = 0 
        nedenler = []
        
        # 1. UZUN VADELİ İSKONTO (En Büyük Ağırlık)
        if fiyat < sma_200:
            fark_yuzde = ((sma_200 - fiyat) / sma_200) * 100
            if fark_yuzde > 15:
                skor += 40; nedenler.append(f"Derin İskonto (SMA200 altı %{int(fark_yuzde)})")
            elif fark_yuzde > 5:
                skor += 20; nedenler.append("Kısmi İskonto (SMA200 altı)")
        
        # 2. AŞIRI SATIM (Panik Fırsatı)
        if rsi < 35:
            skor += 30; nedenler.append(f"Aşırı Satım (RSI: {int(rsi)})")
        elif rsi < 45:
            skor += 15; nedenler.append("Soğumuş Bölge (RSI < 45)")
            
        # 3. KISA VADELİ DİP (Bollinger)
        if fiyat <= bb_lower * 1.02: # %2 opsiyon payı
            skor += 15; nedenler.append("Bollinger Alt Bandında")
            
        # 4. GÖRELİ GÜÇ (Düşerken bile piyasaya direnenler)
        xu100 = DataFetcher.endeks_verisi_getir()
        if xu100 is not None and len(gunluk) >= 60 and len(xu100) >= 60:
            hisse_getiri = (fiyat / gunluk['Close'].iloc[-60]) - 1
            endeks_getiri = (xu100['Close'].iloc[-1] / xu100['Close'].iloc[-60]) - 1
            if hisse_getiri > endeks_getiri:
                skor += 15; nedenler.append("Endeksten Pozitif Ayrışma")

        # 5. NEGATİF FİLTRELER (Ceza Puanları)
        if rsi > self.config.rsi_asiri_alim:
            skor -= 40; nedenler.append("Aşırı Alım / Şişkinlik")
        if fiyat > sma_200 * 1.20:
            skor -= 30; nedenler.append("Ortalamadan Çok Uzak (Pahalı)")
                
        skor = max(0, min(skor, 100))
        
        # SADECE 80 ÜSTÜ "🔥 KESİN TOPLA" ETİKETİ ALABİLİR
        if skor >= 80: karar = "🔥 KESİN TOPLA (Kriz İskontosu)"
        elif skor >= 60: karar = "🟢 KADEMELİ AL (Değer Bölgesi)"
        elif skor <= 30: karar = "🔴 PAHALI / UZAK DUR"
        else: karar = "⚪ NÖTR / İZLEMEDE"
            
        return {
            "Hisse": hisse_kodu.replace(".IS", ""), 
            "Karar": karar, 
            "Skor": f"%{skor}",
            "Veri Kaynağı": kaynak,
            "Fiyat (₺)": round(fiyat, 2), 
            "Maliyetlenme Seviyesi (₺)": round(bb_lower, 2),
            "Uzun Vade Trend": "POZİTİF" if fiyat > sma_200 else "İSKONTOLU",
            "Win Rate": f"%{win_rate}",
            "Fırsat Özeti": " | ".join(nedenler[:3]) if nedenler else "Yatay / Nötr",
            "Grafik_Verisi": gunluk[['Open', 'High', 'Low', 'Close', 'SMA_50', 'SMA_200']].tail(90)
        }

# --- 6. ARAYÜZ (UI) ---
def ui_olustur():
    st.title("🎯 Değer ve Temettü Odaklı Katılım Botu v10.1")
    st.markdown("Keskin Nişancı Algoritması ve Hibrit Veri Altyapısı Aktif. Sadece gerçek fırsatları filtreler.")
    st.markdown("---")

    st.sidebar.markdown("### 🏦 Portföy Parametreleri")
    toplam_sermaye = st.sidebar.number_input("Yönetilen Bakiye (₺)", min_value=10000, value=100000)

    config = BotConfig(rsi_asiri_satim=35, rsi_asiri_alim=70, sermaye=toplam_sermaye)
    strateji = QuantStrategy(config)

    piyasa_durumu = DataFetcher.piyasa_rejimi_kontrol()
    if piyasa_durumu == "BULL":
        st.sidebar.success("📊 BIST Genel Trendi: BOĞA")
    else:
        st.sidebar.warning("⚠️ BIST Genel Trendi: AYI (Toplama Fırsatı)")

    st.sidebar.markdown("### 🔍 Favori İzleme Listesi")
    varsayilan_hisseler = "MPARK\nBIMAS\nENJSA\nASELS\nLOGO\nTUPRS\nALBRK\nCIMSA\nYEOTK\nEBEBK"
    hisseler_metin = st.sidebar.text_area("Taranacak Hisseler:", varsayilan_hisseler, height=220)

    tablo_alani = st.container()
    firsat_alani = st.container()

    if st.sidebar.button("🚀 İzleme Listesini Tara", use_container_width=True):
        hisse_listesi = [h.strip().upper() for h in hisseler_metin.split("\n") if h.strip()]
        ilerleme = st.progress(0)
        sonuclar = []
        
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
                if "🔥" in str(val): return 'background-color: #1e4620; color: white; font-weight: bold;'
                elif "🟢" in str(val): return 'background-color: #388e3c; color: white;'
                elif "🔴" in str(val): return 'background-color: #b71c1c; color: white;'
                elif "⚪" in str(val): return 'background-color: #546e7a; color: white;'
                return ''
            
            with tablo_alani:
                st.markdown("### 📋 Genel Analiz Tablosu")
                st.dataframe(gosterim_df.style.map(tablo_renk, subset=['Karar']), use_container_width=True)
            
            with firsat_alani:
                # Kendi listende hem Kesin Topla hem Kademeli Al fırsatlarını gör
                toplama_firsatlari = [s for s in sonuclar if "🔥" in s["Karar"] or "🟢" in s["Karar"]]
                if toplama_firsatlari:
                    st.markdown("---")
                    st.markdown("### 🎯 DEĞER / İSKONTO BÖLGESİNDEKİ HİSSELER")
                    
                    sutunlar = st.columns(min(len(toplama_firsatlari), 3))
                    for idx, firsat in enumerate(toplama_firsatlari):
                        with sutunlar[idx % 3]:
                            arkaplan = "#1e4620" if "🔥" in firsat['Karar'] else "#2e7d32"
                            st.markdown(f"""
                            <div style="border: 2px solid #2e7d32; border-radius: 10px; padding: 15px; background-color: {arkaplan}; color: white; margin-bottom: 10px;">
                                <h2 style="text-align: center; color: #a5d6a7; margin-top: 0;">{firsat['Hisse']}</h2>
                                <h1 style="text-align: center; margin: 0;">{firsat['Skor']}</h1>
                                <p style="text-align: center; font-size: 14px; background-color: #1b5e20; border-radius: 5px; padding: 4px;"><b>{firsat['Karar']}</b></p>
                                <p style="text-align: center; font-size: 12px; margin-top: -5px;">{firsat['Fırsat Özeti']}</p>
                                <hr style="border-color: #4caf50;">
                                <p style="font-size: 15px;"><b>Güncel Fiyat:</b> {firsat['Fiyat (₺)']} ₺</p>
                                <p style="font-size: 15px; color: #81c784;"><b>Maliyetlenme Hedefi:</b> {firsat['Maliyetlenme Seviyesi (₺)']} ₺ civarı</p>
                                <p style="font-size: 11px; text-align: right; color: #c8e6c9;">{firsat['Veri Kaynağı']}</p>
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
            st.error("Veri çekilemedi. İş Yatırım ve Yahoo sunucuları yanıt vermiyor.")

    # --- 2. OTOMATİK FIRSAT RADARI ---
    st.markdown("### 📡 Katılım Endeksi Fırsat Radarı (Sadece Keskin Nişancı)")
    if st.button("🔍 Katılım Endeksindeki En Dip Hisseleri Bul", use_container_width=True):
        bist_katilim_hisseler = [
            "ALBRK", "ALFAS", "ASELS", "ASTOR", "BIMAS", "BRSAN", 
            "CANTE", "CIMSA", "CWENE", "DOAS", "EGEEN", "EKGYO", 
            "ENJSA", "ENKAI", "EUPWR", "FROTO", "GESAN", "GWIND", 
            "HEKTS", "JANTS", "KCAER", "KMPUR", "KONTR", 
            "KORDS", "KRDMD", "MIATK", "MPARK", 
            "OTKAR", "OYAKC", "QUAGR", "SASA", "SMRTG", "TTRAK", 
            "TUKAS", "VESBE", "YEOTK", "YUNSA"
        ]
        
        st.info("Algoritma devrede. Sadece ağır iskonto yemiş (Kriz İskontosu) hisseler aranıyor...")
        
        bulunan_firsatlar = []
        
        with ThreadPoolExecutor(max_workers=3) as executor:
            radar_sonuclari = executor.map(strateji.analiz_et, bist_katilim_hisseler)
            for sonuc in radar_sonuclari:
                # OTOMATİK TARAMADA FİLTRE ÇOK KATI: SADECE 🔥 KESİN TOPLA
                if sonuc and ("🔥" in sonuc["Karar"]):
                    bulunan_firsatlar.append(sonuc)
        
        if bulunan_firsatlar:
            st.success(f"🚨 Keskin Nişancı Radarı Tamamlandı: Kademeli Toplanabilecek {len(bulunan_firsatlar)} Nadide Fırsat Bulundu!")
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
                        <p style="font-size: 11px; text-align: right; color: #c8e6c9;">{firsat['Veri Kaynağı']}</p>
                    </div>
                    <br>
                    """, unsafe_allow_html=True)
        else:
            st.warning("Şu an için kriterlere uyan, dibin dibi bölgesinde (kriz iskontolu) bir hisse bulunamadı. Nakitte beklemek en iyisi.")

if __name__ == "__main__":
    ui_olustur()
