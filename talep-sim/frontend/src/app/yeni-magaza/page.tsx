"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Loader2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { estimateNewStore, fetchLocations, type LocationProfile, type NewStoreCandidate, type NewStoreEstimate } from "@/lib/api";

const usd0 = (v: number) => `$${Math.round(v).toLocaleString("tr-TR")}`;
const OWN_LABEL: Record<NewStoreEstimate["own_data"], string> = {
  "şehir": "bu şehirde kendi mağazan var",
  "ülke": "bu ülkede kendi mağazan var",
  "bölge": "yalnızca aynı bölgede kendi mağazan var",
  yok: "bu bölgede kendi veri yok",
};

/** Yeni bölgede mağaza öngörüsü: dış veri + benzer mevcut mağazalar; belirsizlik açıkça gösterilir. */
export default function NewStorePage() {
  const [locations, setLocations] = useState<LocationProfile[]>([]);
  const [cand, setCand] = useState<NewStoreCandidate>({ ulke: "SA", sehir: "Jeddah", lokasyon_tipi: "avm", metrekare: 400 });
  const [result, setResult] = useState<NewStoreEstimate | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    fetchLocations().then(setLocations).catch((e) => setError(String(e.message ?? e)));
  }, []);

  async function run() {
    setBusy(true);
    setError(null);
    try {
      setResult(await estimateNewStore(cand));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const noOwn = result && (result.own_data === "yok" || result.own_data === "bölge");
  return (
    <main className="mx-auto grid max-w-5xl gap-4 p-4">
      <div>
        <h1 className="text-xl font-semibold">Yeni bölgede mağaza öngörüsü</h1>
        <p className="text-sm text-muted-foreground">
          Aday lokasyonun dış verisi, mevcut mağazalarının satışıyla eşleştirilir. Sonuç bir benzerlik tahminidir, ölçülmüş satış değildir.{" "}
          <Link className="underline" href="/">Talep simülasyonuna dön</Link>
        </p>
      </div>
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Aday lokasyon</CardTitle>
          <CardDescription>Listede olmayan şehir için dış veri yoksa eşleştirme yalnızca lokasyon tipine dayanır.</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3 sm:grid-cols-5">
          <div className="grid gap-1">
            <Label htmlFor="ulke">Ülke kodu</Label>
            <Input id="ulke" value={cand.ulke} onChange={(e) => setCand({ ...cand, ulke: e.target.value.toUpperCase() })} />
          </div>
          <div className="grid gap-1 sm:col-span-2">
            <Label htmlFor="sehir">Şehir</Label>
            <Input id="sehir" list="sehirler" value={cand.sehir} onChange={(e) => {
              const loc = locations.find((l) => l.sehir === e.target.value);
              setCand({ ...cand, sehir: e.target.value, ulke: loc ? loc.ulke : cand.ulke });
            }} />
            <datalist id="sehirler">
              {locations.map((l) => <option key={`${l.ulke}-${l.sehir}`} value={l.sehir}>{l.ulke}</option>)}
            </datalist>
          </div>
          <div className="grid gap-1">
            <Label htmlFor="tip">Lokasyon tipi</Label>
            <select id="tip" className="h-9 rounded-md border bg-transparent px-2 text-sm" value={cand.lokasyon_tipi}
              onChange={(e) => setCand({ ...cand, lokasyon_tipi: e.target.value as NewStoreCandidate["lokasyon_tipi"] })}>
              <option value="avm">AVM</option><option value="cadde">Cadde</option><option value="outlet">Outlet</option>
            </select>
          </div>
          <div className="grid gap-1">
            <Label htmlFor="m2">Metrekare</Label>
            <Input id="m2" type="number" value={cand.metrekare} onChange={(e) => setCand({ ...cand, metrekare: Number(e.target.value) })} />
          </div>
          <div className="sm:col-span-5">
            <Button onClick={run} disabled={busy}>{busy && <Loader2 className="mr-2 size-4 animate-spin" />}Öngör</Button>
          </div>
        </CardContent>
      </Card>
      {error && <p className="rounded-md border border-red-500/40 bg-red-500/10 p-2 text-sm">{error}</p>}
      {result && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              Yıllık ciro tahmini: {usd0(result.low_usd)} – {usd0(result.high_usd)}
            </CardTitle>
            <CardDescription>
              Orta değer {usd0(result.annual_revenue_usd)} (m² başı {usd0(result.per_sqm_usd)}). Aralığın tamamı birlikte okunmalı.
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3 text-sm">
            <div className="flex flex-wrap gap-2">
              <Badge variant={result.confidence === "düşük" ? "destructive" : "secondary"}>Güven: {result.confidence}</Badge>
              <Badge variant={noOwn ? "destructive" : "outline"}>{OWN_LABEL[result.own_data]}</Badge>
              {result.region && <Badge variant="outline">Bölge: {result.region}</Badge>}
            </div>
            {noOwn && (
              <p className="rounded-md border border-amber-500/50 bg-amber-500/10 p-2 font-medium">
                {result.own_data === "yok" ? "Bu bölgede kendi veri yok." : "Bu ülkede kendi veri yok."} Tahmin başka pazarlardaki
                mağazalarından aktarılıyor; aralık bu yüzden genişletildi. Açılış kararından önce pilot ya da pazar araştırmasıyla doğrula.
              </p>
            )}
            {result.warnings.length > 0 && (
              <ul className="list-disc pl-5 text-amber-700">{result.warnings.map((w) => <li key={w}>{w}</li>)}</ul>
            )}
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Benzer mağaza</TableHead><TableHead>Şehir</TableHead><TableHead>Tip</TableHead>
                    <TableHead>m²</TableHead><TableHead>Yıllık ciro</TableHead><TableHead>m² başı</TableHead><TableHead>Benzerlik</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {result.analogs.map((a) => (
                    <TableRow key={a.magaza}>
                      <TableCell className="font-mono">{a.magaza}{a.kapandi ? " (kapandı)" : ""}</TableCell>
                      <TableCell>{a.sehir}, {a.ulke}</TableCell><TableCell>{a.lokasyon_tipi}</TableCell><TableCell>{a.metrekare}</TableCell>
                      <TableCell>{usd0(a.yillik_ciro_usd)}</TableCell><TableCell>{usd0(a.m2_ciro_usd)}</TableCell>
                      <TableCell>{a.benzerlik.toFixed(2)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
            <p className="text-xs text-muted-foreground">
              Dayanak: {result.basis}. Karşılaştırılan dış veri: {result.features_used.join(", ") || "yok"}. Profil kaynağı: {result.profile_source}.
            </p>
            <ul className="list-disc pl-5 text-xs text-muted-foreground">{result.assumptions.map((a) => <li key={a}>{a}</li>)}</ul>
          </CardContent>
        </Card>
      )}
    </main>
  );
}
