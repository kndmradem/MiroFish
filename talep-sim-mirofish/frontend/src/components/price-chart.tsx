"use client";

import dynamic from "next/dynamic";
import type { EChartsOption } from "echarts";

import type { RegionPredictionResult } from "@/lib/api";

const ReactECharts = dynamic(() => import("echarts-for-react"), { ssr: false });

export const ZONE_COLOR: Record<string, string> = {
  too_cheap: "rgba(148,163,184,0.20)",
  cheap: "rgba(59,130,246,0.14)",
  ideal: "rgba(34,197,94,0.22)",
  expensive: "rgba(245,158,11,0.16)",
  too_expensive: "rgba(239,68,68,0.14)",
};

export function VanWestendorpChart({ result }: { result: RegionPredictionResult }) {
  const vw = result.van_westendorp;
  const series = (name: string, key: "too_cheap" | "cheap" | "expensive" | "too_expensive", color: string, dashed = false) => ({
    name,
    type: "line" as const,
    smooth: true,
    showSymbol: false,
    lineStyle: { color, width: 2, type: dashed ? ("dashed" as const) : ("solid" as const) },
    itemStyle: { color },
    data: vw.curve.map((p) => [Number(p.price), Math.round(p[key] * 100)]),
  });

  const xMin = Number(vw.curve[0].price);
  const xMax = Number(vw.curve[vw.curve.length - 1].price);
  const zoneAreas = (vw.zones ?? []).map((z) => {
    const lo = Math.max(xMin, Number(z.low));
    const hi = z.high == null ? xMax : Math.min(xMax, Number(z.high));
    const range = z.high == null ? `$${Math.round(Number(z.low))}+` : `$${Math.round(Number(z.low))}-${Math.round(Number(z.high))}`;
    return [
      { name: `${z.label}\n${range}`, xAxis: lo, itemStyle: { color: ZONE_COLOR[z.key] }, label: { show: hi - lo >= (xMax - xMin) * 0.12, position: "insideTop" as const, fontSize: 10, color: "#475569" } },
      { xAxis: hi },
    ];
  });

  const option: EChartsOption = {
    grid: { left: 48, right: 24, top: 64, bottom: 48 },
    tooltip: {
      trigger: "axis",
      valueFormatter: (v) => `%${v}`,
    },
    legend: { top: 0 },
    xAxis: {
      type: "value",
      name: "Fiyat ($)",
      nameLocation: "middle",
      nameGap: 28,
      min: xMin,
      max: xMax,
    },
    yAxis: { type: "value", name: "Ajan %", max: 100 },
    series: [
      {
        ...series("Çok ucuz", "too_cheap", "#94a3b8", true),
        markArea: { silent: true, data: zoneAreas as never },
        markLine: {
          symbol: "none",
          label: { formatter: "{b}", position: "insideEndTop" },
          data: [
            { name: `OPP ${vw.optimal_price_point}$`, xAxis: Number(vw.optimal_price_point), lineStyle: { color: "#64748b" } },
            { name: `Önerilen ${result.optimal_sale_price}$`, xAxis: Number(result.optimal_sale_price), lineStyle: { color: "#16a34a", width: 2 } },
          ],
        },
      },
      series("Ucuz", "cheap", "#3b82f6"),
      series("Pahalı", "expensive", "#f59e0b"),
      series("Çok pahalı", "too_expensive", "#ef4444", true),
    ],
  };

  return (
    <div>
      {vw.quality && vw.quality !== "high" && (
        <p className="mb-2 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900">
          {vw.quality === "low" ? "Düşük örneklem: " : "Orta örneklem: "}
          {vw.quality_note} Bölge sınırlarını kesin değer değil, yaklaşık aralık olarak okuyun.
        </p>
      )}
      <ReactECharts option={option} style={{ height: 380 }} notMerge />
    </div>
  );
}
