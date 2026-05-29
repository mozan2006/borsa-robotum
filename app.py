import streamlit as st
yfinance'ı yf olarak içe aktar
pandas'ı pd olarak içe aktar
ithalat ta
ithalat uyarıları
içe aktarma günlüğü
import plotly.graph_objects as go

uyarılar.filtreuyarıları('yoksay')
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- SAYFA AYARLARI ---
st.set_page_config(page_title="Ultimate Quant Bot v3.1", page_icon="ğŸ“ˆ", layout="wide")

# --- 1. YAPILANDIRMA SINIFI (CONFIG) ---
BotConfig sınıfı:
    def __init__(self, rsi_al, rsi_sat, atr_stop, atr_kar, sermaye, risk_orani):
        self.rsi_al = rsi_al
        self.rsi_sat = rsi_sat
        self.atr_stop = atr_stop
        self.atr_kar = atr_kar
        self.sermaye = sermaye
        kendi.risk_orani = risk_orani

# --- 2. VERÄ° YÜ–NETÄ°MÄ° SINIFI ---
DataFetcher sınıfı:
    @statik yöntem
    def veri_indir(hisse_kodu):
        denemek:
            onay işareti = yf.Ticker(hisse_kodu)
            # History() yöntemi, download'a göre daha stabil ve MultiIndex sorunu yaratmaz.
            # Haftalık veriyi 5 yıl alıyor ki SMA_50 sorunsuz hesaplansın.
            Gunluk_veri = ticker.history(period="2y", interval="1d")
            haftalik_veri = ticker.history(dönem = "5 yıl", aralık = "1 hafta")
            
            gunluk_veri.empty veya haftalik_veri.empty veya len(haftalik_veri) < 50 ise:
                None, None, None döndür
            
            bilgi = ticker.info
            fk = info.get('trailingPE', None)
            
            gunluk_veri, haftalik_veri, fk'a dön
        e istisnası hariç:
            logging.error(f"Veri Çekme Hatası ({hisse_kodu}): {e}")
            None, None, None döndür

# --- 3. TEKNİK ANALİZ SINIFI ---
TeknikAnalizci sınıfı:
    @statik yöntem
    def gostergeleri_hesapla(veri, periyot="gunluk"):
        df = veri.copy()
        kapanis = df['Close']
        hacim = df['Hacim']
        yuksek = df['High']
        dusuk = df['Düşük']
        
        # Haftalık periyotta sadece ana trend analizi yapıyoruz
        if periyot == "haftalik":
            df['SMA_50'] = ta.trend.SMAIndicator(close=kapanis, window=50).sma_indicator()
        
        # Günlük periyotta detaylÄ± al-sat göstergeleri hesaplanyor
        elif periyot == "gunluk":
            df['RSI'] = ta.momentum.RSIIndicator(close=kapanis, window=14).rsi()
            macd = ta.trend.MACD(kapat=kapanis)
            df['MACD_Line'] = macd.macd()
            df['MACD_Signal'] = macd.macd_signal()
            df['SMA_200'] = ta.trend.SMAIndicator(close=kapanis, window=200).sma_indicator()
            df['SMA_50'] = ta.trend.SMAIndicator(close=kapanis, window=50).sma_indicator()
            df['SMA_20'] = ta.trend.SMAIndicator(close=kapanis, window=20).sma_indicator()
            
            atr_ind = ta.volatility.AverageTrueRange(high=yuksek, low=dusuk, close=kapanis, window=14)
            df['ATR'] = atr_ind.average_true_range()
            df['Hacim_Ort_20'] = hacim.rolling(window=20).mean()
            
            bollinger = ta.volatility.BollingerBands(close=kapanis, window=20, window_dev=2)
            df['BB_Alt'] = bollinger.bollinger_lband()
        
        df.dropna(inplace=True)
        df'yi döndür

# --- 4. STRATEJÄ° VE RÄ°SK YÃ–NETÄ°MÄ° SINIFI ---
QuantStrategy sınıfı:
    def __init__(self, config):
        self.config = config

    def pozisyon_buyuklugu_hesapla(self, fiyat, stop_loss):
        risk_miktari = self.config.sermaye * self.config.risk_orani
        his_basina_risk = fiyat - stop_loss
        
        eğer hisse_basina_risk <= 0 ise, 0 döndür
        alinacak_lot = int(risk_miktari / his_basina_risk)
        alinacak_lot'u döndür

    def analiz_et(self, his_kodu):
        günlük, haftalık, fk_orani = DataFetcher.veri_indir(hisse_kodu)
        Eğer Gunluk veya Haftalık boşsa, None döndür.
            
        gunluk = TeknikAnalyzer.gostergeleri_hesapla(gunluk, periyot="gunluk")
        haftalik = TeknikAnalyzer.gostergeleri_hesapla(haftalik, periyot=”haftalik”)
        
        Eğer gunluk.empty veya haftalik.empty ise None döndür.
            
        son_gunluk = gunluk.iloc[-1]
        son_haftalik = haftalik.iloc[-1]
        
        fiyat = float(son_gunluk['Kapat'])
        rsi = float(son_gunluk['RSI'])
        atr = float(son_gunluk['ATR'])
        
        stop_loss = fiyat - (atr * self.config.atr_stop)
        kar_al = fiyat + (atr * self.config.atr_kar)
        
        skor = 0
        nedenler = []
        
        # Oklu Zaman Dilimi Kontrolü (Haftalıç Trend)
        if son_haftalik['Kapat'] > son_haftalik['SMA_50']:
            skor += 25
            nedenler.append("Haftalıç Trend Yükselişte")
        başka:
            nedenler.append("Haftalıç Trend Günü")

        # Günlük Kriterler
        if fiyat > son_gunluk['SMA_200']: skor += 15; nedenler.append("200G Ort. Boyutunda")
        if rsi < self.config.rsi_al: skor += 20; nedenler.append("RSI Aşkı Satarım")
        if son_gunluk['MACD_Line'] > son_gunluk['MACD_Signal']: skor += 15; nedenler.append("MACD Alımda")
        if son_gunluk['Volume'] > son_gunluk['Hacim_Ort_20']: skor += 15; nedenler.append("Hacım Artış")
        if fiyat <= son_gunluk['BB_Alt'] * 1.02: skor += 10; nedenler.append("BB Alt Bant")
        
        # Temel Analiz Filtresi
        eğer fk_orani:
            fk_orani > 50 ise: skor -= 15; nedenler.append("PahalÄ± (F/K Yüksek)")
            elif fk_orani < 0: skor -= 25; nedenleri.append("Zarar Ediyor")
                
        skor = max(0, skor)
        
        if skor >= 80: karar = "ğŸ”¥ KEŞİN AL"
        elif skor >= 60: karar = "ğŸŸ¢ POTANSIYEL AL"
        elif rsi > self.config.rsi_sat: karar = "ğŸ”´ SAT / RÄ°SKLÄ°"
        else: karar = "âšª İZLEMEDE"
            
        lot_sayisi = self.pozisyon_buyuklugu_hesapla(fiyat, stop_loss) if "AL" in karar else 0
        sermaye_kullanimi = round((lot_sayisi * fiyat), 2)
            
        geri dönmek {
            "Hisse": his_kodu.replace(".IS", ""),
            "Fiyat (â‚º)": yuvarlak(fiyat, 2),
            "Skor": f"%{skor}",
            "Karar": karar,
            "Önerilen Lot": lot_sayisi,
            "Sermaye Gerekli (â‚º)": sermaye_kullanımı,
            "Zarar Durdurma (â‚º)": round(zarar durdurma, 2),
            "Hedef (â‚º)": yuvarlak(kar_al, 2),
            "Nedenler": " | ".join(nedenler)
        }

# --- 5. ARAYÜZ (UI) MANTIK ---
def ui_olustur():
    st.title("ğŸ¤– Profesyonel Quant Bot v3.1")
    st.markdown("Hız sınırlarına takılmayan asenkron analiz, Şoklu zaman dilimi ve OOP mimarisi.")

    # ÅžÄ°FRE KONTROLÃœ (Streamlit Cloud iÃ§in)
    denemek:
        beklenen_sifre = st.secrets["sistem_sifresi"]
    KeyError hariç:
        st.error("ğŸš¨ Sistem Hatası: Åžifre ayarlanmamÄ±ÅŸ! Streamlit Settings -> Secrets bÃ¶lÃ¼mÃ¼ne 'sistem_sifresi' ekleyin.")
        st.stop()

    girilen_sifre = st.sidebar.text_input("Sisteme Giriş Şifresi:", type="password")
    if girilen_sifre != beklenen_sifre:
        st.sidebar.warning("Sistemi kullanmak için doğru şekilde ifreyi girmelisiniz.")
        st.stop()
    st.sidebar.success("GiriŸ BaŸarālā! âœ…")

    st.sidebar.markdown("### âš™ï¸ Portföy ve Risk AyarlarıÄ±")
    toplam_sermaye = st.sidebar.number_input("Toplam Sermaye (â‚º)", min_value=10000, value=100000, step=10000)
    risk_yuzdesi = st.sidebar.slider("Alt Risk (%)", 0.5, 5.0, 1.0, step=0.1) / 100

    st.sidebar.markdown("### ğŸ“Š Teknik Strateji AyarlarıÄ±")
    rsi_al = st.sidebar.slider("RSI AlÄ±m SÄ±nÄ±rÄ±", 20, 50, 40)
    rsi_sat = st.sidebar.slider("RSI Satām Sānārā", 60, 90, 75)
    atr_stop = st.sidebar.slider("Stop-Loss ATR Ã‡arpanÄ±", 1.0, 5.0, 1.5, step=0.1)
    atr_kar = st.sidebar.slider("Kar-Al ATR Ã‡arpanÄ±", 1.0, 10.0, 3.0, adım=0.1)

    config = BotConfig(rsi_al, rsi_sat, atr_stop, atr_kar, toplam_sermaye, risk_yuzdesi)
    strateji = QuantStrategy(config)

    varsayilan_hisseler = "THYAO\nASELS\nTUPRS\nISCTR\nKCHOL\nSISE\nBIMAS\nAKSA\nENKAI"
    st.sidebar.markdown("---")
    hisler_metin = st.sidebar.text_area("Hisse Kodları (Alt Alta):", varsayilan_hisseler, height=150)

    if st.sidebar.button("ğŸš€ Analizi BaŸlat"):
        his_listesi = [h.strip().upper() + ".IS" for h in hisler_metin.split("\n") if h.strip()]
        
        st.info("Piyasa verileri analiz ediliyor, lütfen bekleyin...")
        ilerleme_cubugu = st.ilerleme(0)
        durum_metni = st.empty()
        
        sonuclar = []
        toplam_hisse = len(hisse_listesi)
        
        # Yahoo IP engeline takālmamak iāin dÃ¶ngÃ¼sel (sequential) iŸlem
        i için, numaralandırmada tıslama(hisse_listesi):
            durum_metni.text(f"Analiz yapılıyor: {hisse} ({i+1}/{toplam_hisse})")
            
            analiz = strateji.analiz_et(hisse)
            eğer analiz:
                sonuclar.append(analiz)
                
            ilerleme_cubugu.progress((i + 1) / toplam_hisse)
        
        durum_metni.empty() # Bitince metnini temizle
        
        eğer sonuclar:
            df = pd.DataFrame(sonuclar)
            df['Saf Skor'] = df['Skor'].apply(lambda x: int(x.replace('%', '')))
            df = df.sort_values(by='Saf Skor', ascending=False).drop(columns=['Saf Skor'])
            
            st.success("âœ… Analiz ve Risk HesaplamalarÄ± TamamlandÄ±!")
            
            def tabloyu_renklendir(val):
                if "ğŸ”¥ KESÄ°N AL" in str(val): return 'background-color: #1e4620; color: white; font-weight: bold;'
                elif "ğŸŸ¢ POTANSÄ°YEL AL" in str(val): return 'background-color: #2e7d32; color: white;'
                elif "ğŸ"´ SAT" in str(val): return 'background-color: #b71c1c; color: white;'
                geri dönmek ''
                
            st.dataframe(df.style.map(tabloyu_renklendir, subset=['Karar']), use_container_width=True)
            
            st.markdown("---")
            st.markdown("### ğŸ“ˆ Hüzünlü Grafik İşleme")
            secilen_hisse = st.selectbox("Detayın görmek istediniz hisyi seğin:", df["Hisse"].tolist())
            secilen_hisse ise:
                veri, _, _ = DataFetcher.veri_indir(secilen_hisse + ".IS")
                Eğer veri boş değilse:
                    veri = veri.tail(120)
                    fig = go.Figure(data=[go.Candlestick(x=veri.index, open=veri['Open'], high=veri['High'], low=veri['Low'], close=veri['Close'], name="Fiyat")])
                    fig.update_layout(title=f"{secilen_hisse} - Son 120 GÃ¼n", template="plotly_dark", margin=dict(l=0, r=0, t=40, b=0))
                    st.plotly_chart(fig, use_container_width=True)
        başka:
            st.error("Veri Ã§ekilmedi. BaÄŸlantÄ± sorunu olabilir veya hisler Ã§ok yeni olabilir.")

Eğer __name__ == "__main__" ise:
    ui_olustur()
