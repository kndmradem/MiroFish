export const REGIONS = [
  { code: "EU", label: "Avrupa (EU)" },
  { code: "MENA", label: "Körfez (MENA)" },
  { code: "CIS", label: "Kafkaslar (CIS)" },
  { code: "US", label: "Amerika (US)" },
] as const;

export type RegionCode = (typeof REGIONS)[number]["code"];

export interface PredictionRequest {
  product_name: string;
  image_base64: string;
  technical_specs: string;
  unit_cost: string;
  total_production_budget: number;
  target_regions: RegionCode[];
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
}

export interface PredictionResponse {
  session_id: string;
  status: string;
  total_produced_qty: number;
  unallocated_budget: string;
  product_card: Record<string, unknown>;
  regional_breakdown: RegionPredictionResult[];
}

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function predict(body: PredictionRequest): Promise<PredictionResponse> {
  const res = await fetch(`${API_URL}/api/predict`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    throw new Error(`Simülasyon başarısız (${res.status}): ${await res.text()}`);
  }
  return res.json();
}

export const usd = (v: string | number) =>
  Number(v).toLocaleString("tr-TR", { style: "currency", currency: "USD" });
