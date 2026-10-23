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

## MiroFish ile entegrasyon planı

MiroFish (Flask, port 5001) bir "seed doküman → Zep bilgi grafiği → OASIS
persona'ları → sosyal medya simülasyonu → rapor" hattı. Bizim ihtiyacımız
olan parçalar:

1. **Persona üretimi:** `services/oasis_profile_generator.py` Zep grafiğindeki
   varlıklardan detaylı ajan profili üretir. Bölge persona'larımızı seed
   doküman olarak verip `POST /api/graph/build` → `POST /api/simulation/create`
   → `/prepare` ile bölge başına ajan havuzu kurulabilir.
2. **Fiyat ve itiraz soruları:** `POST /api/simulation/interview/batch`
   simülasyondaki ajanlara toplu soru sorar. Van Westendorp'un dört sorusu ve
   "bu üründe neyi beğenmedin?" sorusu buradan sorulur; cevaplar
   `AgentPriceAnswer` listesine ve itiraz listesine çevrilir.
3. **Bağlantı noktası:** `SimulationEngine` arayüzünü uygulayan bir
   `MiroFishSimulationEngine` yazmak yeterli; `main.py` ve dashboard değişmez.

Gereken anahtarlar (MiroFish `.env`): `LLM_API_KEY`, `LLM_BASE_URL`,
`LLM_MODEL_NAME` (OpenAI uyumlu herhangi bir model) ve `ZEP_API_KEY`.

**Lisans notu:** MiroFish AGPL-3.0. Bu kodu MiroFish ile birlikte ağ
üzerinden hizmet olarak sunarsan kaynak kodunu kullanıcılara açma
yükümlülüğü doğar. Ticari kapalı ürün düşünülüyorsa MiroFish'i ayrı bir
servis olarak HTTP üzerinden çağırmak ve hukuki görüş almak gerekir.
