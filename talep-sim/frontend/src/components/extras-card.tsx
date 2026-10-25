import { Badge } from "@/components/ui/badge";
import type { RegionPredictionResult } from "@/lib/api";
import { usd } from "@/lib/api";

const n = (v: number) => v.toLocaleString("tr-TR");
const LEVEL_STYLE = { düşük: "bg-red-600", orta: "bg-amber-500", yüksek: "bg-green-600" } as const;

/** Güvenilirlik, başa baş noktası, fiyat/maliyet duyarlılığı, beden dağılımı ve mevsim uyumu. */
export function ExtrasCard({ row }: { row: RegionPredictionResult }) {
  const rows = row.sensitivity ?? [];
  const price = rows.filter((r) => r.kind === "price");
  const cost = rows.filter((r) => r.kind === "cost");
  const be = row.break_even;
  const conf = row.confidence;
  return (
    <div className="grid gap-5 text-sm">
      {conf && (
        <div className="grid gap-1">
          <p className="font-medium">
            Tahmin güvenilirliği <Badge className={LEVEL_STYLE[conf.level]}>{conf.level}</Badge>
          </p>
          <ul className="list-disc pl-5 text-xs text-muted-foreground">{conf.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
        </div>
      )}
      {be && (
        <div className="rounded-md border p-3">
          <p className="text-xs text-muted-foreground">Başa baş noktası (üretim maliyeti çıkar, iade sonrası)</p>
          <p className="text-xl font-semibold">{n(be.units)} adet <span className="text-sm font-normal text-muted-foreground">(üretimin %{be.pct_of_production} kadarı)</span></p>
          <p className="text-xs text-muted-foreground">{be.note}</p>
        </div>
      )}
      {price.length > 0 && (() => {
        const base = price.find((r) => r.vs_base_pct === 0);
        const best = price.reduce((a, b) => (Number(b.net_profit) > Number(a.net_profit) ? b : a), price[0]);
        if (!base || best === base) return null;
        const above = Number(best.price) > Number(row.van_westendorp.acceptable_range_high);
        return (
          <p className="rounded-md bg-muted/60 p-2 text-xs">
            Üretim miktarı talebi sınırladığı için fiyatı <b>{best.label.replace("Fiyat ", "")}</b> ({usd(best.price)}) yapmak modelde net kârı
            %{best.vs_base_pct} artırıyor.{" "}
            {above ? "Ancak bu fiyat kabul edilebilir aralığın üstünde; ajanların çoğu bu fiyatı çok pahalı bulur, risk yüksek." : "Bu fiyat hâlâ kabul edilebilir aralıkta."}
          </p>
        );
      })()}
      {rows.length > 0 && (
        <div className="grid gap-3 md:grid-cols-2">
          {[["Fiyat duyarlılığı (120 gün net kâr)", price], ["Maliyet duyarlılığı", cost]].map(([title, list]) => (
            <div key={title as string}>
              <p className="mb-1 font-medium">{title as string}</p>
              <table className="w-full text-xs">
                <thead><tr className="text-left text-muted-foreground"><th className="py-1">Senaryo</th><th>Fiyat</th><th>Adet</th><th>Net kâr</th><th>Fark</th></tr></thead>
                <tbody>
                  {(list as typeof rows).map((r) => (
                    <tr key={r.label} className="border-t">
                      <td className="py-1">{r.label}</td><td>{usd(r.price)}</td><td>{n(r.units)}</td><td>{usd(r.net_profit)}</td>
                      <td className={r.vs_base_pct < 0 ? "text-red-600" : r.vs_base_pct > 0 ? "text-green-600" : ""}>
                        {r.vs_base_pct > 0 ? "+" : ""}{r.vs_base_pct}%
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
        </div>
      )}
      {(row.size_curve?.length ?? 0) > 0 && (
        <div>
          <p className="mb-1 font-medium">Önerilen beden dağılımı <span className="text-xs font-normal text-muted-foreground">(kural varsayımı; kendi satış verinle değiştir)</span></p>
          <div className="flex h-6 overflow-hidden rounded text-[10px] text-white">
            {row.size_curve!.map((s, i) => (
              <div key={s.size} className="grid place-items-center" style={{ width: `${s.share_pct}%`, background: `hsl(${210 + i * 12} 60% ${35 + i * 4}%)` }}>
                {s.share_pct >= 8 ? `${s.size} %${s.share_pct}` : s.size.length <= 2 && s.share_pct >= 4 ? s.size : ""}
              </div>
            ))}
          </div>
        </div>
      )}
      {row.seasonality && (
        <p className="text-xs">
          <b>Mevsim uyumu:</b> {row.seasonality.note} <span className="text-muted-foreground">({row.seasonality.basis})</span>
        </p>
      )}
    </div>
  );
}
