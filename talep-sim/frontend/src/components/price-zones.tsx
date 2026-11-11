import { ZONE_COLOR } from "@/components/price-chart";
import type { RegionPredictionResult } from "@/lib/api";
import { try_ } from "@/lib/api";

const fmt = (v: string | number) => `$${Math.round(Number(v)).toLocaleString("tr-TR")}`;

/** Fiyat bölgeleri (tutar aralıklarıyla) ve ajanların her fiyat basamağına verdiği kararlar. */
export function PriceZones({ row }: { row: RegionPredictionResult }) {
  const zones = row.van_westendorp.zones ?? [];
  const steps = row.price_steps ?? [];
  const rate = row.local_currency === "TRY" ? row.fx_rate : null;
  const tl = (v: string | number) => (rate ? ` (${try_(Number(v) * rate)})` : "");
  if (zones.length === 0) return null;
  return (
    <div className="grid gap-4 text-sm">
      <div className="grid gap-1">
        {zones.map((z) => (
          <div key={z.key} className="flex flex-wrap items-baseline justify-between gap-2 rounded px-3 py-2" style={{ background: ZONE_COLOR[z.key] }}>
            <span className="font-medium">{z.label}</span>
            <span className="font-mono">
              {z.high == null ? `${fmt(z.low)} üstü` : `${fmt(z.low)} - ${fmt(z.high)}`}
              <span className="text-muted-foreground">{tl(z.low)}</span>
            </span>
            <span className="w-full text-xs text-muted-foreground">{z.description}</span>
          </div>
        ))}
      </div>
      <p className="text-xs text-muted-foreground">
        Sınırlar Van Westendorp kesişimlerinden gelir: kabul edilebilir aralık {fmt(row.van_westendorp.acceptable_range_low)}-
        {fmt(row.van_westendorp.acceptable_range_high)}, optimal nokta {fmt(row.van_westendorp.optimal_price_point)}, kayıtsızlık
        noktası {fmt(row.van_westendorp.indifference_price_point)}.
      </p>
      {steps.length > 0 && (
        <div className="overflow-x-auto">
          <p className="mb-1 font-medium">
            Ajanların fiyat basamaklarına kararı{" "}
            <span className="text-xs font-normal text-muted-foreground">
              ({steps[0].basis === "ladder" ? "ajan cevabı: her basamak için verilen karar" : "ajanların eşik fiyatlarından hesaplandı"})
            </span>
          </p>
          <table className="w-full text-xs">
            <thead>
              <tr className="text-left text-muted-foreground">
                <th className="py-1 pr-2">Fiyat</th><th className="pr-2">Şüpheli</th><th className="pr-2">Uygun</th>
                <th className="pr-2">Pahalı</th><th className="pr-2">Çok pahalı</th><th>Dağılım</th>
              </tr>
            </thead>
            <tbody>
              {steps.map((s) => (
                <tr key={s.price} className="border-t">
                  <td className="py-1 pr-2 font-mono">{fmt(s.price)}</td>
                  <td className="pr-2">{s.suspicious}</td><td className="pr-2">{s.fair}</td>
                  <td className="pr-2">{s.expensive}</td><td className="pr-2">{s.too_expensive}</td>
                  <td className="w-40">
                    <div className="flex h-2 overflow-hidden rounded">
                      {[["#94a3b8", s.suspicious], ["#22c55e", s.fair], ["#f59e0b", s.expensive], ["#ef4444", s.too_expensive]].map(([c, n], i) => (
                        <div key={i} style={{ background: c as string, width: `${s.n ? ((n as number) / s.n) * 100 : 0}%` }} />
                      ))}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
