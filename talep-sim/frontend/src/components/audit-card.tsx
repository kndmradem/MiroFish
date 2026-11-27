"use client";

import { useState } from "react";
import { AlertTriangle, CheckCircle2, ChevronDown, ChevronRight, Info, ShieldAlert } from "lucide-react";

import { cn } from "@/lib/utils";
import type { DenetimRaporu, Seviye } from "@/lib/denetim";

const SEV: Record<Seviye, { label: string; cls: string }> = {
  hata: { label: "Hata", cls: "border-rose-300 bg-rose-50 text-rose-800" },
  uyarı: { label: "Uyarı", cls: "border-amber-300 bg-amber-50 text-amber-800" },
  bilgi: { label: "Bilgi", cls: "border-slate-300 bg-slate-50 text-slate-700" },
};

/** Sonuç ekranında 'Denetim uyarıları'. Hata varsa kırmızı 'İncelenmeli' damgası ve liste açık gelir. */
export function AuditCard({ rapor, names, reportUrl }: { rapor?: DenetimRaporu | null; names?: Record<string, string>; reportUrl?: string }) {
  const bad = rapor?.durum === "incelenmeli";
  const [open, setOpen] = useState(bad);
  const [showInfo, setShowInfo] = useState(false);
  if (!rapor) return null;
  const s = rapor.sayilar;
  const list = rapor.bulgular.filter((b) => showInfo || b.seviye !== "bilgi");
  const tone = bad ? "border-rose-400 bg-rose-50 text-rose-900" : rapor.durum === "uyarılı" ? "border-amber-300 bg-amber-50/60 text-amber-900" : "border-emerald-300 bg-emerald-50/60 text-emerald-900";
  const Icon = bad ? ShieldAlert : rapor.durum === "uyarılı" ? AlertTriangle : CheckCircle2;
  return (
    <section className={cn("audit-card grid gap-2 rounded-lg border p-3 text-sm", tone)}>
      <div className="flex flex-wrap items-center gap-2">
        <Icon className="size-4 shrink-0" />
        <span className="font-semibold">Denetim uyarıları</span>
        {bad && <span className="rounded bg-rose-600 px-2 py-0.5 text-xs font-bold tracking-wide text-white">İNCELENMELİ</span>}
        <span className="text-xs">{s.hata ?? 0} hata · {s["uyarı"] ?? 0} uyarı · {s.bilgi ?? 0} bilgi</span>
        <span className="flex-1">{rapor.ozet}</span>
        {rapor.bulgular.length > 0 && (
          <button type="button" className="no-print inline-flex items-center gap-1 text-xs underline" onClick={() => setOpen(!open)}>
            {open ? <ChevronDown className="size-3" /> : <ChevronRight className="size-3" />}{open ? "Gizle" : "Göster"}
          </button>
        )}
        {reportUrl && <a href={reportUrl} target="_blank" rel="noreferrer" className="no-print text-xs underline">Denetim raporu</a>}
      </div>
      {open && rapor.bulgular.length > 0 && (
        <ul className="grid gap-1.5">
          {list.map((b, i) => (
            <li key={i} className="flex items-start gap-2 rounded-md border bg-white/70 p-2">
              <span className={cn("shrink-0 rounded-full border px-1.5 py-px text-[10px] font-medium", SEV[b.seviye].cls)}>{SEV[b.seviye].label}</span>
              <span className="flex-1">
                <span className="font-medium">{b.baslik}:</span> {b.mesaj}
                {b.skus.length > 0 && names && <span className="text-xs text-muted-foreground"> ({b.skus.map((k) => names[k] ?? k).join(", ")})</span>}
              </span>
              <span className="shrink-0 rounded-full border px-1.5 py-px text-[10px] text-muted-foreground" title="Denetlenen sayının dayanağı">{b.dayanak}</span>
            </li>
          ))}
          {rapor.bulgular.some((b) => b.seviye === "bilgi") && (
            <li className="no-print">
              <button type="button" className="inline-flex items-center gap-1 text-xs underline" onClick={() => setShowInfo(!showInfo)}>
                <Info className="size-3" />{showInfo ? "Bilgi notlarını gizle" : `Bilgi notlarını da göster (${s.bilgi})`}
              </button>
            </li>
          )}
          <li className="text-xs text-muted-foreground">{rapor.sinir}</li>
        </ul>
      )}
    </section>
  );
}
