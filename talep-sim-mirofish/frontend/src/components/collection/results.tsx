"use client";

import { Fragment, useEffect, useMemo, useState } from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import type { EChartsOption } from "echarts";
import { ChevronDown, ChevronRight, Download, ExternalLink, RotateCcw } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import {
  DECISION_CLASS, DECISION_LABEL, exportUrl, imageUrl, money, ROLE_CLASS, ROLE_LABEL, whatIf,
  type Basis, type CollectionResult, type ColorDecision, type Decision, type ItemResult, type Metric, type WhatIf,
} from "@/lib/collection-api";
import { cn } from "@/lib/utils";
import { ColorStrip, ColorsTab, ColorTable } from "./colors";
import { AudienceChip } from "@/components/audience-card";

const ReactECharts = dynamic(() => import("echarts-for-react"), { ssr: false });

const BASIS_CLASS: Record<Basis, string> = {
  ajan: "border-violet-300 bg-violet-50 text-violet-800",
  "kural varsayımı": "border-amber-300 bg-amber-50 text-amber-800",
  "LLM tahmini": "border-sky-300 bg-sky-50 text-sky-800",
  ERP: "border-emerald-300 bg-emerald-50 text-emerald-800",
  "kullanıcı girdisi": "border-slate-300 bg-slate-50 text-slate-700",
};

export function BasisChip({ basis, how }: { basis: Basis; how?: string }) {
  return <span title={how} className={cn("rounded-full border px-1.5 py-px text-[10px] font-medium whitespace-nowrap", BASIS_CLASS[basis])}>{basis}</span>;
}

function Tile({ label, value, sub, m }: { label: string; value: string; sub?: string; m?: Metric }) {
  return (
    <div className="grid gap-1 rounded-lg border p-3">
      <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">{label}{m && <BasisChip basis={m.basis} how={m.how} />}</div>
      <div className="text-2xl font-semibold">{value}</div>
      {sub && <div className="text-xs text-muted-foreground">{sub}</div>}
    </div>
  );
}

/** Başlıkta: ürünlerin hedef kitle dağılımı ve kaçının tahmin olduğu (panel her ürün için kitlesine göre seçilir). */
function audienceSummary(items: ItemResult[]): string {
  const withA = items.filter((i) => i.audience);
  if (!withA.length) return "";
  const cnt = new Map<string, number>();
  withA.forEach((i) => cnt.set(i.audience!.label, (cnt.get(i.audience!.label) ?? 0) + 1));
  const guessed = withA.filter((i) => i.audience!.source === "tahmin").length;
  return ` · hedef kitle: ${[...cnt].map(([l, n]) => `${n} ${l.toLowerCase()}`).join(", ")}${guessed ? ` (${guessed} ürün tahmin)` : ""}; panel her ürün için kendi kitlesine göre seçildi`;
}

const TABS = ["Özet", "Ürünler", "Renkler", "Vitrin", "Bölgeler", "Fiyat", "Bütçe"] as const;
type Tab = (typeof TABS)[number];
const DECISIONS: Decision[] = ["üret", "azalt", "üretme"];

export function DecisionChip({ d, user }: { d: Decision | null; user?: boolean }) {
  if (!d) return <span className="text-xs text-muted-foreground">–</span>;
  return (
    <span className={cn("rounded-full border px-2 py-0.5 text-xs font-medium whitespace-nowrap", DECISION_CLASS[d])}>
      {DECISION_LABEL[d]}{user ? " (elle)" : ""}
    </span>
  );
}

export function CollectionResults({ base }: { base: CollectionResult }) {
  const [tab, setTab] = useState<Tab>("Özet");
  const [view, setView] = useState<string>("genel");
  const [scenario, setScenario] = useState<WhatIf>({});
  const [res, setRes] = useState<CollectionResult>(base);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const active = !!(scenario.exclude?.length || Object.keys(scenario.planned_prices ?? {}).length || scenario.total_budget != null
    || scenario.allocation_objective || Object.keys(scenario.decisions ?? {}).length
    || scenario.color_min_qty != null || scenario.color_mix != null || Object.keys(scenario.color_decisions ?? {}).length);
  const indep = base.kind === "bagimsiz";
  const tabs = TABS.filter((t) => !(indep && t === "Vitrin") && !(t === "Renkler" && !base.color_plan));

  useEffect(() => { setRes(base); setScenario({}); setView("genel"); }, [base]);
  const one = view !== "genel" && base.regions.includes(view) ? view : null;
  useEffect(() => {
    if (!active) { setRes(base); return; }
    const t = setTimeout(() => {
      setBusy(true);
      whatIf(base.collection_id, scenario).then(setRes).catch((e) => setError(String(e.message ?? e))).finally(() => setBusy(false));
    }, 400);
    return () => clearTimeout(t);
  }, [scenario, active, base]);

  const cur = res.currency;
  const fx = res.fx_rate;
  const m = (v: number | null | undefined) => money(v, cur, fx);
  const excluded = new Set(scenario.exclude ?? []);
  const setDecision = (sku: string, d: Decision | "") =>
    setScenario((x) => {
      const ds = { ...(x.decisions ?? {}) };
      if (d) ds[sku] = d; else delete ds[sku];
      return { ...x, decisions: ds };
    });
  const setColor = (key: string, d: ColorDecision | "") =>
    setScenario((x) => {
      const ds = { ...(x.color_decisions ?? {}) };
      if (d) ds[key] = d; else delete ds[key];
      return { ...x, color_decisions: ds };
    });
  const toggleExclude = (sku: string, on: boolean) =>
    setScenario((s) => ({ ...s, exclude: on ? [...(s.exclude ?? []), sku] : (s.exclude ?? []).filter((x) => x !== sku) }));
  const s = res.summary;
  const allItems = useMemo(() => {
    // çıkarılan ürünler de tabloda (soluk) kalsın ki geri alınabilsin
    const map = new Map(res.items.map((i) => [i.sku, i]));
    const order = { "üret": 0, azalt: 1, "üretme": 2 } as Record<string, number>;
    const all = [...res.items, ...base.items.filter((i) => !map.has(i.sku))];
    return indep
      ? all.sort((a, b) => (order[a.decision ?? ""] ?? 3) - (order[b.decision ?? ""] ?? 3) || (b.appeal.value ?? -1) - (a.appeal.value ?? -1))
      : all.sort((a, b) => (a.rank.value ?? 999) - (b.rank.value ?? 999));
  }, [res, base, indep]);

  return (
    <Card>
      <CardHeader className="gap-3">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <CardTitle className="text-base">4. Sonuç: {res.name}</CardTitle>
            <CardDescription>
              {s.n_evaluated}/{s.n_items} ürün değerlendirildi · bölgeler: {res.regions.join(", ")}
              {res.panel_shared ? " · her bölgede bütün ürünlere aynı kişiler baktı" : ""}
              {indep ? " · her ürün kendi paneliyle ayrı değerlendirildi" : ""}
              {audienceSummary(res.items)}
              {res.data_basis?.persona_version ? ` · persona ${String(res.data_basis.persona_version)}` : ""}
              {res.data_basis?.context_as_of ? `, bağlam ${String(res.data_basis.context_as_of)}` : ""}
            </CardDescription>
          </div>
          <a href={exportUrl(res.collection_id)} className="inline-flex items-center gap-1 rounded-md border px-3 py-1.5 text-sm hover:bg-muted">
            <Download className="size-4" />Excel olarak indir
          </a>
        </div>
        {active && (
          <div className="flex flex-wrap items-center gap-2 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">
            Ne olur senaryosu açık{excluded.size ? `: ${excluded.size} ürün çıkarıldı` : ""}{Object.keys(scenario.planned_prices ?? {}).length ? `, ${Object.keys(scenario.planned_prices ?? {}).length} fiyat değişti` : ""}
            {scenario.total_budget != null ? ", bütçe değişti" : ""}{Object.keys(scenario.decisions ?? {}).length ? `, ${Object.keys(scenario.decisions ?? {}).length} karar elle değişti` : ""}
            {scenario.color_min_qty != null || scenario.color_mix != null || Object.keys(scenario.color_decisions ?? {}).length ? ", renk ayarı değişti" : ""}. Panel yeniden sorulmadı; sonuçlar kayıtlı cevaplardan yeniden hesaplandı.
            <Button size="sm" variant="outline" onClick={() => setScenario({})}><RotateCcw className="size-3" />Geri al</Button>
            {busy && <span className="text-xs">hesaplanıyor…</span>}
          </div>
        )}
        {error && <div className="text-sm text-rose-600">{error}</div>}
        <div className="flex flex-wrap gap-1 border-b">
          {tabs.map((t) => (
            <button key={t} onClick={() => setTab(t)}
              className={cn("-mb-px border-b-2 px-3 py-1.5 text-sm", tab === t ? "border-primary font-medium" : "border-transparent text-muted-foreground")}>{t}</button>
          ))}
        </div>
        {res.regions.length > 1 && <RegionBar regions={res.regions} view={view} setView={setView} tab={tab} />}
      </CardHeader>
      <CardContent>
        {tab === "Özet" && <Summary res={res} m={m} one={one} />}
        {tab === "Ürünler" && <Items res={res} items={one ? allItems.filter((i) => !i.regions.length || i.regions.some((r) => r.region === one)) : allItems}
          excluded={excluded} onExclude={toggleExclude} m={m} one={one}
          overrides={scenario.decisions ?? {}} onDecision={setDecision} colorOverrides={scenario.color_decisions ?? {}} onColor={setColor} />}
        {tab === "Renkler" && <ColorsTab res={res} scenario={scenario} setScenario={setScenario} BasisChip={BasisChip} one={one} />}
        {tab === "Vitrin" && <Showcase res={res} one={one} />}
        {tab === "Bölgeler" && <Heatmap res={res} one={one} />}
        {tab === "Fiyat" && <Prices res={res} m={m} scenario={scenario} setScenario={setScenario} one={one} />}
        {tab === "Bütçe" && <Budget res={res} m={m} scenario={scenario} setScenario={setScenario} one={one} />}
        {tab === "Özet" && <p className="mt-4 text-xs text-muted-foreground">Bir ürünün kararını değiştirmek için Ürünler sekmesinde &quot;Karar&quot; sütununu kullanın; bütçe dağıtımı anında yeniden hesaplanır.</p>}
      </CardContent>
    </Card>
  );
}

const TAB_SCOPE_NOTE: Partial<Record<Tab, string>> = {
  Vitrin: "Vitrin turunun sonuçları bölgeler birlikte toplanıyor; bu sekmede bölge kırılımı yok.",
};

/** Bütün sekmelere uygulanan bölge seçici. */
function RegionBar({ regions, view, setView, tab }: { regions: string[]; view: string; setView: (v: string) => void; tab: Tab }) {
  const one = view !== "genel" ? view : null;
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-md bg-muted/40 px-3 py-2 text-sm">
      <span className="text-xs font-medium">Bölge:</span>
      {["genel", ...regions].map((r) => (
        <button key={r} type="button" onClick={() => setView(r)}
          className={cn("rounded-full border px-3 py-1 text-xs", view === r ? "border-foreground bg-foreground text-background" : "bg-background hover:bg-muted")}>
          {r === "genel" ? "Genel (tüm bölgeler)" : r}
        </button>
      ))}
      <span className="text-xs text-muted-foreground">
        {TAB_SCOPE_NOTE[tab] ?? (one ? `Bu sekmedeki sayılar yalnızca ${one} bölgesinin.` : "Genel: bölgelerin toplamı / ortalaması; bölgeler birbirinden çok farklı olabilir, ayrıntı için bölge seçin.")}
      </span>
    </div>
  );
}

/** Ürünün seçilen bölgedeki kararı: diğer bölgelerde üretilip bu bölgeye adet düşmüyorsa bu bölge için "üretme". */
export function regionDecision(it: ItemResult, region: string | null): Decision | null {
  if (!region || !it.decision || it.decision === "üretme") return it.decision;
  const anyQty = Object.values(it.qty_by_region).some((x) => x > 0);
  return anyQty && !(it.qty_by_region[region] > 0) ? "üretme" : it.decision;
}

function DecisionTile({ res, counts, scope }: { res: CollectionResult; counts?: Record<string, number>; scope?: string }) {
  const d = counts ?? res.summary.decisions ?? {};
  return (
    <div className="grid gap-1 rounded-lg border p-3">
      <div className="flex items-center justify-between text-xs text-muted-foreground">Üretim kararı{scope ? ` (${scope})` : ""}
        <BasisChip basis="kural varsayımı" how="Talep (ajan) ve önerilen fiyattaki net marj eşiklerinden; koleksiyonda iç sıra ve kanibalizasyon da hesaba katılır" /></div>
      <div className="flex flex-wrap content-start items-start gap-1.5 pt-1">
        {DECISIONS.map((k) => <span key={k} className={cn("rounded-full border px-2 py-0.5 text-xs", DECISION_CLASS[k])}>{DECISION_LABEL[k]} {d[k] ?? 0}</span>)}
      </div>
    </div>
  );
}

const r1 = (x: number) => Math.round(x * 10) / 10;
const avg = (xs: number[]) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null);

/** Özet kutuları için seçilen bölgenin (ya da hepsinin) sayıları; hepsi ürün x bölge sonuçlarından türetilir. */
function regionView(res: CollectionResult, region: string | null) {
  const s = res.summary;
  const items = res.items.filter((i) => i.regions.length);
  const rows = items.flatMap((i) => i.regions.filter((r) => !region || r.region === region).map((r) => ({ i, r })));
  const appeal = region ? avg(rows.map((x) => x.r.demand)) : s.mean_appeal.value;
  const ent = rows.map((x) => x.r.enthusiast_pct).filter((x): x is number => x != null);
  const enthusiast = ent.length ? r1(avg(ent)!) : null;
  const decisions: Record<string, number> = { "üret": 0, azalt: 0, "üretme": 0 };
  let qty = 0, cost = 0;
  for (const it of items) {
    if (!it.decision) continue;
    if (!region) { decisions[it.decision] += 1; qty += it.recommended_qty.value ?? 0; continue; }
    if (!it.regions.some((r) => r.region === region)) continue;
    const q = it.qty_by_region[region] ?? 0;
    decisions[regionDecision(it, region)!] += 1;
    qty += q;
    cost += q * (it.unit_cost_usd ?? 0);
  }
  if (!region) qty = s.total_qty;
  const byRegion = res.regions.length > 1
    ? res.regions.map((rg) => `${rg} ${Math.round(avg(items.flatMap((i) => i.regions.filter((r) => r.region === rg).map((r) => r.demand))) ?? 0)}`).join(" · ")
    : "";
  const vals = rows.map((x) => x.r.demand);
  const spread = vals.length ? Math.max(...vals) - Math.min(...vals) : 0;
  const interestNote = vals.length
    ? (spread < 5 ? `ürünler arası fark ${spread} puan: panel ürünleri ayırt etmedi` : `ürün talepleri ${Math.min(...vals)}–${Math.max(...vals)} arası`)
    : "veri yok";
  return {
    appeal: appeal != null ? r1(appeal) : null, enthusiast, decisions, qty, cost,
    reach: region ? (s.reach_by_region[region] ?? null) : s.reach.value, byRegion, interestNote,
  };
}

function catStats(res: CollectionResult, category: string, region: string) {
  const regs = res.items.filter((i) => (i.category || "(kategorisiz)") === category)
    .flatMap((i) => i.regions.filter((r) => r.region === region));
  if (!regs.length) return { min: null, max: null, demand: null };
  const prices = regs.map((r) => r.optimal_price);
  return { min: Math.min(...prices), max: Math.max(...prices), demand: Math.round(avg(regs.map((r) => r.demand))!) };
}

function Summary({ res, m, one }: { res: CollectionResult; m: (v: number | null | undefined) => string; one: string | null }) {
  const s = res.summary;
  const indep = res.kind === "bagimsiz";
  const curve: EChartsOption = {
    grid: { left: 40, right: 16, top: 16, bottom: 60 },
    tooltip: { trigger: "axis", valueFormatter: (v) => `%${v}` },
    xAxis: { type: "category", data: s.reach_curve.map((p) => p.name), axisLabel: { rotate: 30, fontSize: 10 } },
    yAxis: { type: "value", max: 100, axisLabel: { formatter: "%{value}" } },
    series: [
      { type: "line", name: "Erişim", data: s.reach_curve.map((p) => p.reach_pct), smooth: true, areaStyle: { opacity: 0.15 } },
      { type: "bar", name: "Bu ürünün eklediği", data: s.reach_curve.map((p) => p.added_pct), barWidth: 10, itemStyle: { opacity: 0.5 } },
    ],
  };
  const sat = s.reach_curve.length;
  const scope = one ?? "tüm bölgeler";
  const v = regionView(res, one);
  return (
    <div className="grid gap-5">
      <div className={cn("grid gap-3 sm:grid-cols-2", indep ? "lg:grid-cols-4" : "lg:grid-cols-6")}>
        <DecisionTile res={res} counts={v.decisions} scope={res.regions.length > 1 ? scope : undefined} />
        {!indep && <Tile label={`Koleksiyon erişimi (${scope})`} m={s.reach} value={v.reach != null ? `%${v.reach}` : "–"}
          sub={v.reach != null ? "panelin en az bir ürünü çok beğenen kısmı" : "kişi bazlı puan yok"} />}
        <Tile label={`Ortalama talep skoru (${scope})`} m={s.mean_appeal} value={v.appeal != null ? String(v.appeal) : "–"}
          sub={one ? "0-100, bu bölgedeki ürünlerin ortalaması" : `0-100${v.byRegion ? ` · ${v.byRegion}` : ""}`} />
        <Tile label={`İlgi durumu (${scope})`} m={{ value: v.enthusiast, basis: "ajan", how: "Ürünlere 70+ ilgi puanı veren kişilerin oranı, ürün ortalaması." }}
          value={v.enthusiast != null ? `%${v.enthusiast}` : "–"}
          sub={v.interestNote} />
        {!indep && <div className="grid gap-1 rounded-lg border p-3">
          <div className="flex items-center justify-between text-xs text-muted-foreground">Ürün rolleri (tüm bölgeler)<BasisChip basis="kural varsayımı" how="Koleksiyon içi sıra, hevesli kişi oranı ve görüş ayrılığından kurallarla" /></div>
          <div className="flex flex-wrap gap-1.5 pt-1">
            {(["hero", "çekirdek", "tamamlayıcı", "destek", "riskli"] as const).filter((r) => r !== "tamamlayıcı" || s.roles[r]).map((r) => (
              <span key={r} className={cn("rounded-full border px-2 py-0.5 text-xs", ROLE_CLASS[r])}>{ROLE_LABEL[r]} {s.roles[r] ?? 0}</span>
            ))}
          </div>
        </div>}
        <Tile label={`Önerilen üretim (${scope})`} m={s.expected_units} value={`${v.qty.toLocaleString("tr-TR")} adet`}
          sub={one ? `${m(v.cost)} bütçe bu bölgeye · toplam ${s.total_qty.toLocaleString("tr-TR")} adet`
            : s.budget_total_usd ? `${m(s.budget_used_usd)} / ${m(s.budget_total_usd)} bütçe · 120 günde ~${(s.expected_units.value ?? 0).toLocaleString("tr-TR")} satış` : "bütçe girilmedi"} />
      </div>

      {res.brand_effect && <BrandEffectCard b={res.brand_effect} regions={res.regions} />}
      {!res.brand_effect && (
        <div className="rounded-md border p-3 text-sm text-muted-foreground">
          Marka girilmedi: fiyatlar nötr çarpanla (maliyet × 2,7) kuruldu <BasisChip basis="kural varsayımı" />. Marka değeri fiyatı ciddi etkiler; marka girip yeniden çalıştırın.
        </div>
      )}

      {s.actions.length > 0 && (
        <div className="grid gap-2">
          <h3 className="text-sm font-medium">{indep ? "Bu ürünler için öneriler" : "Bu koleksiyon için öneriler"}</h3>
          {s.actions.map((a, i) => (
            <div key={i} className="flex items-start gap-2 rounded-md border p-2 text-sm">
              {a.kind === "üretme" || a.kind === "azalt" ? <span className="shrink-0"><DecisionChip d={a.kind as Decision} /></span> : <Badge variant="outline" className="shrink-0">{a.kind}</Badge>}
              <span className="flex-1">{a.text}</span>
              <BasisChip basis={a.basis} />
            </div>
          ))}
        </div>
      )}

      {sat > 0 && (
        <div className="grid gap-1">
          <h3 className="flex items-center gap-2 text-sm font-medium">Erişim eğrisi <BasisChip basis="ajan" how="En çok yeni kişi getiren ürün sırayla eklenir (TURF)." /></h3>
          <p className="text-xs text-muted-foreground">
            İlk {sat} ürün panelin %{s.reach_curve[sat - 1].reach_pct}&apos;ine ulaşıyor; listede olmayan ürünler panelde yeni bir kişiye ulaşmıyor (başka ürünü seven kişileri seviyor).
          </p>
          <ReactECharts option={curve} style={{ height: 280 }} notMerge />
        </div>
      )}

      {s.cannibal_pairs.length > 0 && (
        <div className="grid gap-2">
          <h3 className="flex items-center gap-2 text-sm font-medium">Birbirinin müşterisini paylaşan ürünler <BasisChip basis="ajan" /><BasisChip basis="kural varsayımı" /></h3>
          {s.cannibal_pairs.map((p) => {
            const a = res.items.find((i) => i.sku === p.a), b = res.items.find((i) => i.sku === p.b);
            return <div key={p.a + p.b} className="text-sm">{a?.name} ↔ {b?.name} <span className="text-muted-foreground">({p.category}, örtüşme %{p.overlap_pct})</span></div>;
          })}
        </div>
      )}

      <div className="grid gap-2">
        <h3 className="text-sm font-medium">Kategoriler ({scope})</h3>
        <Table>
          <TableHeader><TableRow>
            <TableHead>Kategori</TableHead><TableHead className="text-right">Ürün</TableHead>{!indep && <TableHead>Roller (tüm bölgeler)</TableHead>}
            <TableHead className="text-right">Önerilen fiyat aralığı</TableHead><TableHead className="text-right">Ort. talep</TableHead>
          </TableRow></TableHeader>
          <TableBody>
            {s.categories.map((c) => {
              const regs = one ? [one] : res.regions;
              const stats = regs.map((r) => ({ r, ...catStats(res, c.category, r) }));
              return (
                <TableRow key={c.category}>
                  <TableCell>{c.category}</TableCell>
                  <TableCell className="text-right">{c.count}</TableCell>
                  {!indep && <TableCell className="text-xs">{Object.entries(c.roles).filter(([, v]) => v).map(([k, v]) => `${ROLE_LABEL[k as keyof typeof ROLE_LABEL]} ${v}`).join(" · ")}</TableCell>}
                  <TableCell className="text-right text-xs">
                    {stats.map((x) => <div key={x.r} className="whitespace-nowrap">{!one && <span className="mr-1 font-mono text-muted-foreground">{x.r}</span>}{x.min != null ? `${m(x.min)} – ${m(x.max)}` : "–"}</div>)}
                  </TableCell>
                  <TableCell className="text-right text-xs">
                    {stats.map((x) => <div key={x.r} className="whitespace-nowrap">{!one && <span className="mr-1 font-mono text-muted-foreground">{x.r}</span>}{x.demand ?? "–"}</div>)}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>

      <ul className="list-disc space-y-1 pl-5 text-xs text-muted-foreground">
        {res.notes.map((n, i) => <li key={i}>{n}</li>)}
      </ul>
    </div>
  );
}

function BrandEffectCard({ b, regions }: { b: NonNullable<CollectionResult["brand_effect"]>; regions: string[] }) {
  return (
    <div className="grid gap-2 rounded-lg border p-3">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-sm font-medium">Marka etkisi: {b.name ?? "isimsiz"}</h3>
        <span className="text-xs text-muted-foreground">profil kaynağı</span><BasisChip basis={b.basis} />
        <span className="text-xs text-muted-foreground">fiyata etkisi</span><BasisChip basis="kural varsayımı" />
        <span className="text-xs text-muted-foreground">panel cevabı</span><BasisChip basis="ajan" />
      </div>
      {b.warning && <div className="rounded-md border border-amber-300 bg-amber-50 px-2 py-1 text-xs text-amber-900">{b.warning}</div>}
      <div className="grid gap-2 text-sm sm:grid-cols-2 lg:grid-cols-4">
        <div><div className="text-xs text-muted-foreground">Segment</div>{b.tier}</div>
        <div><div className="text-xs text-muted-foreground">Fiyat çarpanı (satış ÷ maliyet)</div>× {b.price_multiple} <span className="text-xs text-muted-foreground">(nötr × {b.neutral_multiple})</span></div>
        <div><div className="text-xs text-muted-foreground">Fiyat seviyesine etkisi</div>
          <span className={b.price_level_pct >= 0 ? "text-emerald-700" : "text-rose-700"}>%{b.price_level_pct > 0 ? "+" : ""}{b.price_level_pct}</span></div>
        <div><div className="text-xs text-muted-foreground">Bölge bilinirliği</div>{regions.map((r) => `${r} ${b.regional_strength[r] ?? 50}`).join(" · ")}</div>
      </div>
      <ul className="list-disc space-y-0.5 pl-5 text-xs text-muted-foreground">{b.lines.map((l, i) => <li key={i}>{l}</li>)}</ul>
    </div>
  );
}

function Items({ res, items, excluded, onExclude, m, overrides, onDecision, colorOverrides, onColor, one }: {
  res: CollectionResult; items: ItemResult[]; excluded: Set<string>; onExclude: (sku: string, on: boolean) => void; one: string | null;
  m: (v: number | null | undefined) => string; overrides: Record<string, Decision>; onDecision: (sku: string, d: Decision | "") => void;
  colorOverrides: Record<string, ColorDecision>; onColor: (key: string, d: ColorDecision | "") => void;
}) {
  const [open, setOpen] = useState<string | null>(null);
  const n = res.summary.n_evaluated;
  const indep = res.kind === "bagimsiz";
  const cols = indep ? 8 : 12;
  const rs = one ? ` (${one})` : "";
  const all = one ? " (tüm bölgeler)" : "";
  return (
    <div className="overflow-x-auto">
      {one && <p className="mb-2 rounded-md border border-sky-200 bg-sky-50 px-2 py-1 text-xs text-sky-900">
        Talep, karar, önerilen fiyat, net marj ve adet {one} bölgesine göre. Sıra, koleksiyona göre konum, vitrin sırası ve rol bütün bölgelerin birlikte sonucu.
        Bir ürünün kararı başka bölgede &quot;üret&quot; olsa da {one}&apos;e adet düşmüyorsa burada &quot;üretme&quot; görünür.</p>}
      <p className="mb-2 flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
        Kaynaklar: talep, önerilen fiyat ve kabul aralığı <BasisChip basis="ajan" />, net marj, karar eşikleri ve adet <BasisChip basis="kural varsayımı" />,
        maliyet{indep ? "" : " ve hedef rol"} <BasisChip basis="kullanıcı girdisi" />. Satıra tıklayınca kararın gerekçesi ve bölge ayrıntısı açılır.
        {!indep && <> &quot;Çıkar&quot; kutusu ürünü ne olur senaryosunda koleksiyondan tamamen çıkarır.</>}
      </p>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-6" /><TableHead>Ürün</TableHead><TableHead>Karar{rs}</TableHead>
            {!indep && <TableHead>Sıra{all}</TableHead>}
            <TableHead className="text-right">Talep{rs}</TableHead>
            {!indep && <><TableHead>Koleksiyona göre{all}</TableHead><TableHead className="text-right">Vitrin sırası{all}</TableHead><TableHead>Rol (hedef → panel){all}</TableHead></>}
            <TableHead className="text-right">Önerilen fiyat{rs}</TableHead><TableHead className="text-right">Net marj{rs}</TableHead>
            <TableHead className="text-right">Önerilen adet{rs}</TableHead><TableHead>Bayraklar</TableHead>
            {!indep && <TableHead>Çıkar</TableHead>}
          </TableRow>
        </TableHeader>
        <TableBody>
          {items.map((it) => {
            const ex = excluded.has(it.sku);
            const rel = it.relative.value ?? 0;
            const rr = one ? it.regions.find((x) => x.region === one) : undefined;
            const rp = rr ? { ...it.recommended_price, value: rr.optimal_price, low: rr.range_low, high: rr.range_high, how: `${one} paneli` } : it.recommended_price;
            const dec = regionDecision(it, one);
            const nm = rr ? rr.net_margin_pct : it.net_margin.value;
            const qty = one ? (it.decision ? (it.qty_by_region[one] ?? 0) : null) : it.recommended_qty.value;
            return (
              <Fragment key={it.sku}>
                <TableRow className={cn(ex && "opacity-40", dec === "üretme" && !ex && "bg-rose-50/40")}>
                  <TableCell>
                    <button onClick={() => setOpen(open === it.sku ? null : it.sku)} disabled={!it.regions.length} aria-label="Ayrıntı">
                      {open === it.sku ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
                    </button>
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center gap-2">
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      {it.image && <img src={imageUrl(res.collection_id, it.image)} alt="" className="size-11 rounded object-cover" />}
                      <div className="min-w-40 whitespace-normal"><div className="font-medium">{it.name}</div><div className="font-mono text-[11px] text-muted-foreground">{it.sku} · {it.category || "kategorisiz"}</div><AudienceChip a={it.audience} className="mt-0.5" /><ColorStrip it={it} region={one} /></div>
                    </div>
                  </TableCell>
                  <TableCell className="min-w-44 whitespace-normal">
                    <div className="flex items-center gap-1.5">
                      <DecisionChip d={dec} user={it.decision_source === "kullanıcı"} />
                      {it.decision && (
                        <select className="h-6 rounded border bg-background px-1 text-[11px]" value={overrides[it.sku] ?? ""} title="Kararı elle değiştir"
                          onChange={(e) => onDecision(it.sku, e.target.value as Decision | "")}>
                          <option value="">sistem</option>
                          {DECISIONS.map((d) => <option key={d} value={d}>{DECISION_LABEL[d]}</option>)}
                        </select>
                      )}
                    </div>
                    {dec !== it.decision && <div className="mt-1 text-[11px] leading-snug text-muted-foreground">Genel karar: {it.decision ? DECISION_LABEL[it.decision] : "–"}; {one}&apos;e adet düşmedi.</div>}
                    {it.decision_reasons[0] && <div className="mt-1 text-[11px] leading-snug text-muted-foreground">{it.decision_reasons[0].text}</div>}
                    {!it.decision && <div className="mt-1 text-[11px] text-muted-foreground">{it.role_why}</div>}
                  </TableCell>
                  {!indep && (
                    <TableCell className="whitespace-nowrap" title={it.rank.how}>
                      {it.rank.value != null ? <><b>{it.rank.value}</b><span className="text-muted-foreground">/{n}</span>{it.rank.low != null && <span className="text-xs text-muted-foreground"> ({it.rank.low}-{it.rank.high})</span>}</> : "–"}
                    </TableCell>
                  )}
                  <TableCell className="text-right">{rr ? rr.demand : (it.appeal.value ?? "–")}</TableCell>
                  {!indep && (
                    <>
                      <TableCell title={it.relative.how}>
                        {it.relative.value != null && (
                          <div className="flex w-24 items-center">
                            <div className="relative h-2 w-full rounded bg-muted">
                              <div className="absolute top-0 left-1/2 h-2 w-px bg-foreground/40" />
                              <div className={cn("absolute top-0 h-2 rounded", rel >= 0 ? "left-1/2 bg-emerald-500" : "right-1/2 bg-rose-400")}
                                style={{ width: `${Math.min(50, Math.abs(rel) * 25)}%` }} />
                            </div>
                          </div>
                        )}
                      </TableCell>
                      <TableCell className="text-right" title="Ürünler bir arada gösterildiğinde seçilme sırası">
                        {it.showcase ? <><b>{it.showcase.rank}</b><div className="text-[11px] text-muted-foreground">en çok %{it.showcase.best_pct}</div></> : "–"}
                      </TableCell>
                      <TableCell title={it.role_why}>
                        <span className="text-xs text-muted-foreground">{it.declared_role ? `${it.declared_role} → ` : ""}</span>
                        <span className={cn("rounded-full border px-2 py-0.5 text-xs", ROLE_CLASS[it.role])}>{ROLE_LABEL[it.role]}</span>
                      </TableCell>
                    </>
                  )}
                  <TableCell className="text-right whitespace-nowrap" title={rp.how}>
                    {rp.value != null ? <><b>{m(rp.value)}</b>
                      {rp.low != null && <div className="text-[11px] text-muted-foreground">kabul {m(rp.low)} – {m(rp.high)}</div>}</> : "–"}
                  </TableCell>
                  <TableCell className={cn("text-right", nm != null && nm < 15 && "text-rose-700")} title={it.net_margin.how}>
                    {nm != null ? `%${nm}` : "–"}
                  </TableCell>
                  <TableCell className="text-right" title={it.recommended_qty.how}>{qty != null ? qty.toLocaleString("tr-TR") : "–"}
                    {one && it.recommended_qty.value != null && <div className="text-[11px] text-muted-foreground">toplam {it.recommended_qty.value.toLocaleString("tr-TR")}</div>}
                    {it.planned_qty != null && !one && <div className="text-[11px] text-muted-foreground">plan {it.planned_qty.toLocaleString("tr-TR")}</div>}</TableCell>
                  <TableCell className="max-w-48 text-xs whitespace-normal">{it.flags.join(", ")}</TableCell>
                  {!indep && <TableCell><Checkbox checked={ex} onCheckedChange={(v) => onExclude(it.sku, v === true)} /></TableCell>}
                </TableRow>
                {open === it.sku && (
                  <TableRow className="bg-muted/30 hover:bg-muted/30">
                    <TableCell colSpan={cols}>
                      <div className="grid gap-3 py-1">
                        {it.decision_reasons.length > 0 && (
                          <div className="grid gap-1">
                            <div className="flex items-center gap-2 text-sm font-medium">Karar: <DecisionChip d={it.decision} user={it.decision_source === "kullanıcı"} /> gerekçeler</div>
                            <ul className="grid gap-0.5 text-sm">
                              {it.decision_reasons.map((r, k) => (
                                <li key={k} className="flex items-start gap-2"><span className="mt-1.5 size-1 shrink-0 rounded-full bg-foreground/50" /><span className="flex-1">{r.text}</span><BasisChip basis={r.basis} /></li>
                              ))}
                            </ul>
                          </div>
                        )}
                        {!indep && <div className="text-xs text-muted-foreground">Rol: {it.role_why}</div>}
                        <ColorTable res={res} it={it} overrides={colorOverrides} onColor={onColor} BasisChip={BasisChip} region={one} />
                        <Table>
                          <TableHeader><TableRow>
                            <TableHead>Bölge</TableHead><TableHead className="text-right">Talep</TableHead><TableHead className="text-right">Hevesli</TableHead>
                            <TableHead className="text-right">Önerilen fiyat</TableHead><TableHead className="text-right">Kabul aralığı</TableHead>
                            <TableHead className="text-right">Brüt marj</TableHead><TableHead className="text-right">Net marj</TableHead><TableHead className="text-right">İade</TableHead><TableHead className="text-right">Adet</TableHead>
                            <TableHead>En sık itirazlar</TableHead><TableHead>Güven</TableHead>
                          </TableRow></TableHeader>
                          <TableBody>
                            {it.regions.filter((r) => !one || r.region === one).map((r) => (
                              <TableRow key={r.region}>
                                <TableCell>{r.region}</TableCell><TableCell className="text-right">{r.demand}</TableCell>
                                <TableCell className="text-right">{r.enthusiast_pct != null ? `%${r.enthusiast_pct}` : "–"}</TableCell>
                                <TableCell className="text-right">{m(r.optimal_price)}</TableCell>
                                <TableCell className="text-right whitespace-nowrap">{m(r.range_low)} – {m(r.range_high)}</TableCell>
                                <TableCell className="text-right">%{r.margin_pct}</TableCell>
                                <TableCell className="text-right">{r.net_margin_pct != null ? `%${r.net_margin_pct}` : "–"}</TableCell>
                                <TableCell className="text-right">%{r.return_pct}</TableCell>
                                <TableCell className="text-right">{it.qty_by_region[r.region] ?? "–"}</TableCell>
                                <TableCell className="text-xs">{r.objections.join(" · ")}</TableCell><TableCell className="text-xs">{r.confidence}</TableCell>
                              </TableRow>
                            ))}
                          </TableBody>
                        </Table>
                        <Link className="inline-flex w-fit items-center gap-1 text-sm underline" target="_blank"
                          href={`/?koleksiyon=${encodeURIComponent(res.collection_id)}&sku=${encodeURIComponent(it.sku)}`}>
                          <ExternalLink className="size-3" />Tekli ürün ekranında ayrıntı (fiyat eğrisi, satış tahmini, senaryolar)
                        </Link>
                      </div>
                    </TableCell>
                  </TableRow>
                )}
              </Fragment>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}

function Showcase({ res, one }: { res: CollectionResult; one: string | null }) {
  const v = res.showcase;
  if (!v) {
    return (
      <p className="text-sm text-muted-foreground">
        Bu koşuda vitrin turu yok. Panel veya karma motorla (SIM_ENGINE=panel / hybrid) &quot;Vitrin turu&quot; kutusu işaretli çalıştırın; tek tek sonuçlar
        yeniden sorulmaz, yalnızca vitrin soruları eklenir.
      </p>
    );
  }
  const name = (sku: string) => res.items.find((i) => i.sku === sku)?.name ?? sku;
  const items = res.items.filter((i) => i.showcase).sort((a, b) => a.showcase!.rank - b.showcase!.rank);
  const bar = (p: number, cls: string) => <div className="h-2 rounded bg-muted"><div className={cn("h-2 rounded", cls)} style={{ width: `${Math.min(100, p)}%` }} /></div>;
  return (
    <div className="grid gap-5">
      {one && <p className="rounded-md border border-sky-200 bg-sky-50 px-2 py-1 text-xs text-sky-900">
        {one} seçili, ama vitrin turu sonuçları bütün bölgelerin panelinden birlikte toplanıyor. Bu sekmedeki sayılar tüm bölgelerin.</p>}
      <p className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
        Panel ürünleri en fazla {v.block_size} ürünlük gruplar halinde, her kişide farklı karıştırılmış sırayla bir arada gördü ve seçti
        <BasisChip basis="ajan" />. {v.n_persons} kişi, {v.n_answers} grup cevabı{v.n_failed ? `, ${v.n_failed} okunamadı` : ""}
        {v.mean_n_buy != null ? ` · kişi başı bir gruptan ortalama ${v.mean_n_buy} parça` : ""}.
        {v.agreement_pct != null && ` Tek tek sıralama ile vitrin sıralaması ${
          v.agreement_pct >= 60 ? "büyük ölçüde aynı" : v.agreement_pct >= 30 ? "kısmen benzer" : v.agreement_pct > -30 ? "birbirinden bağımsız" : "çoğunlukla ters"
        } (sıra korelasyonu ${(v.agreement_pct / 100).toFixed(2)}; 1 tam aynı, 0 ilişkisiz, -1 tam ters). Fark büyükse ürünler yan yana görülünce farklı algılanıyor demektir.`}
      </p>
      {v.basis_note && <p className="rounded-md border border-amber-300 bg-amber-50 p-2 text-xs">{v.basis_note}</p>}
      <div className={cn("rounded-md border p-3 text-sm", v.position_warning ? "border-amber-300 bg-amber-50" : "")}>
        <div className="mb-2 flex items-center gap-2 font-medium">Sıra etkisi kontrolü <BasisChip basis="ajan" how="Seçilen ürünlerin listedeki konumu" /></div>
        <div className="grid gap-1 sm:grid-cols-3">
          {v.position.map((p) => (
            <div key={p.position} className="text-xs">
              <div>{p.position === "ilk" ? "Listede ilk" : p.position === "son" ? "Listede son" : "Ortadakiler"}: seçimlerin %{p.pick_pct} <span className="text-muted-foreground">(beklenen %{p.expected_pct})</span></div>
              {bar(p.expected_pct ? (50 * p.pick_pct) / p.expected_pct : 0, p.expected_pct && p.pick_pct > 1.5 * p.expected_pct ? "bg-amber-500" : "bg-emerald-500")}
            </div>
          ))}
        </div>
        <div className="mt-2 text-xs">{v.position_warning ?? "Seçimler listedeki konuma göre belirgin kaymıyor."}</div>
      </div>
      <Table>
        <TableHeader><TableRow>
          <TableHead>Vitrin sırası</TableHead><TableHead>Ürün</TableHead><TableHead>En çok seçilen</TableHead><TableHead>Almam denen</TableHead>
          <TableHead className="text-right">Kombinde</TableHead><TableHead className="text-right">Tek tek sırası</TableHead><TableHead>Not</TableHead>
        </TableRow></TableHeader>
        <TableBody>
          {items.map((i) => {
            const x = i.showcase!;
            return (
              <TableRow key={i.sku}>
                <TableCell><b>{x.rank}</b></TableCell>
                <TableCell>{i.name}<div className="text-[11px] text-muted-foreground">{x.shown} kez gösterildi</div></TableCell>
                <TableCell className="w-40"><div className="text-xs">%{x.best_pct}</div>{bar(x.best_pct, "bg-emerald-500")}</TableCell>
                <TableCell className="w-40"><div className="text-xs">%{x.worst_pct}</div>{bar(x.worst_pct, "bg-rose-400")}</TableCell>
                <TableCell className="text-right">{x.together}</TableCell>
                <TableCell className="text-right">{x.single_rank ?? "–"}</TableCell>
                <TableCell className="text-xs">{i.flags.filter((f) => f.startsWith("vitrinde")).join(", ")}{i.role === "tamamlayıcı" ? " tamamlayıcı parça" : ""}</TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
      <div className="grid gap-4 md:grid-cols-2">
        <div className="grid content-start gap-1">
          <h3 className="text-sm font-medium">Birlikte alınan ürünler (kombin)</h3>
          {v.together_pairs.length ? v.together_pairs.map((p) => (
            <div key={p.a + p.b} className="text-sm">{name(p.a)} + {name(p.b)} <span className="text-muted-foreground">· {p.count} kez, yan yana gösterildiklerinde %{p.pct}</span></div>
          )) : <p className="text-xs text-muted-foreground">En az 2 kez birlikte seçilen çift yok.</p>}
        </div>
        <div className="grid content-start gap-1">
          <h3 className="text-sm font-medium">Birbirinin yerine geçen ürünler</h3>
          {v.substitute_pairs.length ? v.substitute_pairs.map((p) => (
            <div key={p.a + p.b} className="text-sm">{name(p.a)} / {name(p.b)} <span className="text-muted-foreground">· {p.count} kişi &quot;ikisinden birini&quot; dedi</span></div>
          )) : <p className="text-xs text-muted-foreground">En az 2 kişinin işaretlediği çift yok.</p>}
        </div>
      </div>
      {v.comments.length > 0 && (
        <div className="grid gap-1">
          <h3 className="flex items-center gap-2 text-sm font-medium">Koleksiyon hakkında panel yorumlarından örnekler <BasisChip basis="ajan" /></h3>
          {v.comments.map((c, i) => <div key={i} className="text-sm text-muted-foreground">“{c}”</div>)}
        </div>
      )}
    </div>
  );
}

function Heatmap({ res, one }: { res: CollectionResult; one: string | null }) {
  const regs = one ? [one] : res.regions;
  const dOf = (i: ItemResult) => i.regions.find((r) => r.region === one)?.demand ?? -1;
  const items = res.items.filter((i) => i.regions.some((r) => regs.includes(r.region)))
    .sort((a, b) => (one ? dOf(b) - dOf(a) : (a.rank.value ?? 0) - (b.rank.value ?? 0)));
  const data = items.flatMap((it, y) => it.regions.filter((r) => regs.includes(r.region)).map((r) => [regs.indexOf(r.region), y, r.demand]));
  const opt: EChartsOption = {
    tooltip: { formatter: (p) => { const d = (p as { data: number[] }).data; return `${items[d[1]].name} · ${regs[d[0]]}: talep ${d[2]}`; } },
    grid: { left: 160, right: 20, top: 10, bottom: 50 },
    xAxis: { type: "category", data: regs, position: "top" },
    yAxis: { type: "category", data: items.map((i) => i.name), inverse: true, axisLabel: { width: 150, overflow: "truncate" } },
    visualMap: { min: 0, max: 100, orient: "horizontal", left: "center", bottom: 0, calculable: false, inRange: { color: ["#fee2e2", "#fef9c3", "#bbf7d0", "#15803d"] } },
    series: [{ type: "heatmap", data, label: { show: true } }],
  };
  const byRegion = Object.fromEntries(Object.entries(res.summary.reach_by_region).filter(([r]) => !one || r === one));
  return (
    <div className="grid gap-3">
      <p className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">Ürün × bölge talep skoru (0-100) <BasisChip basis="ajan" />. {one ? `Yalnızca ${one}, talebe göre sıralı.` : "Bir ürün bir bölgede zayıfsa o bölgenin koleksiyonundan çıkarılabilir."}</p>
      {Object.keys(byRegion).length > 0 && (
        <div className="flex flex-wrap gap-2 text-sm">
          {Object.entries(byRegion).map(([r, v]) => <Badge key={r} variant="outline">{r}: erişim %{v}</Badge>)}
        </div>
      )}
      <ReactECharts option={opt} style={{ height: Math.max(220, 34 * items.length + 80) }} notMerge />
    </div>
  );
}

const ZONE_CLASS: Record<string, string> = {
  too_cheap: "bg-slate-200", cheap: "bg-sky-200", ideal: "bg-emerald-300", expensive: "bg-amber-200", too_expensive: "bg-rose-200",
};

function Prices({ res, m, scenario, setScenario, one }: {
  res: CollectionResult; m: (v: number | null | undefined) => string; scenario: WhatIf; setScenario: (f: (s: WhatIf) => WhatIf) => void; one: string | null;
}) {
  const regs = one ? [one] : res.regions;
  const items = res.items.filter((i) => i.regions.length);
  const cats = Array.from(new Set(items.map((i) => i.category || "kategorisiz")));
  const legend = items.flatMap((i) => i.regions).find((r) => r.zones.length)?.zones ?? [];
  return (
    <div className="grid gap-4">
      <div className="flex items-start gap-3 text-xs text-muted-foreground">
        <p className="flex-1 leading-relaxed">
          Renkli bantlar panelin fiyat bölgeleri (Van Westendorp) <BasisChip basis="ajan" />, koyu çizgi sistemin önerdiği en kârlı fiyat.
          Satış fiyatını siz girmiyorsunuz; isterseniz sağdaki kutuya bir fiyat yazıp marjı ve kararı deneyebilirsiniz (panel yeniden sorulmaz) <BasisChip basis="kullanıcı girdisi" />.
          Her satırın ölçeği kendi fiyat aralığına göredir.
          {!one && regs.length > 1 && " Genel görünümde her ürün için bölge başına ayrı satır var; tek bölgeye bakmak için yukarıdan bölge seçin."}
        </p>
      </div>
      {legend.length > 0 && (
        <div className="flex flex-wrap gap-3 text-xs">
          {legend.map((z) => <span key={z.key} className="flex items-center gap-1"><span className={cn("inline-block size-3 rounded-sm", ZONE_CLASS[z.key] ?? "bg-muted")} />{z.label}</span>)}
        </div>
      )}
      {cats.map((c) => {
        const rows = items.filter((i) => (i.category || "kategorisiz") === c);
        return (
          <div key={c} className="grid gap-2">
            <h3 className="text-sm font-medium">{c}</h3>
            {rows.flatMap((i) => regs.map((region, ri) => {
              const r = i.regions.find((x) => x.region === region);
              if (!r) return null;
              const first = ri === 0 || !i.regions.some((x) => x.region === regs[ri - 1]);
              const trial = i.planned_price_usd;
              const min = Math.min(r.range_low * 0.6, trial ?? Infinity);
              const max = Math.max(r.range_high * 1.4, trial ? trial * 1.05 : 0);
              const pos = (v: number) => Math.max(0, Math.min(100, (100 * (v - min)) / (max - min || 1)));
              const zones = r.zones.length ? r.zones : [{ key: "ideal", label: "Kabul aralığı", low: r.range_low, high: r.range_high }];
              return (
                <div key={i.sku + region} className={cn("grid grid-cols-[minmax(110px,190px)_1fr_minmax(150px,auto)_110px] items-center gap-3 text-sm", !one && regs.length > 1 && first && "mt-1 border-t pt-2")}>
                  <span className="grid min-w-0 gap-0.5">
                    {(one || first || regs.length === 1) && <span className="truncate" title={i.name}>{i.name}</span>}
                    <span className="flex items-center gap-1.5">{!one && regs.length > 1 && <span className="rounded border px-1 font-mono text-[11px]">{region}</span>}<DecisionChip d={regionDecision(i, region)} /></span>
                  </span>
                  <div className="relative h-7 overflow-hidden rounded bg-muted/50">
                    {zones.map((z) => {
                      const lo = pos(z.low), hi = pos(z.high ?? max);
                      return <div key={z.key} className={cn("absolute top-1 h-5", ZONE_CLASS[z.key] ?? "bg-slate-300")}
                        style={{ left: `${lo}%`, width: `${Math.max(0, hi - lo)}%` }} title={`${z.label}: ${m(z.low)} – ${z.high != null ? m(z.high) : "üstü"}`} />;
                    })}
                    <div className="absolute top-0 h-7 w-0.5 bg-slate-900" style={{ left: `${pos(r.optimal_price)}%` }} title={`Önerilen ${m(r.optimal_price)}`} />
                    {trial != null && (
                      <div className={cn("absolute top-2 size-3 -translate-x-1/2 rounded-full border-2 border-white",
                        r.price_fit === "içinde" ? "bg-emerald-700" : r.price_fit === "üstünde" ? "bg-rose-600" : "bg-sky-600")}
                        style={{ left: `${pos(trial)}%` }} title={`Denenen ${m(trial)}`} />
                    )}
                  </div>
                  <span className="text-right text-xs whitespace-nowrap">
                    <b className="text-sm">{m(r.optimal_price)}</b> önerilen<br />
                    <span className="text-muted-foreground">kabul {m(r.range_low)} – {m(r.range_high)}{r.net_margin_pct != null ? ` · net marj %${r.net_margin_pct}` : ""}</span>
                  </span>
                  {first || one ? <Input className="h-8 text-right" type="number" placeholder="fiyat dene" title="Denenen fiyat bütün bölgelere uygulanır"
                    value={scenario.planned_prices?.[i.sku] ?? ""}
                    onChange={(e) => {
                      const v = e.target.value;
                      setScenario((s) => {
                        const pp = { ...(s.planned_prices ?? {}) };
                        if (v === "") delete pp[i.sku]; else pp[i.sku] = Number(v);
                        return { ...s, planned_prices: pp };
                      });
                    }} /> : <span />}
                </div>
              );
            }))}
          </div>
        );
      })}
    </div>
  );
}

function Budget({ res, m, scenario, setScenario, one }: {
  res: CollectionResult; m: (v: number | null | undefined) => string; scenario: WhatIf; setScenario: (f: (s: WhatIf) => WhatIf) => void; one: string | null;
}) {
  const s = res.summary;
  const regs = one ? [one] : res.regions;
  const q = (i: ItemResult) => (one ? (i.qty_by_region[one] ?? 0) : (i.recommended_qty.value ?? 0));
  const items = res.items.filter((i) => i.regions.length && (!one || i.regions.some((r) => r.region === one))).sort((a, b) => q(b) - q(a));
  const regQty = items.reduce((a, i) => a + q(i), 0);
  const regCost = items.reduce((a, i) => a + q(i) * (i.unit_cost_usd ?? 0), 0);
  const localBudget = s.budget_total_usd != null ? Math.round(res.currency === "TRY" ? s.budget_total_usd * res.fx_rate : s.budget_total_usd) : "";
  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-end gap-3">
        <div className="grid gap-1">
          <span className="text-xs text-muted-foreground">Toplam bütçe ({res.currency})</span>
          <Input className="h-9 w-44" type="number" value={scenario.total_budget ?? localBudget}
            onChange={(e) => setScenario((x) => ({ ...x, total_budget: e.target.value === "" ? null : Number(e.target.value) }))} />
        </div>
        <div className="grid gap-1">
          <span className="text-xs text-muted-foreground">Dağıtım hedefi</span>
          <select className="h-9 rounded-md border bg-background px-2 text-sm" value={scenario.allocation_objective ?? "balanced"}
            onChange={(e) => setScenario((x) => ({ ...x, allocation_objective: e.target.value as WhatIf["allocation_objective"] }))}>
            <option value="balanced">Dengeli (satış hızı)</option><option value="profit">Kâr ağırlıklı</option><option value="blended">Karışık</option>
          </select>
        </div>
        <div className="text-sm text-muted-foreground">
          {one ? <>{one}: {m(regCost)} · {regQty.toLocaleString("tr-TR")} adet <span className="text-xs">(toplam {m(s.budget_used_usd)} · {s.total_qty.toLocaleString("tr-TR")} adet)</span></>
            : <>Kullanılan {m(s.budget_used_usd)} · {s.total_qty.toLocaleString("tr-TR")} adet</>} <BasisChip basis="kural varsayımı" how={s.expected_units.how} />
        </div>
      </div>
      <p className="text-xs text-muted-foreground">
        Bütçe, ürün × bölge hücrelerine bir sonraki birimin satılma olasılığına göre dağıtılır; son birimin satılma olasılığı %50&apos;nin altına inince o hücre durur.
        Bütçe talebi aşıyorsa kalan bütçe harcanmaz. &quot;Üretme&quot; kararlı ürünler ve talebi düşük bölgeler dağıtıma girmez; &quot;azalt&quot; kararında talebin %60&apos;ı esas alınır. Talep panelden, kitle ve dönüşüm varsayımlardan gelir; ERP ile kalibre edilene kadar adetler varsayımdır.
      </p>
      <Table>
        <TableHeader><TableRow>
          <TableHead>Ürün</TableHead><TableHead>Karar</TableHead>
          {regs.map((r) => <TableHead key={r} className="text-right">{r}</TableHead>)}
          <TableHead className="text-right">{one ? "Tüm bölgeler" : "Toplam"}</TableHead><TableHead className="text-right">Planlanan</TableHead><TableHead className="text-right">Tutar{one ? ` (${one})` : ""}</TableHead>
        </TableRow></TableHeader>
        <TableBody>
          {items.map((i) => {
            const tot = i.recommended_qty.value ?? 0;
            const amt = q(i);
            return (
              <TableRow key={i.sku}>
                <TableCell>{i.name}<div className="text-[11px] text-muted-foreground">{i.flags.filter((f) => f.startsWith("MOQ") || f === "maliyet yok").join(", ")}</div></TableCell>
                <TableCell><DecisionChip d={regionDecision(i, one)} user={i.decision_source === "kullanıcı"} /></TableCell>
                {regs.map((r) => <TableCell key={r} className="text-right">{(i.qty_by_region[r] ?? 0).toLocaleString("tr-TR")}</TableCell>)}
                <TableCell className="text-right font-medium">{i.recommended_qty.value != null ? tot.toLocaleString("tr-TR") : "–"}</TableCell>
                <TableCell className="text-right text-muted-foreground">{i.planned_qty?.toLocaleString("tr-TR") ?? "–"}</TableCell>
                <TableCell className="text-right">{i.unit_cost_usd != null ? m(amt * i.unit_cost_usd) : "–"}</TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}
