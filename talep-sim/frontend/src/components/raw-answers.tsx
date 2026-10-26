import type { RawAnswer } from "@/lib/api";

const STATUS: Record<RawAnswer["status"], string> = {
  json: "JSON",
  partial: "yalnızca ilgi puanı",
  extracted: "metinden çıkarıldı",
  repaired: "onarım sorusuyla düzeltildi",
  error: "model hatası",
  failed: "çözümlenemedi",
  empty: "boş cevap",
};

/** Ajanların ham cevapları; açılır bölüm, hata ayıklama için. */
export function RawAnswers({ groups }: { groups: { region: string; answers: RawAnswer[] }[] }) {
  const shown = groups.filter((g) => g.answers.length > 0);
  if (shown.length === 0) return null;
  return (
    <details className="rounded-md border p-3 text-sm">
      <summary className="cursor-pointer font-medium">Ham ajan cevapları</summary>
      <div className="mt-3 grid gap-4">
        {shown.map((g) => (
          <div key={g.region} className="grid gap-2">
            <p className="font-mono text-xs font-semibold">{g.region}</p>
            {g.answers.map((a) => (
              <div key={a.agent} className="rounded bg-muted/50 p-2">
                <p className="text-xs text-muted-foreground">
                  Ajan {a.agent}{a.segment ? ` (${a.segment})` : ""} · {STATUS[a.status] ?? a.status}
                  {a.interest != null && ` · ilgi ${Math.round(a.interest)}`}
                </p>
                <p className="whitespace-pre-wrap break-words text-xs">{a.text || "(boş)"}</p>
              </div>
            ))}
          </div>
        ))}
      </div>
    </details>
  );
}
