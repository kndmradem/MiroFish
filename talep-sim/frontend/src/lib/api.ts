export const REGIONS = [
  { code: "EU", label: "Avrupa (EU)" },
  { code: "MENA", label: "Körfez (MENA)" },
  { code: "CIS", label: "Kafkaslar (CIS)" },
  { code: "US", label: "Amerika (US)" },
  { code: "TR", label: "Türkiye (TR)" },
] as const;

export type RegionCode = (typeof REGIONS)[number]["code"];

export type PriceTier = "budget" | "mass" | "upper_mass" | "premium" | "luxury";

export const TIER_LABEL: Record<PriceTier, string> = {
  budget: "Ekonomik", mass: "Kitlesel", upper_mass: "Üst-kitlesel", premium: "Premium", luxury: "Lüks",
};

export interface BrandProfile {
  name: string;
  positioning: string;
  price_tier: PriceTier;
  price_multiple: number;
  price_sensitivity: number;
  brand_pull: number;
  typical_customer: string;
  margin_norm_pct: number;
  regional_strength: Record<string, number>;
  known_brand: boolean;
  confidence: "low" | "medium" | "high";
  source: "llm_knowledge" | "user_notes" | "generic_default";
  edited: boolean;
  warning: string | null;
}

export interface Explanation {
  key: "demand" | "price" | "margin" | "quantity";
  label: string;
  value: string;
  how: string;
  assumptions: string[];
}

export interface Recommendation {
  category: "fiyat" | "bölge" | "tasarım" | "üretim" | "marka";
  title: string;
  detail: string;
  based_on: string;
  source: "model" | "kural";
}

export interface PredictionRequest {
  product_name: string;
  image_base64: string;
  technical_specs: string;
  unit_cost: string;
  total_production_budget: number;
  target_regions: RegionCode[];
  brand?: string;
  brand_notes?: string;
  brand_profile?: BrandProfile;
  usd_try_rate?: number;
}

export interface PricePoint {
  price: string;
  too_cheap: number;
  cheap: number;
  expensive: number;
  too_expensive: number;
}

export interface VanWestendorpResult {
  optimal_price_point: string;
  indifference_price_point: string;
  acceptable_range_low: string;
  acceptable_range_high: string;
  curve: PricePoint[];
}

export interface RegionPredictionResult {
  region: RegionCode;
  demand_score_100: number;
  optimal_sale_price: string;
  recommended_production_qty: number;
  allocated_budget: string;
  estimated_margin_percentage: number;
  key_objections: string[];
  van_westendorp: VanWestendorpResult;
  explanations: Explanation[];
  raw_answers?: RawAnswer[];
  local_currency?: string | null;
  local_price?: string | null;
  fx_rate?: number | null;
}

export interface RawAnswer {
  agent: number;
  status: "json" | "extracted" | "failed" | "empty";
  text: string;
  interest?: number | null;
}

export interface PredictionResponse {
  session_id: string;
  status: string;
  total_produced_qty: number;
  unallocated_budget: string;
  product_card: Record<string, unknown>;
  engine: string;
  brand_profile: BrandProfile | null;
  recommendations: Recommendation[];
  methodology_notes: string[];
  regional_breakdown: RegionPredictionResult[];
  /** Zaman aşımı vb. yüzünden hesaplanamayan bölgeler; diğer bölgeler yine de gösterilir. */
  failed_regions: { region: string; reason: string; raw_answers?: RawAnswer[] }[];
  /** Eski bir API sürümü açıklama/öneri alanlarını göndermediyse true (istemci tarafında eklenir). */
  api_outdated?: boolean;
}

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface ProgressEvent {
  stage: string;
  region?: string;
  detail?: string;
  done?: number;
  total?: number;
}

/** NDJSON akışlı tahmin: ilerleme olaylarını `onProgress`e iletir. Akış uç noktası yoksa (eski API) /api/predict'e düşer. */
export async function predictStream(body: PredictionRequest, onProgress: (e: ProgressEvent) => void): Promise<PredictionResponse> {
  const res = await fetch(`${API_URL}/api/predict/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (res.status === 404 || res.status === 405 || !res.body) return predict(body);
  if (!res.ok) throw new Error(`Simülasyon başarısız (${res.status}): ${await res.text()}`);

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let result: PredictionResponse | null = null;
  const handle = (line: string) => {
    if (!line.trim()) return;
    const ev = JSON.parse(line);
    if (ev.type === "progress") onProgress(ev);
    else if (ev.type === "result") result = normalizePrediction(ev.data);
    else if (ev.type === "error") throw new Error(`Simülasyon başarısız (${ev.status}): ${ev.detail}`);
  };
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    lines.forEach(handle);
  }
  handle(buffer);
  if (!result) throw new Error("Simülasyon sonuç döndürmeden bağlantı kapandı.");
  return result;
}

export async function predict(body: PredictionRequest): Promise<PredictionResponse> {
  const res = await fetch(`${API_URL}/api/predict`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    throw new Error(`Simülasyon başarısız (${res.status}): ${await res.text()}`);
  }
  return normalizePrediction(await res.json());
}

/** Eski/eksik API cevabında arayüzün çökmemesi için eksik alanları boş değerle doldurur. */
export function normalizePrediction(raw: PredictionResponse): PredictionResponse {
  const outdated = raw.recommendations === undefined || raw.regional_breakdown.some((r) => r.explanations === undefined);
  return {
    ...raw,
    engine: raw.engine ?? "mock",
    brand_profile: raw.brand_profile ?? null,
    recommendations: raw.recommendations ?? [],
    methodology_notes: raw.methodology_notes ?? [],
    failed_regions: raw.failed_regions ?? [],
    regional_breakdown: raw.regional_breakdown.map((r) => ({ ...r, explanations: r.explanations ?? [] })),
    api_outdated: outdated,
  };
}

export async function fetchBrandProfile(brand: string, notes: string): Promise<BrandProfile> {
  const res = await fetch(`${API_URL}/api/brand-profile`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ brand, notes: notes || null }),
  });
  if (!res.ok) throw new Error(`Marka profili alınamadı (${res.status}): ${await res.text()}`);
  return res.json();
}

export const try_ = (v: string | number) => `₺${Math.round(Number(v)).toLocaleString("tr-TR")}`;

export const usd = (v: string | number) =>
  Number(v).toLocaleString("tr-TR", { style: "currency", currency: "USD" });
