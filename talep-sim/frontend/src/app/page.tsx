"use client";

import { useCallback, useState } from "react";
import { ImageIcon, Loader2 } from "lucide-react";

import { BrandPanel, SourceBadge } from "@/components/brand-panel";
import { VanWestendorpChart } from "@/components/price-chart";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableFooter, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import { predict, REGIONS, TIER_LABEL, try_, usd, type BrandProfile, type PredictionResponse, type RegionCode } from "@/lib/api";

function demandTone(score: number) {
  if (score >= 70) return "text-green-600";
  if (score >= 40) return "text-amber-600";
  return "text-red-600";
}

export default function Dashboard() {
  const [productName, setProductName] = useState("Kışlık Oversize Yün Kaban");
  const [specs, setSpecs] = useState("GSM: 450g, %80 Yün %20 Polyamid, Su itici astar.");
  const [unitCost, setUnitCost] = useState("25.50");
  const [budget, setBudget] = useState("100000");
  const [usdTry, setUsdTry] = useState("42");
  const [brand, setBrand] = useState("");
  const [brandNotes, setBrandNotes] = useState("");
  const [profile, setProfile] = useState<BrandProfile | null>(null);
  const [regions, setRegions] = useState<RegionCode[]>(["EU", "MENA", "CIS"]);
  const [image, setImage] = useState<{ name: string; dataUrl: string } | null>(null);
  const [dragging, setDragging] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<PredictionResponse | null>(null);
  const [chartRegion, setChartRegion] = useState<RegionCode | null>(null);

  const readFile = useCallback((file: File | undefined) => {
    if (!file || !file.type.startsWith("image/")) return;
    const reader = new FileReader();
    reader.onload = () => setImage({ name: file.name, dataUrl: String(reader.result) });
    reader.readAsDataURL(file);
  }, []);

  const toggleRegion = (code: RegionCode, on: boolean) =>
    setRegions((prev) => (on ? [...prev, code] : prev.filter((r) => r !== code)));

  const canSubmit = !!image && productName && specs && Number(unitCost) > 0 && Number(budget) > 0 && regions.length > 0;

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!image) return;
    setLoading(true);
    setError(null);
    try {
      const res = await predict({
        product_name: productName,
        image_base64: image.dataUrl.split(",")[1] ?? "",
        technical_specs: specs,
        unit_cost: unitCost,
        total_production_budget: Math.floor(Number(budget)),
        target_regions: regions,
        brand: brand.trim() || undefined,
        brand_notes: brandNotes.trim() || undefined,
        brand_profile: profile ?? undefined,
        usd_try_rate: regions.includes("TR") && Number(usdTry) > 0 ? Number(usdTry) : undefined,
      });
      if (res.brand_profile) setProfile(res.brand_profile);
      setResult(res);
      setChartRegion(res.regional_breakdown[0]?.region ?? null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  const chartRow = result?.regional_breakdown.find((r) => r.region === chartRegion);

  return (
    <main className="mx-auto grid max-w-7xl gap-6 p-4 md:p-8 lg:grid-cols-[380px_1fr]">
      <Card className="h-fit">
        <CardHeader>
          <CardTitle>Ürün Girdisi</CardTitle>
          <CardDescription>Tasarımı ve maliyetleri gir, bölgesel talebi simüle et.</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={onSubmit} className="grid gap-4">
            <label
              onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
              onDragLeave={() => setDragging(false)}
              onDrop={(e) => { e.preventDefault(); setDragging(false); readFile(e.dataTransfer.files[0]); }}
              className={cn(
                "flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed p-4 text-center text-sm text-muted-foreground transition-colors",
                dragging && "border-primary bg-muted",
              )}
            >
              {image ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={image.dataUrl} alt={image.name} className="max-h-40 rounded-md object-contain" />
              ) : (
                <>
                  <ImageIcon className="size-8" />
                  <span>Tasarım görselini sürükle bırak ya da tıkla</span>
                </>
              )}
              <input type="file" accept="image/*" className="hidden" onChange={(e) => readFile(e.target.files?.[0])} />
            </label>

            <div className="grid gap-2">
              <Label htmlFor="name">Ürün adı</Label>
              <Input id="name" value={productName} onChange={(e) => setProductName(e.target.value)} />
            </div>
            <BrandPanel brand={brand} notes={brandNotes} profile={profile}
              onBrand={setBrand} onNotes={setBrandNotes} onProfile={setProfile} />
            <div className="grid gap-2">
              <Label htmlFor="specs">Teknik detay</Label>
              <Textarea id="specs" rows={4} value={specs} onChange={(e) => setSpecs(e.target.value)}
                placeholder="Kumaş, kalıp, ekstra detaylar" />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="grid gap-2">
                <Label htmlFor="cost">Birim maliyet ($)</Label>
                <Input id="cost" type="number" min="0.01" step="0.01" value={unitCost} onChange={(e) => setUnitCost(e.target.value)} />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="budget">Toplam bütçe ($)</Label>
                <Input id="budget" type="number" min="1" step="1" value={budget} onChange={(e) => setBudget(e.target.value)} />
              </div>
            </div>
            <div className="grid gap-2">
              <Label>Hedef bölgeler</Label>
              <div className="grid grid-cols-2 gap-2">
                {REGIONS.map((r) => (
                  <label key={r.code} className="flex items-center gap-2 text-sm">
                    <Checkbox checked={regions.includes(r.code)} onCheckedChange={(v) => toggleRegion(r.code, v === true)} />
                    {r.label}
                  </label>
                ))}
              </div>
            </div>
            {regions.includes("TR") && (
              <div className="grid gap-1 rounded-md border p-3">
                <Label htmlFor="fx" className="text-xs">Türkiye için kur: 1 USD = ? TL</Label>
                <Input id="fx" type="number" min="1" step="0.1" value={usdTry} onChange={(e) => setUsdTry(e.target.value)} />
                <p className="text-xs text-muted-foreground">
                  Varsayılan örnek bir kurdur, canlı kur değildir; güncel kurunu gir. Türkiye fiyatı TL olarak da gösterilir.
                </p>
              </div>
            )}
            <Button type="submit" disabled={!canSubmit || loading}>
              {loading && <Loader2 className="animate-spin" />}
              {loading ? "Ajanlar değerlendiriyor…" : "Simülasyonu çalıştır"}
            </Button>
            {!image && <p className="text-xs text-muted-foreground">Simülasyon için görsel gerekli.</p>}
            {error && <p className="text-sm text-destructive">{error}</p>}
          </form>
        </CardContent>
      </Card>

      <section className="grid min-w-0 content-start gap-6">
        {!result ? (
          <Card className="grid min-h-64 place-items-center text-muted-foreground">
            <p className="p-6 text-center text-sm">Sonuçlar burada görünecek.</p>
          </Card>
        ) : (
          <>
            {result.api_outdated && (
              <p className="rounded-md border border-amber-500/40 bg-amber-500/10 p-3 text-sm">
                API eski sürümde çalışıyor: açıklama ve öneri alanları gelmedi. Backend terminalinde <code>Ctrl+C</code> ile
                durdurup <code>uvicorn</code> komutunu yeniden çalıştır.
              </p>
            )}

            {result.brand_profile && (
              <Card>
                <CardHeader>
                  <CardTitle>Marka profili: {result.brand_profile.name}</CardTitle>
                  <CardDescription>
                    {TIER_LABEL[result.brand_profile.price_tier]} segment · tipik fiyat çarpanı {result.brand_profile.price_multiple}× ·
                    tipik marj %{result.brand_profile.margin_norm_pct} · çekim gücü {result.brand_profile.brand_pull}/100
                  </CardDescription>
                </CardHeader>
                <CardContent className="grid gap-3 text-sm">
                  <SourceBadge profile={result.brand_profile} />
                  {result.brand_profile.positioning && <p>{result.brand_profile.positioning}</p>}
                  {result.brand_profile.typical_customer && (
                    <p className="text-muted-foreground">Tipik müşteri: {result.brand_profile.typical_customer}</p>
                  )}
                </CardContent>
              </Card>
            )}

            <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-5">
              {result.regional_breakdown.map((r) => (
                <Card key={r.region} className="gap-2 py-4">
                  <CardHeader className="px-4">
                    <CardDescription>{REGIONS.find((x) => x.code === r.region)?.label}</CardDescription>
                    <CardTitle className={cn("text-4xl tabular-nums", demandTone(r.demand_score_100))}>
                      {r.demand_score_100}
                      <span className="ml-1 text-sm font-normal text-muted-foreground">/ 100</span>
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="px-4 text-xs text-muted-foreground">
                    Talep endeksi
                    {r.local_price && <div className="mt-1 font-medium text-foreground">{try_(r.local_price)} / {usd(r.optimal_sale_price)}</div>}
                  </CardContent>
                </Card>
              ))}
            </div>

            <Card>
              <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-2">
                <div>
                  <CardTitle>Optimal Fiyat (Van Westendorp)</CardTitle>
                  <CardDescription>
                    Yeşil alan kabul edilebilir fiyat aralığı. OPP: “çok ucuz” ve “çok pahalı” eğrilerinin kesişimi.
                  </CardDescription>
                </div>
                <div className="flex gap-1">
                  {result.regional_breakdown.map((r) => (
                    <Button key={r.region} size="sm" variant={r.region === chartRegion ? "default" : "outline"}
                      onClick={() => setChartRegion(r.region)}>
                      {r.region}
                    </Button>
                  ))}
                </div>
              </CardHeader>
              <CardContent>{chartRow && <VanWestendorpChart result={chartRow} />}</CardContent>
            </Card>

            {chartRow && chartRow.explanations.length > 0 && (
              <Card>
                <CardHeader>
                  <CardTitle>Bu sayılar nasıl hesaplandı? ({chartRow.region})</CardTitle>
                  <CardDescription>Bölgeyi yukarıdaki düğmelerle değiştirebilirsin.</CardDescription>
                </CardHeader>
                <CardContent className="grid gap-4">
                  {chartRow.explanations.map((e) => (
                    <div key={e.key} className="grid gap-1 border-b pb-3 last:border-0 last:pb-0">
                      <div className="flex items-baseline justify-between gap-2">
                        <span className="font-medium">{e.label}</span>
                        <span className="text-lg font-semibold tabular-nums">{e.value}</span>
                      </div>
                      <p className="text-sm">{e.how}</p>
                      <ul className="list-disc space-y-0.5 pl-5 text-xs text-muted-foreground">
                        {e.assumptions.map((a) => <li key={a}>{a}</li>)}
                      </ul>
                    </div>
                  ))}
                </CardContent>
              </Card>
            )}

            <Card>
              <CardHeader>
                <CardTitle>Önerilen Üretim Adedi</CardTitle>
                <CardDescription>Bütçe, talep skoru × birim kâr ağırlığıyla dağıtıldı.</CardDescription>
              </CardHeader>
              <CardContent>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Bölge</TableHead>
                      <TableHead className="text-right">Satış fiyatı</TableHead>
                      <TableHead className="text-right">Brüt marj</TableHead>
                      <TableHead className="text-right">Bütçe</TableHead>
                      <TableHead className="text-right">Adet</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {result.regional_breakdown.map((r) => (
                      <TableRow key={r.region}>
                        <TableCell className="font-medium">{r.region}</TableCell>
                        <TableCell className="text-right tabular-nums">
                          {usd(r.optimal_sale_price)}
                          {r.local_price && <div className="text-xs text-muted-foreground">{try_(r.local_price)}</div>}
                        </TableCell>
                        <TableCell className="text-right tabular-nums">%{r.estimated_margin_percentage}</TableCell>
                        <TableCell className="text-right tabular-nums">{usd(r.allocated_budget)}</TableCell>
                        <TableCell className="text-right font-semibold tabular-nums">
                          {r.recommended_production_qty.toLocaleString("tr-TR")}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                  <TableFooter>
                    <TableRow>
                      <TableCell colSpan={3}>Toplam (artan bütçe: {usd(result.unallocated_budget)})</TableCell>
                      <TableCell />
                      <TableCell className="text-right tabular-nums">{result.total_produced_qty.toLocaleString("tr-TR")}</TableCell>
                    </TableRow>
                  </TableFooter>
                </Table>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Ajan İtirazları</CardTitle>
                <CardDescription>Her bölgedeki persona sürüsünün öne çıkan 3 eleştirisi.</CardDescription>
              </CardHeader>
              <CardContent className="grid gap-4 md:grid-cols-2">
                {result.regional_breakdown.map((r) => (
                  <div key={r.region} className="grid gap-2">
                    <Badge variant="secondary">{r.region}</Badge>
                    <ul className="list-disc space-y-1 pl-5 text-sm">
                      {r.key_objections.map((o) => <li key={o}>{o}</li>)}
                    </ul>
                  </div>
                ))}
              </CardContent>
            </Card>

            {(result.recommendations ?? []).length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle>Öneriler</CardTitle>
                <CardDescription>
                  Bu çalıştırmanın sayılarına ve marka profiline göre üretildi; her önerinin dayanağı yanında yazıyor.
                </CardDescription>
              </CardHeader>
              <CardContent className="grid gap-3">
                {(result.recommendations ?? []).map((r, i) => (
                  <div key={i} className="grid gap-1 rounded-md border p-3 text-sm">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge variant="secondary">{r.category}</Badge>
                      <span className="font-medium">{r.title}</span>
                      <Badge variant="outline">{r.source === "model" ? "model önerisi" : "kural tabanlı"}</Badge>
                    </div>
                    <p>{r.detail}</p>
                    {r.based_on && <p className="text-xs text-muted-foreground">Dayanak: {r.based_on}</p>}
                  </div>
                ))}
              </CardContent>
            </Card>
            )}

            <ul className="list-disc space-y-1 pl-5 text-xs text-muted-foreground">
              {(result.methodology_notes ?? []).map((n) => <li key={n}>{n}</li>)}
            </ul>
          </>
        )}
      </section>
    </main>
  );
}
