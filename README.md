# Bilgi Akını
**Aklınla savaş, bilginle fetih et.**

"Bil ve Fethet" mantığında bir bilgi yarışması oyunu: haritadaki bölgelere
soruları doğru cevaplayarak sahip oluyorsun. Yanlış cevap ya da süre
dolması bölgeyi kaybettiriyor.

İki mod var: **tek kişilik sefer** (mevcut haritayı tek başına fethet) ve
**iki kişilik meydan okuma** (aynı haritada, iki ayrı cihazdan, gerçek
zamanlı olarak rakibinle yarışırsınız — oda kodu ile eşleşilir, bir
bölgeye ilk dokunan onu kilitler, doğru bilirse bölge onun olur, yanlış/
süre biterse bölge farklı bir soruyla tekrar herkese açılır).

## Proje yapısı

```
bilgi-akini/
├── backend/          Flask API (sorular, bölgeler, oyuncu verisi)
│   ├── app.py
│   ├── requirements.txt
│   └── schema.sql    MySQL şeması (referans)
└── frontend/          Tarayıcıda / mobilde çalışan oyun arayüzü
    ├── index.html
    ├── style.css
    └── game.js
```

## Windows'ta çalıştırma

**`start.bat`'e çift tıkla.** Python'u kendisi bulur (ilk seferde sanal ortamı
kurar), oyun sunucusunu açar, sunucu hazır olunca tarayıcıyı açar ve
telefondan girilecek adresi yazar (örn. `http://192.168.1.20:5000`).
Oyun ve API aynı sunucudan (port 5000) servis edilir; internet gerekmez
(fontlar ve socket.io `frontend/` içinde).

- Telefon ve bilgisayar aynı Wi-Fi'da olmalı; Windows güvenlik duvarı sorarsa
  Python'a izin ver.
- `sifirla.bat`: test oyuncularını ve ilerlemeyi siler (sorular korunur).
- Kısayollar (masaüstü): `1-4` şık seç, `Enter` devam, `Esc`/`Backspace`
  pencereyi kapat, `F` tam ekran.

Elle çalıştırmak istersen:

```powershell
cd backend
python -m venv venv
venv\Scriptsctivate
pip install -r requirements.txt
python app.py
```

Sonra tarayıcıda `http://localhost:5000` adresine git.

### Görseller

`kaynak_gorseller/` orijinal PNG'leri tutar; `frontend/assets/` altındaki
küçültülmüş WebP'ler ve uygulama ikonları
`backendenv\Scripts\python.exe scripts\optimize_images.py` ile üretilir.

## MySQL'e geçiş (üretim / gerçek yayın için)

1. MySQL sunucunu kur, `schema.sql` dosyasını çalıştır:
   ```
   mysql -u root -p < backend/schema.sql
   ```
2. Ortam değişkenini ayarla ve uygulamayı öyle başlat:
   ```powershell
   set DATABASE_URL=mysql+mysqlconnector://kullanici:sifre@localhost/bilgi_akini
   python app.py
   ```
   (SQLAlchemy tabloları otomatik oluşturur, örnek verileri de ekler.)

## Yeni soru / bölge eklemek

`backend/app.py` içindeki `seed_data()` fonksiyonuna yeni satırlar ekle,
ya da doğrudan veritabanına INSERT at (ileride bir admin panel eklenebilir).

## Sıradaki adımlar (mobil paketleme)

1. Backend'i bir sunucuya deploy et (Render / Railway / PythonAnywhere) —
   `frontend/config.js` içindeki `BILGI_AKINI_SERVER` değerini o adrese yaz.
2. Projeyi bir Capacitor kabuğuna al:
   ```
   npm install @capacitor/core @capacitor/cli
   npx cap init "Bilgi Akını" "com.seninadın.bilgiakini"
   npx cap add android
   npx cap add ios
   ```
   `frontend/` klasörünü Capacitor'ün `webDir` olarak göstermesi yeterli.
3. Android build'i Windows'ta Android Studio ile alabilirsin.
4. iOS build'i için projeyi Mac'e (arkadaşının) taşı, Xcode ile aç,
   `npx cap sync ios` çalıştır, imzala ve App Store Connect'e yükle.

## Notlar

- `username` ile basit bir oyuncu kaydı tutuluyor (şifre yok — istersen
  sonra eklenir).
- Zorluk seviyesi bölgeye bağlı (`kolay` / `normal` / `zor`); yeni
  kategoriler eklemek için hem `regions` hem `questions` tablosuna aynı
  `category` değeriyle satır eklemen yeterli.
- İki kişilik maç durumu (oda kodu, kim hangi bölgeyi fethetti) veritabanına
  değil, sadece backend'in belleğine yazılır — sunucu yeniden başlayınca
  ya da her iki oyuncu da ayrılınca oda silinir. Kazanılan altın (`gold`)
  kalıcı olarak oyuncunun kaydına işlenir, ama fetihler tek kişilik
  sefer geçmişini etkilemez (iki mod birbirinden bağımsızdır).
- Her bölge/zorluk kombinasyonunda az sayıda soru olduğundan (bazılarında
  tek soru), "aynı soru tekrar gelmesin" kuralı elden geldiğince
  uygulanır ama başka aday kalmadığında aynı soru yine gelebilir — daha
  fazla soru eklemek bu sınırı ortadan kaldırır.
