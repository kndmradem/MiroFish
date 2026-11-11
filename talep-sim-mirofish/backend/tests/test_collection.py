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
    assert it["SW27-002"].unit_cost == 510.5 and it["SW27-002"].planned_price is None      # satış fiyatı okunmaz
    assert any("Satış fiyatı sütunu (Planlanan fiyat) okunmadı" in i.message for i in prev.issues)
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
    assert any(l == "hata" and s == "SW27-020" and "Maliyet fiyatı boş" in m for l, s, m in msgs)
    assert any(s == "SW27-020" and "Hedef rol tanınmadı" in m for _, s, m in msgs)
    assert any(s == "SW27-003" and "Görsel küçük" in m for _, s, m in msgs)
    assert any(l == "bilgi" and "genel bilgi" in m for l, _, m in msgs)
    st = [(p.item.sku, p.status) for p in prev.items]
    assert ("SW27-001", "ok") in st and ("SW27-001", "hata") in st and ("SW27-020", "hata") in st


def test_template_is_readable_by_importer():
    prev = build_preview("t3", read_workbook(template_bytes()), [])
    assert [p.item.sku for p in prev.items] == ["URN-001", "URN-002", "URN-003"]
    assert prev.meta.currency == "TRY" and prev.meta.target_regions == ["TR", "EU"] and prev.meta.name == "SS27 Ana Koleksiyon"
    assert not prev.ignored_columns
    first = prev.items[0].item
    assert first.unit_cost == 420 and first.technical_specs.startswith("%100 keten") and first.planned_price is None
    assert first.attributes["Hedef kitle"] == "kadın" and first.attributes["yaka"] == "klasik"
    wb = load_workbook(io.BytesIO(template_bytes()))
    heads = [c.value for c in wb["Ürünler"][1]]
    assert not any("fiyat" in h and "maliyet" not in h for h in heads)          # satış fiyatı sütunu yok
    assert {"sku", "urun_adi", "kategori", "urun_icerigi", "maliyet_fiyati"} <= set(heads)
    # aynı şablon bağımsız ürün ekranında da okunur
    ind = build_preview("t3b", read_workbook(template_bytes()), [], kind="bagimsiz")
    assert ind.meta.kind == "bagimsiz" and len(ind.items) == 3
    assert any("Koleksiyona özel sütunlar" in i.message for i in ind.issues)


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


# ---------- vitrin turu ----------

from collections import Counter

from app.collection import showcase as sc
from app.collection.summary import summarize_showcase

from .test_panel import FakeLLMServer


def test_plan_blocks_small_collection_rotates_positions():
    skus = [f"S{i}" for i in range(6)]
    firsts = Counter()
    for p in range(12):
        blocks = sc.plan_blocks(skus, p, 12, 8, "seed")
        assert len(blocks) == 1 and sorted(blocks[0]) == skus
        firsts[blocks[0][0]] += 1
    assert max(firsts.values()) <= 3 and len(firsts) >= 5     # her ürün başta yaklaşık eşit


def test_plan_blocks_large_collection_each_item_twice():
    skus = [f"S{i}" for i in range(20)]
    blocks = sc.plan_blocks(skus, 3, 12, 8, "seed")
    seen = Counter(x for b in blocks for x in b)
    assert set(seen.values()) == {2} and all(len(set(b)) == len(b) <= 8 for b in blocks)
    assert {len(b) for b in blocks} <= {6, 7}                   # 20 ürün -> 3 grup, eşit boy
    assert blocks != sc.plan_blocks(skus, 4, 12, 8, "seed")    # kişiden kişiye farklı


def test_parse_is_tolerant():
    a = sc.parse('cevap: {"best": ["a", "Z", "B", "C", "D"], "worst": ["B", "E"], "together": [["A","C"],["C","A"],["A","A"]],'
                 ' "substitutes": [["D","E"]], "n_buy": "2", "comment": "iyi"}', list("ABCDE"))
    assert a["best"] == ["A", "C"] and a["worst"] == ["E"]     # Z geçersiz, B hem iyi hem kötü: çıkarıldı
    assert a["together"] == [["A", "C"]] and a["substitutes"] == [["D", "E"]] and a["n_buy"] == 2
    assert sc.parse("bilmiyorum", list("AB")) is None


def test_position_bias_is_detected():
    recs = []
    for p in range(30):
        order = [f"S{(p + i) % 5}" for i in range(5)]
        recs.append({"region": "TR", "person": p, "order": order, "letters": dict(zip("ABCDE", order)),
                     "answer": {"best": ["A"], "worst": ["E"], "together": [["A", "B"]], "substitutes": [], "n_buy": 1, "comment": ""}})
    items, summ = summarize_showcase({"TR": recs}, [f"S{i}" for i in range(5)], {})
    assert summ.position_warning and "ilk" in summ.position_warning
    assert summ.position[0].pick_pct == 100.0 and summ.position[0].expected_pct == 20.0
    assert all(v.shown == 30 for v in items.values())


def test_showcase_end_to_end_with_panel_and_resume(client):
    server = FakeLLMServer()
    app.dependency_overrides[get_engine] = lambda: make_engine(server=server, panel_size=4, min_valid=2)
    rows = [[f"SW27-1{i:02d}", f"{'Gömlek' if i < 5 else 'Etek'} model {i}", "Üst" if i < 5 else "Alt", "pamuk", 300 + i, 1200 + 50 * i,
             None, None, None] for i in range(10)]
    files = [("sheet", ("l.xlsx", xlsx(rows, {**META, "hedef_bolgeler": "TR"}), "application/octet-stream"))]
    files += [("images", (f"{r[0]}.jpg", png(), "image/png")) for r in rows]
    prev = client.post("/api/collections/import", files=files).json()
    cid = prev["collection_id"]
    client.post(f"/api/collections/{cid}/confirm", json={"meta": prev["meta"], "items": [p["item"] for p in prev["items"]]})
    client.post(f"/api/collections/{cid}/run", json={"block_size": 4})
    st = _wait(client, cid)
    assert not st["failed"] and any("vitrin turu başlıyor" in line for line in st["log"]), st["log"]
    showcase_prompts = [b for b in server.bodies if "VİTRİN TURU" in b["messages"][1]["content"]]
    # 4 kişi x (10 ürün, 4'lük grup -> 3 grup x 2 tekrar = 6 grup)
    assert len(showcase_prompts) == 4 * 6
    assert not any("SW27-1" in b["messages"][1]["content"] for b in showcase_prompts)   # ürün kodu prompta yok
    res = client.get(f"/api/collections/{cid}/result").json()
    s = res["showcase"]
    assert s["n_answers"] == 24 and s["n_persons"] == 4 and len(s["position"]) == 3
    assert all(i["showcase"]["shown"] == 8 for i in res["items"])         # her ürün kişi başı 2 kez
    assert s["together_pairs"]

    n_before = len(server.bodies)
    client.post(f"/api/collections/{cid}/run", json={"block_size": 4})
    _wait(client, cid)
    assert len(server.bodies) == n_before                                 # kaldığı yerden: hiçbir şey yeniden sorulmadı


def test_showcase_runs_on_panel_side_of_hybrid_engine(client):
    """Karma motor: tek tek tur MiroFish'te, vitrin turu (MiroFish'te yok) panelde; ekranda farkı açıklanır."""
    from app.services.hybrid_engine import HybridEngine
    from .test_hybrid_engine import FakeMiroFish

    server = FakeLLMServer()
    mf = FakeMiroFish()
    app.dependency_overrides[get_engine] = lambda: HybridEngine(mf, make_engine(server=server, panel_size=4, min_valid=2))
    rows = [[f"SW27-1{i:02d}", f"Gömlek model {i}", "Üst", "pamuk", 300 + i, 1200 + 50 * i, None, None, None] for i in range(5)]
    files = [("sheet", ("l.xlsx", xlsx(rows, {**META, "hedef_bolgeler": "TR"}), "application/octet-stream"))]
    files += [("images", (f"{r[0]}.jpg", png(), "image/png")) for r in rows]
    prev = client.post("/api/collections/import", files=files).json()
    cid = prev["collection_id"]
    client.post(f"/api/collections/{cid}/confirm", json={"meta": prev["meta"], "items": [p["item"] for p in prev["items"]]})
    client.post(f"/api/collections/{cid}/run", json={"block_size": 4})
    st = _wait(client, cid)
    assert not st["failed"], st["log"]
    assert any("persona paneliyle yapılıyor" in line for line in st["log"]), st["log"]
    assert len(mf.calls) == 5                                             # tek tek tur: MiroFish
    assert any("VİTRİN TURU" in b["messages"][1]["content"] for b in server.bodies)   # vitrin: panel
    assert not any("VİTRİN TURU" not in b["messages"][1]["content"] for b in server.bodies)
    s = client.get(f"/api/collections/{cid}/result").json()["showcase"]
    assert s["n_answers"] > 0 and "MiroFish" in s["basis_note"]


# ---------- üretim kararı (üret / azalt / üretme) ----------

def test_production_decision_drops_low_demand_and_low_margin_items():
    col = _col(5)
    for it in col.items:
        it.planned_price = None                       # yeni akış: satış fiyatı girilmez, sistem önerir
    col.items[3].unit_cost = 40.0                     # 50$ fiyatta iade sonrası net marj ~%9: üretme
    results = {
        "S0": _resp({"TR": [80, 82, 78, 81]}, demand=70),
        "S1": _resp({"TR": [70, 72, 69, 71]}, demand=62),
        "S2": _resp({"TR": [50, 52, 49, 51]}, demand=44),    # orta talep: azalt
        "S3": _resp({"TR": [75, 74, 76, 73]}, demand=66),
        "S4": _resp({"TR": [20, 22, 25, 21]}, demand=25),    # düşük talep: üretme
    }
    res = summarize(col, results, 42.0)
    by = {i.sku: i for i in res.items}
    assert by["S4"].decision == "üretme" and by["S4"].decision_reasons[0].basis == "ajan"
    assert "Talep skoru 25/100" in by["S4"].decision_reasons[0].text
    assert by["S3"].decision == "üretme" and by["S3"].decision_reasons[0].basis == "kural varsayımı"
    assert "net marj" in by["S3"].decision_reasons[0].text and by["S3"].net_margin.value < 15
    assert by["S2"].decision == "azalt" and by["S0"].decision == "üret"
    assert by["S4"].recommended_qty.value == 0 and by["S3"].recommended_qty.value == 0
    assert not by["S4"].qty_by_region.get("TR") and by["S0"].recommended_qty.value > 0
    assert "Önerilen fiyatta" in by["S3"].decision_reasons[0].text
    # S1 güçlü (çekirdek) ürün: S0 ile aynı kişiler seviyor ama bu yalnızca bilgi olarak gerekçeye düşer
    assert by["S1"].decision == "üret" and any("kanibalizasyon" in r.text for r in by["S1"].decision_reasons)
    assert res.summary.decisions == {"üret": 2, "azalt": 1, "üretme": 2}
    assert {a.kind for a in res.summary.actions} >= {"üretme", "azalt"}
    assert all(r.basis in ("ajan", "kural varsayımı", "kullanıcı girdisi") for i in res.items for r in i.decision_reasons)
    # önerilen fiyat panelden gelir ve dayanağı ajan
    assert by["S0"].recommended_price.value == 50.0 and by["S0"].recommended_price.basis == "ajan"
    assert by["S0"].recommended_price.low == 40.0 and by["S0"].recommended_price.high == 60.0

    # elle karar: üretme -> üret; ürün bütçeye girer ve kaynağı kullanıcı olur
    wi = summarize(col, results, 42.0, WhatIf(decisions={"S3": "üret"}))
    s3 = next(i for i in wi.items if i.sku == "S3")
    assert s3.decision == "üret" and s3.decision_source == "kullanıcı" and s3.recommended_qty.value > 0
    assert s3.decision_reasons[0].basis == "kullanıcı girdisi" and "sistem önerisi: üretme" in s3.decision_reasons[0].text


def test_trial_price_changes_margin_and_decision():
    col = _col(3)
    for it in col.items:
        it.planned_price = None
    results = {f"S{i}": _resp({"TR": [70, 72, 71]}, demand=70) for i in range(3)}
    base = {i.sku: i for i in summarize(col, results, 42.0).items}
    assert base["S0"].decision == "üret"
    cheap = {i.sku: i for i in summarize(col, results, 42.0, WhatIf(planned_prices={"S0": 22.0})).items}
    assert cheap["S0"].decision == "üretme" and "Denenen fiyatta" in cheap["S0"].decision_reasons[0].text


def test_weak_region_is_left_out_of_budget():
    col = _col(3)
    col.meta.target_regions = ["TR", "EU"]
    ok = _resp({"TR": [70, 72, 71]}, demand=70)
    weak = _resp({"EU": [20, 22, 21]}, demand=20)
    mixed = {"panel_seed": "x", "response": {"regional_breakdown": ok["response"]["regional_breakdown"] + weak["response"]["regional_breakdown"],
                                             "failed_regions": []}}
    results = {"S0": mixed, "S1": _resp({"TR": [60, 61, 62], "EU": [60, 61, 62]}, demand=65),
               "S2": _resp({"TR": [65, 61, 62], "EU": [65, 61, 62]}, demand=66)}
    res = summarize(col, results, 42.0)
    s0 = next(i for i in res.items if i.sku == "S0")
    assert s0.decision == "azalt" and any("EU bölgesinde talep" in r.text for r in s0.decision_reasons)
    assert not s0.qty_by_region.get("EU") and s0.qty_by_region.get("TR", 0) > 0


# ---------- bağımsız ürünler (koleksiyonu olmayan toplu yükleme) ----------

def test_independent_items_skip_collection_logic():
    col = _col(5)
    col.meta.kind = "bagimsiz"
    ans = {"S0": [95, 90, 92, 72], "S1": [94, 91, 90, 71], "S2": [80, 80, 80, 30], "S3": [70, 72, 71, 20], "S4": [60, 60, 60, 10]}
    results = {s: _resp({"TR": a}) for s, a in ans.items()}
    res = summarize(col, results, 42.0, showcase={"TR": [{"region": "TR", "person": 1, "order": ["S0", "S1"],
                                                          "letters": {"A": "S0", "B": "S1"}, "answer": None}]})
    assert res.kind == "bagimsiz" and not res.panel_shared
    assert {i.role for i in res.items} == {"belirsiz"} and not res.summary.cannibal_pairs and res.summary.reach.value is None
    assert res.showcase is None
    assert all(i.decision == "üret" for i in res.items)               # her ürün kendi talep/marjıyla
    assert any("Bağımsız ürün listesi" in n for n in res.notes)


def test_api_independent_items_each_get_own_panel(client, monkeypatch):
    from app.panel import engine as panel_engine
    seeds = []
    real = panel_engine.sample_panel
    monkeypatch.setattr(panel_engine, "sample_panel", lambda lib, n, seed="", *a, **k: (seeds.append(seed), real(lib, n, seed, *a, **k))[1])
    server = FakeLLMServer()
    app.dependency_overrides[get_engine] = lambda: make_engine(server=server, panel_size=6, min_valid=2)
    files = [("sheet", ("l.xlsx", template_bytes(), "application/octet-stream"))]
    files += [("images", (f"URN-00{i}.jpg", png(), "image/png")) for i in (1, 2, 3)]
    r = client.post("/api/collections/import", files=files, data={"kind": "bagimsiz"})
    assert r.status_code == 200, r.text
    prev = r.json()
    assert prev["meta"]["kind"] == "bagimsiz"
    meta = {**prev["meta"], "target_regions": ["TR"]}
    cid = prev["collection_id"]
    col = client.post(f"/api/collections/{cid}/confirm", json={"meta": meta, "items": [p["item"] for p in prev["items"]]}).json()
    assert col["meta"]["kind"] == "bagimsiz"
    client.post(f"/api/collections/{cid}/run", json={})
    st = _wait(client, cid)
    assert not st["failed"], st
    assert not any("VİTRİN TURU" in b["messages"][1]["content"] for b in server.bodies)    # vitrin turu yok
    for sku in ("URN-001", "URN-002", "URN-003"):
        p = client.get(f"/api/collections/{cid}/items/{sku}/prediction").json()
        assert "panel_seed" not in p["product_card"]
    assert len(set(seeds)) == 3 and not any(x.startswith("koleksiyon:") for x in seeds)   # her ürüne ayrı panel (ürün adıyla)
    res = client.get(f"/api/collections/{cid}/result").json()
    assert res["kind"] == "bagimsiz" and all(i["decision"] in ("üret", "azalt", "üretme") for i in res["items"])
    assert all(i["recommended_price"]["value"] for i in res["items"])
    assert client.get(f"/api/collections/{cid}/export.xlsx").status_code == 200


# ---------- Excel'e gömülü görseller ve renk satırları ----------

def _xlsx_with_embedded(rows, headers, img_col=8):
    from openpyxl.drawing.image import Image as XLImage
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet"
    ws.append(headers)
    for i, r in enumerate(rows, start=2):
        ws.append(r)
        if r[img_col] is None:
            pic = XLImage(io.BytesIO(png(134, 202, (10 * i, 80, 120))))
            ws.add_image(pic, f"{chr(65 + img_col)}{i}")
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


ERP_HEADERS = ["Ürün Tipi Açıklması", "Ürün Kodu", "Ürün Adı", None, "Renk Kodu", "Renk Açıklaması", "Beden", "Birim Cinsi (1)",
               "ColorPhoto_Data Uri", "Model Cinsi Açıklama", "Alt Kategori Açıklama", "Sezon Açıklama", "Yıl Açıklama",
               "Ürün Cinsi Açıklama", "Kumaş Tipi Açıklama", "Kumaş İçeriği", "Maliyet"]


def _erp_rows():
    import base64 as b64
    uri = "data:image/png;base64," + b64.b64encode(png(300, 400)).decode()
    return [
        ["Ürün", "ST1", "Fine Rib Body", None, "012", "BLACK", "S, M, L", "AD", None, "BODY", "TRENDY", "KIŞ", "2027", "BODY", "ÖRME", "%86 Modal %14 Elastan", 1013],
        ["Ürün", "ST1", "Fine Rib Body", None, "019", "BROWN", "S, M, L", "AD", None, "BODY", "TRENDY", "KIŞ", "2027", "BODY", "ÖRME", "%86 Modal %14 Elastan", 1013],
        ["Ürün", "WS2", "Campus Bra", None, "020", "BURGUNDY", "75, 80", "AD", uri, "ÜÇGEN BRA", "TRENDY", "KIŞ", "2027", "SUTYEN", "ÖRME", "%48 Pamuk", 361],
    ]


def test_api_reads_images_embedded_in_excel_and_merges_colors(client):
    data = _xlsx_with_embedded(_erp_rows(), ERP_HEADERS)
    r = client.post("/api/collections/import", files=[("sheet", ("CardProduct.xlsx", data, "application/octet-stream"))])
    assert r.status_code == 200, r.text
    prev = r.json()
    items = {p["item"]["sku"]: p for p in prev["items"]}
    assert set(items) == {"ST1", "WS2"}                                       # renk satırları modelde birleşti
    st1 = items["ST1"]["item"]
    assert st1["colors"] == ["BLACK", "BROWN"] and len(st1["images"]) == 2 and items["ST1"]["match_rule"] == "Excel'e gömülü"
    assert st1["category"] == "BODY" and st1["unit_cost"] == 1013 and st1["technical_specs"].startswith("%86")
    assert st1["attributes"]["Kumaş tipi"] == "ÖRME" and st1["attributes"]["Alt Kategori"] == "TRENDY"
    assert items["WS2"]["item"]["images"] and items["WS2"]["item"]["subcategory"] == "ÜÇGEN BRA"   # data URI hücresi
    assert prev["meta"]["season"] == "KIŞ 2027" and not prev["orphans"]
    assert any("Görsel küçük" in i["message"] for i in prev["issues"])
    cid = prev["collection_id"]
    assert client.get(f"/api/collections/{cid}/images/{st1['images'][0]}").status_code == 200
    col = client.post(f"/api/collections/{cid}/confirm", json={"meta": prev["meta"], "items": [p["item"] for p in prev["items"]]}).json()
    assert len(col["items"]) == 2 and all(i["images"] for i in col["items"])

    # her renk ayrı ürün
    r2 = client.post("/api/collections/import", data={"variants": "renk"},
                     files=[("sheet", ("CardProduct.xlsx", data, "application/octet-stream"))]).json()
    assert sorted(p["item"]["sku"] for p in r2["items"]) == ["ST1-012", "ST1-019", "WS2"]
    assert all(len(p["item"]["images"]) == 1 for p in r2["items"])

    # aynı SKU ile yüklenen büyük görsel gömülü olanın yerine geçer
    r3 = client.post("/api/collections/import", files=[("sheet", ("CardProduct.xlsx", data, "application/octet-stream")),
                                                       ("images", ("ST1_on.jpg", png(1200, 1600), "image/jpeg"))]).json()
    st = next(p for p in r3["items"] if p["item"]["sku"] == "ST1")
    assert st["item"]["images"] == ["ST1_on.jpg"] and st["match_rule"] == "dosya adı = SKU"


# ---------- renk bazlı plan ----------

def _color_col(budget=100_000.0):
    col = _col(3, budget)
    col.items[0].colors = ["BLACK", "PINK"]
    col.items[0].attributes["Renk kodu"] = "001, 045"
    col.items[1].colors = ["Pembe"]
    col.items[2].colors = ["siyah", "lacivert", "lila"]
    return col


def _same_results(n=3):
    return {f"S{i}": _resp({"TR": [60 + i, 61, 62]}, demand=65, demand_units=800) for i in range(n)}


def test_color_shares_follow_rule_weights_and_keep_model_total():
    from app.collection import colors as cl
    t = cl.family_table()
    assert t.family("BLACK") == "siyah" and t.family("Off White") == "beyaz" and t.family("Kırmızı") == "kirmizi"
    assert t.family("NAVY BLUE") == "lacivert" and t.family("XYZ-12") == "diger"
    res = summarize(_color_col(), _same_results(), 42.0, whatif=WhatIf(color_min_qty=1))
    s0 = next(i for i in res.items if i.sku == "S0")
    black, pink = s0.colors
    assert black.code == "001" and black.share.basis == "kural varsayımı"
    assert black.share.value > pink.share.value and abs(black.share.value + pink.share.value - 100) < 0.2
    assert black.qty + pink.qty == int(s0.recommended_qty.value)          # model adedi renklere eksiksiz bölünür
    assert res.color_plan and res.color_plan.source == "kural varsayımı" and {"siyah", "pembe", "lacivert", "mor"} == {f.family for f in res.color_plan.families}
    assert sum(f.qty for f in res.color_plan.families) == res.summary.total_qty


def test_color_mix_moves_model_qty_and_can_be_turned_off():
    col = _color_col()
    on = summarize(col, _same_results(), 42.0)
    off = summarize(col, _same_results(), 42.0, whatif=WhatIf(color_mix=False))
    q = lambda r, s: next(i for i in r.items if i.sku == s).recommended_qty.value
    s1 = next(i for i in on.items if i.sku == "S1")
    assert s1.color_mix and s1.color_mix.value < 1                         # yalnız pembe: zayıf renk karışımı
    assert q(on, "S1") < q(off, "S1")
    assert all(i.color_mix is None for i in off.items) and not off.color_plan.mix_effect


def test_color_below_min_qty_is_dropped_and_qty_moves_to_other_colors():
    res = summarize(_color_col(budget=30_000.0), _same_results(), 42.0, whatif=WhatIf(color_min_qty=400))
    s2 = next(i for i in res.items if i.sku == "S2")
    by = {c.color: c for c in s2.colors}
    assert by["lila"].decision == "üretme" and by["lila"].qty == 0
    assert any("minimum 400" in r.text for r in by["lila"].reasons)
    assert sum(c.qty for c in s2.colors) == int(s2.recommended_qty.value)
    assert any(a.kind == "renk" and "lila" in a.text for a in res.summary.actions)
    # kullanıcı rengi elle tutabilir
    kept = summarize(_color_col(budget=30_000.0), _same_results(), 42.0,
                     whatif=WhatIf(color_min_qty=400, color_decisions={"S2::lila": "üret"}))
    lila = next(c for c in next(i for i in kept.items if i.sku == "S2").colors if c.color == "lila")
    assert lila.decision == "üret" and lila.decision_source == "kullanıcı" and lila.qty > 0


def test_color_shares_come_from_erp_when_file_is_given(tmp_path, monkeypatch):
    p = tmp_path / "renk.csv"
    p.write_text("kategori;renk;adet\nElbise;PEMBE;900\nElbise;SİYAH;100\n", encoding="utf-8")
    monkeypatch.setenv("RENK_ERP_DOSYASI", str(p))
    res = summarize(_color_col(), _same_results(), 42.0, whatif=WhatIf(color_min_qty=1))
    s0 = next(i for i in res.items if i.sku == "S0")
    black, pink = s0.colors
    assert black.share.basis == "ERP" and pink.share.value > black.share.value   # geçmişte pembe daha çok satmış
    assert res.color_plan.source == "ERP"


def test_import_keeps_color_image_per_color_row(client):
    data = _xlsx_with_embedded(_erp_rows(), ERP_HEADERS)
    prev = client.post("/api/collections/import", files=[("sheet", ("CardProduct.xlsx", data, "application/octet-stream"))]).json()
    st1 = next(p["item"] for p in prev["items"] if p["item"]["sku"] == "ST1")
    assert set(st1["color_images"]) == {"BLACK", "BROWN"} and st1["color_images"]["BLACK"] != st1["color_images"]["BROWN"]
    cid = prev["collection_id"]
    meta = dict(prev["meta"], total_budget=2_000_000, currency="TRY", target_regions=["TR"], color_min_qty=50)
    client.post(f"/api/collections/{cid}/confirm", json={"meta": meta, "items": [p["item"] for p in prev["items"]]})
    assert client.post(f"/api/collections/{cid}/run", json={"showcase": False}).status_code == 200
    assert not _wait(client, cid)["failed"]
    res = client.get(f"/api/collections/{cid}/result").json()
    st = next(i for i in res["items"] if i["sku"] == "ST1")
    assert [c["color"] for c in st["colors"]] == ["BLACK", "BROWN"] and st["colors"][0]["image"]
    assert res["color_plan"]["min_qty"] == 50 and res["color_plan"]["min_qty_basis"] == "kullanıcı girdisi"
    wb = load_workbook(io.BytesIO(client.get(f"/api/collections/{cid}/export.xlsx").content))
    assert wb["Renkler"]["D2"].value == "BLACK"


# ---------- panel ayırt etmediğinde (herkes aynı puanı verirse) ----------

def _showcase_recs(n, best, worst, persons=24):
    recs = []
    for p in range(persons):
        order = [f"S{(p + i) % n}" for i in range(n)]
        letters = dict(zip("ABCDEFGH", order))
        inv = {v: k for k, v in letters.items()}
        recs.append({"region": "TR", "person": p, "order": order, "letters": letters,
                     "answer": {"best": [inv[best]], "worst": [inv[worst]], "together": [], "substitutes": [], "n_buy": 1, "comment": ""}})
    return {"TR": recs}


def test_flat_scores_do_not_create_fake_risk_and_roles_come_from_showcase():
    col = _col(6)
    # küçük modelde herkes 55 diyor; tek bir kişinin S5'e 50 demesi ürünü "riskli" yapmamalı
    results = {f"S{i}": _resp({"TR": [55] * 12}, demand=55) for i in range(5)}
    results["S5"] = _resp({"TR": [55] * 11 + [50]}, demand=55)
    res = summarize(col, results, 42.0, showcase=_showcase_recs(6, best="S5", worst="S0"))
    by = {i.sku: i for i in res.items}
    assert by["S5"].role != "riskli" and by["S5"].rank.value == 1          # vitrinde en çok seçilen
    assert by["S0"].role == "riskli" and "vitrin turundan" in by["S0"].role_why
    assert not any("vitrinde daha" in f for i in res.items for f in i.flags)   # eşit puanlardan sahte karşılaştırma yok
    assert any("ayırt etmedi" in n and "vitrin turundaki" in n for n in res.notes)


def test_one_deviant_answer_is_not_blown_up_by_normalization():
    col = _col(5)
    results = {f"S{i}": _resp({"TR": [55] * 12}, demand=55) for i in range(4)}
    results["S4"] = _resp({"TR": [55] * 11 + [50]}, demand=55)
    res = summarize(col, results, 42.0)
    assert abs(next(i for i in res.items if i.sku == "S4").relative.value) < 0.1
    assert {i.role for i in res.items} == {"belirsiz"}


def test_single_weak_but_showcase_strong_is_not_risky():
    col = _col(6)
    results = {f"S{i}": _resp({"TR": [70 - 3 * i + (k % 3) for k in range(12)]}, demand=70 - 3 * i) for i in range(6)}
    res = summarize(col, results, 42.0, showcase=_showcase_recs(6, best="S5", worst="S1"))
    s5 = next(i for i in res.items if i.sku == "S5")
    assert s5.role != "riskli" and "çelişiyor" in s5.role_why


def test_no_enthusiast_means_reduce_and_template_objection_is_dropped():
    from app.services.answer_extractor import clean_objection
    assert clean_objection("<en büyük itirazın, tek kısa cümle>") == "" and clean_objection("Asla almam.") == ""
    assert clean_objection("Kumaş ince görünüyor") == "Kumaş ince görünüyor"
    col = _col(3)
    results = {"S0": _resp({"TR": [60, 62, 58, 61, 63, 59]}, demand=60), "S1": _resp({"TR": [80, 75, 90, 72, 70, 85]}, demand=80),
               "S2": _resp({"TR": [40, 45, 42, 41, 44, 43]}, demand=55)}
    res = summarize(col, results, 42.0)
    s0 = next(i for i in res.items if i.sku == "S0")
    assert s0.decision == "azalt" and any("hevesli" in r.text for r in s0.decision_reasons)


def test_identical_price_answers_lower_quality():
    from app.pricing import AgentPriceAnswer as A, analyze
    r, _ = analyze([A(10, 20, 40, 60)] * 11 + [A(12, 22, 44, 70)], 15)
    assert r.quality == "low" and "aynı fiyat" in r.quality_note
