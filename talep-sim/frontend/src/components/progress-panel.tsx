"use client";

import { useEffect, useState } from "react";
import { Check, Loader2, TriangleAlert, WifiOff } from "lucide-react";

import type { ProgressEvent } from "@/lib/api";

export type RegionStatus = "waiting" | "running" | "done" | "failed";

export interface AgentCount { answered: number; agents: number; chunk: number; chunks: number }

export interface ProgressState {
  message: string;
  regions: Record<string, RegionStatus>;
  counts: Record<string, AgentCount>;
  startedAt: number;       // ms, istemci ya da sunucu başlangıcı
  lastEventAt: number;     // ms, sunucudan son haber (ilerleme ya da kalp atışı)
  connection: "ok" | "reconnecting";
  stage: string;
}

export function initialProgress(regions: string[], message = "Başlatılıyor…"): ProgressState {
  const now = Date.now();
  return {
    message, regions: Object.fromEntries(regions.map((r) => [r, "waiting" as RegionStatus])), counts: {},
    startedAt: now, lastEventAt: now, connection: "ok", stage: "start",
  };
}

export function applyProgress(prev: ProgressState | null, ev: ProgressEvent, selected: string[]): ProgressState {
  const base = prev ?? initialProgress(selected);
  const regions = { ...base.regions };
  const counts = { ...base.counts };
  if (ev.region) {
    if (ev.stage === "region_done") regions[ev.region] = "done";
    else if (ev.stage === "region_failed") regions[ev.region] = "failed";
    else regions[ev.region] = "running";
    if (ev.agents !== undefined) {
      counts[ev.region] = { answered: ev.answered ?? 0, agents: ev.agents, chunk: ev.chunk ?? 0, chunks: ev.chunks ?? 0 };
    }
  }
  const label = ev.region && ev.stage !== "region_failed" ? `${ev.region}: ${ev.detail ?? ""}` : (ev.detail ?? base.message);
  return { ...base, regions, counts, message: label, lastEventAt: Date.now(), connection: "ok", stage: ev.stage };
}

const fmt = (s: number) => `${Math.floor(s / 60)} dk ${String(s % 60).padStart(2, "0")} sn`;

export function ProgressPanel({ progress }: { progress: ProgressState }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);
  const entries = Object.entries(progress.regions);
  const finished = entries.filter(([, s]) => s === "done" || s === "failed").length;
  const elapsed = Math.max(0, Math.round((now - progress.startedAt) / 1000));
  const silent = Math.max(0, Math.round((now - progress.lastEventAt) / 1000));
  return (
    <div className="grid gap-3 rounded-md border bg-muted/40 p-4 text-sm" aria-live="polite">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="font-medium">{finished}/{entries.length} bölge tamamlandı</p>
        <p className="font-mono text-xs text-muted-foreground">Geçen süre {fmt(elapsed)}</p>
      </div>
      {progress.connection === "reconnecting" ? (
        <p className="flex items-center gap-2 rounded bg-amber-500/15 p-2 text-xs">
          <WifiOff className="size-4" /> Bağlantı koptu, yeniden bağlanılıyor. Sunucu çalışmaya devam ediyor, sonuç kaybolmaz.
        </p>
      ) : silent > 20 ? (
        <p className="text-xs text-muted-foreground">
          Sunucudan {silent} sn önce haber geldi. Yerel model yavaş olabilir; sunucu canlı olduğu sürece bekle.
        </p>
      ) : null}
      <ul className="grid gap-2">
        {entries.map(([region, status]) => {
          const c = progress.counts[region];
          return (
            <li key={region} className="grid gap-1">
              <div className="flex items-center gap-2">
                {status === "done" && <Check className="size-4 text-green-600" />}
                {status === "running" && <Loader2 className="size-4 animate-spin" />}
                {status === "failed" && <TriangleAlert className="size-4 text-amber-600" />}
                {status === "waiting" && <span className="size-4 rounded-full border" />}
                <span className="font-mono">{region}</span>
                <span className="text-muted-foreground">
                  {{ waiting: "sırada", running: "değerlendiriliyor", done: "tamam", failed: "zaman aşımı / hata" }[status]}
                </span>
                {status === "running" && c && c.agents > 0 && (
                  <span className="ml-auto font-mono text-xs">{c.answered}/{c.agents} ajan cevapladı · grup {Math.min(c.chunk, c.chunks)}/{c.chunks}</span>
                )}
              </div>
              {status === "running" && c && c.agents > 0 && (
                <div className="h-1.5 overflow-hidden rounded bg-muted">
                  <div className="h-full bg-green-500 transition-all" style={{ width: `${(c.answered / c.agents) * 100}%` }} />
                </div>
              )}
            </li>
          );
        })}
      </ul>
      <p className="text-xs text-muted-foreground">{progress.message}</p>
    </div>
  );
}
