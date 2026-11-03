"use client";

import { useCallback, useEffect, useState } from "react";
import { Plus } from "lucide-react";

import { Button } from "@/components/ui/button";
import { BrandCard } from "@/components/collection/brand-card";
import { ImportStep } from "@/components/collection/import-step";
import { CollectionResults } from "@/components/collection/results";
import { RunPanel } from "@/components/collection/run-panel";
import {
  getCollection, getResult, listCollections,
  type Collection, type CollectionListRow, type CollectionResult,
} from "@/lib/collection-api";

const KEY = "talep-sim-koleksiyon";
const remember = (id: string | null) => {
  try { if (id) localStorage.setItem(KEY, id); else localStorage.removeItem(KEY); } catch { /* yok say */ }
};

/** Koleksiyon modu: bütün ürünleri toplu yükle, aynı panel hepsine baksın, ürün ve koleksiyon sonucu gör. */
export default function CollectionPage() {
  const [list, setList] = useState<CollectionListRow[]>([]);
  const [col, setCol] = useState<Collection | null>(null);
  const [result, setResult] = useState<CollectionResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const open = useCallback(async (id: string | null) => {
    setError(null);
    setResult(null);
    remember(id);
    if (!id) { setCol(null); return; }
    try {
      const c = await getCollection(id);
      setCol(c);
      const r = await getResult(id);
      setResult(r.summary.n_evaluated > 0 ? r : null);
    } catch (e) {
      setCol(null);
      remember(null);
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    listCollections().then(setList).catch((e) => setError(`API'ye ulaşılamadı: ${e.message ?? e}`));
    let saved: string | null = null;
    try { saved = localStorage.getItem(KEY); } catch { /* yok say */ }
    if (saved) open(saved);
  }, [open]);

  const refresh = useCallback(async () => {
    if (!col) return;
    try {
      const r = await getResult(col.id);
      setResult(r.summary.n_evaluated > 0 ? r : null);
      setList(await listCollections());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [col]);

  return (
    <main className="mx-auto grid max-w-7xl gap-4 p-4 md:p-8">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">Koleksiyon değerlendirme</h1>
          <p className="text-sm text-muted-foreground">
            Koleksiyonun bütün ürünlerini Excel ve görsellerle yükleyin. Her bölgede aynı kişiler bütün ürünlere bakar;
            ürün ürün ve koleksiyon geneli sonuç çıkar. Tek bir ürünü ayrıntılı incelemek için &quot;Tekli ürün&quot; sekmesini kullanın.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {list.length > 0 && (
            <select className="h-9 max-w-72 rounded-md border bg-background px-2 text-sm" value={col?.id ?? ""} onChange={(e) => open(e.target.value || null)}>
              <option value="">Kayıtlı koleksiyonlar…</option>
              {list.map((c) => <option key={c.id} value={c.id}>{c.name} · {c.items} ürün · {c.status}</option>)}
            </select>
          )}
          {col && <Button variant="outline" onClick={() => open(null)}><Plus className="size-4" />Yeni koleksiyon</Button>}
        </div>
      </div>
      {error && <div className="rounded-md border border-rose-300 bg-rose-50 p-3 text-sm text-rose-800">{error}</div>}

      {!col && <ImportStep onSaved={(c) => { setCol(c); remember(c.id); listCollections().then(setList).catch(() => {}); }} />}
      {col && (
        <>
          <div className="rounded-lg border p-3 text-sm">
            <b>{col.meta.name}</b> {col.meta.season && `· ${col.meta.season}`} · {col.items.length} ürün · {col.meta.target_regions.join(", ")}
            {col.meta.brand ? ` · marka ${col.meta.brand}` : " · marka girilmedi (nötr)"}
            {col.meta.total_budget ? ` · bütçe ${col.meta.total_budget.toLocaleString("tr-TR")} ${col.meta.currency}` : " · bütçe girilmedi"}
          </div>
          <div className="grid gap-4 lg:grid-cols-[420px_1fr]">
            <BrandCard key={col.id} col={col} onSaved={(c) => { setCol(c); refresh(); }} />
            <RunPanel col={col} onFinished={refresh} />
          </div>
          {result && <CollectionResults base={result} />}
        </>
      )}
    </main>
  );
}
