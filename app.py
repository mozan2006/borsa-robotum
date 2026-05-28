import streamlit as st
import yfinance as yf
import pandas as pd
import ta
import warnings
import plotly.graph_objects as go
from concurrent.futures import ThreadPoolExecutor, as_completed

warnings.filterwarnings('ignore')

# --- SAYFA AYARLARI ---
st.set_page_config(page_title="Ultimate Quant Bot", page_icon="📈", layout="wide")

st.title("🤖 Borsa Analiz ve Karar Robotu v2.0")
st.markdown("Bu sistem, hisseleri teknik ve temel olarak inceler, dinamik al/sat hedefleri belirler.")

# --- 1. GÜVENLİK: TAMAMEN GİZLİ ŞİFRE KORUMASI ---
# Şifre artık kodun içinde yazmıyor, sadece Streamlit Secrets üzerinden çekiliyor.
try:
    beklenen_sifre = st.secrets["sistem_sifresi"]
except KeyError:
    st.error("🚨 Sistem Hatası: Şifre ayarlanmamış! Lütfen Streamlit Cloud üzerinden 'Secrets' bölümüne 'sistem_sifresi' değerini ekleyin.")
    st.stop()

girilen_sifre = st.sidebar.text_input("Sisteme Giriş Şifresi:", type="password")

if girilen_sifre != beklenen_sifre:
    st.sidebar.warning("Sistemi kullanmak için doğru şifreyi girmelisiniz.")
    st.stop()

st.sidebar.success("Giriş Başarılı! ✅")

# --- DİNAMİK STRATEJİ AYARLARI ---
st.sidebar.markdown("### ⚙️ Strateji Ayarları")
rsi_al_siniri = st.sidebar.slider("RSI Alım Sınırı (Aşırı Satım)", 20, 50, 40)
rsi_sat_siniri = st.sidebar.slider("RSI Satım Sınırı (Aşırı Alım)", 60, 90, 75)
atr_stop_carpani = st.sidebar.slider("Stop-Loss ATR Çarpanı", 1.0, 5.0, 1.5, step=0.1)
atr_kar_carpani = st.sidebar.slider("Kar-Al ATR Çarpanı", 1.0, 10.0, 3.0, step=0.1)

# --- 2. VERİ ÇEKME VE HATA YÖNETİMİ ---
@st.cache_data(ttl=3600)
def veri_indir(hisse_kodu):
    try:
        veri = yf.download(hisse_kodu, period="2y", interval="1d", progress=False)
        if veri.empty or len(veri) < 50: 
            return None, None
            
        if isinstance(veri.columns, pd.MultiIndex): 
            veri.columns = veri.columns.droplevel(1)
        
        info = yf.Ticker(hisse_kodu).info
        fk = info.get('trailingPE', None)
        
        return veri, fk
    except Exception as e:
        print(f"Hata ({hisse_kodu}): Veri indirilemedi. Detay: {e}")
        return None, None

# --- 3. MODÜLERLİK: GÖSTERGELERİ HESAPLAMA ---
def gostergeleri_hesapla(veri):
    kapanis = veri['Close']
    hacim = veri['Volume']
    yuksek = veri['High']
    dusuk = veri['Low']
    
    veri['RSI'] = ta.momentum.RSIIndicator(close=kapanis, window=14).rsi()
    macd = ta.trend.MACD(close=kapanis)
    veri['MACD_Line'] = macd.macd()
    veri['MACD_Signal'] = macd.macd_signal()
    veri['SMA_200'] = ta.trend.SMAIndicator(close=kapanis, window=200).sma_indicator()
    veri['SMA_20'] = ta.trend.SMAIndicator(close=kapanis, window=20).sma_indicator()
    veri['SMA_50'] = ta.trend.SMAIndicator(close=kapanis, window=50).sma_indicator()
    
    atr_ind = ta.volatility.AverageTrueRange(high=yuksek, low=dusuk, close=kapanis, window=14)
    veri['ATR'] = atr_ind.average_true_range()
    veri['Hacim_Ort_20'] = hacim.rolling(window=20).mean()
    
    bollinger = ta.volatility.BollingerBands(close=kapanis, window=20, window_dev=2)
    veri['BB_Alt'] = bollinger.bollinger_lband()
    
    # Eksik verileri (NaN) temizle
    veri.dropna(inplace=True)
    return veri

# --- MODÜLERLİK & FİNANSAL MANTIK: SKORLAMA ---
def skor_hesapla(son_durum, fk_orani, fiyat, rsi):
    skor = 0
    nedenler = []
    
    if fiyat > son_durum['SMA_200']: skor += 15; nedenler.append("Uzun Vade Trend Pozitif")
    if son_durum['SMA_20'] > son_durum['SMA_50']: skor += 15; nedenler.append("Kısa Vade Trend Güçlü")
    if rsi < rsi_al_siniri: skor += 20; nedenler.append("Ucuz/Düzeltmede")
    if son_durum['MACD_Line'] > son_durum['MACD_Signal']: skor += 15; nedenler.append("MACD Alımda")
    if son_durum['Volume'] > son_durum['Hacim_Ort_20']: skor += 15; nedenler.append("Hacim Onaylı")
    if fiyat <= son_durum['BB_Alt'] * 1.02: skor += 20; nedenler.append("Alt Bant Tepkisi")
    
    # Gelişmiş Temel Analiz Filtresi
    if fk_orani is not None:
        if fk_orani > 50:
            skor -= 15
            nedenler.append("Pahalı (Yüksek F/K)")
        elif fk_orani < 0:
            skor -= 25 # Zarar eden şirketi daha sert cezalandır
            nedenler.append("Zarar Ediyor (Negatif F/K)")
            
    return max(0, skor), nedenler

# --- ANA ORKESTRATÖR ---
def nihai_analiz(hisse_kodu):
    veri, fk_orani = veri_indir(hisse_kodu)
    if veri is None or veri.empty: return None
        
    try:
        veri = gostergeleri_hesapla(veri)
        if veri.empty: return None 
            
        son_durum = veri.iloc[-1]
        fiyat = float(son_durum['Close'])
        rsi = float(son_durum['RSI'])
        atr = float(son_durum['ATR'])
        
        stop_loss = fiyat - (atr * atr_stop_carpani)
        kar_al = fiyat + (atr * atr_kar_carpani)
        
        risk = fiyat - stop_loss
        odul = kar_al - fiyat
        rrr = odul / risk if risk > 0 else 0
        
        skor, nedenler = skor_hesapla(son_durum, fk_orani, fiyat, rsi)
        
        if skor >= 80: karar = "🔥 KESİN AL"
        elif skor >= 60: karar = "🟢 POTANSİYEL AL"
        elif rsi > rsi_sat_siniri: karar = "🔴 SAT / RİSKLİ"
        else: karar = "⚪ İZLEMEDE"
            
        return {
            "Hisse": hisse_kodu.replace(".IS", ""), 
            "Fiyat (₺)": round(fiyat, 2), 
            "F/K": round(fk_orani, 2) if fk_orani else "Bilinmiyor",
            "Skor": f"%{skor}", 
            "Karar": karar, 
            "Stop-Loss": round(stop_loss, 2), 
            "Hedef (Kar Al)": round(kar_al, 2), 
            "R/R Oranı": round(rrr, 2),
            "Nedenler": ", ".join(nedenler) if nedenler else "Kriter Yok"
        }
    except Exception as e:
        print(f"Hata ({hisse_kodu}) analiz sürecinde: {e}")
        return None

# --- TABLO RENKLENDİRME ---
def tabloyu_renklendir(val):
    if "🔥 KESİN AL" in str(val): return 'background-color: #1e4620; color: white; font-weight: bold;'
    elif "🟢 POTANSİYEL AL" in str(val): return 'background-color: #2e7d32; color: white;'
    elif "🔴 SAT / RİSKLİ" in str(val): return 'background-color: #b71c1c; color: white; font-weight: bold;'
    elif "⚪ İZLEMEDE" in str(val): return 'background-color: #424242; color: white;'
    return ''

# --- 5. UI/UX: GRAFİK ÇİZİMİ (PLOTLY) ---
def grafik_ciz(hisse_kodu):
    veri, _ = veri_indir(hisse_kodu + ".IS")
    if veri is not None and not veri.empty:
        # Son 120 günü göster
        veri = veri.tail(120)
        fig = go.Figure(data=[go.Candlestick(x=veri.index,
                        open=veri['Open'], high=veri['High'],
                        low=veri['Low'], close=veri['Close'],
                        name="Fiyat")])
        
        fig.update_layout(
            title=f"{hisse_kodu} - Son 120 Günlük Fiyat Hareketi",
            yaxis_title="Fiyat (₺)",
            xaxis_title="Tarih",
            template="plotly_dark",
            margin=dict(l=0, r=0, t=40, b=0)
        )
        st.plotly_chart(fig, use_container_width=True)

# --- ARAYÜZ VE UYGULAMA MANTIĞI ---
varsayilan_hisseler = "THYAO\nASELS\nTUPRS\nISCTR\nKCHOL\nSISE\nBIMAS\nAKSA\nENKAI"
st.sidebar.markdown("---")
hisseler_metin = st.sidebar.text_area("Hisse Kodlarını Alt Alta Yazın:", varsayilan_hisseler, height=200)

if st.sidebar.button("🚀 Analizi Başlat"):
    hisse_listesi = [h.strip().upper() + ".IS" for h in hisseler_metin.split("\n") if h.strip()]
    
    # 4. PERFORMANS: ASENKRON VERİ ÇEKME (ThreadPoolExecutor)
    with st.spinner('Piyasa verileri asenkron olarak çekiliyor ve analiz ediliyor...'):
        sonuclar = []
        with ThreadPoolExecutor(max_workers=10) as executor:
            gelecek_sonuclar = {executor.submit(nihai_analiz, hisse): hisse for hisse in hisse_listesi}
            for future in as_completed(gelecek_sonuclar):
                analiz = future.result()
                if analiz:
                    sonuclar.append(analiz)
        
        if sonuclar:
            df = pd.DataFrame(sonuclar)
            
            # Puanına göre büyükten küçüğe sırala
            df['Saf Skor'] = df['Skor'].apply(lambda x: int(x.replace('%', '')))
            df = df.sort_values(by='Saf Skor', ascending=False).drop(columns=['Saf Skor'])
            
            st.success("✅ Analiz Tamamlandı!")
            
            styled_df = df.style.map(tabloyu_renklendir, subset=['Karar'])
            st.dataframe(styled_df, use_container_width=True)
            
            st.markdown("---")
            
            # Etkileşimli Grafik Alanı
            st.markdown("### 📊 Teknik Görünüm")
            st.markdown("Tablodaki hisselerden birini seçerek detaylı mum grafiğini inceleyebilirsiniz.")
            secilen_hisse = st.selectbox("Grafiğini görmek istediğiniz hisseyi seçin:", df["Hisse"].tolist())
            if secilen_hisse:
                grafik_ciz(secilen_hisse)
            
            st.markdown("---")
            csv = df.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 Sonuçları CSV (Excel) Olarak İndir",
                data=csv,
                file_name='hisse_analizi_raporu.csv',
                mime='text/csv',
            )
        else:
            st.error("Veri çekilemedi. Lütfen hisse kodlarını kontrol edin (Bağlantı sorunu olabilir).")
