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

export interface Assumptions {
  channel: "online" | "store";
  return_base_pct: Record<string, number>;
  restock_share: number;
  reverse_logistics_pct: number;
  audience: Record<string, number>;
  conversion_ceiling_pct: number;
  competitor_price_usd: Record<string, number>;
  launch_month?: number;
}

export interface SensitivityRow {
  kind: "price" | "cost";
  label: string;
  price: string;
  unit_cost: string;
  units: number;
  net_profit: string;
  vs_base_pct: number;
}

export interface BreakEven {
  units: number;
  pct_of_production: number;
  day: number | null;
  note: string;
}

export interface Confidence {
  level: "düşük" | "orta" | "yüksek";
  reasons: string[];
}

export interface Seasonality {
  launch_month: number;
  factor: number;
  note: string;
  basis: string;
}

export interface PricePhase {
  name: string;
  day_from: number;
  day_to: number;
  price: string;
  discount_pct: number;
  zone: string;
  purchase_prob_pct: number;
  units: number;
  revenue: string;
  net_profit: string;
  net_margin_pct: number;
  note: string;
}

export interface PricePlan {
  phases: PricePhase[];
  total_units: number;
  total_revenue: string;
  total_net_profit: string;
  leftover_units: number;
  flat_units: number;
  flat_revenue: string;
  flat_net_profit: string;
  flat_leftover_units: number;
  verdict?: string;
  assumptions: string[];
  basis: string;
}

export interface CampaignLever {
  label: string;
  uplift_low_pct: number;
  uplift_high_pct: number;
  cost_pct: number;
  basis: string;
}

export interface CampaignScenario {
  goal: "clear_stock" | "boost_sales" | "defend_competition";
  goal_label: string;
  name: string;
  recommended: boolean;
  why: string;
  start_day: number;
  window_days: number;
  discount_pct: number;
  campaign_price: string;
  levers: CampaignLever[];
  baseline_units: number;
  units_low: number;
  units: number;
  units_high: number;
  extra_units: number;
  extra_revenue: string;
  profit_delta: string;
  margin_impact_pts: number;
  timing: string;
  rationale: string;
  assumptions: string[];
  basis: string;
}

export interface ForecastMilestone {
  day: number;
  units_low: number;
  units: number;
  units_high: number;
  period_units: number;
  revenue: string;
  net_revenue: string;
  stock_left: number;
}

export interface ForecastPoint {
  day: number;
  demand: number;
  sold: number;
  sold_low: number;
  sold_high: number;
}

export interface SalesForecast {
  milestones: ForecastMilestone[];
  curve: ForecastPoint[];
  stockout_day: number | null;
  leftover_units: number;
  lost_units: number;
  sell_through_pct: number;
  audience: number;
  purchase_prob_pct: number;
  assumptions: string[];
  basis: string;
}

export interface ReturnDriver {
  label: string;
  points: number;
  detail: string;
  basis: string;
}

export interface ReturnEstimate {
  rate_pct: number;
  low_pct: number;
  high_pct: number;
  base_pct: number;
  drivers: ReturnDriver[];
  gross_margin_pct: number;
  net_margin_pct: number;
  return_cost_per_sale: string;
  net_qty_if_sold_out: number;
  basis: string;
}

export interface PredictionRequest {
  assumptions?: Assumptions;
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
  reset_world?: boolean;
}

export interface PricePoint {
  price: string;
  too_cheap: number;
  cheap: number;
  expensive: number;
  too_expensive: number;
}

export interface PriceZone {
  key: "too_cheap" | "cheap" | "ideal" | "expensive" | "too_expensive";
  label: string;
  low: string;
  high: string | null;
  description: string;
}

export interface PriceStep {
  price: string;
  suspicious: number;
  fair: number;
  expensive: number;
  too_expensive: number;
  n: number;
  basis: "ladder" | "threshold";
}

export interface VanWestendorpResult {
  zones?: PriceZone[];
  optimal_price_point: string;
  indifference_price_point: string;
  acceptable_range_low: string;
  acceptable_range_high: string;
  curve: PricePoint[];
  quality?: "low" | "medium" | "high";
  quality_note?: string;
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
  price_steps?: PriceStep[];
  returns?: ReturnEstimate | null;
  forecast?: SalesForecast | null;
  price_plan?: PricePlan | null;
  campaigns?: CampaignScenario[];
  sensitivity?: SensitivityRow[];
  break_even?: BreakEven | null;
  confidence?: Confidence | null;
  size_curve?: { size: string; share_pct: number }[];
  seasonality?: Seasonality | null;
  raw_answers?: RawAnswer[];
  local_currency?: string | null;
  local_price?: string | null;
  fx_rate?: number | null;
}

export interface RawAnswer {
  agent: number;
  status: "json" | "partial" | "extracted" | "failed" | "empty";
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
  disclaimer?: string;
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
  answered?: number;
  agents?: number;
  chunk?: number;
  chunks?: number;
  phase?: string;
}

export interface StreamHandlers {
  onProgress: (e: ProgressEvent) => void;
  /** Sunucudan gelen her şey (ilerleme ya da kalp atışı) için: sunucunun canlı olduğunu gösterir. */
  onAlive?: (serverElapsedS?: number) => void;
  onConnection?: (state: "ok" | "reconnecting") => void;
  onRun?: (id: string, startedMs: number) => void;
}

const RUN_KEY = "talep-sim-run";
export const savedRun = (): string | null => {
  try { return sessionStorage.getItem(RUN_KEY); } catch { return null; }
};
const saveRun = (id: string | null) => {
  try {
    if (id) sessionStorage.setItem(RUN_KEY, id);
    else sessionStorage.removeItem(RUN_KEY);
  } catch { /* yok say */ }
};

interface StreamCtx { runId: string | null; nextSeq: number; result: PredictionResponse | null; error: Error | null }

async function readStream(res: Response, ctx: StreamCtx, h: StreamHandlers): Promise<void> {
  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  const handle = (line: string) => {
    if (!line.trim()) return;
    const ev = JSON.parse(line);
    h.onAlive?.(ev.elapsed);
    if (typeof ev.seq === "number") ctx.nextSeq = ev.seq + 1;
    if (ev.type === "run") { ctx.runId = ev.id; saveRun(ev.id); h.onRun?.(ev.id, Math.round(ev.started * 1000)); }
    else if (ev.type === "progress") h.onProgress(ev);
    else if (ev.type === "result") ctx.result = normalizePrediction(ev.data);
    else if (ev.type === "error") ctx.error = new Error(`Simülasyon başarısız (${ev.status}): ${ev.detail}`);
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
}

/** Akışı okur; bağlantı koparsa koşu kimliğiyle kaldığı yerden yeniden bağlanır (sunucu koşuyu sürdürür). */
async function consume(first: Response | null, ctx: StreamCtx, h: StreamHandlers): Promise<PredictionResponse> {
  let res = first;
  for (let attempt = 0; attempt <= 8; attempt++) {
    try {
      if (res) {
        h.onConnection?.("ok");
        await readStream(res, ctx, h);
      }
    } catch {
      /* bağlantı koptu: aşağıda yeniden bağlanılır */
    }
    if (ctx.result) { saveRun(null); return ctx.result; }
    if (ctx.error) { saveRun(null); throw ctx.error; }
    if (!ctx.runId) throw new Error("Bağlantı koptu ve koşu kimliği alınamadı; API'nin çalıştığını kontrol et.");
    h.onConnection?.("reconnecting");
    await new Promise((r) => setTimeout(r, 2000));
    try {
      res = await fetch(`${API_URL}/api/runs/${ctx.runId}/events?start=${ctx.nextSeq}`);
    } catch {
      res = null;
      continue;
    }
    if (res.status === 404) {
      saveRun(null);
      throw new Error("Bağlantı koptu ve sunucu koşuyu bulamadı (API yeniden başlatılmış olabilir). Simülasyonu yeniden çalıştır.");
    }
  }
  throw new Error("Sunucuya yeniden bağlanılamadı. API'nin çalıştığını kontrol et.");
}

/** NDJSON akışlı tahmin: ilerleme, kalp atışı ve otomatik yeniden bağlanma. Akış uç noktası yoksa /api/predict'e düşer. */
export async function predictStream(body: PredictionRequest, h: StreamHandlers): Promise<PredictionResponse> {
  const res = await fetch(`${API_URL}/api/predict/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (res.status === 404 || res.status === 405 || !res.body) return predict(body);
  if (!res.ok) throw new Error(`Simülasyon başarısız (${res.status}): ${await res.text()}`);
  return consume(res, { runId: null, nextSeq: 0, result: null, error: null }, h);
}

/** Sayfa yenilendiyse sürmekte olan koşuya baştan bağlanır (olaylar sunucuda saklı). */
export async function resumeRun(id: string, h: StreamHandlers): Promise<PredictionResponse> {
  const res = await fetch(`${API_URL}/api/runs/${id}/events?start=0`);
  if (res.status === 404) { saveRun(null); throw new Error("Önceki koşu bulunamadı (API yeniden başlatılmış olabilir)."); }
  return consume(res, { runId: id, nextSeq: 0, result: null, error: null }, h);
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
