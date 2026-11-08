"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils";

const TABS = [
  { href: "/", label: "Tekli ürün", hint: "Tek bir tasarımı ayrıntılı simüle et" },
  { href: "/koleksiyon", label: "Koleksiyon (çoklu)", hint: "Koleksiyonun bütün ürünlerini toplu değerlendir" },
  { href: "/toplu", label: "Toplu ürün (ayrı ayrı)", hint: "Koleksiyonu olmayan ürünleri toplu yükle, her biri ayrı değerlendirilsin" },
  { href: "/yeni-magaza", label: "Yeni mağaza", hint: "Yeni bölgede mağaza öngörüsü" },
];

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
    </nav>
  );
}
