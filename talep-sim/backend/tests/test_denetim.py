"""Mantık denetimi: kurallar, koşuya bağlanması, regresyon vakaları, ilk veri testi."""
import base64
import copy
import io
import json

import pytest
from fastapi.testclient import TestClient

from app.collection import routes
from app.collection.models import CollectionItem
from app.collection.store import CollectionStore
from app.collection.summary import summarize
from app.denetim import denetle_koleksiyon, denetle_tahmin, denetle_urunler
from app.denetim.vaka import VAKA_DIR, vaka_calistir, vakalar
from app.main import app

from .test_collection import META, ROWS, _col, _resp, _upload, _wait, png, xlsx


def _kurallar(r, seviye=None):
    return {b.kural for b in r.bulgular if seviye is None or b.seviye == seviye}


@pytest.fixture
def temiz():
    """İki kategorili, tutarlı bir koleksiyon sonucu (sözlük)."""
    ans = {"S0": [95, 90, 92, 72, 75, 74, 80, 81, 70, 90, 88, 77], "S1": [94, 91, 90, 71, 76, 73, 79, 83, 72, 91, 86, 75],
           "S2": [80, 80, 80, 30, 30, 30, 50, 55, 60, 40, 45, 50], "S3": [70, 72, 71, 20, 25, 22, 40, 44, 41, 30, 35, 33],
           "S4": [60, 60, 60, 10, 12, 11, 30, 31, 32, 20, 22, 21]}
    res = summarize(_col(), {s: _resp({"TR": a}, demand=d, demand_units=u) for (s, a), d, u in
                             zip(ans.items(), [80, 79, 60, 50, 40], [900, 880, 600, 450, 300])}, 42.0)
    return json.loads(res.model_dump_json())


def test_clean_result_has_no_errors(temiz):
    r = denetle_koleksiyon(temiz)
    assert r.sayilar["hata"] == 0, [b.mesaj for b in r.bulgular]
    assert "kategori_disi_eslesme" in r.kurallar and "etiketsiz_sayi" in r.kurallar


def test_summarize_attaches_audit_and_whatif_reaudits():
    res = summarize(_col(), {f"S{i}": _resp({"TR": [60 + i] * 12}) for i in range(5)}, 42.0)
    assert res.denetim is not None and res.denetim.kapsam == "koleksiyon"


def test_cross_category_pair_is_error(temiz):
    d = copy.deepcopy(temiz)
    d["summary"]["cannibal_pairs"] = [{"a": "S0", "b": "S3", "category": "Elbise", "overlap_pct": 25.0, "why": "", "source": "vitrin",
                                       "basis": "ajan", "shared": 3, "base": 12, "panel_n": 12}]
    r = denetle_koleksiyon(d)
    assert r.durum == "incelenmeli" and "kategori_disi_eslesme" in _kurallar(r, "hata")
    b = next(b for b in r.bulgular if b.kural == "kategori_disi_eslesme")
    assert set(b.skus) == {"S0", "S3"} and "Elbise" in b.mesaj and "Gömlek" in b.mesaj


def test_category_spelling_does_not_count_as_different(temiz):
    d = copy.deepcopy(temiz)
    for it in d["items"]:
        if it["sku"] == "S1":
            it["category"] = " elbıse "          # büyük/küçük harf, Türkçe karakter, boşluk farkı
    d["summary"]["cannibal_pairs"] = [{"a": "S0", "b": "S1", "category": "Elbise", "overlap_pct": 80.0, "why": "", "shared": 8,
                                       "base": 10, "panel_n": 12}]
    assert "kategori_disi_eslesme" not in _kurallar(denetle_koleksiyon(d))


def test_small_sample_percentages(temiz):
    d = copy.deepcopy(temiz)
    d["summary"]["cannibal_pairs"] = [{"a": "S0", "b": "S1", "category": "Elbise", "overlap_pct": 100.0, "why": "", "shared": 3, "base": 3, "panel_n": 12},
                                      {"a": "S0", "b": "S2", "category": "Elbise", "overlap_pct": 100.0, "why": "", "shared": 2, "base": 2, "panel_n": 12},
                                      {"a": "S1", "b": "S2", "category": "Elbise", "overlap_pct": 70.0, "why": ""}]
    r = denetle_koleksiyon(d)
    msgs = [(b.seviye, b.mesaj) for b in r.bulgular if b.kural == "kucuk_orneklem"]
    assert any(s == "uyarı" and "3/3" in m for s, m in msgs)
    assert any(s == "hata" and "2 kişiye" in m for s, m in msgs)
    assert any(s == "uyarı" and "kaç kişiye" in m for s, m in msgs)


def test_price_below_cost_and_negative_margin_on_produce(temiz):
    d = copy.deepcopy(temiz)
    it = d["items"][0]
    it["recommended_price"]["value"] = it["unit_cost_usd"] * 0.8
    it["net_margin"]["value"] = -12.0
    it["decision"] = "üret"
    r = denetle_koleksiyon(d)
    m = [b.mesaj for b in r.bulgular if b.kural == "fiyat_maliyet" and b.seviye == "hata"]
    assert any("birim maliyetin" in x for x in m) and any("negatif" in x for x in m)


def test_reversed_price_range_is_error(temiz):
    d = copy.deepcopy(temiz)
    reg = d["items"][1]["regions"][0]
    reg["range_low"], reg["range_high"] = reg["range_high"], reg["range_low"] * 0.5
    assert "fiyat_maliyet" in _kurallar(denetle_koleksiyon(d), "hata")


def test_totals_region_sum_budget_and_dont_produce(temiz):
    d = copy.deepcopy(temiz)
    a, b = d["items"][0], d["items"][4]
    a["qty_by_region"] = {"TR": int(a["recommended_qty"]["value"]) + 50}
    b["decision"], b["recommended_qty"]["value"] = "üretme", 40
    d["summary"]["budget_used_usd"] = d["summary"]["budget_total_usd"] * 1.2
    r = denetle_koleksiyon(d)
    m = " | ".join(x.mesaj for x in r.bulgular if x.kural == "toplam_tutarlilik" and x.seviye == "hata")
    assert "bölge adetleri" in m and "'üretme'" in m and "aşıyor" in m


def test_rank_contradicting_score_and_pricier_weaker_item_with_more_qty(temiz):
    d = copy.deepcopy(temiz)
    by = {i["sku"]: i for i in d["items"]}
    by["S0"]["rank"]["value"], by["S4"]["rank"]["value"] = by["S4"]["rank"]["value"], by["S0"]["rank"]["value"]
    r = denetle_koleksiyon(d)
    assert "siralama" in _kurallar(r, "hata")
    d = copy.deepcopy(temiz)
    by = {i["sku"]: i for i in d["items"]}
    # aynı kategori (Gömlek): S4 daha pahalı ve daha az ilgi görüyor ama daha çok adet
    by["S4"]["recommended_price"]["value"] = by["S3"]["recommended_price"]["value"] * 1.5
    by["S4"]["appeal"]["value"] = by["S3"]["appeal"]["value"] - 15
    by["S4"]["recommended_qty"]["value"] = (by["S3"]["recommended_qty"]["value"] or 10) * 2
    r = denetle_koleksiyon(d)
    assert any(b.kural == "siralama" and "daha pahalı" in b.mesaj for b in r.bulgular)


def test_nan_negative_and_out_of_range(temiz):
    d = copy.deepcopy(temiz)
    d["items"][0]["regions"][0]["demand"] = 140
    d["items"][1]["enthusiast_pct"]["value"] = float("nan")
    d["items"][2]["regions"][0]["demand_units"] = -5
    r = denetle_koleksiyon(d)
    m = " | ".join(b.mesaj for b in r.bulgular if b.kural == "bos_uc_deger")
    assert "NaN" in m and "negatif" in m and "0-100" in m


def test_unlabeled_number(temiz):
    d = copy.deepcopy(temiz)
    d["items"][0]["appeal"].pop("basis")
    d["summary"]["actions"].append({"kind": "fiyat", "text": "Fiyatı %20 artırın", "skus": [], "basis": ""})
    r = denetle_koleksiyon(d)
    assert "etiketsiz_sayi" in _kurallar(r, "hata")


def test_existing_trust_check_surfaces_as_warning():
    costs = [10.0, 20.0, 5.0, 8.0, 12.0]
    col = _col()
    for it, c in zip(col.items, costs):
        it.unit_cost, it.planned_price = c, None
    res = summarize(col, {it.sku: _resp({"TR": [60 + i] * 12}, price=c * 2.45, demand_units=394)
                          for i, (it, c) in enumerate(zip(col.items, costs))}, 42.0)
    assert "panel_ayirt_etmedi" in _kurallar(res.denetim, "uyarı")


def test_failed_items():
    col = _col()
    results = {f"S{i}": _resp({"TR": [60 + i] * 12}) for i in range(2)}
    results.update({f"S{i}": {"error": "zaman aşımı"} for i in range(2, 5)})
    assert "eksik_sonuc" in _kurallar(summarize(col, results, 42.0).denetim, "hata")


# ---------- tekli tahmin ----------

def _tekli():
    c = TestClient(app)
    body = {"product_name": "Yün kaban", "image_base64": base64.b64encode(png()).decode(), "technical_specs": "yün",
            "unit_cost": 25.5, "total_production_budget": 100000, "target_regions": ["EU", "TR"]}
    return c.post("/api/predict", json=body).json()


def test_single_prediction_is_audited_and_clean():
    r = _tekli()
    assert r["denetim"]["durum"] in ("temiz", "uyarılı") and r["denetim"]["sayilar"]["hata"] == 0, r["denetim"]


def test_single_prediction_rules():
    r = _tekli()
    d = copy.deepcopy(r)
    d["total_produced_qty"] += 100
    d["regional_breakdown"][0]["optimal_sale_price"] = 10.0
    d["regional_breakdown"][1]["raw_answers"] = [{"agent": 1, "status": "json", "interest": 80}]
    f = d["regional_breakdown"][0]["forecast"]
    if f.get("milestones") and len(f["milestones"]) > 1:
        f["milestones"][1]["units"] = -1
    out = denetle_tahmin(d, unit_cost=25.5, budget=100000)
    assert {"toplam_tutarlilik", "fiyat_maliyet", "kucuk_orneklem"} <= _kurallar(out, "hata")


# ---------- müşteri ürün listesi ----------

def test_product_list_rules():
    items = [CollectionItem(sku="A", name="a", category="Sütyen", unit_cost=10), CollectionItem(sku="A", name="a2", category="SUTYEN", unit_cost=11),
             CollectionItem(sku="B", name="b", category="Sütyen", unit_cost=0), CollectionItem(sku="C", name="c", category="", unit_cost=9),
             CollectionItem(sku="D", name="d", category="Sütyen", unit_cost=12), CollectionItem(sku="E", name="e", category="Sütyen", unit_cost=300)]
    r = denetle_urunler(items)
    m = " | ".join(b.mesaj for b in r.bulgular)
    assert r.durum == "incelenmeli"
    assert "birden fazla" in m and "maliyet boş" in m and "kategori boş" in m and "farklı yazılmış" in m and "medyanının" in m


# ---------- regresyon vakaları ----------

VAKALAR = vakalar()


def test_there_are_regression_cases():
    assert any(ad.startswith("bralet-slip") for ad, _ in VAKALAR)


@pytest.mark.parametrize("ad,vaka", VAKALAR, ids=[a for a, _ in VAKALAR])
def test_regression_case(ad, vaka):
    sorun = vaka_calistir(vaka)
    if vaka.get("durum") == "acik":
        acik = [s for s in sorun if s.startswith("[bugünkü kod]")]
        sorun = [s for s in sorun if not s.startswith("[bugünkü kod]")]
        assert not sorun, sorun
        if acik:
            pytest.xfail("açık vaka, kod henüz düzeltilmedi: " + "; ".join(acik))
    assert not sorun, sorun


def test_add_case_is_one_step(tmp_path):
    """vaka-ekle: kayıtlı koleksiyondan anonim vaka üretir; denetim yakaladıysa test kendiliğinden geçer."""
    from app.collection.models import Collection, CollectionMeta
    from app.denetim.vaka import vaka_ekle
    st = CollectionStore(str(tmp_path / "cols"))
    col = _col()
    col.meta.brand = "GizliMarka"
    for it in col.items:
        it.name = f"Gizli ürün {it.sku}"
    st.save(col)
    for i, it in enumerate(col.items):
        st.save_result(col.id, it.sku, _resp({"TR": [60 + i] * 3}))       # 3 kişilik panel: az kişi uyarısı
    yol, rapor, eksik = vaka_ekle(st, col.id, "Deneme vaka", "test", 42.0, [], klasor=tmp_path / "v")
    v = json.loads(yol.read_text(encoding="utf-8"))
    assert yol.name == "deneme-vaka.json" and not eksik
    assert "Gizli" not in yol.read_text(encoding="utf-8")
    assert v["sonuc_beklenen"] and vaka_calistir(v) == []


# ---------- API ve ilk veri testi ----------

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(routes, "_store", CollectionStore(str(tmp_path / "cols")))
    with TestClient(app) as c:
        yield c


def test_api_collection_result_carries_audit_and_report(client):
    prev = _upload(client).json()
    cid = prev["collection_id"]
    client.post(f"/api/collections/{cid}/confirm", json={"meta": prev["meta"], "items": [p["item"] for p in prev["items"]]})
    client.post(f"/api/collections/{cid}/run", json={})
    _wait(client, cid)
    res = client.get(f"/api/collections/{cid}/result").json()
    assert res["denetim"]["durum"] in ("temiz", "uyarılı", "incelenmeli") and res["denetim"]["sayilar"]["hata"] == 0
    assert "Mantık denetimi" in client.get(f"/api/denetim/koleksiyon/{cid}?bicim=md").text
    assert client.get(f"/api/denetim/koleksiyon/{cid}?bicim=html").text.startswith("<!doctype html>")
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(client.get(f"/api/collections/{cid}/export.xlsx").content))
    assert "Denetim" in wb.sheetnames
    assert len(client.get("/api/denetim/kurallar").json()) >= 9


def test_api_first_data_test_with_mock_engine(client):
    rows = ROWS + [["SW27-001", "Tekrar", "Elbise", "", 0, None, None, None, None]]
    files = [("sheet", ("liste.xlsx", xlsx(rows, META), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))]
    r = client.post("/api/denetim/ilk-test", files=files, data={"motor": "mock", "ornek": "3"})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["genel"]["durum"] == "incelenmeli"                    # tekrarlayan SKU ve sıfır maliyet
    assert [p["ad"] for p in j["parcalar"]] == ["Ürün listesi", "Örnek koşu sonucu"]
    assert "yer tutucu" in j["not"] and j["md"].startswith("# İlk veri testi")
