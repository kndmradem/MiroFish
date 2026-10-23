"use client";

import dynamic from "next/dynamic";
import type { EChartsOption } from "echarts";

import type { RegionPredictionResult } from "@/lib/api";

const ReactECharts = dynamic(() => import("echarts-for-react"), { ssr: false });

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

  const option: EChartsOption = {
    grid: { left: 48, right: 24, top: 56, bottom: 48 },
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
      min: Number(vw.curve[0].price),
      max: Number(vw.curve[vw.curve.length - 1].price),
    },
    yAxis: { type: "value", name: "Ajan %", max: 100 },
    series: [
      {
        ...series("Çok ucuz", "too_cheap", "#94a3b8", true),
        markArea: {
          silent: true,
          itemStyle: { color: "rgba(34,197,94,0.08)" },
          data: [[{ xAxis: Number(vw.acceptable_range_low) }, { xAxis: Number(vw.acceptable_range_high) }]],
        },
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

  return <ReactECharts option={option} style={{ height: 340 }} notMerge />;
}
