"""Mantık denetimi: her koşunun sonucunda çalışan, marka/ürün listesi içermeyen genel tutarlılık kuralları.

    from app.denetim import denetle_koleksiyon, denetle_tahmin, denetle_urunler

Bulgular hata / uyarı / bilgi seviyesindedir; en az bir hata varsa rapor durumu 'incelenmeli' olur.
Komut satırı: python -m app.denetim --help
"""
from typing import Any, Dict, Iterable, List, Optional

from .kurallar import KURALLAR, Sonuc
from .model import SIRA, Bulgu, DenetimRaporu

SURUM = "1"


def _calistir(kapsam: str, veri: Dict[str, Any], ek: Optional[Dict[str, Any]] = None) -> DenetimRaporu:
    s = Sonuc(kapsam=kapsam, veri=veri, ek=ek or {})
    bulgular: List[Bulgu] = []
    calisan: List[str] = []
    for k in KURALLAR:
        if kapsam not in k.kapsam:
            continue
        calisan.append(k.kod)
        try:
            bulgular += list(k.fn(s))
        except Exception as e:  # bir kuralın çökmesi sonucu gizlemesin, kendisi bulgu olsun
            bulgular.append(Bulgu(seviye="uyarı", kural=k.kod, baslik=k.baslik,
                                  mesaj=f"Kural çalışırken hata verdi ({type(e).__name__}: {e}); bu kontrol yapılamadı."))
    # aynı mesaj iki kez gelmesin
    tekil, gor = [], set()
    for b in bulgular:
        anahtar = (b.seviye, b.kural, b.mesaj)
        if anahtar not in gor:
            gor.add(anahtar)
            tekil.append(b)
    tekil.sort(key=lambda b: (SIRA[b.seviye], b.kural))
    return rapor_olustur(tekil, calisan, kapsam)


def rapor_olustur(bulgular: List[Bulgu], kurallar: Iterable[str], kapsam: str) -> DenetimRaporu:
    say = {s: sum(1 for b in bulgular if b.seviye == s) for s in ("hata", "uyarı", "bilgi")}
    durum = "incelenmeli" if say["hata"] else "uyarılı" if say["uyarı"] else "temiz"
    if durum == "incelenmeli":
        ozet = (f"{say['hata']} mantık hatası bulundu. Bu sonuç incelenmeden müşteriye gösterilmemeli.")
    elif durum == "uyarılı":
        ozet = f"Hata yok; {say['uyarı']} uyarı var. Sunarken uyarıları açıklayın."
    else:
        ozet = "Otomatik kurallar bir tutarsızlık bulmadı."
    return DenetimRaporu(durum=durum, ozet=ozet, sayilar=say, bulgular=bulgular, kurallar=list(kurallar), kapsam=kapsam, surum=SURUM)


def _dict(x: Any) -> Dict[str, Any]:
    if hasattr(x, "model_dump"):
        return x.model_dump(mode="json", exclude={"denetim"})
    return {k: v for k, v in dict(x).items() if k != "denetim"}


def denetle_koleksiyon(sonuc: Any) -> DenetimRaporu:
    """CollectionResult (ya da sözlük hali) üzerinde koleksiyon kuralları."""
    return _calistir("koleksiyon", _dict(sonuc))


def denetle_tahmin(yanit: Any, unit_cost: Optional[float] = None, budget: Optional[float] = None) -> DenetimRaporu:
    """Tekli ürün tahmini (PredictionResponse) üzerinde kurallar. Maliyet ve bütçe istekten gelir (USD)."""
    return _calistir("tekli", _dict(yanit), {"unit_cost": float(unit_cost) if unit_cost else None,
                                            "budget": float(budget) if budget else None})


def denetle_urunler(items: List[Any], issues: Optional[List[Any]] = None) -> DenetimRaporu:
    """Müşterinin ürün listesi (Excel içe aktarma) üzerinde veri kuralları. issues: içe aktarıcının kendi bulguları."""
    its = [_dict(i) for i in items]
    iss = [_dict(i) for i in issues or []]
    return _calistir("veri", {"items": its}, {"issues": iss})


def kural_listesi() -> List[dict]:
    return [{"kod": k.kod, "kapsam": list(k.kapsam), "baslik": k.baslik, "aciklama": k.aciklama} for k in KURALLAR]


__all__ = ["Bulgu", "DenetimRaporu", "denetle_koleksiyon", "denetle_tahmin", "denetle_urunler", "rapor_olustur",
           "kural_listesi", "KURALLAR", "SURUM"]
