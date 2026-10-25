"use client";

import { Button } from "@/components/ui/button";
import type { PredictionResponse } from "@/lib/api";
import { usd } from "@/lib/api";

const n = (v: number) => v.toLocaleString("tr-TR");

/** Müşteriye sunulabilir tek sayfalık özet; "Yazdır / PDF" ile kaydedilir. */
export function SummaryCard({ result, productName }: { result: PredictionResponse; productName: string }) {
  return (
    <section className="print-summary grid gap-3 rounded-lg border p-4 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-lg font-semibold">Yönetici özeti: {productName}</h2>
          <p className="text-xs text-muted-foreground">
            {result.brand_profile ? `Marka: ${result.brand_profile.name}. ` : ""}Motor: {result.engine === "mirofish" ? "MiroFish ajan simülasyonu" : "mock (örnek)"} ·
            toplam üretim {n(result.total_produced_qty)} adet
          </p>
        </div>
        <Button type="button" variant="outline" className="no-print" onClick={() => window.print()}>Yazdır / PDF</Button>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-left text-muted-foreground">
              <th className="py-1">Bölge</th><th>Talep</th><th>Önerilen fiyat</th><th>Kabul aralığı</th><th>Üretim</th>
              <th>120g satış (aralık)</th><th>İade</th><th>Net marj</th><th>Önerilen kampanya</th><th>Güven</th>
            </tr>
          </thead>
          <tbody>
            {result.regional_breakdown.map((r) => {
              const f = r.forecast?.milestones[3];
              const camp = r.campaigns?.find((c) => c.recommended);
              return (
                <tr key={r.region} className="border-t align-top">
                  <td className="py-1 font-mono">{r.region}</td>
                  <td>{r.demand_score_100}/100</td>
                  <td>{usd(r.optimal_sale_price)}</td>
                  <td>{usd(r.van_westendorp.acceptable_range_low)}-{usd(r.van_westendorp.acceptable_range_high)}</td>
                  <td>{n(r.recommended_production_qty)}</td>
                  <td>{f ? `${n(f.units)} (${n(f.units_low)}-${n(f.units_high)})` : "-"}</td>
                  <td>{r.returns ? `%${r.returns.rate_pct} (${r.returns.low_pct}-${r.returns.high_pct})` : "-"}</td>
                  <td>{r.returns ? `%${r.returns.net_margin_pct}` : `%${r.estimated_margin_percentage}`}</td>
                  <td>{camp ? camp.goal_label : "-"}</td>
                  <td>{r.confidence?.level ?? "-"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {result.failed_regions.length > 0 && (
        <p className="text-xs text-amber-700">Hesaplanamayan bölgeler: {result.failed_regions.map((f) => f.region).join(", ")}.</p>
      )}
      <p className="rounded-md border border-amber-500/40 bg-amber-500/10 p-2 text-xs">
        <b>Uyarı:</b> {result.disclaimer ?? "Bu çıktılar model tabanlı tahmindir, ölçülmüş satış verisi değildir."} Talep skoru ve fiyat
        kabulü ajan cevaplarından; kitle büyüklüğü, dönüşüm, iade katsayıları, kampanya etkileri ve mevsim uyumu kural varsayımlarından gelir.
      </p>
    </section>
  );
}
