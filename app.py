import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import ta
import warnings
import logging
import plotly.graph_objects as go
from sklearn.ensemble import RandomForestClassifier
import datetime

warnings.filterwarnings('ignore')
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- SAYFA AYARLARI ---
st.set_page_config(page_title="Quant Terminal v7.0", page_icon="🏦", layout="wide")

# --- 0. GÜVENLİK VE OTURUM YÖNETİMİ ---
def oturum_baslat():
    if "giris_basarili" not in st.session_state: st.session_state["giris_basarili"] = False
    if "portfoy" not in st.session_state: st.session_state["portfoy"] = []

    if not st.session_state["giris_basarili"]:
        st.markdown("<h1 style='text-align: center;'>🔒 Sistem Erişimi</h1>", unsafe_allow_html=True)
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            with st.form("login_form"):
                girilen_sifre = st.text_input("Erişim Şifresi:", type="password")
                if st.form_submit_button("Sisteme Giriş Yap", use_container_width=True):
                    dogru_sifre = st.secrets.get("sistem_sifresi", "admin123")
                    if girilen_sifre == dogru_sifre:
                        st.session_state["giris_basarili"] = True
                        st.rerun()
                    else: st.error("🚨 Hatalı Şifre!")
        st.stop()

oturum_baslat()

if st.sidebar.button("🚪 Çıkış Yap", use_container_width=True):
    st.session_state["giris_basarili"] = False
    st.rerun()

# --- 1. YAPILANDIRMA ---
class BotConfig:
    def __init__(self, sermaye, komisyon, slippage):
        self.sermaye = sermaye
        self.komisyon = komisyon
        self.slippage = slippage

# --- 2. VERİ VE ÇOKLU ZAMAN DİLİMİ (MTF) ---
class DataFetcher:
    @staticmethod
    def veri_indir(hisse_kodu):
        try:
            ticker = yf.Ticker(hisse_kodu)
            gunluk_veri = ticker.history(period="2y", interval="1d")
            saatlik_veri = ticker.history(period="1mo", interval="1h") # YENİ: Saatlik Veri
            
            if gunluk_veri.empty or len(gunluk_veri) < 50: 
                return None, None, None, None
            
            info = ticker.info
            temel_veriler = {'fk': info.get('trailingPE', None), 'pd_dd': info.get('priceToBook', None)}
            
            son_hacim_degisimi = gunluk_veri['Volume'].pct_change().iloc[-1]
            duygu_skoru = np.clip(son_hacim_degisimi * 100, -100, 100)
            
            return gunluk_veri, saatlik_veri, temel_veriler, duygu_skoru
        except: return None, None, None, None

# --- 3. TEKNİK ANALİZ VE YAPAY ZEKA ---
class QuantModel:
    @staticmethod
    def gostergeleri_hesapla(df):
        kapanis, yuksek, dusuk = df['Close'], df['High'], df['Low']
        df['RSI'] = ta.momentum.RSIIndicator(close=kapanis).rsi()
        macd = ta.trend.MACD(close=kapanis)
        df['MACD_Line'], df['MACD_Signal'] = macd.macd(), macd.macd_signal()
        df['SMA_50'] = ta.trend.SMAIndicator(close=kapanis, window=50).sma_indicator()
        df['SMA_20'] = ta.trend.SMAIndicator(close=kapanis, window=20).sma_indicator()
        
        # Bollinger Bantları
        bollinger = ta.volatility.BollingerBands(close=kapanis, window=20, window_dev=2)
        df['BB_Ust'] = bollinger.bollinger_hband()
        df['BB_Alt'] = bollinger.bollinger_lband()
        
        df['ATR'] = ta.volatility.AverageTrueRange(high=yuksek, low=dusuk, close=kapanis).average_true_range()
        df['Std_Dev'] = kapanis.rolling(window=20).std()
        df['Z_Score'] = (kapanis - df['SMA_20']) / df['Std_Dev']
        df.dropna(inplace=True)
        return df

    @staticmethod
    def ml_tahmin_et(df):
        try:
            veri = df.copy()
            veri['Hedef'] = np.where(veri['Close'].shift(-1) > veri['Close'], 1, 0)
            veri.dropna(inplace=True)
            X = veri[['RSI', 'MACD_Line', 'Z_Score', 'Volume']]
            y = veri['Hedef']
            model = RandomForestClassifier(n_estimators=100, random_state=42, max_depth=5)
            model.fit(X, y)
            return round(model.predict_proba(df[['RSI', 'MACD_Line', 'Z_Score', 'Volume']].iloc[-1:])[0][1] * 100, 1)
        except: return 50.0

# --- 4. STRATEJİ MOTORU ---
class QuantStrategy:
    def __init__(self, config):
        self.config = config

    def analiz_et(self, hisse_kodu):
        gunluk, saatlik, temel, duygu = DataFetcher.veri_indir(hisse_kodu)
        if gunluk is None: return None
            
        gunluk = QuantModel.gostergeleri_hesapla(gunluk)
        if not saatlik.empty: saatlik = QuantModel.gostergeleri_hesapla(saatlik)
            
        ml_olasilik = QuantModel.ml_tahmin_et(gunluk)
        son_gun = gunluk.iloc[-1]
        fiyat = float(son_gun['Close'])
        
        skor = 0
        nedenler = []
        
        # Makine Öğrenmesi
        if ml_olasilik > 65: skor += 20; nedenler.append(f"AI: %{ml_olasilik} Yükseliş")
        elif ml_olasilik < 40: skor -= 20
            
        # Çoklu Zaman Dilimi (MTF) Koruması
        if not saatlik.empty:
            son_saat = saatlik.iloc[-1]
            if son_saat['RSI'] > 70: skor -= 25; nedenler.append("Saatlikte Zirvede (FOMO Riski)")
            elif son_saat['RSI'] < 40 and son_saat['MACD_Line'] > son_saat['MACD_Signal']: 
                skor += 15; nedenler.append("Saatlik Momentum Pozitif")

        # Günlük Trend ve Temeller
        if son_gun['MACD_Line'] > son_gun['MACD_Signal']: skor += 15
        if son_gun['Z_Score'] > 2: skor -= 30; nedenler.append("Fiyat Aşırı Şişmiş (Z>2)")
        if temel.get('fk') and 0 < temel.get('fk') < 15: skor += 15
        
        skor = max(0, min(skor, 100))
        if skor >= 80: karar = "🔥 KESİN AL"
        elif skor >= 60: karar = "🟢 POTANSİYEL AL"
        elif skor <= 30 or son_gun['RSI'] > 75: karar = "🔴 SAT / RİSKLİ"
        else: karar = "⚪ İZLEMEDE"
            
        return {
            "Hisse": hisse_kodu.replace(".IS", ""), 
            "Karar": karar, 
            "Skor": f"%{skor}",
            "Fiyat": round(fiyat, 2), 
            "Saf_Skor": skor,
            "Nedenler": " | ".join(nedenler[:3])
        }

# --- 5. GRAFİK ÇİZİCİ ---
def grafik_ciz(hisse_kodu):
    df, _, _, _ = DataFetcher.veri_indir(hisse_kodu + ".IS")
    if df is not None:
        df = QuantModel.gostergeleri_hesapla(df).tail(100)
        fig = go.Figure()
        # Mum Grafiği
        fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='Fiyat'))
        # Ortalamalar ve Bantlar
        fig.add_trace(go.Scatter(x=df.index, y=df['SMA_20'], line=dict(color='orange', width=1.5), name='SMA 20'))
        fig.add_trace(go.Scatter(x=df.index, y=df['SMA_50'], line=dict(color='blue', width=1.5), name='SMA 50'))
        fig.add_trace(go.Scatter(x=df.index, y=df['BB_Ust'], line=dict(color='gray', width=1, dash='dot'), name='BB Üst'))
        fig.add_trace(go.Scatter(x=df.index, y=df['BB_Alt'], line=dict(color='gray', width=1, dash='dot'), name='BB Alt'))
        
        fig.update_layout(title=f"{hisse_kodu} Teknik Analiz (Son 100 Gün)", template='plotly_dark', height=500, margin=dict(l=20, r=20, t=40, b=20))
        return fig
    return None

# --- 6. ANA ARAYÜZ (UI) ---
def ui_olustur():
    st.title("🏦 Quant Terminal v7.0")
    
    # YAN MENÜ
    st.sidebar.markdown("### ⚙️ Portföy Parametreleri")
    sermaye = st.sidebar.number_input("Yönetilen Bakiye (₺)", min_value=10000, value=100000)
    komisyon = st.sidebar.number_input("Komisyon Oranı (%)", value=0.1) / 100
    slippage = st.sidebar.number_input("Kayma Oranı (%)", value=0.2) / 100
    config = BotConfig(sermaye, komisyon, slippage)
    strateji = QuantStrategy(config)

    # SEKMELER (TABS)
    tab1, tab2, tab3 = st.tabs(["🔍 Tarama & Radar", "💼 Sanal Portföy", "📈 Grafikler"])

    # --- TAB 1: RADAR ---
    with tab1:
        st.markdown("### 📡 Dinamik Sektörel Radar")
        endeks_secimi = st.selectbox("Taranacak Endeksi Seçin:", ["BIST 30 (Ana Tahtalar)", "BIST Bankacılık (XBANK)", "BIST Teknoloji (XUTEK)"])
        
        endeksler = {
            "BIST 30 (Ana Tahtalar)": ["AKBNK.IS", "ASELS.IS", "BIMAS.IS", "EREGL.IS", "FROTO.IS", "GARAN.IS", "ISCTR.IS", "KCHOL.IS", "SAHOL.IS", "SISE.IS", "THYAO.IS", "TUPRS.IS", "YKBNK.IS"],
            "BIST Bankacılık (XBANK)": ["AKBNK.IS", "GARAN.IS", "HALKB.IS", "ISCTR.IS", "VAKBN.IS", "YKBNK.IS", "SKBNK.IS", "TSKB.IS"],
            "BIST Teknoloji (XUTEK)": ["ASELS.IS", "LOGO.IS", "ARDYZ.IS", "MIATK.IS", "KFEIN.IS", "PAPIL.IS"]
        }
        
        if st.button("🚀 Seçili Endeksi Tara", use_container_width=True):
            hedef_hisseler = endeksler[endeks_secimi]
            ilerleme = st.progress(0)
            bulunanlar = []
            
            for i, hisse in enumerate(hedef_hisseler):
                sonuc = strateji.analiz_et(hisse)
                if sonuc and sonuc['Saf_Skor'] >= 60:  # Potansiyel veya Kesin Al
                    bulunanlar.append(sonuc)
                ilerleme.progress((i + 1) / len(hedef_hisseler))
            ilerleme.empty()
            
            if bulunanlar:
                st.success(f"{len(bulunanlar)} adet fırsat bulundu!")
                cols = st.columns(3)
                for idx, f in enumerate(bulunanlar):
                    with cols[idx % 3]:
                        st.markdown(f"""
                        <div style="border: 1px solid #4caf50; border-radius: 8px; padding: 10px; background-color: #1e4620;">
                            <h3 style="margin:0; color:#a5d6a7;">{f['Hisse']}</h3>
                            <h2 style="margin:0;">{f['Fiyat']} ₺</h2>
                            <p style="margin:0; font-size:14px;">Skor: <b>{f['Skor']}</b> ({f['Karar']})</p>
                            <p style="margin:0; font-size:12px; color:#c8e6c9;">{f['Nedenler']}</p>
                        </div><br>
                        """, unsafe_allow_html=True)
                        
                        # Portföye Ekleme Butonu
                        if st.button(f"💼 {f['Hisse']} Al", key=f"al_{f['Hisse']}"):
                            st.session_state["portfoy"].append({
                                "hisse": f['Hisse'],
                                "maliyet": f['Fiyat'],
                                "lot": 100, # Şimdilik sabit 100 lot simülasyonu
                                "tarih": datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
                            })
                            st.toast(f"{f['Hisse']} portföye eklendi!", icon="✅")
            else:
                st.warning("Bu endekste şu an güçlü bir alım fırsatı bulunamadı.")

    # --- TAB 2: SANAL PORTFÖY ---
    with tab2:
        st.markdown("### 💼 Açık Pozisyonlarım (Paper Trading)")
        if len(st.session_state["portfoy"]) == 0:
            st.info("Henüz portföyünüzde hisse bulunmuyor. Radar sekmesinden hisse ekleyebilirsiniz.")
        else:
            portfoy_verileri = []
            toplam_kar_zarar = 0
            
            for pozisyon in st.session_state["portfoy"]:
                try:
                    # Canlı fiyatı çek
                    anlik_fiyat = yf.Ticker(pozisyon["hisse"] + ".IS").history(period="1d")['Close'].iloc[-1]
                    kar_zarar_orani = ((anlik_fiyat - pozisyon["maliyet"]) / pozisyon["maliyet"]) * 100
                    kar_zarar_tl = (anlik_fiyat - pozisyon["maliyet"]) * pozisyon["lot"]
                    toplam_kar_zarar += kar_zarar_tl
                    
                    portfoy_verileri.append({
                        "Hisse": pozisyon["hisse"],
                        "Maliyet (₺)": round(pozisyon["maliyet"], 2),
                        "Anlık Fiyat (₺)": round(anlik_fiyat, 2),
                        "Lot": pozisyon["lot"],
                        "Kâr/Zarar (%)": f"%{round(kar_zarar_orani, 2)}",
                        "Kâr/Zarar (₺)": round(kar_zarar_tl, 2)
                    })
                except: pass
                
            df_portfoy = pd.DataFrame(portfoy_verileri)
            st.dataframe(df_portfoy, use_container_width=True)
            
            # P&L Özeti
            renk = "green" if toplam_kar_zarar >= 0 else "red"
            st.markdown(f"<h3 style='color:{renk};'>Toplam Açık Kâr/Zarar (P&L): {round(toplam_kar_zarar, 2)} ₺</h3>", unsafe_allow_html=True)
            
            if st.button("🗑️ Portföyü Temizle"):
                st.session_state["portfoy"] = []
                st.rerun()

    # --- TAB 3: GRAFİKLER ---
    with tab3:
        st.markdown("### 📈 Gelişmiş Grafik İnceleme")
        incelenecek_hisse = st.text_input("Grafiğini görmek istediğiniz hisse kodunu yazın (Örn: ASELS):", value="THYAO")
        if st.button("Grafiği Getir"):
            fig = grafik_ciz(incelenecek_hisse)
            if fig:
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.error("Grafik verisi çekilemedi.")

if __name__ == "__main__":
    ui_olustur()
