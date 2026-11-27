"use client";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { PredictionResponse } from "@/lib/api";

const n = (v: number) => v.toLocaleString("tr-TR");
const OBJ: Record<string, string> = { balanced: "Dengeli (satış hızı)", profit: "Kâr ağırlıklı", blended: "Karışık" };

export function AllocationCard({ result }: { result: PredictionResponse }) {
  const rows = result.regional_breakdown.filter((r) => r.allocation);
  if (!rows.length) return null;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Üretim dağıtımı: önce / sonra</CardTitle>
        <CardDescription>
          Hedef: {OBJ[result.allocation_objective] ?? result.allocation_objective}. &quot;Önce&quot; eski kâr ağırlıklı dağıtımdır;
          satış ve stok rakamları 120 günlük orta senaryo tahminidir (varsayımlara dayanır, ölçülmüş veri değildir).
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4">
        {result.allocation_note && (
          <p className="rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">{result.allocation_note}</p>
        )}
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Bölge</TableHead>
              <TableHead className="text-right">Beklenen talep</TableHead>
              <TableHead className="text-right">Adet (önce → sonra)</TableHead>
              <TableHead className="text-right">Satılan</TableHead>
              <TableHead className="text-right">Kalan stok</TableHead>
              <TableHead className="text-right">Karşılanamayan talep</TableHead>
              <TableHead className="text-right">Satış oranı</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((r) => {
              const a = r.allocation!;
              return (
                <TableRow key={r.region}>
                  <TableCell className="font-medium">{r.region}</TableCell>
                  <TableCell className="text-right tabular-nums">{n(a.demand_units)}</TableCell>
                  <TableCell className="text-right tabular-nums">{n(a.units_before)} → <b>{n(a.units)}</b></TableCell>
                  <TableCell className="text-right tabular-nums">{n(a.sold_before)} → <b>{n(a.sold)}</b></TableCell>
                  <TableCell className="text-right tabular-nums">{n(a.leftover_before)} → <b>{n(a.leftover)}</b></TableCell>
                  <TableCell className="text-right tabular-nums">{n(a.unmet_before)} → <b>{n(a.unmet)}</b></TableCell>
                  <TableCell className="text-right tabular-nums">%{a.sell_through_before_pct} → <b>%{a.sell_through_pct}</b></TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
        <div className="grid gap-2 text-sm">
          {rows.map((r) => (
            <p key={r.region}><Badge variant="secondary" className="mr-2">{r.region}</Badge>{r.allocation!.why}</p>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
