"""Denetim raporunun Markdown ve HTML hali (kurulum raporu, komut satırı, indirme)."""
import html
from typing import List, Optional, Tuple

from .kurallar import KURALLAR
from .model import DenetimRaporu

ETIKET = {"incelenmeli": "İNCELENMELİ", "uyarılı": "Uyarılı", "temiz": "Temiz"}
RENK = {"hata": "#b91c1c", "uyarı": "#b45309", "bilgi": "#475569"}


def md(rapor: DenetimRaporu, baslik: str = "Mantık denetimi", parcalar: Optional[List[Tuple[str, DenetimRaporu]]] = None,
       not_: str = "") -> str:
    s = rapor.sayilar
    out = [f"# {baslik}", "", f"**Durum: {ETIKET[rapor.durum]}** · {s.get('hata', 0)} hata, {s.get('uyarı', 0)} uyarı, "
           f"{s.get('bilgi', 0)} bilgi", "", rapor.ozet, ""]
    if not_:
        out += [not_, ""]
    for ad, r in parcalar or [("", rapor)]:
        if ad:
            out += [f"## {ad}: {ETIKET[r.durum]}", ""]
        if not r.bulgular:
            out += ["Bulgu yok.", ""]
            continue
        out += ["| Seviye | Kural | Bulgu | Ürün | Dayanak |", "|---|---|---|---|---|"]
        for b in r.bulgular:
            out.append(f"| {b.seviye} | {b.baslik} | {b.mesaj.replace('|', '/')} | {', '.join(b.skus[:4])} | {b.dayanak} |")
        out.append("")
    out += ["## Çalışan kurallar", ""]
    kods = set(rapor.kurallar)
    out += [f"- **{k.baslik}** (`{k.kod}`): {k.aciklama}" for k in KURALLAR if k.kod in kods]
    out += ["", f"_{rapor.sinir}_", ""]
    return "\n".join(out)


def html_(rapor: DenetimRaporu, baslik: str = "Mantık denetimi", parcalar: Optional[List[Tuple[str, DenetimRaporu]]] = None,
          not_: str = "") -> str:
    e = html.escape
    s = rapor.sayilar
    renk = {"incelenmeli": "#b91c1c", "uyarılı": "#b45309", "temiz": "#15803d"}[rapor.durum]
    parts = [f"""<!doctype html><html lang="tr"><head><meta charset="utf-8"><title>{e(baslik)}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>body{{font:14px/1.5 system-ui,sans-serif;max-width:960px;margin:24px auto;padding:0 16px;color:#0f172a}}
.d{{display:inline-block;padding:4px 10px;border-radius:6px;color:#fff;background:{renk};font-weight:600}}
table{{border-collapse:collapse;width:100%;margin:8px 0 20px}}td,th{{border:1px solid #e2e8f0;padding:6px 8px;text-align:left;vertical-align:top}}
th{{background:#f8fafc}}.s{{font-weight:600;white-space:nowrap}}small{{color:#64748b}}</style></head><body>
<h1>{e(baslik)}</h1><p><span class="d">{ETIKET[rapor.durum]}</span> {s.get('hata', 0)} hata · {s.get('uyarı', 0)} uyarı · {s.get('bilgi', 0)} bilgi</p>
<p>{e(rapor.ozet)}</p>"""]
    if not_:
        parts.append(f"<p>{e(not_)}</p>")
    for ad, r in parcalar or [("", rapor)]:
        if ad:
            parts.append(f"<h2>{e(ad)}: {ETIKET[r.durum]}</h2>")
        if not r.bulgular:
            parts.append("<p>Bulgu yok.</p>")
            continue
        parts.append("<table><tr><th>Seviye</th><th>Kural</th><th>Bulgu</th><th>Ürün</th><th>Dayanak</th></tr>")
        for b in r.bulgular:
            parts.append(f"<tr><td class='s' style='color:{RENK[b.seviye]}'>{e(b.seviye)}</td><td>{e(b.baslik)}</td>"
                         f"<td>{e(b.mesaj)}</td><td>{e(', '.join(b.skus[:4]))}</td><td>{e(b.dayanak)}</td></tr>")
        parts.append("</table>")
    parts.append(f"<p><small>{e(rapor.sinir)}</small></p></body></html>")
    return "".join(parts)
