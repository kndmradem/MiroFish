import { Badge } from "@/components/ui/badge";
import type { RegionPredictionResult } from "@/lib/api";
import { usd } from "@/lib/api";

/** İade oranı tahmini: faktörler, aralık ve net marj. Tüm değerler kural tabanlı varsayımdır. */
export function ReturnsCard({ row }: { row: RegionPredictionResult }) {
  const r = row.returns;
  if (!r) return null;
  const maxAbs = Math.max(1, ...r.drivers.map((d) => Math.abs(d.points)));
  return (
    <div className="grid gap-4 text-sm">
      <div className="grid gap-3 sm:grid-cols-3">
        <div className="rounded-md border p-3">
          <p className="text-xs text-muted-foreground">Tahmini iade oranı</p>
          <p className="text-2xl font-semibold">%{r.rate_pct}</p>
          <p className="text-xs text-muted-foreground">Aralık %{r.low_pct} - %{r.high_pct}</p>
        </div>
        <div className="rounded-md border p-3">
          <p className="text-xs text-muted-foreground">Marj: brüt → iade sonrası</p>
          <p className="text-2xl font-semibold">%{r.gross_margin_pct} → %{r.net_margin_pct}</p>
          <p className="text-xs text-muted-foreground">Satış başına iade maliyeti {usd(r.return_cost_per_sale)}</p>
        </div>
        <div className="rounded-md border p-3">
          <p className="text-xs text-muted-foreground">Üretimin tamamı satılırsa net adet</p>
          <p className="text-2xl font-semibold">{r.net_qty_if_sold_out.toLocaleString("tr-TR")}</p>
          <p className="text-xs text-muted-foreground">iade düşüldükten sonra (önerilen {row.recommended_production_qty.toLocaleString("tr-TR")})</p>
        </div>
      </div>
      <ul className="grid gap-2">
        {r.drivers.map((d) => (
          <li key={d.label} className="grid gap-1">
            <div className="flex items-center justify-between gap-2">
              <span className="font-medium">{d.label}</span>
              <span className="flex items-center gap-2">
                <Badge variant="outline" className="text-[10px]">{d.basis}</Badge>
                {d.points !== 0 && (
                  <span className={d.points > 0 ? "font-mono text-red-600" : "font-mono text-green-600"}>
                    {d.points > 0 ? "+" : ""}{d.points} puan
                  </span>
                )}
              </span>
            </div>
            {d.points !== 0 && (
              <div className="h-1.5 rounded bg-muted">
                <div
                  className={d.points > 0 ? "h-full rounded bg-red-500" : "h-full rounded bg-green-500"}
                  style={{ width: `${(Math.abs(d.points) / maxAbs) * 100}%` }}
                />
              </div>
            )}
            <p className="text-xs text-muted-foreground">{d.detail}</p>
          </li>
        ))}
      </ul>
      <p className="text-xs text-muted-foreground">
        {r.basis}. Katsayılar sektör genel eğilimlerinden alınmış varsayımlardır; gerçek iade verin varsa soldaki
        &quot;Varsayımlar&quot; bölümüne gir.
      </p>
    </div>
  );
}
