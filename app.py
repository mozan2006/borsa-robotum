import streamlit as st
import yfinance as yf
import pandas as pd
import ta
import warnings

warnings.filterwarnings('ignore')

# --- SAYFA AYARLARI VE ŞİFRE KORUMASI ---
st.set_page_config(page_title="Ultimate Quant Bot", page_icon="📈", layout="wide")

st.title("🤖 Borsa Analiz ve Karar Robotu")
st.markdown("Bu sistem, hisseleri teknik olarak inceler ve dinamik al/sat hedefleri belirler.")

# Güvenlik Şifresi (Buradaki "1234" yazan yeri kendi şifrenle değiştirebilirsin)
girilen_sifre = st.sidebar.text_input("Sisteme Giriş Şifresi:", type="password")

if girilen_sifre != "mozan@2006":
    st.sidebar.warning("Sistemi kullanmak için şifre girmelisiniz.")
    st.stop() # Şifre yanlışsa kodun aşağısını çalıştırmaz, sistemi kilitler.

st.sidebar.success("Giriş Başarılı! ✅")

# --- ANALİZ MOTORU ---
def nihai_analiz(hisse_kodu):
    try:
        veri = yf.download(hisse_kodu, period="2y", interval="1d", progress=False)
        if veri.empty or len(veri) < 50: return None
        if isinstance(veri.columns, pd.MultiIndex): veri.columns = veri.columns.droplevel(1)
            
        kapanis = veri['Close']
        hacim = veri['Volume']
        yuksek = veri['High']
        dusuk = veri['Low']
        
        veri['RSI'] = ta.momentum.RSIIndicator(close=kapanis, window=14).rsi()
        macd = ta.trend.MACD(close=kapanis)
        veri['MACD_Line'] = macd.macd()
        veri['MACD_Signal'] = macd.macd_signal()
        veri['SMA_200'] = ta.trend.SMAIndicator(close=kapanis, window=200).sma_indicator()
        
        atr_ind = ta.volatility.AverageTrueRange(high=yuksek, low=dusuk, close=kapanis, window=14)
        veri['ATR'] = atr_ind.average_true_range()
        veri['Hacim_Ort_20'] = hacim.rolling(window=20).mean()
        
        bollinger = ta.volatility.BollingerBands(close=kapanis, window=20, window_dev=2)
        veri['BB_Alt'] = bollinger.bollinger_lband()
        
        son_durum = veri.iloc[-1]
        fiyat = son_durum['Close']
        rsi = son_durum['RSI']
        atr = son_durum['ATR']
        
        stop_loss = fiyat - (atr * 1.5)
        kar_al = fiyat + (atr * 3.0)
        
        skor = 0
        nedenler = []
        
        if fiyat > son_durum['SMA_200']: skor += 20; nedenler.append("Trend Pozitif")
        if rsi < 40: skor += 20; nedenler.append("Ucuz/Düzeltmede")
        if son_durum['MACD_Line'] > son_durum['MACD_Signal']: skor += 20; nedenler.append("MACD Alımda")
        if son_durum['Volume'] > son_durum['Hacim_Ort_20']: skor += 20; nedenler.append("Hacim Onaylı")
        if fiyat <= son_durum['BB_Alt'] * 1.02: skor += 20; nedenler.append("Alt Bant Tepkisi")

        if skor >= 80: karar = "🔥 KESİN AL"
        elif skor == 60: karar = "🟢 POTANSİYEL AL"
        elif rsi > 75: karar = "🔴 SAT / RİSKLİ"
        else: karar = "⚪ İZLEMEDE"
            
        return {"Hisse": hisse_kodu.replace(".IS",""), "Fiyat (₺)": round(fiyat, 2), "Skor": f"%{skor}", "Karar": karar, "Stop-Loss": round(stop_loss, 2), "Hedef (Kar Al)": round(kar_al, 2), "Nedenler": ", ".join(nedenler) if nedenler else "Kriter Yok"}
    except Exception:
        return None

# --- KULLANICI ARAYÜZÜ ---
varsayilan_hisseler = "THYAO\nASELS\nTUPRS\nISCTR\nKCHOL\nSISE\nBIMAS\nAKSA\nENKAI"
hisseler_metin = st.sidebar.text_area("Hisse Kodlarını Alt Alta Yazın:", varsayilan_hisseler, height=200)

if st.sidebar.button("🚀 Analizi Başlat"):
    hisse_listesi = [h.strip().upper() + ".IS" for h in hisseler_metin.split("\n") if h.strip()]
    
    with st.spinner('Piyasa verileri çekiliyor ve analiz ediliyor... Lütfen bekleyin.'):
        sonuclar = []
        for hisse in hisse_listesi:
            analiz = nihai_analiz(hisse)
            if analiz:
                sonuclar.append(analiz)
        
        if sonuclar:
            df = pd.DataFrame(sonuclar)
            st.success("✅ Analiz Tamamlandı!")
            # Tabloyu ekranda göster
            st.dataframe(df, use_container_width=True)
        else:
            st.error("Veri çekilemedi. Lütfen hisse kodlarını kontrol edin.")
