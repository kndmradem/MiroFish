const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8100";

export type Basis = "dış veri" | "kural varsayımı" | "kullanıcı girdisi" | "bilinmiyor";
export type BrandTier = "budget" | "mass" | "upper_mass" | "premium" | "luxury";

export interface MallHit {
  id: string;
  name: string;
  aliases: string[];
  apparel_count: number;
  dense_area: boolean;
}

export interface MallCity {
  ulke: string;
  sehir: string;
  mall_count: number;
  verified: boolean;
}

export interface MallSignal {
  key: string;
  label: string;
  value: string | null;
  basis: Basis;
  note: string;
}

export interface SegmentShift {
  id: string;
  label: string;
  income_band: string;
  base_weight: number;
  mall_weight: number;
  multiplier: number;
}

export interface MallProfile {
  mall_id: string | null;
  name: string;
  ulke: string;
  sehir: string;
  region: string | null;
  source: { dataset: string; release: string; license: string; url: string; retrieved_at: string } | null;
  verified: boolean;
  manual: boolean;
  tenant_count: number;
  known_brands: { name: string; tier: string }[];
  unknown_brands: string[];
  tier_counts: Record<string, number>;
  price_index: number | null;
  city_price_index: number | null;
  price_segment: string | null;
  rivals: string[];
  signals: MallSignal[];
  segments: SegmentShift[];
  warnings: string[];
}

export interface ManualMall {
  name: string;
  tenants: string[];
  visitors_yearly?: number | null;
  visitors_source?: string | null;
}

async function ok<T>(res: Response, what: string): Promise<T> {
  if (!res.ok) throw new Error(`${what} (${res.status}): ${await res.text()}`);
  return res.json();
}

export async function fetchMallCities(): Promise<MallCity[]> {
  return ok(await fetch(`${API_URL}/api/malls/cities`), "AVM şehirleri alınamadı");
}

export async function searchMalls(ulke: string, sehir: string, q: string): Promise<MallHit[]> {
  const p = new URLSearchParams({ ulke, sehir, q });
  return ok(await fetch(`${API_URL}/api/malls/search?${p}`), "AVM araması başarısız");
}

export async function fetchMallProfile(body: {
  ulke: string;
  sehir: string;
  mall_id?: string;
  manual?: ManualMall;
  brand_tier?: BrandTier | null;
}): Promise<MallProfile> {
  return ok(
    await fetch(`${API_URL}/api/malls/profile`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
    "AVM profili alınamadı",
  );
}
