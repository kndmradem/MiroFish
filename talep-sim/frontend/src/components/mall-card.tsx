"use client";

import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import {
  fetchMallProfile, searchMalls,
  type Basis, type BrandTier, type MallHit, type MallProfile,
} from "@/lib/mall-api";

const BASIS_CLASS: Record<Basis, string> = {
  "dış veri": "border-sky-500/50 bg-sky-500/10 text-sky-800 dark:text-sky-300",
  "kural varsayımı": "border-amber-500/50 bg-amber-500/10 text-amber-800 dark:text-amber-300",
  "kullanıcı girdisi": "border-violet-500/50 bg-violet-500/10 text-violet-800 dark:text-violet-300",
  bilinmiyor: "border-zinc-400/50 bg-zinc-400/10 text-zinc-600 dark:text-zinc-400",
};
const TIERS: { value: BrandTier; label: string }[] = [
  { value: "budget", label: "ekonomik" }, { value: "mass", label: "kitlesel" }, { value: "upper_mass", label: "üst-kitlesel" },
  { value: "premium", label: "premium" }, { value: "luxury", label: "lüks" },
];
const pct = (v: number) => `%${Math.round(v * 100)}`;

function BasisBadge({ basis }: { basis: Basis }) {
  return <span className={`rounded border px-1.5 py-0.5 text-[11px] whitespace-nowrap ${BASIS_CLASS[basis]}`}>{basis}</span>;
}

/** Aday mağazanın AVM'si: yerel katalogdan arama ya da elle giriş; veri yoksa şehir bazlı hesap aynen çalışır. */
export function MallCard({ ulke, sehir }: { ulke: string; sehir: string }) {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<MallHit[] | null>(null);
  const [mode, setMode] = useState<"katalog" | "elle">("katalog");
  const [tier, setTier] = useState<BrandTier | "">("");
  const [selected, setSelected] = useState<MallHit | null>(null);
  const [manual, setManual] = useState({ name: "", tenants: "", visitors: "", source: "" });
  const [profile, setProfile] = useState<MallProfile | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setSelected(null);
    setProfile(null);
    if (!ulke || !sehir) return;
    const t = setTimeout(() => {
      searchMalls(ulke, sehir, q).then(setHits).catch((e) => setError(String(e.message ?? e)));
    }, 250);
    return () => clearTimeout(t);
  }, [ulke, sehir, q]);

  const noCatalog = hits !== null && hits.length === 0 && q === "";

  async function load(body: Parameters<typeof fetchMallProfile>[0]) {
    setBusy(true);
    setError(null);
    try {
      setProfile(await fetchMallProfile({ ...body, brand_tier: tier || null }));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  function pick(h: MallHit) {
    setSelected(h);
    void load({ ulke, sehir, mall_id: h.id });
  }

  function submitManual() {
    void load({
      ulke, sehir,
      manual: {
        name: manual.name || "Elle girilen AVM", tenants: [manual.tenants],
        visitors_yearly: manual.visitors ? Number(manual.visitors) : null, visitors_source: manual.source || null,
      },
    });
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">AVM</CardTitle>
        <CardDescription>
          AVM seçilirse kiracı markalarından fiyat segmenti ve rakipler çıkarılır, panel segment ağırlıkları buna göre kaydırılır.
          Seçilmezse tahmin şehir verisiyle yapılır.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-3 text-sm">
        <div className="flex flex-wrap items-end gap-3">
          <div className="flex gap-1 rounded-md border p-0.5">
            {(["katalog", "elle"] as const).map((m) => (
              <button key={m} type="button" onClick={() => { setMode(m); setProfile(null); }}
                className={`rounded px-2 py-1 text-xs ${mode === m ? "bg-primary text-primary-foreground" : ""}`}>
                {m === "katalog" ? "Katalogdan ara" : "Elle gir"}
              </button>
            ))}
          </div>
          <div className="grid gap-1">
            <Label htmlFor="tier">Markanın fiyat katmanı (rakipler için)</Label>
            <select id="tier" className="h-9 rounded-md border bg-transparent px-2 text-sm" value={tier}
              onChange={(e) => setTier(e.target.value as BrandTier | "")}>
              <option value="">seçilmedi</option>
              {TIERS.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
            </select>
          </div>
        </div>

        {mode === "katalog" && (
          <div className="grid gap-2">
            {noCatalog ? (
              <p className="rounded-md border border-amber-500/50 bg-amber-500/10 p-2">
                {sehir} ({ulke}) için AVM kataloğu yok. Tahmin şehir verisiyle yapılır; AVM bilgisini &quot;Elle gir&quot; ile ekleyebilirsin.
              </p>
            ) : (
              <>
                <Input placeholder="AVM adı yaz (ör. Zorlu, Kingdom, Esentai)" value={q} onChange={(e) => setQ(e.target.value)} />
                {hits && hits.length > 0 && (
                  <ul className="max-h-56 overflow-y-auto rounded-md border">
                    {hits.map((h) => (
                      <li key={h.id}>
                        <button type="button" onClick={() => pick(h)}
                          className={`flex w-full items-center justify-between gap-2 px-2 py-1.5 text-left hover:bg-muted ${selected?.id === h.id ? "bg-muted" : ""}`}>
                          <span>
                            {h.name}
                            {h.aliases.length > 0 && <span className="text-xs text-muted-foreground"> · {h.aliases.join(" · ")}</span>}
                          </span>
                          <span className="shrink-0 text-xs text-muted-foreground">
                            {h.apparel_count} giyim mağazası{h.dense_area ? " · çarşı bölgesi" : ""}
                          </span>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
                {hits && hits.length === 0 && q !== "" && (
                  <p className="text-muted-foreground">Bulunamadı. Katalogda olmayabilir; &quot;Elle gir&quot; ile ekleyebilirsin.</p>
                )}
              </>
            )}
          </div>
        )}

        {mode === "elle" && (
          <div className="grid gap-2 sm:grid-cols-2">
            <div className="grid gap-1">
              <Label htmlFor="avm-ad">AVM adı</Label>
              <Input id="avm-ad" value={manual.name} onChange={(e) => setManual({ ...manual, name: e.target.value })} />
            </div>
            <div className="grid gap-1">
              <Label htmlFor="avm-ziy">Yıllık ziyaretçi (biliniyorsa)</Label>
              <Input id="avm-ziy" type="number" value={manual.visitors} onChange={(e) => setManual({ ...manual, visitors: e.target.value })} />
            </div>
            <div className="grid gap-1 sm:col-span-2">
              <Label htmlFor="avm-kir">Kiracı markalar (virgülle ya da satır satır)</Label>
              <textarea id="avm-kir" rows={3} className="rounded-md border bg-transparent p-2 text-sm"
                value={manual.tenants} onChange={(e) => setManual({ ...manual, tenants: e.target.value })} />
            </div>
            <div className="grid gap-1 sm:col-span-2">
              <Label htmlFor="avm-kay">Ziyaretçi sayısının kaynağı (link ya da &quot;AVM yönetimi, 2026&quot;)</Label>
              <Input id="avm-kay" value={manual.source} onChange={(e) => setManual({ ...manual, source: e.target.value })} />
            </div>
            <div><Button onClick={submitManual} disabled={busy}>{busy && <Loader2 className="mr-2 size-4 animate-spin" />}AVM profilini çıkar</Button></div>
          </div>
        )}

        {busy && mode === "katalog" && <p className="flex items-center gap-2 text-muted-foreground"><Loader2 className="size-4 animate-spin" />AVM profili hazırlanıyor</p>}
        {error && <p className="rounded-md border border-red-500/40 bg-red-500/10 p-2">{error}</p>}
        {profile && <MallProfileView p={profile} />}
      </CardContent>
    </Card>
  );
}

function MallProfileView({ p }: { p: MallProfile }) {
  const byTier = TIERS.map((t) => ({ ...t, brands: p.known_brands.filter((b) => b.tier === t.label).map((b) => b.name) }));
  const changed = p.segments.some((s) => s.multiplier !== 1);
  return (
    <div className="grid gap-3 border-t pt-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">{p.name}</span>
        {p.price_segment && <Badge>{p.price_segment}</Badge>}
        {p.manual ? <Badge variant="outline">elle girildi</Badge>
          : <Badge variant={p.verified ? "secondary" : "outline"}>{p.verified ? "onaylı katalog" : "taslak katalog"}</Badge>}
      </div>
      {p.warnings.length > 0 && <ul className="list-disc pl-5 text-amber-700 dark:text-amber-400">{p.warnings.map((w) => <li key={w}>{w}</li>)}</ul>}

      <div className="overflow-x-auto">
        <Table>
          <TableHeader><TableRow><TableHead>Sinyal</TableHead><TableHead>Değer</TableHead><TableHead>Dayanak</TableHead><TableHead>Not</TableHead></TableRow></TableHeader>
          <TableBody>
            {p.signals.map((s) => (
              <TableRow key={s.key}>
                <TableCell>{s.label}</TableCell>
                <TableCell className="font-medium">{s.value ?? "bilinmiyor"}</TableCell>
                <TableCell><BasisBadge basis={s.basis} /></TableCell>
                <TableCell className="text-xs text-muted-foreground">{s.note}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      {p.known_brands.length > 0 && (
        <div className="grid gap-1">
          <p className="font-medium">Katmanı bilinen markalar</p>
          {byTier.filter((t) => t.brands.length).map((t) => (
            <p key={t.value}>
              <span className="text-muted-foreground">{t.label} ({t.brands.length}): </span>
              {t.brands.map((b) => <span key={b} className={`mr-1 inline-block rounded px-1 ${p.rivals.includes(b) ? "bg-red-500/15" : ""}`}>{b}</span>)}
            </p>
          ))}
          {p.rivals.length > 0 && <p className="text-xs text-muted-foreground">Kırmızı zeminli markalar seçilen katmanda ya da komşu katmanda rakip.</p>}
          {p.unknown_brands.length > 0 && (
            <p className="text-xs text-muted-foreground">Katmanı bilinmeyen ({p.unknown_brands.length}, hesaba girmedi): {p.unknown_brands.slice(0, 15).join(", ")}{p.unknown_brands.length > 15 ? " …" : ""}</p>
          )}
        </div>
      )}

      {p.segments.length > 0 && (
        <div className="grid gap-1">
          <p className="font-medium">Panel segment ağırlıkları ({p.region}): bölge varsayılanı ve bu AVM için</p>
          <div className="overflow-x-auto">
            <Table>
              <TableHeader><TableRow><TableHead>Segment</TableHead><TableHead>Gelir</TableHead><TableHead>Bölge</TableHead><TableHead>Bu AVM</TableHead><TableHead>Çarpan</TableHead><TableHead className="w-40"></TableHead></TableRow></TableHeader>
              <TableBody>
                {p.segments.map((s) => (
                  <TableRow key={s.id}>
                    <TableCell>{s.label}</TableCell>
                    <TableCell className="text-muted-foreground">{s.income_band}</TableCell>
                    <TableCell>{pct(s.base_weight)}</TableCell>
                    <TableCell className="font-medium">{pct(s.mall_weight)}</TableCell>
                    <TableCell className={s.multiplier > 1 ? "text-emerald-700 dark:text-emerald-400" : s.multiplier < 1 ? "text-red-700 dark:text-red-400" : ""}>×{s.multiplier.toFixed(2)}</TableCell>
                    <TableCell>
                      <div className="relative h-2 rounded bg-muted">
                        <div className="absolute inset-y-0 left-0 rounded bg-zinc-400/60" style={{ width: `${s.base_weight * 200}%` }} />
                        <div className="absolute inset-y-0 left-0 h-1 rounded bg-primary" style={{ width: `${s.mall_weight * 200}%` }} />
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          <p className="text-xs text-muted-foreground">
            {changed
              ? "Çarpanlar kural varsayımıdır (AVM fiyat segmentinin şehir ortalamasından farkı × segment gelir bandı; 0,5 ile 2 arasında sınırlı). Pilot verisiyle kalibre edilene kadar böyle gösterilir."
              : "AVM bilgisi panel ağırlıklarını değiştirmedi; bölge varsayılanı kullanılır."}
            {" "}Bu kart şimdilik ciro tahminini değiştirmez.
          </p>
        </div>
      )}
      {p.source && (
        <p className="text-xs text-muted-foreground">
          Kaynak: {p.source.dataset} {p.source.release}, alındı {p.source.retrieved_at}. {p.source.license}.
        </p>
      )}
    </div>
  );
}
