"""Zep'siz kişi listesi: /api/graph/local ile verilen kişiler simülasyon hazırlığında varlık olarak okunur."""
from app import create_app
from app.config import Config
from app.models.project import ProjectManager, ProjectStatus
from app.services.local_people import apply_attributes, is_local
from app.services.zep_entity_reader import ZepEntityReader

PEOPLE = [
    {"name": "Ayşe Polat", "type": "Person", "summary": "Ayşe Polat, 34, İstanbul, kadın",
     "attributes": {"age": 34, "gender": "female", "country": "Türkiye", "profession": "beyaz yaka"}},
    {"name": "Mehmet Kaya", "type": "Person", "summary": "Mehmet Kaya, 41, Ankara, erkek; baba",
     "attributes": {"age": 41, "gender": "male", "country": "Türkiye", "profession": "esnaf"}},
]


def _client(tmp_path, monkeypatch):
    monkeypatch.setattr(ProjectManager, "PROJECTS_DIR", str(tmp_path))
    monkeypatch.setattr(Config, "ZEP_API_KEY", None)        # Zep anahtarı olmadan çalışmalı
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def test_local_project_is_ready_without_zep(tmp_path, monkeypatch):
    r = _client(tmp_path, monkeypatch).post("/api/graph/local", json={
        "project_name": "talep", "simulation_requirement": "Tüketiciler ürünü değerlendirir.", "people": PEOPLE})
    assert r.status_code == 200, r.json
    pid, gid = r.json["data"]["project_id"], r.json["data"]["graph_id"]
    project = ProjectManager.get_project(pid)
    assert project.status == ProjectStatus.GRAPH_COMPLETED and project.graph_id == gid and is_local(gid)

    filtered = ZepEntityReader().filter_defined_entities(graph_id=gid, defined_entity_types=["Person"])
    assert [e.name for e in filtered.entities] == ["Ayşe Polat", "Mehmet Kaya"]
    assert filtered.entities[0].attributes["gender"] == "female"


def test_local_project_rejects_bad_input(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    assert c.post("/api/graph/local", json={"simulation_requirement": "x", "people": []}).status_code == 400
    dup = c.post("/api/graph/local", json={"simulation_requirement": "x", "people": [PEOPLE[0], PEOPLE[0]]})
    assert dup.status_code == 400 and "benzersiz" in dup.json["error"]


def test_given_attributes_override_llm_profile():
    out = apply_attributes({"age": 25, "gender": "male", "country": "China", "mbti": "INTJ"},
                           {"age": "34", "gender": "female", "country": "Türkiye", "region": "TR"})
    assert out == {"age": 34, "gender": "female", "country": "Türkiye", "mbti": "INTJ"}
