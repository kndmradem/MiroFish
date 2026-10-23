import { Check, Loader2, TriangleAlert } from "lucide-react";

import type { ProgressEvent } from "@/lib/api";

export type RegionStatus = "waiting" | "running" | "done" | "failed";

export interface ProgressState {
  message: string;
  regions: Record<string, RegionStatus>;
}

export function applyProgress(prev: ProgressState | null, ev: ProgressEvent, selected: string[]): ProgressState {
  const base: ProgressState = prev ?? { message: "", regions: Object.fromEntries(selected.map((r) => [r, "waiting" as RegionStatus])) };
  const regions = { ...base.regions };
  if (ev.region) {
    if (ev.stage === "region_done") regions[ev.region] = "done";
    else if (ev.stage === "region_failed") regions[ev.region] = "failed";
    else regions[ev.region] = "running";
  }
  const label = ev.region && ev.stage !== "region_failed" ? `${ev.region}: ${ev.detail ?? ""}` : (ev.detail ?? base.message);
  return { message: label, regions };
}

export function ProgressPanel({ progress }: { progress: ProgressState }) {
  const entries = Object.entries(progress.regions);
  const finished = entries.filter(([, s]) => s === "done" || s === "failed").length;
  return (
    <div className="grid gap-2 rounded-md border bg-muted/40 p-3 text-sm" aria-live="polite">
      <p className="font-medium">{finished}/{entries.length} bölge tamamlandı</p>
      <ul className="grid gap-1">
        {entries.map(([region, status]) => (
          <li key={region} className="flex items-center gap-2">
            {status === "done" && <Check className="size-4 text-green-600" />}
            {status === "running" && <Loader2 className="size-4 animate-spin" />}
            {status === "failed" && <TriangleAlert className="size-4 text-amber-600" />}
            {status === "waiting" && <span className="size-4 rounded-full border" />}
            <span className="font-mono">{region}</span>
            <span className="text-muted-foreground">
              {{ waiting: "sırada", running: "değerlendiriliyor", done: "tamam", failed: "zaman aşımı / hata" }[status]}
            </span>
          </li>
        ))}
      </ul>
      <p className="text-xs text-muted-foreground">{progress.message}</p>
    </div>
  );
}
