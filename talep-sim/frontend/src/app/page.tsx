"use client";

import { useCallback, useEffect, useState } from "react";
import { ImageIcon, Loader2 } from "lucide-react";

import { BrandPanel, SourceBadge } from "@/components/brand-panel";
import { applyProgress, initialProgress, ProgressPanel, type ProgressState } from "@/components/progress-panel";
import { ExtrasCard } from "@/components/extras-card";
import { SummaryCard } from "@/components/summary-card";
import { CampaignsCard, PricePlanCard } from "@/components/scenarios-card";
import { ForecastCard } from "@/components/forecast-card";
import { ReturnsCard } from "@/components/returns-card";
import { PriceZones } from "@/components/price-zones";
import { RawAnswers } from "@/components/raw-answers";
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
import { predictStream, REGIONS, resumeRun, savedRun, type StreamHandlers, TIER_LABEL, try_, usd, type BrandProfile, type PredictionResponse, type RegionCode } from "@/lib/api";

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
  const [channel, setChannel] = useState<"online" | "store">("online");
  const [restock, setRestock] = useState("70");
  const [logistics, setLogistics] = useState("8");
  const [launchMonth, setLaunchMonth] = useState("");
  const [conversion, setConversion] = useState("2");
  const [competitor, setCompetitor] = useState<Record<string, string>>({});
  const [audience, setAudience] = useState<Record<string, string>>({});
  const [baseReturn, setBaseReturn] = useState<Record<string, string>>({});
  const [brand, setBrand] = useState("");
  const [brandNotes, setBrandNotes] = useState("");
  const [profile, setProfile] = useState<BrandProfile | null>(null);
  const [regions, setRegions] = useState<RegionCode[]>(["EU", "MENA", "CIS"]);
  const [image, setImage] = useState<{ name: string; dataUrl: string } | null>(null);
  const [resetWorld, setResetWorld] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState<ProgressState | null>(null);
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

  const handlers = (selected: string[]): StreamHandlers => ({
    onProgress: (ev) => setProgress((prev) => applyProgress(prev, ev, selected)),
    onAlive: () => setProgress((prev) => (prev ? { ...prev, lastEventAt: Date.now(), connection: "ok" } : prev)),
    onConnection: (state) => setProgress((prev) => (prev ? { ...prev, connection: state } : prev)),
    onRun: (_id, startedMs) => setProgress((prev) => (prev ? { ...prev, startedAt: startedMs } : prev)),
  });

  // Sayfa yenilense de sunucuda süren koşuya yeniden bağlan
  useEffect(() => {
    const id = savedRun();
    if (!id) return;
    setLoading(true);
    setProgress(initialProgress([], "Önceki koşuya yeniden bağlanılıyor…"));
    resumeRun(id, handlers([]))
      .then((res) => {
        if (res.brand_profile) setProfile(res.brand_profile);
        setResult(res);
        setChartRegion(res.regional_breakdown[0]?.region ?? null);
      })
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
      .finally(() => { setLoading(false); setProgress(null); });
  }, []);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!image) return;
    setLoading(true);
    setError(null);
    setProgress(initialProgress(regions));
    try {
      const res = await predictStream({
        product_name: productName,
        image_base64: image.dataUrl.split(",")[1] ?? "",
        technical_specs: specs,
        unit_cost: unitCost,
        total_production_budget: Math.floor(Number(budget)),
        target_regions: regions,
        brand: brand.trim() || undefined,
        brand_notes: brandNotes.trim() || undefined,
        brand_profile: profile ?? undefined,
        assumptions: {
          launch_month: launchMonth ? Number(launchMonth) : undefined,
          conversion_ceiling_pct: Math.max(0.1, Number(conversion) || 2),
          audience: Object.fromEntries(
            Object.entries(audience).filter(([r, v]) => regions.includes(r as RegionCode) && Number(v) > 0).map(([r, v]) => [r, Math.floor(Number(v))]),
          ),
          competitor_price_usd: Object.fromEntries(
            Object.entries(competitor).filter(([r, v]) => regions.includes(r as RegionCode) && Number(v) > 0).map(([r, v]) => [r, Number(v)]),
          ),
          channel,
          restock_share: Math.min(1, Math.max(0, Number(restock) / 100)),
          reverse_logistics_pct: Math.max(0, Number(logistics) || 0),
          return_base_pct: Object.fromEntries(
            Object.entries(baseReturn).filter(([r, v]) => regions.includes(r as RegionCode) && v !== "" && Number(v) >= 0).map(([r, v]) => [r, Number(v)]),
          ),
        },
        usd_try_rate: regions.includes("TR") && Number(usdTry) > 0 ? Number(usdTry) : undefined,
        reset_world: resetWorld || undefined,
      }, handlers(regions));
      setResetWorld(false);
      if (res.brand_profile) setProfile(res.brand_profile);
      setResult(res);
      setChartRegion(res.regional_breakdown[0]?.region ?? null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
      setProgress(null);
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
            <details className="rounded-md border p-3 text-sm">
              <summary className="cursor-pointer font-medium">Varsayımlar (iade, satış, rakip)</summary>
              <div className="mt-3 grid gap-3">
                <div className="grid gap-1.5">
                  <Label htmlFor="channel">Satış kanalı</Label>
                  <select id="channel" value={channel} onChange={(e) => setChannel(e.target.value as "online" | "store")}
                    className="h-9 rounded-md border bg-transparent px-2 text-sm">
                    <option value="online">Online</option>
                    <option value="store">Mağaza</option>
                  </select>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div className="grid gap-1.5">
                    <Label htmlFor="restock">Yeniden satılabilir iade (%)</Label>
                    <Input id="restock" type="number" min="0" max="100" value={restock} onChange={(e) => setRestock(e.target.value)} />
                  </div>
                  <div className="grid gap-1.5">
                    <Label htmlFor="logi">İade lojistiği (% fiyat)</Label>
                    <Input id="logi" type="number" min="0" max="50" value={logistics} onChange={(e) => setLogistics(e.target.value)} />
                  </div>
                </div>
                <div className="grid gap-1.5">
                  <Label htmlFor="month">Lansman ayı (mevsim uyumu için), boşsa mevsim etkisi yok</Label>
                  <select id="month" value={launchMonth} onChange={(e) => setLaunchMonth(e.target.value)}
                    className="h-9 rounded-md border bg-transparent px-2 text-sm">
                    <option value="">Seçilmedi</option>
                    {["Ocak","Şubat","Mart","Nisan","Mayıs","Haziran","Temmuz","Ağustos","Eylül","Ekim","Kasım","Aralık"].map((m, i) => (
                      <option key={m} value={i + 1}>{m}</option>
                    ))}
                  </select>
                </div>
                <div className="grid gap-1.5">
                  <Label htmlFor="conv">Dönüşüm tavanı (% — ilgili ve fiyatı kabul eden kitlenin alıma dönüşen kısmı)</Label>
                  <Input id="conv" type="number" min="0.1" max="30" step="0.1" value={conversion} onChange={(e) => setConversion(e.target.value)} />
                </div>
                <div className="grid gap-1.5">
                  <Label>120 günde ulaşabileceğin kitle (kişi), boşsa varsayılan</Label>
                  <div className="grid grid-cols-5 gap-2">
                    {regions.map((r) => (
                      <div key={r} className="grid gap-1">
                        <span className="text-center font-mono text-xs">{r}</span>
                        <Input type="number" min="0" placeholder="-" value={audience[r] ?? ""}
                          onChange={(e) => setAudience((p) => ({ ...p, [r]: e.target.value }))} />
                      </div>
                    ))}
                  </div>
                </div>
                <div className="grid gap-1.5">
                  <Label>Rakip ürün fiyatı ($, rakip savunma senaryosu için), boşsa genel varsayım</Label>
                  <div className="grid grid-cols-5 gap-2">
                    {regions.map((r) => (
                      <div key={r} className="grid gap-1">
                        <span className="text-center font-mono text-xs">{r}</span>
                        <Input type="number" min="0" placeholder="-" value={competitor[r] ?? ""}
                          onChange={(e) => setCompetitor((p) => ({ ...p, [r]: e.target.value }))} />
                      </div>
                    ))}
                  </div>
                </div>
                <div className="grid gap-1.5">
                  <Label>Gerçek taban iade oranların (%), boşsa varsayılan</Label>
                  <div className="grid grid-cols-5 gap-2">
                    {regions.map((r) => (
                      <div key={r} className="grid gap-1">
                        <span className="text-center font-mono text-xs">{r}</span>
                        <Input type="number" min="0" max="80" placeholder="-" value={baseReturn[r] ?? ""}
                          onChange={(e) => setBaseReturn((p) => ({ ...p, [r]: e.target.value }))} />
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </details>
            <label className="flex items-start gap-2 rounded-md border p-3 text-sm">
              <Checkbox checked={resetWorld} onCheckedChange={(v) => setResetWorld(v === true)} className="mt-0.5" />
              <span>
                <span className="font-medium">Dünyayı sıfırla ve baştan kur</span>
                <span className="block text-xs text-muted-foreground">
                  Seçili bölgelerin önbellekteki MiroFish dünyasını ve Zep grafiğini siler; ajanlar güncel profil ve
                  promptlarla sıfırdan kurulur (yerel modelde 10-30 dk). Yalnızca bir sonraki koşuda uygulanır.
                </span>
              </span>
            </label>
            <Button type="submit" disabled={!canSubmit || loading}>
              {loading && <Loader2 className="animate-spin" />}
              {loading ? "Ajanlar değerlendiriyor…" : "Simülasyonu çalıştır"}
            </Button>
            {!image && <p className="text-xs text-muted-foreground">Simülasyon için görsel gerekli.</p>}
            {loading && <p className="text-xs text-muted-foreground">İlerleme sağdaki panelde görünür.</p>}
            {error && <p className="text-sm text-destructive">{error}</p>}
          </form>
        </CardContent>
      </Card>

      <section className="grid min-w-0 content-start gap-6">
        {loading && progress && <ProgressPanel progress={progress} />}
        {!result ? (
          loading ? null : (
            <Card className="grid min-h-64 place-items-center text-muted-foreground">
              <p className="p-6 text-center text-sm">Sonuçlar burada görünecek.</p>
            </Card>
          )
        ) : (
          <>
            <SummaryCard result={result} productName={productName} />

            {result.failed_regions.length > 0 && (
              <div className="rounded-md border border-amber-500/40 bg-amber-500/10 p-3 text-sm">
                <p className="font-medium">
                  {result.failed_regions.map((f) => f.region).join(", ")} bölgesi hesaplanamadı (model zaman aşımına uğradı ya da geçerli cevap vermedi).
                </p>
                <p className="text-muted-foreground">
                  Diğer bölgeler gösteriliyor; bütçe yalnızca hesaplanan bölgeler arasında dağıtıldı. Yeniden denemek için
                  modeli ısıtıp tekrar çalıştır veya <code>MIROFISH_BATCH_SIZE</code>/<code>MIROFISH_INTERVIEW_TIMEOUT</code> değerlerini ayarla.
                </p>
                <ul className="mt-1 list-disc pl-5 text-xs text-muted-foreground">
                  {result.failed_regions.map((f) => <li key={f.region}><b>{f.region}:</b> {f.reason}</li>)}
                </ul>
              </div>
            )}
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
              <CardContent className="grid gap-4">
                {chartRow && <VanWestendorpChart result={chartRow} />}
                {chartRow && <PriceZones row={chartRow} />}
              </CardContent>
            </Card>

            {chartRow?.forecast && (
              <Card>
                <CardHeader>
                  <CardTitle>30 / 60 / 90 / 120 gün satış potansiyeli ({chartRow.region})</CardTitle>
                  <CardDescription>Üretim miktarıyla sınırlı; talep skoru ve fiyat kabulü ajanlardan, kitle ve dönüşüm varsayımdır.</CardDescription>
                </CardHeader>
                <CardContent><ForecastCard row={chartRow} /></CardContent>
              </Card>
            )}

            {chartRow?.price_plan && (
              <Card>
                <CardHeader>
                  <CardTitle>Fiyat senaryoları: lansman, ilk kampanya sonrası, stok eritme ({chartRow.region})</CardTitle>
                  <CardDescription>Fiyat kabulü ajan eğrisinden; aşama süreleri varsayım.</CardDescription>
                </CardHeader>
                <CardContent><PricePlanCard row={chartRow} /></CardContent>
              </Card>
            )}

            {(chartRow?.campaigns?.length ?? 0) > 0 && chartRow && (
              <Card>
                <CardHeader>
                  <CardTitle>Kampanya senaryoları ({chartRow.region})</CardTitle>
                  <CardDescription>Hedefe göre bu bölgenin müşterisine uygun yapı: stok eritme, satışı artırma ya da rakibe karşı konum koruma.</CardDescription>
                </CardHeader>
                <CardContent><CampaignsCard row={chartRow} /></CardContent>
              </Card>
            )}

            {chartRow && (chartRow.break_even || chartRow.confidence) && (
              <Card>
                <CardHeader>
                  <CardTitle>Güvenilirlik ve ek analizler ({chartRow.region})</CardTitle>
                  <CardDescription>Güven düzeyi, başa baş noktası, fiyat/maliyet duyarlılığı, beden dağılımı, mevsim uyumu.</CardDescription>
                </CardHeader>
                <CardContent><ExtrasCard row={chartRow} /></CardContent>
              </Card>
            )}

            {chartRow?.returns && (
              <Card>
                <CardHeader>
                  <CardTitle>İade oranı tahmini ({chartRow.region})</CardTitle>
                  <CardDescription>Kalıp, kumaş, kesim ve bölge iade kültürüne göre; kural tabanlı varsayım.</CardDescription>
                </CardHeader>
                <CardContent><ReturnsCard row={chartRow} /></CardContent>
              </Card>
            )}

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

            <RawAnswers groups={[
              ...result.regional_breakdown.map((r) => ({ region: r.region, answers: r.raw_answers ?? [] })),
              ...result.failed_regions.map((f) => ({ region: `${f.region} (hesaplanamadı)`, answers: f.raw_answers ?? [] })),
            ]} />

            <ul className="list-disc space-y-1 pl-5 text-xs text-muted-foreground">
              {(result.methodology_notes ?? []).map((n) => <li key={n}>{n}</li>)}
            </ul>
          </>
        )}
      </section>
    </main>
  );
}
