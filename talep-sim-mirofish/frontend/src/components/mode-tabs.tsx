"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { cn } from "@/lib/utils";

const TABS = [
  { href: "/", label: "Tekli ürün", hint: "Tek bir tasarımı ayrıntılı simüle et" },
  { href: "/koleksiyon", label: "Koleksiyon (çoklu)", hint: "Koleksiyonun bütün ürünlerini toplu değerlendir" },
  { href: "/toplu", label: "Toplu ürün (ayrı ayrı)", hint: "Koleksiyonu olmayan ürünleri toplu yükle, her biri ayrı değerlendirilsin" },
  { href: "/yeni-magaza", label: "Yeni mağaza", hint: "Yeni bölgede mağaza öngörüsü" },
];

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8100";

type Health = { engine: string; mirofish_ok: boolean | null; mirofish_url?: string };

/** Karma/MiroFish motorunda MiroFish servisine ulaşılamıyorsa koşudan önce uyarır (30 sn'de bir kontrol). */
function MiroFishStatus() {
  const [h, setH] = useState<Health | null>(null);
  useEffect(() => {
    let alive = true;
    const tick = () => fetch(`${API_URL}/health`).then((r) => r.json()).then((d) => alive && setH(d)).catch(() => alive && setH(null));
    tick();
    const t = setInterval(tick, 30000);
    return () => { alive = false; clearInterval(t); };
  }, []);
  if (!h || h.mirofish_ok !== false) return null;
  return (
    <div className="border-b border-amber-300 bg-amber-50 px-4 py-2 text-center text-xs text-amber-900 md:px-8">
      MiroFish servisine ulaşılamıyor ({h.mirofish_url}).{" "}
      {h.engine === "hybrid"
        ? "Şimdi çalıştırırsan bütün bölgeler persona paneliyle hesaplanır. MiroFish için 1-mirofish.sh penceresini başlat."
        : "Tahmin çalışmaz. 1-mirofish.sh penceresini başlat."}
    </div>
  );
}

/** Üst sekmeler: kullanıcı tekli ya da koleksiyon modunu seçer. Her mod kendi sayfasıdır, sonuçları birbirini etkilemez. */
export function ModeTabs() {
  const path = usePathname();
  return (
    <nav className="sticky top-0 z-20 border-b bg-background/95 backdrop-blur">
      <div className="mx-auto flex max-w-7xl items-center gap-1 overflow-x-auto px-4 md:px-8">
        <span className="mr-3 py-3 text-sm font-semibold whitespace-nowrap">Talep Simülasyonu</span>
        {TABS.map((t) => {
          const active = t.href === "/" ? path === "/" : path.startsWith(t.href);
          return (
            <Link key={t.href} href={t.href} title={t.hint}
              className={cn("border-b-2 px-3 py-3 text-sm whitespace-nowrap transition-colors",
                active ? "border-primary font-medium text-foreground" : "border-transparent text-muted-foreground hover:text-foreground")}>
              {t.label}
            </Link>
          );
        })}
      </div>
      <MiroFishStatus />
    </nav>
  );
}
