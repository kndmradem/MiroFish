"""İnsan onayı: kaynağı olmayan tek bilgi bile kalmışsa paket onaylanmaz."""
from datetime import date
from typing import List, Optional

from ..panel.library import ContextPack

_FIELDS = {"inflation_yoy_pct": lambda p: p.macro.inflation_yoy_pct,
           "consumer_confidence": lambda p: p.macro.consumer_confidence,
           "purchasing_power": lambda p: p.macro.purchasing_power,
           "fx_note": lambda p: p.macro.fx_note,
           "season_notes": lambda p: p.season_notes,
           "shopping_notes": lambda p: p.shopping_notes}


class ApprovalError(ValueError):
    pass


def missing_sources(pack: ContextPack) -> List[str]:
    out = [f for f, get in _FIELDS.items() if get(pack) not in (None, "") and not pack.field_sources.get(f)]
    out += [f"trend: {t.note[:50]}" for t in pack.trends if not t.sources]
    out += [f"rakip fiyatı: {c.item[:50]}" for c in pack.competitor_prices if not c.sources]
    return out


def approve(pack: ContextPack, reviewer: str, version: Optional[str] = None, today: Optional[date] = None) -> ContextPack:
    """Onaylı kopya döner: verified=true, onaylayan ve tarih yazılır, sürüm adı '-taslak' ekinden arınır."""
    if not reviewer.strip():
        raise ApprovalError("Onaylayan kişinin adı gerekli")
    missing = missing_sources(pack)
    if missing:
        raise ApprovalError("Kaynağı olmayan bilgi var, önce kaynak ekle ya da sil: " + "; ".join(missing))
    today = today or date.today()
    return pack.model_copy(update={
        "verified": True, "approved_by": reviewer.strip(), "approved_at": today,
        "version": version or pack.version.removesuffix("-taslak"),
        "source": f"Onaylı bağlam paketi ({reviewer.strip()}, {today.isoformat()}); kaynaklar bilgi bazında",
    })
