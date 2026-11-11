// Koleksiyon modu API istemcisi (/api/collections). Tekli ürün API'si (api.ts) değişmez.
import { normalizePrediction, try_, usd, type BrandProfile, type PredictionResponse, type RegionCode } from "@/lib/api";

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8100";

export type Basis = "ajan" | "kural varsayımı" | "LLM tahmini" | "ERP" | "kullanıcı girdisi";
export type Role = "hero" | "çekirdek" | "tamamlayıcı" | "destek" | "riskli" | "belirsiz";
export type DeclaredRole = "hero" | "çekirdek" | "tamamlayıcı" | "deneme";
/** koleksiyon: aynı panel bütün ürünlere bakar. bagimsiz: koleksiyonu olmayan ürünler, her biri kendi paneliyle. */
export type Kind = "koleksiyon" | "bagimsiz";
export type Decision = "üret" | "azalt" | "üretme";
export interface Reason { text: string; basis: Basis }

export interface CollectionItem {
  sku: string;
  name: string;
  category: string;
  subcategory: string;
  technical_specs: string;
  unit_cost: number | null;
  planned_price: number | null;
  images: string[];
  colors: string[];
  sizes: string;
  planned_qty: number | null;
  declared_role: DeclaredRole | null;
  outfit_group: string;
  launch_month: number | null;
  moq: number | null;
  attributes: Record<string, string>;
}

export interface CollectionMeta {
  kind: Kind;
  name: string;
  brand: string | null;
  brand_notes: string;
  brand_profile: BrandProfile | null;
  season: string;
  total_budget: number | null;
  currency: "TRY" | "USD";
  target_regions: RegionCode[];
  channel: "online" | "store";
  launch_month: number | null;
  usd_try_rate: number | null;
  notes: string;
}

export interface Issue { level: "hata" | "uyarı" | "bilgi"; sku: string | null; row: number | null; message: string }
export interface ItemPreview { row: number; item: CollectionItem; status: "ok" | "uyarı" | "hata" | "belirsiz"; match_rule: string; candidates: string[] }
export interface OrphanImage { file: string; suggestion: string | null; candidates: string[] }
export interface ImportPreview {
  collection_id: string;
  meta: CollectionMeta;
  items: ItemPreview[];
  orphans: OrphanImage[];
  issues: Issue[];
  column_map: Record<string, string>;
  ignored_columns: string[];
  counts: Record<string, number>;
}

export interface Collection { id: string; meta: CollectionMeta; items: CollectionItem[]; created: number; status: string }
export interface CollectionListRow { id: string; name: string; kind: Kind; season: string; status: string; items: number; created: number; running: boolean }

export interface RunStatus {
  collection_id: string;
  running: boolean;
  done: number;
  total: number;
  failed: string[];
  current: string | null;
  detail: string;
  started: number | null;
  finished: number | null;
  error: string | null;
  log: string[];
}

export interface Metric { value: number | null; low?: number | null; high?: number | null; basis: Basis; how: string }

export interface PriceZoneLite { key: string; label: string; low: number; high: number | null }

export interface ItemRegion {
  region: string;
  demand: number;
  enthusiast_pct: number | null;
  optimal_price: number;
  range_low: number;
  range_high: number;
  margin_pct: number;
  return_pct: number;
  demand_units: number;
  price_fit: "altında" | "içinde" | "üstünde" | null;
  ipp: number | null;
  zones: PriceZoneLite[];
  net_margin_pct: number | null;
  objections: string[];
  confidence: string;
}

export interface ItemResult {
  sku: string;
  name: string;
  category: string;
  image: string | null;
  unit_cost_usd: number | null;
  planned_price_usd: number | null;
  declared_role: string | null;
  regions: ItemRegion[];
  appeal: Metric;
  relative: Metric;
  rank: Metric;
  enthusiast_pct: Metric;
  role: Role;
  role_why: string;
  decision: Decision | null;
  decision_source: "sistem" | "kullanıcı";
  decision_reasons: Reason[];
  recommended_price: Metric;
  net_margin: Metric;
  recommended_qty: Metric;
  qty_by_region: Record<string, number>;
  planned_qty: number | null;
  flags: string[];
  failed_regions: string[];
  showcase: ShowcaseItem | null;
}

export interface ShowcaseItem { shown: number; best: number; worst: number; score: number; best_pct: number; worst_pct: number; rank: number; single_rank: number | null; together: number }
export interface PairCount { a: string; b: string; count: number; pct: number }
export interface ShowcaseSummary {
  n_answers: number;
  n_failed: number;
  n_persons: number;
  block_size: number;
  by_region: Record<string, number>;
  together_pairs: PairCount[];
  substitute_pairs: PairCount[];
  position: { position: string; pick_pct: number; expected_pct: number }[];
  position_warning: string | null;
  basis_note?: string | null;
  mean_n_buy: number | null;
  comments: string[];
  agreement_pct: number | null;
}

export interface ReachPoint { k: number; sku: string; name: string; reach_pct: number; added_pct: number }
export interface CannibalPair { a: string; b: string; category: string; overlap_pct: number; why: string }
export interface CategorySummary { category: string; count: number; roles: Record<string, number>; price_min: number | null; price_max: number | null; mean_appeal: number; in_zone: number; out_zone: number }
export interface Action { kind: string; text: string; skus: string[]; basis: Basis }

export interface CollectionSummary {
  n_items: number;
  n_evaluated: number;
  n_failed: number;
  reach: Metric;
  reach_by_region: Record<string, number>;
  reach_curve: ReachPoint[];
  roles: Record<string, number>;
  decisions: Record<Decision, number>;
  mean_appeal: Metric;
  categories: CategorySummary[];
  cannibal_pairs: CannibalPair[];
  budget_total_usd: number | null;
  budget_used_usd: number;
  total_qty: number;
  expected_units: Metric;
  actions: Action[];
}

export interface BrandEffect {
  name: string | null;
  tier: string;
  price_multiple: number;
  neutral_multiple: number;
  price_level_pct: number;
  brand_pull: number;
  price_sensitivity: number;
  regional_strength: Record<string, number>;
  demand_points: Record<string, number>;
  source: string;
  confidence: string;
  edited: boolean;
  basis: Basis;
  lines: string[];
  warning: string | null;
}

export interface CollectionResult {
  collection_id: string;
  name: string;
  kind: Kind;
  currency: "TRY" | "USD";
  fx_rate: number;
  regions: string[];
  items: ItemResult[];
  summary: CollectionSummary;
  notes: string[];
  data_basis: Record<string, unknown> | null;
  panel_shared: boolean;
  brand_effect: BrandEffect | null;
  showcase: ShowcaseSummary | null;
}

export interface WhatIf {
  exclude?: string[];
  planned_prices?: Record<string, number>;
  total_budget?: number | null;
  allocation_objective?: "balanced" | "profit" | "blended";
  decisions?: Record<string, Decision>;
}

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let msg = await res.text();
    try { msg = JSON.parse(msg).detail ?? msg; } catch { /* düz metin */ }
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return res.json();
}

export const templateUrl = `${API_URL}/api/collections/template.xlsx`;
export const exportUrl = (cid: string) => `${API_URL}/api/collections/${cid}/export.xlsx`;
export const imageUrl = (cid: string, path: string) =>
  `${API_URL}/api/collections/${cid}/images/${path.split("/").map(encodeURIComponent).join("/")}`;

/** Klasörden seçilen dosyalarda göreli yol (klasör/dosya) korunur; böylece SKU adlı klasörler eşleşir. */
export async function importCollection(sheet: File, images: File[], collectionId?: string, kind: Kind = "koleksiyon"): Promise<ImportPreview> {
  const fd = new FormData();
  fd.append("kind", kind);
  fd.append("sheet", sheet, sheet.name);
  for (const f of images) {
    const rel = (f as File & { webkitRelativePath?: string }).webkitRelativePath;
    // Klasör seçiminde en üst klasör adı atılır (ör. "SS27/SW27-001.jpg" -> "SW27-001.jpg")
    const name = rel ? rel.split("/").slice(1).join("/") || f.name : f.name;
    fd.append("images", f, name);
  }
  if (collectionId) fd.append("collection_id", collectionId);
  return json(await fetch(`${API_URL}/api/collections/import`, { method: "POST", body: fd }));
}

export const listCollections = async (kind?: Kind): Promise<CollectionListRow[]> =>
  json(await fetch(`${API_URL}/api/collections${kind ? `?kind=${kind}` : ""}`));
export const getCollection = async (cid: string): Promise<Collection> => json(await fetch(`${API_URL}/api/collections/${cid}`));
export const getPreview = async (cid: string): Promise<ImportPreview> => json(await fetch(`${API_URL}/api/collections/${cid}/preview`));

export async function confirmCollection(cid: string, meta: CollectionMeta, items: CollectionItem[]): Promise<Collection> {
  return json(await fetch(`${API_URL}/api/collections/${cid}/confirm`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ meta, items }),
  }));
}

export async function updateMeta(cid: string, meta: CollectionMeta): Promise<Collection> {
  return json(await fetch(`${API_URL}/api/collections/${cid}/meta`, {
    method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ meta }),
  }));
}

export async function startRun(cid: string, opts: { regions?: string[]; only?: string[]; rerun?: boolean; showcase?: boolean; block_size?: number } = {}): Promise<RunStatus> {
  return json(await fetch(`${API_URL}/api/collections/${cid}/run`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(opts),
  }));
}

export const runStatus = async (cid: string): Promise<RunStatus> => json(await fetch(`${API_URL}/api/collections/${cid}/status`));
export const stopRun = async (cid: string): Promise<RunStatus> => json(await fetch(`${API_URL}/api/collections/${cid}/stop`, { method: "POST" }));
export const getResult = async (cid: string): Promise<CollectionResult> => json(await fetch(`${API_URL}/api/collections/${cid}/result`));

export async function whatIf(cid: string, body: WhatIf): Promise<CollectionResult> {
  return json(await fetch(`${API_URL}/api/collections/${cid}/whatif`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  }));
}

export interface CollectionContext {
  decision: Decision | null; qty: number | null; qty_by_region: Record<string, number>;
  colors: { color: string; qty: number | null; decision: string | null }[]; detail_qty: number;
}

export async function itemPrediction(cid: string, sku: string): Promise<PredictionResponse & { collection_context?: CollectionContext }> {
  return normalizePrediction(await json(await fetch(`${API_URL}/api/collections/${cid}/items/${encodeURIComponent(sku)}/prediction`)));
}

/** Sonuçlar USD tutulur; ekranda koleksiyonun para biriminde gösterilir. */
export const money = (usdValue: number | null | undefined, currency: "TRY" | "USD", fx: number) =>
  usdValue == null ? "–" : currency === "TRY" ? try_(usdValue * fx) : usd(usdValue);

export const ROLE_LABEL: Record<Role, string> = {
  hero: "Hero", "çekirdek": "Çekirdek", "tamamlayıcı": "Tamamlayıcı", destek: "Destek", riskli: "Riskli", belirsiz: "Belirsiz",
};
export const ROLE_CLASS: Record<Role, string> = {
  hero: "bg-emerald-100 text-emerald-900 border-emerald-300",
  "çekirdek": "bg-sky-100 text-sky-900 border-sky-300",
  "tamamlayıcı": "bg-violet-100 text-violet-900 border-violet-300",
  destek: "bg-slate-100 text-slate-800 border-slate-300",
  riskli: "bg-rose-100 text-rose-900 border-rose-300",
  belirsiz: "bg-muted text-muted-foreground",
};

export const DECISION_LABEL: Record<Decision, string> = { "üret": "Üret", azalt: "Azalt", "üretme": "Üretme" };
export const DECISION_CLASS: Record<Decision, string> = {
  "üret": "bg-emerald-100 text-emerald-900 border-emerald-300",
  azalt: "bg-amber-100 text-amber-900 border-amber-300",
  "üretme": "bg-rose-100 text-rose-900 border-rose-300",
};
