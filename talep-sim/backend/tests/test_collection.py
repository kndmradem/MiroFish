import io
import json
import time

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook
from PIL import Image

from app.collection import routes
from app.collection.importer import ImageInfo, build_preview, match_images, read_workbook, template_bytes
from app.collection.models import Collection, CollectionItem, CollectionMeta, WhatIf
from app.collection.store import CollectionStore
from app.collection.summary import allocate_items, summarize
from app.main import app, get_engine

from .test_panel import make_engine


def xlsx(items, meta=None, item_headers=None) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Ürünler"
    ws.append(item_headers or ["SKU", "Ürün Adı", "Kategori", "Teknik özellikler", "Birim maliyet", "Planlanan fiyat",
                               "gorsel_dosyalari", "hedef_rol", "min_siparis_adedi"])
    for r in items:
        ws.append(r)
    if meta:
        m = wb.create_sheet("Koleksiyon")
        m.append(list(meta))
        m.append(list(meta.values()))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def png(w=600, h=800, color=(200, 180, 160)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, "PNG")
    return buf.getvalue()


META = {"koleksiyon_adi": "SS27", "marka": "", "sezon": "İY 2027", "toplam_butce": 2_000_000, "para_birimi": "TL",
        "hedef_bolgeler": "TR, EU", "kanal": "online"}
ROWS = [
    ["SW27-001", "Keten gömlek", "Üst giyim", "%100 keten 160 gsm", 420, 1499, None, "çekirdek", None],
    ["SW27-002", "Keten pantolon", "Alt giyim", "keten viskon 220 gsm", "510,50", "1.799", "pantolon_on.jpg; pantolon_arka.jpg", "tamamlayıcı", None],
    ["SW27-003", "Midi elbise", "Elbise", "viskon 120 gsm", 640, 2299, None, "hero", 200],
    ["SW27-0031", "Mini elbise", "Elbise", "viskon 120 gsm", 600, 2199, None, None, None],
]


# ---------- içe aktarma ----------

def test_headers_numbers_and_meta_are_read_flexibly():
    book = read_workbook(xlsx(ROWS, META))
    prev = build_preview("t1", book, [])
    assert prev.meta.name == "SS27" and prev.meta.currency == "TRY" and prev.meta.target_regions == ["TR", "EU"]
    assert prev.meta.total_budget == 2_000_000
    it = {p.item.sku: p.item for p in prev.items}
    assert it["SW27-002"].unit_cost == 510.5 and it["SW27-002"].planned_price == 1799
    assert it["SW27-001"].declared_role == "çekirdek" and it["SW27-003"].moq == 200
    assert prev.column_map["Ürün Adı"] == "name"


def test_image_matching_rules():
    items = [CollectionItem(sku=s, name=s, images=imgs) for s, imgs in
             [("SW27-001", []), ("SW27-002", ["pantolon_on.jpg", "PANTOLON_ARKA"]), ("SW27-003", []),
              ("SW27-0031", []), ("SW27-010", []), ("ŞAL-1", [])]]
    imgs = [ImageInfo(p) for p in ["SW27-001_2.jpg", "sw27-001.JPG", "pantolon_on.jpg", "pantolon_arka.png",
                                   "SW27-003-arka.jpg", "SW27-0031.jpg", "SW27-010/on.jpg", "sal-1 (1).png",
                                   "SW72-003.jpg", "logo.png"]]
    matched, rule, amb, orphans = match_images(items, imgs)
    assert matched["SW27-001"] == ["sw27-001.JPG", "SW27-001_2.jpg"]          # ana görsel önce
    assert rule["SW27-002"] == "Excel görsel sütunu" and matched["SW27-002"] == ["pantolon_on.jpg", "pantolon_arka.png"]
    assert matched["SW27-003"] == ["SW27-003-arka.jpg"]                       # SW27-0031.jpg 003'e gitmez
    assert matched["SW27-0031"] == ["SW27-0031.jpg"]
    assert rule["SW27-010"] == "SKU klasörü"
    assert matched["ŞAL-1"] == ["sal-1 (1).png"]                              # Türkçe karakter önemsiz
    by_file = {o.file: o for o in orphans}
    assert set(by_file) == {"SW72-003.jpg", "logo.png"}
    assert by_file["SW72-003.jpg"].suggestion == "SW27-003"                   # yazım hatası önerisi
    assert not amb


def test_preview_reports_errors_and_warnings():
    rows = ROWS + [["SW27-001", "Kopya", "Üst giyim", "x", 1, 2, None, None, None],
                   [None, "SKU'suz", "", "x", None, None, None, None, None],
                   ["SW27-020", "Görselsiz", "", "x", None, None, None, "süper", None]]
    imgs = [ImageInfo("SW27-001.jpg", 1200, 1600), ImageInfo("SW27-003.jpg", 300, 300),
            ImageInfo("pantolon_on.jpg"), ImageInfo("SW27-0031.jpg")]
    prev = build_preview("t2", read_workbook(xlsx(rows)), imgs)
    msgs = [(i.level, i.sku, i.message) for i in prev.issues]
    assert any(l == "hata" and "Aynı SKU" in m for l, _, m in msgs)
    assert any(l == "hata" and m == "SKU boş" for l, _, m in msgs)
    assert any(s == "SW27-020" and m == "Görsel bulunamadı" for _, s, m in msgs)
    assert any(s == "SW27-020" and "Birim maliyet boş" in m for _, s, m in msgs)
    assert any(s == "SW27-020" and "Hedef rol tanınmadı" in m for _, s, m in msgs)
    assert any(s == "SW27-003" and "Görsel küçük" in m for _, s, m in msgs)
    assert any(l == "bilgi" and "koleksiyon sayfası" in m for l, _, m in msgs)
    st = [(p.item.sku, p.status) for p in prev.items]
    assert ("SW27-001", "ok") in st and ("SW27-001", "hata") in st and ("SW27-020", "hata") in st


def test_template_is_readable_by_importer():
    prev = build_preview("t3", read_workbook(template_bytes()), [])
    assert [p.item.sku for p in prev.items] == ["SW27-001", "SW27-002", "SW27-003"]
    assert prev.meta.currency == "TRY" and prev.meta.target_regions == ["TR", "EU"]
    assert not prev.ignored_columns


def test_csv_with_semicolons():
    data = "Model Kodu;Ürün;Kategori;Maliyet\nA-1;Gömlek;Üst;100\n".encode("utf-8")
    prev = build_preview("t4", read_workbook(data, "liste.csv"), [ImageInfo("A-1.jpg")])
    assert prev.items[0].item.unit_cost == 100 and prev.items[0].item.images == ["A-1.jpg"]


# ---------- koleksiyon özeti ----------

def _resp(region_answers, price=50.0, demand=60, demand_units=500):
    """Tek ürün yanıtının özetin kullandığı alanları."""
    regs = []
    for r, answers in region_answers.items():
        regs.append({"region": r, "demand_score_100": demand, "optimal_sale_price": price,
                     "estimated_margin_percentage": 50.0, "key_objections": ["pahalı"],
                     "van_westendorp": {"acceptable_range_low": price * 0.8, "acceptable_range_high": price * 1.2},
                     "returns": {"rate_pct": 10.0}, "allocation": {"demand_units": demand_units},
                     "raw_answers": [{"agent": i + 1, "status": "json", "interest": v} for i, v in enumerate(answers)],
                     "confidence": {"level": "orta"}, "data_basis": {"persona_version": "v1"}})
    return {"panel_seed": "koleksiyon:x", "response": {"regional_breakdown": regs, "failed_regions": []}}


def _col(n=5, budget=100_000.0):
    items = [CollectionItem(sku=f"S{i}", name=f"Ürün {i}", category="Elbise" if i < 3 else "Gömlek",
                            unit_cost=20.0, planned_price=50.0, images=[f"S{i}.jpg"]) for i in range(n)]
    return Collection(id="20261103-abcd1234", meta=CollectionMeta(name="T", currency="USD", total_budget=budget,
                                                                  target_regions=["TR"]), items=items)


def test_within_person_normalization_cannibal_roles_and_budget():
    # 6 kişi. Kişi 1-3 cömert (her şeye yüksek), 4-6 titiz. S0 ve S1 aynı kişilerce sevilir (kanibalizasyon).
    ans = {
        "S0": [95, 90, 92, 72, 75, 74],
        "S1": [94, 91, 90, 71, 76, 73],
        "S2": [80, 80, 80, 30, 30, 30],
        "S3": [70, 72, 71, 20, 25, 22],
        "S4": [60, 60, 60, 10, 12, 11],
    }
    col = _col()
    results = {s: _resp({"TR": a}) for s, a in ans.items()}
    res = summarize(col, results, 42.0)
    by = {i.sku: i for i in res.items}
    assert by["S0"].rank.value in (1, 2) and by["S4"].rank.value == 5
    assert by["S4"].role == "riskli" and by["S0"].role == "hero"
    assert by["S0"].rank.low is not None                       # bootstrap aralığı var
    assert res.panel_shared
    pair = res.summary.cannibal_pairs[0]
    assert {pair.a, pair.b} == {"S0", "S1"} and "kanibalizasyon adayı" in by["S0"].flags
    assert res.summary.reach.value == 100.0                    # herkes en az bir ürüne 70+
    assert res.summary.reach_curve[0].sku in ("S0", "S1")
    assert res.summary.budget_used_usd <= 100_000
    assert all(i.recommended_qty.basis == "kural varsayımı" for i in res.items)
    assert any(a.kind == "kanibalizasyon" for a in res.summary.actions)


def test_whatif_exclude_price_and_budget_without_llm():
    ans = {f"S{i}": [80 - 10 * i + k for k in range(4)] for i in range(5)}
    col = _col()
    results = {s: _resp({"TR": a}) for s, a in ans.items()}
    base = summarize(col, results, 42.0)
    wi = summarize(col, results, 42.0, WhatIf(exclude=["S4"], planned_prices={"S0": 90.0}, total_budget=5000))
    assert len(wi.items) == 4 and base.summary.n_items == 5
    s0 = next(i for i in wi.items if i.sku == "S0")
    assert all(r.price_fit == "üstünde" for r in s0.regions) and "fiyat aralığın üstünde" in s0.flags
    assert wi.summary.budget_used_usd <= 5000 < base.summary.budget_used_usd


def test_try_currency_and_missing_results():
    col = _col(3)
    col.meta.currency = "TRY"
    col.items[0].unit_cost, col.items[0].planned_price = 840.0, 2100.0     # 20$ / 50$ @42
    results = {"S0": _resp({"TR": [80, 70, 60]}), "S1": {"error": "Görsel yok"}}
    res = summarize(col, results, 42.0)
    s0, s1, s2 = res.items
    assert s0.unit_cost_usd == 20.0 and s0.regions[0].price_fit == "içinde"
    assert s1.flags == ["hata"] and s1.role_why == "Görsel yok"
    assert s2.flags == ["değerlendirilmedi"]
    assert res.summary.n_evaluated == 1 and res.summary.n_failed == 1


def test_allocate_items_respects_budget_and_cost():
    sig = [{"sku": "A", "region": "TR", "demand": 1000, "net": 40, "cost": 10},
           {"sku": "B", "region": "TR", "demand": 1000, "net": 40, "cost": 30},
           {"sku": "C", "region": "TR", "demand": 1000, "net": 5, "cost": 10}]   # zarar: almaz
    q = allocate_items(sig, 20_000, "balanced")
    spent = q[("A", "TR")] * 10 + q[("B", "TR")] * 30
    assert spent <= 20_000 and q[("C", "TR")] == 0 and q[("A", "TR")] > 0
    q2 = allocate_items(sig, 10_000_000, "balanced")                             # bütçe talebi aşar
    assert q2[("A", "TR")] < 1400


# ---------- API uçtan uca ----------

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(routes, "_store", CollectionStore(str(tmp_path / "cols")))
    with TestClient(app) as c:
        yield c


def _upload(client, rows=ROWS, meta=META, extra=None):
    files = [("sheet", ("liste.xlsx", xlsx(rows, meta), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))]
    for name in ["SW27-001.jpg", "pantolon_on.jpg", "pantolon_arka.jpg", "SW27-003.png", "SW27-0031.jpg"] + (extra or []):
        files.append(("images", (name, png(), "image/png")))
    zbuf = io.BytesIO()
    import zipfile
    with zipfile.ZipFile(zbuf, "w") as z:
        z.writestr("__MACOSX/._x.jpg", b"x")
        z.writestr("ek/SW27-001_2.jpg", png())
        z.writestr("foto.heic", b"x")
    files.append(("images", ("ek.zip", zbuf.getvalue(), "application/zip")))
    return client.post("/api/collections/import", files=files)


def _wait(client, cid, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        st = client.get(f"/api/collections/{cid}/status").json()
        if not st["running"]:
            return st
        time.sleep(0.05)
    raise AssertionError("koşu bitmedi")


def test_api_import_confirm_run_result_export(client):
    r = _upload(client)
    assert r.status_code == 200, r.text
    prev = r.json()
    cid = prev["collection_id"]
    imgs = {p["item"]["sku"]: p["item"]["images"] for p in prev["items"]}
    assert imgs["SW27-001"] == ["SW27-001.jpg", "ek/SW27-001_2.jpg"]
    assert imgs["SW27-002"] == ["pantolon_on.jpg", "pantolon_arka.jpg"]
    assert any("heic" in i["message"] for i in prev["issues"])
    assert client.get(f"/api/collections/{cid}/images/pantolon_on.jpg").status_code == 200
    assert client.get(f"/api/collections/{cid}/images/../../etc/passwd").status_code == 404

    body = {"meta": prev["meta"], "items": [p["item"] for p in prev["items"]]}
    col = client.post(f"/api/collections/{cid}/confirm", json=body).json()
    assert col["status"] == "hazır" and len(col["items"]) == 4

    assert client.post(f"/api/collections/{cid}/run", json={}).status_code == 200
    st = _wait(client, cid)
    assert st["done"] == 4 and not st["failed"], st
    res = client.get(f"/api/collections/{cid}/result").json()
    assert res["summary"]["n_evaluated"] == 4 and res["currency"] == "TRY"
    assert {r["region"] for r in res["items"][0]["regions"]} == {"TR", "EU"}
    assert client.get(f"/api/collections/{cid}/items/SW27-001/prediction").json()["regional_breakdown"]

    # ikinci koşu: girdiler değişmedi, önceki sonuçlar kullanılır
    client.post(f"/api/collections/{cid}/run", json={})
    st2 = _wait(client, cid)
    assert any("önceki sonuç" in line for line in st2["log"])

    wi = client.post(f"/api/collections/{cid}/whatif", json={"exclude": ["SW27-0031"]}).json()
    assert wi["summary"]["n_items"] == 3
    x = client.get(f"/api/collections/{cid}/export.xlsx")
    wb = load_workbook(io.BytesIO(x.content))
    assert wb["Ürünler"].max_row == 5
    assert any(c["id"] == cid for c in client.get("/api/collections").json())


def test_api_template_and_bad_file(client):
    t = client.get("/api/collections/template.xlsx")
    assert t.status_code == 200 and load_workbook(io.BytesIO(t.content))["Ürünler"].max_row == 4
    r = client.post("/api/collections/import", files=[("sheet", ("x.xls", b"abc", "application/octet-stream"))])
    assert r.status_code == 422


def test_panel_engine_uses_same_people_for_every_item(client):
    app.dependency_overrides[get_engine] = lambda: make_engine(panel_size=6, min_valid=2)
    rows = [r for r in ROWS if r[0] != "SW27-0031"]
    prev = _upload(client, rows=rows, meta={**META, "hedef_bolgeler": "TR"}).json()
    cid = prev["collection_id"]
    client.post(f"/api/collections/{cid}/confirm", json={"meta": prev["meta"], "items": [p["item"] for p in prev["items"]]})
    client.post(f"/api/collections/{cid}/run", json={})
    st = _wait(client, cid)
    assert not st["failed"], st
    segs = []
    for sku in ("SW27-001", "SW27-002", "SW27-003"):
        p = client.get(f"/api/collections/{cid}/items/{sku}/prediction").json()
        segs.append([(a["agent"], a["segment"]) for a in p["regional_breakdown"][0]["raw_answers"]])
    assert segs[0] == segs[1] == segs[2]          # aynı kişiler
    res = client.get(f"/api/collections/{cid}/result").json()
    assert res["panel_shared"] and res["summary"]["reach"]["value"] is not None
    assert all(i["rank"]["low"] is not None for i in res["items"])


def test_ties_do_not_create_fake_roles():
    col = _col()
    results = {f"S{i}": _resp({"TR": [60, 61, 59, 60]}) for i in range(5)}
    res = summarize(col, results, 42.0)
    assert {i.role for i in res.items} == {"belirsiz"}
    assert any("ayırt etmedi" in n for n in res.notes)
    assert not any(a.kind == "çıkar" for a in res.summary.actions)


def _profile(name, mult, tier, pull=50):
    from app.brand import generic_profile
    return json.loads(generic_profile(name, "").model_copy(update={
        "price_multiple": mult, "price_tier": tier, "brand_pull": pull, "edited": True}).model_dump_json())


def test_brand_from_screen_drives_prices_and_triggers_rerun(client):
    app.dependency_overrides[get_engine] = lambda: make_engine(panel_size=6, min_valid=2)
    rows = [r for r in ROWS if r[0] in ("SW27-001", "SW27-003")]
    prev = _upload(client, rows=rows, meta={**META, "hedef_bolgeler": "TR", "marka": "Excel Markası"}).json()
    cid = prev["collection_id"]
    meta = {**prev["meta"], "brand": "Ekran Markası", "brand_profile": _profile("Ekran Markası", 1.8, "budget")}
    client.post(f"/api/collections/{cid}/confirm", json={"meta": meta, "items": [p["item"] for p in prev["items"]]})
    client.post(f"/api/collections/{cid}/run", json={})
    assert not _wait(client, cid)["failed"]
    cheap = client.get(f"/api/collections/{cid}/result").json()
    be = cheap["brand_effect"]
    assert be["name"] == "Ekran Markası" and be["basis"] == "kullanıcı girdisi" and be["price_level_pct"] < 0
    pred = client.get(f"/api/collections/{cid}/items/SW27-001/prediction").json()
    assert pred["brand_profile"]["name"] == "Ekran Markası"          # ekrandaki giriş Excel'e baskın

    meta2 = {**meta, "brand": "Lüks Marka", "brand_profile": _profile("Lüks Marka", 6.0, "luxury", 85)}
    assert client.put(f"/api/collections/{cid}/meta", json={"meta": meta2}).status_code == 200
    stale = client.get(f"/api/collections/{cid}/result").json()["brand_effect"]
    assert "yeniden çalıştırın" in (stale["warning"] or "")
    client.post(f"/api/collections/{cid}/run", json={})
    st = _wait(client, cid)
    assert not any("önceki sonuç" in line for line in st["log"])         # marka değişti, yeniden soruldu
    lux = client.get(f"/api/collections/{cid}/result").json()
    p_cheap = cheap["items"][0]["regions"][0]["optimal_price"]
    p_lux = next(i for i in lux["items"] if i["sku"] == cheap["items"][0]["sku"])["regions"][0]["optimal_price"]
    assert p_lux > 2 * p_cheap
    assert lux["brand_effect"]["price_level_pct"] > 100 and not lux["brand_effect"]["warning"]
