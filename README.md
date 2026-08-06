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

## Windows'ta çalıştırma (geliştirme)

### 1. Backend'i ayağa kaldır

```powershell
cd backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Bu, `http://localhost:5000` adresinde API'yi başlatır ve **SQLite** ile
otomatik olarak örnek sorular/bölgeler doldurur (`bilgi_akini.db` dosyası
oluşur). Hiçbir ekstra kurulum gerekmez — ilk test için bu yeterli.

`requirements.txt` artık `Flask-SocketIO` da içeriyor (2 kişilik gerçek
zamanlı mod için); `pip install -r requirements.txt` bunu otomatik kurar,
ekstra bir adım gerekmez.

### 2. Frontend'i aç

`frontend/index.html` dosyasını doğrudan tarayıcıda açabilirsin, ya da basit
bir sunucuyla servis et (bazı tarayıcılar `fetch`i dosya:// üzerinden
kısıtlayabilir):

```powershell
cd frontend
python -m http.server 5500
```

Sonra tarayıcıda `http://localhost:5500` adresine git.

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
   `game.js` içindeki `API_BASE` değişkenini o adrese güncelle.
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
