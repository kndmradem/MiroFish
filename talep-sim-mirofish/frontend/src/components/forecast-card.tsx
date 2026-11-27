"use client";

import dynamic from "next/dynamic";
import type { EChartsOption } from "echarts";

import type { RegionPredictionResult } from "@/lib/api";
import { usd } from "@/lib/api";

const ReactECharts = dynamic(() => import("echarts-for-react"), { ssr: false });

const n = (v: number) => v.toLocaleString("tr-TR");

/** 30/60/90/120 gün satış potansiyeli: düşük-yüksek bandı, stok sınırı ve kilometre taşı tablosu. */
export function ForecastCard({ row }: { row: RegionPredictionResult }) {
  const f = row.forecast;
  if (!f) return null;
  const qty = row.recommended_production_qty;
  const option: EChartsOption = {
    grid: { left: 56, right: 24, top: 48, bottom: 44 },
    tooltip: { trigger: "axis" },
    legend: { top: 0 },
    xAxis: { type: "value", name: "Gün", nameLocation: "middle", nameGap: 26, min: 0, max: 120, interval: 30 },
    yAxis: { type: "value", name: "Adet (kümülatif)" },
    series: [
      { name: "Düşük", type: "line", showSymbol: false, smooth: true, lineStyle: { type: "dashed", color: "#94a3b8" }, itemStyle: { color: "#94a3b8" },
        data: f.curve.map((p) => [p.day, p.sold_low]) },
      { name: "Orta (satış)", type: "line", showSymbol: false, smooth: true, lineStyle: { width: 3, color: "#16a34a" }, itemStyle: { color: "#16a34a" },
        data: f.curve.map((p) => [p.day, p.sold]),
        markLine: { symbol: "none", silent: true, label: { formatter: `Üretim ${n(qty)}`, position: "insideEndTop" },
          lineStyle: { color: "#ef4444", type: "dashed" }, data: [{ yAxis: qty }] } },
      { name: "Yüksek", type: "line", showSymbol: false, smooth: true, lineStyle: { type: "dashed", color: "#3b82f6" }, itemStyle: { color: "#3b82f6" },
        data: f.curve.map((p) => [p.day, p.sold_high]) },
      { name: "Talep (stok sınırsız)", type: "line", showSymbol: false, smooth: true, lineStyle: { type: "dotted", color: "#f59e0b" }, itemStyle: { color: "#f59e0b" },
        data: f.curve.map((p) => [p.day, p.demand]) },
    ],
  };
  return (
    <div className="grid gap-4 text-sm">
      <div className="grid gap-3 sm:grid-cols-3">
        <div className="rounded-md border p-3">
          <p className="text-xs text-muted-foreground">120 günde satış (orta)</p>
          <p className="text-2xl font-semibold">{n(f.milestones[3].units)}</p>
          <p className="text-xs text-muted-foreground">Aralık {n(f.milestones[3].units_low)} - {n(f.milestones[3].units_high)}</p>
        </div>
        <div className="rounded-md border p-3">
          <p className="text-xs text-muted-foreground">Stok durumu</p>
          <p className="text-2xl font-semibold">
            {f.stockout_day ? `${f.stockout_day}. günde biter` : `${n(f.leftover_units)} adet kalır`}
          </p>
          <p className="text-xs text-muted-foreground">
            {f.stockout_day ? `Kaçan talep ≈ ${n(f.lost_units)} adet` : `Satış oranı %${f.sell_through_pct}`}
          </p>
        </div>
        <div className="rounded-md border p-3">
          <p className="text-xs text-muted-foreground">120. gün ciro (brüt → iade sonrası)</p>
          <p className="text-lg font-semibold">{usd(f.milestones[3].revenue)} → {usd(f.milestones[3].net_revenue)}</p>
          <p className="text-xs text-muted-foreground">Fiyat kabulü %{f.purchase_prob_pct}, hedef kitle {n(f.audience)}</p>
        </div>
      </div>
      <ReactECharts option={option} style={{ height: 300 }} notMerge />
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-left text-muted-foreground">
              <th className="py-1">Gün</th><th>Dönem adedi</th><th>Kümülatif (aralık)</th><th>Brüt ciro</th><th>İade sonrası ciro</th><th>Kalan stok</th>
            </tr>
          </thead>
          <tbody>
            {f.milestones.map((m) => (
              <tr key={m.day} className="border-t">
                <td className="py-1 font-mono">{m.day}</td>
                <td>{n(m.period_units)}</td>
                <td>{n(m.units)} <span className="text-muted-foreground">({n(m.units_low)}-{n(m.units_high)})</span></td>
                <td>{usd(m.revenue)}</td><td>{usd(m.net_revenue)}</td><td>{n(m.stock_left)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ul className="list-disc space-y-1 pl-5 text-xs text-muted-foreground">
        {f.assumptions.map((a) => <li key={a}>{a}</li>)}
        <li><b>Dayanak:</b> {f.basis}. Bu bir ölçüm değil model tahminidir; düşük-yüksek aralığı varsayımdır.</li>
      </ul>
    </div>
  );
}
