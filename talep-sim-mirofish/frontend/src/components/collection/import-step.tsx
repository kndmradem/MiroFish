"use client";

import { useMemo, useState } from "react";
import { AlertTriangle, CheckCircle2, CircleHelp, Download, FileSpreadsheet, FolderOpen, Images, Loader2, XCircle } from "lucide-react";

import { BrandPanel } from "@/components/brand-panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { REGIONS, type RegionCode } from "@/lib/api";
import {
  confirmCollection, imageUrl, importCollection, templateUrl,
  type Collection, type CollectionItem, type CollectionMeta, type ImportPreview, type ItemPreview, type Kind,
} from "@/lib/collection-api";
import { cn } from "@/lib/utils";

const STATUS_ICON = {
  ok: <CheckCircle2 className="size-4 text-emerald-600" />,
  "uyarı": <AlertTriangle className="size-4 text-amber-600" />,
  hata: <XCircle className="size-4 text-rose-600" />,
  belirsiz: <CircleHelp className="size-4 text-sky-600" />,
};

/** 1. adım: Excel + görselleri yükle. 2. adım: önizlemede düzelt ve kaydet. */
export function ImportStep({ kind, onSaved }: { kind: Kind; onSaved: (c: Collection) => void }) {
  const [sheet, setSheet] = useState<File | null>(null);
  const [images, setImages] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<ImportPreview | null>(null);

  async function upload(extraOnly = false) {
    if (!sheet) return;
    setBusy(true);
    setError(null);
    try {
      setPreview(await importCollection(sheet, images, extraOnly ? preview?.collection_id : undefined, kind));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid gap-4">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">1. {kind === "bagimsiz" ? "Ürünleri yükle" : "Koleksiyonu yükle"}</CardTitle>
          <CardDescription>
            Ürün bilgilerinin olduğu Excel ile görselleri birlikte yükleyin. Excel&apos;de her ürün için ürün adı, SKU, kategori,
            ürün içeriği (kumaş/kompozisyon) ve maliyet fiyatı olmalı; satış fiyatı yazılmaz, sistem önerir. Görseller dosya adındaki
            SKU ile ya da Excel&apos;deki görsel sütunuyla eşleşir. Hiçbir şey onayınız olmadan kaydedilmez.{" "}
            <a className="inline-flex items-center gap-1 underline" href={templateUrl}><Download className="size-3" />Toplu yükleme şablonu (koleksiyon ve bağımsız ürünler için aynı)</a>
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4 md:grid-cols-2">
          <label className={cn("flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed p-5 text-center text-sm text-muted-foreground",
            sheet && "border-emerald-400 bg-emerald-50/50")}>
            <FileSpreadsheet className="size-7" />
            <span>{sheet ? <b className="text-foreground">{sheet.name}</b> : "Ürün listesi (.xlsx ya da .csv)"}</span>
            <input type="file" accept=".xlsx,.xlsm,.csv" className="hidden" onChange={(e) => setSheet(e.target.files?.[0] ?? null)} />
          </label>
          <div className={cn("flex flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed p-5 text-center text-sm text-muted-foreground",
            images.length > 0 && "border-emerald-400 bg-emerald-50/50")}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => { e.preventDefault(); setImages(Array.from(e.dataTransfer.files)); }}>
            <Images className="size-7" />
            <span>{images.length ? <b className="text-foreground">{images.length} dosya seçildi</b> : "Görseller (JPG, PNG, WEBP ya da zip)"}</span>
            <div className="flex flex-wrap justify-center gap-2">
              <label className="cursor-pointer rounded-md border bg-background px-2 py-1 text-xs text-foreground hover:bg-muted">
                Dosya seç
                <input type="file" multiple accept="image/jpeg,image/png,image/webp,.zip" className="hidden"
                  onChange={(e) => setImages(Array.from(e.target.files ?? []))} />
              </label>
              <label className="inline-flex cursor-pointer items-center gap-1 rounded-md border bg-background px-2 py-1 text-xs text-foreground hover:bg-muted">
                <FolderOpen className="size-3" />Klasör seç
                <input type="file" multiple className="hidden"
                  // @ts-expect-error tarayıcıya özgü klasör seçimi
                  webkitdirectory="" directory=""
                  onChange={(e) => setImages(Array.from(e.target.files ?? []))} />
              </label>
            </div>
          </div>
          <div className="flex items-center gap-3 md:col-span-2">
            <Button onClick={() => upload()} disabled={!sheet || busy}>
              {busy && <Loader2 className="size-4 animate-spin" />}Yükle ve kontrol et
            </Button>
            {preview && images.length > 0 && (
              <Button variant="outline" onClick={() => upload(true)} disabled={busy}>Görselleri bu taslağa ekle</Button>
            )}
            {error && <span className="text-sm text-rose-600">{error}</span>}
          </div>
        </CardContent>
      </Card>
      {preview && <PreviewStep key={preview.collection_id + preview.items.length + preview.counts.images} kind={kind} preview={preview} onSaved={onSaved} />}
    </div>
  );
}

function PreviewStep({ kind, preview, onSaved }: { kind: Kind; preview: ImportPreview; onSaved: (c: Collection) => void }) {
  const [meta, setMeta] = useState<CollectionMeta>({ ...preview.meta, kind });
  const [rows, setRows] = useState<(ItemPreview & { include: boolean })[]>(
    preview.items.map((p) => ({ ...p, include: p.status !== "hata" || (!!p.item.sku && !!p.item.name && p.item.images.length > 0 && !!p.item.unit_cost) })),
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);
  const linked = useMemo(() => new Set(rows.flatMap((r) => r.item.images)), [rows]);
  const freeImages = useMemo(() => {
    const all = [...preview.orphans.map((o) => o.file), ...preview.items.flatMap((p) => p.candidates)];
    return Array.from(new Set(all)).filter((f) => !linked.has(f));
  }, [preview, linked]);
  const skuCount = useMemo(() => {
    const m: Record<string, number> = {};
    rows.filter((r) => r.include).forEach((r) => { m[r.item.sku] = (m[r.item.sku] ?? 0) + 1; });
    return m;
  }, [rows]);

  const setItem = (i: number, patch: Partial<CollectionItem>) =>
    setRows((prev) => prev.map((r, j) => (j === i ? { ...r, item: { ...r.item, ...patch } } : r)));
  const attach = (file: string, sku: string) =>
    setRows((prev) => prev.map((r) => (r.item.sku === sku ? { ...r, item: { ...r.item, images: [...r.item.images, file] } } : r)));

  const included = rows.filter((r) => r.include);
  const problems = included.filter((r) => !r.item.sku || !r.item.name || r.item.images.length === 0 || !r.item.unit_cost || skuCount[r.item.sku] > 1);
  const noSpecs = included.filter((r) => !r.item.technical_specs).length;
  const toggleRegion = (code: RegionCode, on: boolean) =>
    setMeta((m) => ({ ...m, target_regions: on ? [...m.target_regions, code] : m.target_regions.filter((r) => r !== code) }));

  async function save() {
    setBusy(true);
    setError(null);
    try {
      onSaved(await confirmCollection(preview.collection_id, meta, included.map((r) => r.item)));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const c = preview.counts;
  const issues = showAll ? preview.issues : preview.issues.filter((i) => i.level !== "bilgi").slice(0, 12);
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">2. Kontrol et ve kaydet</CardTitle>
        <CardDescription className="flex flex-wrap gap-2">
          <Badge variant="outline">{c.rows ?? 0} ürün satırı</Badge>
          <Badge variant="outline" className="border-emerald-300 text-emerald-800">{c.ok ?? 0} sorunsuz</Badge>
          {!!c.warn && <Badge variant="outline" className="border-amber-300 text-amber-800">{c.warn} uyarılı</Badge>}
          {!!c.error && <Badge variant="outline" className="border-rose-300 text-rose-800">{c.error} hatalı</Badge>}
          {!!c.ambiguous && <Badge variant="outline" className="border-sky-300 text-sky-800">{c.ambiguous} belirsiz görsel</Badge>}
          <Badge variant="outline">{c.images ?? 0} görsel, {c.orphans ?? 0} sahipsiz</Badge>
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-5">
        <div className="grid gap-3 rounded-lg border p-3 md:grid-cols-4">
          <div className="grid gap-1 md:col-span-2"><Label>{kind === "bagimsiz" ? "Liste adı" : "Koleksiyon adı"}</Label>
            <Input value={meta.name} onChange={(e) => setMeta({ ...meta, name: e.target.value })} /></div>
          <div className="grid gap-1 md:col-span-2"><Label>Sezon</Label>
            <Input value={meta.season} onChange={(e) => setMeta({ ...meta, season: e.target.value })} /></div>
          <div className="grid gap-1"><Label>Toplam üretim bütçesi</Label>
            <Input type="number" value={meta.total_budget ?? ""} onChange={(e) => setMeta({ ...meta, total_budget: e.target.value ? Number(e.target.value) : null })} /></div>
          <div className="grid gap-1"><Label>Para birimi</Label>
            <select className="h-9 rounded-md border bg-background px-2 text-sm" value={meta.currency}
              onChange={(e) => setMeta({ ...meta, currency: e.target.value as "TRY" | "USD" })}>
              <option value="TRY">TRY</option><option value="USD">USD</option>
            </select></div>
          <div className="grid gap-1"><Label>USD/TRY kuru (boşsa varsayılan)</Label>
            <Input type="number" value={meta.usd_try_rate ?? ""} onChange={(e) => setMeta({ ...meta, usd_try_rate: e.target.value ? Number(e.target.value) : null })} /></div>
          <div className="grid gap-1"><Label>Kanal</Label>
            <select className="h-9 rounded-md border bg-background px-2 text-sm" value={meta.channel}
              onChange={(e) => setMeta({ ...meta, channel: e.target.value as "online" | "store" })}>
              <option value="online">Online</option><option value="store">Mağaza</option>
            </select></div>
          <div className="md:col-span-4">
            <BrandPanel brand={meta.brand ?? ""} notes={meta.brand_notes ?? ""} profile={meta.brand_profile ?? null}
              onBrand={(v) => setMeta((m) => ({ ...m, brand: v || null }))}
              onNotes={(v) => setMeta((m) => ({ ...m, brand_notes: v }))}
              onProfile={(p) => setMeta((m) => ({ ...m, brand_profile: p }))} />
          </div>
          <div className="grid gap-2 md:col-span-4"><Label>Hedef bölgeler</Label>
            <div className="flex flex-wrap gap-4">
              {REGIONS.map((r) => (
                <label key={r.code} className="flex items-center gap-2 text-sm">
                  <Checkbox checked={meta.target_regions.includes(r.code)} onCheckedChange={(v) => toggleRegion(r.code, v === true)} />{r.label}
                </label>
              ))}
            </div></div>
        </div>

        <div className="overflow-x-auto rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-8">Dahil</TableHead>
                <TableHead className="w-8" />
                <TableHead>Görsel</TableHead>
                <TableHead>SKU</TableHead>
                <TableHead>Ürün</TableHead>
                <TableHead>Kategori</TableHead>
                <TableHead>Ürün içeriği</TableHead>
                <TableHead className="text-right">Maliyet fiyatı</TableHead>
                <TableHead>Eşleşme</TableHead>
                <TableHead>Sorun</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((r, i) => {
                const rowIssues = preview.issues.filter((x) => x.row === r.row && x.level !== "bilgi");
                const dup = r.include && skuCount[r.item.sku] > 1;
                return (
                  <TableRow key={`${r.row}-${i}`} className={cn(!r.include && "opacity-45")}>
                    <TableCell><Checkbox checked={r.include} onCheckedChange={(v) => setRows((p) => p.map((x, j) => (j === i ? { ...x, include: v === true } : x)))} /></TableCell>
                    <TableCell>{STATUS_ICON[r.item.images.length === 0 && r.status !== "hata" ? "belirsiz" : r.status]}</TableCell>
                    <TableCell>
                      <div className="flex gap-1">
                        {r.item.images.slice(0, 3).map((im) => (
                          // eslint-disable-next-line @next/next/no-img-element
                          <img key={im} src={imageUrl(preview.collection_id, im)} alt={im} title={im} className="size-10 rounded object-cover" />
                        ))}
                        {r.item.images.length > 3 && <span className="text-xs text-muted-foreground">+{r.item.images.length - 3}</span>}
                        {r.item.images.length === 0 && (
                          <select className="h-8 max-w-40 rounded-md border bg-background px-1 text-xs" value=""
                            onChange={(e) => e.target.value && setItem(i, { images: [e.target.value] })}>
                            <option value="">Görsel seç…</option>
                            {[...r.candidates, ...freeImages.filter((f) => !r.candidates.includes(f))].map((f) => <option key={f} value={f}>{f}</option>)}
                          </select>
                        )}
                      </div>
                    </TableCell>
                    <TableCell className={cn("font-mono text-xs", dup && "text-rose-600")}>{r.item.sku || "—"}</TableCell>
                    <TableCell><Input className="h-8 min-w-36" value={r.item.name} onChange={(e) => setItem(i, { name: e.target.value })} /></TableCell>
                    <TableCell><Input className="h-8 min-w-28" value={r.item.category} onChange={(e) => setItem(i, { category: e.target.value })} /></TableCell>
                    <TableCell><Input className="h-8 min-w-44" value={r.item.technical_specs} placeholder="kumaş / kompozisyon"
                      onChange={(e) => setItem(i, { technical_specs: e.target.value })} /></TableCell>
                    <TableCell><Input className={cn("h-8 w-24 text-right", r.include && !r.item.unit_cost && "border-rose-400")} type="number" value={r.item.unit_cost ?? ""}
                      onChange={(e) => setItem(i, { unit_cost: e.target.value ? Number(e.target.value) : null })} /></TableCell>
                    <TableCell className="text-xs text-muted-foreground">{r.match_rule || (r.item.images.length ? "elle" : "—")}</TableCell>
                    <TableCell className="max-w-72 text-xs">
                      {dup && <div className="text-rose-700">Aynı SKU birden fazla dahil satırda</div>}
                      {rowIssues.map((x, k) => <div key={k} className={x.level === "hata" ? "text-rose-700" : "text-amber-700"}>{x.message}</div>)}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>

        {freeImages.length > 0 && (
          <div className="grid gap-2">
            <Label>Sahipsiz görseller</Label>
            <div className="flex flex-wrap gap-3">
              {freeImages.map((f) => {
                const o = preview.orphans.find((x) => x.file === f);
                return (
                  <div key={f} className="flex items-center gap-2 rounded-md border p-1.5 text-xs">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src={imageUrl(preview.collection_id, f)} alt={f} className="size-9 rounded object-cover" />
                    <span className="max-w-40 truncate" title={f}>{f}</span>
                    <select className="h-7 rounded border bg-background px-1" value="" onChange={(e) => e.target.value && attach(f, e.target.value)}>
                      <option value="">{o?.suggestion ? `Bağla (öneri: ${o.suggestion})` : "Ürüne bağla…"}</option>
                      {o?.suggestion && <option value={o.suggestion}>{o.suggestion}</option>}
                      {rows.filter((r) => r.item.sku && r.item.sku !== o?.suggestion).map((r) => <option key={r.row} value={r.item.sku}>{r.item.sku} · {r.item.name}</option>)}
                    </select>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {preview.issues.length > 0 && (
          <div className="grid gap-1 rounded-lg bg-muted/50 p-3 text-xs">
            {issues.map((x, k) => (
              <div key={k} className={x.level === "hata" ? "text-rose-700" : x.level === "uyarı" ? "text-amber-800" : "text-muted-foreground"}>
                {x.row ? `Satır ${x.row}${x.sku ? ` (${x.sku})` : ""}: ` : ""}{x.message}
              </div>
            ))}
            <button className="w-fit underline" onClick={() => setShowAll((v) => !v)}>
              {showAll ? "Daha az göster" : `Bütün notlar (${preview.issues.length})`}
            </button>
          </div>
        )}

        <div className="flex flex-wrap items-center gap-3">
          <Button onClick={save} disabled={busy || included.length === 0 || problems.length > 0 || meta.target_regions.length === 0}>
            {busy && <Loader2 className="size-4 animate-spin" />}{included.length} ürünü kaydet
          </Button>
          {problems.length > 0 && <span className="text-sm text-rose-600">{problems.length} dahil satırda SKU, ad, maliyet fiyatı ya da görsel eksik veya SKU tekrarlı; düzeltin ya da dahil etmeyin.</span>}
          {noSpecs > 0 && problems.length === 0 && <span className="text-sm text-amber-700">{noSpecs} üründe ürün içeriği boş: panel yalnızca görsel ve addan değerlendirir.</span>}
          {error && <span className="text-sm text-rose-600">{error}</span>}
        </div>
      </CardContent>
    </Card>
  );
}
