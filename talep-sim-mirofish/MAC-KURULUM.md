# MiroFish motorlu kopya: Mac kurulumu

Bu klasör (`talep-sim-mirofish/`), `talep-sim/`'in birebir kopyasıdır; farkı yalnızca şunlar:

| | Eski kurulum (`~/MiroFish`) | Yeni kurulum (`~/MiroFish-v2`) |
|---|---|---|
| Motor (varsayılan) | `.env`'de ne yazıyorsa | `SIM_ENGINE=hybrid` (MiroFish + persona paneli) |
| MiroFish backend | 5001 | **5101** |
| Talep API | 8000 | **8100** |
| Dashboard | 3100 | **3200** |
| Ollama | 11434 (ortak) | 11434 (ortak) |

Eski klasöre, eski `.env` dosyalarına ve eski portlara hiçbir betik dokunmaz. Kurulum, eski `.env`'lerden
anahtarları (Zep, LLM) yalnızca **okuyup kopyalar**. Betikler eski klasörde çalıştırılırsa kendiliğinden durur.

> 16 GB RAM'de iki kurulumu aynı anda çalıştırmak Qwen'i yavaşlatır (aynı Ollama'yı paylaşırlar).
> Yenisini denerken eskisinin pencerelerini Ctrl+C ile kapatman önerilir. Çakışma olmaz, yalnızca yavaşlar.

## Bir kez: kurulum

Terminal'i aç (Cmd+Boşluk, "Terminal" yaz, Enter). Şu iki satırı sırayla yapıştır:

```bash
git clone -b claude/project-thread-cc5fup https://github.com/kndmradem/MiroFish.git ~/MiroFish-v2
```

```bash
~/MiroFish-v2/talep-sim-mirofish/mac/kurulum.sh
```

İkincisi 5-15 dakika sürer (Python ve Node paketleri). Sonunda "KURULUM TAMAM" yazar.
"ZEP_API_KEY boş" uyarısı çıkarsa: `open -e ~/MiroFish-v2/.env` ile dosyayı aç, `ZEP_API_KEY=` satırına
anahtarı yaz, kaydet.

## Her seferinde: çalıştırma (3 pencere)

Ollama uygulaması açık olmalı (menü çubuğunda lama simgesi). Her pencere için Terminal'de Cmd+T ile yeni sekme aç.

**Pencere 1, MiroFish (5101):**
```bash
~/MiroFish-v2/talep-sim-mirofish/mac/1-mirofish.sh
```
"Running on http://127.0.0.1:5101" görünce sonraki pencereye geç.

**Pencere 2, API (8100):**
```bash
~/MiroFish-v2/talep-sim-mirofish/mac/2-api.sh
```
"Uvicorn running on http://127.0.0.1:8100" görünce devam.

**Pencere 3, Dashboard (3200):**
```bash
~/MiroFish-v2/talep-sim-mirofish/mac/3-panel.sh
```
"Ready" görünce tarayıcıda **http://localhost:3200** aç.

Durdurmak: her pencerede Ctrl+C. Pencereyi kapatmak da yeterli.

## Karma motor: hangi iş kimde?

MiroFish'in yapabildiği her yerde MiroFish çalışır; yapamadığı yerde bizim yazdığımız persona paneli devreye girer.
Hiçbir özellik çıkarılmadı. Hangi sonucun nereden geldiği ekranda yazar.

| İş | Kim yapıyor |
|---|---|
| Ürün kartı (görsel + teknik bilgi okuma) | Qwen-VL (iki motorda ortak) |
| Bölge bölge talep puanı, fiyat eşikleri, itirazlar | **MiroFish ajanları** |
| MiroFish'in hesaplayamadığı bölge (MiroFish kapalı, zaman aşımı, yeterli cevap yok) | Persona paneli. Sonuçta bölge "persona paneli" diye etiketlenir, nedeni yöntem notlarında yazar |
| Koleksiyon: tek tek ürün değerlendirmesi, kişi içi sıralama, erişim, kanibalizasyon | **MiroFish ajanları** (bölgedeki aynı ajanlar bütün ürünlere bakar) |
| Koleksiyon: vitrin turu (ürünleri gruplar halinde birlikte görme) | Persona paneli (MiroFish'te bu tür soru yok). Ekranda "tek tek tur MiroFish, vitrin turu panel" notu çıkar |
| Fiyat bölgeleri, iade, 30/60/90/120 gün satış, senaryolar, bütçe dağıtımı | Bizim hesap kodumuz (motordan gelen cevaplarla) |
| Yeni mağaza / AVM profili, ERP tahmin ve testleri | Bizim kodumuz (motordan bağımsız) |

MiroFish penceresi kapalıyken tahmin çalıştırırsan bütün bölgeler panelle hesaplanır ve ekranda öyle yazar.
Bunu istemiyorsan `~/MiroFish-v2/talep-sim-mirofish/backend/.env` içinde `HYBRID_FALLBACK=false` yap: o zaman
MiroFish'in hesaplayamadığı bölge "hesaplanamadı" olarak görünür.

## Kontrol

```bash
~/MiroFish-v2/talep-sim-mirofish/mac/durum.sh
```
Yeni kurulumun üç servisini ve Ollama'yı ✓/✗ ile gösterir; API satırında `"engine":"hybrid"` görünmeli.

## Bilinmesi gerekenler

- **İlk tahmin uzun sürer.** MiroFish ilk istekte "dünya"yı kurar (ontoloji, Zep grafiği, ajan profilleri):
  yerel Qwen ile 10-30 dakika. Sonra `talep-sim-mirofish/backend/.mirofish_world.json` dosyasına kaydedilir ve
  sonraki tahminler yalnızca röportaj süresi kadar sürer. Eski kurulumun dünyası ayrıdır, paylaşılmaz.
- **Motoru geçici değiştirmek:** `~/MiroFish-v2/talep-sim-mirofish/backend/.env` içindeki `SIM_ENGINE=` satırı
  (`hybrid` varsayılan / `mirofish` yalnız MiroFish, vitrin turu atlanır / `panel` / `mock`). Değiştirince 2. pencereyi Ctrl+C ile durdurup tekrar başlat.
- **Hata: "Port 8100 dolu"** gibi bir mesaj görürsen betik o porttaki eski süreci zaten kapatır; yalnızca
  5101/8100/3200'e dokunur, 5001/8000/3100'e asla.
- **Kodu güncellemek** (yeni sürüm gelince): `cd ~/MiroFish-v2 && git pull`, sonra kurulumu tekrar çalıştır
  (mevcut `.env`'lerdeki anahtarlar korunur; yalnızca port/motor satırları yeniden yazılır).
