import { Badge } from "@/components/ui/badge";
import type { RegionPredictionResult } from "@/lib/api";
import { usd } from "@/lib/api";

const n = (v: number) => v.toLocaleString("tr-TR");
const signed = (v: number) => `${v > 0 ? "+" : ""}${v.toLocaleString("tr-TR", { maximumFractionDigits: 1 })}`;

/** Lansman -> ilk kampanya sonrası -> stok eritme fiyat planı ve tek fiyatla karşılaştırma. */
export function PricePlanCard({ row }: { row: RegionPredictionResult }) {
  const p = row.price_plan;
  if (!p) return null;
  const dProfit = Number(p.total_net_profit) - Number(p.flat_net_profit);
  return (
    <div className="grid gap-4 text-sm">
      <div className="grid gap-3 md:grid-cols-3">
        {p.phases.map((ph) => (
          <div key={ph.name} className="rounded-md border p-3">
            <p className="text-xs text-muted-foreground">{ph.name} · gün {ph.day_from}-{ph.day_to}</p>
            <p className="text-2xl font-semibold">{usd(ph.price)}</p>
            <p className="text-xs">{ph.discount_pct > 0 ? `%${ph.discount_pct} indirim` : "tam fiyat"} · {ph.zone}</p>
            <p className="mt-1 text-xs text-muted-foreground">
              Satın alma olasılığı %{ph.purchase_prob_pct} (ajan) · {n(ph.units)} adet · net marj %{ph.net_margin_pct}
            </p>
            <p className="text-xs text-muted-foreground">{ph.note}</p>
          </div>
        ))}
      </div>
      <table className="w-full text-xs">
        <thead>
          <tr className="text-left text-muted-foreground"><th className="py-1">Plan</th><th>Satılan</th><th>Kalan stok</th><th>Ciro</th><th>İade sonrası kâr</th></tr>
        </thead>
        <tbody>
          <tr className="border-t font-medium">
            <td className="py-1">Üç aşamalı fiyat planı</td><td>{n(p.total_units)}</td><td>{n(p.leftover_units)}</td>
            <td>{usd(p.total_revenue)}</td><td>{usd(p.total_net_profit)}</td>
          </tr>
          <tr className="border-t">
            <td className="py-1">Tek fiyat (lansman fiyatı, 120 gün)</td><td>{n(p.flat_units)}</td><td>{n(p.flat_leftover_units)}</td>
            <td>{usd(p.flat_revenue)}</td><td>{usd(p.flat_net_profit)}</td>
          </tr>
        </tbody>
      </table>
      {p.verdict && <p className="rounded-md bg-muted/60 p-2 text-xs font-medium">{p.verdict}</p>}
      <p className="text-xs">
        Fark: kâr <b className={dProfit >= 0 ? "text-green-600" : "text-red-600"}>{dProfit >= 0 ? "+" : ""}{usd(dProfit)}</b>,
        kalan stok {n(p.flat_leftover_units - p.leftover_units)} adet {p.flat_leftover_units >= p.leftover_units ? "azalır" : "artar"}.
      </p>
      <ul className="list-disc space-y-1 pl-5 text-xs text-muted-foreground">
        {p.assumptions.map((a) => <li key={a}>{a}</li>)}
        <li><b>Dayanak:</b> {p.basis}.</li>
      </ul>
    </div>
  );
}

/** Hedefe göre (stok eritme / satış artırma / rakip savunma) bölgeye uygun kampanya yapıları. */
export function CampaignsCard({ row }: { row: RegionPredictionResult }) {
  const cs = row.campaigns ?? [];
  if (cs.length === 0) return null;
  return (
    <div className="grid gap-4 text-sm">
      {cs.map((c) => (
        <div key={c.goal} className={`grid gap-2 rounded-md border p-3 ${c.recommended ? "border-green-500 bg-green-500/5" : ""}`}>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <Badge variant="secondary">{c.goal_label}</Badge>
              <span className="font-medium">{c.name}</span>
            </div>
            {c.recommended && <Badge className="bg-green-600">Önerilen</Badge>}
          </div>
          {c.recommended && c.why && <p className="text-xs font-medium">{c.why}</p>}
          <p className="text-xs text-muted-foreground">{c.rationale}</p>
          <div className="grid gap-2 sm:grid-cols-4">
            <div><p className="text-xs text-muted-foreground">Fiyat</p><p className="font-semibold">{usd(c.campaign_price)}</p>
              <p className="text-xs text-muted-foreground">%{c.discount_pct} indirim</p></div>
            <div><p className="text-xs text-muted-foreground">Ek adet ({c.window_days} gün)</p>
              <p className="font-semibold">{signed(c.extra_units)}</p>
              <p className="text-xs text-muted-foreground">toplam {n(c.units)} ({n(c.units_low)}-{n(c.units_high)})</p></div>
            <div><p className="text-xs text-muted-foreground">Kâr etkisi</p>
              <p className={`font-semibold ${Number(c.profit_delta) >= 0 ? "text-green-600" : "text-red-600"}`}>{usd(c.profit_delta)}</p>
              <p className="text-xs text-muted-foreground">ek ciro {usd(c.extra_revenue)}</p></div>
            <div><p className="text-xs text-muted-foreground">Marj etkisi</p>
              <p className="font-semibold">{signed(c.margin_impact_pts)} puan</p>
              <p className="text-xs text-muted-foreground">gün {c.start_day}, {c.timing}</p></div>
          </div>
          <ul className="flex flex-wrap gap-1">
            {c.levers.map((l) => (
              <li key={l.label}>
                <Badge variant="outline" className="text-[10px]">{l.label}: +%{l.uplift_low_pct}-{l.uplift_high_pct} talep (varsayım)</Badge>
              </li>
            ))}
          </ul>
          <ul className="list-disc space-y-0.5 pl-5 text-xs text-muted-foreground">
            {c.assumptions.map((a) => <li key={a}>{a}</li>)}
          </ul>
        </div>
      ))}
      <p className="text-xs text-muted-foreground">
        Fiyat etkisi ajan eğrisinden hesaplanır; taksit, kargo, paket gibi kaldıraçların etkisi bölge alışkanlıklarına dair
        kural varsayımıdır ve aralık olarak verilir. Kendi kampanya sonuçlarınla kalibre et.
      </p>
    </div>
  );
}
