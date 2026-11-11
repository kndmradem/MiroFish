import json
import tarfile
from datetime import date

import httpx
import pytest

from app.contextpacks.bundle import BundleError, build_bundle, generate_keys, import_bundle, verify_bundle
from app.contextpacks.drafter import DraftRequest, OpenAICompatResearcher, build_draft, draft_pack
from app.contextpacks.review import ApprovalError, approve, missing_sources
from app.panel.library import PanelStore

TODAY = date(2026, 11, 1)
SRC = [{"url": "https://data.tuik.gov.tr/bulten", "title": "TÜFE", "published_at": "2026-10-03"}]
RAW = {
    "macro": {"inflation_yoy_pct": 31.5, "consumer_confidence": "Endeks geriledi", "purchasing_power": "Baskı altında",
              "fx_note": ""},
    "season_notes": "Kasım ortalamanın üstünde ılık", "shopping_notes": "Efsane Cuma 20-30 Kasım",
    "field_sources": {"inflation_yoy_pct": SRC, "consumer_confidence": SRC,
                      "season_notes": [{"url": "https://mgm.gov.tr/x", "published_at": "2026-10-25"}],
                      "shopping_notes": [{"url": "not-a-link"}]},
    "trends": [{"note": "Oversize kaban aramaları arttı", "as_of": "2026-10-20",
                "sources": [{"url": "https://trends.example.com/a", "published_at": "2026-10-20"}]},
               {"note": "Uydurma trend", "sources": []}],
    "competitor_prices": [{"item": "Yün karışımlı kaban", "price_usd": 120,
                           "sources": [{"url": "https://rakip.example.com/kaban", "published_at": "2026-02-01"}]}],
}


def test_draft_request_rejects_customer_data():
    with pytest.raises(ValueError):
        DraftRequest(region="TR", as_of=TODAY, categories=["KD25A-0412 maliyet 182 TL"])
    with pytest.raises(ValueError):
        DraftRequest(region="XX", as_of=TODAY)
    assert set(DraftRequest.model_fields) == {"region", "as_of", "categories"}  # müşteri verisi alanı yok


def test_unsourced_facts_are_dropped():
    pack, rep = build_draft(DraftRequest(region="TR", as_of=TODAY), RAW, TODAY)
    assert not pack.verified and pack.macro.inflation_yoy_pct == 31.5
    assert pack.macro.purchasing_power is None  # kaynaksız
    assert pack.shopping_notes == ""            # geçersiz link
    assert [t.note for t in pack.trends] == ["Oversize kaban aramaları arttı"]
    assert pack.competitor_prices[0].sources[0].retrieved_at == TODAY
    assert any("purchasing_power" in d for d in rep.dropped) and any("trends[1]" in d for d in rep.dropped)
    assert rep.old_sources == ["rakip fiyatı: Yün karışımlı kaban"]  # 120 günden eski kaynak işaretlenir
    assert missing_sources(pack) == []


async def test_draft_via_openai_compatible_endpoint():
    seen = {}

    def handler(req):
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "```json\n" + json.dumps(RAW) + "\n```"}}]})

    r = OpenAICompatResearcher("https://cloud.test/v1", "model-x", "k", extra_body={"tools": [{"type": "web_search"}]},
                               client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    pack, _ = await draft_pack(DraftRequest(region="TR", as_of=TODAY), r, TODAY)
    assert seen["body"]["tools"] == [{"type": "web_search"}]
    assert "Türkiye" in seen["body"]["messages"][1]["content"] and pack.trends


def test_approval_requires_sources_and_reviewer():
    pack, _ = build_draft(DraftRequest(region="TR", as_of=TODAY), RAW, TODAY)
    with pytest.raises(ApprovalError):
        approve(pack, " ")
    bad = pack.model_copy(update={"macro": pack.macro.model_copy(update={"fx_note": "kaynaksız not"})})
    with pytest.raises(ApprovalError, match="fx_note"):
        approve(bad, "Adem")
    ok = approve(pack, "Adem", today=TODAY)
    assert ok.verified and ok.approved_by == "Adem" and ok.version == "2026-11-01"


def _approved(region="TR"):
    pack, _ = build_draft(DraftRequest(region=region, as_of=TODAY), RAW, TODAY)
    return approve(pack, "Adem", today=TODAY)


def test_signed_bundle_roundtrip_and_store_sees_only_verified(tmp_path):
    priv, pub = generate_keys()
    out = build_bundle([_approved("TR"), _approved("EU")], priv, tmp_path / "b.tar.gz", "talep-sim")
    root = tmp_path / "data"
    written = import_bundle(out, root, pub)
    assert len(written) == 2
    # aynı klasöre onaysız bir taslak düşse bile üretim kipindeki depo onu görmez
    draft, _ = build_draft(DraftRequest(region="TR", as_of=date(2026, 11, 5)), RAW, TODAY)
    (root / "context" / "TR" / "2026-11-05.json").write_text(draft.model_dump_json())
    assert PanelStore(root, require_verified=True).context("TR", date(2026, 11, 10)).approved_by == "Adem"
    assert not PanelStore(root).context("TR", date(2026, 11, 10)).verified


def test_bundle_rejects_unverified_tampered_or_foreign(tmp_path):
    priv, pub = generate_keys()
    draft, _ = build_draft(DraftRequest(region="TR", as_of=TODAY), RAW, TODAY)
    with pytest.raises(BundleError, match="onaysız"):
        build_bundle([draft], priv, tmp_path / "x.tar.gz", "p")
    out = build_bundle([_approved()], priv, tmp_path / "b.tar.gz", "p")
    _, other_pub = generate_keys()
    with pytest.raises(BundleError, match="İmza"):
        verify_bundle(out, other_pub)
    # içerik değiştirilmiş paket
    with tarfile.open(out) as t:
        members = {m.name: t.extractfile(m).read() for m in t.getmembers()}
    name = next(n for n in members if n.startswith("context/"))
    members[name] = members[name].replace(b"31.5", b"5.0")
    tampered = tmp_path / "t.tar.gz"
    with tarfile.open(tampered, "w:gz") as t:
        import io
        for n, data in members.items():
            info = tarfile.TarInfo(n)
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
    with pytest.raises(BundleError, match="özet"):
        verify_bundle(tampered, pub)
