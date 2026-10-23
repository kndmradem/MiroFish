"use client";

import { useState } from "react";
import { AlertTriangle, Loader2, Sparkles } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { fetchBrandProfile, REGIONS, TIER_LABEL, type BrandProfile, type PriceTier } from "@/lib/api";

const SOURCE_LABEL: Record<BrandProfile["source"], string> = {
  llm_knowledge: "Model bilgisi (doğrulanmadı)",
  user_notes: "Senin notların + model bilgisi",
  generic_default: "Nötr varsayılan (marka bilgisi yok)",
};
const CONF_LABEL = { low: "düşük güven", medium: "orta güven", high: "yüksek güven" } as const;

export function SourceBadge({ profile }: { profile: BrandProfile }) {
  const weak = profile.confidence === "low" || profile.source === "generic_default";
  return (
    <div className="grid gap-2">
      <div className="flex flex-wrap gap-1">
        <Badge variant={weak ? "destructive" : "secondary"}>{SOURCE_LABEL[profile.source]}</Badge>
        <Badge variant="outline">{CONF_LABEL[profile.confidence]}</Badge>
        {profile.edited && <Badge variant="outline">elle düzenlendi</Badge>}
      </div>
      {profile.warning && (
        <p className="flex gap-2 rounded-md border border-amber-500/40 bg-amber-500/10 p-2 text-xs">
          <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-amber-600" />
          <span>{profile.warning}</span>
        </p>
      )}
    </div>
  );
}

interface Props {
  brand: string;
  notes: string;
  profile: BrandProfile | null;
  onBrand: (v: string) => void;
  onNotes: (v: string) => void;
  onProfile: (p: BrandProfile | null) => void;
}

export function BrandPanel({ brand, notes, profile, onBrand, onNotes, onProfile }: Props) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function generate() {
    setLoading(true);
    setError(null);
    try {
      onProfile(await fetchBrandProfile(brand.trim(), notes.trim()));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  const edit = (patch: Partial<BrandProfile>) => profile && onProfile({ ...profile, ...patch, edited: true });
  const num = (v: string, fallback: number) => (Number.isFinite(Number(v)) && v !== "" ? Number(v) : fallback);

  return (
    <div className="grid gap-3 rounded-lg border p-3">
      <div className="grid gap-2">
        <Label htmlFor="brand">Marka</Label>
        <div className="flex gap-2">
          <Input id="brand" value={brand} placeholder="ör. Ipekyol, Zara, kendi markan"
            onChange={(e) => { onBrand(e.target.value); onProfile(null); }} />
          <Button type="button" variant="secondary" disabled={!brand.trim() || loading} onClick={generate}>
            {loading ? <Loader2 className="animate-spin" /> : <Sparkles />}
            Profil çıkar
          </Button>
        </div>
        <Textarea rows={2} value={notes} onChange={(e) => { onNotes(e.target.value); onProfile(null); }}
          placeholder="İsteğe bağlı marka notları (müşteri kitlesi, fiyat bandı, konumlandırma…)" />
        {!profile && (
          <p className="text-xs text-muted-foreground">
            Marka yazıp simülasyonu çalıştırırsan profil otomatik çıkarılır. “Profil çıkar” ile önce görüp düzenleyebilirsin.
          </p>
        )}
        {error && <p className="text-xs text-destructive">{error}</p>}
      </div>

      {profile && (
        <div className="grid gap-3 border-t pt-3 text-sm">
          <SourceBadge profile={profile} />
          <div className="grid gap-1">
            <Label className="text-xs">Konumlandırma</Label>
            <Textarea rows={2} value={profile.positioning} onChange={(e) => edit({ positioning: e.target.value })} />
          </div>
          <div className="grid gap-1">
            <Label className="text-xs">Tipik müşteri</Label>
            <Input value={profile.typical_customer} onChange={(e) => edit({ typical_customer: e.target.value })} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="grid gap-1">
              <Label className="text-xs">Fiyat segmenti</Label>
              <select className="h-9 rounded-md border bg-transparent px-2 text-sm" value={profile.price_tier}
                onChange={(e) => edit({ price_tier: e.target.value as PriceTier })}>
                {(Object.keys(TIER_LABEL) as PriceTier[]).map((t) => <option key={t} value={t}>{TIER_LABEL[t]}</option>)}
              </select>
            </div>
            <div className="grid gap-1">
              <Label className="text-xs">Fiyat çarpanı (satış ÷ maliyet)</Label>
              <Input type="number" min="1.2" max="30" step="0.1" value={profile.price_multiple}
                onChange={(e) => edit({ price_multiple: num(e.target.value, profile.price_multiple) })} />
            </div>
            <div className="grid gap-1">
              <Label className="text-xs">Fiyat duyarlılığı: {profile.price_sensitivity.toFixed(2)}</Label>
              <input type="range" min="0" max="1" step="0.05" value={profile.price_sensitivity}
                onChange={(e) => edit({ price_sensitivity: Number(e.target.value) })} />
            </div>
            <div className="grid gap-1">
              <Label className="text-xs">Marka çekim gücü (0-100)</Label>
              <Input type="number" min="0" max="100" value={profile.brand_pull}
                onChange={(e) => edit({ brand_pull: num(e.target.value, profile.brand_pull) })} />
            </div>
            <div className="grid gap-1">
              <Label className="text-xs">Tipik brüt marj (%)</Label>
              <Input type="number" min="10" max="95" value={profile.margin_norm_pct}
                onChange={(e) => edit({ margin_norm_pct: num(e.target.value, profile.margin_norm_pct) })} />
            </div>
          </div>
          <div className="grid gap-1">
            <Label className="text-xs">Bölgesel marka gücü (0-100)</Label>
            <div className="grid grid-cols-5 gap-2">
              {REGIONS.map((r) => (
                <div key={r.code} className="grid gap-1">
                  <span className="text-xs text-muted-foreground">{r.code}</span>
                  <Input type="number" min="0" max="100" className="px-1.5" value={profile.regional_strength[r.code] ?? 50}
                    onChange={(e) => edit({ regional_strength: { ...profile.regional_strength, [r.code]: num(e.target.value, 50) } })} />
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
