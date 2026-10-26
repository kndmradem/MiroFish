# Persona paneli motoru (MiroFish'siz)

`SIM_ENGINE=panel` ile çalışan bu motor, MiroFish'in dünya kurma, Zep grafiği ve profil üretimi adımlarını
tamamen atlar. Bizim çıktılarımız (talep skoru, fiyat bölgeleri, iade, 120 gün satış, senaryolar, üretim
dağıtımı) yalnızca tüketici cevaplarına ihtiyaç duyar; panel motoru bu cevapları doğrudan üretir.

- **Bulut bağımlılığı yok:** Zep, MiroFish backend'i ve internet gerekmez. Yerel LLM (Ollama, vLLM, LM Studio)
  yeterlidir. Müşteri sunucusuna kurulum için uygundur.
- **AGPL kodu yok:** motor `talep-sim/backend/app/panel/` altındaki kendi kodumuzdur, MiroFish koduna
  dayanmaz. MiroFish motoru (`SIM_ENGINE=mirofish`) seçenek olarak duruyor.
- **Süre:** dakikalar. Dünya kurma (yerel modelde 10-30 dk) yoktur; her kişi için tek LLM çağrısı yapılır.

## Değişen dünyada doğru persona: tasarımın ana fikri

Dil modelinin moda, trend ve ekonomi bilgisi eğitim tarihinde donmuştur. 7B bir model "bu sezon ne moda"
sorusuna bir iki yıl önceki dünyaya göre cevap verir. Bu yüzden sistem modelin hafızasına güvenmez:

1. **Persona ve bağlam veri dosyasıdır, kod değil.** Her dosyada `version`, `as_of` (geçerlilik tarihi),
   `source`, `owner` ve `verified` alanları var. Müşteri kendi kopyasını düzenler (`PANEL_DATA_DIR`).
2. **Prompt modele açıkça söyler:** "Kendi trend bilgin eskidir, yalnızca verilen GÜNCEL BAĞLAM'a güven,
   orada olmayan trendi varsayma."
3. **Eskime görünür:** bağlam paketi süresini (`valid_days`, varsayılan 45 gün) aşınca, persona seti
   `review_by` tarihini geçince ya da veri doğrulanmamışsa sonuçta uyarı çıkar ve güven seviyesi düşer.
   Yönetici özetinde "Veri dayanağı" satırı hangi sürümün hangi tarih itibarıyla kullanıldığını gösterir.
4. **Gerçek satışla ölçülür:** ERP satışları geldikçe kalibrasyon katsayıları uydurulur, bölge bazında
   isabet zaman içinde izlenir (sapma uyarısı), yeni persona sürümü ancak geçmiş ürünlerde ölçülerek daha
   isabetli çıkarsa aktif yapılır. "Daha iyi görünen" değil, "daha doğru tahmin eden" persona kazanır.
5. **Segment ağırlıkları veriden gelir:** hedef, persona segment paylarını müşterinin kendi verisinden
   (Nebim'de şehir, kanal, sadakat kartı yaş bandı, sepet tutarı dağılımı) türetmek. Başlangıç dosyaları
   bunun yerine geçen taslaktır ve `verified: false` olarak işaretlidir.

Önerilen bakım ritmi: bağlam paketleri **ayda bir** (enflasyon, kur, sezon, trend notları, rakip fiyatları),
persona segmentleri **üç ayda bir** ya da sapma uyarısı geldiğinde; her değişiklik yeni bir sürüm olarak
backtest'ten geçer.

## Veri klasörü

```
panel_data/                         (PANEL_DATA_DIR; varsayılan talep-sim/backend/panel_data)
  active.json                       aktif persona sürümü (backtest terfisiyle değişir)
  personas/v1/EU.json ... TR.json   segmentler: ağırlık, yaş, gelir, tarz, fiyat duyarlılığı,
                                    trend ilgisi, kanal alışkanlıkları, iklim, giyim normları
  context/TR/2026-10-26.json        tarihli bağlam paketleri; ürünün tarihinden önceki en yenisi kullanılır
  calibration.json                  (oluşursa) bölge katsayıları
  accuracy.jsonl                    (oluşursa) gerçekleşen satış ile tahmin kayıtları, sapma izleme için
```

**Yeni bağlam paketi eklemek:** `context/<BÖLGE>/` altına yeni tarihli bir dosya kopyala, alanları
kaynağıyla doldur, `verified: true` yap. Eski dosyayı silme: backtest geçmiş ürünleri kendi tarihlerindeki
paketle koşar, böylece geleceğin bilgisi geçmiş tahmine sızmaz.

**Yeni persona sürümü:** `personas/v1` klasörünü `personas/v2` olarak kopyala, değiştir. Backtest ile
karşılaştır, kazanırsa terfi ettir (aşağıda). Doğrudan denemek için `active.json`'u elle de değiştirebilirsin.

Durumu görmek için: `GET http://localhost:8000/api/panel/status` (sürümler, tarihler, uyarılar, kalibrasyon,
sapma raporu).

## Nasıl çalışır

1. Bölgenin persona dosyasından segment ağırlıklarına göre `PANEL_SIZE` kişilik panel örneklenir (aynı ürün
   için her seferinde aynı panel; yaş, duyarlılık ve trend ilgisi kişiden kişiye hafif değişir).
2. Her kişiye tek çağrıda bağlam paketi + ürün kartı + 9 basamaklı fiyat merdiveni sorulur. Cevap JSON
   şemasıyla istenir (vLLM guided decoding, Ollama structured outputs). Sunucu şemayı tanımazsa motor
   kendiliğinden `json_object`, sonra düz metin kipine iner. Bozuk cevap bir kez modele geri verilip
   düzeltmesi istenir.
3. İsteğe bağlı akran turu (`PANEL_PEER_ROUND=true`, varsayılan kapalı): kişiler ilk turdaki yorumların
   özetini görüp yeniden cevaplar. Çağrı sayısını ikiye katlar; sürü etkisi yaratabilir, etkisi backtest
   ile ölçülmeden açılmamalı.
4. Kalibrasyon katsayıları uygulanır ve cevaplar mevcut fiyat bölgesi, iade, satış tahmini, senaryo ve
   dağıtım hesaplarına girer.

## Kalibrasyon, sapma ve persona karşılaştırma

Katsayılar bölge başına (1.0 = düzeltme yok): `demand_scale` (talep), `price_scale` (fiyat eşikleri),
`sensitivity_scale` ve `trend_scale` (persona özellikleri). İlk ikisi gerçek satıştan formülle uydurulur;
az gözlemde 1.0'a doğru büzülür (2-3 ürünle aşırı düzeltme yapılmaz). Diğer ikisi backtest adaylarıyla
denenir.

ERP verisi (Nebim V3 → PostgreSQL aktarımı) hazır olduğunda kullanım:

```python
from datetime import date
from app.panel.backtest import Actual, BacktestCase, Candidate, compare, pipeline_predictor, promote
from app.panel.library import PanelStore
from app.panel.questioner import PanelLLM

store = PanelStore()                       # ya da PanelStore("/musteri/panel_data")
llm = PanelLLM("http://localhost:11434/v1", "qwen2.5:7b-instruct", concurrency=2)
cases = [BacktestCase("Yün kaban AW25", date(2025, 10, 1), istek, {"TR": Actual(units=1840, full_price=79)}), ...]
predictor = pipeline_predictor(store, llm, fuser)
results = await compare(cases, [Candidate("v1", "v1"), Candidate("v2", "v2")], predictor)
print(promote(store, results))             # en az 5 puan daha iyiyse v2 aktif olur, kalibrasyon kaydedilir
```

Ürünler zaman sırasına göre bölünür: eski ürünlerde katsayılar uydurulur, yeni ürünlerde sınanır. Gerçek
satış geldikçe `DriftMonitor(store.root / "accuracy.jsonl").record(...)` ile kaydedilir; son 90 günün hatası
önceki dönemden belirgin kötüyse ya da tahminler hep aynı yöne kayıyorsa bölge "sapma var" olarak işaretlenir.
ERP aktarımı henüz yok; arayüzler hazır ve sentetik verilerle test edildi.

## Adem'in Mac'inde çalıştırma (MacBook Air M2, 16 GB, Ollama)

MiroFish backend'ine ve Zep anahtarına gerek yok. Üç pencere yerine iki pencere yeter.

**0. Kodu al** (MiroFish klasöründe, yolun farklıysa onu yaz):

```bash
cd ~/MiroFish
git fetch origin
git checkout claude/project-thread-0w9g1l
```

**1. Ollama:** zaten kurulu. Aynı anda iki isteği işlemesi için bir kez şunu çalıştır, sonra Ollama
uygulamasını menü çubuğundan kapatıp yeniden aç:

```bash
launchctl setenv OLLAMA_NUM_PARALLEL 2
```

**2. `talep-sim/backend/.env` dosyası** (mevcut satırları bunlarla değiştir):

```
SIM_ENGINE=panel
LLM_API_KEY=ollama
LLM_BASE_URL=http://localhost:11434/v1
LLM_MODEL_NAME=qwen2.5:7b-instruct
PANEL_SIZE=12
PANEL_CONCURRENCY=2
PANEL_MIN_VALID=4
PANEL_GUIDED=json_schema
PANEL_PEER_ROUND=false
```

Görsel için `VISION_*` ayarların aynı kalır.

**3. Pencere 1, API:**

```bash
cd ~/MiroFish/talep-sim/backend
kill $(lsof -ti :8000) 2>/dev/null
.venv/bin/uvicorn app.main:app --port 8000
```

**4. Pencere 2, panel:** her zamanki gibi `npm run dev -- -p 3100` (frontend klasöründe).

Beklenen süre: bölge başına 12 kişi, iki paralel istekle yaklaşık 1-2 dakika; 5 bölge 5-10 dakika
(MiroFish'te ilk kurulum 10-30 dakikaydı, üstüne röportaj). Daha hızlı demo için `PANEL_SIZE=8`.
GPU'lu bir sunucuda vLLM ile aynı iş bir dakikanın altına iner.

Gerçek model olmadan boru hattını denemek için sahte LLM sunucusu var:

```bash
.venv/bin/uvicorn app.panel.mock_llm:app --port 11500     # ayrı pencerede
PANEL_LLM_BASE_URL=http://localhost:11500/v1 SIM_ENGINE=panel .venv/bin/uvicorn app.main:app --port 8000
```

Sahte sunucunun cevapları anlamlı değildir, yalnızca akışı sınar.

## Kalite sınırları (açıkça)

- **Persona cevabı ölçüm değildir.** Panel, gerçek tüketiciye sorulmuş bir anket değil; bir dil modelinin
  verilen persona ve bağlamla yaptığı tahmindir. En güvenilir kullanımı **göreli** karşılaştırmadır (hangi
  bölge, hangi fiyat bandı, hangi itiraz). Mutlak adetler ERP ile kalibre edilene kadar varsayımdır; bu
  yüzden kalibre edilmemiş panel en fazla "orta" güven gösterir.
- **Küçük yerel modeller (7B):** personalar arasındaki farkı gerçekte olduğundan küçük gösterir, ilgi
  puanlarını ortaya (50-70) toplama, ürüne fazla olumlu bakma ve Türkçe dışı bölgelerde kültürel ayrıntıyı
  yüzeysel işleme eğilimindedir. Demo için yeterli; müşteri kurulumunda daha büyük bir model (ör. 32B ya da
  70B sınıfı, vLLM ile GPU sunucuda) belirgin fark yaratır. Model değişince backtest tekrar koşulmalı.
- **Başlangıç personaları taslaktır:** 5 bölge × 5 segment, genel pazar bilgisinden yazıldı ve ölçülmüş
  veri değildir. Bağlam paketlerindeki sayısal alanlar (enflasyon, rakip fiyatı) bilerek boş bırakıldı;
  uydurma sayı yerine boş alan ve uyarı tercih edildi. Müşteriye gösterilmeden önce doldurulmalı.
- **Bağlam kalitesi = sonuç kalitesi:** model yalnızca pakette yazanı bilir. Trend notu eksik ya da yanlışsa
  panel bunu düzeltemez.
- **Akran turu** gerçek sosyal etkiyi modellemez; ortalamayı birbirine yaklaştırabilir. Varsayılan kapalı.
