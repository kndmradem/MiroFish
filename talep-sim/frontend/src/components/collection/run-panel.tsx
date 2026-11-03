"use client";

import { useEffect, useRef, useState } from "react";
import { Loader2, Play, Square } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { runStatus, startRun, stopRun, type Collection, type RunStatus } from "@/lib/collection-api";

const fmtDur = (s: number) => (s < 90 ? `${Math.round(s)} sn` : s < 5400 ? `${Math.round(s / 60)} dk` : `${(s / 3600).toFixed(1)} saat`);

/** 3. adım: koşuyu başlat ve izle. Koşu sunucuda sürer; sayfa kapansa da devam eder, kesilirse kaldığı yerden başlar. */
export function RunPanel({ col, onFinished }: { col: Collection; onFinished: () => void }) {
  const [st, setSt] = useState<RunStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const wasRunning = useRef(false);
  const lastDone = useRef(0);

  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      try {
        const s = await runStatus(col.id);
        if (!alive) return;
        setSt(s);
        if (s.running && s.done > lastDone.current) onFinished();   // ara sonuçları da göster
        lastDone.current = s.done;
        if (wasRunning.current && !s.running) onFinished();
        wasRunning.current = s.running;
      } catch (e) {
        if (alive) setError(e instanceof Error ? e.message : String(e));
      }
      if (alive) timer = setTimeout(tick, wasRunning.current ? 2000 : 8000);
    };
    tick();
    return () => { alive = false; clearTimeout(timer); };
  }, [col.id, onFinished]);

  async function start(rerun = false) {
    setError(null);
    try {
      const s = await startRun(col.id, { rerun });
      wasRunning.current = true;
      setSt(s);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  const regions = col.meta.target_regions.length;
  const pairs = col.items.length * regions;
  const elapsed = st?.started ? (st.finished ?? Date.now() / 1000) - st.started : 0;
  const eta = st?.running && st.done > 0 ? (elapsed / st.done) * (st.total - st.done) : null;
  const pct = st && st.total ? Math.round((100 * st.done) / st.total) : 0;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">3. Paneli çalıştır</CardTitle>
        <CardDescription>
          {col.items.length} ürün × {regions} bölge = {pairs} değerlendirme. Her bölgede aynı kişiler bütün ürünlere bakar.
          Mac&apos;te (12 kişi, 2 paralel) ürün-bölge başına yaklaşık 1-2 dakika: toplam kabaca {fmtDur(pairs * 60)}-{fmtDur(pairs * 120)} (tahmin, ölçülmedi).
          Koşu sunucuda sürer; sayfayı kapatabilirsiniz. Durdurulursa ya da API yeniden başlarsa, tekrar başlatınca biten ürünler atlanır.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-3">
        <div className="flex flex-wrap items-center gap-2">
          {!st?.running ? (
            <>
              <Button onClick={() => start(false)}><Play className="size-4" />{st && st.done > 0 ? "Devam et / eksikleri çalıştır" : "Çalıştır"}</Button>
              {st && st.done > 0 && <Button variant="outline" onClick={() => start(true)}>Hepsini baştan çalıştır</Button>}
            </>
          ) : (
            <Button variant="outline" onClick={() => stopRun(col.id).then(setSt)}><Square className="size-4" />Durdur</Button>
          )}
          {error && <span className="text-sm text-rose-600">{error}</span>}
        </div>
        {st && st.total > 0 && (
          <div className="grid gap-1.5">
            <div className="h-2 overflow-hidden rounded-full bg-muted">
              <div className="h-full bg-primary transition-all" style={{ width: `${pct}%` }} />
            </div>
            <div className="flex flex-wrap justify-between gap-2 text-xs text-muted-foreground">
              <span className="flex items-center gap-1">
                {st.running && <Loader2 className="size-3 animate-spin" />}
                {st.done}/{st.total} ürün{st.failed.length ? `, ${st.failed.length} hata` : ""}
                {st.running && st.detail ? ` · ${st.detail}` : ""}
              </span>
              <span>{elapsed > 0 && `geçen ${fmtDur(elapsed)}`}{eta ? ` · kalan ~${fmtDur(eta)}` : ""}</span>
            </div>
            {st.error && <div className="text-sm text-rose-600">{st.error}</div>}
            {st.log.length > 0 && (
              <details className="text-xs">
                <summary className="cursor-pointer text-muted-foreground">Koşu günlüğü</summary>
                <pre className="mt-1 max-h-48 overflow-auto rounded bg-muted p-2 whitespace-pre-wrap">{st.log.slice(-40).join("\n")}</pre>
              </details>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
