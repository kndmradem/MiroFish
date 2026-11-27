"use client";

import type { AudienceInfo, AudiencePanel, PredictionResponse } from "@/lib/api";
import { cn } from "@/lib/utils";

export const AUDIENCE_OPTIONS = [
  { value: "", label: "Otomatik (ad ve kategoriden tahmin)" },
  { value: "kadın", label: "Kadın" },
  { value: "erkek", label: "Erkek" },
  { value: "çocuk", label: "Çocuk" },
  { value: "kız çocuk", label: "Çocuk (kız)" },
  { value: "erkek çocuk", label: "Çocuk (erkek)" },
  { value: "bebek", label: "Bebek" },
  { value: "unisex", label: "Unisex" },
];

const METHOD: Record<AudiencePanel["method"], { label: string; how: string }> = {
  kota: { label: "kota ile seçildi", how: "Panel kişileri hedef cinsiyet ve yaş dağılımına göre seçildi." },
  "ağırlık": { label: "ağırlıklandırıldı", how: "MiroFish dünyasındaki kişiler sabit: hepsi soruldu, cevaplar hedef dağılıma göre ağırlıklandırıldı." },
  "gösterim": { label: "yalnızca gösterim", how: "Örnek (mock) motor kişi bazlı cevap üretmez; hedef dağılım yalnızca gösterilir." },
};

/** Hedef kitlenin dayanağı: kullanıcı girdisi mi, addan/kategoriden tahmin mi. */
export function AudienceChip({ a, className }: { a: AudienceInfo | null | undefined; className?: string }) {
  if (!a) return null;
  const guess = a.source === "tahmin";
  return (
    <span className={cn("inline-flex items-center gap-1 whitespace-nowrap", className)} title={a.reason}>
      <span className="rounded-full border border-indigo-300 bg-indigo-50 px-1.5 py-px text-[10px] font-medium text-indigo-800">{a.label}</span>
      <span className={cn("rounded-full border px-1.5 py-px text-[10px] font-medium",
        guess ? "border-sky-300 bg-sky-50 text-sky-800" : "border-slate-300 bg-slate-50 text-slate-700")}>
        {guess ? "tahmin" : "kullanıcı girdisi"}
      </span>
    </span>
  );
}

function who(p: AudiencePanel): string {
  const c = p.composition;
  const r = c.roles;
  if (p.value === "cocuk") {
    const kid = p.child_gender === "kız" ? "kız çocukları" : p.child_gender === "erkek" ? "erkek çocukları" : "çocukları";
    const age = p.child_age_range ? `, ${p.child_age_range[0]}-${p.child_age_range[1]} yaş` : "";
    return `${c.n} ebeveyn: ${c.n_female} anne, ${c.n_male} baba (${kid} için${age})`;
  }
  const gift = r["hediye"] ? `, ${r["hediye"]} kişi ürünü yakını için değerlendirdi` : "";
  const unk = c.n_unknown ? `, ${c.n_unknown} kişinin cinsiyeti bilinmiyor` : "";
  return `${c.n} kişi: ${c.n_female} kadın, ${c.n_male} erkek${gift}${unk}`;
}

/** Sonuç ekranı: bu ürün kime soruldu, hedef ve gerçekleşen dağılım, dayanakları. */
export function AudienceCard({ result }: { result: PredictionResponse }) {
  const rows = result.regional_breakdown.filter((r) => r.audience_panel);
  const a = result.target_audience;
  if (!a && rows.length === 0) return null;
  const warnings = Array.from(new Set(rows.flatMap((r) => r.audience_panel!.warnings)));
  return (
    <section className="grid gap-2 rounded-lg border p-4 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-base font-semibold">Kime soruldu</h2>
        <span className="text-muted-foreground">hedef kitle:</span>
        <AudienceChip a={a} />
        {a?.source === "tahmin" && <span className="text-xs text-muted-foreground">({a.reason}; formdan değiştirebilirsiniz)</span>}
      </div>
      <div className="grid gap-2 md:grid-cols-2">
        {rows.map((r) => {
          const p = r.audience_panel!;
          const m = METHOD[p.method];
          const weighted = p.method === "ağırlık";
          return (
            <div key={r.region} className="grid gap-1.5 rounded-md border p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="font-mono font-semibold">{r.region}</span>
                <span title={m.how} className="rounded-full border border-violet-300 bg-violet-50 px-1.5 py-px text-[10px] font-medium text-violet-800">{m.label}</span>
              </div>
              <p>{who(p)}</p>
              <p className="text-xs">
                {p.value === "cocuk" ? "Anne payı" : "Kadın payı"} %{p.composition.female_pct}
                <span className="text-muted-foreground"> (hedef %{p.composition.target_female_pct}{weighted ? ", ağırlıklı" : ""})</span>
                {p.n_eff != null && <span className="text-muted-foreground"> · etkili kişi sayısı {p.n_eff}</span>}
                {p.unweighted_demand != null && <span className="text-muted-foreground"> · ağırlıksız talep {p.unweighted_demand}, ağırlıklı {r.demand_score_100}</span>}
              </p>
              <table className="w-full text-xs">
                <thead><tr className="text-left text-muted-foreground"><th className="font-normal">{p.value === "cocuk" ? "Ebeveyn yaşı" : "Yaş"}</th><th className="text-right font-normal">Hedef</th><th className="text-right font-normal">Panel</th></tr></thead>
                <tbody>
                  {p.composition.age_bands.map((b) => (
                    <tr key={b.band} className="border-t">
                      <td>{b.band}</td><td className="text-right">%{b.target_pct}</td>
                      <td className="text-right">%{b.pct} <span className="text-muted-foreground">({b.n} kişi)</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="text-[11px] text-muted-foreground">
                Dağılım: <span className="rounded-full border border-amber-300 bg-amber-50 px-1.5 py-px text-[10px] font-medium text-amber-800">{p.calibration.basis}</span>{" "}
                {p.calibration.region_specific ? `${r.region} için ayrı kalibre` : "genel varsayım (bölgeye özel değil)"}, {p.calibration.version} ({p.calibration.as_of}),{" "}
                {p.calibration.verified ? "doğrulandı" : "doğrulanmadı"}. {p.note}
              </p>
            </div>
          );
        })}
      </div>
      {warnings.length > 0 && (
        <ul className="list-disc pl-4 text-xs text-amber-700">{warnings.map((w) => <li key={w}>{w}</li>)}</ul>
      )}
    </section>
  );
}
