import { Badge } from "@/components/ui/badge";
import type { CalendarPlan, RegionPredictionResult } from "@/lib/api";
import { usd } from "@/lib/api";

const n = (v: number) => v.toLocaleString("tr-TR");
const dt = (s: string) => new Date(s + "T00:00:00").toLocaleDateString("tr-TR", { day: "2-digit", month: "short" });
const range = (a: string, b: string) => (a === b ? dt(a) : `${dt(a)} - ${dt(b)}`);

const KIND_COLOR: Record<string, string> = {
  hediye: "bg-pink-500",
  dini: "bg-emerald-600",
  mega_indirim: "bg-red-500",
  pazaryeri: "bg-orange-500",
  sezon_sonu: "bg-amber-500",
  sezon_basi: "bg-sky-500",
  okul: "bg-indigo-500",
  milli: "bg-slate-500",
};

const BASIS_LABEL: Record<string, string> = { ajan: "ajan", mock: "mock (sahte)", "kural varsayımı": "kural varsayımı" };

function monthTicks(cp: CalendarPlan) {
  const start = new Date(cp.start_date + "T00:00:00");
  const ticks: { day: number; label: string }[] = [];
  const d = new Date(start.getFullYear(), start.getMonth() + 1, 1);
  while (true) {
    const day = Math.round((d.getTime() - start.getTime()) / 86400000);
    if (day >= cp.horizon_days) break;
    ticks.push({ day, label: d.toLocaleDateString("tr-TR", { month: "short" }) });
    d.setMonth(d.getMonth() + 1);
  }
  return ticks;
}

/** Perakende takvimi şeridi: etkinlikler (ön pencere açık renk) ve önerilen planın kampanyaları. */
function Timeline({ cp }: { cp: CalendarPlan }) {
  const H = cp.horizon_days;
  const pct = (d: number) => `${(Math.max(0, Math.min(H, d)) / H) * 100}%`;
  const w = (a: number, b: number) => `${((Math.max(0, Math.min(H, b)) - Math.max(0, Math.min(H, a))) / H) * 100}%`;
  const rec = cp.options.find((o) => o.recommended);
  const ticks = monthTicks(cp);
  return (
    <div className="grid gap-1 text-xs">
      <div className="relative ml-[9rem] h-4 border-b text-muted-foreground">
        {ticks.map((t) => (
          <span key={t.day} className="absolute -translate-x-1/2" style={{ left: pct(t.day) }}>{t.label}</span>
        ))}
      </div>
      {cp.events.map((e) => (
        <div key={e.code} className="flex items-center gap-2">
          <span className="w-[8.5rem] shrink-0 truncate" title={e.name}>{e.name}</span>
          <div className="relative h-4 flex-1 rounded bg-muted/50">
            {ticks.map((t) => <span key={t.day} className="absolute top-0 h-4 border-l border-dashed border-muted-foreground/20" style={{ left: pct(t.day) }} />)}
            {e.window_from_day < e.day_from && (
              <span className={`absolute top-1 h-2 rounded opacity-30 ${KIND_COLOR[e.kind] ?? "bg-slate-500"}`}
                style={{ left: pct(e.window_from_day), width: w(e.window_from_day, e.day_from) }} />
            )}
            <span className={`absolute top-0 h-4 min-w-1 rounded ${KIND_COLOR[e.kind] ?? "bg-slate-500"} ${e.verified ? "" : "opacity-80"}`}
              style={{ left: pct(e.day_from), width: w(e.day_from, e.day_to + 1) }} title={`${e.kind_label}, uygunluk %${e.fit_pct}`} />
          </div>
        </div>
      ))}
      <div className="flex items-center gap-2 pt-1">
        <span className="w-[8.5rem] shrink-0 font-medium">Önerilen kampanya</span>
        <div className="relative h-5 flex-1 rounded border border-dashed">
          {(rec?.campaigns ?? []).map((c) => (
            <span key={c.event_code} className="absolute top-0 flex h-5 items-center justify-center rounded bg-green-600 px-1 text-[10px] font-semibold text-white"
              style={{ left: pct(c.day_from), width: w(c.day_from, c.day_to + 1), minWidth: "2.2rem" }}>
              %{c.discount_pct}
            </span>
          ))}
          {rec && rec.campaigns.length === 0 && <span className="absolute inset-0 grid place-items-center text-muted-foreground">kampanya yok, tam fiyat</span>}
        </div>
      </div>
    </div>
  );
}

/** Perakende takvimine göre kampanya planı: etkinlikler, ürün-etkinlik uygunluğu ve puanlanmış plan seçenekleri. */
export function CalendarPlanCard({ row }: { row: RegionPredictionResult }) {
  const cp = row.calendar_plan;
  if (!cp) return null;
  return (
    <div className="grid gap-4 text-sm">
      {cp.verdict && <p className="rounded-md bg-muted/60 p-2 text-xs font-medium">{cp.verdict}</p>}
      {cp.events.length > 0 && <Timeline cp={cp} />}

      <div className="grid gap-3">
        {cp.options.map((o) => (
          <div key={o.key} className={`grid gap-2 rounded-md border p-3 ${o.recommended ? "border-green-500 bg-green-500/5" : ""}`}>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="font-medium">{o.label}</span>
              {o.recommended && <Badge className="bg-green-600">Önerilen</Badge>}
            </div>
            {o.campaigns.length > 0 ? (
              <ul className="grid gap-1 text-xs">
                {o.campaigns.map((c) => (
                  <li key={c.event_code}>
                    <b>{c.event_name}</b>: {range(c.date_from, c.date_to)}, %{c.discount_pct} indirim ({usd(c.price)}), {n(c.units)} adet,
                    satın alma olasılığı %{c.purchase_prob_pct} (ajan)
                    {c.advertised_discount_pct + 0.5 < c.discount_pct && (
                      <span className="text-amber-600"> · ilan edilebilecek indirim %{c.advertised_discount_pct} (son 30 gün en düşük {usd(c.ref_price)})</span>
                    )}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-xs text-muted-foreground">120 gün tam fiyat.</p>
            )}
            <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
              <div><p className="text-muted-foreground">Satış</p><p className="font-semibold">{n(o.units)}</p>
                <p className="text-muted-foreground">{n(o.units_low)} - {n(o.units_high)}</p></div>
              <div><p className="text-muted-foreground">Kalan stok</p><p className="font-semibold">{n(o.leftover_units)}</p>
                <p className="text-muted-foreground">satış oranı %{o.sell_through_pct}</p></div>
              <div><p className="text-muted-foreground">İade sonrası kâr</p><p className="font-semibold">{usd(o.net_profit)}</p>
                <p className="text-muted-foreground">+ kalan stok değeri {usd(o.residual_value)}</p></div>
              <div><p className="text-muted-foreground">Toplam değer</p><p className="font-semibold">{usd(o.total_value)}</p>
                <p className="text-muted-foreground">{usd(o.total_value_low)} - {usd(o.total_value_high)}</p></div>
            </div>
          </div>
        ))}
      </div>

      {cp.events.length > 0 && (
        <div className="overflow-x-auto">
        <table className="w-full min-w-[40rem] text-xs">
          <thead>
            <tr className="text-left text-muted-foreground">
              <th className="py-1">Etkinlik</th><th>Tarih</th><th>Tür</th><th>Uygunluk</th><th>Etki (indirimsiz)</th><th>Takvim</th>
            </tr>
          </thead>
          <tbody>
            {cp.events.map((e) => (
              <tr key={e.code} className="border-t align-top">
                <td className="py-1">
                  {e.name}{e.country_only && <Badge variant="outline" className="ml-1">yalnız {e.scope}</Badge>}
                  {e.comments.length > 0 && <p className="text-muted-foreground">“{e.comments[0]}”</p>}
                </td>
                <td>{range(e.date_from, e.date_to)}</td>
                <td>{e.kind_label}</td>
                <td>%{e.fit_pct} <span className="text-muted-foreground">({BASIS_LABEL[e.fit_basis] ?? e.fit_basis}{e.fit_n ? `, ${e.fit_n} cevap` : ""})</span></td>
                <td>+%{e.lift_low_pct} - %{e.lift_high_pct} <span className="text-muted-foreground">(kural)</span></td>
                <td>{e.verified ? "doğrulandı" : <span className="text-amber-600">doğrulanmadı</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      )}

      {cp.wait_event && cp.wait_share_pct != null && (
        <p className="text-xs">
          <b>Bekleme eğilimi:</b> cevap verenlerin %{cp.wait_share_pct}&apos;i bu ürün için {cp.events.find((e) => e.code === cp.wait_event)?.name ?? cp.wait_event} indirimini
          bekleyeceğini söyledi ({BASIS_LABEL[cp.wait_basis] ?? cp.wait_basis}, {cp.wait_n} cevap).
        </p>
      )}

      {cp.warnings.length > 0 && (
        <ul className="list-disc space-y-1 rounded-md border border-amber-500/40 bg-amber-500/5 p-2 pl-6 text-xs">
          {cp.warnings.map((w) => <li key={w}>{w}</li>)}
        </ul>
      )}
      <ul className="list-disc space-y-1 pl-5 text-xs text-muted-foreground">
        {cp.assumptions.map((a) => <li key={a}>{a}</li>)}
        <li>{n(cp.n_plans_evaluated)} plan denendi. Takvim dosyası: panel_data/takvim/perakende_takvimi.csv (Excel ile düzenlenir).</li>
        <li><b>Dayanak:</b> {cp.basis}.</li>
      </ul>
    </div>
  );
}
