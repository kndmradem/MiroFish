"use client";

import dynamic from "next/dynamic";
import type { EChartsOption } from "echarts";

import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import {
  imageUrl, type Basis, type ColorDecision, type ColorFamilySummary, type ColorLine, type CollectionResult, type ItemResult, type WhatIf,
} from "@/lib/collection-api";
import { cn } from "@/lib/utils";

const ReactECharts = dynamic(() => import("echarts-for-react"), { ssr: false });

// Renk ailesi -> ekrandaki nokta rengi (yalnızca görsel ipucu)
const SWATCH: Record<string, string> = {
  siyah: "#141414", lacivert: "#1f2a4d", beyaz: "#f4efe3", bej: "#d6bf9f", gri: "#9ca3af", kahve: "#6b4423",
  bordo: "#6d1a2b", kirmizi: "#c81e1e", pembe: "#f2a2bd", mavi: "#3b82f6", yesil: "#4d7c0f", mor: "#a78bfa",
  sari: "#f59e0b", diger: "#cbd5e1",
};

export function Swatch({ family, className }: { family: string; className?: string }) {
  const bg = family === "desenli" ? "conic-gradient(#f59e0b, #ec4899, #3b82f6, #10b981, #f59e0b)" : SWATCH[family] ?? SWATCH.diger;
  return <span className={cn("inline-block size-3 shrink-0 rounded-full border border-black/15", className)} style={{ background: bg }} />;
}

const qtyFmt = (v: number | null | undefined) => (v == null ? "–" : v.toLocaleString("tr-TR"));

/** Ürün satırının altında kısa renk özeti: renk, adet; üretilmeyen renk üstü çizili. */
export function ColorStrip({ it, region }: { it: ItemResult; region?: string | null }) {
  if (!it.colors?.length) return null;
  return (
    <div className="mt-1 flex flex-wrap gap-x-2 gap-y-0.5 text-[11px] text-muted-foreground">
      {it.colors.map((c) => (
        <span key={c.color} className={cn("inline-flex items-center gap-1", c.decision === "üretme" && "line-through opacity-60")}
          title={`${c.family_label}, pay %${c.share.value}`}>
          <Swatch family={c.family} className="size-2.5" />{c.color}{c.qty != null && c.decision !== "üretme" ? ` ${qtyFmt(region ? (c.qty_by_region[region] ?? 0) : c.qty)}` : ""}
        </span>
      ))}
    </div>
  );
}

/** Ürün ayrıntısındaki renk tablosu. */
export function ColorTable({ res, it, overrides, onColor, BasisChip, region }: {
  res: CollectionResult; it: ItemResult; overrides: Record<string, ColorDecision>; region?: string | null;
  onColor: (key: string, d: ColorDecision | "") => void; BasisChip: (p: { basis: Basis; how?: string }) => React.ReactNode;
}) {
  if (!it.colors?.length) return null;
  const basis = it.colors[0].share.basis;
  const regs = region ? [region] : res.regions;
  return (
    <div className="grid gap-1">
      <div className="flex flex-wrap items-center gap-2 text-sm font-medium">
        Renkler <span className="text-xs font-normal text-muted-foreground">pay</span> <BasisChip basis={basis} how={it.colors[0].share.how} />
        <span className="text-xs font-normal text-muted-foreground">minimum adet</span> <BasisChip basis={res.color_plan?.min_qty_basis ?? "kural varsayımı"} />
        {it.color_mix && <span className="text-xs font-normal text-muted-foreground" title={it.color_mix.how}>· renk karışımı çarpanı ×{it.color_mix.value}</span>}
      </div>
      <Table>
        <TableHeader><TableRow>
          <TableHead>Renk</TableHead><TableHead className="text-right">Pay</TableHead><TableHead>Karar</TableHead>
          <TableHead className="text-right">Adet{region ? " (tüm bölgeler)" : ""}</TableHead>
          {regs.map((r) => <TableHead key={r} className="text-right">{r}</TableHead>)}
          <TableHead>Gerekçe</TableHead>
        </TableRow></TableHeader>
        <TableBody>
          {it.colors.map((c) => {
            const key = `${it.sku}::${c.color}`;
            return (
              <TableRow key={c.color} className={cn(c.decision === "üretme" && "bg-rose-50/40")}>
                <TableCell>
                  <div className="flex items-center gap-2">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    {c.image ? <img src={imageUrl(res.collection_id, c.image)} alt="" className="h-10 w-7 rounded object-cover" /> : <Swatch family={c.family} className="size-4" />}
                    <div><div className="font-medium">{c.color}</div><div className="text-[11px] text-muted-foreground">{c.code ? `${c.code} · ` : ""}{c.family_label}</div></div>
                  </div>
                </TableCell>
                <TableCell className="text-right" title={c.share.how}>%{c.share.value}
                  {c.share.low != null && <div className="text-[11px] text-muted-foreground">%{c.share.low}-{c.share.high}</div>}</TableCell>
                <TableCell>
                  <div className="flex items-center gap-1.5">
                    {c.decision ? <span className={cn("rounded-full border px-2 py-0.5 text-xs", c.decision === "üret" ? "border-emerald-300 bg-emerald-50 text-emerald-800" : "border-rose-300 bg-rose-50 text-rose-800")}>
                      {c.decision === "üret" ? "Üret" : "Üretme"}{c.decision_source === "kullanıcı" ? " (elle)" : ""}</span> : "–"}
                    {it.decision && it.decision !== "üretme" && (
                      <select className="h-6 rounded border bg-background px-1 text-[11px]" value={overrides[key] ?? ""} title="Renk kararını elle değiştir"
                        onChange={(e) => onColor(key, e.target.value as ColorDecision | "")}>
                        <option value="">sistem</option><option value="üret">üret</option><option value="üretme">üretme</option>
                      </select>
                    )}
                  </div>
                </TableCell>
                <TableCell className="text-right font-medium">{qtyFmt(c.qty)}</TableCell>
                {regs.map((r) => <TableCell key={r} className="text-right">{qtyFmt(c.qty_by_region[r])}</TableCell>)}
                <TableCell className="text-xs whitespace-normal">
                  {c.reasons.map((x, k) => <div key={k} className="flex items-start gap-1.5"><span className="flex-1">{x.text}</span><BasisChip basis={x.basis} /></div>)}
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}

/** "Renkler" sekmesi: koleksiyonun renk dağılımı, renk x bölge, model x renk adetleri ve renk ayarları. */
export function ColorsTab({ res, scenario, setScenario, BasisChip, one }: {
  res: CollectionResult; scenario: WhatIf; setScenario: (f: (s: WhatIf) => WhatIf) => void; one?: string | null;
  BasisChip: (p: { basis: Basis; how?: string }) => React.ReactNode;
}) {
  const cp = res.color_plan;
  if (!cp) return <p className="text-sm text-muted-foreground">Ürünlerde renk bilgisi yok. Excel&apos;de &quot;renkler&quot; sütunu ya da her renk için ayrı satır (aynı SKU) olursa renk bazlı plan çıkar.</p>;
  const regs = one ? [one] : res.regions;
  const items = res.items.filter((i) => i.colors?.length && (!one || i.regions.some((r) => r.region === one)));
  const fq = (f: ColorFamilySummary) => (one ? (f.by_region[one] ?? 0) : f.qty);
  const total = cp.families.reduce((a, f) => a + fq(f), 0);
  const mq = (it: ItemResult) => (one ? (it.qty_by_region[one] ?? 0) : it.recommended_qty.value);
  const cq = (c: ColorLine) => (one ? (c.qty_by_region[one] ?? 0) : c.qty);
  const actions = res.summary.actions.filter((a) => a.kind === "renk");
  const opt: EChartsOption = {
    grid: { left: 110, right: 30, top: 30, bottom: 20 },
    legend: { top: 0, textStyle: { fontSize: 11 } },
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
    xAxis: { type: "value", axisLabel: { fontSize: 10 } },
    yAxis: { type: "category", inverse: true, data: cp.families.map((f) => f.label), axisLabel: { fontSize: 11 } },
    series: regs.map((r) => ({ name: r, type: "bar", stack: "q", data: cp.families.map((f) => f.by_region[r] ?? 0), barMaxWidth: 18 })),
  };
  const allColors = items.flatMap((i) => i.colors);
  return (
    <div className="grid gap-5">
      <div className="flex flex-wrap items-end gap-4 rounded-md border p-3 text-sm">
        <div className="grid gap-1">
          <span className="flex items-center gap-1.5 text-xs text-muted-foreground">Renk payı kaynağı <BasisChip basis={cp.source} how={cp.source_note} /></span>
          <span className="max-w-md text-xs text-muted-foreground">{cp.source === "ERP" ? "Geçmiş renk satışları (ERP)" : "Renk ailesi ağırlıkları (doğrulanmamış taslak). Canlıda ERP satış payı kullanılacak; ekran aynı kalır."}</span>
        </div>
        <label className="grid gap-1">
          <span className="flex items-center gap-1.5 text-xs text-muted-foreground">Renk başına minimum adet <BasisChip basis={cp.min_qty_basis} /></span>
          <Input type="number" min={1} className="h-8 w-28" placeholder={String(cp.min_qty)} value={scenario.color_min_qty ?? ""}
            onChange={(e) => setScenario((s) => ({ ...s, color_min_qty: e.target.value ? Math.max(1, Number(e.target.value)) : null }))} />
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={scenario.color_mix ?? cp.mix_effect}
            onChange={(e) => setScenario((s) => ({ ...s, color_mix: e.target.checked }))} />
          Renk karışımı model adedini etkilesin <BasisChip basis={cp.source} how="Güçlü renklerden oluşan model bütçeden biraz daha çok, zayıf renklerden oluşan model biraz daha az pay alır (en fazla ±%15)." />
        </label>
        <div className="ml-auto text-right text-xs text-muted-foreground">{cp.n_colors} renk · {cp.n_dropped} renk minimum altında kaldı</div>
      </div>

      {actions.length > 0 && (
        <ul className="grid gap-1 text-sm">
          {actions.map((a, k) => <li key={k} className="flex items-start gap-2"><span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-amber-500" /><span className="flex-1">{a.text}</span><BasisChip basis={a.basis} /></li>)}
        </ul>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <div>
          <div className="mb-1 text-sm font-medium">Renk ailesine göre üretim adedi ({one ?? "bölgelere göre"})</div>
          {total > 0 ? <ReactECharts option={opt} style={{ height: Math.max(160, 34 * cp.families.length + 50) }} notMerge /> : <p className="text-sm text-muted-foreground">Bütçe girilmediği için adet yok; yalnızca renk payları gösteriliyor.</p>}
        </div>
        <Table>
          <TableHeader><TableRow>
            <TableHead>Renk ailesi</TableHead><TableHead className="text-right">Model</TableHead><TableHead className="text-right">Adet</TableHead>
            <TableHead className="text-right">{one ? `Pay (${one})` : "Pay"}</TableHead>
            {!one && regs.map((r) => <TableHead key={r} className="text-right">{r}</TableHead>)}
          </TableRow></TableHeader>
          <TableBody>
            {cp.families.map((f) => (
              <TableRow key={f.family}>
                <TableCell><span className="inline-flex items-center gap-1.5"><Swatch family={f.family} />{f.label}</span></TableCell>
                <TableCell className="text-right">{f.n_models}</TableCell>
                <TableCell className="text-right font-medium">{qtyFmt(fq(f))}</TableCell>
                <TableCell className="text-right">%{one ? (total ? Math.round((1000 * fq(f)) / total) / 10 : 0) : f.share_pct}</TableCell>
                {!one && regs.map((r) => <TableCell key={r} className="text-right">{qtyFmt(f.by_region[r])}</TableCell>)}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      <div className="overflow-x-auto">
        <div className="mb-1 text-sm font-medium">Model ve renk bazında üretim hedefi</div>
        <Table>
          <TableHeader><TableRow>
            <TableHead>Model</TableHead><TableHead className="text-right">Model adedi{one ? ` (${one})` : ""}</TableHead><TableHead>Renkler ({one ? `${one} adedi` : "adet"} · pay)</TableHead>
          </TableRow></TableHeader>
          <TableBody>
            {items.map((it) => (
              <TableRow key={it.sku} className={cn(it.decision === "üretme" && "opacity-50")}>
                <TableCell className="min-w-44">
                  <div className="font-medium">{it.name}</div>
                  <div className="font-mono text-[11px] text-muted-foreground">{it.sku}{it.color_mix ? ` · renk çarpanı ×${it.color_mix.value}` : ""}</div>
                </TableCell>
                <TableCell className="text-right">{qtyFmt(mq(it))}</TableCell>
                <TableCell>
                  <div className="flex flex-wrap gap-1.5">
                    {it.colors.map((c: ColorLine) => (
                      <span key={c.color} title={c.reasons.map((x) => x.text).join(" · ") || c.share.how}
                        className={cn("inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs",
                          c.decision === "üretme" ? "border-rose-200 bg-rose-50 text-rose-700 line-through" : "bg-background")}>
                        <Swatch family={c.family} />{c.color}<b className="font-semibold">{c.decision === "üretme" ? 0 : qtyFmt(cq(c))}</b>
                        <span className="text-muted-foreground">%{c.share.value}</span>
                      </span>
                    ))}
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        {allColors.length > 0 && <p className="mt-2 text-xs text-muted-foreground">Bir rengin kararını değiştirmek için Ürünler sekmesinde modelin satırını açın.</p>}
      </div>
    </div>
  );
}
