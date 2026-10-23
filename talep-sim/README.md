# Talep Simülasyonu MVP (Faz 1)

Tasarım görseli + teknik bilgi + maliyet/bütçe girilen bir ürün için bölgesel
talep skoru, Van Westendorp optimal fiyatı, bütçe ağırlıklı üretim adedi ve
ajan itirazlarını hesaplayan MVP. Şu an LLM ve ajan sürüsü **mock**; bütçe
dağıtımı ve fiyat analizi gerçek hesaplama.

## Çalıştırma

```bash
# Backend (Python 3.11+)
cd backend
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --reload --port 8000   # http://localhost:8000/docs
.venv/bin/python -m pytest -q

# Frontend (Node 18+)
cd frontend
npm install
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev   # http://localhost:3000
```

MiroFish kendi frontend'ini 3000, backend'ini 5001 portunda açar. İkisini
aynı anda çalıştıracaksan bu dashboard'u `npm run dev -- -p 3100` ile başlat
ve backend'e `CORS_ORIGINS=http://localhost:3100` ver.

## Yapı

| Dosya | Görev |
|---|---|
| `backend/app/models.py` | Dokümandaki Pydantic sözleşmesi (+ grafik için Van Westendorp eğrisi, bölge bütçesi) |
| `backend/app/allocation.py` | `allocate_production_budget`: Ağırlık = Talep × (Fiyat − Maliyet), adet aşağı yuvarlanır |
| `backend/app/pricing.py` | Van Westendorp eğrileri, OPP/IPP/PMC/PME, kabul aralığında en kârlı fiyat |
| `backend/app/services/engine.py` | `SimulationEngine` arayüzü + `MockSimulationEngine` (asyncio.sleep, deterministik) |
| `backend/app/services/personas.py` | EU/MENA/CIS/US persona promptları ve mock parametreleri |
| `frontend/src/app/page.tsx` | Girdi paneli + dashboard (skor kartları, ECharts fiyat grafiği, üretim tablosu, itirazlar) |

## Marka profiline göre fiyatlama

Marka adı yazıldığında (herhangi bir marka; sabit liste yok) `POST /api/brand-profile` bir LLM'e
markanın konumlandırmasını, fiyat segmentini, tipik fiyat çarpanını (satış ÷ maliyet), fiyat
duyarlılığını, bölgesel gücünü ve brüt marj normunu sordurur. Profil arayüzde düzenlenebilir;
düzenlenmiş profil `/api/predict`'e `brand_profile` olarak gider ve yeniden üretilmez.

- **Etkisi:** fiyat çarpanı ve duyarlılık ajanların fiyat bandını, bölgesel güç ve çekim gücü talep
  endeksini kaydırır (mock motorda formülle, MiroFish motorunda ajan promptlarına marka bloğu olarak).
- **Dürüstlük:** model markayı tanımıyorsa `confidence=low` ve uyarı döner; LLM yoksa ya da cevap
  bozuksa nötr profil ve açık uyarı döner. Arayüz kaynağı (model bilgisi / notların / nötr varsayılan)
  rozetle gösterir; bu bilgi doğrulanmış veri değildir.
- **Açıklamalar ve öneriler:** her bölge için talep, fiyat, marj ve adet sayılarının nasıl
  türetildiği gerçek sayılarla yazılır (`explanations`). Öneriler LLM'den (özet sayılarına bakarak)
  gelir; LLM yoksa ya da cevap geçersizse veriden türeyen kurallar kullanılır (`recommendations[].source`).
- **LLM ayarı:** `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL_NAME` (MiroFish'le aynı adlar). API, hem
  `talep-sim/backend/.env` hem repo kökündeki `.env` dosyasını okur.

## MiroFish entegrasyonu

`SIM_ENGINE=mirofish` ile mock yerine MiroFish ajan sürüsü kullanılır
(`backend/app/services/mirofish_engine.py`). `main.py`, fiyat analizi,
bütçe dağıtımı ve dashboard değişmez; anahtar yoksa `SIM_ENGINE=mock` kalır.
MiroFish ya da vision servisine ulaşılamazsa API 502 döner (sessizce mock'a
düşmez, çünkü sahte sonuç gerçek sanılmasın).

Akış:
1. **Dünya kurulumu (ilk istekte, bir kez, `.mirofish_world.json`'a kaydedilir):**
   `personas.py` içindeki 20 adlandırılmış tüketici (bölge başına 5) seed doküman
   olarak `POST /api/graph/ontology/generate` → `/api/graph/build` (Zep grafiği)
   → `/api/simulation/create` → `/prepare` (OASIS profilleri) → `/start`
   (kısa simülasyon, ortam komut bekler). Ajanlar profildeki isim/şehirden bölgelere eşlenir.
   İlk istek dakikalar sürebilir; sonrakiler saklanan dünyayı kullanır.
2. **Her tahmin:** vision modeli (ya da mock) ürün kartını çıkarır; bölgedeki ajanlara
   `POST /api/simulation/interview/batch` ile kart + bölge persona'sı sorulur. Ajan JSON
   döner: ilgi (0-100), dört Van Westendorp eşiği, en büyük itiraz.
3. Talep skoru = ilgi ortalaması, fiyat eğrileri = ajan eşikleri, itirazlar = en sık 3 cevap.

### Gerekli anahtarlar ve yerleri

| Anahtar | Nereye | Ne için |
|---|---|---|
| `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL_NAME` | MiroFish kökündeki `.env` | Persona üretimi, simülasyon, röportaj cevapları (OpenAI uyumlu herhangi bir model) |
| `ZEP_API_KEY` | MiroFish kökündeki `.env` | Zep Cloud bilgi grafiği (ücretsiz kota yeterli) |
| `VISION_API_KEY` (+ `VISION_BASE_URL`, `VISION_MODEL`) | `talep-sim/backend/.env` | Görsel + metin füzyonu. Opsiyonel; boşsa metin tabanlı mock |

Çalıştırma: MiroFish için `cp .env.example .env`, anahtarları yaz, `npm run setup:all && npm run backend`
(Python 3.11-3.12 gerekir). Sonra `SIM_ENGINE=mirofish uvicorn app.main:app --port 8000`.
MiroFish simülasyonu LLM tüketir; `MIROFISH_MAX_ROUNDS` düşük tutuldu.

Not: Bu entegrasyon gerçek MiroFish'e karşı henüz çalıştırılmadı (anahtar yok). Testler
MiroFish API'sini taklit eden bir sahte sunucuyla çalışıyor; gerçek ajan cevaplarının
JSON formatına uyma oranı ilk gerçek denemede ölçülmeli.

### Yerel Qwen ile çalıştırma (OpenAI API anahtarı yerine)

`local-llm/` klasörü Ollama'yı ayağa kaldırır: `docker compose up -d && ./pull-models.sh`
(ya da Ollama'yı doğrudan kurup `OLLAMA=ollama ./pull-models.sh`). Betik çıktısındaki
`LLM_*` satırlarını MiroFish `.env`'ine, `VISION_*` satırlarını `talep-sim/backend/.env`'e yaz.
Önerilen: metin için `qwen2.5:14b-instruct` (~16 GB GPU belleği ya da 32 GB Mac), görsel için
`qwen2.5vl:7b`. 7B altı metin modelleri ajan JSON'unu sık bozar; motor geçersiz cevap veren
ajanlara bir kez tekrar sorar (`retries`). **Zep yine buluttan gelir**, aşağıya bak.

#### macOS (MacBook, Docker olmadan)

```bash
cd talep-sim/local-llm && ./setup-mac.sh
```

Betik RAM'e göre model seçer: 8 GB → `qwen2.5:3b-instruct` + `qwen2.5vl:3b`, 16 GB →
`qwen2.5:7b-instruct` + `qwen2.5vl:7b`, 24 GB+ → `qwen2.5:14b-instruct` + `qwen2.5vl:7b`.
Ollama'yı Homebrew ile kurar, indirir ve `.env`'e yazılacak satırları basar. 8 GB'ta 3B model
JSON'u sık bozar ve simülasyon yavaş olur; ilk deneme için `MIROFISH_MAX_ROUNDS=2` kullan,
sonuç güvenilmezse bulut LLM'e geç. MiroFish backend'i Python 3.11-3.12 ister; macOS'un
varsayılan Python'u daha yeniyse `uv` kullan (`npm run setup:backend` zaten uv ile kurar).

### Zep ne yapıyor?

MiroFish, seed dokümanı (bizde 20 tüketicilik panel) Zep Cloud'a yükler. Zep metinden
kişi/yer/kavram varlıklarını ve aralarındaki ilişkileri çıkarıp bir **bilgi grafiği** kurar.
MiroFish ajan profillerini bu grafiğe bakarak zenginleştirir (bir tüketicinin şehri, tercihleri,
çevresi) ve ajanlar uzun vadeli hafızasını buradan okur. Zep kendi başına bir LLM değil, bir
hafıza/bilgi-grafiği servisidir. Bu MVP'de katkısı sınırlı; asıl ajan zekâsını LLM verir. Ama
MiroFish bu adım olmadan çalışmıyor ve yalnızca Zep Cloud'a bağlanıyor (`ZEP_API_URL` kabul etmiyor).

**Lisans notu:** MiroFish AGPL-3.0. Bu kodu MiroFish ile birlikte ağ
üzerinden hizmet olarak sunarsan kaynak kodunu kullanıcılara açma
yükümlülüğü doğar. Ticari kapalı ürün düşünülüyorsa MiroFish'i ayrı bir
servis olarak HTTP üzerinden çağırmak ve hukuki görüş almak gerekir.
