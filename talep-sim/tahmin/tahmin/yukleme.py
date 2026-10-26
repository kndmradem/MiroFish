"""CSV klasörünü sözleşmedeki tiplerle DataFrame'lere yükler."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from .sozlesme import TABLO, TABLOLAR, Tip

EVET = {"evet", "e", "1", "true", "yes", "y"}
HAYIR = {"hayir", "hayır", "h", "0", "false", "no", "n"}


_BOS_TIP = {Tip.METIN: "string", Tip.TAMSAYI: "Int64", Tip.ONDALIK: "Float64", Tip.TARIH: "datetime64[ns]", Tip.EVET_HAYIR: "boolean"}


@dataclass
class VeriSeti:
    klasor: Path
    tablolar: dict[str, pd.DataFrame] = field(default_factory=dict)
    # tablo -> alan -> çevrilemeyen (boş olmayan) değer sayısı
    cevrim_hatalari: dict[str, dict[str, int]] = field(default_factory=dict)
    eksik_alanlar: dict[str, list[str]] = field(default_factory=dict)

    def __getitem__(self, ad: str) -> pd.DataFrame:
        return self.tablolar[ad]

    def __contains__(self, ad: str) -> bool:
        return ad in self.tablolar

    def get(self, ad: str) -> pd.DataFrame | None:
        return self.tablolar.get(ad)


def _dosya_bul(klasor: Path, tablo: str) -> Path | None:
    for uzanti in (".csv", ".csv.gz"):
        p = klasor / f"{tablo}{uzanti}"
        if p.exists():
            return p
    return None


def tiplere_cevir(df: pd.DataFrame, tablo: str) -> tuple[pd.DataFrame, dict[str, int]]:
    hatalar: dict[str, int] = {}
    t = TABLO[tablo]
    df = df.copy()
    for a in t.alanlar:
        if a.ad not in df.columns:
            continue
        ham = df[a.ad]
        bos = ham.isna() | (ham.astype(str).str.strip() == "")
        if a.tip == Tip.METIN:
            df[a.ad] = ham.where(~bos, None).astype("string").str.strip()
            continue
        if a.tip == Tip.TARIH:
            cevrilmis = pd.to_datetime(ham.where(~bos), errors="coerce", format="ISO8601")
        elif a.tip in (Tip.TAMSAYI, Tip.ONDALIK):
            metin = ham.where(~bos).astype("string").str.replace(",", ".", regex=False)
            cevrilmis = pd.to_numeric(metin, errors="coerce")
            if a.tip == Tip.TAMSAYI:
                tam_degil = cevrilmis.notna() & (cevrilmis % 1 != 0)
                hatalar[a.ad] = int(tam_degil.sum())
                cevrilmis = cevrilmis.where(~tam_degil).astype("Int64")
        else:  # EVET_HAYIR
            k = ham.where(~bos).astype("string").str.strip().str.lower()
            cevrilmis = pd.Series(pd.NA, index=df.index, dtype="boolean")
            cevrilmis[k.isin(EVET).fillna(False)] = True
            cevrilmis[k.isin(HAYIR).fillna(False)] = False
        hatali = int((cevrilmis.isna() & ~bos).sum())
        hatalar[a.ad] = hatalar.get(a.ad, 0) + hatali
        df[a.ad] = cevrilmis
    return df, {k: v for k, v in hatalar.items() if v}


def yukle(klasor: str | Path, tablolar: list[str] | None = None) -> VeriSeti:
    klasor = Path(klasor)
    vs = VeriSeti(klasor=klasor)
    for t in TABLOLAR:
        if tablolar is not None and t.ad not in tablolar:
            continue
        p = _dosya_bul(klasor, t.ad)
        if p is None:
            continue
        ham = pd.read_csv(p, dtype=str, keep_default_na=False, na_values=[""])
        ham.columns = [c.strip().lower() for c in ham.columns]
        vs.eksik_alanlar[t.ad] = [a for a in t.zorunlu_alanlar if a not in ham.columns]
        df, hatalar = tiplere_cevir(ham, t.ad)
        # opsiyonel alanlar dosyada yoksa boş kolon olarak eklenir; sonraki adımlar her alanın var olduğunu varsayabilir
        for a in t.alanlar:
            if a.ad not in df.columns:
                df[a.ad] = pd.Series(pd.NA, index=df.index, dtype=_BOS_TIP[a.tip])
        vs.tablolar[t.ad] = df
        if hatalar:
            vs.cevrim_hatalari[t.ad] = hatalar
    return vs
