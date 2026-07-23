# --- 6. ARAYÜZ (UI) VE ÇİFT RADAR ---
def ui_olustur():
    st.title("🎯 Hibrit Quant Bot v11.4 (Çift Motor & Çift Radar)")
    st.markdown("Algoritma hem dipten dönüş yapan iskontolu hisseleri (Değer), hem de direnç kırmış hacimli ralli hisselerini (Momentum) avlar.")
    st.markdown("---")

    # SOL MENÜ - AYARLAR
    st.sidebar.markdown("### 🏦 Portföy & Risk Parametreleri")
    toplam_sermaye = st.sidebar.number_input("Yönetilen Bakiye (₺)", min_value=10000, value=100000)
    atr_carpan = st.sidebar.slider("Stop-Loss ATR Çarpanı", min_value=1.0, max_value=3.0, value=1.5, step=0.25)
    risk_odul = st.sidebar.slider("Risk / Ödül Oranı", min_value=1.5, max_value=4.0, value=2.0, step=0.5)
    
    config = BotConfig(sermaye=toplam_sermaye, atr_stop_carpan=atr_carpan, risk_odul_orani=risk_odul)
    strateji = QuantStrategy(config)

    # SOL MENÜ - HIZLI TARAMA BÖLÜMÜ
    st.sidebar.markdown("### 🔍 Hızlı Radar Testi")
    hisseler_metin = st.sidebar.text_area("Manuel Hisse Girin:", "GUNDG\nOZATD\nASELS\nTKNSA", height=120)
    
    # 1. BUTON: HIZLI TARAMA
    hizli_tarama_butonu = st.sidebar.button("🚀 Sadece Bunları Tara", use_container_width=True)

    # ANA EKRAN - GENEL TARAMA BÖLÜMÜ
    st.markdown("### 📡 Tüm Katılım Endeksi Radarı")
    
    # 2. BUTON: TÜM LİSTEYİ TARAMA
    ana_tarama_butonu = st.button("🔍 Tüm Listeyi (Katılım Endeksi) Tara", use_container_width=True)

    # --- HANGİ BUTONA BASILDIYSA ONA GÖRE İŞLEM YAP ---
    if hizli_tarama_butonu or ana_tarama_butonu:
        
        # Eğer sol menüdeki butona basıldıysa listeyi metin kutusundan al
        if hizli_tarama_butonu:
            hisse_listesi = [h.strip().upper() for h in hisseler_metin.split("\n") if h.strip()]
            st.info(f"Hızlı Motor Aktif: Yalnızca girdiğiniz {len(hisse_listesi)} hisse taranıyor...")
        
        # Eğer ana ekrandaki butona basıldıysa listeyi ana yapılandırmadan al
        else:
            hisse_listesi = KATILIM_LISTESI
            st.info(f"Derin Tarama Aktif: Listedeki tüm hisseler taranıyor. Bu işlem 1-2 dakika sürebilir...")
            
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
            st.warning("Bu listede ne bir dip dönüşü (Değer), ne de bir ralli başlangıcı (Momentum) tespit edilemedi. Kriterler karşılanmıyor.")

if __name__ == "__main__":
    ui_olustur()
