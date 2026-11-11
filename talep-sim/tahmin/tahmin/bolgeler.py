"""Ülke -> bölge eşlemesi (talep-sim MVP'sindeki bölgelerle aynı: TR, EU, MENA, CIS, US).

Liste genişletilebilir; listede olmayan ülke 'DIGER' olur. Müşteri kendi bölgelemesini
magazalar.musteri_bolgesi ile verirse raporlarda o da kullanılabilir.
"""
from __future__ import annotations

ULKE_BOLGE: dict[str, str] = {
    "TR": "TR",
    **{u: "EU" for u in ("DE", "NL", "FR", "BE", "AT", "IT", "ES", "PL", "RO", "BG", "GR", "SE", "DK", "CH", "GB", "CZ", "HU", "PT", "IE")},
    **{u: "MENA" for u in ("AE", "SA", "QA", "KW", "BH", "OM", "EG", "MA", "JO", "LB", "IQ", "DZ", "TN", "LY")},
    **{u: "CIS" for u in ("KZ", "AZ", "UZ", "RU", "UA", "BY", "GE", "AM", "KG", "TM", "TJ", "MD")},
    **{u: "US" for u in ("US", "CA")},
}

BOLGELER = ("TR", "EU", "MENA", "CIS", "US")


def bolge(ulke: str | None) -> str:
    if not ulke:
        return "DIGER"
    return ULKE_BOLGE.get(str(ulke).upper(), "DIGER")
