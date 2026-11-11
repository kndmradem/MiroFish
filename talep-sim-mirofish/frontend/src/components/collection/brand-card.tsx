"use client";

import { useState } from "react";
import { Loader2 } from "lucide-react";

import { BrandPanel } from "@/components/brand-panel";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { updateMeta, type Collection } from "@/lib/collection-api";

/** Kayıtlı koleksiyonun markası: tekli moddaki gibi gir, profil çıkar, düzenle. Ekrandaki giriş Excel'dekine baskındır. */
export function BrandCard({ col, onSaved }: { col: Collection; onSaved: (c: Collection) => void }) {
  const [brand, setBrand] = useState(col.meta.brand ?? "");
  const [notes, setNotes] = useState(col.meta.brand_notes ?? "");
  const [profile, setProfile] = useState(col.meta.brand_profile ?? null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const dirty = brand !== (col.meta.brand ?? "") || notes !== (col.meta.brand_notes ?? "")
    || JSON.stringify(profile) !== JSON.stringify(col.meta.brand_profile ?? null);

  async function save() {
    setBusy(true);
    setError(null);
    try {
      onSaved(await updateMeta(col.id, { ...col.meta, brand: brand.trim() || null, brand_notes: notes, brand_profile: profile }));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Marka</CardTitle>
        <CardDescription>
          Marka değeri fiyatı doğrudan etkiler: panelin gördüğü fiyat basamakları ve &quot;bu marka genelde şu fiyata satar&quot; bilgisi
          bu profilden kurulur. Profili çıkarıp düzenleyebilirsiniz; değiştirirseniz ürünler yeniden sorulur. Marka boşsa nötr varsayım kullanılır.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-3">
        <BrandPanel brand={brand} notes={notes} profile={profile} onBrand={setBrand} onNotes={setNotes} onProfile={setProfile} />
        <div className="flex items-center gap-3">
          <Button onClick={save} disabled={!dirty || busy} variant={dirty ? "default" : "outline"}>
            {busy && <Loader2 className="size-4 animate-spin" />}Markayı kaydet
          </Button>
          {dirty && <span className="text-xs text-amber-700">Kaydedilmemiş değişiklik var.</span>}
          {error && <span className="text-sm text-rose-600">{error}</span>}
        </div>
      </CardContent>
    </Card>
  );
}
